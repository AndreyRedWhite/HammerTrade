"""Pure-math tests for the perp funding-carry sandbox trader."""
from datetime import datetime, timedelta, timezone

import scripts.run_carry_sandbox_trader as ct

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


def test_funding_ma_bp_basic():
    # 20 days of 2.0 pts funding on a 2300-pt perp → 2/2300*1e4 ≈ 8.7 bp
    fma = ct.funding_ma_bp([2.0] * 20, 2300.0, 20)
    assert abs(fma - 8.6957) < 0.01


def test_funding_ma_bp_insufficient_history():
    assert ct.funding_ma_bp([2.0] * 5, 2300.0, 20) is None
    assert ct.funding_ma_bp([2.0] * 10, 2300.0, 20) is not None  # ≥ n/2 ok


def test_expected_carry_subtracts_basis_decay():
    # funding 8 bp/d, basis 1% (100 bp) over 50 dte → decay 2 bp/d → carry 6
    carry = ct.expected_carry_bp(8.0, 2300.0, 2323.0, 50)
    assert abs(carry - 6.0) < 0.01


def test_required_daily_carry_has_cost_margin():
    # 10bp full cycle, require 2x cover over a conservative 10-day hold.
    assert ct.required_daily_carry(10, 10, 2) == 2.0


def test_required_daily_carry_rejects_invalid_horizon():
    import pytest
    with pytest.raises(ValueError):
        ct.required_daily_carry(10, 0, 2)


def test_pick_front_respects_min_dte():
    contracts = [
        {"ticker": "MMU6", "expiry": NOW + timedelta(days=5)},
        {"ticker": "MMZ6", "expiry": NOW + timedelta(days=96)},
    ]
    front = ct.pick_front(contracts, NOW, min_dte=10)
    assert front["ticker"] == "MMZ6"
    front = ct.pick_front(contracts, NOW, min_dte=3)
    assert front["ticker"] == "MMU6"
    assert ct.pick_front(contracts[:1], NOW, min_dte=10) is None


def test_leg_lots_matches_notionals():
    # IMOEXF 2275.5 pts × 10 ₽/pt ≈ 22 755 ₽; MMU6 2260.8 × 10 ≈ 22 608 ₽
    perp_lots, q_lots = ct.leg_lots(45000.0, 2275.5, 10.0, 2260.8, 10.0)
    assert perp_lots == 2 and q_lots == 2
    # gold 1:1 (both pv=1, ~10k ₽)
    perp_lots, q_lots = ct.leg_lots(20000.0, 10075.6, 1.0, 10322.8, 1.0)
    assert perp_lots == 2 and q_lots == 2


def test_fill_points_normalizes_total_rub():
    # 2 lots IMOEXF (pv=10) executed for TOTAL 45 510 ₽ → 2275.5 pts
    assert ct.fill_points(45510.0, 2, 10.0) == 2275.5
    assert ct.fill_points(None, 2, 10.0) is None
    assert ct.fill_points(45510.0, 0, 10.0) is None


def test_funding_rub_short_receives_positive():
    # swaprate 2.07 pts × pv 10 × 2 lots = 41.4 ₽/day received by the short
    assert abs(ct.funding_rub(2.07, 2, 10.0) - 41.4) < 1e-9


def test_carry_db_funding_ledger_dedup(tmp_path):
    db = ct.CarryDB(str(tmp_path / "c.sqlite"))
    assert db.add_funding("IMOEXF", "2026-07-01", 2.0, 2, 40.0) is True
    assert db.add_funding("IMOEXF", "2026-07-01", 2.0, 2, 40.0) is False  # same date
    assert db.add_funding("IMOEXF", "2026-07-02", 1.5, 2, 30.0) is True
    assert db.funding_total() == 70.0
    assert db.last_funding_date("IMOEXF") == "2026-07-02"


def test_carry_db_funding_attributed_to_trade(tmp_path):
    db = ct.CarryDB(str(tmp_path / "c.sqlite"))
    db.upsert_trade(dict(trade_id="t1", asset="IMOEXF", status="OPEN",
                         direction="NEUTRAL", funding_rub=0.0))
    assert db.add_funding("IMOEXF", "2026-07-01", 2.0, 2, 40.0, trade_id="t1") is True
    assert db.add_funding("IMOEXF", "2026-07-02", 1.5, 2, 30.0, trade_id="t1") is True
    # duplicate date must not double-attribute
    assert db.add_funding("IMOEXF", "2026-07-02", 1.5, 2, 30.0, trade_id="t1") is False
    t = db.open_trade("IMOEXF")
    assert t["funding_rub"] == 70.0


def test_dashboard_query_shape_matches_fleet(tmp_path):
    """fleet.py reads SELECT direction, net_pnl_rub, exit_ts, status FROM carry_trades."""
    db = ct.CarryDB(str(tmp_path / "c.sqlite"))
    db.upsert_trade(dict(trade_id="t1", asset="IMOEXF", status="CLOSED",
                         direction="NEUTRAL", net_pnl_rub=55.0,
                         exit_ts="2026-07-02T12:00:00+00:00"))
    rows = db.con.execute(
        "SELECT direction, net_pnl_rub AS pnl, exit_ts AS ets, status FROM carry_trades"
    ).fetchall()
    assert rows[0]["pnl"] == 55.0 and rows[0]["direction"] == "NEUTRAL"


