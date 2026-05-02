import pytest
import pandas as pd

from src.backtest.engine import run_backtest


def _make_df(rows):
    records = []
    for i, r in enumerate(rows):
        records.append({
            "timestamp": pd.Timestamp(f"2026-04-01 10:{i:02d}:00"),
            "instrument": "BRK6",
            "timeframe": "1m",
            "open": r.get("open", 100.0),
            "high": r.get("high", 101.0),
            "low": r.get("low", 99.0),
            "close": r.get("close", 100.0),
            "volume": 100,
            "is_signal": r.get("is_signal", False),
            "fail_reason": r.get("fail_reason", "filter"),
            "direction_candidate": r.get("direction", "BUY"),
        })
    return pd.DataFrame(records)


def _buy_take_df():
    return _make_df([
        {"is_signal": True, "fail_reason": "pass", "direction": "BUY",
         "open": 99, "high": 102, "low": 95, "close": 100},
        {"open": 102, "high": 106, "low": 100, "close": 105},
    ])


def _sell_take_df():
    return _make_df([
        {"is_signal": True, "fail_reason": "pass", "direction": "SELL",
         "open": 101, "high": 105, "low": 99, "close": 100},
        {"open": 100, "high": 100, "low": 94, "close": 97},
    ])


# --- 1. slippage_ticks=1, tick_size=0.01 -> effective_slippage_points=0.01 ---

def test_effective_slippage_points_computed():
    df = _buy_take_df()
    result = run_backtest(df, entry_mode="close", take_r=1.0,
                          slippage_ticks=1, tick_size=0.01)
    row = result.iloc[0]
    assert abs(row["effective_slippage_points"] - 0.01) < 1e-9
    assert row["slippage_ticks"] == 1
    assert abs(row["tick_size"] - 0.01) < 1e-9


# --- 2. BUY result with slippage_ticks is worse than without ---

def test_buy_slippage_ticks_worsens_result():
    df = _buy_take_df()
    no_slip = run_backtest(df, entry_mode="close", take_r=1.0,
                           slippage_ticks=0, tick_size=0.01)
    with_slip = run_backtest(df, entry_mode="close", take_r=1.0,
                             slippage_ticks=5, tick_size=0.01)
    assert with_slip.iloc[0]["net_pnl_rub"] < no_slip.iloc[0]["net_pnl_rub"]


# --- 3. SELL result with slippage_ticks is worse than without ---

def test_sell_slippage_ticks_worsens_result():
    df = _sell_take_df()
    no_slip = run_backtest(df, entry_mode="close", take_r=1.0,
                           slippage_ticks=0, tick_size=0.01)
    with_slip = run_backtest(df, entry_mode="close", take_r=1.0,
                             slippage_ticks=5, tick_size=0.01)
    assert with_slip.iloc[0]["net_pnl_rub"] < no_slip.iloc[0]["net_pnl_rub"]


# --- 4. slippage_ticks without tick_size raises an error ---

def test_slippage_ticks_without_tick_size_raises():
    df = _buy_take_df()
    with pytest.raises(ValueError, match="tick_size"):
        run_backtest(df, entry_mode="close", take_r=1.0,
                     slippage_ticks=1, tick_size=None)


# --- 5. negative slippage_ticks raises ---

def test_negative_slippage_ticks_raises():
    df = _buy_take_df()
    with pytest.raises(ValueError, match="slippage_ticks"):
        run_backtest(df, entry_mode="close", take_r=1.0,
                     slippage_ticks=-1, tick_size=0.01)


# --- 6. negative slippage_points raises ---

def test_negative_slippage_points_raises():
    df = _buy_take_df()
    with pytest.raises(ValueError, match="slippage_points"):
        run_backtest(df, entry_mode="close", take_r=1.0, slippage_points=-1.0)


# --- 7. slippage_ticks with tick_size=0 raises ---

def test_slippage_ticks_with_zero_tick_size_raises():
    df = _buy_take_df()
    with pytest.raises(ValueError, match="tick_size"):
        run_backtest(df, entry_mode="close", take_r=1.0,
                     slippage_ticks=1, tick_size=0.0)


# --- 8. effective_slippage_points = slippage_points when no ticks mode ---

def test_effective_slippage_points_fallback_to_slippage_points():
    df = _buy_take_df()
    result = run_backtest(df, entry_mode="close", take_r=1.0, slippage_points=0.5)
    row = result.iloc[0]
    assert abs(row["effective_slippage_points"] - 0.5) < 1e-9
    assert pd.isna(row["slippage_ticks"])
