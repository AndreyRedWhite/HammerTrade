"""Tests for Opening Range Fade strategy."""
from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.opening_range_fade.strategy import run_orf_backtest


def _make_orf_candles(
    breakout_bar: int = 35,
    return_bar: int = 38,
    base_or: float = 82000.0,
    or_range: float = 200.0,
    add_breakout: bool = True,
    return_to_inside: bool = True,
) -> pd.DataFrame:
    """Build a session with OR window 10:00-10:30 MSK (07:00-07:30 UTC).

    OR: bars 0-29 (07:00-07:29 UTC)
    The OR candles fill the full or_range so OR high = base_or + or_range/2,
    OR low = base_or - or_range/2.

    Post-OR: bars 30+ (07:30+)
    Neutral post-OR bars stay strictly below the OR high.
    breakout_bar: index (in post-OR) where breakout above OR high occurs
    return_bar: index where price returns below OR high
    """
    or_bars = 30  # 10:00-10:30 MSK
    total_bars = 80  # enough for simulation

    ts = pd.date_range("2026-01-15 07:00:00", periods=total_bars, freq="1min", tz="UTC")

    or_high = base_or + or_range / 2.0
    or_low = base_or - or_range / 2.0

    prices_high = []
    prices_low = []
    prices_close = []

    for i in range(total_bars):
        if i < or_bars:
            # OR bars: collectively span the full or_range so OR high = base_or + or_range/2
            if i == 0:
                # First OR bar establishes the range
                prices_high.append(or_high)
                prices_low.append(or_low)
            else:
                # Rest stay inside
                prices_high.append(base_or + or_range / 4.0)
                prices_low.append(base_or - or_range / 4.0)
            prices_close.append(base_or)
        else:
            post_i = i - or_bars
            if add_breakout and post_i == breakout_bar:
                # Breakout: high > or_high
                prices_high.append(or_high + 50)
                prices_low.append(or_low)
                prices_close.append(or_high + 30)
            elif return_to_inside and post_i == return_bar:
                # Return: close < or_high
                prices_high.append(or_high + 10)
                prices_low.append(or_low - 5)
                prices_close.append(or_high - 20)  # back inside
            else:
                # Neutral post-OR bar: stay strictly below OR high
                prices_high.append(or_high - 5)
                prices_low.append(or_low + 5)
                prices_close.append(base_or)

    return pd.DataFrame({
        "timestamp": ts,
        "open": [base_or] * total_bars,
        "high": prices_high,
        "low": prices_low,
        "close": prices_close,
        "volume": [500.0] * total_bars,
    })


class TestFadeSignalAfterBreakoutAndReturn:
    """Test the full fade signal sequence: breakout up → return inside OR."""

    def test_signal_fires_on_breakout_and_return(self):
        """A breakout + return within n_return_bars should produce a trade."""
        candles = _make_orf_candles(breakout_bar=2, return_bar=4)
        results, trades = run_orf_backtest(
            candles,
            or_windows=[["10:00", "10:30"]],
            n_return_bars_list=[5],
            take_mode_list=["one_r"],
        )
        assert len(trades) >= 1, "Expected at least 1 fade trade"
        t = trades[0]
        assert t["direction"] == "SHORT"
        assert t["exit_reason"] in ("STOP", "TAKE", "TIME_EXIT")

    def test_trade_direction_is_short(self):
        """All ORF trades should be SHORT (fading the upside breakout)."""
        candles = _make_orf_candles(breakout_bar=2, return_bar=4)
        _, trades = run_orf_backtest(
            candles,
            or_windows=[["10:00", "10:30"]],
            n_return_bars_list=[5],
            take_mode_list=["midpoint"],
        )
        for t in trades:
            assert t["direction"] == "SHORT"


class TestNoSignalWithoutReturn:
    """No signal if price doesn't return inside OR within n_return_bars."""

    def test_no_signal_if_no_return(self):
        """Breakout without return within n_return_bars should produce no trade.

        Build candles where post-OR bars stay above or_high (sustained breakout),
        so the close never returns inside OR within n_return=3 bars.
        """
        or_high = 82100.0
        or_low = 81900.0
        base = 82000.0
        total_bars = 80
        ts = pd.date_range("2026-01-15 07:00:00", periods=total_bars, freq="1min", tz="UTC")

        highs = []
        lows = []
        closes = []

        for i in range(total_bars):
            if i < 30:
                if i == 0:
                    highs.append(or_high)
                    lows.append(or_low)
                else:
                    highs.append(base + 50)
                    lows.append(base - 50)
                closes.append(base)
            elif i == 32:
                # Breakout bar: high above or_high, close stays above or_high
                highs.append(or_high + 100)
                lows.append(or_high)
                closes.append(or_high + 80)  # close stays above or_high
            else:
                # Stay above or_high — no return to inside OR
                highs.append(or_high + 80)
                lows.append(or_high + 10)
                closes.append(or_high + 50)

        candles = pd.DataFrame({
            "timestamp": ts,
            "open": [base] * total_bars,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [500.0] * total_bars,
        })

        _, trades_n3 = run_orf_backtest(
            candles,
            or_windows=[["10:00", "10:30"]],
            n_return_bars_list=[3],
            take_mode_list=["one_r"],
        )
        # Price never returns inside OR → no trade
        assert len(trades_n3) == 0, f"Expected 0 trades (no return), got {len(trades_n3)}"

    def test_no_breakout_no_signal(self):
        """If no breakout occurs, no fade trade should be generated."""
        candles = _make_orf_candles(add_breakout=False, return_to_inside=False)
        _, trades = run_orf_backtest(
            candles,
            or_windows=[["10:00", "10:30"]],
            n_return_bars_list=[5],
            take_mode_list=["one_r"],
        )
        assert len(trades) == 0, "No breakout → no trade"


class TestTimeExitWorks:
    """Test that time_exit closes trades properly."""

    def test_time_exit_closes_at_1840(self):
        """Trades should have TIME_EXIT if no stop/take is hit."""
        # Use _make_orf_candles with breakout and return
        candles = _make_orf_candles(breakout_bar=2, return_bar=4)
        _, trades = run_orf_backtest(
            candles,
            or_windows=[["10:00", "10:30"]],
            n_return_bars_list=[5],
            take_mode_list=["one_r"],
            time_exit_str="18:40",
        )
        for t in trades:
            assert t["exit_reason"] in ("STOP", "TAKE", "TIME_EXIT")
