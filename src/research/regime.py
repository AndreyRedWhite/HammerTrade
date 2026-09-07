"""Day regime classifier for research purposes."""
from __future__ import annotations

from enum import Enum
from datetime import time
import pandas as pd
import pytz

MSK = pytz.timezone("Europe/Moscow")


class DayRegime(str, Enum):
    LOW_VOL_RANGE = "LOW_VOL_RANGE"
    NORMAL = "NORMAL"
    HIGH_VOL_TREND = "HIGH_VOL_TREND"
    NEWS_SHOCK_PROXY = "NEWS_SHOCK_PROXY"


def _to_msk(ts: pd.Timestamp) -> pd.Timestamp:
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(MSK)


def classify_day_regime(day_candles: pd.DataFrame, context: dict) -> DayRegime:
    """Classify the regime for a single trading day.

    Args:
        day_candles: 1m candles for a single trading day (UTC timestamps).
        context: dict with optional keys:
            - median_daily_range: float (rolling 20-day median)
            - median_first_hour_range: float
            - atr_60m: float (avg ATR over first 60 min)

    Returns:
        DayRegime enum value.

    Rules:
        NEWS_SHOCK_PROXY:
            opening_gap > 3 * median_daily_range * 0.1
            OR first_hour_range > 2.5 * median_first_hour_range
        HIGH_VOL_TREND:
            daily_range > 2.0 * median_daily_range
            AND close is in top/bottom 20% of day's range
        LOW_VOL_RANGE:
            daily_range < 0.5 * median_daily_range
        NORMAL: otherwise
    """
    if day_candles.empty:
        return DayRegime.NORMAL

    # Ensure timestamps are parsed
    candles = day_candles.copy()
    if not pd.api.types.is_datetime64_any_dtype(candles["timestamp"]):
        candles["timestamp"] = pd.to_datetime(candles["timestamp"], utc=True)
    elif candles["timestamp"].dt.tz is None:
        candles["timestamp"] = candles["timestamp"].dt.tz_localize("UTC")

    candles = candles.sort_values("timestamp")

    daily_high = float(candles["high"].max())
    daily_low = float(candles["low"].min())
    daily_range = daily_high - daily_low
    daily_close = float(candles.iloc[-1]["close"])
    daily_open = float(candles.iloc[0]["open"])

    median_daily_range = float(context.get("median_daily_range", daily_range or 1.0))
    median_first_hour_range = float(context.get("median_first_hour_range", 1.0))

    # Compute first-hour range (first 60 1m candles, or up to session end)
    msk_times = candles["timestamp"].apply(_to_msk)
    first_hour_mask = msk_times.apply(lambda t: t.time() < time(11, 0))
    first_hour = candles[first_hour_mask]
    if not first_hour.empty:
        first_hour_range = float(first_hour["high"].max()) - float(first_hour["low"].min())
    else:
        first_hour_range = 0.0

    # Opening gap: compare today's open vs previous close is not available here,
    # so use the gap between first candle open and the second candle open as a proxy.
    # If prior_close is provided in context, use that.
    prior_close = context.get("prior_close", daily_open)
    opening_gap = abs(daily_open - prior_close)

    # NEWS_SHOCK_PROXY
    gap_threshold = 3.0 * median_daily_range * 0.1
    if median_first_hour_range > 0:
        first_hour_shock = first_hour_range > 2.5 * median_first_hour_range
    else:
        first_hour_shock = False

    if opening_gap > gap_threshold or first_hour_shock:
        return DayRegime.NEWS_SHOCK_PROXY

    # HIGH_VOL_TREND
    if daily_range > 0 and median_daily_range > 0:
        if daily_range > 2.0 * median_daily_range:
            # Close in top 20% → bullish trend
            if daily_range > 0:
                close_pct = (daily_close - daily_low) / daily_range
                if close_pct >= 0.80 or close_pct <= 0.20:
                    return DayRegime.HIGH_VOL_TREND

    # LOW_VOL_RANGE
    if median_daily_range > 0 and daily_range < 0.5 * median_daily_range:
        return DayRegime.LOW_VOL_RANGE

    return DayRegime.NORMAL


def compute_regime_context(all_candles: pd.DataFrame, window_days: int = 20) -> pd.DataFrame:
    """Compute per-day regime context using a rolling window.

    Args:
        all_candles: All 1m candles (UTC timestamps), columns: timestamp, open, high, low, close.
        window_days: Rolling window for median computations (default 20 trading days).

    Returns:
        DataFrame indexed by date with columns:
            date, daily_range, first_hour_range, median_daily_range,
            median_first_hour_range, prior_close, regime
    """
    if all_candles.empty:
        return pd.DataFrame()

    candles = all_candles.copy()
    if not pd.api.types.is_datetime64_any_dtype(candles["timestamp"]):
        candles["timestamp"] = pd.to_datetime(candles["timestamp"], utc=True)
    elif candles["timestamp"].dt.tz is None:
        candles["timestamp"] = candles["timestamp"].dt.tz_localize("UTC")

    candles["msk_dt"] = candles["timestamp"].apply(_to_msk)
    candles["msk_date"] = candles["msk_dt"].dt.date

    day_stats = []
    for date, day_df in candles.groupby("msk_date"):
        day_df = day_df.sort_values("timestamp")
        daily_high = float(day_df["high"].max())
        daily_low = float(day_df["low"].min())
        daily_range = daily_high - daily_low
        daily_open = float(day_df.iloc[0]["open"])
        daily_close = float(day_df.iloc[-1]["close"])

        first_hour_mask = day_df["msk_dt"].apply(lambda t: t.time() < time(11, 0))
        first_hour = day_df[first_hour_mask]
        if not first_hour.empty:
            first_hour_range = float(first_hour["high"].max()) - float(first_hour["low"].min())
        else:
            first_hour_range = daily_range

        day_stats.append({
            "date": date,
            "daily_range": daily_range,
            "first_hour_range": first_hour_range,
            "daily_open": daily_open,
            "daily_close": daily_close,
        })

    stats_df = pd.DataFrame(day_stats).sort_values("date").reset_index(drop=True)

    if stats_df.empty:
        return stats_df

    # Rolling medians
    stats_df["median_daily_range"] = (
        stats_df["daily_range"].rolling(window=window_days, min_periods=1).median()
    )
    stats_df["median_first_hour_range"] = (
        stats_df["first_hour_range"].rolling(window=window_days, min_periods=1).median()
    )
    stats_df["prior_close"] = stats_df["daily_close"].shift(1).fillna(stats_df["daily_open"])

    # Classify each day
    regimes = []
    day_candles_by_date = {date: df for date, df in candles.groupby("msk_date")}

    for _, row in stats_df.iterrows():
        context = {
            "median_daily_range": row["median_daily_range"],
            "median_first_hour_range": row["median_first_hour_range"],
            "prior_close": row["prior_close"],
        }
        day_df = day_candles_by_date.get(row["date"], pd.DataFrame())
        regime = classify_day_regime(day_df, context)
        regimes.append(regime.value)

    stats_df["regime"] = regimes
    return stats_df
