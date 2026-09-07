"""Tests for the multi-strategy R2 runner infrastructure."""
from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.momentum_continuation.strategy import run_momentum_backtest
from src.strategies.opening_range_fade.strategy import run_orf_backtest
from src.strategies.vwap_reversion.strategy import run_vwap_reversion_backtest


def _minimal_candles(n: int = 50, base: float = 82000.0, date: str = "2026-01-15") -> pd.DataFrame:
    """Create minimal candle DataFrame for testing."""
    ts = pd.date_range(f"{date} 07:00:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": [base] * n,
        "high": [base + 5.0] * n,
        "low": [base - 5.0] * n,
        "close": [base] * n,
        "volume": [500.0] * n,
    })


class TestRunnerReturnsResults:
    """Test that all strategy runners return lists (even if empty)."""

    def test_momentum_returns_lists(self):
        candles = _minimal_candles()
        results, trades = run_momentum_backtest(
            candles,
            atr_mult_list=[1.0],
            vol_mult_list=[1.2],
            take_r_list=[1.0],
        )
        assert isinstance(results, list)
        assert isinstance(trades, list)

    def test_orf_returns_lists(self):
        candles = _minimal_candles(n=60)
        results, trades = run_orf_backtest(
            candles,
            or_windows=[["10:00", "10:30"]],
            n_return_bars_list=[3],
            take_mode_list=["one_r"],
        )
        assert isinstance(results, list)
        assert isinstance(trades, list)

    def test_vwap_reversion_returns_lists(self):
        candles = _minimal_candles()
        results, trades = run_vwap_reversion_backtest(
            candles,
            distance_mult_list=[1.0],
            stop_mult_list=[1.0],
            take_mode_list=["one_r_1_0"],
        )
        assert isinstance(results, list)
        assert isinstance(trades, list)


class TestEmptyDataHandled:
    """Test that strategies handle empty DataFrames gracefully."""

    def test_momentum_empty_candles(self):
        empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        results, trades = run_momentum_backtest(
            empty,
            atr_mult_list=[1.0],
            vol_mult_list=[1.2],
            take_r_list=[1.0],
        )
        assert isinstance(results, list)
        assert isinstance(trades, list)
        assert len(trades) == 0

    def test_orf_empty_candles(self):
        empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        results, trades = run_orf_backtest(
            empty,
            or_windows=[["10:00", "10:30"]],
            n_return_bars_list=[3],
            take_mode_list=["one_r"],
        )
        assert isinstance(results, list)
        assert isinstance(trades, list)
        assert len(trades) == 0

    def test_vwap_reversion_empty_candles(self):
        empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        results, trades = run_vwap_reversion_backtest(
            empty,
            distance_mult_list=[1.0],
            stop_mult_list=[1.0],
            take_mode_list=["one_r_1_0"],
        )
        assert isinstance(results, list)
        assert isinstance(trades, list)
        assert len(trades) == 0


class TestScenarioCount:
    """Test that the number of scenarios matches the grid size."""

    def test_momentum_scenario_count(self):
        candles = _minimal_candles()
        results, _ = run_momentum_backtest(
            candles,
            atr_mult_list=[1.0, 2.0],
            vol_mult_list=[1.2, 1.5],
            take_r_list=[1.0, 1.5, 2.0],
        )
        # 2 * 2 * 3 = 12 scenarios
        assert len(results) == 12

    def test_orf_scenario_count(self):
        candles = _minimal_candles(n=60)
        results, _ = run_orf_backtest(
            candles,
            or_windows=[["10:00", "10:30"], ["10:00", "11:00"]],
            n_return_bars_list=[3, 5],
            take_mode_list=["midpoint", "one_r"],
        )
        # 2 * 2 * 2 = 8 scenarios
        assert len(results) == 8

    def test_vwap_reversion_scenario_count(self):
        candles = _minimal_candles()
        results, _ = run_vwap_reversion_backtest(
            candles,
            distance_mult_list=[0.5, 1.0, 1.5],
            stop_mult_list=[1.0, 1.5],
            take_mode_list=["to_vwap", "one_r_1_0"],
        )
        # 3 * 2 * 2 = 12 scenarios
        assert len(results) == 12
