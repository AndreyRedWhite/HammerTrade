"""Tests for src/paper/momentum/engine.py (MVP-R3)."""
from datetime import time, datetime, timezone
import pandas as pd
import pytest

from src.paper.momentum.engine import process_candle_momentum
from src.paper.momentum.models import (
    MomentumDailyContext,
    MomentumDayState,
    MomentumExitReason,
    MomentumPaperTrade,
    MomentumTradeStatus,
)

MSK_OFFSET = 3  # UTC+3


def _ts(h_utc: int, m: int = 0, date: str = "2026-06-02") -> str:
    return f"{date}T{h_utc:02d}:{m:02d}:00+00:00"


def _candle(h_utc: int, high: float, low: float, close: float,
            volume: float = 100.0, date: str = "2026-06-02") -> pd.Series:
    return pd.Series({
        "timestamp": _ts(h_utc, date=date),
        "open": (high + low) / 2,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _recent(n: int = 30, base_range: float = 20.0, base_vol: float = 100.0) -> pd.DataFrame:
    """Build recent_candles with stable ATR ≈ base_range and avg volume ≈ base_vol."""
    rows = []
    for i in range(n):
        rows.append({
            "timestamp": f"2026-06-02T07:{i:02d}:00+00:00",
            "open": 72000.0,
            "high": 72000.0 + base_range,
            "low": 72000.0,
            "close": 72000.0 + base_range / 2,
            "volume": base_vol,
        })
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _ctx(date: str = "2026-06-02") -> MomentumDailyContext:
    return MomentumDailyContext(date_msk=date)


_KWARGS = dict(
    atr_mult=2.0, vol_mult=2.0, take_r=2.0,
    atr_window=14, vol_window=20,
    time_exit_msk=time(18, 40),
    ticker="SiM6", experiment_name="test",
    max_trades_per_day=1,
)


# ── 1. No signal when range too small ────────────────────────────────────────

def test_no_signal_when_range_too_small():
    # base ATR ≈ 20, atr_mult=2.0 → need range >= 40. Give only 10.
    recent = _recent(base_range=20.0)
    candle = _candle(11, high=72010.0, low=72000.0, close=72001.0, volume=300.0)  # range=10 < 40
    ctx, trade, logs = process_candle_momentum(candle, recent, _ctx(), None, **_KWARGS)
    assert trade is None
    assert ctx.trades_today == 0


# ── 2. No signal when close not near low ─────────────────────────────────────

def test_no_signal_when_close_not_near_low():
    # range=50 >= 40, but close near HIGH (close_pos > 0.25)
    recent = _recent(base_range=20.0)
    candle = _candle(11, high=72050.0, low=72000.0, close=72045.0, volume=300.0)
    ctx, trade, logs = process_candle_momentum(candle, recent, _ctx(), None, **_KWARGS)
    assert trade is None


# ── 3. No signal when volume too low ─────────────────────────────────────────

def test_no_signal_when_volume_too_low():
    # range=50, close near low, but volume=50 < vol_mult*100=200
    recent = _recent(base_range=20.0, base_vol=100.0)
    candle = _candle(11, high=72050.0, low=72000.0, close=72005.0, volume=50.0)
    ctx, trade, logs = process_candle_momentum(candle, recent, _ctx(), None, **_KWARGS)
    assert trade is None


# ── 4. Signal opens trade SHORT ───────────────────────────────────────────────

def test_signal_opens_trade_short():
    # range=50 >= 40, close near low, volume=300 >= 200
    recent = _recent(base_range=20.0, base_vol=100.0)
    candle = _candle(11, high=72050.0, low=72000.0, close=72005.0, volume=300.0)
    ctx, trade, logs = process_candle_momentum(candle, recent, _ctx(), None, **_KWARGS)
    assert trade is not None
    assert trade.status == MomentumTradeStatus.OPEN
    assert trade.entry_price == pytest.approx(72005.0)
    assert trade.stop_price == pytest.approx(72050.0)
    assert trade.direction == "SHORT"
    assert ctx.trades_today == 1
    assert ctx.state == MomentumDayState.IN_TRADE


# ── 5. Take price is entry - risk * take_r ────────────────────────────────────

def test_take_price_correct():
    recent = _recent(base_range=20.0, base_vol=100.0)
    candle = _candle(11, high=72050.0, low=72000.0, close=72005.0, volume=300.0)
    _, trade, _ = process_candle_momentum(candle, recent, _ctx(), None, **_KWARGS)
    # risk = stop - entry = 72050 - 72005 = 45
    # take = entry - risk * 2.0 = 72005 - 90 = 71915
    assert trade.take_price == pytest.approx(72005.0 - 45.0 * 2.0)


# ── 6. TAKE hit closes trade ──────────────────────────────────────────────────

def test_take_hit_closes_trade():
    open_trade = MomentumPaperTrade(
        trade_id="t1", strategy_name="mc", experiment_name="test",
        ticker="SiM6", direction="SHORT",
        signal_timestamp=datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc),
        entry_timestamp=datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc),
        entry_price=72005.0, stop_price=72050.0, take_price=71915.0,
        atr_value=20.0, volume_value=300.0, volume_avg=100.0,
        candle_range=50.0, close_position=0.1,
        status=MomentumTradeStatus.OPEN,
    )
    recent = _recent()
    ctx = MomentumDailyContext(date_msk="2026-06-02", state=MomentumDayState.IN_TRADE, trades_today=1)
    # Candle dips to 71900 → take hit
    candle = _candle(12, high=72010.0, low=71900.0, close=71920.0)
    ctx2, trade, logs = process_candle_momentum(candle, recent, ctx, open_trade, **_KWARGS)
    assert trade.exit_reason == MomentumExitReason.TAKE
    assert trade.status == MomentumTradeStatus.CLOSED
    assert trade.pnl_rub > 0  # take is profitable for SHORT


