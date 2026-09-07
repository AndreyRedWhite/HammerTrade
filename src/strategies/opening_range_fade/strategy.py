"""Opening Range Fade (ORF) strategy for MOEX Si futures.

Fades false breakouts above the Opening Range high.

Signal for SHORT fade (false breakout up):
1. After OR window closes, watch for candles with high > OR_high (breakout)
2. Within n_return_bars after breakout, price returns back inside OR (close < OR_high)
3. Enter short at the return candle's close
4. Stop = max high of breakout candles + 1pt
5. Take = OR midpoint OR entry - (stop - entry) * 1.0 (configurable)
"""
from __future__ import annotations

import itertools
from datetime import time
from zoneinfo import ZoneInfo

import pandas as pd

from src.research.metrics import compute_metrics
from src.strategies.opening_range_breakout.strategy import compute_opening_range

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

        if c_msk.time() >= time_exit_msk:
            exit_price = float(candle["open"])
            exit_reason = "TIME_EXIT"
            break

        if float(candle["high"]) >= stop_price:
            exit_price = stop_price
            exit_reason = "STOP"
            break

        if float(candle["low"]) <= take_price:
            exit_price = take_price
            exit_reason = "TAKE"
            break

    if exit_price is None:
        if len(post_candles) > 0:
            exit_price = float(post_candles.iloc[-1]["close"])
            exit_reason = "TIME_EXIT"
            bars_held = len(post_candles)
        else:
            exit_price = entry_price
            exit_reason = "TIME_EXIT"

    pnl_points = entry_price - exit_price
    pnl_rub = pnl_points * POINT_VALUE_RUB - COMMISSION_RUB

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


def run_orf_backtest(
    candles: pd.DataFrame,
    or_windows: list[list[str]],
    n_return_bars_list: list[int],
    take_mode_list: list[str],
    time_exit_str: str = "18:40",
    max_trades_per_day: int = 1,
    regime_df: pd.DataFrame | None = None,
) -> tuple[list[dict], list[dict]]:
    """Run Opening Range Fade backtest over all scenario combinations.

    Args:
        candles: DataFrame with columns: timestamp, open, high, low, close, volume.
        or_windows: List of [or_start, or_end] pairs (MSK time strings).
        n_return_bars_list: How many candles after breakout to look for return.
        take_mode_list: ["midpoint", "one_r"] — how to compute take price.
        time_exit_str: Force-close time in MSK.
        max_trades_per_day: Max trades per day.
        regime_df: Optional regime DataFrame.

    Returns:
        (scenario_results, all_trades)
    """
    df = candles.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    elif df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

    df = df.sort_values("timestamp").reset_index(drop=True)
    df["_msk_dt"] = df["timestamp"].apply(_to_msk)
    df["_msk_date"] = df["_msk_dt"].dt.date

    time_exit_msk = _parse_time(time_exit_str)

    regime_lookup: dict = {}
    if regime_df is not None and not regime_df.empty:
        for _, row in regime_df.iterrows():
            regime_lookup[row["date"]] = row["regime"]

    scenario_results = []
    all_trades: list[dict] = []
    scenario_id = 0

    for or_window, n_return, take_mode in itertools.product(or_windows, n_return_bars_list, take_mode_list):
        or_start_str, or_end_str = or_window[0], or_window[1]
        or_start_t = _parse_time(or_start_str)
        or_end_t = _parse_time(or_end_str)
        scenario_id += 1
        or_label = f"{or_start_str}-{or_end_str}"
        scenario_name = f"ORF_{or_label}_n{n_return}_{take_mode}"
        scenario_trades: list[dict] = []

        for date, day_df in df.groupby("_msk_date"):
            day_df = day_df.sort_values("timestamp").reset_index(drop=True)
            trades_today = 0
            regime = regime_lookup.get(date, "NORMAL")

            # Compute OR for the day using strategy utility
            try:
                import pytz
                # Build a sub-df for compute_opening_range (needs timestamp column)
                or_info = compute_opening_range(day_df, or_start_t, or_end_t)
            except Exception:
                continue

            if or_info is None:
                continue

            or_high = or_info["or_high"]
            or_low = or_info["or_low"]
            or_mid = (or_high + or_low) / 2.0

            # Post-OR candles
            post_or_mask = day_df["_msk_dt"].apply(lambda t: t.time() >= or_end_t)
            post_or = day_df[post_or_mask].reset_index(drop=True)

            if post_or.empty:
                continue

            # Scan for breakout + return
            i = 0
            while i < len(post_or) and trades_today < max_trades_per_day:
                candle = post_or.iloc[i]
                msk_t = candle["_msk_dt"].time()

                if msk_t >= time_exit_msk:
                    break

                # Check breakout above OR_high
                if float(candle["high"]) <= or_high:
                    i += 1
                    continue

                # Breakout detected — record max breakout high
                breakout_high = float(candle["high"])
                # Look for return within n_return_bars
                signal_found = False
                for j in range(i, min(i + n_return, len(post_or))):
                    ret_candle = post_or.iloc[j]
                    breakout_high = max(breakout_high, float(ret_candle["high"]))
                    ret_msk = ret_candle["_msk_dt"].time()
                    if ret_msk >= time_exit_msk:
                        break
                    # Return: close back inside OR (below OR_high)
                    if float(ret_candle["close"]) < or_high:
                        signal_found = True
                        signal_candle = ret_candle
                        break

                if not signal_found:
                    i += 1
                    continue

                # Build the trade
                entry_price = float(signal_candle["close"])
                stop_price = breakout_high + 1.0  # 1pt beyond breakout extreme

                risk = stop_price - entry_price
                if risk <= 0:
                    i += 1
                    continue

                if take_mode == "midpoint":
                    take_price = or_mid
                else:  # one_r
                    take_price = entry_price - risk

                # Ensure take is below entry for a SHORT
                if take_price >= entry_price:
                    take_price = entry_price - risk

                # Simulate
                sig_ts = signal_candle["timestamp"]
                post_trade = df[df["timestamp"] > sig_ts].reset_index(drop=True)

                trade = _simulate_short_trade(
                    entry_price, stop_price, take_price, post_trade, time_exit_msk
                )

                entry_msk_ts = _to_msk(signal_candle["timestamp"])
                trade_row = {
                    "scenario": scenario_name,
                    "scenario_id": scenario_id,
                    "or_window": or_label,
                    "n_return_bars": n_return,
                    "take_mode": take_mode,
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
                    "or_high": or_high,
                    "or_low": or_low,
                    "regime": regime,
                }
                scenario_trades.append(trade_row)
                all_trades.append(trade_row)
                trades_today += 1
                break  # max 1 trade per day — after first signal stop scanning

        metrics = compute_metrics(scenario_trades)
        scenario_results.append(
            {
                "scenario": scenario_name,
                "scenario_id": scenario_id,
                "or_window": or_label,
                "n_return_bars": n_return,
                "take_mode": take_mode,
                "direction": "SHORT",
                **metrics,
            }
        )

    return scenario_results, all_trades
