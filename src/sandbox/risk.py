"""Risk manager for the sandbox execution layer (MVP-L1a).

All checks are conservative: any breach pauses trading until manual review.
This module never places orders — it only decides whether the runner is
allowed to do so.
"""
import os
from dataclasses import dataclass

from src.sandbox.models import (
    ReconciliationStatus,
    RiskCheckResult,
    SandboxDailyRisk,
    SandboxRiskState,
)


# Pause reasons that are *daily* circuit breakers: they should halt trading
# for the rest of the day they trip on, then lift automatically on the next
# trading day. Without this lift the pause is sticky forever, so a
# positive-expectancy strategy permanently disables itself on an ordinary
# losing streak (e.g. P(3 losses) ~9% at WR 55%) and never participates in the
# recovery — which is exactly why the sandbox booked a steady net loss while
# the paper control (which has no such breaker) stayed profitable.
#
# All other pause reasons (reconciliation_failed, max_total_loss_exceeded,
# max_exit_retries_exceeded, max_consecutive_errors) are technical/hard halts
# that require manual review and are NOT auto-cleared here.
DAILY_RESETTABLE_PAUSE_REASONS = frozenset(
    {"max_consecutive_losses_exceeded", "max_daily_loss_exceeded"}
)


@dataclass(frozen=True)
class RiskLimits:
    capital_budget_rub: float
    max_position_notional_rub: float
    max_order_notional_rub: float
    max_daily_loss_rub: float
    max_total_loss_rub: float
    max_trades_per_day: int
    max_consecutive_errors: int
    max_consecutive_losses: int
    max_open_positions_per_strategy: int
    kill_switch_file: str
    # Cap on consecutive failed *exit* (closing) order attempts for one open
    # position before the strategy pauses. Exits bypass check_pre_trade, so
    # without this an unfillable close (e.g. sandbox "Not enough balance")
    # would retry every cycle forever. Default mirrors max_consecutive_errors.
    max_exit_retries: int = 3


