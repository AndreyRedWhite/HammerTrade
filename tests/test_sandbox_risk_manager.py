"""Tests for src/sandbox/risk.py (MVP-L1a)."""
from src.sandbox.models import ReconciliationStatus, SandboxDailyRisk, SandboxRiskState
from src.sandbox.risk import RiskLimits, RiskManager


def _limits(tmp_path, **overrides):
    defaults = dict(
        capital_budget_rub=40_000,
        max_position_notional_rub=40_000,
        max_order_notional_rub=40_000,
        max_daily_loss_rub=3_000,
        max_total_loss_rub=10_000,
        max_trades_per_day=5,
        max_consecutive_errors=3,
        max_consecutive_losses=3,
        max_open_positions_per_strategy=1,
        kill_switch_file=str(tmp_path / "STOP_SANDBOX_TRADING"),
    )
    defaults.update(overrides)
    return RiskLimits(**defaults)


def _state():
    return SandboxRiskState()


def _daily():
    return SandboxDailyRisk(date_msk="2026-06-11")


def test_allows_normal_trade_under_limits(tmp_path):
    rm = RiskManager(_limits(tmp_path))
    result = rm.check_pre_trade(
        risk_state=_state(), daily_risk=_daily(), open_positions=0,
        order_notional_rub=36_500.0,  # below max_order_notional_rub=40_000
        position_notional_rub=36_500.0,
    )
    assert result.allowed is True
    assert result.reason is None


def test_blocks_when_kill_switch_present(tmp_path):
    limits = _limits(tmp_path)
    rm = RiskManager(limits)
    open(limits.kill_switch_file, "w").close()

    result = rm.check_pre_trade(risk_state=_state(), daily_risk=_daily(), open_positions=0)
    assert result.allowed is False
    assert "kill_switch_active" in result.reason


def test_blocks_when_daily_loss_exceeded(tmp_path):
    rm = RiskManager(_limits(tmp_path))
    daily = SandboxDailyRisk(date_msk="2026-06-11", realized_pnl_rub=-3_000.0)

    result = rm.check_pre_trade(risk_state=_state(), daily_risk=daily, open_positions=0)
    assert result.allowed is False
    assert "max_daily_loss_exceeded" in result.reason


def test_blocks_when_total_loss_exceeded(tmp_path):
    rm = RiskManager(_limits(tmp_path))
    state = SandboxRiskState(total_pnl_rub=-10_000.0)

    result = rm.check_pre_trade(risk_state=state, daily_risk=_daily(), open_positions=0)
    assert result.allowed is False
    assert "max_total_loss_exceeded" in result.reason


def test_blocks_when_max_trades_per_day_exceeded(tmp_path):
    rm = RiskManager(_limits(tmp_path))
    daily = SandboxDailyRisk(date_msk="2026-06-11", trades_today=5)

    result = rm.check_pre_trade(risk_state=_state(), daily_risk=daily, open_positions=0)
    assert result.allowed is False
    assert "max_trades_per_day_exceeded" in result.reason


def test_blocks_when_reconciliation_failed(tmp_path):
    rm = RiskManager(_limits(tmp_path))
    state = SandboxRiskState(reconciliation_status=ReconciliationStatus.RECONCILIATION_FAILED.value)

    result = rm.check_pre_trade(risk_state=state, daily_risk=_daily(), open_positions=0)
    assert result.allowed is False
    assert "reconciliation_status" in result.reason


def test_blocks_when_trading_paused(tmp_path):
    rm = RiskManager(_limits(tmp_path))
    state = SandboxRiskState(trading_paused=True, trading_paused_reason="manual_pause")

    result = rm.check_pre_trade(risk_state=state, daily_risk=_daily(), open_positions=0)
    assert result.allowed is False
    assert "trading_paused" in result.reason


def test_blocks_when_max_open_positions_exceeded(tmp_path):
    rm = RiskManager(_limits(tmp_path, max_open_positions_per_strategy=1))

    result = rm.check_pre_trade(risk_state=_state(), daily_risk=_daily(), open_positions=1)
    assert result.allowed is False
    assert "max_open_positions_exceeded" in result.reason


def test_blocks_when_consecutive_errors_exceeded(tmp_path):
    rm = RiskManager(_limits(tmp_path, max_consecutive_errors=3))
    state = SandboxRiskState(consecutive_errors=3)

    result = rm.check_pre_trade(risk_state=state, daily_risk=_daily(), open_positions=0)
    assert result.allowed is False
    assert "max_consecutive_errors_exceeded" in result.reason


def test_blocks_when_consecutive_losses_exceeded(tmp_path):
    rm = RiskManager(_limits(tmp_path, max_consecutive_losses=3))
    state = SandboxRiskState(consecutive_losses=3)

    result = rm.check_pre_trade(risk_state=state, daily_risk=_daily(), open_positions=0)
    assert result.allowed is False
    assert "max_consecutive_losses_exceeded" in result.reason


def test_blocks_when_order_notional_exceeded(tmp_path):
    rm = RiskManager(_limits(tmp_path, max_order_notional_rub=10_000))

    result = rm.check_pre_trade(
        risk_state=_state(), daily_risk=_daily(), open_positions=0,
        order_notional_rub=730_000,
    )
    assert result.allowed is False
    assert "max_order_notional_exceeded" in result.reason


def test_update_after_losing_trade_increments_consecutive_losses(tmp_path):
    rm = RiskManager(_limits(tmp_path, max_consecutive_losses=3))
    state, daily = _state(), _daily()

    state, daily = rm.update_after_trade(state, daily, net_pnl_rub=-500.0)
    assert state.total_pnl_rub == -500.0
    assert daily.realized_pnl_rub == -500.0
    assert daily.trades_today == 1
    assert state.consecutive_losses == 1
    assert state.trading_paused is False


