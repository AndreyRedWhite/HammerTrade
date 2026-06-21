"""Tests for ORB paper trading status builder."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.orb.models import OrbDailyContext, OrbDayState, OrbPaperTrade, OrbTradeStatus
from src.paper.orb.status import build_orb_status


def _make_daily_ctx() -> OrbDailyContext:
    return OrbDailyContext(
        date_msk="2026-05-30",
        state=OrbDayState.WAITING_FOR_BREAKOUT,
        or_high=120.0,
        or_low=100.0,
        or_candles_count=7,
    )


def _build_status(**kwargs):
    defaults = dict(
        ticker="SiM6",
        experiment_name="orb_or60_short2r",
        direction="SHORT",
        or_start="10:00",
        or_end="11:00",
        take_r=2.0,
        daily_ctx=_make_daily_ctx(),
        open_trade=None,
        closed_trades_total=5,
        net_pnl_total=100.0,
        market_open=True,
        session="morning",
        fetch_status="OK",
        last_successful_fetch_at="2026-05-30T08:00:00Z",
        consecutive_api_errors=0,
        total_api_errors=0,
        last_api_error_at=None,
        last_api_error_message=None,
        market_open_since="2026-05-30T06:59:00Z",
        pid=12345,
    )
    defaults.update(kwargs)
    return build_orb_status(**defaults)


# ─────────────────────────────── 1 ────────────────────────────────────────────
def test_status_includes_strategy_fields():
    """build_orb_status() returns dict with strategy, ticker, direction, opening_range."""
    status = _build_status()
    assert status["strategy"] == "ORB"
    assert status["ticker"] == "SiM6"
    assert status["direction"] == "SHORT"
    assert "opening_range" in status
    assert status["opening_range"]["start"] == "10:00"
    assert status["opening_range"]["end"] == "11:00"
    assert status["take_r"] == 2.0
    assert status["experiment_name"] == "orb_or60_short2r"
    assert "daily_state" in status
    assert "pid" in status
    assert "trading_liveness_status" in status


# ─────────────────────────────── 2 ────────────────────────────────────────────
def test_liveness_ok_when_no_errors():
    """Market open, no API errors, recent fetch → liveness=OK."""
    now = datetime.now(tz=timezone.utc)
    recent_fetch = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    status = _build_status(
        market_open=True,
        consecutive_api_errors=0,
        last_successful_fetch_at=recent_fetch,
    )
    assert status["trading_liveness_status"] == "OK"
    assert status["trading_liveness_reason"] is None


# ─────────────────────────────── 3 ────────────────────────────────────────────
def test_liveness_stalled_when_many_errors():
    """25 consecutive errors → liveness=STALLED."""
    status = _build_status(
        market_open=True,
        consecutive_api_errors=25,
        last_successful_fetch_at=None,
        market_open_since=None,
    )
    assert status["trading_liveness_status"] == "STALLED"
    assert "consecutive_api_errors" in (status["trading_liveness_reason"] or "")
