"""VWAP Reversion strategy for MOEX Si futures.

Signal for SHORT:
- close > VWAP + distance_mult * ATR (price above VWAP)
- Enter short at signal candle close
- Stop = entry + stop_mult * ATR
- Take = VWAP (to_vwap mode) or entry - risk * take_r (one_r mode)

Up to max_trades_per_day per session.
"""
from __future__ import annotations

import itertools
from datetime import time
from zoneinfo import ZoneInfo

import pandas as pd

from src.research.metrics import compute_metrics
from src.research.vwap import compute_session_vwap, compute_atr

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
    vwap_series: pd.Series | None = None,
    take_mode: str = "to_vwap",
) -> dict:
    """Simulate a short trade. For to_vwap mode, take_price updates each bar."""
    exit_price = None
    exit_reason = None
    bars_held = 0

    for idx, candle in post_candles.iterrows():
        bars_held += 1
        c_msk = _to_msk(candle["timestamp"])

        # For to_vwap: update take dynamically (current VWAP)
        effective_take = take_price
        if take_mode == "to_vwap" and vwap_series is not None and idx in vwap_series.index:
            vwap_now = float(vwap_series.loc[idx])
            if not pd.isna(vwap_now) and vwap_now < entry_price:
                effective_take = vwap_now

        if c_msk.time() >= time_exit_msk:
            exit_price = float(candle["open"])
            exit_reason = "TIME_EXIT"
            break

        if float(candle["high"]) >= stop_price:
            exit_price = stop_price
            exit_reason = "STOP"
            break

        if float(candle["low"]) <= effective_take:
            exit_price = effective_take
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


def run_vwap_reversion_backtest(
    candles: pd.DataFrame,
    distance_mult_list: list[float],
    stop_mult_list: list[float],
    take_mode_list: list[str],
    atr_window: int = 14,
    time_exit_str: str = "18:40",
    max_trades_per_day: int = 3,
    regime_df: pd.DataFrame | None = None,
) -> tuple[list[dict], list[dict]]:
    """Run VWAP Reversion backtest over all scenario combinations.

    Args:
        candles: DataFrame with columns: timestamp, open, high, low, close, volume.
        distance_mult_list: ATR multiples above VWAP for signal.
        stop_mult_list: ATR multiples for stop placement.
        take_mode_list: ["to_vwap", "one_r_1_0", "one_r_1_5"]
        atr_window: ATR rolling window (default 14).
        time_exit_str: Force-close time in MSK.
        max_trades_per_day: Max trades per day (default 3).
        regime_df: Optional regime DataFrame.

    Returns:
        (scenario_results, all_trades)
    """
    if candles.empty:
        # Return empty results with correct scenario count
        results = []
        for dist_mult, stop_mult, take_mode in itertools.product(
            distance_mult_list, stop_mult_list, take_mode_list
        ):
            scenario_name = f"VR_d{dist_mult}_s{stop_mult}_{take_mode}"
            results.append({
                "scenario": scenario_name,
                "scenario_id": len(results) + 1,
                "distance_mult": dist_mult,
                "stop_mult": stop_mult,
                "take_mode": take_mode,
                "direction": "SHORT",
                **compute_metrics([]),
            })
        return results, []

    df = candles.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    elif df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

    df = df.sort_values("timestamp").reset_index(drop=True)

    # Compute VWAP and ATR over the entire dataset
    df["_vwap"] = compute_session_vwap(df)
    df["_atr"] = compute_atr(df, window=atr_window)
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

    for dist_mult, stop_mult, take_mode in itertools.product(
        distance_mult_list, stop_mult_list, take_mode_list
    ):
        scenario_id += 1
        scenario_name = f"VR_d{dist_mult}_s{stop_mult}_{take_mode}"
        scenario_trades: list[dict] = []

        for date, day_df in df.groupby("_msk_date"):
            day_df = day_df.sort_values("timestamp").reset_index(drop=True)
            trades_today = 0
            regime = regime_lookup.get(date, "NORMAL")

            for i, row in day_df.iterrows():
                if trades_today >= max_trades_per_day:
                    break

                msk_t = row["_msk_dt"].time()
                if msk_t >= time_exit_msk:
                    break

                vwap_val = float(row["_vwap"]) if not pd.isna(row["_vwap"]) else None
                atr_val = float(row["_atr"])
                close_val = float(row["close"])

                if vwap_val is None or vwap_val <= 0 or atr_val <= 0:
                    continue

                # Signal: close > VWAP + distance_mult * ATR
                threshold = vwap_val + dist_mult * atr_val
                if close_val <= threshold:
                    continue

                # Enter SHORT at signal close
                entry_price = close_val
                stop_price = entry_price + stop_mult * atr_val
                risk = stop_price - entry_price

                if risk <= 0:
                    continue

                # Take price
                if take_mode == "to_vwap":
                    # Dynamic — will track VWAP in simulation; initial target = current VWAP
                    take_price = vwap_val
                elif take_mode == "one_r_1_0":
                    take_price = entry_price - risk * 1.0
                elif take_mode == "one_r_1_5":
                    take_price = entry_price - risk * 1.5
                else:
                    take_price = vwap_val

                # Ensure take < entry for SHORT
                if take_price >= entry_price:
                    continue

                sig_ts = row["timestamp"]
                post_candles = df[df["timestamp"] > sig_ts].reset_index(drop=True)

                # Pass VWAP series for dynamic to_vwap mode
                vwap_post = None
                if take_mode == "to_vwap":
                    vwap_post = df.loc[df["timestamp"] > sig_ts, "_vwap"]

                trade = _simulate_short_trade(
                    entry_price,
                    stop_price,
                    take_price,
                    post_candles,
                    time_exit_msk,
                    vwap_series=vwap_post,
                    take_mode=take_mode,
                )

                entry_msk_ts = _to_msk(row["timestamp"])
                trade_row = {
                    "scenario": scenario_name,
                    "scenario_id": scenario_id,
                    "distance_mult": dist_mult,
                    "stop_mult": stop_mult,
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
                    "vwap_at_signal": round(vwap_val, 2),
                    "atr_at_signal": round(atr_val, 2),
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
                "distance_mult": dist_mult,
                "stop_mult": stop_mult,
                "take_mode": take_mode,
                "direction": "SHORT",
                **metrics,
            }
        )

    return scenario_results, all_trades
