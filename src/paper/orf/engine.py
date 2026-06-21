"""ORB Fade (ORF) paper trading state machine engine.

No real orders are placed.

Strategy (SHORT — fade false breakouts above OR high):
1. Build Opening Range (10:00-11:00 MSK)
2. After OR: if candle.high > OR_high → breakout detected
3. Within n_return_bars after breakout: if candle.close < OR_high → return inside OR
4. Enter SHORT at return candle close
5. Stop = breakout_high + stop_buffer
6. Take = OR midpoint
7. Time exit: 18:40 MSK, max 1 trade/day
"""
from datetime import datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from src.paper.orf.models import (
    OrfDailyContext,
    OrfDayState,
    OrfExitReason,
    OrfPaperTrade,
    OrfTradeStatus,
)

MSK = ZoneInfo("Europe/Moscow")
MIN_OR_CANDLES = 5


def _parse_candle_ts(candle: pd.Series) -> datetime:
    ts = candle["timestamp"]
    if isinstance(ts, pd.Timestamp):
        dt = ts.to_pydatetime()
    elif isinstance(ts, str):
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    else:
        dt = ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def process_candle_orf(
    candle: pd.Series,
    daily_ctx: OrfDailyContext,
    open_trade: Optional[OrfPaperTrade],
    *,
    or_start_msk: time,
    or_end_msk: time,
    time_exit_msk: time,
    n_return_bars: int,
    take_mode: str,
    stop_buffer: float,
    ticker: str,
    experiment_name: str,
    point_value_rub: float = 10.0,
    commission_rub: float = 0.05,
) -> tuple[Optional[OrfDailyContext], Optional[OrfPaperTrade], list[str]]:
    """Process one candle through the ORF state machine.

    Returns: (updated_daily_ctx, trade_to_upsert, log_messages)
    trade_to_upsert is None if no trade change.
    """
    logs: list[str] = []

    candle_ts_utc = _parse_candle_ts(candle)
    candle_msk = candle_ts_utc.astimezone(MSK)
    candle_date_msk = candle_msk.date().isoformat()
    candle_time = candle_msk.time()

    if daily_ctx.date_msk != candle_date_msk:
        logs.append(
            f"NEW_DAY date={candle_date_msk} (prev={daily_ctx.date_msk}) resetting daily context"
        )
        daily_ctx = OrfDailyContext(date_msk=candle_date_msk)
        open_trade = None

    if daily_ctx.done_for_day:
        return daily_ctx, None, logs

    daily_ctx.last_processed_candle_ts = str(candle_ts_utc.isoformat())

    # ── OR window: before start ────────────────────────────────────────────────
    if candle_time < or_start_msk:
        daily_ctx.state = OrfDayState.WAITING_FOR_OR_START
        return daily_ctx, None, logs

    # ── OR window: building ────────────────────────────────────────────────────
    if or_start_msk <= candle_time < or_end_msk:
        daily_ctx.state = OrfDayState.BUILDING_OPENING_RANGE
        h = float(candle["high"])
        lo = float(candle["low"])
        daily_ctx.or_high = max(daily_ctx.or_high, h) if daily_ctx.or_high is not None else h
        daily_ctx.or_low = min(daily_ctx.or_low, lo) if daily_ctx.or_low is not None else lo
        daily_ctx.or_candles_count += 1
        return daily_ctx, None, logs

    # ── After OR window ────────────────────────────────────────────────────────

    if daily_ctx.or_high is None or daily_ctx.or_candles_count < MIN_OR_CANDLES:
        logs.append(
            f"SKIP_INVALID_OR ticker={ticker} or_candles={daily_ctx.or_candles_count}"
        )
        daily_ctx.done_for_day = True
        daily_ctx.state = OrfDayState.DONE_FOR_DAY
        return daily_ctx, None, logs

    or_high = daily_ctx.or_high
    or_low = daily_ctx.or_low
    or_mid = (or_high + or_low) / 2.0

    # ── Manage open trade ──────────────────────────────────────────────────────
    if open_trade is not None and open_trade.status == OrfTradeStatus.OPEN:
        daily_ctx.state = OrfDayState.IN_TRADE
        open_trade.bars_held += 1
        candle_high = float(candle["high"])
        candle_low = float(candle["low"])

        if candle_time >= time_exit_msk:
            exit_price = float(candle["open"])
            pnl_points = open_trade.entry_price - exit_price
            pnl_rub = pnl_points * point_value_rub - commission_rub
            open_trade.status = OrfTradeStatus.CLOSED
            open_trade.exit_timestamp = candle_ts_utc
            open_trade.exit_price = exit_price
            open_trade.exit_reason = OrfExitReason.TIME_EXIT
            open_trade.pnl_points = pnl_points
            open_trade.pnl_rub = pnl_rub
            daily_ctx.done_for_day = True
            daily_ctx.state = OrfDayState.DONE_FOR_DAY
            logs.append(
                f"TIME_EXIT ticker={ticker} entry={open_trade.entry_price} "
                f"exit={exit_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
            )
            return daily_ctx, open_trade, logs

        if candle_high >= open_trade.stop_price:
            exit_price = open_trade.stop_price
            pnl_points = open_trade.entry_price - exit_price
            pnl_rub = pnl_points * point_value_rub - commission_rub
            open_trade.status = OrfTradeStatus.CLOSED
            open_trade.exit_timestamp = candle_ts_utc
            open_trade.exit_price = exit_price
            open_trade.exit_reason = OrfExitReason.STOP
            open_trade.pnl_points = pnl_points
            open_trade.pnl_rub = pnl_rub
            daily_ctx.done_for_day = True
            daily_ctx.state = OrfDayState.DONE_FOR_DAY
            logs.append(
                f"STOP_HIT ticker={ticker} entry={open_trade.entry_price} "
                f"stop={open_trade.stop_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
            )
            return daily_ctx, open_trade, logs

        if candle_low <= open_trade.take_price:
            exit_price = open_trade.take_price
            pnl_points = open_trade.entry_price - exit_price
            pnl_rub = pnl_points * point_value_rub - commission_rub
            open_trade.status = OrfTradeStatus.CLOSED
            open_trade.exit_timestamp = candle_ts_utc
            open_trade.exit_price = exit_price
            open_trade.exit_reason = OrfExitReason.TAKE
            open_trade.pnl_points = pnl_points
            open_trade.pnl_rub = pnl_rub
            daily_ctx.done_for_day = True
            daily_ctx.state = OrfDayState.DONE_FOR_DAY
            logs.append(
                f"TAKE_HIT ticker={ticker} entry={open_trade.entry_price} "
                f"take={open_trade.take_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
            )
            return daily_ctx, open_trade, logs

        return daily_ctx, open_trade, logs

    # ── No open trade: look for fade signal ───────────────────────────────────
    if daily_ctx.trade_opened:
        # Already had a trade today (max 1/day)
        daily_ctx.done_for_day = True
        daily_ctx.state = OrfDayState.DONE_FOR_DAY
        return daily_ctx, None, logs

    if candle_time >= time_exit_msk:
        daily_ctx.done_for_day = True
        daily_ctx.state = OrfDayState.DONE_FOR_DAY
        return daily_ctx, None, logs

    candle_high = float(candle["high"])
    candle_close = float(candle["close"])

    # Check breakout: candle high exceeded OR_high
    if not daily_ctx.in_breakout:
        if candle_high > or_high:
            daily_ctx.in_breakout = True
            daily_ctx.breakout_high = candle_high
            daily_ctx.breakout_bars_count = 1
            daily_ctx.state = OrfDayState.IN_BREAKOUT_WINDOW
            logs.append(
                f"BREAKOUT_DETECTED ticker={ticker} or_high={or_high} "
                f"candle_high={candle_high}"
            )
        else:
            daily_ctx.state = OrfDayState.WATCHING_FOR_BREAKOUT
        return daily_ctx, None, logs

    # Already in breakout window — update breakout high and bars count
    daily_ctx.breakout_high = max(daily_ctx.breakout_high or 0, candle_high)
    daily_ctx.breakout_bars_count += 1
    daily_ctx.state = OrfDayState.IN_BREAKOUT_WINDOW

    # Check if return window expired (too many bars without returning inside OR)
    if daily_ctx.breakout_bars_count > n_return_bars:
        # False breakout never confirmed — reset and wait for next opportunity
        daily_ctx.in_breakout = False
        daily_ctx.breakout_high = None
        daily_ctx.breakout_bars_count = 0
        daily_ctx.state = OrfDayState.WATCHING_FOR_BREAKOUT
        logs.append(
            f"BREAKOUT_EXPIRED ticker={ticker} n_return_bars={n_return_bars} — resetting"
        )
        return daily_ctx, None, logs

    # Check for return inside OR: close < OR_high
    if candle_close < or_high:
        # Return confirmed → entry signal
        entry_price = candle_close
        stop_price = daily_ctx.breakout_high + stop_buffer
        risk = stop_price - entry_price
        if risk <= 0:
            daily_ctx.in_breakout = False
            daily_ctx.breakout_high = None
            daily_ctx.breakout_bars_count = 0
            daily_ctx.state = OrfDayState.WATCHING_FOR_BREAKOUT
            return daily_ctx, None, logs

        if take_mode == "midpoint":
            take_price = or_mid
        else:  # one_r
            take_price = entry_price - risk

        if take_price >= entry_price:
            take_price = entry_price - risk

        trade_id = f"orf:{ticker}:{experiment_name}:{candle_ts_utc.isoformat()}"
        new_trade = OrfPaperTrade(
            trade_id=trade_id,
            experiment_name=experiment_name,
            ticker=ticker,
            direction="SHORT",
            entry_timestamp=candle_ts_utc,
            entry_price=entry_price,
            stop_price=stop_price,
            take_price=take_price,
            or_high=or_high,
            or_low=or_low,
            breakout_high=daily_ctx.breakout_high,
            status=OrfTradeStatus.OPEN,
            bars_held=0,
        )
        daily_ctx.trade_opened = True
        daily_ctx.in_breakout = False
        daily_ctx.state = OrfDayState.IN_TRADE
        logs.append(
            f"ORF_SIGNAL SHORT ticker={ticker} entry={entry_price} "
            f"stop={stop_price:.2f} take={take_price:.2f} "
            f"or_high={or_high} or_low={or_low} or_mid={or_mid:.2f} "
            f"breakout_high={daily_ctx.breakout_high}"
        )
        return daily_ctx, new_trade, logs

    return daily_ctx, None, logs
