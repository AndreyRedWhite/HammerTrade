from types import SimpleNamespace

import scripts.run_volatility_breakout_sandbox_trader as vb


def test_fill_points_uses_contract_point_value():
    assert vb.fill_points(45510, 2, 10) == 2275.5
    assert vb.fill_points(152800, 2, 1) == 76400


def test_fill_points_rejects_invalid_denominator():
    assert vb.fill_points(None, 2, 1) is None
    assert vb.fill_points(1, 0, 1) is None


def test_breakout_db_dashboard_shape(tmp_path):
    db = vb.BreakoutDB(str(tmp_path / "v.sqlite"))
    db.upsert({
        "trade_id": "t", "ticker": "IMOEXF", "direction": "LONG", "status": "CLOSED",
        "exit_ts": "2026-01-01T00:00:00+00:00", "net_pnl_rub": 123.0,
    })
    row = db.con.execute(
        "SELECT direction, net_pnl_rub AS pnl, exit_ts AS ets, status "
        "FROM volatility_breakout_trades"
    ).fetchone()
    assert row["pnl"] == 123.0
