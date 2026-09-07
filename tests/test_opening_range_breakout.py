"""Tests for Opening Range Breakout strategy (Part G, ≥11 tests)."""
from __future__ import annotations

import pytest
import pandas as pd
import pytz
from datetime import datetime, time, timedelta

from src.strategies.opening_range_breakout.strategy import (
    OpeningRangeBreakoutStrategy,
    compute_opening_range,
    simulate_trade,
    _to_msk,
    _parse_time,
)
from src.strategies.base import StrategySignal

MSK = pytz.timezone("Europe/Moscow")
UTC = pytz.utc

# Real Si costs. The point value is 1.0 RUB/point (data/instruments/futures_specs.csv),
# NOT the 10.0 this module used to hardcode, and a round trip is ~38 RUB, not 0.05.
SI_POINT_VALUE_RUB = 1.0
SI_COMMISSION_RUB = 38.0


def make_candle(dt_msk: datetime, open_: float, high: float, low: float, close: float, vol: int = 100) -> dict:
    """Create a candle dict with UTC timestamp from MSK datetime."""
    if dt_msk.tzinfo is None:
        dt_msk = MSK.localize(dt_msk)
    dt_utc = dt_msk.astimezone(UTC)
    return {
        "timestamp": pd.Timestamp(dt_utc),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
    }


def make_day_candles(
    date_str: str,  # "2026-02-10"
    or_price: float = 82500.0,
    or_minutes: int = 15,
    post_or_price: float = 82500.0,
    post_or_high: float = 82500.0,
    post_or_low: float = 82500.0,
    or_start_h: int = 10,
    or_start_m: int = 0,
    session_end_h: int = 18,
    session_end_m: int = 40,
) -> pd.DataFrame:
    """
    Build a synthetic day of 1m candles.
    - OR period: from or_start with or_minutes candles at flat price or_price
    - Post-OR: candles with given high/low until session_end
    """
    candles = []
    year, month, day = [int(x) for x in date_str.split("-")]
    base_dt = MSK.localize(datetime(year, month, day, or_start_h, or_start_m, 0))

    # OR candles
    for i in range(or_minutes):
        dt = base_dt + timedelta(minutes=i)
        candles.append(make_candle(dt, or_price, or_price + 5, or_price - 5, or_price))

    # Post-OR candles
    post_start = base_dt + timedelta(minutes=or_minutes)
    session_end = MSK.localize(datetime(year, month, day, session_end_h, session_end_m, 0))
    dt = post_start
    while dt <= session_end:
        candles.append(make_candle(
            dt, post_or_price, post_or_high, post_or_low, post_or_price
        ))
        dt += timedelta(minutes=1)

    return pd.DataFrame(candles)


# ─── Test 1: OR high/low computed correctly ──────────────────────────────────

def test_or_high_low_correct():
    """OR high = max(high) and OR low = min(low) within the OR window."""
    candles = make_day_candles("2026-02-10", or_price=82500.0, or_minutes=15)
    or_info = compute_opening_range(candles, time(10, 0), time(10, 15))

    assert or_info is not None
    assert or_info["or_high"] == pytest.approx(82505.0)
    assert or_info["or_low"] == pytest.approx(82495.0)
    assert or_info["candle_count"] == 15


# ─── Test 2: Long signal on breakout up ──────────────────────────────────────

def test_long_signal_on_breakout():
    """Long signal generated when candle HIGH > OR_high after range ends."""
    or_high = 82505.0
    # First 2 candles after OR are at flat price (false breakout filter)
    # 3rd candle breaks up
    candles = make_day_candles(
        "2026-02-10",
        or_price=82500.0,
        or_minutes=15,
        post_or_high=or_high + 20,  # will break
        post_or_low=82490.0,
    )

    strategy = OpeningRangeBreakoutStrategy({
        "or_start_msk": "10:00",
        "or_end_msk": "10:15",
        "direction": "long",
        "take_r": 1.5,
        "false_breakout_bars": 2,
    })
    signals = strategy.generate_signals(candles, {"ticker": "SiM6"})

    assert len(signals) == 1
    assert signals[0].direction == "LONG"
    assert signals[0].entry_price == pytest.approx(or_high)


# ─── Test 3: Short signal on breakout down ───────────────────────────────────

