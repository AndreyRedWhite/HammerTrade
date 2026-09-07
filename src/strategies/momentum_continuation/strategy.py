"""Momentum Continuation strategy for MOEX Si futures.

Signal for SHORT:
- Candle range >= atr_mult * ATR (14-bar)
- Close is in bottom 25% of range: (close - low) / range <= 0.25
- Volume >= vol_mult * 20-bar rolling mean volume
- => Strong bearish impulse candle

Entry: close of impulse candle (SHORT)
Stop: high of impulse candle
Take: entry - (stop - entry) * take_r
"""
from __future__ import annotations

import itertools
from datetime import time
from zoneinfo import ZoneInfo

import pandas as pd

from src.research.metrics import compute_metrics
from src.research.vwap import compute_atr

MSK = ZoneInfo("Europe/Moscow")
COMMISSION_RUB = 0.05
POINT_VALUE_RUB = 10.0


def _to_msk(ts: pd.Timestamp) -> pd.Timestamp:
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(MSK)


def _parse_time(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _simulate_short_trade(
    entry_price: float,
    stop_price: float,
    take_price: float,
    post_candles: pd.DataFrame,
    time_exit_msk: time,
) -> dict:
    """Simulate a short trade given entry/stop/take prices and forward candles."""
    exit_price = None
    exit_reason = None
    bars_held = 0

    for _, candle in post_candles.iterrows():
        bars_held += 1
        c_msk = _to_msk(candle["timestamp"])

        # Time exit first
        if c_msk.time() >= time_exit_msk:
            exit_price = float(candle["open"])
            exit_reason = "TIME_EXIT"
            break

        # Stop: high >= stop_price
        if float(candle["high"]) >= stop_price:
            exit_price = stop_price
            exit_reason = "STOP"
            break

        # Take: low <= take_price
        if float(candle["low"]) <= take_price:
            exit_price = take_price
            exit_reason = "TAKE"
            break

    if exit_price is None:
        # End of data
        if len(post_candles) > 0:
            exit_price = float(post_candles.iloc[-1]["close"])
            exit_reason = "TIME_EXIT"
            bars_held = len(post_candles)
        else:
            exit_price = entry_price
            exit_reason = "TIME_EXIT"

    pnl_points = entry_price - exit_price
    pnl_rub = pnl_points * POINT_VALUE_RUB - COMMISSION_RUB

    # Exit timestamp
    exit_msk = None
    if bars_held > 0 and len(post_candles) >= bars_held:
        exit_msk = _to_msk(post_candles.iloc[bars_held - 1]["timestamp"])

    return {
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pnl_points": pnl_points,
        "pnl_rub": pnl_rub,
        "bars_held": bars_held,
        "exit_msk": exit_msk,
    }


def run_momentum_backtest(
    candles: pd.DataFrame,
    atr_mult_list: list[float],
    vol_mult_list: list[float],
    take_r_list: list[float],
    atr_window: int = 14,
    vol_window: int = 20,
    time_exit_str: str = "18:40",
    max_trades_per_day: int = 1,
    regime_df: pd.DataFrame | None = None,
) -> tuple[list[dict], list[dict]]:
    """Run Momentum Continuation backtest over all scenario combinations.

    Args:
        candles: DataFrame with columns: timestamp, open, high, low, close, volume.
        atr_mult_list: List of ATR multipliers for signal range filter.
        vol_mult_list: List of volume multipliers for signal volume filter.
        take_r_list: List of R-multiple targets.
        atr_window: ATR rolling window (default 14).
        vol_window: Volume rolling mean window (default 20).
        time_exit_str: Force-close time in MSK (default "18:40").
        max_trades_per_day: Max trades per day (default 1).
        regime_df: Optional DataFrame from compute_regime_context().

    Returns:
        (scenario_results, all_trades) — lists of dicts.
    """
    df = candles.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    elif df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

    df = df.sort_values("timestamp").reset_index(drop=True)

    # Compute ATR and rolling volume mean over the entire dataset (no look-ahead in usage)
    df["_atr"] = compute_atr(df, window=atr_window)
    df["_vol_mean"] = df["volume"].rolling(window=vol_window, min_periods=1).mean()

    # MSK date
    df["_msk_dt"] = df["timestamp"].apply(_to_msk)
    df["_msk_date"] = df["_msk_dt"].dt.date

    time_exit_msk = _parse_time(time_exit_str)

    # Build regime lookup
    regime_lookup: dict = {}
    if regime_df is not None and not regime_df.empty:
        for _, row in regime_df.iterrows():
            regime_lookup[row["date"]] = row["regime"]

    scenario_results = []
    all_trades: list[dict] = []
    scenario_id = 0

    for atr_mult, vol_mult, take_r in itertools.product(atr_mult_list, vol_mult_list, take_r_list):
        scenario_id += 1
        scenario_name = f"MC_atr{atr_mult}_vol{vol_mult}_r{take_r}"
        scenario_trades: list[dict] = []

        for date, day_df in df.groupby("_msk_date"):
            day_df = day_df.sort_values("timestamp").reset_index(drop=True)
            trades_today = 0
            regime = regime_lookup.get(date, "NORMAL")

            for i, row in day_df.iterrows():
                if trades_today >= max_trades_per_day:
                    break

                msk_t = row["_msk_dt"].time()
                # No new entry at or after time_exit
                if msk_t >= time_exit_msk:
                    break

                # Need at least atr_window bars of history
                # i is the positional index in day_df; we need global index context
                # Use the precomputed ATR value
                atr_val = float(row["_atr"])
                vol_mean = float(row["_vol_mean"])

                if atr_val <= 0 or vol_mean <= 0:
                    continue

                candle_high = float(row["high"])
                candle_low = float(row["low"])
                candle_close = float(row["close"])
                candle_vol = float(row["volume"])

                candle_range = candle_high - candle_low
                if candle_range <= 0:
                    continue

                # Signal conditions
                range_ok = candle_range >= atr_mult * atr_val
                close_pct = (candle_close - candle_low) / candle_range
                close_bearish = close_pct <= 0.25
                vol_ok = candle_vol >= vol_mult * vol_mean

                if not (range_ok and close_bearish and vol_ok):
                    continue

                # Signal confirmed — enter SHORT on this candle's close
                entry_price = candle_close
                stop_price = candle_high
                risk = stop_price - entry_price
                if risk <= 0:
                    continue
                take_price = entry_price - risk * take_r

                # Simulate: use candles strictly after this signal candle
                sig_ts = row["timestamp"]
                post_candles = df[df["timestamp"] > sig_ts].reset_index(drop=True)

                trade = _simulate_short_trade(
                    entry_price, stop_price, take_price, post_candles, time_exit_msk
                )

                entry_msk_ts = _to_msk(row["timestamp"])

                trade_row = {
                    "scenario": scenario_name,
                    "scenario_id": scenario_id,
                    "atr_mult": atr_mult,
                    "vol_mult": vol_mult,
                    "take_r": take_r,
                    "direction": "SHORT",
                    "date": str(date),
                    "entry_msk": str(entry_msk_ts),
                    "exit_msk": str(trade["exit_msk"]),
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "take_price": take_price,
                    "exit_price": trade["exit_price"],
                    "exit_reason": trade["exit_reason"],
                    "pnl_rub": round(trade["pnl_rub"], 4),
                    "pnl_points": round(trade["pnl_points"], 6),
                    "bars_held": trade["bars_held"],
                    "candle_range": round(candle_range, 2),
                    "atr_val": round(atr_val, 2),
                    "regime": regime,
                    "or_window": "N/A",
                }
                scenario_trades.append(trade_row)
                all_trades.append(trade_row)
                trades_today += 1

        metrics = compute_metrics(scenario_trades)
        scenario_results.append(
            {
                "scenario": scenario_name,
                "scenario_id": scenario_id,
                "atr_mult": atr_mult,
                "vol_mult": vol_mult,
                "take_r": take_r,
                "direction": "SHORT",
                **metrics,
            }
        )

    return scenario_results, all_trades
