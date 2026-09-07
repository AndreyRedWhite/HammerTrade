"""Research runner: dispatches strategy-specific backtests and attaches regime."""
from __future__ import annotations

import pandas as pd

from src.research.regime import compute_regime_context


def run_research(
    strategy_name: str,
    config_dict: dict,
) -> tuple[list[dict], list[dict]]:
    """Run research for a given strategy and config.

    Args:
        strategy_name: Registered strategy name (e.g. 'opening_range_breakout').
        config_dict: Full config dict (loaded from YAML).

    Returns:
        Tuple of (scenario_results, all_trades).
    """
    if strategy_name == "opening_range_breakout":
        return _run_orb(config_dict)
    else:
        raise ValueError(f"Unknown strategy for research runner: '{strategy_name}'")


def _run_orb(config_dict: dict) -> tuple[list[dict], list[dict]]:
    """Run ORB backtest and optionally attach regime labels."""
    from src.strategies.opening_range_breakout.backtest import run_orb_backtest

    candles_csv = config_dict["data"]["candles_csv"]
    scenario_results, all_trades = run_orb_backtest(candles_csv, config_dict)

    regime_enabled = config_dict.get("regime", {}).get("enabled", False)
    if regime_enabled and all_trades:
        scenario_results, all_trades = _attach_regime(
            candles_csv, config_dict, scenario_results, all_trades
        )

    return scenario_results, all_trades


def _attach_regime(
    candles_csv: str,
    config_dict: dict,
    scenario_results: list[dict],
    all_trades: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Attach regime labels to trades and augment scenario results with regime breakdown."""
    window_days = config_dict.get("regime", {}).get("window_days", 20)

    candles = pd.read_csv(candles_csv)
    if not pd.api.types.is_datetime64_any_dtype(candles["timestamp"]):
        candles["timestamp"] = pd.to_datetime(candles["timestamp"], utc=True)
    elif candles["timestamp"].dt.tz is None:
        candles["timestamp"] = candles["timestamp"].dt.tz_localize("UTC")

    regime_context_df = compute_regime_context(candles, window_days=window_days)
    regime_map = dict(zip(regime_context_df["date"].astype(str), regime_context_df["regime"]))

    # Attach regime to each trade
    for trade in all_trades:
        date_str = str(trade.get("date", ""))[:10]
        trade["regime"] = regime_map.get(date_str, "NORMAL")

    # Build per-scenario regime breakdown
    from collections import defaultdict
    scenario_regime_pnl: dict = defaultdict(lambda: defaultdict(list))
    for trade in all_trades:
        sid = trade["scenario_id"]
        regime = trade.get("regime", "NORMAL")
        scenario_regime_pnl[sid][regime].append(float(trade.get("pnl_rub", 0)))

    for result in scenario_results:
        sid = result["scenario_id"]
        breakdown = {}
        for regime, pnls in scenario_regime_pnl[sid].items():
            wins = sum(1 for p in pnls if p > 0)
            breakdown[regime] = {
                "trades": len(pnls),
                "wins": wins,
                "net_pnl": round(sum(pnls), 2),
                "winrate": round(wins / len(pnls), 4) if pnls else 0.0,
            }
        result["regime_breakdown"] = breakdown

    return scenario_results, all_trades