def test_short_signal_on_breakout():
    """Short signal generated when candle LOW < OR_low after range ends."""
    or_low = 82495.0
    candles = make_day_candles(
        "2026-02-10",
        or_price=82500.0,
        or_minutes=15,
        post_or_high=82500.0,
        post_or_low=or_low - 20,  # will break down
    )

    strategy = OpeningRangeBreakoutStrategy({
        "or_start_msk": "10:00",
        "or_end_msk": "10:15",
        "direction": "short",
        "take_r": 1.5,
        "false_breakout_bars": 2,
    })
    signals = strategy.generate_signals(candles, {"ticker": "SiM6"})

    assert len(signals) == 1
    assert signals[0].direction == "SHORT"
    assert signals[0].entry_price == pytest.approx(or_low)


# ─── Test 4: No signal within OR window (no look-ahead) ──────────────────────

def test_no_signal_within_or_window():
    """No signal generated if breakout happens inside the OR window itself."""
    # Create candles where the high exceeds or_high but that candle is during OR
    candles = []
    date_str = "2026-02-10"
    year, month, day = 2026, 2, 10
    base_dt = MSK.localize(datetime(year, month, day, 10, 0, 0))

    # OR candle at 10:00 has very high high — but this is within OR
    candles.append(make_candle(base_dt, 82500.0, 82600.0, 82480.0, 82500.0))
    for i in range(1, 15):
        candles.append(make_candle(base_dt + timedelta(minutes=i), 82500.0, 82505.0, 82495.0, 82500.0))

    # Post-OR candles — flat (no breakout after OR)
    for i in range(15, 15 + 30):
        dt = base_dt + timedelta(minutes=i)
        candles.append(make_candle(dt, 82500.0, 82504.0, 82496.0, 82500.0))

    df = pd.DataFrame(candles)
    or_high = 82505.0  # max of OR candles after the first weird candle

    # With default strategy direction=long, no post-OR breakout should trigger
    strategy = OpeningRangeBreakoutStrategy({
        "or_start_msk": "10:00",
        "or_end_msk": "10:15",
        "direction": "long",
        "take_r": 1.5,
        "false_breakout_bars": 2,
    })
    signals = strategy.generate_signals(df, {"ticker": "SiM6"})

    # Should be no long signal since post-OR candles don't exceed OR high (82505)
    assert len(signals) == 0


# ─── Test 5: False breakout filter — no signal in first 2 candles ────────────

def test_false_breakout_filter():
    """No signal in first 2 candles after OR ends (false breakout filter)."""
    # Create candles where only bars 0 and 1 after OR have a breakout
    candles = []
    year, month, day = 2026, 2, 10
    base_dt = MSK.localize(datetime(year, month, day, 10, 0, 0))

    # OR candles (10:00-10:14)
    for i in range(15):
        candles.append(make_candle(base_dt + timedelta(minutes=i), 82500.0, 82505.0, 82495.0, 82500.0))

    # Bar 0 after OR (10:15) — big breakout, but filtered
    candles.append(make_candle(base_dt + timedelta(minutes=15), 82500.0, 82600.0, 82490.0, 82510.0))
    # Bar 1 after OR (10:16) — also breakout, but filtered
    candles.append(make_candle(base_dt + timedelta(minutes=16), 82500.0, 82600.0, 82490.0, 82510.0))
    # Bar 2+ (10:17 onwards) — back to flat, no breakout
    for i in range(17, 17 + 30):
        candles.append(make_candle(base_dt + timedelta(minutes=i), 82500.0, 82504.0, 82496.0, 82500.0))

    df = pd.DataFrame(candles)

    strategy = OpeningRangeBreakoutStrategy({
        "or_start_msk": "10:00",
        "or_end_msk": "10:15",
        "direction": "long",
        "take_r": 1.5,
        "false_breakout_bars": 2,
    })
    signals = strategy.generate_signals(df, {"ticker": "SiM6"})

    # No signal because only the first 2 post-OR bars break out (filtered)
    assert len(signals) == 0


# ─── Test 6: One trade per day ───────────────────────────────────────────────

def test_one_trade_per_day():
    """One trade per day — second breakout in same day ignored."""
    candles = make_day_candles(
        "2026-02-10",
        or_price=82500.0,
        or_minutes=15,
        post_or_high=82600.0,  # continuous breakout all day
        post_or_low=82400.0,
    )

    strategy = OpeningRangeBreakoutStrategy({
        "or_start_msk": "10:00",
        "or_end_msk": "10:15",
        "direction": "long",
        "take_r": 1.5,
        "false_breakout_bars": 2,
    })
    signals = strategy.generate_signals(candles, {"ticker": "SiM6"})

    # Should generate at most 1 signal for this day
    assert len(signals) <= 1


# ─── Test 7: Stop = OR_low for long ──────────────────────────────────────────

