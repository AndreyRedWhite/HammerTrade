"""Pure metric + classification functions for the fleet report.

Kept dependency-free (stdlib only) and side-effect-free so they are easy to
unit-test. IO (sqlite, systemctl, status JSON) lives in fleet.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class Trade:
    exit_ts: datetime
    pnl_rub: float
    direction: str = ""


@dataclass
class Metrics:
    trades: int = 0
    pnl_rub: float = 0.0
    pf: Optional[float] = None       # None when undefined (no losses / no trades)
    wr: Optional[float] = None       # win rate %
    max_dd_rub: float = 0.0
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    gross_win: float = 0.0           # for aggregating PF across services
    gross_loss: float = 0.0          # absolute value of summed losses


# Per-family classification thresholds (edge assessment on LIFETIME trades).
# pf_floor / min_freeze_trades from project history (hammer PF<1.25@60,
# ORB PF<1.1@30). Generic fallback for newer families.
FAMILY_RULES: dict[str, dict] = {
    "hammer":   {"pf_floor": 1.25, "min_freeze": 60, "promote_pf": 1.5, "promote_min": 50},
    "orb":      {"pf_floor": 1.10, "min_freeze": 30, "promote_pf": 1.4, "promote_min": 30},
    "momentum": {"pf_floor": 1.20, "min_freeze": 40, "promote_pf": 1.5, "promote_min": 40},
    "orf":      {"pf_floor": 1.10, "min_freeze": 30, "promote_pf": 1.4, "promote_min": 30},
    "vwap":     {"pf_floor": 1.10, "min_freeze": 40, "promote_pf": 1.4, "promote_min": 40},
    "pairs":    {"pf_floor": 1.00, "min_freeze": 60, "promote_pf": 1.4, "promote_min": 50},
    "sandbox":  {"pf_floor": 1.25, "min_freeze": 60, "promote_pf": 1.5, "promote_min": 50},
}
_DEFAULT_RULE = {"pf_floor": 1.10, "min_freeze": 40, "promote_pf": 1.5, "promote_min": 40}


def filter_window(trades: list[Trade], now: datetime, days: int) -> list[Trade]:
    cutoff = now - timedelta(days=days)
    return [t for t in trades if t.exit_ts >= cutoff]


def compute_metrics(trades: list[Trade]) -> Metrics:
    if not trades:
        return Metrics()
    pnls = [t.pnl_rub for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (None if gross_win == 0 else float("inf"))

    # Max drawdown of the cumulative PnL curve (trades ordered by exit time).
    ordered = sorted(trades, key=lambda t: t.exit_ts)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in ordered:
        cum += t.pnl_rub
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    return Metrics(
        trades=len(trades),
        pnl_rub=round(sum(pnls), 1),
        pf=(round(pf, 3) if isinstance(pf, float) and pf != float("inf") else pf),
        wr=round(len(wins) / len(trades) * 100, 1),
        max_dd_rub=round(max_dd, 1),
        avg_win=round(sum(wins) / len(wins), 1) if wins else None,
        avg_loss=round(sum(losses) / len(losses), 1) if losses else None,
        gross_win=round(gross_win, 1),
        gross_loss=round(gross_loss, 1),
    )


def cumulative_curve(trades: list[Trade], max_points: int = 40) -> list[float]:
    """Cumulative PnL over trades ordered by exit time, downsampled to max_points."""
    if not trades:
        return []
    ordered = sorted(trades, key=lambda t: t.exit_ts)
    cum, curve = 0.0, []
    for t in ordered:
        cum += t.pnl_rub
        curve.append(round(cum, 1))
    if len(curve) <= max_points:
        return curve
    step = len(curve) / max_points
    return [curve[min(int(i * step), len(curve) - 1)] for i in range(max_points)]


def classify(family: str, lifetime: Metrics, liveness: str) -> str:
    """Return ACTIVE / WATCH / FREEZE / PROMOTE for a strategy's lifetime edge.

    Liveness problems do NOT change the edge class (reported in a separate
    column); only STALLED forces a WATCH so it surfaces.
    """
    rule = FAMILY_RULES.get(family, _DEFAULT_RULE)
    n = lifetime.trades
    pf = lifetime.pf

    # Not enough data to judge the edge yet.
    if n < min(rule["min_freeze"], rule["promote_min"]):
        return "WATCH"

    # Enough sample to potentially freeze a broken edge.
    if n >= rule["min_freeze"]:
        if pf is None or (isinstance(pf, float) and pf < rule["pf_floor"]):
            return "FREEZE"

    # Strong, well-sampled edge → promotion candidate.
    if n >= rule["promote_min"] and isinstance(pf, float) and pf >= rule["promote_pf"]:
        return "PROMOTE"

    return "ACTIVE"
