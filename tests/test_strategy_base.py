"""Tests for Strategy base classes (Part G)."""
import pytest
from datetime import datetime, timezone
from src.strategies.base import StrategySignal, StrategyResult


def test_strategy_signal_creation():
    """StrategySignal can be created with all fields."""
    ts = datetime(2026, 1, 20, 10, 15, 0, tzinfo=timezone.utc)
    sig = StrategySignal(
        strategy_name="opening_range_breakout",
        ticker="SiM6",
        direction="LONG",
        timestamp=ts,
        entry_price=82500.0,
        stop_price=82450.0,
        take_price=82600.0,
        reason="ORB_LONG breakout at 10:17",
        metadata={"or_high": 82500.0, "or_low": 82450.0, "date": "2026-01-20"},
    )
    assert sig.strategy_name == "opening_range_breakout"
    assert sig.ticker == "SiM6"
    assert sig.direction == "LONG"
    assert sig.timestamp == ts
    assert sig.entry_price == 82500.0
    assert sig.stop_price == 82450.0
    assert sig.take_price == 82600.0
    assert sig.reason == "ORB_LONG breakout at 10:17"
    assert sig.metadata["or_high"] == 82500.0
    assert sig.metadata["date"] == "2026-01-20"


def test_strategy_result_to_dict():
    """StrategyResult.to_dict() works and has all required keys."""
    result = StrategyResult(
        strategy_name="opening_range_breakout",
        ticker="SiM6",
        direction="LONG",
        timeframe="1m",
        scenario="ORB_10:00-10:15_LONG_R1.5",
        period="2026-01-15 to 2026-04-09",
        trades=42,
        wins=25,
        losses=17,
        winrate=0.595,
        net_pnl=1250.0,
        profit_factor=1.42,
        expectancy=29.76,
        max_drawdown=420.0,
        best_trade=310.0,
        worst_trade=-210.0,
        avg_bars_held=12.3,
        median_bars_held=10.0,
        profitable_days_pct=0.62,
        profitable_weeks_pct=0.75,
        warnings=["test warning"],
    )
    d = result.to_dict()

    required_keys = [
        "strategy_name", "ticker", "direction", "timeframe", "scenario", "period",
        "trades", "wins", "losses", "winrate", "net_pnl", "profit_factor",
        "expectancy", "max_drawdown", "best_trade", "worst_trade",
        "avg_bars_held", "median_bars_held", "profitable_days_pct",
        "profitable_weeks_pct", "warnings",
    ]
    for key in required_keys:
        assert key in d, f"Missing key: {key}"

    assert d["strategy_name"] == "opening_range_breakout"
    assert d["trades"] == 42
    assert d["winrate"] == 0.595
    assert d["warnings"] == ["test warning"]
