"""Tests for scripts/run_hammer_maxhold5_sandbox.py (MVP-L1a).

Covers: config loading, the "never live" safety gate, missing-token /
missing-account hard fails, trading-state computation, and a dry-run
--once smoke test that touches no DB, broker, or token.
"""
import copy
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

import scripts.run_hammer_maxhold5_sandbox as m
from src.sandbox.models import SandboxDailyRisk, SandboxRiskState, SandboxTrade, SandboxTradeStatus

CONFIG_PATH = "configs/sandbox/hammer_maxhold5_siu6.yaml"


def _open_trade(status=SandboxTradeStatus.OPEN):
    from datetime import datetime, timezone
    return SandboxTrade(
        trade_id="t1", signal_id="s1", entry_order_id=None, exit_order_id=None,
        ticker="SiU6", direction="SELL", qty=1,
        entry_time=datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc),
        entry_price=100.0, stop_price=105.0, take_price=95.0,
        status=status,
    )


def _synthetic_candles_df():
    base = pd.Timestamp("2026-06-11T10:00:00Z")
    rows = [
        {"timestamp": base + pd.Timedelta(minutes=i),
         "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 10}
        for i in range(5)
    ]
    return pd.DataFrame(rows), 1.0


def _write_temp_config(tmp_path):
    cfg = copy.deepcopy(m._load_config(CONFIG_PATH))
    cfg["artifacts"]["status"] = str(tmp_path / "sandbox_status.json")
    cfg["artifacts"]["db"] = str(tmp_path / "sandbox_state.sqlite")
    cfg["artifacts"]["trades_csv"] = str(tmp_path / "trades.csv")
    cfg["artifacts"]["orders_csv"] = str(tmp_path / "orders.csv")
    cfg["artifacts"]["log"] = str(tmp_path / "sandbox.log")
    cfg_path = tmp_path / "config.yaml"
    with open(cfg_path, "w") as f:
        yaml.safe_dump(cfg, f)
    return str(cfg_path), cfg


# ── config loading ────────────────────────────────────────────────────────

def test_load_config_returns_expected_structure():
    cfg = m._load_config(CONFIG_PATH)
    assert cfg["mode"] == "sandbox"
    assert cfg["strategy"] == "hammer_maxhold5"
    assert cfg["ticker"] == "SiU6"
    assert cfg["direction"] == "SELL"
    assert cfg["max_hold_bars"] == 5
    assert cfg["orders"]["environment"] == "sandbox"
    assert cfg["orders"]["real_orders_enabled"] is False
    assert cfg["paper_control_service"] == "hammertrade-paper-maxhold5.service"


def test_load_config_missing_file_hard_fails():
    with pytest.raises(SystemExit):
        m._load_config("configs/sandbox/does_not_exist.yaml")


# ── validate_safety: never live ─────────────────────────────────────────────

def test_validate_safety_passes_for_real_sandbox_config(monkeypatch):
    monkeypatch.delenv("TINVEST_LIVE_TRADING_TOKEN", raising=False)
    cfg = m._load_config(CONFIG_PATH)
    m.validate_safety(cfg)  # must not raise


@pytest.mark.parametrize("mode", ["live", "prod", None])
def test_validate_safety_rejects_non_sandbox_mode(monkeypatch, mode):
    monkeypatch.delenv("TINVEST_LIVE_TRADING_TOKEN", raising=False)
    cfg = m._load_config(CONFIG_PATH)
    cfg["mode"] = mode
    with pytest.raises(SystemExit) as exc:
        m.validate_safety(cfg)
    assert "CONFIG ERROR" in str(exc.value)


@pytest.mark.parametrize("environment", ["live", "prod", None])
def test_validate_safety_rejects_non_sandbox_orders_environment(monkeypatch, environment):
    monkeypatch.delenv("TINVEST_LIVE_TRADING_TOKEN", raising=False)
    cfg = m._load_config(CONFIG_PATH)
    cfg["orders"]["environment"] = environment
    with pytest.raises(SystemExit) as exc:
        m.validate_safety(cfg)
    assert "CONFIG ERROR" in str(exc.value)


def test_validate_safety_rejects_real_orders_enabled(monkeypatch):
    monkeypatch.delenv("TINVEST_LIVE_TRADING_TOKEN", raising=False)
    cfg = m._load_config(CONFIG_PATH)
    cfg["orders"]["real_orders_enabled"] = True
    with pytest.raises(SystemExit) as exc:
        m.validate_safety(cfg)
    assert "CONFIG ERROR" in str(exc.value)


def test_validate_safety_rejects_live_trading_token_env(monkeypatch):
    monkeypatch.setenv("TINVEST_LIVE_TRADING_TOKEN", "something")
    cfg = m._load_config(CONFIG_PATH)
    with pytest.raises(SystemExit) as exc:
        m.validate_safety(cfg)
    assert "CONFIG ERROR" in str(exc.value)
    assert "TINVEST_LIVE_TRADING_TOKEN" in str(exc.value)


# ── check_token_and_account: missing token/account hard fails ──────────────

def test_check_token_and_account_missing_token_hard_fails(monkeypatch):
    monkeypatch.delenv("SANDBOX_TOKEN", raising=False)
    monkeypatch.delenv("SANDBOX_ACCOUNT_ID", raising=False)
    cfg = m._load_config(CONFIG_PATH)
    with pytest.raises(SystemExit) as exc:
        m.check_token_and_account(cfg)
    assert "CONFIG ERROR" in str(exc.value)
    assert "SANDBOX_TOKEN" in str(exc.value)


def test_check_token_and_account_missing_account_hard_fails(monkeypatch):
    monkeypatch.setenv("SANDBOX_TOKEN", "dummy-token")
    monkeypatch.delenv("SANDBOX_ACCOUNT_ID", raising=False)
    cfg = m._load_config(CONFIG_PATH)
    with pytest.raises(SystemExit) as exc:
        m.check_token_and_account(cfg)
    assert "CONFIG ERROR" in str(exc.value)
    assert "SANDBOX_ACCOUNT_ID" in str(exc.value)


def test_check_token_and_account_returns_account_id_when_present(monkeypatch):
    monkeypatch.setenv("SANDBOX_TOKEN", "dummy-token")
    monkeypatch.setenv("SANDBOX_ACCOUNT_ID", "acct-123")
    cfg = m._load_config(CONFIG_PATH)
    assert m.check_token_and_account(cfg) == "acct-123"


# ── _build_context ───────────────────────────────────────────────────────────

def test_build_context_dry_run_skips_token_and_repo(monkeypatch):
    monkeypatch.delenv("SANDBOX_TOKEN", raising=False)
    monkeypatch.delenv("SANDBOX_ACCOUNT_ID", raising=False)
    cfg = m._load_config(CONFIG_PATH)
    logger = m._setup_logging("logs/unused.log", dry_run=True)

    ctx = m._build_context(cfg, dry_run=True, logger=logger)

    assert ctx.repo is None
    assert ctx.account_id is None
    assert ctx.engine_kwargs["direction_filter"] == "SELL"
    assert ctx.engine_kwargs["max_hold_bars"] == 5
    assert ctx.engine_kwargs["contracts"] == 1
    assert ctx.margin_per_lot_rub == 6000


def test_build_context_non_dry_run_requires_token(monkeypatch):
    monkeypatch.delenv("SANDBOX_TOKEN", raising=False)
    monkeypatch.delenv("SANDBOX_ACCOUNT_ID", raising=False)
    cfg = m._load_config(CONFIG_PATH)
    logger = m._setup_logging("logs/unused.log", dry_run=True)

    with pytest.raises(SystemExit) as exc:
        m._build_context(cfg, dry_run=False, logger=logger)
    assert "CONFIG ERROR" in str(exc.value)


# ── _compute_trading_state ──────────────────────────────────────────────────

def test_compute_trading_state_kill_switch_takes_priority():
    risk_state = SandboxRiskState()
    state = m._compute_trading_state(risk_state, _open_trade(), {"direction": "SELL"}, kill_switch_active=True)
    assert state == "KILL_SWITCH_ACTIVE"


def test_compute_trading_state_reconciliation_failed():
    risk_state = SandboxRiskState(reconciliation_status="RECONCILIATION_FAILED")
    state = m._compute_trading_state(risk_state, None, None, kill_switch_active=False)
    assert state == "RECONCILIATION_FAILED"


def test_compute_trading_state_trading_paused():
    risk_state = SandboxRiskState(trading_paused=True, trading_paused_reason="max_daily_loss_exceeded")
    state = m._compute_trading_state(risk_state, None, None, kill_switch_active=False)
    assert state == "TRADING_PAUSED"


def test_compute_trading_state_in_position():
    risk_state = SandboxRiskState()
    state = m._compute_trading_state(risk_state, _open_trade(), None, kill_switch_active=False)
    assert state == "IN_POSITION"


def test_compute_trading_state_pending_entry():
    risk_state = SandboxRiskState()
    state = m._compute_trading_state(risk_state, None, {"direction": "SELL"}, kill_switch_active=False)
    assert state == "PENDING_ENTRY"


def test_compute_trading_state_waiting_for_signal():
    risk_state = SandboxRiskState()
    state = m._compute_trading_state(risk_state, None, None, kill_switch_active=False)
    assert state == "WAITING_FOR_SIGNAL"


def test_compute_trading_state_closed_trade_does_not_block():
    risk_state = SandboxRiskState()
    state = m._compute_trading_state(risk_state, _open_trade(SandboxTradeStatus.CLOSED), None, kill_switch_active=False)
    assert state == "WAITING_FOR_SIGNAL"


# ── dry-run --once end-to-end smoke test ────────────────────────────────────

def test_dry_run_once_writes_status_without_db_or_token(tmp_path, monkeypatch):
    monkeypatch.delenv("SANDBOX_TOKEN", raising=False)
    monkeypatch.delenv("SANDBOX_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("TINVEST_LIVE_TRADING_TOKEN", raising=False)

    cfg_path, cfg = _write_temp_config(tmp_path)

    monkeypatch.setattr(m, "_fetch_with_timeout", lambda *a, **k: _synthetic_candles_df())
    monkeypatch.setattr("src.market.market_hours.is_session_open", lambda *a, **k: True)
    monkeypatch.setattr("src.market.market_hours.get_session_name", lambda *a, **k: "main")

    monkeypatch.setattr(sys, "argv", [
        "run_hammer_maxhold5_sandbox.py", "--config", cfg_path, "--dry-run", "--once",
    ])
    m.main()

    status_path = Path(cfg["artifacts"]["status"])
    assert status_path.exists()

    import json
    status = json.loads(status_path.read_text())
    assert status["mode"] == "sandbox"
    assert status["real_orders_enabled"] is False
    assert status["trading_state"] == "DRY_RUN"
    assert status["paper_control_service"] == "hammertrade-paper-maxhold5.service"
    assert "SANDBOX_TOKEN" not in json.dumps(status)

    # Dry-run must never create the sandbox state DB.
    assert not Path(cfg["artifacts"]["db"]).exists()
