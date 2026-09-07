"""Walk-forward analysis utilities for ORB and other strategy research."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.research.metrics import compute_metrics


def split_by_month(trades: list[dict]) -> dict[str, list[dict]]:
    """Group trades by calendar month.

    Args:
        trades: List of trade dicts, each with a 'date' field (YYYY-MM-DD or datetime).

    Returns:
        Dict mapping 'YYYY-MM' -> list of trade dicts.
    """
    result: dict[str, list[dict]] = {}
    for t in trades:
        date_str = str(t.get("date", ""))[:10]
        if not date_str or date_str == "":
            continue
        try:
            key = date_str[:7]  # "YYYY-MM"
        except (ValueError, AttributeError):
            continue
        result.setdefault(key, []).append(t)
    return dict(sorted(result.items()))


def split_by_week(trades: list[dict]) -> dict[str, list[dict]]:
    """Group trades by ISO week.

    Args:
        trades: List of trade dicts, each with a 'date' field (YYYY-MM-DD).

    Returns:
        Dict mapping 'YYYY-WXX' -> list of trade dicts.
    """
    result: dict[str, list[dict]] = {}
    for t in trades:
        date_str = str(t.get("date", ""))[:10]
        if not date_str:
            continue
        try:
            dt = datetime.fromisoformat(date_str)
            iso = dt.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        except (ValueError, AttributeError):
            continue
        result.setdefault(key, []).append(t)
    return dict(sorted(result.items()))


def period_summary(trades: list[dict], period_label: str) -> dict:
    """Compute metrics for a subset of trades and add period metadata.

    Args:
        trades: List of trade dicts for the period.
        period_label: Label for this period (e.g. '2026-01', '2026-W03').

    Returns:
        Dict with all compute_metrics() fields plus:
        - period_label: str
        - trading_days: int (distinct dates with at least 1 trade)
        - profitable_days: int (days where daily net_pnl > 0)
    """
    metrics = compute_metrics(trades)

    # Compute trading days and profitable days
    day_pnl: dict[str, float] = {}
    for t in trades:
        date_str = str(t.get("date", ""))[:10]
        if not date_str:
            continue
        day_pnl[date_str] = day_pnl.get(date_str, 0.0) + float(t.get("pnl_rub", 0))

    trading_days = len(day_pnl)
    profitable_days = sum(1 for v in day_pnl.values() if v > 0)

    return {
        "period_label": period_label,
        "trading_days": trading_days,
        "profitable_days": profitable_days,
        **metrics,
    }


def walkforward_table(all_trades: list[dict], period: str = "month") -> list[dict]:
    """Build a walk-forward table grouped by period.

    Args:
        all_trades: All trade dicts to analyse.
        period: 'month' or 'week'.

    Returns:
        List of period_summary dicts, one per period, sorted chronologically.
    """
    if not all_trades:
        return []

    if period == "month":
        groups = split_by_month(all_trades)
    elif period == "week":
        groups = split_by_week(all_trades)
    else:
        raise ValueError(f"Unknown period: {period!r}. Use 'month' or 'week'.")

    rows = []
    for label, trades in groups.items():
        rows.append(period_summary(trades, label))
    return rows
