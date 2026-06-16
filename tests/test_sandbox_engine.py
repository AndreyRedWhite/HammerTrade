"""Tests for src/sandbox/engine.py (MVP-L1a).

These tests exercise the SandboxTrade <-> PaperTrade translation and the
decision state machine. The underlying signal/exit logic itself is provided
by src.paper.engine.process_candle (reused unchanged, see test_paper_engine
or equivalent for full coverage of that logic).
"""
import pandas as pd

from src.sandbox.engine import (
    expected_position_from_trade,
    process_sandbox_candle,
)
from src.sandbox.models import SandboxExitReason, SandboxTradeStatus
from src.sandbox.reconciliation import PositionView

ENGINE_KWARGS = dict(
    direction_filter="SELL",
    entry_mode="breakout",
    entry_horizon_bars=3,
    max_hold_bars=5,
    take_r=1.0,
    stop_buffer_points=0.0,
    slippage_ticks=1.0,
    tick_size=1.0,
    point_value_rub=10.0,
    commission_per_trade=0.025,
    contracts=1,
    ticker="SiU6",
    class_code="SPBFUT",
    timeframe="1m",
    profile="balanced",
    experiment_name="sandbox_hammer_maxhold5",
)


def _candle(ts, o, h, l, c, is_signal=False, direction_candidate="", fail_reason="pass"):
    return pd.Series({
        "timestamp": pd.Timestamp(ts, tz="UTC"),
        "open": o, "high": h, "low": l, "close": c,
        "is_signal": is_signal,
        "direction_candidate": direction_candidate,
        "fail_reason": fail_reason,
    })


def test_idle_candle_no_signal_returns_none():
    candle = _candle("2026-06-11T10:00:00Z", 100, 101, 99, 100)
    result = process_sandbox_candle(candle, open_trade=None, pending_signal=None, **ENGINE_KWARGS)
    assert result.decision == "NONE"
    assert result.trade is None
    assert result.pending_signal is None


def test_signal_candle_creates_pending_signal():
    candle = _candle(
        "2026-06-11T10:00:00Z", 102, 105, 100, 101,
        is_signal=True, direction_candidate="SELL",
    )
    result = process_sandbox_candle(candle, open_trade=None, pending_signal=None, **ENGINE_KWARGS)
    assert result.decision == "PENDING"
    assert result.trade is None
    assert result.pending_signal is not None
    assert result.pending_signal["direction"] == "SELL"
    assert result.pending_signal["entry_trigger"] == 100
    assert result.pending_signal["stop_price"] == 105
    assert result.pending_signal["take_price"] == 95


def test_entry_trigger_hit_creates_open_trade():
    pending_signal = {
        "direction": "SELL",
        "signal_timestamp": "2026-06-11 10:00:00+00:00",
        "entry_trigger": 100,
        "stop_price": 105,
        "take_price": 95,
        "bars_remaining": 3,
    }
    candle = _candle("2026-06-11T10:01:00Z", 100, 101, 99, 99.5)
    result = process_sandbox_candle(candle, open_trade=None, pending_signal=pending_signal, **ENGINE_KWARGS)

    assert result.decision == "ENTRY"
    trade = result.trade
    assert trade is not None
    assert trade.status == SandboxTradeStatus.OPEN
    assert trade.direction == "SELL"
    assert trade.qty == 1
    assert trade.entry_price == 99.0  # entry_trigger(100) - slippage(1)
    assert trade.stop_price == 105
    assert trade.take_price == 95
    assert trade.bars_held == 0
    assert result.pending_signal is None


def test_open_trade_holds_when_no_exit_condition():
    pending_signal = {
        "direction": "SELL",
        "signal_timestamp": "2026-06-11 10:00:00+00:00",
        "entry_trigger": 100,
        "stop_price": 105,
        "take_price": 95,
        "bars_remaining": 3,
    }
    entry_candle = _candle("2026-06-11T10:01:00Z", 100, 101, 99, 99.5)
    entry_result = process_sandbox_candle(entry_candle, open_trade=None, pending_signal=pending_signal, **ENGINE_KWARGS)
    open_trade = entry_result.trade

    hold_candle = _candle("2026-06-11T10:02:00Z", 99.5, 102, 96, 98)
    result = process_sandbox_candle(hold_candle, open_trade=open_trade, pending_signal=None, **ENGINE_KWARGS)

    assert result.decision == "HOLD"
    assert result.trade.status == SandboxTradeStatus.OPEN
    assert result.trade.bars_held == 1


def test_open_trade_exits_on_take():
    pending_signal = {
        "direction": "SELL",
        "signal_timestamp": "2026-06-11 10:00:00+00:00",
        "entry_trigger": 100,
        "stop_price": 105,
        "take_price": 95,
        "bars_remaining": 3,
    }
    entry_candle = _candle("2026-06-11T10:01:00Z", 100, 101, 99, 99.5)
    entry_result = process_sandbox_candle(entry_candle, open_trade=None, pending_signal=pending_signal, **ENGINE_KWARGS)
    open_trade = entry_result.trade

    take_candle = _candle("2026-06-11T10:02:00Z", 98, 99, 94, 95)
    result = process_sandbox_candle(take_candle, open_trade=open_trade, pending_signal=None, **ENGINE_KWARGS)

    assert result.decision == "EXIT"
    trade = result.trade
    assert trade.status == SandboxTradeStatus.CLOSED
    assert trade.exit_reason == SandboxExitReason.TAKE
    assert trade.exit_price == 96.0  # take_price(95) + slippage(1)
    assert trade.gross_pnl_rub == 30.0  # (entry 99 - exit 96) * 10 RUB * 1 lot
    assert trade.commission_rub == 0.05
    assert trade.net_pnl_rub == 29.95


def test_open_trade_exits_on_max_hold(monkeypatch=None):
    pending_signal = {
        "direction": "SELL",
        "signal_timestamp": "2026-06-11 10:00:00+00:00",
        "entry_trigger": 100,
        "stop_price": 105,
        "take_price": 95,
        "bars_remaining": 3,
    }
    entry_candle = _candle("2026-06-11T10:01:00Z", 100, 101, 99, 99.5)
    entry_result = process_sandbox_candle(entry_candle, open_trade=None, pending_signal=pending_signal, **ENGINE_KWARGS)
    open_trade = entry_result.trade

    flat_candle = _candle("2026-06-11T10:02:00Z", 99.5, 102, 96, 98)
    for _ in range(5):
        result = process_sandbox_candle(flat_candle, open_trade=open_trade, pending_signal=None, **ENGINE_KWARGS)
        open_trade = result.trade
        if result.decision == "EXIT":
            break

    assert result.decision == "EXIT"
    assert open_trade.exit_reason == SandboxExitReason.MAX_HOLD_EXIT
    assert open_trade.bars_held == 5


def test_expected_position_from_trade():
    assert expected_position_from_trade(None) == PositionView("FLAT", 0)

    pending_signal = {
        "direction": "SELL",
        "signal_timestamp": "2026-06-11 10:00:00+00:00",
        "entry_trigger": 100,
        "stop_price": 105,
        "take_price": 95,
        "bars_remaining": 3,
    }
    entry_candle = _candle("2026-06-11T10:01:00Z", 100, 101, 99, 99.5)
    entry_result = process_sandbox_candle(entry_candle, open_trade=None, pending_signal=pending_signal, **ENGINE_KWARGS)
    open_trade = entry_result.trade

    assert expected_position_from_trade(open_trade) == PositionView("SHORT", 1)

    open_trade.status = SandboxTradeStatus.CLOSED
    assert expected_position_from_trade(open_trade) == PositionView("FLAT", 0)
