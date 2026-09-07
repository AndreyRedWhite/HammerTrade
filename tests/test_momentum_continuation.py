"""Tests for Momentum Continuation strategy."""
from __future__ import annotations

import pandas as pd
import pytest

from src.research.vwap import compute_atr
from src.strategies.momentum_continuation.strategy import run_momentum_backtest


def _make_candles(n: int = 30, base: float = 82000.0) -> pd.DataFrame:
    """Flat candles — no impulse signals."""
    ts = pd.date_range("2026-01-15 07:00:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": [base] * n,
        "high": [base + 5.0] * n,
        "low": [base - 5.0] * n,
        "close": [base + 2.0] * n,  # close near top => NOT bearish
        "volume": [500.0] * n,
    })


def _make_impulse_candles(n_setup: int = 20, base: float = 82000.0) -> pd.DataFrame:
    """Make candles with a clear bearish impulse bar after n_setup setup bars."""
    ts_setup = pd.date_range("2026-01-15 07:00:00", periods=n_setup, freq="1min", tz="UTC")
    setup_rows = pd.DataFrame({
        "timestamp": ts_setup,
        "open": [base] * n_setup,
        "high": [base + 5.0] * n_setup,
        "low": [base - 5.0] * n_setup,
        "close": [base] * n_setup,
        "volume": [500.0] * n_setup,
    })

    # Impulse bar: very large range, close near low, high volume
    impulse_ts = pd.date_range(
        "2026-01-15 07:20:00", periods=1, freq="1min", tz="UTC"
    )
    impulse = pd.DataFrame({
        "timestamp": impulse_ts,
        "open": [base],
        "high": [base + 200.0],  # huge range
        "low": [base - 200.0],
        "close": [base - 190.0],  # close near low => (close-low)/range = 10/400 = 0.025 < 0.25
        "volume": [5000.0],  # 10x normal volume
    })

    # Follow-up bars for simulation (neutral)
    ts_post = pd.date_range("2026-01-15 07:21:00", periods=20, freq="1min", tz="UTC")
    post = pd.DataFrame({
        "timestamp": ts_post,
        "open": [base - 190.0] * 20,
        "high": [base - 100.0] * 20,
        "low": [base - 250.0] * 20,  # take hit
        "close": [base - 190.0] * 20,
        "volume": [500.0] * 20,
    })

    return pd.concat([setup_rows, impulse, post], ignore_index=True)


class TestATRComputed:
    """Test that ATR is computed and used in signal detection."""

    def test_atr_increases_on_volatile_bars(self):
        # Make increasingly volatile bars
        ts = pd.date_range("2026-01-15 07:00:00", periods=20, freq="1min", tz="UTC")
        highs = [82000.0 + i * 10 for i in range(20)]
        lows = [82000.0 - i * 10 for i in range(20)]
        df = pd.DataFrame({
            "timestamp": ts,
            "open": [82000.0] * 20,
            "high": highs,
            "low": lows,
            "close": [82000.0] * 20,
            "volume": [500.0] * 20,
        })
        atr = compute_atr(df, window=5)
        # Later bars should have higher ATR
        assert float(atr.iloc[-1]) > float(atr.iloc[5])


class TestImpulseSignalDetected:
    """Test that a clear bearish impulse triggers a trade."""

    def test_impulse_signal_detected(self):
        candles = _make_impulse_candles(n_setup=20)
        results, trades = run_momentum_backtest(
            candles,
            atr_mult_list=[1.0],
            vol_mult_list=[1.2],
            take_r_list=[1.0],
            atr_window=14,
            vol_window=10,
            max_trades_per_day=1,
        )
        assert len(trades) >= 1, "Expected at least 1 trade on clear bearish impulse"
        t = trades[0]
        assert t["direction"] == "SHORT"
        # Stop should be the impulse bar high
        assert t["stop_price"] == pytest.approx(82200.0, abs=1.0)

    def test_impulse_pnl_correct(self):
        """Verify PnL calculation is correct for a SHORT trade."""
        candles = _make_impulse_candles(n_setup=20)
        _, trades = run_momentum_backtest(
            candles,
            atr_mult_list=[1.0],
            vol_mult_list=[1.2],
            take_r_list=[1.0],
            atr_window=14,
            vol_window=10,
            max_trades_per_day=1,
        )
        assert len(trades) >= 1
        t = trades[0]
        # pnl_rub = pnl_points * 10 - 0.05
        expected_rub = t["pnl_points"] * 10.0 - 0.05
        assert abs(t["pnl_rub"] - expected_rub) < 0.001


class TestNoSignalBelowThreshold:
    """Test that signals are NOT generated when conditions are not met."""

    def test_no_signal_on_flat_candles(self):
        """Flat candles: close near top (not bearish), small range => no signal."""
        candles = _make_candles(n=40)
        _, trades = run_momentum_backtest(
            candles,
            atr_mult_list=[2.0],
            vol_mult_list=[1.5],
            take_r_list=[1.0],
            atr_window=14,
            vol_window=10,
            max_trades_per_day=1,
        )
        assert len(trades) == 0, f"Expected 0 trades on flat candles, got {len(trades)}"

    def test_no_signal_high_vol_mult(self):
        """Even with impulse, if vol_mult is very high, no signal fires."""
        candles = _make_impulse_candles(n_setup=20)
        _, trades = run_momentum_backtest(
            candles,
            atr_mult_list=[1.0],
            vol_mult_list=[20.0],  # requires 20x average volume
            take_r_list=[1.0],
            atr_window=14,
            vol_window=10,
            max_trades_per_day=1,
        )
        assert len(trades) == 0, "Very high vol_mult should suppress the signal"

    def test_max_trades_per_day_respected(self):
        """With max_trades_per_day=1, only one trade should be taken per day."""
        # Build multiple impulse bars on the same day
        ts_all = pd.date_range("2026-01-15 07:00:00", periods=100, freq="1min", tz="UTC")
        base = 82000.0
        # Alternate between normal and impulse bars
        highs = [base + 200.0 if i % 5 == 4 else base + 5.0 for i in range(100)]
        lows = [base - 200.0 if i % 5 == 4 else base - 5.0 for i in range(100)]
        closes = [base - 190.0 if i % 5 == 4 else base for i in range(100)]
        vols = [5000.0 if i % 5 == 4 else 100.0 for i in range(100)]

        candles = pd.DataFrame({
            "timestamp": ts_all,
            "open": [base] * 100,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        })

        _, trades = run_momentum_backtest(
            candles,
            atr_mult_list=[1.0],
            vol_mult_list=[1.5],
            take_r_list=[1.0],
            atr_window=5,
            vol_window=5,
            max_trades_per_day=1,
        )

        day_counts: dict[str, int] = {}
        for t in trades:
            day_counts[t["date"]] = day_counts.get(t["date"], 0) + 1

        for day, cnt in day_counts.items():
            assert cnt <= 1, f"max_trades_per_day=1 violated: {cnt} trades on {day}"
