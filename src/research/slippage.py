"""Slippage sensitivity analysis utilities for ORB research."""
from __future__ import annotations

from src.research.metrics import compute_metrics

# Cost constants deliberately removed: this module used to hardcode
# POINT_VALUE_RUB = 10.0 and COMMISSION_RUB = 0.05 and silently re-price every
# trade with them, so the ORB slippage-sensitivity table was computed on a 10x
# point value and a ~zero commission regardless of what the study configured.
# Both are now required arguments. See src/costs.


def apply_slippage_to_trades(
    trades: list[dict],
    slip_pts: float,
    *,
    point_value_rub: float,
    commission_rub: float,
) -> list[dict]:
    """Apply slippage to a list of simulated trade dicts.

    For each trade, compute worse fill prices and recalculate pnl_points / pnl_rub.
    The original trade dicts are NOT modified; new dicts are returned.

    Slippage model:
      Long trade:
        entry_price_slip = entry_price + slip_pts
        exit_price_slip  = exit_price - slip_pts (always worse regardless of exit reason)
        pnl_points_slip  = exit_price_slip - entry_price_slip
        pnl_rub_slip     = pnl_points_slip * point_value_rub - commission_rub

      Short trade:
        entry_price_slip = entry_price - slip_pts
        exit_price_slip  = exit_price + slip_pts
        pnl_points_slip  = entry_price_slip - exit_price_slip
        pnl_rub_slip     = pnl_points_slip * point_value_rub - commission_rub

    Args:
        trades: List of trade dicts (with entry_price, exit_price, direction, pnl_points, pnl_rub).
        slip_pts: Slippage in points to apply symmetrically at entry and exit.
        point_value_rub: RUB per point per contract. REQUIRED — no default.
        commission_rub: Round-trip commission in RUB. REQUIRED — no default.

    Returns:
        New list of trade dicts with modified pnl_points and pnl_rub.
    """
    result = []
    for t in trades:
        new_t = dict(t)
        direction = str(t.get("direction", "LONG")).upper()
        entry_price = float(t.get("entry_price", 0))
        exit_price = float(t.get("exit_price", 0))

        if direction == "LONG":
            entry_slip = entry_price + slip_pts
            exit_slip = exit_price - slip_pts
            pnl_pts = exit_slip - entry_slip
        else:  # SHORT
            entry_slip = entry_price - slip_pts
            exit_slip = exit_price + slip_pts
            pnl_pts = entry_slip - exit_slip

        pnl_rub = pnl_pts * point_value_rub - commission_rub

        new_t["entry_price_slip"] = entry_slip
        new_t["exit_price_slip"] = exit_slip
        new_t["pnl_points"] = round(pnl_pts, 6)
        new_t["pnl_rub"] = round(pnl_rub, 4)
        new_t["slip_pts_applied"] = slip_pts
        result.append(new_t)
    return result


def slippage_sensitivity(
    trades: list[dict],
    slip_pts_list: list[float],
    *,
    point_value_rub: float,
    commission_rub: float,
) -> list[dict]:
    """Compute metrics for each slippage level.

    Args:
        trades: Base trade list (zero or baseline slippage already baked in).
        slip_pts_list: List of slippage values to test (e.g. [0, 1, 2, 5, 10]).

    Returns:
        List of dicts, one per slip_pts, each containing:
        - slip_pts: float
        - destroyed_edge: bool
        - all keys from compute_metrics()
    """
    rows = []
    for slip in slip_pts_list:
        slipped = apply_slippage_to_trades(
            trades, slip,
            point_value_rub=point_value_rub, commission_rub=commission_rub,
        )
        metrics = compute_metrics(slipped)
        destroyed = slippage_destroyed_edge(metrics)
        rows.append({
            "slip_pts": slip,
            "destroyed_edge": destroyed,
            **metrics,
        })
    return rows


def slippage_destroyed_edge(metrics: dict, threshold_pf: float = 1.1) -> bool:
    """Return True if slippage has destroyed the trading edge.

    Destroyed if:
      - profit_factor < threshold_pf, OR
      - net_pnl <= 0

    Args:
        metrics: Result from compute_metrics().
        threshold_pf: Minimum acceptable profit factor (default 1.1).

    Returns:
        True if edge is destroyed, False otherwise.
    """
    pf = float(metrics.get("profit_factor", 0))
    net = float(metrics.get("net_pnl", 0))
    return pf < threshold_pf or net <= 0
