"""Fill-unit normalization: API executed_order_price is a TOTAL, journal is per-share.

Covers the 2026-07-02 bug where run_pairs_sandbox_trader stored the total and
multiplied by qty again in PnL (RTKM pair showed +56k instead of ~+59 ₽ gross).
"""
import logging
from types import SimpleNamespace

import scripts.run_pairs_sandbox_trader as pt
import scripts.run_orb_sandbox_trader as orb
from scripts.fix_pairs_fill_units_20260702 import recompute

LOG = logging.getLogger("test")


class FakeBroker:
    def __init__(self, responses):
        self._responses = list(responses)
        self.orders = []

    def post_order(self, **kw):
        self.orders.append(kw)
        return self._responses.pop(0)

    def get_order_state(self, account_id, order_id):
        return self._responses.pop(0)

    def cancel_order(self, account_id, order_id):
        pass


def _resp(lots_executed, total, comm=1.0, order_id="o1", status="FILL"):
    return SimpleNamespace(order_id=order_id, lots_executed=lots_executed,
                           executed_price=total, commission_rub=comm, status=status)


def test_per_share_normalizes_total():
    # 45 lots × 10 shares @ 44.75 → API total 20137.5
    assert pt._per_share(20137.5, 45, 10) == 44.75
    assert pt._per_share(None, 45, 10) is None
    assert pt._per_share(20137.5, 0, 10) is None


def test_place_market_returns_per_share_price():
    broker = FakeBroker([_resp(45, 20137.5)])
    px, comm, filled = pt._place(broker, "acc", "uid", 45, "BUY", False, LOG, "t", lot=10)
    assert px == 44.75
    assert filled == 45


def test_place_limit_market_fallback_combines_totals():
    # LIMIT fills 2 of 5 lots (total 895 = 44.75×2×10), fallback MARKET fills
    # 3 lots (total 1350 = 45.0×3×10) → avg per-share (895+1350)/50 = 44.9
    broker = FakeBroker([
        _resp(2, 895.0, comm=0.5),          # post LIMIT
        _resp(2, 895.0, comm=0.5),          # get_order_state (still 2)
        _resp(3, 1350.0, comm=0.7),         # fallback MARKET
    ])
    px, comm, filled = pt._place(broker, "acc", "uid", 5, "BUY", False, LOG, "t",
                                 lot=10, order_type="limit", limit_price=44.8,
                                 timeout_sec=0.01, poll_sec=0.01, force_fill=True)
    assert filled == 5
    assert px == (895.0 + 1350.0) / (5 * 10)
    assert comm == 1.2


def test_orb_order_returns_per_contract_price():
    broker = FakeBroker([_resp(2, 152800.0)])
    px, comm = orb._order(broker, "acc", "uid", 2, "SELL", False, LOG, "t")
    assert px == 76400.0


def test_migration_recomputes_real_rtkm_trade():
    # trade 2 from the live DB: recorded gross +26770, reality +59 gross
    row = dict(trade_id="x", status="CLOSED", direction="SHORT_SPREAD",
               pref_qty=440, ord_qty=450,
               pref_entry_fill=19866.0, ord_entry_fill=19818.0,
               pref_exit_fill=19888.0, ord_exit_fill=19899.0,
               commission_rub=39.7355, gross_pnl_rub=26770.0, net_pnl_rub=26730.26)
    new = recompute(row)
    assert new["pref_entry_fill"] == 19866.0 / 440
    assert abs(new["gross_pnl_rub"] - 59.0) < 0.5
    assert abs(new["net_pnl_rub"] - (new["gross_pnl_rub"] - 39.7355)) < 0.01


def test_migration_converts_open_trade_entry_only():
    row = dict(trade_id="y", status="OPEN", direction="LONG_SPREAD",
               pref_qty=100, ord_qty=110,
               pref_entry_fill=4475.0, ord_entry_fill=4829.0,
               pref_exit_fill=None, ord_exit_fill=None,
               commission_rub=5.0, gross_pnl_rub=None, net_pnl_rub=None)
    new = recompute(row)
    assert new["pref_entry_fill"] == 44.75
    assert new["ord_entry_fill"] == 43.9
    assert new["pref_exit_fill"] is None
    assert new["gross_pnl_rub"] is None
