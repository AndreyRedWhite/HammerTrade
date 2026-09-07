"""ORB backtest runner: iterates over all scenario combinations and returns results."""
from __future__ import annotations

import itertools
import statistics
from datetime import time
from typing import Optional
import pandas as pd

from src.strategies.opening_range_breakout.strategy import (
    OpeningRangeBreakoutStrategy,
    simulate_trade,
    _parse_time,
    _to_msk,
)
from src.research.metrics import compute_metrics


def run_orb_backtest(
    candles_csv: str,
    config_dict: dict,
) -> tuple[list[dict], list[dict]]:
    """Run ORB backtest over all scenario combinations.

    Args:
        candles_csv: Path to CSV file with columns: timestamp, open, high, low, close, volume.
        config_dict: Config dict (from YAML). Key sections: opening_ranges, directions,
                     take.r, entry, stop, exit, commission.

    Returns:
        Tuple of (scenario_results, all_trades) where each element is a list of dicts.
    """
    # Load candles
    if isinstance(candles_csv, str):
        candles = pd.read_csv(candles_csv)
    else:
        candles = candles_csv.copy()

    if candles.empty:
        return [], []

    if not pd.api.types.is_datetime64_any_dtype(candles["timestamp"]):
        candles["timestamp"] = pd.to_datetime(candles["timestamp"], utc=True)
    elif candles["timestamp"].dt.tz is None:
        candles["timestamp"] = candles["timestamp"].dt.tz_localize("UTC")

    # Extract scenario parameters from config
    opening_ranges = config_dict.get("opening_ranges", [["10:00", "10:15"]])
    directions = config_dict.get("directions", ["long", "short"])
    take_rs = config_dict.get("take", {}).get("r", [1.5])
    if not isinstance(take_rs, list):
        take_rs = [take_rs]

    ticker = config_dict.get("experiment", {}).get("ticker", "SiM6")
    timeframe = config_dict.get("experiment", {}).get("timeframe", "1m")
    min_range_points = config_dict.get("stop", {}).get("min_range_points", 10.0)
    false_breakout_bars = config_dict.get("entry", {}).get("min_false_breakout_bars", 2)
    time_exit_str = config_dict.get("exit", {}).get("time_exit", "18:40")
    time_exit_msk = _parse_time(time_exit_str)
    # Costs are MANDATORY and must come from the config. They used to be read
    # here into local variables and then never passed to simulate_trade(), which
    # silently fell back to module constants of 0.05 RUB and 10.0 RUB/point —
    # so a config specifying the correct 38.0 / 1.0 changed nothing at all.
    # Defaulting them is what made that failure invisible, so there is no default.
    commission_cfg = config_dict.get("commission", {}) or {}
    if "rub_per_trade" not in commission_cfg or "point_value_rub" not in commission_cfg:
        raise ValueError(
            "ORB backtest config must set commission.rub_per_trade (ROUND TRIP, in RUB) "
            "and commission.point_value_rub. Resolve the point value from instrument "
            "specs (src.costs.point_value_rub) — for SiM6 it is 1.0, not 10.0."
        )
    commission_rub = float(commission_cfg["rub_per_trade"])
    point_value_rub = float(commission_cfg["point_value_rub"])

    # Build period string
    msk_dates = candles["timestamp"].apply(_to_msk)
    period_start = msk_dates.min().date()
    period_end = msk_dates.max().date()
    period = f"{period_start} to {period_end}"

    scenario_results = []
    all_trades = []
    scenario_id = 0

    for or_range_def, direction, take_r in itertools.product(opening_ranges, directions, take_rs):
        or_start_str, or_end_str = or_range_def[0], or_range_def[1]
        scenario_id += 1

        scenario_config = {
            "or_start_msk": or_start_str,
            "or_end_msk": or_end_str,
            "direction": direction,
            "take_r": take_r,
            "min_range_points": min_range_points,
            "false_breakout_bars": false_breakout_bars,
            "time_exit_msk": time_exit_str,
        }

        strategy = OpeningRangeBreakoutStrategy(scenario_config)
        context = {"ticker": ticker}
        signals = strategy.generate_signals(candles, context)

        scenario_trades = []
        for signal in signals:
            # Get post-OR candles for simulation: candles from entry bar onwards
            sig_ts = signal.timestamp
            post_candles = candles[candles["timestamp"] >= sig_ts].reset_index(drop=True)

            trade_outcome = simulate_trade(
                signal,
                post_candles,
                time_exit_msk,
                point_value_rub=point_value_rub,
                commission_rub=commission_rub,
            )

            trade_row = {
                "scenario_id": scenario_id,
                "or_window": f"{or_start_str}-{or_end_str}",
                "direction": direction.upper(),
                "take_r": take_r,
                "ticker": ticker,
                "date": signal.metadata.get("date", ""),
                "entry_msk": str(trade_outcome["entry_msk"]),
                "exit_msk": str(trade_outcome["exit_msk"]),
                "entry_price": trade_outcome["entry_price"],
                "stop_price": trade_outcome["stop_price"],
                "take_price": trade_outcome["take_price"],
                "exit_price": trade_outcome["exit_price"],
                "exit_reason": trade_outcome["exit_reason"],
                "pnl_points": trade_outcome["pnl_points"],
                "pnl_rub": trade_outcome["pnl_rub"],
                "bars_held": trade_outcome["bars_held"],
                "or_high": signal.metadata.get("or_high"),
                "or_low": signal.metadata.get("or_low"),
                "or_range": signal.metadata.get("or_range"),
                "regime": signal.metadata.get("regime", ""),
            }
            scenario_trades.append(trade_row)
            all_trades.append(trade_row)

        # Compute metrics for this scenario
        metrics = compute_metrics(scenario_trades)

        or_window_label = f"{or_start_str}-{or_end_str}"
        scenario_result = {
            "scenario_id": scenario_id,
            "or_window": or_window_label,
            "direction": direction.upper(),
            "take_r": take_r,
            "ticker": ticker,
            "timeframe": timeframe,
            "period": period,
            "scenario": f"ORB_{or_window_label}_{direction.upper()}_R{take_r}",
            **metrics,
        }
        scenario_results.append(scenario_result)

    return scenario_results, all_trades
