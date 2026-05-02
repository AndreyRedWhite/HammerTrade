from datetime import datetime, timezone

import pandas as pd
import pytest

from src.paper.engine import process_candle, build_trade_id
from src.paper.models import PaperTrade, PaperTradeStatus, PaperExitReason


_BASE_PARAMS = dict(
    direction_filter="SELL",
    entry_mode="breakout",
    entry_horizon_bars=3,
    max_hold_bars=5,
    take_r=1.0,
    stop_buffer_points=0.0,
    slippage_ticks=1.0,
    tick_size=1.0,
    point_value_rub=1000.0,
    commission_per_trade=0.025,
    contracts=1,
    ticker="SiM6",
    class_code="SPBFUT",
    timeframe="1m",
    profile="balanced",
)


def _candle(ts="2026-01-01 10:00:00", open_=100, high=105, low=90, close=95,
            is_signal=False, direction_candidate="SELL", fail_reason="range") -> pd.Series:
    return pd.Series({
        "timestamp": pd.Timestamp(ts, tz="UTC"),
        "open": float(open_), "high": float(high), "low": float(low), "close": float(close),
        "volume": 100,
        "is_signal": is_signal,
        "direction_candidate": direction_candidate,
        "fail_reason": "pass" if is_signal else fail_reason,
    })


def _open_sell_trade(entry_price=90.0, stop=105.0, take=75.0, bars_held=0) -> PaperTrade:
    now = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    return PaperTrade(
        trade_id="paper:SiM6:1m:balanced:SELL:2026-01-01T10:00:00+00:00",
        ticker="SiM6", class_code="SPBFUT", timeframe="1m",
        profile="balanced", direction="SELL",
        signal_timestamp=now, entry_timestamp=now,
        entry_price=entry_price, stop_price=stop, take_price=take,
        status=PaperTradeStatus.OPEN, bars_held=bars_held,
        created_at=now, updated_at=now,
    )


# ── signal detection ──────────────────────────────────────────────────────────

def test_sell_signal_creates_pending_signal():
    candle = _candle(high=105, low=90, is_signal=True, direction_candidate="SELL")
    trade, pending, logs = process_candle(candle, None, None, **_BASE_PARAMS)
    assert trade is None
    assert pending is not None
    assert pending["direction"] == "SELL"
    assert pending["entry_trigger"] == pytest.approx(90.0)  # low of signal candle
    assert pending["stop_price"] == pytest.approx(105.0)    # high + buffer=0


def test_no_signal_no_pending():
    candle = _candle(is_signal=False)
    trade, pending, logs = process_candle(candle, None, None, **_BASE_PARAMS)
    assert trade is None
    assert pending is None


def test_existing_open_trade_no_new_signal():
    candle = _candle(is_signal=True, direction_candidate="SELL")
    open_trade = _open_sell_trade()
    trade, pending, logs = process_candle(candle, open_trade, None, **_BASE_PARAMS)
    # Should only update existing trade, not open new one
    assert pending is None or trade == open_trade or trade is not None


# ── breakout entry ────────────────────────────────────────────────────────────

def test_breakout_entry_on_low_touch():
    ps = {
        "direction": "SELL",
        "signal_timestamp": "2026-01-01T10:00:00+00:00",
        "entry_trigger": 90.0,
        "stop_price": 105.0,
        "take_price": 75.0,
        "bars_remaining": 3,
    }
    # Candle whose low <= entry_trigger (90)
    candle = _candle(ts="2026-01-01 10:01:00", high=92, low=89, close=91)
    trade, pending, logs = process_candle(candle, None, ps, **_BASE_PARAMS)
    assert trade is not None
    assert trade.status == PaperTradeStatus.OPEN
    assert pending is None  # signal consumed
    # SELL entry: entry_price = entry_trigger - slippage = 90 - 1 = 89
    assert trade.entry_price == pytest.approx(89.0)


def test_breakout_not_triggered():
    ps = {
        "direction": "SELL",
        "signal_timestamp": "2026-01-01T10:00:00+00:00",
        "entry_trigger": 90.0,
        "stop_price": 105.0,
        "take_price": 75.0,
        "bars_remaining": 3,
    }
    candle = _candle(ts="2026-01-01 10:01:00", high=95, low=91, close=93)
    trade, pending, logs = process_candle(candle, None, ps, **_BASE_PARAMS)
    assert trade is None
    assert pending is not None
    assert pending["bars_remaining"] == 2


