"""Tests for src/research/robustness.py — MVP-R1a."""
import pytest

from src.research.robustness import (
    top_trades_contribution,
    best_day_contribution,
    concentration_flag,
    net_without_best_day,
    worst_day_contribution,
    net_without_top_n_trades,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(date: str, pnl_rub: float) -> dict:
    return {
        "date": date,
        "pnl_rub": pnl_rub,
        "pnl_points": pnl_rub / 10.0,
        "bars_held": 5,
        "exit_reason": "TAKE" if pnl_rub > 0 else "STOP",
    }


# ---------------------------------------------------------------------------
# Test 1: top_trades_contribution — top 1 trade = correct % of net
# ---------------------------------------------------------------------------

def test_top_trades_contribution_correct():
    trades = [
        _trade("2026-01-20", 500.0),
        _trade("2026-01-21", 100.0),
        _trade("2026-01-22", -50.0),
    ]
    # Total net = 500 + 100 - 50 = 550
    # Top 1 = 500.0, pct = 500/550 ≈ 0.909
    result = top_trades_contribution(trades, 1)
    assert result["n"] == 1
    assert result["total_net"] == pytest.approx(550.0)
    assert result["top_n_net"] == pytest.approx(500.0)
    assert result["pct_of_total"] == pytest.approx(500.0 / 550.0, rel=1e-5)


# ---------------------------------------------------------------------------
# Test 2: best_day_contribution — correct best day net
# ---------------------------------------------------------------------------

def test_best_day_contribution():
    trades = [
        _trade("2026-01-20", 300.0),
        _trade("2026-01-20", 200.0),  # same day — total 500
        _trade("2026-01-21", 100.0),
    ]
    result = best_day_contribution(trades)
    assert result["best_date"] == "2026-01-20"
    assert result["best_day_net"] == pytest.approx(500.0)
    assert result["total_net"] == pytest.approx(600.0)
    assert result["pct_of_total"] == pytest.approx(500.0 / 600.0, rel=1e-5)


# ---------------------------------------------------------------------------
# Test 3: concentration_flag returns True when top 3 > 50% of net
# ---------------------------------------------------------------------------

def test_concentration_flag_high_when_top3_dominant():
    # Top 3 trades carry almost all of the profit
    trades = [
        _trade("2026-01-19", 1000.0),
        _trade("2026-01-20", 1000.0),
        _trade("2026-01-21", 1000.0),
        _trade("2026-01-22", 10.0),
        _trade("2026-01-23", 10.0),
        _trade("2026-01-24", -50.0),
    ]
    # Total = 1000*3 + 10*2 - 50 = 2970
    # Top 3 = 3000 → 3000/2970 > 1.0 (> 50%)
    flag, reason = concentration_flag(trades)
    assert flag is True
    assert "CONCENTRATION_HIGH" in reason


def test_concentration_flag_false_when_distributed():
    # 10 equal trades: each 100 — top 3 = 300/1000 = 30% < 50%
    trades = [_trade(f"2026-01-{10+i}", 100.0) for i in range(10)]
    flag, reason = concentration_flag(trades)
    assert flag is False


# ---------------------------------------------------------------------------
# Test 4: Empty trades — no crash, returns safe defaults
# ---------------------------------------------------------------------------

def test_empty_trades_no_crash():
    assert top_trades_contribution([], 3) == {"n": 3, "total_net": 0.0, "top_n_net": 0.0, "pct_of_total": 0.0}
    assert best_day_contribution([]) == {"best_date": "", "best_day_net": 0.0, "total_net": 0.0, "pct_of_total": 0.0}
    flag, reason = concentration_flag([])
    assert flag is False
    assert net_without_best_day([]) == 0.0
    assert worst_day_contribution([]) == {"worst_date": "", "worst_day_net": 0.0, "total_net": 0.0, "pct_of_total": 0.0}
    assert net_without_top_n_trades([], 3) == 0.0
