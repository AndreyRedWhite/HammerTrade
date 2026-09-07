"""Research metrics computation utilities."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime
from typing import Optional

# StrategyResult is defined in base — re-export for convenience
from src.strategies.base import StrategyResult  # noqa: F401


def compute_max_drawdown(pnls: list[float]) -> float:
    """Compute maximum drawdown from a list of per-trade PnL values.

    Returns the maximum peak-to-trough drawdown (always non-negative).
    """
    if not pnls:
        return 0.0

    peak = 0.0
    cumulative = 0.0
    max_dd = 0.0

    for pnl in pnls:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_dd:
            max_dd = drawdown

    return max_dd


def compute_profitable_periods(trades: list[dict], period: str = "day") -> float:
    """Compute percentage of profitable periods.

    Args:
        trades: List of trade dicts with 'pnl_rub' and 'date' or 'entry_msk'.
        period: 'day' or 'week'.

    Returns:
        Fraction of profitable periods [0.0 .. 1.0].
    """
    if not trades:
        return 0.0

    period_pnl: dict = defaultdict(float)

    for t in trades:
        pnl = float(t.get("pnl_rub", 0))
        # Try to get date key
        date_str = t.get("date", "") or t.get("entry_msk", "")
        if not date_str:
            continue
        try:
            if period == "day":
                # Use date portion
                key = str(date_str)[:10]
            else:  # week
                dt = datetime.fromisoformat(str(date_str)[:10])
                # ISO week
                key = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
            period_pnl[key] += pnl
        except (ValueError, AttributeError):
            continue

    if not period_pnl:
        return 0.0

    profitable = sum(1 for v in period_pnl.values() if v > 0)
    return profitable / len(period_pnl)


def compute_metrics(trades: list[dict]) -> dict:
    """Compute all standard performance metrics from a list of trade dicts.

    Each trade dict must have: pnl_rub, pnl_points, bars_held, exit_reason.

    Returns:
        dict with keys: trades, wins, losses, winrate, net_pnl, profit_factor,
        expectancy, max_drawdown, best_trade, worst_trade, avg_bars_held,
        median_bars_held, profitable_days_pct, profitable_weeks_pct,
        exit_reason_breakdown.
    """
    closed_trades = [t for t in trades if t.get("exit_reason") is not None]

    if not closed_trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "winrate": 0.0,
            "net_pnl": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "max_drawdown": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "avg_bars_held": 0.0,
            "median_bars_held": 0.0,
            "profitable_days_pct": 0.0,
            "profitable_weeks_pct": 0.0,
            "exit_reason_breakdown": {},
        }

    pnls = [float(t["pnl_rub"]) for t in closed_trades]
    bars = [int(t.get("bars_held", 0)) for t in closed_trades]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total = len(pnls)
    win_count = len(wins)
    loss_count = len(losses)
    winrate = win_count / total if total > 0 else 0.0
    net_pnl = sum(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    expectancy = net_pnl / total if total > 0 else 0.0
    max_dd = compute_max_drawdown(pnls)
    best_trade = max(pnls) if pnls else 0.0
    worst_trade = min(pnls) if pnls else 0.0
    avg_bars = sum(bars) / len(bars) if bars else 0.0
    median_bars = statistics.median(bars) if bars else 0.0

    profitable_days = compute_profitable_periods(closed_trades, "day")
    profitable_weeks = compute_profitable_periods(closed_trades, "week")

    # Exit reason breakdown
    exit_counts: dict = defaultdict(int)
    for t in closed_trades:
        exit_counts[t.get("exit_reason", "UNKNOWN")] += 1
    exit_reason_breakdown = dict(exit_counts)

    return {
        "trades": total,
        "wins": win_count,
        "losses": loss_count,
        "winrate": round(winrate, 4),
        "net_pnl": round(net_pnl, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 9999.0,
        "expectancy": round(expectancy, 2),
        "max_drawdown": round(max_dd, 2),
        "best_trade": round(best_trade, 2),
        "worst_trade": round(worst_trade, 2),
        "avg_bars_held": round(avg_bars, 2),
        "median_bars_held": float(median_bars),
        "profitable_days_pct": round(profitable_days, 4),
        "profitable_weeks_pct": round(profitable_weeks, 4),
        "exit_reason_breakdown": exit_reason_breakdown,
    }