# ─── The phantom close: an exit must be confirmed by the ACCOUNT ─────────────

class _FakeBroker:
    """Minimal broker double. `positions` is {uid: signed balance}."""

    def __init__(self, positions, fill_lots=None, fill_total_rub=None):
        self._positions = dict(positions)
        self._fill_lots = fill_lots
        self._fill_total_rub = fill_total_rub

    def get_positions(self, account_id):
        class _P:
            def __init__(self, uid, bal):
                self.instrument_uid = uid
                self.figi = uid
                self.balance = bal
        return [_P(u, b) for u, b in self._positions.items()]

    def post_order(self, **kw):
        class _R:
            pass
        r = _R()
        r.order_id = "fake"
        r.status = "EXECUTION_REPORT_STATUS_FILL"
        r.lots_executed = self._fill_lots if self._fill_lots is not None else kw["quantity_lots"]
        r.executed_price = self._fill_total_rub
        r.commission_rub = 0.0
        return r


def _open_trade_row():
    return {
        "trade_id": "sbcarry:GLDRUBF:t0", "asset": "GLDRUBF", "status": "OPEN",
        "perp_ticker": "GLDRUBF", "q_ticker": "GLZ6",
        "perp_lots": 2, "q_lots": 2, "perp_pv": 1.0, "q_pv": 1.0,
        "perp_entry_pts": 12000.0, "q_entry_pts": 12500.0,
        "commission_rub": 0.0, "funding_rub": 0.0,
    }


def test_verify_flat_reports_remaining_legs():
    broker = _FakeBroker({"uid-perp": -2, "uid-q": 0})
    flat, held = ct._verify_flat(broker, "acct", {"uid-perp", "uid-q"}, dry_run=False)
    assert flat is False
    assert held == {"uid-perp": -2}


def test_verify_flat_true_when_account_is_empty():
    broker = _FakeBroker({"uid-perp": 0, "uid-q": 0})
    flat, held = ct._verify_flat(broker, "acct", {"uid-perp", "uid-q"}, dry_run=False)
    assert flat is True and held == {}


def test_close_refuses_when_the_broker_still_holds_a_leg(tmp_path, caplog):
    """THE bug: a zero-lot exit used to book a bar-price PnL and write CLOSED.

    Here the orders report fills but the ACCOUNT still shows the perp leg, so the
    close must be refused, the trade left OPEN and trading paused.
    """
    db = ct.CarryDB(str(tmp_path / "c.sqlite"))
    t = _open_trade_row()
    db.upsert_trade(dict(t, direction="NEUTRAL", entry_ts="2026-09-07T10:00:00+00:00",
                         created_at="x", updated_at="x"))
    broker = _FakeBroker({"uid-perp": -2, "uid-q": 0}, fill_total_rub=24000.0)

    import logging
    logger = logging.getLogger("t1")
    out = ct._close_construction(
        broker, "acct", db, logger, False, t=t,
        perp_uid="uid-perp", q_uid="uid-q",
        perp_px=12000.0, q_px=12500.0, carry_bp=0.0,
        ts="2026-09-07T12:00:00+00:00", reason="CARRY_FLIP")

    assert out is None                                    # no close reported
    assert db.open_trade("GLDRUBF") is not None           # still open
    assert db.daily(ct._today_msk())["paused"] == 1       # entries blocked
    db.con.close()


def test_close_succeeds_when_the_account_is_confirmed_flat(tmp_path):
    db = ct.CarryDB(str(tmp_path / "c.sqlite"))
    t = _open_trade_row()
    db.upsert_trade(dict(t, direction="NEUTRAL", entry_ts="2026-09-07T10:00:00+00:00",
                         created_at="x", updated_at="x"))
    # 2 lots at 11900 and 12450 -> executed_order_price is the TOTAL in RUB.
    broker = _FakeBroker({"uid-perp": 0, "uid-q": 0}, fill_total_rub=23800.0)

    import logging
    out = ct._close_construction(
        broker, "acct", db, logging.getLogger("t2"), False, t=t,
        perp_uid="uid-perp", q_uid="uid-q",
        perp_px=12000.0, q_px=12500.0, carry_bp=0.0,
        ts="2026-09-07T12:00:00+00:00", reason="CARRY_FLIP")

    assert out is not None
    assert out["status"] == "CLOSED"
    assert db.daily(ct._today_msk())["paused"] == 0
    db.con.close()


# ─── Contractual cashflows we know we cannot observe ─────────────────────────

def test_index_perpetual_declares_its_missing_dividend_adjustment():
    """IMOEXF debits IndexDiv from the short leg; ISS history has no such column."""
    assert ct._missing_cashflows("IMOEXF:MM") == ["IMOEXF:INDEX_DIV"]


def test_gold_has_no_dividend_adjustment():
    """The verdict is instrument-specific: gold pays no dividend."""
    assert ct._missing_cashflows("GLDRUBF:GL") == []


def test_mixed_legs_report_only_the_affected_instrument():
    assert ct._missing_cashflows("IMOEXF:MM,GLDRUBF:GL") == ["IMOEXF:INDEX_DIV"]
