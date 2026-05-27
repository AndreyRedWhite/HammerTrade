"""Tests for MVP-2.3a: Trading Liveness Guard."""
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.paper.liveness import (
    compute_liveness,
    DEGRADED_AFTER_CONSECUTIVE_ERRORS,
    STALLED_AFTER_CONSECUTIVE_ERRORS,
    DEGRADED_AFTER_FETCH_MINUTES,
    STALLED_AFTER_FETCH_MINUTES,
    DEGRADED_AFTER_EMPTY_RESPONSES,
    OPEN_MARKET_GRACE_MINUTES,
)
from src.paper.status import build_status


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ts(minutes_ago: float) -> str:
    dt = _now_utc() - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _base_status(**overrides):
    base = {
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
        "last_fetch_status": "OK",
    }
    base.update(overrides)
    return base


# ── 1. Liveness OK when market open and recent fetch ─────────────────────────

def test_liveness_ok_recent_fetch():
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=0,
        last_successful_fetch_at=_ts(1),
    )
    assert status == "OK"
    assert reason is None


# ── 2. DEGRADED when consecutive_api_errors >= threshold ─────────────────────

def test_liveness_degraded_consecutive_errors():
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=DEGRADED_AFTER_CONSECUTIVE_ERRORS,
        last_successful_fetch_at=_ts(1),
    )
    assert status == "DEGRADED"
    assert "consecutive_api_errors" in reason


# ── 3. STALLED when consecutive_api_errors >= stalled threshold ───────────────

def test_liveness_stalled_consecutive_errors():
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=STALLED_AFTER_CONSECUTIVE_ERRORS,
        last_successful_fetch_at=_ts(1),
    )
    assert status == "STALLED"
    assert "consecutive_api_errors" in reason


# ── 4. DEGRADED when last_successful_fetch older than degraded threshold ──────

def test_liveness_degraded_stale_fetch():
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=0,
        last_successful_fetch_at=_ts(DEGRADED_AFTER_FETCH_MINUTES + 1),
    )
    assert status == "DEGRADED"
    assert "minutes_since_last_successful_fetch" in reason


# ── 5. STALLED when last_successful_fetch older than stalled threshold ────────

def test_liveness_stalled_stale_fetch():
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=0,
        last_successful_fetch_at=_ts(STALLED_AFTER_FETCH_MINUTES + 1),
    )
    assert status == "STALLED"
    assert "minutes_since_last_successful_fetch" in reason


# ── 6. Market closed does NOT trigger STALLED from old fetch ──────────────────

def test_liveness_ok_when_market_closed():
    status, reason = compute_liveness(
        is_market_open=False,
        consecutive_api_errors=STALLED_AFTER_CONSECUTIVE_ERRORS + 100,
        last_successful_fetch_at=_ts(500),  # many hours ago
    )
    assert status == "OK"
    assert reason is None


# ── 7. Successful fetch (errors=0) → OK even if previous errors ───────────────

def test_liveness_recovered_after_reset():
    # Simulates what happens when api_errors is reset to 0 after successful fetch
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=0,
        last_successful_fetch_at=_ts(0),
    )
    assert status == "OK"


# ── 8. API error increments consecutive AND total counters ────────────────────

def test_api_error_increments_counters():
    """Verify build_status reflects incremented error counters."""
    s = build_status(
        **_base_status(
            last_fetch_status="API_ERROR",
            consecutive_api_errors=3,
            total_api_errors=42,
            last_api_error_at=_ts(0),
            last_api_error_message="connection reset",
            last_error="connection reset",
        )
    )
    assert s["consecutive_api_errors"] == 3
    assert s["total_api_errors"] == 42
    assert s["last_api_error_message"] == "connection reset"
    assert s["last_api_error_at"] is not None


# ── 9. Status JSON backward-compatible (no new fields → still works) ──────────