def test_update_after_trade_pauses_on_max_consecutive_losses(tmp_path):
    rm = RiskManager(_limits(tmp_path, max_consecutive_losses=2, max_daily_loss_rub=3_000, max_total_loss_rub=10_000))
    state, daily = _state(), _daily()

    state, daily = rm.update_after_trade(state, daily, net_pnl_rub=-100.0)
    state, daily = rm.update_after_trade(state, daily, net_pnl_rub=-100.0)

    assert state.consecutive_losses == 2
    assert state.trading_paused is True
    assert state.trading_paused_reason == "max_consecutive_losses_exceeded"


def test_update_after_winning_trade_resets_consecutive_losses(tmp_path):
    rm = RiskManager(_limits(tmp_path))
    state, daily = _state(), _daily()
    state.consecutive_losses = 2
    daily.consecutive_losses = 2

    state, daily = rm.update_after_trade(state, daily, net_pnl_rub=200.0)
    assert state.consecutive_losses == 0
    assert daily.consecutive_losses == 0
    assert state.total_pnl_rub == 200.0


def test_update_after_error_pauses_on_threshold(tmp_path):
    rm = RiskManager(_limits(tmp_path, max_consecutive_errors=2))
    state = _state()

    state = rm.update_after_error(state)
    assert state.consecutive_errors == 1
    assert state.trading_paused is False

    state = rm.update_after_error(state)
    assert state.consecutive_errors == 2
    assert state.trading_paused is True
    assert state.trading_paused_reason == "max_consecutive_errors_exceeded"


def test_reset_errors(tmp_path):
    rm = RiskManager(_limits(tmp_path))
    state = SandboxRiskState(consecutive_errors=2)
    state = rm.reset_errors(state)
    assert state.consecutive_errors == 0


def test_mark_reconciliation_failed_and_ok(tmp_path):
    rm = RiskManager(_limits(tmp_path))
    state = _state()

    state = rm.mark_reconciliation_failed(state)
    assert state.reconciliation_status == ReconciliationStatus.RECONCILIATION_FAILED.value
    assert state.trading_paused is True

    state = rm.mark_reconciliation_ok(state)
    assert state.reconciliation_status == ReconciliationStatus.OK.value


def test_record_exit_error_pauses_after_cap(tmp_path):
    rm = RiskManager(_limits(tmp_path, max_exit_retries=3))
    state = _state()

    state = rm.record_exit_error(state)
    assert state.exit_error_count == 1
    assert rm.exit_retries_exhausted(state) is False
    assert state.trading_paused is False

    state = rm.record_exit_error(state)
    state = rm.record_exit_error(state)
    assert state.exit_error_count == 3
    assert rm.exit_retries_exhausted(state) is True
    assert state.trading_paused is True
    assert state.trading_paused_reason == "max_exit_retries_exceeded"


def test_reset_exit_errors(tmp_path):
    rm = RiskManager(_limits(tmp_path))
    state = SandboxRiskState(exit_error_count=2)
    state = rm.reset_exit_errors(state)
    assert state.exit_error_count == 0


def test_reset_for_new_day_lifts_consecutive_loss_pause(tmp_path):
    # The daily circuit breaker must lift on a new trading day; otherwise a
    # positive-expectancy strategy stays disabled forever after a losing streak.
    rm = RiskManager(_limits(tmp_path, max_consecutive_losses=3))
    state = SandboxRiskState(
        consecutive_losses=3,
        trading_paused=True,
        trading_paused_reason="max_consecutive_losses_exceeded",
    )

    state, changed = rm.reset_for_new_day(state)
    assert changed is True
    assert state.consecutive_losses == 0
    assert state.trading_paused is False
    assert state.trading_paused_reason is None
    # and trading is allowed again
    assert rm.check_pre_trade(risk_state=state, daily_risk=_daily(), open_positions=0).allowed is True


def test_reset_for_new_day_lifts_daily_loss_pause(tmp_path):
    rm = RiskManager(_limits(tmp_path))
    state = SandboxRiskState(trading_paused=True, trading_paused_reason="max_daily_loss_exceeded")

    state, changed = rm.reset_for_new_day(state)
    assert changed is True
    assert state.trading_paused is False
    assert state.trading_paused_reason is None


def test_reset_for_new_day_keeps_hard_halts(tmp_path):
    # Technical/cumulative halts must survive the daily rollover (manual review).
    rm = RiskManager(_limits(tmp_path))
    for reason in (
        "max_total_loss_exceeded",
        "max_exit_retries_exceeded",
        "max_consecutive_errors_exceeded",
        "reconciliation_failed",
    ):
        state = SandboxRiskState(trading_paused=True, trading_paused_reason=reason)
        state, _ = rm.reset_for_new_day(state)
        assert state.trading_paused is True, reason
        assert state.trading_paused_reason == reason


def test_reset_for_new_day_noop_when_clean(tmp_path):
    rm = RiskManager(_limits(tmp_path))
    state = _state()
    state, changed = rm.reset_for_new_day(state)
    assert changed is False
    assert state.trading_paused is False


def test_exit_error_count_independent_of_consecutive_errors(tmp_path):
    # Exit retries must not be conflated with entry-side consecutive_errors.
    rm = RiskManager(_limits(tmp_path, max_exit_retries=5, max_consecutive_errors=3))
    state = _state()
    for _ in range(4):
        rm.record_exit_error(state)
    assert state.exit_error_count == 4
    assert state.consecutive_errors == 0
    assert rm.exit_retries_exhausted(state) is False
