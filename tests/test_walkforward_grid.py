import pandas as pd
import pytest
from pathlib import Path

from src.backtest.walkforward import run_period_grid_backtests
from src.backtest.walkforward_report import generate_walkforward_grid_report

REQUIRED_COLS = {
    "period_key", "period_start", "period_end",
    "scenario_id", "entry_mode", "entry_horizon_bars", "take_r",
    "max_hold_bars", "stop_buffer_points", "slippage_points", "contracts",
    "rows", "total_signals", "closed_trades", "skipped_trades",
    "wins", "losses", "timeouts", "winrate",
    "gross_pnl_rub", "net_pnl_rub", "avg_net_pnl_rub", "median_net_pnl_rub",
    "profit_factor", "max_drawdown_rub", "max_drawdown_pct", "ending_equity_rub",
    "avg_bars_held", "buy_trades", "sell_trades", "buy_net_pnl_rub", "sell_net_pnl_rub",
}


def _make_multiweek_df():
    rows = []
    for day_offset in range(10):  # April 1-10 UTC midday = same MSK day
        base = pd.Timestamp(f"2026-04-{1 + day_offset:02d} 10:00:00+00:00")
        rows.append({
            "timestamp": base,
            "instrument": "SiM6", "timeframe": "1m",
            "open": 100.0, "high": 102.0, "low": 95.0, "close": 100.0,
            "volume": 100,
            "is_signal": True, "fail_reason": "pass", "direction_candidate": "BUY",
        })
        rows.append({
            "timestamp": base + pd.Timedelta(minutes=2),
            "instrument": "SiM6", "timeframe": "1m",
            "open": 100.0, "high": 106.0, "low": 99.0, "close": 105.0,
            "volume": 100,
            "is_signal": False, "fail_reason": "range", "direction_candidate": "BUY",
        })
    return pd.DataFrame(rows)


# --- 1. Grid creates scenario × period rows ---

def test_grid_row_count():
    df = _make_multiweek_df()
    result = run_period_grid_backtests(
        df, period="week",
        entry_modes=["close"],
        take_r_values=[1.0, 2.0],
        max_hold_bars_values=[30],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0],
    )
    # 2 scenarios × 2 weeks = 4 rows
    assert len(result) == 4


def test_grid_row_count_multi_scenario():
    df = _make_multiweek_df()
    result = run_period_grid_backtests(
        df, period="week",
        entry_modes=["close", "breakout"],
        take_r_values=[1.0, 2.0],
        max_hold_bars_values=[30],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0],
    )
    # 4 scenarios × 2 weeks = 8 rows
    assert len(result) == 8


# --- 2. Required columns present ---

def test_required_columns():
    df = _make_multiweek_df()
    result = run_period_grid_backtests(
        df, period="week",
        entry_modes=["close"],
        take_r_values=[1.0],
        max_hold_bars_values=[30],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0],
    )
    missing = REQUIRED_COLS - set(result.columns)
    assert not missing, f"Missing: {missing}"


# --- 3. Report is created ---

def test_grid_report_created(tmp_path):
    df = _make_multiweek_df()
    result = run_period_grid_backtests(
        df, period="week",
        entry_modes=["close"],
        take_r_values=[1.0],
        max_hold_bars_values=[30],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0],
    )
    report_path = str(tmp_path / "wf_grid_report.md")
    generate_walkforward_grid_report(result, report_path, "test.csv", period="week")
    assert Path(report_path).exists()
    content = Path(report_path).read_text()
    assert "# Walk-forward Grid Report" in content
    assert "Scenario Stability Ranking" in content
    assert "Robust Scenarios" in content
    assert "Fragile Scenarios" in content


# --- 4. Slippage scenarios present ---

def test_slippage_scenarios_in_grid():
    df = _make_multiweek_df()
    result = run_period_grid_backtests(
        df, period="week",
        entry_modes=["close"],
        take_r_values=[1.0],
        max_hold_bars_values=[30],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0, 2.0],
    )
    assert set(result["slippage_points"].unique()) == {0.0, 2.0}


# --- 5. Higher slippage never improves net PnL within same scenario params ---

def test_slippage_reduces_pnl_in_grid():
    df = _make_multiweek_df()
    result = run_period_grid_backtests(
        df, period="day",
        entry_modes=["close"],
        take_r_values=[1.0],
        max_hold_bars_values=[30],
        stop_buffer_points_values=[0.0],
        slippage_points_values=[0.0, 1.0],
    )
    no_slip = result[result["slippage_points"] == 0.0]["net_pnl_rub"].sum()
    with_slip = result[result["slippage_points"] == 1.0]["net_pnl_rub"].sum()
    assert no_slip >= with_slip
