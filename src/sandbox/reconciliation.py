"""Position reconciliation for the sandbox execution layer (MVP-L1a).

Compares the bot's expected position (derived from sandbox_trades / open
trade state) against the actual position reported by the sandbox account.
On any mismatch, the caller must stop opening new trades (see
src/sandbox/risk.py: RiskManager.mark_reconciliation_failed).
"""
from dataclasses import dataclass

from src.sandbox.models import RiskCheckResult


@dataclass(frozen=True)
class PositionView:
    """Simplified position view used for reconciliation."""
    direction: str  # "FLAT" | "LONG" | "SHORT"
    qty: int = 0


def position_from_signed_qty(signed_qty: int) -> PositionView:
    """Build a PositionView from a signed lot quantity (positive=LONG, negative=SHORT)."""
    if signed_qty == 0:
        return PositionView(direction="FLAT", qty=0)
    if signed_qty > 0:
        return PositionView(direction="LONG", qty=signed_qty)
    return PositionView(direction="SHORT", qty=abs(signed_qty))


def reconcile_position(expected: PositionView, actual: PositionView) -> RiskCheckResult:
    """Compare expected (bot state) vs actual (sandbox account) position.

    Returns RiskCheckResult(allowed=True) on match,
    RiskCheckResult(allowed=False, reason=...) on any mismatch.
    """
    if expected.direction == "FLAT" and actual.direction == "FLAT":
        return RiskCheckResult(True, None)

    if expected.direction == "FLAT" and actual.direction != "FLAT":
        return RiskCheckResult(
            False,
            f"expected_flat_actual_position actual_direction={actual.direction} actual_qty={actual.qty}",
        )

    if expected.direction != "FLAT" and actual.direction == "FLAT":
        return RiskCheckResult(
            False,
            f"expected_position_actual_flat expected_direction={expected.direction} "
            f"expected_qty={expected.qty}",
        )

    if expected.direction != actual.direction:
        return RiskCheckResult(
            False,
            f"direction_mismatch expected={expected.direction} actual={actual.direction}",
        )

    if expected.qty != actual.qty:
        return RiskCheckResult(
            False,
            f"qty_mismatch expected_qty={expected.qty} actual_qty={actual.qty}",
        )

    return RiskCheckResult(True, None)
