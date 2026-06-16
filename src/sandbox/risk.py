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

    def update_after_error(self, risk_state: SandboxRiskState) -> SandboxRiskState:
        risk_state.consecutive_errors += 1
        if risk_state.consecutive_errors >= self.limits.max_consecutive_errors:
            risk_state.trading_paused = True
            risk_state.trading_paused_reason = "max_consecutive_errors_exceeded"
        return risk_state

    def reset_errors(self, risk_state: SandboxRiskState) -> SandboxRiskState:
        risk_state.consecutive_errors = 0
        return risk_state

    def mark_reconciliation_failed(self, risk_state: SandboxRiskState) -> SandboxRiskState:
        risk_state.reconciliation_status = ReconciliationStatus.RECONCILIATION_FAILED.value
        risk_state.trading_paused = True
        risk_state.trading_paused_reason = "reconciliation_failed"
        return risk_state

    def mark_reconciliation_ok(self, risk_state: SandboxRiskState) -> SandboxRiskState:
        risk_state.reconciliation_status = ReconciliationStatus.OK.value
        return risk_state
