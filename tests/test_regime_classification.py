"""Tests for day regime classifier (Part G, 4 tests)."""
from __future__ import annotations

import pytest
import pandas as pd
import pytz
from datetime import datetime, timedelta

from src.research.regime import classify_day_regime, DayRegime

MSK = pytz.timezone("Europe/Moscow")
UTC = pytz.utc


def make_day(
    price_start: float,
    price_end: float,
    day_high: float,
    day_low: float,
    first_hour_high: float,
    first_hour_low: float,
    date_str: str = "2026-02-10",
    session_start_h: int = 10,
    prior_open: float = None,
) -> pd.DataFrame:
    """Build a minimal day candle DataFrame for regime testing."""
    year, month, day = [int(x) for x in date_str.split("-")]
    base_dt = MSK.localize(datetime(year, month, day, session_start_h, 0, 0))

    candles = []
    # First hour candles (10:00-10:59)
    for i in range(60):
        dt_utc = (base_dt + timedelta(minutes=i)).astimezone(UTC)
        if i == 0:
            h = first_hour_high
            l = first_hour_low
            o = price_start if prior_open is None else price_start
        else:
            h = first_hour_high
            l = first_hour_low
            o = price_start
        candles.append({
            "timestamp": pd.Timestamp(dt_utc),
            "open": o,
            "high": h,
            "low": l,
            "close": price_start,
            "volume": 100,
        })

    # Rest of day (11:00-18:44): use day_high/day_low
    for i in range(60, 60 + 460):
        dt_utc = (base_dt + timedelta(minutes=i)).astimezone(UTC)
        if i == 60 + 459:  # last candle
            candles.append({
                "timestamp": pd.Timestamp(dt_utc),
                "open": price_end,
                "high": max(day_high, price_end),
                "low": min(day_low, price_end),
                "close": price_end,
                "volume": 100,
            })
        else:
            candles.append({
                "timestamp": pd.Timestamp(dt_utc),
                "open": price_start,
                "high": day_high,
                "low": day_low,
                "close": price_start,
                "volume": 100,
            })

    return pd.DataFrame(candles)


def test_low_vol_range():
    """Low vol day (range = 0.3 * median) → LOW_VOL_RANGE."""
    median_daily_range = 200.0
    # Day range ~ 60 (= 0.3 * 200)
    day_df = make_day(82500, 82530, 82560, 82500, 82550, 82510)
    context = {
        "median_daily_range": median_daily_range,
        "median_first_hour_range": 80.0,
        "prior_close": 82500.0,
    }
    regime = classify_day_regime(day_df, context)
    assert regime == DayRegime.LOW_VOL_RANGE


def test_news_shock_proxy_first_hour():
    """Large first-hour range (>2.5x median) → NEWS_SHOCK_PROXY."""
    median_daily_range = 200.0
    median_first_hour_range = 80.0

    # First hour range = 300 > 2.5 * 80 = 200
    day_df = make_day(
        82500, 82500,
        day_high=82800,
        day_low=82200,
        first_hour_high=82800,
        first_hour_low=82500,
    )
    context = {
        "median_daily_range": median_daily_range,
        "median_first_hour_range": median_first_hour_range,
        "prior_close": 82500.0,
    }
    regime = classify_day_regime(day_df, context)
    assert regime == DayRegime.NEWS_SHOCK_PROXY


def test_high_vol_trend():
    """High range + close near high → HIGH_VOL_TREND."""
    median_daily_range = 200.0

    # Day range = 500 > 2.0 * 200 = 400
    # Close near high: close = 82900, high = 82900, low = 82400 → close_pct = 1.0
    day_df = make_day(
        82400, 82900,
        day_high=82900,
        day_low=82400,
        first_hour_high=82600,
        first_hour_low=82450,
    )
    context = {
        "median_daily_range": median_daily_range,
        "median_first_hour_range": 100.0,
        "prior_close": 82400.0,
    }
    regime = classify_day_regime(day_df, context)
    assert regime == DayRegime.HIGH_VOL_TREND


def test_normal_day():
    """Normal day (range ≈ median, no extremes) → NORMAL."""
    median_daily_range = 200.0

    # Day range = 160 (0.8 * 200 → not low vol, not high vol)
    # First hour range = 70 (< 2.5 * 80 = 200)
    # Close in middle of range
    day_df = make_day(
        82500, 82580,
        day_high=82660,
        day_low=82500,
        first_hour_high=82570,
        first_hour_low=82500,
    )
    context = {
        "median_daily_range": median_daily_range,
        "median_first_hour_range": 80.0,
        "prior_close": 82500.0,
    }
    regime = classify_day_regime(day_df, context)
    assert regime == DayRegime.NORMAL
