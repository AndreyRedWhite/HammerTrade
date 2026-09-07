"""VWAP and ATR computation utilities for research strategies."""
from __future__ import annotations

import pandas as pd
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def compute_session_vwap(candles: pd.DataFrame, tz: ZoneInfo = MSK) -> pd.Series:
    """Compute anchored session VWAP, reset at each MSK trading day.

    VWAP = cumsum(typical_price * volume) / cumsum(volume) within each day.
    typical_price = (high + low + close) / 3

    candles must have: timestamp (UTC, tz-aware), high, low, close, volume.
    Returns a pd.Series indexed same as candles.
    """
    if candles.empty:
        return pd.Series(dtype=float, index=candles.index)

    df = candles.copy()

    # Ensure timestamp is tz-aware UTC
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    elif df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

    # Convert to MSK to get the trading day
    df["_msk_dt"] = df["timestamp"].dt.tz_convert(tz)
    df["_msk_date"] = df["_msk_dt"].dt.date

    # Typical price
    df["_tp"] = (df["high"] + df["low"] + df["close"]) / 3.0
    df["_tp_vol"] = df["_tp"] * df["volume"]

    # Cumulative sums within each day
    df["_cum_tp_vol"] = df.groupby("_msk_date")["_tp_vol"].cumsum()
    df["_cum_vol"] = df.groupby("_msk_date")["volume"].cumsum()

    vwap = df["_cum_tp_vol"] / df["_cum_vol"].replace(0, float("nan"))
    vwap.index = candles.index
    return vwap


def compute_atr(candles: pd.DataFrame, window: int = 14) -> pd.Series:
    """Compute Average True Range.

    TR = max(high-low, abs(high-prev_close), abs(low-prev_close))
    ATR = TR.rolling(window).mean()

    Returns a pd.Series indexed same as candles.
    """
    if candles.empty:
        return pd.Series(dtype=float, index=candles.index)

    df = candles.copy()
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(window=window, min_periods=1).mean()
    atr.index = candles.index
    return atr