class RiskManager:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def kill_switch_active(self) -> bool:
        return os.path.exists(self.limits.kill_switch_file)

    def check_pre_trade(
        self,
        *,
        risk_state: SandboxRiskState,
        daily_risk: SandboxDailyRisk,
        open_positions: int,
        order_notional_rub: float = 0.0,
        position_notional_rub: float = 0.0,
    ) -> RiskCheckResult:
        """Run all pre-entry checks. Returns the first failing check, if any."""
        if self.kill_switch_active():
            return RiskCheckResult(False, f"kill_switch_active file={self.limits.kill_switch_file}")

        if risk_state.reconciliation_status != ReconciliationStatus.OK.value:
            return RiskCheckResult(False, f"reconciliation_status={risk_state.reconciliation_status}")

        if risk_state.trading_paused:
            return RiskCheckResult(False, f"trading_paused reason={risk_state.trading_paused_reason}")

        if risk_state.consecutive_errors >= self.limits.max_consecutive_errors:
            return RiskCheckResult(
                False,
                f"max_consecutive_errors_exceeded "
                f"({risk_state.consecutive_errors} >= {self.limits.max_consecutive_errors})",
            )

        if risk_state.consecutive_losses >= self.limits.max_consecutive_losses:
            return RiskCheckResult(
                False,
                f"max_consecutive_losses_exceeded "
                f"({risk_state.consecutive_losses} >= {self.limits.max_consecutive_losses})",
            )

        if daily_risk.trades_today >= self.limits.max_trades_per_day:
            return RiskCheckResult(
                False,
                f"max_trades_per_day_exceeded "
                f"({daily_risk.trades_today} >= {self.limits.max_trades_per_day})",
            )

        if daily_risk.realized_pnl_rub <= -self.limits.max_daily_loss_rub:
            return RiskCheckResult(
                False,
                f"max_daily_loss_exceeded "
                f"({daily_risk.realized_pnl_rub} <= -{self.limits.max_daily_loss_rub})",
            )

        if risk_state.total_pnl_rub <= -self.limits.max_total_loss_rub:
            return RiskCheckResult(
                False,
                f"max_total_loss_exceeded "
                f"({risk_state.total_pnl_rub} <= -{self.limits.max_total_loss_rub})",
            )

        if open_positions >= self.limits.max_open_positions_per_strategy:
            return RiskCheckResult(
                False,
                f"max_open_positions_exceeded "
                f"({open_positions} >= {self.limits.max_open_positions_per_strategy})",
            )

        if order_notional_rub > self.limits.max_order_notional_rub:
            return RiskCheckResult(
                False,
                f"max_order_notional_exceeded "
                f"({order_notional_rub} > {self.limits.max_order_notional_rub})",
            )

        if position_notional_rub > self.limits.max_position_notional_rub:
            return RiskCheckResult(
                False,
                f"max_position_notional_exceeded "
                f"({position_notional_rub} > {self.limits.max_position_notional_rub})",
            )

        return RiskCheckResult(True, None)

    def update_after_trade(
        self,
        risk_state: SandboxRiskState,
        daily_risk: SandboxDailyRisk,
        net_pnl_rub: float,
    ) -> tuple[SandboxRiskState, SandboxDailyRisk]:
        """Update cumulative risk state after a trade closes."""
        risk_state.total_pnl_rub = round(risk_state.total_pnl_rub + net_pnl_rub, 2)
        daily_risk.realized_pnl_rub = round(daily_risk.realized_pnl_rub + net_pnl_rub, 2)
        daily_risk.trades_today += 1

        if net_pnl_rub < 0:
            risk_state.consecutive_losses += 1
            daily_risk.consecutive_losses += 1
        else:
            risk_state.consecutive_losses = 0
            daily_risk.consecutive_losses = 0

        if daily_risk.realized_pnl_rub <= -self.limits.max_daily_loss_rub:
            daily_risk.daily_loss_breached = True
            risk_state.trading_paused = True
            risk_state.trading_paused_reason = "max_daily_loss_exceeded"

        if risk_state.total_pnl_rub <= -self.limits.max_total_loss_rub:
            risk_state.trading_paused = True
            risk_state.trading_paused_reason = "max_total_loss_exceeded"

        if risk_state.consecutive_losses >= self.limits.max_consecutive_losses:
            risk_state.trading_paused = True
            risk_state.trading_paused_reason = "max_consecutive_losses_exceeded"

        return risk_state, daily_risk

    def reset_for_new_day(self, risk_state: SandboxRiskState) -> tuple[SandboxRiskState, bool]:
        """Lift daily-scoped risk halts at the start of a new trading day.

        The consecutive-loss counter is a *daily* circuit-breaker input, so it
        resets each trading day. If trading is paused for a daily-scoped reason
        (see DAILY_RESETTABLE_PAUSE_REASONS) the pause is lifted too; hard halts
        are left in place for manual review.

        Returns (risk_state, changed) where ``changed`` is True if anything was
        cleared (so the caller can log/persist only when needed).
        """
        changed = False
        if risk_state.consecutive_losses != 0:
            risk_state.consecutive_losses = 0
            changed = True
        if (
            risk_state.trading_paused
            and risk_state.trading_paused_reason in DAILY_RESETTABLE_PAUSE_REASONS
        ):
            risk_state.trading_paused = False
            risk_state.trading_paused_reason = None
            changed = True
        return risk_state, changed

    def update_after_error(self, risk_state: SandboxRiskState) -> SandboxRiskState:
        risk_state.consecutive_errors += 1
        if risk_state.consecutive_errors >= self.limits.max_consecutive_errors:
            risk_state.trading_paused = True
            risk_state.trading_paused_reason = "max_consecutive_errors_exceeded"
        return risk_state

    def reset_errors(self, risk_state: SandboxRiskState) -> SandboxRiskState:
        risk_state.consecutive_errors = 0
        return risk_state

    def exit_retries_exhausted(self, risk_state: SandboxRiskState) -> bool:
        """True once an open position has failed to close max_exit_retries times."""
        return risk_state.exit_error_count >= self.limits.max_exit_retries

    def record_exit_error(self, risk_state: SandboxRiskState) -> SandboxRiskState:
        """Count one failed closing-order attempt; pause once the cap is hit."""
        risk_state.exit_error_count += 1
        if risk_state.exit_error_count >= self.limits.max_exit_retries:
            risk_state.trading_paused = True
            risk_state.trading_paused_reason = "max_exit_retries_exceeded"
        return risk_state

    def reset_exit_errors(self, risk_state: SandboxRiskState) -> SandboxRiskState:
        """Clear the exit-retry counter (on a successful exit or a fresh entry)."""
        risk_state.exit_error_count = 0
        return risk_state

    def mark_reconciliation_failed(self, risk_state: SandboxRiskState) -> SandboxRiskState:
        risk_state.reconciliation_status = ReconciliationStatus.RECONCILIATION_FAILED.value
        risk_state.trading_paused = True
        risk_state.trading_paused_reason = "reconciliation_failed"
        return risk_state

    def mark_reconciliation_ok(self, risk_state: SandboxRiskState) -> SandboxRiskState:
        risk_state.reconciliation_status = ReconciliationStatus.OK.value
        return risk_state
