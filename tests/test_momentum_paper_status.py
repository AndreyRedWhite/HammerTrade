"""Tests for src/paper/momentum/status.py (MVP-R3)."""
from src.paper.momentum.models import MomentumDailyContext, MomentumDayState
from src.paper.momentum.status import build_momentum_status

_CTX = MomentumDailyContext(date_msk="2026-06-02", state=MomentumDayState.WAITING_FOR_SIGNAL)

_BASE_KWARGS = dict(
    ticker="SiM6",
    experiment_name="momentum_mc_atr2_vol2_r2",
    direction="SHORT",
    signal_params={"atr_multiplier": 2.0, "volume_multiplier": 2.0, "take_r": 2.0},
    daily_ctx=_CTX,
    open_trade=None,
    closed_trades_total=0,
    net_pnl_total=0.0,
    session="main",
    fetch_status="OK",
    last_successful_fetch_at=None,
    consecutive_api_errors=0,
    total_api_errors=0,
    last_api_error_at=None,
    last_api_error_message=None,
    market_open_since=None,
    pid=12345,
)


# ── 1. Status includes required strategy and signal fields ────────────────────

def test_status_includes_strategy_fields():
    s = build_momentum_status(market_open=False, **_BASE_KWARGS)
    assert s["strategy"] == "momentum_continuation"
    assert s["experiment_name"] == "momentum_mc_atr2_vol2_r2"
    assert s["ticker"] == "SiM6"
    assert s["direction"] == "SHORT"
    assert s["signal_params"]["atr_multiplier"] == 2.0
    assert s["mode"] == "paper"
    assert "daily_state" in s
    assert "closed_trades_total" in s


# ── 2. Liveness OK when market open, no errors, recent fetch ─────────────────

def test_liveness_ok_when_no_errors():
    from datetime import datetime, timezone, timedelta
    recent_fetch = (datetime.now(tz=timezone.utc) - timedelta(seconds=10)).isoformat()
    s = build_momentum_status(
        market_open=True,
        last_successful_fetch_at=recent_fetch,
        market_open_since=recent_fetch,
        **{k: v for k, v in _BASE_KWARGS.items()
           if k not in ("last_successful_fetch_at", "market_open_since")},
    )
    assert s["trading_liveness_status"] == "OK"


# ── 3. Liveness STALLED when many consecutive errors ─────────────────────────

def test_liveness_stalled_when_many_errors():
    s = build_momentum_status(
        market_open=True,
        consecutive_api_errors=25,
        **{k: v for k, v in _BASE_KWARGS.items()
           if k not in ("consecutive_api_errors",)},
    )
    assert s["trading_liveness_status"] == "STALLED"
