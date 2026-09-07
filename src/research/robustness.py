"""Robustness / concentration analysis utilities for ORB research."""
from __future__ import annotations

from collections import defaultdict


def top_trades_contribution(trades: list[dict], n: int) -> dict:
    """Compute the contribution of the top-n best trades to total net PnL.

    Args:
        trades: List of trade dicts with 'pnl_rub' field.
        n: Number of top trades to consider.

    Returns:
        Dict with keys:
          - n: int
          - total_net: float
          - top_n_net: float  (sum of best n trades by pnl_rub)
          - pct_of_total: float  (top_n_net / total_net, or 0 if total_net == 0)
    """
    if not trades:
        return {"n": n, "total_net": 0.0, "top_n_net": 0.0, "pct_of_total": 0.0}

    pnls = sorted([float(t.get("pnl_rub", 0)) for t in trades], reverse=True)
    total_net = sum(pnls)
    top_n_net = sum(pnls[:n])
    pct = top_n_net / total_net if total_net != 0 else 0.0

    return {
        "n": n,
        "total_net": round(total_net, 4),
        "top_n_net": round(top_n_net, 4),
        "pct_of_total": round(pct, 6),
    }


def best_day_contribution(trades: list[dict]) -> dict:
    """Compute the contribution of the best single day to total net PnL.

    Args:
        trades: List of trade dicts with 'pnl_rub' and 'date' fields.

    Returns:
        Dict with keys:
          - best_date: str (date of best day)
          - best_day_net: float
          - total_net: float
          - pct_of_total: float
    """
    if not trades:
        return {"best_date": "", "best_day_net": 0.0, "total_net": 0.0, "pct_of_total": 0.0}

    day_pnl: dict[str, float] = defaultdict(float)
    for t in trades:
        date_str = str(t.get("date", ""))[:10]
        if not date_str:
            continue
        day_pnl[date_str] += float(t.get("pnl_rub", 0))

    if not day_pnl:
        return {"best_date": "", "best_day_net": 0.0, "total_net": 0.0, "pct_of_total": 0.0}

    best_date = max(day_pnl, key=lambda d: day_pnl[d])
    best_day_net = day_pnl[best_date]
    total_net = sum(day_pnl.values())
    pct = best_day_net / total_net if total_net != 0 else 0.0

    return {
        "best_date": best_date,
        "best_day_net": round(best_day_net, 4),
        "total_net": round(total_net, 4),
        "pct_of_total": round(pct, 6),
    }


def worst_day_contribution(trades: list[dict]) -> dict:
    """Compute the contribution of the worst single day to total net PnL.

    Args:
        trades: List of trade dicts with 'pnl_rub' and 'date' fields.

    Returns:
        Dict with keys:
          - worst_date: str
          - worst_day_net: float
          - total_net: float
          - pct_of_total: float (worst day / total, signed)
    """
    if not trades:
        return {"worst_date": "", "worst_day_net": 0.0, "total_net": 0.0, "pct_of_total": 0.0}

    day_pnl: dict[str, float] = defaultdict(float)
    for t in trades:
        date_str = str(t.get("date", ""))[:10]
        if not date_str:
            continue
        day_pnl[date_str] += float(t.get("pnl_rub", 0))

    if not day_pnl:
        return {"worst_date": "", "worst_day_net": 0.0, "total_net": 0.0, "pct_of_total": 0.0}

    worst_date = min(day_pnl, key=lambda d: day_pnl[d])
    worst_day_net = day_pnl[worst_date]
    total_net = sum(day_pnl.values())
    pct = worst_day_net / total_net if total_net != 0 else 0.0

    return {
        "worst_date": worst_date,
        "worst_day_net": round(worst_day_net, 4),
        "total_net": round(total_net, 4),
        "pct_of_total": round(pct, 6),
    }


def net_without_top_n_trades(trades: list[dict], n: int) -> float:
    """Compute net PnL excluding the best n trades.

    Args:
        trades: List of trade dicts with 'pnl_rub' field.
        n: Number of best trades to exclude.

    Returns:
        Net PnL without the top n trades.
    """
    if not trades:
        return 0.0
    pnls = sorted([float(t.get("pnl_rub", 0)) for t in trades], reverse=True)
    return round(sum(pnls[n:]), 4)


def net_without_best_day(trades: list[dict]) -> float:
    """Compute net PnL excluding the best trading day.

    Args:
        trades: List of trade dicts with 'pnl_rub' and 'date' fields.

    Returns:
        Net PnL without all trades on the best day.
    """
    if not trades:
        return 0.0

    day_pnl: dict[str, float] = defaultdict(float)
    for t in trades:
        date_str = str(t.get("date", ""))[:10]
        if not date_str:
            continue
        day_pnl[date_str] += float(t.get("pnl_rub", 0))

    if not day_pnl:
        return 0.0

    best_date = max(day_pnl, key=lambda d: day_pnl[d])
    result = sum(
        float(t.get("pnl_rub", 0))
        for t in trades
        if str(t.get("date", ""))[:10] != best_date
    )
    return round(result, 4)


def concentration_flag(trades: list[dict]) -> tuple[bool, str]:
    """Determine if the trade results are dangerously concentrated.

    Concentration is HIGH if:
      - top 3 trades account for > 50% of total net PnL, OR
      - best single day accounts for > 40% of total net PnL

    Args:
        trades: List of trade dicts.

    Returns:
        Tuple (is_concentrated: bool, reason: str).
        reason is '' if not concentrated, or human-readable description.
    """
    if not trades:
        return (False, "")

    top3 = top_trades_contribution(trades, 3)
    best_day = best_day_contribution(trades)

    total_net = top3["total_net"]
    if total_net <= 0:
        # If losing overall, concentration is still a concern but not in the traditional sense
        return (False, "total_net <= 0, concentration not meaningful")

    reasons = []
    if top3["pct_of_total"] > 0.50:
        reasons.append(
            f"CONCENTRATION_HIGH: top 3 trades = {top3['pct_of_total']:.1%} of total net"
        )
    if best_day["pct_of_total"] > 0.40:
        reasons.append(
            f"CONCENTRATION_HIGH: best day ({best_day['best_date']}) = "
            f"{best_day['pct_of_total']:.1%} of total net"
        )

    if reasons:
        return (True, " | ".join(reasons))
    return (False, "")
