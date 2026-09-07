import pandas as pd
import pytest
from datetime import date

import scripts.run_xsec_momentum_sandbox_trader as xs


def test_momentum_score_skips_recent_month():
    close = pd.Series(range(100, 250))
    expected = close.iloc[-22] / close.iloc[-127] - 1
    assert xs.momentum_score(close, 126, 21) == pytest.approx(expected)


def test_momentum_score_needs_history():
    assert xs.momentum_score(pd.Series([1, 2, 3]), 126, 21) is None


def test_select_basket_has_no_overlap():
    longs, shorts = xs.select_basket({"A": 4, "B": 3, "C": 2, "D": 1}, 2, 2)
    assert longs == ["A", "B"] and shorts == ["D", "C"]
    assert not set(longs) & set(shorts)


def test_fill_price_accounts_for_lot_size():
    assert xs.fill_price(120_000, lots=100, lot_size=10) == 120


def test_completed_daily_bars_excludes_current_session_candle():
    bars = pd.DataFrame({
        "timestamp": ["2026-09-04T07:00:00Z", "2026-09-07T07:00:00Z"],
        "close": [100.0, 200.0],
    })

    completed = xs.completed_daily_bars(bars, date(2026, 9, 7))

    assert completed.close.tolist() == [100.0]


def test_db_has_dashboard_query_shape(tmp_path):
    db = xs.XsecDB(str(tmp_path / "x.sqlite"))
    db.add_trade({"trade_id": "x", "direction": "NEUTRAL", "status": "CLOSED",
                  "exit_ts": "2026-01-01T00:00:00+00:00", "net_pnl_rub": 10.0})
    row = db.con.execute(
        "SELECT direction, net_pnl_rub AS pnl, exit_ts AS ets, status FROM xsec_trades"
    ).fetchone()
    assert row["pnl"] == 10.0
