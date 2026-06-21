"""Tests for ORB paper trading engine state machine.

MSK = UTC+3: to get 10:00 MSK, use 07:00 UTC.
"""
import sys
from datetime import datetime, time, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.orb.engine import process_candle_orb
from src.paper.orb.models import (
    OrbDailyContext,
    OrbDayState,
    OrbExitReason,
    OrbPaperTrade,
    OrbTradeStatus,
)

# Default params for tests
OR_START = time(10, 0)   # 10:00 MSK
OR_END = time(11, 0)     # 11:00 MSK
TIME_EXIT = time(18, 40)
TAKE_R = 2.0
TICKER = "SiM6"
EXP_NAME = "test_exp"
DATE_MSK = "2026-05-30"


def _make_candle(
    utc_hour: int,
    utc_minute: int = 0,
    open_: float = 100.0,
    high: float = 105.0,
    low: float = 95.0,
    close: float = 100.0,
    date: str = "2026-05-30",
) -> pd.Series:
    """Create a candle Series with UTC timestamp."""
    ts = datetime(2026, 5, 30, utc_hour, utc_minute, 0, tzinfo=timezone.utc)
    return pd.Series({
        "timestamp": ts.isoformat(),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
    })


def _fresh_ctx() -> OrbDailyContext:
    return OrbDailyContext(date_msk=DATE_MSK)


def _call(candle, ctx=None, open_trade=None, direction="SHORT"):
    if ctx is None:
        ctx = _fresh_ctx()
    return process_candle_orb(
        candle=candle,
        daily_ctx=ctx,
        open_trade=open_trade,
        direction=direction,
        or_start_msk=OR_START,
        or_end_msk=OR_END,
        take_r=TAKE_R,
        time_exit_msk=TIME_EXIT,
        ticker=TICKER,
        experiment_name=EXP_NAME,
    )


# ─────────────────────────────── 1 ────────────────────────────────────────────
def test_state_waiting_before_or_start():
    """Candle at 06:00 UTC = 09:00 MSK → stays WAITING_FOR_OR_START."""
    candle = _make_candle(utc_hour=6, high=110, low=90)
    ctx, trade, logs = _call(candle)
    assert ctx.state == OrbDayState.WAITING_FOR_OR_START
    assert trade is None
    assert len(logs) == 0


# ─────────────────────────────── 2 ────────────────────────────────────────────
def test_state_builds_or_during_window():
    """Candle at 07:30 UTC = 10:30 MSK → state BUILDING_OPENING_RANGE, or_high updated."""
    candle = _make_candle(utc_hour=7, utc_minute=30, high=115.0, low=90.0)
    ctx, trade, logs = _call(candle)
    assert ctx.state == OrbDayState.BUILDING_OPENING_RANGE
    assert ctx.or_high == 115.0
    assert ctx.or_low == 90.0
    assert ctx.or_candles_count == 1
    assert trade is None


# ─────────────────────────────── 3 ────────────────────────────────────────────
def test_or_high_low_updated_correctly():
    """Two OR candles → or_high=max(highs), or_low=min(lows)."""
    ctx = _fresh_ctx()
    # First OR candle: 10:05 MSK = 07:05 UTC
    c1 = _make_candle(utc_hour=7, utc_minute=5, high=120.0, low=98.0)
    ctx, _, _ = _call(c1, ctx=ctx)
    # Second OR candle: 10:30 MSK = 07:30 UTC
    c2 = _make_candle(utc_hour=7, utc_minute=30, high=110.0, low=85.0)
    ctx, _, _ = _call(c2, ctx=ctx)
    assert ctx.or_high == 120.0
    assert ctx.or_low == 85.0
    assert ctx.or_candles_count == 2


# ─────────────────────────────── 4 ────────────────────────────────────────────
def test_no_breakout_before_or_end():
    """Candle inside OR window → no trade opened even if low is very low."""
    candle = _make_candle(utc_hour=7, utc_minute=30, high=110.0, low=1.0)  # extreme low
    ctx, trade, logs = _call(candle)
    assert trade is None
    assert ctx.state == OrbDayState.BUILDING_OPENING_RANGE
    assert not ctx.trade_opened


