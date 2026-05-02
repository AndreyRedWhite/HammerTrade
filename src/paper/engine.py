"""Paper trading execution engine — processes one closed candle at a time."""
import json
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from src.paper.models import PaperTrade, PaperTradeStatus, PaperExitReason


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def build_trade_id(ticker: str, timeframe: str, profile: str, direction: str, signal_ts) -> str:
    ts = pd.Timestamp(signal_ts).isoformat() if not isinstance(signal_ts, str) else signal_ts
    return f"paper:{ticker}:{timeframe}:{profile}:{direction}:{ts}"


def process_candle(
    candle: pd.Series,
    open_trade: Optional[PaperTrade],
    pending_signal: Optional[dict],
    direction_filter: str,
    entry_mode: str = "breakout",
    entry_horizon_bars: int = 3,
    max_hold_bars: int = 30,
    take_r: float = 1.0,
    stop_buffer_points: float = 0.0,
    slippage_ticks: float = 1.0,
    tick_size: float = 1.0,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
    ticker: str = "",
    class_code: str = "",
    timeframe: str = "",
    profile: str = "",
) -> tuple[Optional[PaperTrade], Optional[dict], list[str]]:
    """Process one newly closed candle.

    Returns:
        (updated_or_new_trade, updated_pending_signal, log_messages)
        - updated_or_new_trade: trade to upsert into DB, or None if no change
        - updated_pending_signal: new pending signal state (None = clear it)
        - log_messages: list of strings to log
    """
    effective_slippage = slippage_ticks * tick_size
    commission_rub = commission_per_trade * 2 * contracts
    logs: list[str] = []
    candle_ts = pd.Timestamp(candle["timestamp"])
    is_signal = bool(candle.get("is_signal", False)) and str(candle.get("fail_reason", "")) == "pass"
    direction_candidate = str(candle.get("direction_candidate", "")).upper()
    is_matching_signal = is_signal and (
        direction_filter == "all" or direction_candidate == direction_filter.upper()
    )

    # ── Case 1: managing an open trade ──────────────────────────────────────
    if open_trade is not None and open_trade.status == PaperTradeStatus.OPEN:
        open_trade.bars_held += 1
        direction = open_trade.direction

        if direction == "BUY":
            stop_hit = float(candle["low"]) <= open_trade.stop_price
            take_hit = float(candle["high"]) >= open_trade.take_price
        else:
            stop_hit = float(candle["high"]) >= open_trade.stop_price
            take_hit = float(candle["low"]) <= open_trade.take_price

        timeout = open_trade.bars_held >= max_hold_bars

        if stop_hit and take_hit:
            exit_price_raw = open_trade.stop_price
            reason = PaperExitReason.STOP
        elif stop_hit:
            exit_price_raw = open_trade.stop_price
            reason = PaperExitReason.STOP
        elif take_hit:
            exit_price_raw = open_trade.take_price
            reason = PaperExitReason.TAKE
        elif timeout:
            exit_price_raw = float(candle["close"])
            reason = PaperExitReason.TIMEOUT
        else:
            logs.append(f"  trade {open_trade.trade_id} still open, bars_held={open_trade.bars_held}")
            return open_trade, pending_signal, logs

        # Apply exit slippage (BUY: sell worse → lower; SELL: buy to close → higher)
        if direction == "BUY":
            exit_price = exit_price_raw - effective_slippage
            gross_points = exit_price - open_trade.entry_price
        else:
            exit_price = exit_price_raw + effective_slippage
            gross_points = open_trade.entry_price - exit_price

        gross_pnl_rub = gross_points * point_value_rub * contracts
        net_pnl_rub = gross_pnl_rub - commission_rub

        open_trade.status = PaperTradeStatus.CLOSED
        open_trade.exit_timestamp = candle_ts.to_pydatetime()
        open_trade.exit_price = exit_price
        open_trade.exit_reason = reason
        open_trade.pnl_points = round(gross_points, 6)
        open_trade.pnl_rub = round(net_pnl_rub, 2)

        logs.append(
            f"  CLOSE trade {open_trade.trade_id}: "
            f"reason={reason.value}, exit={exit_price:.4f}, pnl={net_pnl_rub:.2f} RUB"
        )
        return open_trade, None, logs  # clear pending signal on exit too

    # ── Case 2: waiting for breakout entry ───────────────────────────────────
    if pending_signal is not None:
        ps = pending_signal
        direction = ps["direction"]
        entry_trigger = ps["entry_trigger"]
        bars_remaining = ps["bars_remaining"] - 1

        if direction == "BUY":
            entry_hit = float(candle["high"]) >= entry_trigger
        else:
            entry_hit = float(candle["low"]) <= entry_trigger

        if entry_hit:
            # Entry confirmed
            if direction == "BUY":
                entry_price = entry_trigger + effective_slippage
            else:
                entry_price = entry_trigger - effective_slippage

            trade_id = build_trade_id(ticker, timeframe, profile, direction, ps["signal_timestamp"])
            new_trade = PaperTrade(
                trade_id=trade_id,
                ticker=ticker,
                class_code=class_code,
                timeframe=timeframe,
                profile=profile,
                direction=direction,
                signal_timestamp=pd.Timestamp(ps["signal_timestamp"]).to_pydatetime(),
                entry_timestamp=candle_ts.to_pydatetime(),
                entry_price=round(entry_price, 6),
                stop_price=ps["stop_price"],
                take_price=ps["take_price"],
                status=PaperTradeStatus.OPEN,
                bars_held=0,
                created_at=_now(),
                updated_at=_now(),
            )
            logs.append(
                f"  ENTRY {direction} {ticker}: entry={entry_price:.4f}, "
                f"stop={ps['stop_price']:.4f}, take={ps['take_price']:.4f}"
            )
            return new_trade, None, logs

        if bars_remaining <= 0:
            logs.append(f"  entry horizon expired for signal at {ps['signal_timestamp']}, cancelling")
            return None, None, logs

        updated_ps = dict(ps)
        updated_ps["bars_remaining"] = bars_remaining
        logs.append(f"  waiting entry: {bars_remaining} bars remaining, trigger={entry_trigger:.4f}")
        return None, updated_ps, logs

    # ── Case 3: idle — check for new signal ──────────────────────────────────
    if is_matching_signal:
        direction = direction_candidate if direction_filter == "all" else direction_filter.upper()
        sig_low = float(candle["low"])
        sig_high = float(candle["high"])

        if direction == "BUY":
            entry_trigger = sig_high
            stop_price = sig_low - stop_buffer_points
            risk = entry_trigger - stop_price
        else:
            entry_trigger = sig_low
            stop_price = sig_high + stop_buffer_points
            risk = stop_price - entry_trigger

        if risk <= 0:
            logs.append(f"  signal at {candle_ts} skipped: invalid risk ({risk})")
            return None, None, logs

        if direction == "BUY":
            take_price = entry_trigger + risk * take_r
        else:
            take_price = entry_trigger - risk * take_r

        if entry_mode == "close":
            # Enter immediately at close
            if direction == "BUY":
                entry_price = float(candle["close"]) + effective_slippage
            else:
                entry_price = float(candle["close"]) - effective_slippage

            trade_id = build_trade_id(ticker, timeframe, profile, direction, candle_ts)
            new_trade = PaperTrade(
                trade_id=trade_id,
                ticker=ticker,
                class_code=class_code,
                timeframe=timeframe,
                profile=profile,
                direction=direction,
                signal_timestamp=candle_ts.to_pydatetime(),
                entry_timestamp=candle_ts.to_pydatetime(),
                entry_price=round(entry_price, 6),
                stop_price=round(stop_price, 6),
                take_price=round(take_price, 6),
                status=PaperTradeStatus.OPEN,
                bars_held=0,
                created_at=_now(),
                updated_at=_now(),
            )
            logs.append(
                f"  SIGNAL+ENTRY (close mode) {direction} {ticker}: "
                f"entry={entry_price:.4f}, stop={stop_price:.4f}, take={take_price:.4f}"
            )
            return new_trade, None, logs

        # Breakout mode: store pending signal
        new_ps = {
            "direction": direction,
            "signal_timestamp": str(candle_ts),
            "entry_trigger": round(entry_trigger, 6),
            "stop_price": round(stop_price, 6),
            "take_price": round(take_price, 6),
            "bars_remaining": entry_horizon_bars,
        }
        logs.append(
            f"  SIGNAL {direction} {ticker} at {candle_ts}: "
            f"trigger={entry_trigger:.4f}, stop={stop_price:.4f}, take={take_price:.4f}"
        )
        return None, new_ps, logs

    return None, pending_signal, logs
