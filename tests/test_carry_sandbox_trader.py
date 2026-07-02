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