def test_stop_or_low_for_long():
    """Long signal: stop_price == OR_low."""
    candles = make_day_candles(
        "2026-02-10",
        or_price=82500.0,
        or_minutes=15,
        post_or_high=82600.0,
        post_or_low=82400.0,
    )

    strategy = OpeningRangeBreakoutStrategy({
        "or_start_msk": "10:00",
        "or_end_msk": "10:15",
        "direction": "long",
        "take_r": 1.5,
        "false_breakout_bars": 2,
    })
    signals = strategy.generate_signals(candles, {"ticker": "SiM6"})

    assert len(signals) == 1
    # OR_low = 82495 (or_price - 5)
    assert signals[0].stop_price == pytest.approx(82495.0)


# ─── Test 8: Stop = OR_high for short ────────────────────────────────────────

def test_stop_or_high_for_short():
    """Short signal: stop_price == OR_high."""
    candles = make_day_candles(
        "2026-02-10",
        or_price=82500.0,
        or_minutes=15,
        post_or_high=82505.0,
        post_or_low=82400.0,
    )

    strategy = OpeningRangeBreakoutStrategy({
        "or_start_msk": "10:00",
        "or_end_msk": "10:15",
        "direction": "short",
        "take_r": 1.5,
        "false_breakout_bars": 2,
    })
    signals = strategy.generate_signals(candles, {"ticker": "SiM6"})

    assert len(signals) == 1
    # OR_high = 82505
    assert signals[0].stop_price == pytest.approx(82505.0)


# ─── Test 9: take_r=1.0 for long ─────────────────────────────────────────────

def test_take_r_long():
    """take_r=1.0: take_price = entry + (entry - stop) * 1.0."""
    candles = make_day_candles(
        "2026-02-10",
        or_price=82500.0,
        or_minutes=15,
        post_or_high=82600.0,
        post_or_low=82400.0,
    )

    strategy = OpeningRangeBreakoutStrategy({
        "or_start_msk": "10:00",
        "or_end_msk": "10:15",
        "direction": "long",
        "take_r": 1.0,
        "false_breakout_bars": 2,
    })
    signals = strategy.generate_signals(candles, {"ticker": "SiM6"})

    assert len(signals) == 1
    sig = signals[0]
    risk = sig.entry_price - sig.stop_price  # = 82505 - 82495 = 10
    expected_take = sig.entry_price + risk * 1.0
    assert sig.take_price == pytest.approx(expected_take)


# ─── Test 10: Time exit at 18:40 MSK ─────────────────────────────────────────

def test_time_exit_at_1840():
    """Trade closes at 18:40 MSK if not stopped/taken."""
    # Build minimal signal
    year, month, day = 2026, 2, 10
    entry_dt_msk = MSK.localize(datetime(year, month, day, 11, 0, 0))
    entry_dt_utc = entry_dt_msk.astimezone(UTC)

    sig = StrategySignal(
        strategy_name="opening_range_breakout",
        ticker="SiM6",
        direction="LONG",
        timestamp=pd.Timestamp(entry_dt_utc),
        entry_price=82500.0,
        stop_price=82400.0,  # stop far away
        take_price=83500.0,  # take far away
        reason="test",
    )

    # Post-OR candles: flat price, never touching stop/take
    candles = []
    dt = entry_dt_msk
    while dt <= MSK.localize(datetime(year, month, day, 18, 45, 0)):
        utc_dt = dt.astimezone(UTC)
        candles.append({
            "timestamp": pd.Timestamp(utc_dt),
            "open": 82500.0,
            "high": 82510.0,
            "low": 82490.0,
            "close": 82500.0,
            "volume": 100,
        })
        dt += timedelta(minutes=1)

    post_candles = pd.DataFrame(candles)
    result = simulate_trade(
        sig, post_candles, time_exit_msk=time(18, 40),
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB,
    )

    assert result["exit_reason"] == "TIME_EXIT"


# ─── Test 11: Degenerate OR range < 10 points → skip ─────────────────────────

def test_degenerate_or_range_skipped():
    """OR with range < 10 points → no signal."""
    # OR price very flat: high = price+3, low = price-3 → range = 6 < 10
    candles = []
    year, month, day = 2026, 2, 10
    base_dt = MSK.localize(datetime(year, month, day, 10, 0, 0))

    for i in range(15):
        candles.append(make_candle(base_dt + timedelta(minutes=i), 82500.0, 82503.0, 82497.0, 82500.0))

    # Post-OR: strong breakout
    for i in range(15, 15 + 30):
        candles.append(make_candle(base_dt + timedelta(minutes=i), 82500.0, 82600.0, 82400.0, 82500.0))

    df = pd.DataFrame(candles)

    strategy = OpeningRangeBreakoutStrategy({
        "or_start_msk": "10:00",
        "or_end_msk": "10:15",
        "direction": "long",
        "take_r": 1.5,
        "min_range_points": 10.0,
        "false_breakout_bars": 2,
    })
    signals = strategy.generate_signals(df, {"ticker": "SiM6"})

    assert len(signals) == 0


