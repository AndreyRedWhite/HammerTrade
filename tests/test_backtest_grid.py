import pandas as pd
import pytest
from pathlib import Path

from src.backtest.batch import run_batch
from src.backtest.grid_report import generate_grid_report


REQUIRED_COLS = {
    "scenario_id", "entry_mode", "entry_horizon_bars", "take_r",
    "max_hold_bars", "stop_buffer_points", "slippage_points", "contracts",
    "total_signals", "closed_trades", "skipped_trades",
    "wins", "losses", "timeouts", "winrate",
    "gross_pnl_rub", "net_pnl_rub", "avg_net_pnl_rub", "median_net_pnl_rub",
    "profit_factor", "max_win_rub", "max_loss_rub",
    "max_drawdown_rub", "max_drawdown_pct",
    "avg_bars_held", "buy_trades", "sell_trades",
    "buy_net_pnl_rub", "sell_net_pnl_rub",
}


def _make_df(n_signals=5):
    """Minimal debug DataFrame with BUY signals."""
    rows = []
    for i in range(n_signals * 2):
        is_sig = i % 2 == 0
        rows.append({
            "timestamp": pd.Timestamp(f"2026-04-01 {10 + i // 60:02d}:{i % 60:02d}:00"),
            "instrument": "SiM6",
            "timeframe": "1m",
            "open": 100.0, "high": 102.0, "low": 95.0, "close": 100.0,
            "volume": 100,
            "is_signal": is_sig,
            "fail_reason": "pass" if is_sig else "range",
            "direction_candidate": "BUY",
        })
    # Add exit candles that reach take (+5 from entry)
    for i in range(n_signals * 2, n_signals * 2 + 5):
        rows.append({
            "timestamp": pd.Timestamp(f"2026-04-01 {10 + i // 60:02d}:{i % 60:02d}:00"),
            "instrument": "SiM6",
            "timeframe": "1m",
            "open": 100.0, "high": 106.0, "low": 99.0, "close": 105.0,
            "volume": 100,
            "is_signal": False,
            "fail_reason": "range",
            "direction_candidate": "BUY",
        })
    return pd.DataFrame(rows)


# --- 1. Grid creates correct number of scenarios ---

def test_grid_scenario_count():
    df = _make_df()
    result = run_batch(
        df,
        entry_modes=["breakout", "close"],
        take_r_values=[1.0, 2.0],
        max_hold_bars_values=[10, 30],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0],
    )
    # 2 entry_modes × 2 take_r × 2 max_hold × 1 stop_buf × 1 slip = 8
    assert len(result) == 8


# --- 2. Required columns present ---

def test_grid_required_columns():
    df = _make_df()
    result = run_batch(
        df,
        entry_modes=["breakout"],
        take_r_values=[1.0],
        max_hold_bars_values=[30],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0],
    )
    missing = REQUIRED_COLS - set(result.columns)
    assert not missing, f"Missing columns: {missing}"


# --- 3. Scenario IDs are sequential ---

def test_grid_scenario_ids_sequential():
    df = _make_df()
    result = run_batch(
        df,
        entry_modes=["breakout"],
        take_r_values=[1.0, 2.0],
        max_hold_bars_values=[10],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0],
    )
    assert list(result["scenario_id"]) == [1, 2]


# --- 4. Report file is created ---

def test_grid_report_created(tmp_path):
    df = _make_df()
    grid_df = run_batch(
        df,
        entry_modes=["breakout"],
        take_r_values=[1.0],
        max_hold_bars_values=[30],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0],
    )
    report_path = str(tmp_path / "grid_report.md")
    generate_grid_report(grid_df, report_path, "test.csv", signals_count=5)
    assert Path(report_path).exists()
    content = Path(report_path).read_text()
    assert "# Backtest Grid Report" in content
    assert "Top scenarios" in content
    assert "Slippage points sensitivity" in content
    assert "Robust scenarios" in content


# --- 5. Slippage scenarios are present ---

def test_grid_slippage_scenarios_present():
    df = _make_df()
    result = run_batch(
        df,
        entry_modes=["close"],
        take_r_values=[1.0],
        max_hold_bars_values=[30],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0, 1.0, 5.0],
    )
    assert set(result["slippage_points"]) == {0.0, 1.0, 5.0}


# --- 6. Higher slippage never increases net PnL (for same other params) ---

def test_slippage_monotone_in_grid():
    df = _make_df()
    result = run_batch(
        df,
        entry_modes=["close"],
        take_r_values=[1.0],
        max_hold_bars_values=[30],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0, 1.0, 5.0],
    )
    pnls = result.sort_values("slippage_points")["net_pnl_rub"].tolist()
    for i in range(len(pnls) - 1):
        assert pnls[i] >= pnls[i + 1]
