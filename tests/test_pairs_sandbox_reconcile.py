"""Reconcile self-heal + replay-on-gap guard for the pairs sandbox trader.

Covers the two coupled defects found 2026-07-20:
  * reconcile only HALTed on a mismatch and never healed → TATN froze a week on a
    stray naked leg (TATNP +44) while the journal said flat.
  * clearing the HALT then replayed a week of hourly bars as fresh market orders,
    because `new_bars` = everything since a stale `last_bar`.
"""
import logging
from types import SimpleNamespace

import pandas as pd

import scripts.run_pairs_sandbox_trader as pt

LOG = logging.getLogger("test")

PREF = {"uid": "PREFUID-1234", "figi": "PREFFIGI", "lot": 1}
ORD = {"uid": "ORDUID-5678", "figi": "ORDFIGI", "lot": 1}


def _pos(uid, balance, figi=None):
    return SimpleNamespace(instrument_uid=uid, figi=figi, balance=balance)


class FakeBroker:
    def __init__(self, positions):
        self._positions = positions
        self.orders = []

    def get_positions(self, account_id):
        return list(self._positions)

    def post_order(self, **kw):
        self.orders.append(kw)
        return SimpleNamespace(order_id="o", lots_executed=kw["quantity_lots"],
                               executed_price=1.0, commission_rub=0.1, status="FILL")


class FakeDB:
    def __init__(self):
        self.events = []

    def event(self, pair, kind, message):
        self.events.append((pair, kind, message))


def _bars(n):
    ts = pd.date_range("2026-07-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "z": range(n)})


# ── Fix 1: replay-on-gap guard ────────────────────────────────────────────────
def test_resume_live_bars_passthrough_within_budget():
    bars = _bars(3)
    out, skipped = pt._resume_live_bars(bars, max_backfill=5)
    assert skipped == 0
    assert len(out) == 3


def test_resume_live_bars_caps_large_gap_to_latest():
    bars = _bars(70)   # a week of hourly bars, as when TATN unfroze
    out, skipped = pt._resume_live_bars(bars, max_backfill=5)
    assert skipped == 69
    assert len(out) == 1
    # keeps the MOST RECENT bar, not an old one
    assert out.iloc[0]["timestamp"] == bars.iloc[-1]["timestamp"]


def test_resume_live_bars_exactly_at_budget_not_capped():
    out, skipped = pt._resume_live_bars(_bars(5), max_backfill=5)
    assert skipped == 0
    assert len(out) == 5


# ── Fix 2: reconcile returns structured mismatches ────────────────────────────
def test_reconcile_ok_when_flat_and_account_flat():
    broker = FakeBroker([])
    ok, detail, mism = pt._reconcile(broker, "acc", None, PREF, ORD, 1, 1)
    assert ok and mism == [] and detail == ""


def test_reconcile_reports_stray_with_lot():
    broker = FakeBroker([_pos(PREF["uid"], 44)])
    ok, detail, mism = pt._reconcile(broker, "acc", None, PREF, ORD, 1, 1)
    assert not ok
    assert (PREF["uid"], 1, 0, 44) in mism
    assert "act_lots=44" in detail


# ── Fix 2: self-heal vs halt ──────────────────────────────────────────────────
def test_selfheal_flattens_journal_flat_stray():
    # journal flat, account holds +44 pref (lot 1) → auto-SELL 44, resume next cycle
    broker = FakeBroker([_pos(PREF["uid"], 44)])
    db = FakeDB()
    status, detail = pt._reconcile_or_heal(broker, "acc", None, PREF, ORD,
                                           dry_run=False, logger=LOG, db=db, pair="TATN")
    assert status == "SELF_HEALED"
    assert len(broker.orders) == 1
    o = broker.orders[0]
    assert o["direction"] == "SELL" and o["quantity_lots"] == 44
    assert any(k == "RECONCILE_SELFHEAL" for _, k, _ in db.events)


def test_selfheal_covers_short_stray():
    # account holds -470 pref on lot 10 → BUY 47 lots to cover
    pref10 = {"uid": "P10", "figi": "PF10", "lot": 10}
    broker = FakeBroker([_pos(pref10["uid"], -470)])
    db = FakeDB()
    status, _ = pt._reconcile_or_heal(broker, "acc", None, pref10, ORD,
                                      dry_run=False, logger=LOG, db=db, pair="RTKM")
    assert status == "SELF_HEALED"
    o = broker.orders[0]
    assert o["direction"] == "BUY" and o["quantity_lots"] == 47


def test_halt_when_open_position_desynced():
    # journal has an OPEN trade → a mismatch is a live-position desync, NOT auto-flattened
    open_t = {"status": "OPEN", "direction": "LONG_SPREAD", "pref_qty": 44, "ord_qty": 42}
    broker = FakeBroker([_pos(PREF["uid"], 44)])   # ord leg missing → mismatch
    db = FakeDB()
    status, _ = pt._reconcile_or_heal(broker, "acc", open_t, PREF, ORD,
                                      dry_run=False, logger=LOG, db=db, pair="TATN")
    assert status == "RECONCILE_FAILED"
    assert broker.orders == []
    assert any(k == "RECONCILE_FAIL" for _, k, _ in db.events)


def test_halt_when_stray_not_lot_divisible():
    # 45 shares on a lot-10 instrument cannot be cleanly flattened → HALT, no orders
    pref10 = {"uid": "P10", "figi": "PF10", "lot": 10}
    broker = FakeBroker([_pos(pref10["uid"], 45)])
    db = FakeDB()
    status, _ = pt._reconcile_or_heal(broker, "acc", None, pref10, ORD,
                                      dry_run=False, logger=LOG, db=db, pair="RTKM")
    assert status == "RECONCILE_FAILED"
    assert broker.orders == []