# ─────────────────────────────── 5 ────────────────────────────────────────────
def test_no_trade_when_or_invalid_too_few_candles():
    """After OR window, if or_candles_count < MIN_OR_CANDLES → mark done, no trade."""
    ctx = _fresh_ctx()
    # Only 3 OR candles (less than MIN_OR_CANDLES=5)
    for i in range(3):
        c = _make_candle(utc_hour=7, utc_minute=5 + i, high=120.0, low=80.0)
        ctx, _, _ = _call(c, ctx=ctx)
    assert ctx.or_candles_count == 3

    # Now post-OR candle at 11:30 MSK = 08:30 UTC
    post_or = _make_candle(utc_hour=8, utc_minute=30, low=70.0, high=110.0)
    ctx, trade, logs = _call(post_or, ctx=ctx)
    assert trade is None
    assert ctx.done_for_day
    assert ctx.state == OrbDayState.DONE_FOR_DAY


# ─────────────────────────────── 6 ────────────────────────────────────────────
def test_short_breakout_detected():
    """After OR, candle low < or_low → SHORT trade opened, state=IN_TRADE."""
    ctx = _fresh_ctx()
    # Build OR with 5 candles
    or_high = 120.0
    or_low = 100.0
    for i in range(5):
        c = _make_candle(utc_hour=7, utc_minute=i, high=or_high, low=or_low)
        ctx, _, _ = _call(c, ctx=ctx)
    assert ctx.or_candles_count == 5

    # Breakout candle: 11:30 MSK = 08:30 UTC, low < or_low
    breakout = _make_candle(utc_hour=8, utc_minute=30, high=110.0, low=95.0)  # low=95 < or_low=100
    ctx, trade, logs = _call(breakout, ctx=ctx)

    assert trade is not None
    assert trade.status == OrbTradeStatus.OPEN
    assert trade.direction == "SHORT"
    assert ctx.state == OrbDayState.IN_TRADE
    assert ctx.trade_opened
    assert any("BREAKOUT" in m for m in logs)


# ─────────────────────────────── 7 ────────────────────────────────────────────
def test_stop_price_is_or_high_for_short():
    """When SHORT trade opened, stop_price == or_high."""
    ctx = _fresh_ctx()
    or_high = 125.0
    or_low = 100.0
    for i in range(5):
        c = _make_candle(utc_hour=7, utc_minute=i, high=or_high, low=or_low)
        ctx, _, _ = _call(c, ctx=ctx)

    breakout = _make_candle(utc_hour=8, utc_minute=30, high=110.0, low=95.0)
    ctx, trade, _ = _call(breakout, ctx=ctx)

    assert trade is not None
    assert trade.stop_price == or_high


# ─────────────────────────────── 8 ────────────────────────────────────────────
def test_take_price_with_take_r_2():
    """take = entry - 2 * risk where risk = or_high - or_low."""
    ctx = _fresh_ctx()
    or_high = 120.0
    or_low = 100.0
    for i in range(5):
        c = _make_candle(utc_hour=7, utc_minute=i, high=or_high, low=or_low)
        ctx, _, _ = _call(c, ctx=ctx)

    breakout = _make_candle(utc_hour=8, utc_minute=30, high=110.0, low=95.0)
    ctx, trade, _ = _call(breakout, ctx=ctx)

    assert trade is not None
    risk = or_high - or_low  # 20
    expected_take = or_low - TAKE_R * risk  # 100 - 40 = 60
    assert trade.take_price == expected_take
    assert trade.entry_price == or_low


# ─────────────────────────────── 9 ────────────────────────────────────────────
def test_take_hit_closes_trade():
    """Candle low <= take_price → trade closed with TAKE, pnl_rub positive for SHORT."""
    ctx = _fresh_ctx()
    or_high = 120.0
    or_low = 100.0
    for i in range(5):
        c = _make_candle(utc_hour=7, utc_minute=i, high=or_high, low=or_low)
        ctx, _, _ = _call(c, ctx=ctx)

    # Open trade
    breakout = _make_candle(utc_hour=8, utc_minute=30, high=110.0, low=95.0)
    ctx, trade, _ = _call(breakout, ctx=ctx)
    assert trade is not None
    # entry=100, take=100-2*20=60

    # Candle with low <= take_price (60)
    take_candle = _make_candle(utc_hour=9, utc_minute=0, high=110.0, low=55.0)
    ctx, closed_trade, logs = _call(take_candle, ctx=ctx, open_trade=trade)

    assert closed_trade is not None
    assert closed_trade.status == OrbTradeStatus.CLOSED
    assert closed_trade.exit_reason == OrbExitReason.TAKE
    assert closed_trade.pnl_points is not None
    assert closed_trade.pnl_points > 0  # SHORT: entry - take > 0
    assert closed_trade.pnl_rub is not None
    assert closed_trade.pnl_rub > 0


