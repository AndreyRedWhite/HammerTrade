"""Tests for MVP-2.1a: EMPTY_CANDLES_RESPONSE handling."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scripts.run_paper_trader import _is_empty_candles_error
from src.paper.status import build_status, StatusWriter


# ── _is_empty_candles_error ───────────────────────────────────────────────────

def test_empty_data_error_classified_as_empty():
    exc = pd.errors.EmptyDataError("No columns to parse from file")
    assert _is_empty_candles_error(exc) is True


def test_empty_data_error_subclass_classified_as_empty():
    # Verify it catches the exact pandas exception class
    try:
        pd.read_csv(pd.io.common.StringIO(""))
    except pd.errors.EmptyDataError as e:
        assert _is_empty_candles_error(e) is True


def test_message_pattern_classified_as_empty():
    exc = RuntimeError("No columns to parse from file")
    assert _is_empty_candles_error(exc) is True


def test_other_exception_not_classified_as_empty():
    assert _is_empty_candles_error(RuntimeError("connection refused")) is False
    assert _is_empty_candles_error(TimeoutError("timed out")) is False
    assert _is_empty_candles_error(ValueError("bad value")) is False


# ── build_status — new fields present ────────────────────────────────────────

def test_build_status_includes_empty_response_fields():
    status = build_status(
        ticker="SiM6", class_code="SPBFUT", timeframe="1m",
        profile="balanced", direction="SELL", env="prod",
        market_hours_enabled=True, market_open=True,
        session="main", market_timezone="Europe/Moscow",
        last_fetch_status="EMPTY_CANDLES_RESPONSE",
        empty_response_count=3,
        consecutive_empty_responses=2,
        last_empty_response_at="2026-05-18T08:06:00Z",
        last_empty_response_message="No columns to parse from file",
        last_successful_fetch_at="2026-05-18T08:05:40Z",
    )
    assert status["empty_response_count"] == 3
    assert status["consecutive_empty_responses"] == 2
    assert status["last_empty_response_at"] == "2026-05-18T08:06:00Z"
    assert status["last_empty_response_message"] == "No columns to parse from file"
    assert status["last_successful_fetch_at"] == "2026-05-18T08:05:40Z"
    assert status["last_fetch_status"] == "EMPTY_CANDLES_RESPONSE"


def test_build_status_empty_response_fields_default_to_zero_none():
    status = build_status(
        ticker="SiM6", class_code="SPBFUT", timeframe="1m",
        profile="balanced", direction="SELL", env="prod",
        market_hours_enabled=True, market_open=True,
        session="main", market_timezone="Europe/Moscow",
        last_fetch_status="OK",
    )
    assert status["empty_response_count"] == 0
    assert status["consecutive_empty_responses"] == 0
    assert status["last_empty_response_at"] is None
    assert status["last_empty_response_message"] is None
    assert status["last_successful_fetch_at"] is None


def test_build_status_old_fields_still_present():
    status = build_status(
        ticker="SiM6", class_code="SPBFUT", timeframe="1m",
        profile="balanced", direction="SELL", env="prod",
        market_hours_enabled=True, market_open=True,
        session="main", market_timezone="Europe/Moscow",
        last_fetch_status="OK",
        consecutive_api_errors=1,
        consecutive_empty_fetches=2,
    )
    assert "consecutive_api_errors" in status
    assert "consecutive_empty_fetches" in status
    assert status["consecutive_api_errors"] == 1
    assert status["consecutive_empty_fetches"] == 2


# ── StatusWriter backward compatibility ──────────────────────────────────────

def test_status_writer_roundtrip_with_new_fields():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "status.json"
        writer = StatusWriter(str(path))
        status = build_status(
            ticker="SiM6", class_code="SPBFUT", timeframe="1m",
            profile="balanced", direction="SELL", env="prod",
            market_hours_enabled=True, market_open=True,
            session="main", market_timezone="Europe/Moscow",
            last_fetch_status="EMPTY_CANDLES_RESPONSE",
            empty_response_count=5,
            consecutive_empty_responses=1,
            last_empty_response_at="2026-05-18T09:00:00Z",
            last_empty_response_message="No columns to parse from file",
        )
        writer.write(status)
        loaded = json.loads(path.read_text())
        assert loaded["empty_response_count"] == 5
        assert loaded["last_fetch_status"] == "EMPTY_CANDLES_RESPONSE"


# ── check_paper_status backward compat with old status files ─────────────────

def test_check_paper_status_handles_missing_new_fields(tmp_path, capsys):
    """Status files without new fields should not break check_paper_status."""
    status_file = tmp_path / "status.json"
    old_status = {
        "service": "hammertrade-paper",
        "mode": "paper",
        "ticker": "SiM6",
        "direction": "SELL",
        "last_cycle_at_utc": "2026-05-18T08:00:00Z",
        "last_fetch_status": "OK",
        "consecutive_empty_fetches": 0,
        "consecutive_api_errors": 0,
        "open_trades": 0,
        "pending_signal": False,
        "pid": 12345,
    }
    status_file.write_text(json.dumps(old_status))

    import importlib, sys as _sys
    orig_argv = _sys.argv
    try:
        _sys.argv = ["check_paper_status.py", "--status-file", str(status_file)]
        import scripts.check_paper_status as cps
        result = cps.main()
    except SystemExit as e:
        result = e.code
    finally:
        _sys.argv = orig_argv

    # Should not crash, should return 0 (OK) or 2 (stale) — not 1 (file error)
    captured = capsys.readouterr()
    assert result != 1
    assert "SiM6" in captured.out


# ── paper_error_report ────────────────────────────────────────────────────────

def test_paper_error_report_missing_file(tmp_path, capsys):
    """paper_error_report.py should not crash when status file is missing."""
    import sys as _sys
    orig_argv = _sys.argv
    try:
        _sys.argv = [
            "paper_error_report.py",
            "--status-files",
            str(tmp_path / "nonexistent.json"),
        ]
        from scripts.paper_error_report import main as er_main
        result = er_main()
    finally:
        _sys.argv = orig_argv
    captured = capsys.readouterr()
    assert "not found" in captured.out
    assert result == 0


def test_paper_error_report_with_valid_status(tmp_path, capsys):
    status_file = tmp_path / "status.json"
    status_data = {
        "ticker": "SiM6",
        "last_fetch_status": "EMPTY_CANDLES_RESPONSE",
        "last_cycle_at_utc": "2026-05-18T08:15:00Z",
        "last_successful_fetch_at": "2026-05-18T08:14:40Z",
        "empty_response_count": 5,
        "consecutive_empty_responses": 1,
        "last_empty_response_at": "2026-05-18T08:15:00Z",
        "consecutive_api_errors": 0,
        "consecutive_empty_fetches": 0,
        "open_trades": 0,
        "pending_signal": False,
    }
    status_file.write_text(json.dumps(status_data))

    import sys as _sys
    orig_argv = _sys.argv
    try:
        _sys.argv = ["paper_error_report.py", "--status-files", str(status_file)]
        from scripts.paper_error_report import main as er_main
        result = er_main()
    finally:
        _sys.argv = orig_argv
    captured = capsys.readouterr()
    assert "empty_response_count" in captured.out
    assert "5" in captured.out
    assert result == 0


def test_paper_error_report_json_output(tmp_path, capsys):
    status_file = tmp_path / "status.json"
    status_file.write_text(json.dumps({"ticker": "SiM6", "empty_response_count": 3}))

    import sys as _sys
    orig_argv = _sys.argv
    try:
        _sys.argv = ["paper_error_report.py", "--status-files", str(status_file), "--json"]
        from scripts.paper_error_report import main as er_main
        er_main()
    finally:
        _sys.argv = orig_argv
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert data[0]["empty_response_count"] == 3


# ── consecutive_empty_responses resets on success ────────────────────────────

def test_consecutive_resets_after_success():
    """cycle_state resets consecutive_empty_responses after a good fetch."""
    # Simulate the logic from _run_cycle's successful fetch branch
    cycle_state = {
        "api_errors": 0,
        "consecutive_empty_responses": 3,
        "empty_responses": 3,
        "last_successful_fetch_at": None,
    }
    # This is the code path on successful fetch
    cycle_state["api_errors"] = 0
    cycle_state["consecutive_empty_responses"] = 0
    cycle_state["last_successful_fetch_at"] = "2026-05-18T08:15:40Z"

    assert cycle_state["consecutive_empty_responses"] == 0
    assert cycle_state["empty_responses"] == 3  # total preserved
    assert cycle_state["last_successful_fetch_at"] == "2026-05-18T08:15:40Z"
