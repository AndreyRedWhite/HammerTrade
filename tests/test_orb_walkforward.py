"""Tests for src/research/walkforward.py — MVP-R1a."""
import pytest

from src.research.walkforward import (
    split_by_month,
    split_by_week,
    period_summary,
    walkforward_table,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_trade(date: str, pnl_rub: float, exit_reason: str = "TAKE") -> dict:
    return {
        "date": date,
        "pnl_rub": pnl_rub,
        "pnl_points": pnl_rub / 10.0,
        "bars_held": 5,
        "exit_reason": exit_reason,
        "direction": "LONG",
        "entry_price": 80000.0,
        "exit_price": 80010.0,
    }


SAMPLE_TRADES = [
    _make_trade("2026-01-20", 100.0),
    _make_trade("2026-01-21", -50.0, "STOP"),
    _make_trade("2026-02-05", 200.0),
    _make_trade("2026-02-10", 150.0),
    _make_trade("2026-03-15", -30.0, "STOP"),
]


# ---------------------------------------------------------------------------
# Test 1: split_by_month groups correctly
# ---------------------------------------------------------------------------

def test_split_by_month_groups():
    result = split_by_month(SAMPLE_TRADES)
    assert set(result.keys()) == {"2026-01", "2026-02", "2026-03"}
    assert len(result["2026-01"]) == 2
    assert len(result["2026-02"]) == 2
    assert len(result["2026-03"]) == 1


# ---------------------------------------------------------------------------
# Test 2: split_by_week groups correctly
# ---------------------------------------------------------------------------

def test_split_by_week_groups():
    trades = [
        _make_trade("2026-01-20", 100.0),  # Tue, ISO week 4
        _make_trade("2026-01-21", -50.0),  # Wed, same week 4
        _make_trade("2026-01-26", 200.0),  # Mon, ISO week 5
    ]
    result = split_by_week(trades)
    # Should have 2 weeks
    assert len(result) == 2
    # Week 4 has 2 trades
    week4 = [v for k, v in result.items() if "W04" in k]
    assert len(week4) == 1
    assert len(week4[0]) == 2
    # Week 5 has 1 trade
    week5 = [v for k, v in result.items() if "W05" in k]
    assert len(week5) == 1
    assert len(week5[0]) == 1


# ---------------------------------------------------------------------------
# Test 3: period_summary computes correct net_pnl for a subset
# ---------------------------------------------------------------------------

def test_period_summary_net_pnl():
    jan_trades = [
        _make_trade("2026-01-20", 100.0),
        _make_trade("2026-01-21", -50.0, "STOP"),
    ]
    summary = period_summary(jan_trades, "2026-01")
    assert summary["period_label"] == "2026-01"
    assert abs(summary["net_pnl"] - 50.0) < 0.01
    assert summary["trades"] == 2
    assert summary["trading_days"] == 2
    assert summary["profitable_days"] == 1  # Jan 20 is profitable, Jan 21 is not


# ---------------------------------------------------------------------------
# Test 4: walkforward_table returns one row per period with period_label
# ---------------------------------------------------------------------------

def test_walkforward_table_monthly():
    result = walkforward_table(SAMPLE_TRADES, period="month")
    assert len(result) == 3
    labels = [r["period_label"] for r in result]
    assert "2026-01" in labels
    assert "2026-02" in labels
    assert "2026-03" in labels
    for row in result:
        assert "period_label" in row
        assert "trades" in row
        assert "net_pnl" in row
        assert "trading_days" in row
        assert "profitable_days" in row


# ---------------------------------------------------------------------------
# Test 5: Empty trades list returns empty table
# ---------------------------------------------------------------------------

def test_walkforward_table_empty():
    result = walkforward_table([], period="month")
    assert result == []

    result_week = walkforward_table([], period="week")
    assert result_week == []