def test_build_status_backward_compat_no_liveness_fields():
    """Old callers that don't pass liveness fields get defaults."""
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
    assert "trading_liveness_status" in s
    assert "trading_liveness_reason" in s
    assert "total_api_errors" in s
    assert s["total_api_errors"] == 0
    assert s["last_api_error_at"] is None


# ── 10-12. check_paper_status.py exit codes ──────────────────────────────────

_CHECK_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_paper_status.py"


def _run_check(status_data: dict | None, tmp_path: Path, *extra_args) -> subprocess.CompletedProcess:
    if status_data is not None:
        p = tmp_path / "status.json"
        p.write_text(json.dumps(status_data))
        file_args = ["--status-file", str(p)]
    else:
        file_args = ["--status-file", str(tmp_path / "nonexistent.json")]
    return subprocess.run(
        [sys.executable, str(_CHECK_SCRIPT)] + list(extra_args) + file_args,
        capture_output=True, text=True,
    )


def _fresh_status_json(**overrides) -> dict:
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
        "last_cycle_at_utc": _ts(0),
        "last_fetch_status": "OK",
        "consecutive_api_errors": 0,
        "total_api_errors": 0,
        "last_successful_fetch_at": _ts(1),
        "trading_liveness_status": "OK",
        "trading_liveness_reason": None,
        "minutes_since_last_successful_fetch": 1.0,
        "open_trades": 0,
        "pending_signal": False,
        "pid": 12345,
    }
    base.update(overrides)
    return base


def test_check_status_exit_ok(tmp_path):
    result = _run_check(_fresh_status_json(), tmp_path)
    assert result.returncode == 0
    assert "[OK]" in result.stdout


def test_check_status_exit_degraded(tmp_path):
    result = _run_check(
        _fresh_status_json(
            trading_liveness_status="DEGRADED",
            trading_liveness_reason="consecutive_api_errors=5",
        ),
        tmp_path,
    )
    assert result.returncode == 1
    assert "DEGRADED" in result.stdout


def test_check_status_exit_stalled(tmp_path):
    result = _run_check(
        _fresh_status_json(
            trading_liveness_status="STALLED",
            trading_liveness_reason="consecutive_api_errors=20",
        ),
        tmp_path,
    )
    assert result.returncode == 2
    assert "STALLED" in result.stdout


# ── 13. paper_error_report highlights STALLED ────────────────────────────────

_ERROR_REPORT_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "paper_error_report.py"


def test_error_report_highlights_stalled(tmp_path):
    stalled = tmp_path / "paper_status_SiM6_SELL.json"
    stalled.write_text(json.dumps(_fresh_status_json(
        trading_liveness_status="STALLED",
        trading_liveness_reason="consecutive_api_errors=790",
        consecutive_api_errors=790,
        total_api_errors=790,
    )))
    result = subprocess.run(
        [sys.executable, str(_ERROR_REPORT_SCRIPT), "--status-files", str(stalled)],
        capture_output=True, text=True,
    )
    assert "STALLED" in result.stdout
    assert "CRITICAL" in result.stdout


# ── 14. EMPTY_CANDLES_RESPONSE fields remain intact ──────────────────────────

def test_empty_candles_fields_preserved():
    s = build_status(
        **_base_status(
            last_fetch_status="EMPTY_CANDLES_RESPONSE",
            empty_response_count=5,
            consecutive_empty_responses=2,
            last_empty_response_at=_ts(3),
        )
    )
    assert s["empty_response_count"] == 5
    assert s["consecutive_empty_responses"] == 2
    assert s["last_empty_response_at"] is not None
    # Existing liveness fields still present
    assert "trading_liveness_status" in s


# ── 15. check_paper_status missing file → exit 2 ─────────────────────────────

def test_check_status_missing_file(tmp_path):
    result = _run_check(None, tmp_path)
    assert result.returncode == 2


# ── 16. DEGRADED from consecutive_empty_responses ────────────────────────────

def test_liveness_degraded_empty_responses():
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=0,
        consecutive_empty_responses=DEGRADED_AFTER_EMPTY_RESPONSES,
        last_successful_fetch_at=_ts(1),
    )
    assert status == "DEGRADED"
    assert "consecutive_empty_responses" in reason


