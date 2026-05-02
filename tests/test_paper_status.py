"""Tests for src/paper/status.py and scripts/check_paper_status.py"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.paper.status import StatusWriter, build_status


# --- StatusWriter ---

def test_status_writer_creates_file(tmp_path):
    sw = StatusWriter(str(tmp_path / "status.json"))
    sw.write({"key": "value"})
    assert (tmp_path / "status.json").exists()


def test_status_writer_valid_json(tmp_path):
    sw = StatusWriter(str(tmp_path / "status.json"))
    sw.write({"a": 1, "b": "hello"})
    content = json.loads((tmp_path / "status.json").read_text())
    assert content["a"] == 1
    assert content["b"] == "hello"


def test_status_writer_no_tmp_leftover(tmp_path):
    sw = StatusWriter(str(tmp_path / "status.json"))
    sw.write({"x": 42})
    assert not (tmp_path / "status.tmp").exists()


def test_status_writer_creates_parent_dirs(tmp_path):
    sw = StatusWriter(str(tmp_path / "deep" / "path" / "status.json"))
    sw.write({"ok": True})
    assert (tmp_path / "deep" / "path" / "status.json").exists()


def test_status_writer_overwrites(tmp_path):
    sw = StatusWriter(str(tmp_path / "status.json"))
    sw.write({"v": 1})
    sw.write({"v": 2})
    content = json.loads((tmp_path / "status.json").read_text())
    assert content["v"] == 2


# --- build_status ---

def test_build_status_required_fields():
    s = build_status(
        ticker="SiM6",
        class_code="SPBFUT",
        timeframe="1m",
        profile="balanced",
        direction="SELL",
        env="prod",
        market_hours_enabled=True,
        market_open=True,
        session="main",
        market_timezone="Europe/Moscow",
        last_fetch_status="OK",
    )
    assert s["ticker"] == "SiM6"
    assert s["service"] == "hammertrade-paper"
    assert s["mode"] == "paper"
    assert "last_cycle_at_utc" in s
    assert "pid" in s


def test_build_status_default_counters():
    s = build_status(
        ticker="SiM6",
        class_code="SPBFUT",
        timeframe="1m",
        profile="balanced",
        direction="SELL",
        env="prod",
        market_hours_enabled=True,
        market_open=False,
        session="closed",
        market_timezone="Europe/Moscow",
        last_fetch_status="MARKET_CLOSED",
    )
    assert s["consecutive_empty_fetches"] == 0
    assert s["consecutive_api_errors"] == 0
    assert s["open_trades"] == 0
    assert s["pending_signal"] is False
    assert s["last_error"] is None


def test_build_status_with_error():
    s = build_status(
        ticker="SiM6",
        class_code="SPBFUT",
        timeframe="1m",
        profile="balanced",
        direction="SELL",
        env="prod",
        market_hours_enabled=True,
        market_open=True,
        session="main",
        market_timezone="Europe/Moscow",
        last_fetch_status="API_ERROR",
        last_error="timeout",
        consecutive_api_errors=3,
    )
    assert s["last_error"] == "timeout"
    assert s["consecutive_api_errors"] == 3


# --- check_paper_status.py CLI ---

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_paper_status.py"


def _run_check(*args, status_data=None, tmp_path=None):
    """Write status JSON and run the health-check script."""
    if status_data is not None:
        p = tmp_path / "status.json"
        p.write_text(json.dumps(status_data))
        extra = ["--status-file", str(p)]
    else:
        extra = ["--status-file", str(tmp_path / "nonexistent.json")]
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)] + list(args) + extra,
        capture_output=True,
        text=True,
    )
    return result


def _fresh_status(**overrides):
    base = {
        "service": "hammertrade-paper",
        "mode": "paper",
        "ticker": "SiM6",
        "class_code": "SPBFUT",
        "timeframe": "1m",
        "profile": "balanced",
        "direction": "SELL",
        "env": "prod",
        "market_hours_enabled": True,
        "market_open": True,
        "session": "main",
        "market_timezone": "Europe/Moscow",
        "last_cycle_at_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_cycle_at_msk": datetime.now(tz=timezone.utc).isoformat(),
        "last_fetch_status": "OK",
        "last_candle_ts_utc": None,
        "last_candle_ts_msk": None,
        "last_processed_ts_utc": None,
        "open_trades": 0,
        "pending_signal": False,
        "consecutive_empty_fetches": 0,
        "consecutive_api_errors": 0,
        "last_error": None,
        "pid": 12345,
    }
    base.update(overrides)
    return base


def test_health_check_ok(tmp_path):
    result = _run_check(status_data=_fresh_status(), tmp_path=tmp_path)
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_health_check_missing_file(tmp_path):
    result = _run_check(tmp_path=tmp_path)
    assert result.returncode == 1


def test_health_check_stale(tmp_path):
    old_ts = (datetime.now(tz=timezone.utc) - timedelta(seconds=300)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    result = _run_check(
        "--stale-threshold-sec", "120",
        status_data=_fresh_status(last_cycle_at_utc=old_ts),
        tmp_path=tmp_path,
    )
    assert result.returncode == 2


def test_health_check_json_output(tmp_path):
    result = _run_check("--json", status_data=_fresh_status(), tmp_path=tmp_path)
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert parsed["ticker"] == "SiM6"


def test_health_check_shows_error_in_warn(tmp_path):
    result = _run_check(
        status_data=_fresh_status(last_error="connection reset"),
        tmp_path=tmp_path,
    )
    assert result.returncode == 0
    assert "WARN" in result.stdout or "connection reset" in result.stdout
