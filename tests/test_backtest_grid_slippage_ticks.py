import pandas as pd
import pytest

from src.backtest.batch import run_batch


def _make_signal_df():
    records = []
    for i in range(10):
        records.append({
            "timestamp": pd.Timestamp(f"2026-04-01 {9 + i // 60:02d}:{i % 60:02d}:00"),
            "instrument": "BRK6",
            "timeframe": "1m",
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 100.0,
            "volume": 100,
            "is_signal": (i == 0),
            "fail_reason": "pass" if i == 0 else "filter",
            "direction_candidate": "BUY",
        })
    return pd.DataFrame(records)


# --- 1. Grid creates scenarios by slippage_ticks_values ---

def test_grid_slippage_ticks_scenarios():
    df = _make_signal_df()
    grid = run_batch(
        df,
        entry_modes=["close"],
        take_r_values=[1.0],
        max_hold_bars_values=[5],
        stop_buffer_points_values=[0.0],
        slippage_ticks_values=[0, 1, 2],
        tick_size=0.01,
    )
    assert len(grid) == 3


# --- 2. Result contains slippage_ticks column ---

def test_grid_has_slippage_ticks_column():
    df = _make_signal_df()
    grid = run_batch(
        df,
        entry_modes=["close"],
        take_r_values=[1.0],
        max_hold_bars_values=[5],
        stop_buffer_points_values=[0.0],
        slippage_ticks_values=[0, 1],
        tick_size=0.01,
    )
    assert "slippage_ticks" in grid.columns
    assert list(grid["slippage_ticks"]) == [0, 1]


# --- 3. Result contains effective_slippage_points ---

def test_grid_has_effective_slippage_points():
    df = _make_signal_df()
    grid = run_batch(
        df,
        entry_modes=["close"],
        take_r_values=[1.0],
        max_hold_bars_values=[5],
        stop_buffer_points_values=[0.0],
        slippage_ticks_values=[0, 2],
        tick_size=0.01,
    )
    assert "effective_slippage_points" in grid.columns
    assert abs(grid.iloc[0]["effective_slippage_points"] - 0.0) < 1e-9
    assert abs(grid.iloc[1]["effective_slippage_points"] - 0.02) < 1e-9


# --- 4. tick_size propagated to result column ---

def test_grid_tick_size_column():
    df = _make_signal_df()
    grid = run_batch(
        df,
        entry_modes=["close"],
        take_r_values=[1.0],
        max_hold_bars_values=[5],
        stop_buffer_points_values=[0.0],
        slippage_ticks_values=[0],
        tick_size=0.01,
    )
    assert "tick_size" in grid.columns
    assert abs(grid.iloc[0]["tick_size"] - 0.01) < 1e-9


# --- 5. Without slippage_ticks_values, old behavior preserved ---

def test_grid_without_ticks_uses_points():
    df = _make_signal_df()
    grid = run_batch(
        df,
        entry_modes=["close"],
        take_r_values=[1.0],
        max_hold_bars_values=[5],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0, 1.0],
    )
    assert len(grid) == 2
    assert list(grid["slippage_points"]) == [0.0, 1.0]