# ─────────────────────────────── 10 ───────────────────────────────────────────
def test_stop_hit_closes_trade():
    """Candle high >= stop_price → trade closed with STOP, pnl_rub negative for SHORT."""
    ctx = _fresh_ctx()
    or_high = 120.0
    or_low = 100.0
    for i in range(5):
        c = _make_candle(utc_hour=7, utc_minute=i, high=or_high, low=or_low)
        ctx, _, _ = _call(c, ctx=ctx)

    breakout = _make_candle(utc_hour=8, utc_minute=30, high=110.0, low=95.0)
    ctx, trade, _ = _call(breakout, ctx=ctx)
    assert trade is not None
    # entry=100, stop=120

    # Candle with high >= stop_price (120)
    stop_candle = _make_candle(utc_hour=9, utc_minute=0, high=125.0, low=98.0)
    ctx, closed_trade, logs = _call(stop_candle, ctx=ctx, open_trade=trade)

    assert closed_trade is not None
    assert closed_trade.status == OrbTradeStatus.CLOSED
    assert closed_trade.exit_reason == OrbExitReason.STOP
    assert closed_trade.pnl_points is not None
    assert closed_trade.pnl_points < 0  # SHORT: entry(100) - stop(120) = -20
    assert closed_trade.pnl_rub is not None
    assert closed_trade.pnl_rub < 0


# ─────────────────────────────── 11 ───────────────────────────────────────────
def test_time_exit_closes_trade():
    """Candle at 15:45 UTC = 18:45 MSK (> 18:40) → TIME_EXIT closes trade."""
    ctx = _fresh_ctx()
    or_high = 120.0
    or_low = 100.0
    for i in range(5):
        c = _make_candle(utc_hour=7, utc_minute=i, high=or_high, low=or_low)
        ctx, _, _ = _call(c, ctx=ctx)

    breakout = _make_candle(utc_hour=8, utc_minute=30, high=110.0, low=95.0)
    ctx, trade, _ = _call(breakout, ctx=ctx)
    assert trade is not None

    # Candle at 18:45 MSK = 15:45 UTC
    time_exit_candle = _make_candle(utc_hour=15, utc_minute=45, high=103.0, low=97.0, close=101.0)
    ctx, closed_trade, logs = _call(time_exit_candle, ctx=ctx, open_trade=trade)

    assert closed_trade is not None
    assert closed_trade.status == OrbTradeStatus.CLOSED
    assert closed_trade.exit_reason == OrbExitReason.TIME_EXIT
    assert closed_trade.exit_price == 101.0  # close price


# ─────────────────────────────── 12 ───────────────────────────────────────────
def test_max_one_trade_per_day():
    """After trade is closed, subsequent breakout candles do not open new trade."""
    ctx = _fresh_ctx()
    or_high = 120.0
    or_low = 100.0
    for i in range(5):
        c = _make_candle(utc_hour=7, utc_minute=i, high=or_high, low=or_low)
        ctx, _, _ = _call(c, ctx=ctx)

    # Open trade
    breakout = _make_candle(utc_hour=8, utc_minute=30, high=110.0, low=95.0)
    ctx, trade, _ = _call(breakout, ctx=ctx)
    assert trade is not None

    # Close via stop
    stop_candle = _make_candle(utc_hour=9, utc_minute=0, high=125.0, low=98.0)
    ctx, closed_trade, _ = _call(stop_candle, ctx=ctx, open_trade=trade)
    assert closed_trade.status == OrbTradeStatus.CLOSED
    assert ctx.done_for_day

    # Another breakout candle after trade closed
    second_breakout = _make_candle(utc_hour=10, utc_minute=0, high=115.0, low=90.0)
    ctx, no_trade, logs = _call(second_breakout, ctx=ctx, open_trade=None)

    # Should not open a new trade since done_for_day=True
    assert no_trade is None
    assert ctx.trade_opened  # still True from first trade