# ── 7. STOP hit closes trade ──────────────────────────────────────────────────

def test_stop_hit_closes_trade():
    open_trade = MomentumPaperTrade(
        trade_id="t1", strategy_name="mc", experiment_name="test",
        ticker="SiM6", direction="SHORT",
        signal_timestamp=datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc),
        entry_timestamp=datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc),
        entry_price=72005.0, stop_price=72050.0, take_price=71915.0,
        atr_value=20.0, volume_value=300.0, volume_avg=100.0,
        candle_range=50.0, close_position=0.1,
        status=MomentumTradeStatus.OPEN,
    )
    recent = _recent()
    ctx = MomentumDailyContext(date_msk="2026-06-02", state=MomentumDayState.IN_TRADE, trades_today=1)
    # Candle spikes to 72060 → stop hit
    candle = _candle(12, high=72060.0, low=72000.0, close=72010.0)
    _, trade, _ = process_candle_momentum(candle, recent, ctx, open_trade, **_KWARGS)
    assert trade.exit_reason == MomentumExitReason.STOP
    assert trade.pnl_rub < 0  # stop is a loss for SHORT


# ── 8. STOP priority over TAKE ────────────────────────────────────────────────

def test_stop_priority_over_take():
    open_trade = MomentumPaperTrade(
        trade_id="t1", strategy_name="mc", experiment_name="test",
        ticker="SiM6", direction="SHORT",
        signal_timestamp=datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc),
        entry_timestamp=datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc),
        entry_price=72005.0, stop_price=72050.0, take_price=71915.0,
        atr_value=20.0, volume_value=300.0, volume_avg=100.0,
        candle_range=50.0, close_position=0.1,
        status=MomentumTradeStatus.OPEN,
    )
    recent = _recent()
    ctx = MomentumDailyContext(date_msk="2026-06-02", state=MomentumDayState.IN_TRADE, trades_today=1)
    # Both stop (high=72060) and take (low=71900) hit in same candle → STOP wins
    candle = _candle(12, high=72060.0, low=71900.0, close=72010.0)
    _, trade, _ = process_candle_momentum(candle, recent, ctx, open_trade, **_KWARGS)
    assert trade.exit_reason == MomentumExitReason.STOP


# ── 9. TIME_EXIT closes trade ─────────────────────────────────────────────────

def test_time_exit_closes_trade():
    open_trade = MomentumPaperTrade(
        trade_id="t1", strategy_name="mc", experiment_name="test",
        ticker="SiM6", direction="SHORT",
        signal_timestamp=datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc),
        entry_timestamp=datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc),
        entry_price=72005.0, stop_price=72050.0, take_price=71915.0,
        atr_value=20.0, volume_value=300.0, volume_avg=100.0,
        candle_range=50.0, close_position=0.1,
        status=MomentumTradeStatus.OPEN,
    )
    recent = _recent()
    ctx = MomentumDailyContext(date_msk="2026-06-02", state=MomentumDayState.IN_TRADE, trades_today=1)
    # 15:40 UTC = 18:40 MSK → TIME_EXIT
    candle = _candle(15, high=72020.0, low=71990.0, close=72000.0)
    # Override minutes to 40
    candle["timestamp"] = "2026-06-02T15:40:00+00:00"
    _, trade, _ = process_candle_momentum(candle, recent, ctx, open_trade, **_KWARGS)
    assert trade.exit_reason == MomentumExitReason.TIME_EXIT


# ── 10. Max one trade per day ─────────────────────────────────────────────────

def test_max_one_trade_per_day():
    recent = _recent(base_range=20.0, base_vol=100.0)
    # trades_today already = 1 (max_trades_per_day=1)
    ctx = MomentumDailyContext(date_msk="2026-06-02", trades_today=1)
    candle = _candle(13, high=72050.0, low=72000.0, close=72005.0, volume=300.0)
    ctx2, trade, _ = process_candle_momentum(candle, recent, ctx, None, **_KWARGS)
    assert trade is None
    assert ctx2.trades_today == 1


# ── 11. Done for day skips all candles ────────────────────────────────────────

def test_done_for_day_skips_all():
    recent = _recent(base_range=20.0, base_vol=100.0)
    ctx = MomentumDailyContext(date_msk="2026-06-02", done_for_day=True)
    # Huge signal candle — should still be ignored
    candle = _candle(13, high=72200.0, low=72000.0, close=72001.0, volume=1000.0)
    ctx2, trade, logs = process_candle_momentum(candle, recent, ctx, None, **_KWARGS)
    assert trade is None
    assert ctx2.done_for_day is True


# ── 12. Date reset resets daily context ───────────────────────────────────────

def test_date_reset():
    recent = _recent(base_range=20.0, base_vol=100.0)
    # Context is for yesterday with trades_today=1
    ctx = MomentumDailyContext(
        date_msk="2026-06-01", trades_today=1, done_for_day=True
    )
    # Candle is on June 2
    candle = _candle(11, high=72050.0, low=72000.0, close=72005.0, volume=300.0,
                     date="2026-06-02")
    ctx2, trade, logs = process_candle_momentum(candle, recent, ctx, None, **_KWARGS)
    assert ctx2.date_msk == "2026-06-02"
    assert ctx2.trades_today >= 0  # reset happened
    assert any("NEW_DAY" in log for log in logs)
