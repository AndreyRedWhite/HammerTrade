"""
Key test: same candle with range=0.04, S_MIN_RANGE_TICKS=2.
- tick_size=0.5 → min_range = 1.0 → candle fails (range too small)
- tick_size=0.01 → min_range = 0.02 → candle can pass range filter
"""
import pandas as pd
import pytest

from src.config import HammerParams
from src.strategy.hammer_detector import HammerDetector


def _make_candle_df(price=100.0, candle_range=0.04):
    """Single hammer-shaped candle with given range, surrounded by context bars."""
    mid = price
    half = candle_range / 2
    # Context bars (approach from above for BUY hammer)
    bars = []
    for i in range(6):
        bars.append({
            "timestamp": pd.Timestamp(f"2026-01-01 10:{i:02d}:00+00:00"),
            "open": mid + 1 - i * 0.01,
            "high": mid + 1 - i * 0.01 + 0.01,
            "low": mid + 0.5 - i * 0.01,
            "close": mid + 1 - i * 0.01 - 0.002,
            "volume": 100,
        })
    # Signal candle: BUY hammer with long lower shadow
    # range = candle_range, body at top 10%, lower shadow = 80%
    signal_open = mid + candle_range * 0.9
    signal_close = mid + candle_range
    signal_high = mid + candle_range
    signal_low = mid
    bars.append({
        "timestamp": pd.Timestamp("2026-01-01 10:06:00+00:00"),
        "open": signal_open,
        "high": signal_high,
        "low": signal_low,
        "close": signal_close,
        "volume": 200,
    })
    # Confirmation bar breaks high
    bars.append({
        "timestamp": pd.Timestamp("2026-01-01 10:07:00+00:00"),
        "open": signal_close,
        "high": signal_high + candle_range,
        "low": signal_close - 0.001,
        "close": signal_high + candle_range * 0.5,
        "volume": 150,
    })
    # Extra future bar for excursion
    bars.append({
        "timestamp": pd.Timestamp("2026-01-01 10:08:00+00:00"),
        "open": signal_high + candle_range * 0.3,
        "high": signal_high + candle_range * 1.2,
        "low": signal_high,
        "close": signal_high + candle_range,
        "volume": 100,
    })
    return pd.DataFrame(bars)


def _params_for_tick(tick_size):
    return HammerParams(
        min_range_ticks=2.0,
        min_wick_ticks=1.5,
        opp_wick_max_abs_ticks=1.0,
        body_min_frac=0.05,
        body_max_frac=0.40,
        wick_mult=1.5,
        wick_dom_ratio=1.5,
        silhouette_min_frac=0.40,
        close_pos_frac=0.50,
        ext_window=3,
        ext_eps_ticks=0.5,
        neighbor_eps_ticks=0.5,
        neighbor_mode="left_or_right",
        min_excursion_ticks=1.0,
        excursion_horizon=2,
        confirm_mode="break",
        confirm_horizon=1,
        cooldown_bars=3,
        clearing_enable=False,
        fallback_tick=0.5,
        tick_size=tick_size,
        tick_size_source="cli" if tick_size is not None else "fallback",
    )


def test_small_range_fails_with_large_tick():
    """Range=0.04, tick=0.5 → min_range=1.0 → fails on 'range'."""
    df = _make_candle_df(candle_range=0.04)
    params = _params_for_tick(tick_size=0.5)
    result = HammerDetector(params).detect_all(df, instrument="TEST", timeframe="1m")
    signal_rows = result[result["timestamp"] == pd.Timestamp("2026-01-01 10:06:00+00:00")]
    assert len(signal_rows) == 1
    assert signal_rows.iloc[0]["fail_reason"] == "range"
    assert not signal_rows.iloc[0]["is_signal"]


def test_small_range_passes_with_small_tick():
    """Range=0.04, tick=0.01 → min_range=0.02 → range filter passed."""
    df = _make_candle_df(candle_range=0.04)
    params = _params_for_tick(tick_size=0.01)
    result = HammerDetector(params).detect_all(df, instrument="TEST", timeframe="1m")
    signal_rows = result[result["timestamp"] == pd.Timestamp("2026-01-01 10:06:00+00:00")]
    assert len(signal_rows) == 1
    # Should not fail on range
    assert signal_rows.iloc[0]["fail_reason"] != "range"


def test_tick_size_stored_in_output():
    """tick_size column is present and equals the configured tick."""
    df = _make_candle_df(candle_range=0.04)
    params = _params_for_tick(tick_size=0.01)
    result = HammerDetector(params).detect_all(df)
    assert "tick_size" in result.columns
    assert "tick_size_source" in result.columns
    assert result["tick_size"].nunique() == 1
    assert abs(result["tick_size"].iloc[0] - 0.01) < 1e-9
    assert result["tick_size_source"].nunique() == 1
    assert result["tick_size_source"].iloc[0] == "cli"


def test_fallback_tick_used_when_no_tick_size():
    """When tick_size=None, effective tick = fallback_tick."""
    df = _make_candle_df(candle_range=0.04)
    params = _params_for_tick(tick_size=None)
    result = HammerDetector(params).detect_all(df)
    assert result["tick_size"].nunique() == 1
    assert abs(result["tick_size"].iloc[0] - 0.5) < 1e-9
    assert result["tick_size_source"].iloc[0] == "fallback"