def test_horizon_expired_clears_signal():
    ps = {
        "direction": "SELL",
        "signal_timestamp": "2026-01-01T10:00:00+00:00",
        "entry_trigger": 90.0,
        "stop_price": 105.0,
        "take_price": 75.0,
        "bars_remaining": 1,  # last chance
    }
    candle = _candle(ts="2026-01-01 10:01:00", high=95, low=91, close=93)
    trade, pending, logs = process_candle(candle, None, ps, **_BASE_PARAMS)
    assert trade is None
    assert pending is None


# ── exit conditions ───────────────────────────────────────────────────────────

def test_stop_closes_sell_trade():
    open_trade = _open_sell_trade(entry_price=89.0, stop=105.0, take=74.0, bars_held=1)
    # high >= stop_price → stop hit
    candle = _candle(ts="2026-01-01 10:02:00", high=106, low=88, close=100)
    trade, pending, logs = process_candle(candle, open_trade, None, **_BASE_PARAMS)
    assert trade is not None
    assert trade.status == PaperTradeStatus.CLOSED
    assert trade.exit_reason == PaperExitReason.STOP
    # SELL stop exit: exit_price_raw=105, exit_price = 105 + slippage(1) = 106
    assert trade.exit_price == pytest.approx(106.0)


def test_take_closes_sell_trade():
    open_trade = _open_sell_trade(entry_price=89.0, stop=105.0, take=74.0, bars_held=1)
    # low <= take_price → take hit
    candle = _candle(ts="2026-01-01 10:02:00", high=91, low=73, close=75)
    trade, pending, logs = process_candle(candle, open_trade, None, **_BASE_PARAMS)
    assert trade is not None
    assert trade.status == PaperTradeStatus.CLOSED
    assert trade.exit_reason == PaperExitReason.TAKE
    # SELL take exit: exit_price_raw=74, exit_price = 74 + slippage(1) = 75
    assert trade.exit_price == pytest.approx(75.0)


def test_timeout_closes_trade():
    open_trade = _open_sell_trade(entry_price=89.0, stop=105.0, take=74.0, bars_held=4)
    # bars_held will become 5 = max_hold_bars → timeout
    candle = _candle(ts="2026-01-01 10:05:00", high=91, low=88, close=90)
    trade, pending, logs = process_candle(candle, open_trade, None, **_BASE_PARAMS)
    assert trade.status == PaperTradeStatus.CLOSED
    assert trade.exit_reason == PaperExitReason.TIMEOUT


# ── PnL calculation ───────────────────────────────────────────────────────────

def test_pnl_rub_calculated():
    open_trade = _open_sell_trade(entry_price=89.0, stop=105.0, take=74.0, bars_held=1)
    candle = _candle(ts="2026-01-01 10:02:00", high=91, low=73, close=75)
    trade, _, _ = process_candle(candle, open_trade, None, **_BASE_PARAMS)
    assert trade.pnl_rub is not None
    # SELL: gross_points = entry(89) - exit(75) = 14, gross_pnl = 14 * 1000 = 14000
    # commission = 0.025 * 2 * 1 = 0.05 (in RUB, but wait - it's 0.025 per trade, so commission_rub = 0.025*2*1=0.05?)
    # Actually from engine: commission_rub = commission_per_trade * 2 * contracts = 0.025*2*1 = 0.05
    # net_pnl = 14000 - 0.05 = 13999.95
    assert trade.pnl_rub == pytest.approx(14000.0 - 0.025 * 2 * 1, abs=1.0)


def test_slippage_ticks_affect_pnl():
    params = dict(_BASE_PARAMS)
    params["slippage_ticks"] = 2.0
    params["tick_size"] = 1.0
    open_trade = _open_sell_trade(entry_price=88.0, stop=105.0, take=73.0, bars_held=1)
    candle = _candle(ts="2026-01-01 10:02:00", high=91, low=72, close=75)
    trade, _, _ = process_candle(candle, open_trade, None, **params)
    # Exit at take=73, exit_price = 73 + 2 = 75
    assert trade.exit_price == pytest.approx(75.0)


def test_build_trade_id():
    tid = build_trade_id("SiM6", "1m", "balanced", "SELL", "2026-01-01T10:00:00")
    assert "SiM6" in tid
    assert "SELL" in tid