# ── 17. STALLED takes priority over DEGRADED ─────────────────────────────────

def test_stalled_takes_priority_over_degraded():
    # Both thresholds exceeded — should be STALLED
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=STALLED_AFTER_CONSECUTIVE_ERRORS,
        consecutive_empty_responses=DEGRADED_AFTER_EMPTY_RESPONSES,
        last_successful_fetch_at=_ts(STALLED_AFTER_FETCH_MINUTES + 5),
    )
    assert status == "STALLED"


# ── 18. None last_successful_fetch_at skips time-based checks ────────────────

def test_none_fetch_at_skips_time_checks():
    """When last_successful_fetch_at is None, time checks are skipped."""
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=0,
        last_successful_fetch_at=None,
    )
    assert status == "OK"


# ── 19. minutes_since_last_successful_fetch in build_status ──────────────────

def test_minutes_since_fetch_in_status():
    s = build_status(
        **_base_status(
            last_successful_fetch_at=_ts(5),
            last_fetch_status="OK",
        )
    )
    assert s["minutes_since_last_successful_fetch"] is not None
    assert 4.5 <= s["minutes_since_last_successful_fetch"] <= 5.5


def test_minutes_since_fetch_none_when_no_fetch():
    s = build_status(**_base_status(last_successful_fetch_at=None))
    assert s["minutes_since_last_successful_fetch"] is None


# ── 21. Grace period: within OPEN_MARKET_GRACE_MINUTES → OK ──────────────────

def test_grace_period_within_window():
    """During grace period after market open, time-based checks are skipped."""
    within_grace = _ts(OPEN_MARKET_GRACE_MINUTES - 1)
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=0,
        last_successful_fetch_at=None,
        market_open_since=within_grace,
    )
    assert status == "OK"


# ── 22. After grace period expired → DEGRADED then STALLED ───────────────────

def test_grace_period_expired_degraded():
    """After grace + DEGRADED threshold, no fetch → DEGRADED."""
    open_since = _ts(OPEN_MARKET_GRACE_MINUTES + DEGRADED_AFTER_FETCH_MINUTES + 1)
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=0,
        last_successful_fetch_at=None,
        market_open_since=open_since,
    )
    assert status == "DEGRADED"
    assert "minutes_since_market_open_no_fetch" in reason


def test_grace_period_expired_stalled():
    """After grace + STALLED threshold, no fetch → STALLED."""
    open_since = _ts(OPEN_MARKET_GRACE_MINUTES + STALLED_AFTER_FETCH_MINUTES + 1)
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=0,
        last_successful_fetch_at=None,
        market_open_since=open_since,
    )
    assert status == "STALLED"
    assert "minutes_since_market_open_no_fetch" in reason


# ── 23. market_open_since=None + last_successful_fetch_at=None → OK ──────────

def test_both_none_skips_time_checks():
    """No market_open_since info + no fetch → only error counters apply."""
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=0,
        last_successful_fetch_at=None,
        market_open_since=None,
    )
    assert status == "OK"


# ── 24. market_open_since in build_status JSON ────────────────────────────────

def test_market_open_since_in_build_status():
    open_since = _ts(10)
    s = build_status(**_base_status(
        last_successful_fetch_at=None,
        market_open_since=open_since,
    ))
    assert s["market_open_since"] == open_since


# ── 25. Successful fetch resets concern despite expired grace ─────────────────

def test_successful_fetch_overrides_grace_period():
    """Once last_successful_fetch_at is set, market_open_since is irrelevant."""
    open_since = _ts(OPEN_MARKET_GRACE_MINUTES + STALLED_AFTER_FETCH_MINUTES + 10)
    status, reason = compute_liveness(
        is_market_open=True,
        consecutive_api_errors=0,
        last_successful_fetch_at=_ts(1),  # recent successful fetch
        market_open_since=open_since,
    )
    assert status == "OK"
