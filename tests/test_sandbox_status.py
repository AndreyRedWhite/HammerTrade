"""Tests for src/sandbox/status.py (MVP-L1a)."""
import json

from src.sandbox.status import build_sandbox_status, write_sandbox_status


def _base_status(**overrides):
    defaults = dict(
        strategy="hammer_maxhold5",
        ticker="SiU6",
        direction="SELL",
        max_hold_bars=5,
        orders_enabled=True,
        real_orders_enabled=False,
        paper_control_service="hammertrade-paper-maxhold5.service",
        trading_state="WAITING_FOR_SIGNAL",
        kill_switch_active=False,
        sandbox_account_id_present=True,
        token_present=True,
        open_positions_expected=0,
        open_positions_actual=0,
        open_orders=0,
        daily_pnl_rub=0.0,
        total_pnl_rub=0.0,
        daily_loss_limit_rub=3000,
        total_loss_limit_rub=10000,
        trades_today=0,
        max_trades_per_day=5,
        reconciliation_status="OK",
        market_open=False,
        consecutive_api_errors=0,
    )
    defaults.update(overrides)
    return build_sandbox_status(**defaults)


def test_build_sandbox_status_basic_fields():
    status = _base_status()
    assert status["mode"] == "sandbox"
    assert status["strategy"] == "hammer_maxhold5"
    assert status["ticker"] == "SiU6"
    assert status["direction"] == "SELL"
    assert status["max_hold_bars"] == 5
    assert status["orders_enabled"] is True
    assert status["real_orders_enabled"] is False
    assert status["paper_control_service"] == "hammertrade-paper-maxhold5.service"
    assert status["liveness"] == "OK"
    assert status["trading_state"] == "WAITING_FOR_SIGNAL"
    assert status["kill_switch_active"] is False


def test_build_sandbox_status_never_includes_token_value():
    status = _base_status()
    dumped = json.dumps(status)
    assert "token_present" in status
    for key in status:
        assert key == "token_present" or "token" not in key.lower(), (
            f"unexpected token-related field: {key}"
        )
    assert "SANDBOX_TOKEN" not in dumped


def test_build_sandbox_status_real_orders_always_false_for_mvp():
    status = _base_status(real_orders_enabled=False)
    assert status["real_orders_enabled"] is False


def test_build_sandbox_status_market_closed_liveness_ok():
    status = _base_status(market_open=False, consecutive_api_errors=999)
    assert status["liveness"] == "OK"


def test_build_sandbox_status_market_open_many_errors_stalled():
    status = _base_status(market_open=True, consecutive_api_errors=25)
    assert status["liveness"] == "STALLED"


def test_write_sandbox_status_atomic(tmp_path):
    status = _base_status()
    out = tmp_path / "runtime" / "sandbox_status_hammer_maxhold5_SiU6.json"
    write_sandbox_status(status, str(out))

    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["ticker"] == "SiU6"
    assert not (out.parent / (out.name + ".tmp")).exists()


def test_build_sandbox_status_risk_fields():
    status = _base_status(
        daily_pnl_rub=-150.5,
        total_pnl_rub=-150.5,
        trades_today=1,
        reconciliation_status="OK",
    )
    assert status["daily_pnl_rub"] == -150.5
    assert status["total_pnl_rub"] == -150.5
    assert status["daily_loss_limit_rub"] == 3000
    assert status["total_loss_limit_rub"] == 10000
    assert status["trades_today"] == 1
    assert status["max_trades_per_day"] == 5
    assert status["reconciliation_status"] == "OK"
