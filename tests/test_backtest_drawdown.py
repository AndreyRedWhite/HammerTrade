import pandas as pd
import pytest

from src.backtest.metrics import calculate_backtest_metrics


_COLS = ["trade_id", "status", "direction", "exit_reason",
         "net_pnl_rub", "gross_pnl_rub", "bars_held"]


def _trades_from_pnl(pnl_values, direction="BUY"):
    """Build a minimal closed-trades DataFrame from a list of net_pnl_rub values."""
    rows = []
    for i, pnl in enumerate(pnl_values):
        gross = pnl + 0.05
        rows.append({
            "trade_id": i + 1,
            "status": "closed",
            "direction": direction,
            "exit_reason": "take" if pnl > 0 else "stop",
            "net_pnl_rub": pnl,
            "gross_pnl_rub": gross,
            "bars_held": 5,
        })
    return pd.DataFrame(rows, columns=_COLS)


# Equity curve: +100, +50, -80, +20, -200, +30
# equity:        100  150   70   90  -110  -80
# peak:          100  150  150  150   150  150
# drawdown:        0    0   80   60   260  230
# max_drawdown = 260

PNL_SEQUENCE = [100, 50, -80, 20, -200, 30]


def test_max_drawdown_rub():
    df = _trades_from_pnl(PNL_SEQUENCE)
    m = calculate_backtest_metrics(df)
    assert abs(m["max_drawdown_rub"] - 260.0) < 1e-6


def test_max_drawdown_pct():
    df = _trades_from_pnl(PNL_SEQUENCE)
    m = calculate_backtest_metrics(df)
    # peak = 150, drawdown = 260 → pct = 260/150
    expected_pct = 260.0 / 150.0
    assert abs(m["max_drawdown_pct"] - expected_pct) < 1e-6


def test_ending_equity_rub():
    df = _trades_from_pnl(PNL_SEQUENCE)
    m = calculate_backtest_metrics(df)
    # sum = 100+50-80+20-200+30 = -80
    assert abs(m["ending_equity_rub"] - (-80.0)) < 1e-6


def test_min_equity_rub():
    df = _trades_from_pnl(PNL_SEQUENCE)
    m = calculate_backtest_metrics(df)
    # min equity = -110 (after -200)
    assert abs(m["min_equity_rub"] - (-110.0)) < 1e-6


def test_max_equity_rub():
    df = _trades_from_pnl(PNL_SEQUENCE)
    m = calculate_backtest_metrics(df)
    # max equity = 150 (after +100+50)
    assert abs(m["max_equity_rub"] - 150.0) < 1e-6


def test_drawdown_zero_when_always_profitable():
    df = _trades_from_pnl([10, 20, 30])
    m = calculate_backtest_metrics(df)
    assert m["max_drawdown_rub"] == 0.0


def test_drawdown_no_trades():
    df = _trades_from_pnl([])
    m = calculate_backtest_metrics(df)
    assert m["max_drawdown_rub"] == 0.0
    assert m["max_drawdown_pct"] == 0.0
    assert m["ending_equity_rub"] == 0.0


def test_drawdown_skipped_not_counted():
    # Skipped trades should not affect equity curve
    rows = [
        {"trade_id": 1, "status": "closed", "direction": "BUY",
         "exit_reason": "take", "net_pnl_rub": 100.0, "gross_pnl_rub": 100.05, "bars_held": 5},
        {"trade_id": 2, "status": "skipped_no_entry", "direction": "BUY",
         "exit_reason": "none", "net_pnl_rub": None, "gross_pnl_rub": None, "bars_held": None},
    ]
    df = pd.DataFrame(rows)
    m = calculate_backtest_metrics(df)
    # Only 1 closed trade with +100; equity never drops → drawdown = 0
    assert m["max_drawdown_rub"] == 0.0
    assert abs(m["ending_equity_rub"] - 100.0) < 1e-6