# ─── Test 12: OR insufficient candles → skip ─────────────────────────────────

def test_or_insufficient_candles_skipped():
    """OR with < 5 candles → no signal (holiday/gap protection)."""
    candles = []
    year, month, day = 2026, 2, 10
    base_dt = MSK.localize(datetime(year, month, day, 10, 0, 0))

    # Only 3 OR candles
    for i in range(3):
        candles.append(make_candle(base_dt + timedelta(minutes=i), 82500.0, 82510.0, 82490.0, 82500.0))

    # Post-OR: strong breakout
    for i in range(15, 15 + 30):
        candles.append(make_candle(base_dt + timedelta(minutes=i), 82500.0, 82600.0, 82400.0, 82500.0))

    df = pd.DataFrame(candles)

    strategy = OpeningRangeBreakoutStrategy({
        "or_start_msk": "10:00",
        "or_end_msk": "10:15",
        "direction": "long",
        "take_r": 1.5,
        "false_breakout_bars": 2,
    })
    signals = strategy.generate_signals(df, {"ticker": "SiM6"})

    assert len(signals) == 0


# ─── Test 13: simulate_trade TAKE exit ───────────────────────────────────────

def test_simulate_trade_take():
    """simulate_trade returns TAKE when take price is hit."""
    year, month, day = 2026, 2, 10
    entry_dt_msk = MSK.localize(datetime(year, month, day, 11, 0, 0))
    entry_dt_utc = entry_dt_msk.astimezone(UTC)

    sig = StrategySignal(
        strategy_name="opening_range_breakout",
        ticker="SiM6",
        direction="LONG",
        timestamp=pd.Timestamp(entry_dt_utc),
        entry_price=82500.0,
        stop_price=82400.0,
        take_price=82600.0,
        reason="test",
    )

    candles = []
    dt = entry_dt_msk
    # First 3 candles flat
    for i in range(3):
        utc_dt = (dt + timedelta(minutes=i)).astimezone(UTC)
        candles.append({
            "timestamp": pd.Timestamp(utc_dt),
            "open": 82500.0, "high": 82520.0, "low": 82490.0, "close": 82510.0, "volume": 100,
        })
    # 4th candle hits take
    take_dt = (dt + timedelta(minutes=3)).astimezone(UTC)
    candles.append({
        "timestamp": pd.Timestamp(take_dt),
        "open": 82560.0, "high": 82650.0, "low": 82550.0, "close": 82620.0, "volume": 100,
    })

    post_candles = pd.DataFrame(candles)
    result = simulate_trade(
        sig, post_candles, time_exit_msk=time(18, 40),
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB,
    )

    assert result["exit_reason"] == "TAKE"
    assert result["exit_price"] == pytest.approx(82600.0)
    assert result["pnl_points"] > 0


# ─── Test 14: simulate_trade STOP exit ───────────────────────────────────────

def test_simulate_trade_stop():
    """simulate_trade returns STOP when stop price is hit."""
    year, month, day = 2026, 2, 10
    entry_dt_msk = MSK.localize(datetime(year, month, day, 11, 0, 0))
    entry_dt_utc = entry_dt_msk.astimezone(UTC)

    sig = StrategySignal(
        strategy_name="opening_range_breakout",
        ticker="SiM6",
        direction="LONG",
        timestamp=pd.Timestamp(entry_dt_utc),
        entry_price=82500.0,
        stop_price=82450.0,
        take_price=82600.0,
        reason="test",
    )

    candles = []
    dt = entry_dt_msk
    # First candle hits stop
    utc_dt = dt.astimezone(UTC)
    candles.append({
        "timestamp": pd.Timestamp(utc_dt),
        "open": 82500.0, "high": 82510.0, "low": 82430.0, "close": 82440.0, "volume": 100,
    })

    post_candles = pd.DataFrame(candles)
    result = simulate_trade(
        sig, post_candles, time_exit_msk=time(18, 40),
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB,
    )

    assert result["exit_reason"] == "STOP"
    assert result["exit_price"] == pytest.approx(82450.0)
    assert result["pnl_points"] < 0


# ─── Gap handling: a stop is only fillable if price trades through it ────────

