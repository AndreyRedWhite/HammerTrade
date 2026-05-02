import pandas as pd
import pytest

from src.backtest.engine import run_backtest


def _make_debug_df():
    """Synthetic debug CSV with 3 BUY and 2 SELL signals."""
    rows = []
    t = 1000
    for i, direction in enumerate(["BUY", "SELL", "BUY", "SELL", "BUY"]):
        for j in range(5):
            is_sig = j == 0
            rows.append({
                "timestamp": f"2026-01-01 0{i}:{j:02d}:00+00:00",
                "open": t, "high": t + 10, "low": t - 10, "close": t + 2,
                "volume": 100,
                "is_signal": is_sig,
                "fail_reason": "pass" if is_sig else "body_big",
                "direction_candidate": direction,
                "instrument": "TEST", "timeframe": "1m",
            })
            t += 1
    return pd.DataFrame(rows)


def test_direction_filter_all_includes_both():
    df = _make_debug_df()
    trades = run_backtest(df, direction_filter="all", point_value_rub=10.0, entry_mode="close")
    closed = trades[trades["status"] == "closed"]
    directions = set(closed["direction"].unique())
    assert "BUY" in directions
    assert "SELL" in directions


def test_direction_filter_buy_only():
    df = _make_debug_df()
    trades = run_backtest(df, direction_filter="BUY", point_value_rub=10.0, entry_mode="close")
    closed = trades[trades["status"] == "closed"]
    assert all(closed["direction"] == "BUY")
    assert len(closed) > 0


def test_direction_filter_sell_only():
    df = _make_debug_df()
    trades = run_backtest(df, direction_filter="SELL", point_value_rub=10.0, entry_mode="close")
    closed = trades[trades["status"] == "closed"]
    assert all(closed["direction"] == "SELL")
    assert len(closed) > 0


def test_direction_filter_buy_count():
    df = _make_debug_df()
    all_trades = run_backtest(df, direction_filter="all", point_value_rub=10.0, entry_mode="close")
    buy_trades = run_backtest(df, direction_filter="BUY", point_value_rub=10.0, entry_mode="close")
    sell_trades = run_backtest(df, direction_filter="SELL", point_value_rub=10.0, entry_mode="close")

    all_closed = all_trades[all_trades["status"] == "closed"]
    buy_closed = buy_trades[buy_trades["status"] == "closed"]
    sell_closed = sell_trades[sell_trades["status"] == "closed"]

    assert len(buy_closed) + len(sell_closed) == len(all_closed)


def test_direction_filter_invalid_raises():
    df = _make_debug_df()
    with pytest.raises(ValueError, match="direction_filter"):
        run_backtest(df, direction_filter="LONG", point_value_rub=10.0, entry_mode="close")


def test_direction_filter_case_sensitive():
    df = _make_debug_df()
    with pytest.raises(ValueError):
        run_backtest(df, direction_filter="buy", point_value_rub=10.0, entry_mode="close")


def test_direction_filter_all_is_default():
    df = _make_debug_df()
    trades_default = run_backtest(df, point_value_rub=10.0, entry_mode="close")
    trades_all = run_backtest(df, direction_filter="all", point_value_rub=10.0, entry_mode="close")
    assert len(trades_default) == len(trades_all)