def _one_bar_post_candles(open_, high, low, close):
    """Single post-entry candle at 12:00 MSK (well before any time exit)."""
    dt = MSK.localize(datetime(2026, 1, 20, 12, 0))
    return pd.DataFrame([{
        "timestamp": pd.Timestamp(dt.astimezone(UTC)),
        "open": open_, "high": high, "low": low, "close": close, "volume": 100,
    }])


def _sig(direction, entry, stop, take):
    return StrategySignal(
        strategy_name="opening_range_breakout",
        ticker="SiM6",
        direction=direction,
        timestamp=pd.Timestamp(MSK.localize(datetime(2026, 1, 20, 11, 0)).astimezone(UTC)),
        entry_price=entry,
        stop_price=stop,
        take_price=take,
        reason="test",
    )


def test_long_gapping_through_stop_fills_at_the_open_not_the_stop():
    """A bar that OPENS below the stop never offered the stop price.

    Booking the exit at the stop credits a price that did not exist, and it does
    so on the worst trades — the tail that sets profit factor.
    """
    sig = _sig("LONG", entry=82500.0, stop=82450.0, take=82600.0)
    # Opens at 82400 — a full 50 points BELOW the stop.
    post = _one_bar_post_candles(open_=82400.0, high=82420.0, low=82380.0, close=82390.0)

    result = simulate_trade(
        sig, post, time_exit_msk=time(18, 40),
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB,
    )

    assert result["exit_reason"] == "STOP_GAP"
    assert result["exit_price"] == 82400.0
    assert result["pnl_points"] == pytest.approx(-100.0)  # not the -50 a stop fill implies


def test_short_gapping_through_stop_fills_at_the_open():
    sig = _sig("SHORT", entry=82500.0, stop=82550.0, take=82400.0)
    post = _one_bar_post_candles(open_=82600.0, high=82620.0, low=82580.0, close=82610.0)

    result = simulate_trade(
        sig, post, time_exit_msk=time(18, 40),
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB,
    )

    assert result["exit_reason"] == "STOP_GAP"
    assert result["exit_price"] == 82600.0
    assert result["pnl_points"] == pytest.approx(-100.0)


def test_normal_intrabar_stop_still_fills_at_the_stop_level():
    """No gap: price opens inside the range and trades down through the stop."""
    sig = _sig("LONG", entry=82500.0, stop=82450.0, take=82600.0)
    post = _one_bar_post_candles(open_=82495.0, high=82500.0, low=82430.0, close=82440.0)

    result = simulate_trade(
        sig, post, time_exit_msk=time(18, 40),
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB,
    )

    assert result["exit_reason"] == "STOP"
    assert result["exit_price"] == 82450.0
    assert result["pnl_points"] == pytest.approx(-50.0)


def test_favourable_gap_through_take_also_fills_at_the_open():
    """Symmetry: gaps are modelled in both directions, not only against us."""
    sig = _sig("LONG", entry=82500.0, stop=82450.0, take=82600.0)
    post = _one_bar_post_candles(open_=82650.0, high=82680.0, low=82640.0, close=82660.0)

    result = simulate_trade(
        sig, post, time_exit_msk=time(18, 40),
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB,
    )

    assert result["exit_reason"] == "TAKE_GAP"
    assert result["exit_price"] == 82650.0
    assert result["pnl_points"] == pytest.approx(150.0)


def test_stop_still_wins_over_take_within_the_same_bar():
    """Pre-existing conservative convention must survive the gap change."""
    sig = _sig("LONG", entry=82500.0, stop=82450.0, take=82600.0)
    # Opens inside; the bar touches BOTH the take and the stop.
    post = _one_bar_post_candles(open_=82500.0, high=82650.0, low=82400.0, close=82500.0)

    result = simulate_trade(
        sig, post, time_exit_msk=time(18, 40),
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB,
    )

    assert result["exit_reason"] == "STOP"


def test_simulate_trade_rejects_missing_or_absurd_costs():
    sig = _sig("LONG", entry=82500.0, stop=82450.0, take=82600.0)
    post = _one_bar_post_candles(82495.0, 82500.0, 82430.0, 82440.0)

    with pytest.raises(TypeError):
        simulate_trade(sig, post, time_exit_msk=time(18, 40))
    with pytest.raises(ValueError, match="point_value_rub"):
        simulate_trade(sig, post, time_exit_msk=time(18, 40),
                       point_value_rub=0.0, commission_rub=38.0)
    with pytest.raises(ValueError, match="commission_rub"):
        simulate_trade(sig, post, time_exit_msk=time(18, 40),
                       point_value_rub=1.0, commission_rub=-1.0)
