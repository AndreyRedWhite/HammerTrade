"""ORB (Opening Range Breakout) paper trading state machine engine.

No real orders are placed. This engine processes 1-minute candles and
tracks virtual trades against the ORB strategy.
"""
from datetime import datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from src.paper.orb.models import (
    OrbDailyContext,
    OrbDayState,
    OrbExitReason,
    OrbPaperTrade,
    OrbTradeStatus,
)

MSK = ZoneInfo("Europe/Moscow")
POINT_VALUE_RUB = 10.0
COMMISSION_RUB = 0.05  # per trade round-trip
MIN_OR_CANDLES = 5
MIN_OR_RANGE_POINTS = 10.0


def _parse_candle_ts(candle: pd.Series) -> datetime:
    """Parse candle timestamp to UTC-aware datetime."""
    ts = candle["timestamp"]
    if isinstance(ts, (pd.Timestamp,)):
        dt = ts.to_pydatetime()
    elif isinstance(ts, str):
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    else:
        dt = ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def process_candle_orb(
    candle: pd.Series,
    daily_ctx: OrbDailyContext,
    open_trade: Optional[OrbPaperTrade],
    *,
    direction: str,
    or_start_msk: time,
    or_end_msk: time,
    take_r: float,
    time_exit_msk: time,
    ticker: str,
    experiment_name: str,
    point_value_rub: float = 10.0,
    commission_rub: float = 0.05,
) -> tuple[Optional[OrbDailyContext], Optional[OrbPaperTrade], list[str]]:
    """Process one candle through the ORB state machine.

    Returns: (updated_daily_ctx, trade_to_upsert, log_messages)
    trade_to_upsert is None if no trade change.
    """
    logs: list[str] = []

    candle_ts_utc = _parse_candle_ts(candle)
    candle_msk = candle_ts_utc.astimezone(MSK)
    candle_date_msk = candle_msk.date().isoformat()  # "2026-05-30"
    candle_time = candle_msk.time()

    # Reset context on date change
    if daily_ctx.date_msk != candle_date_msk:
        logs.append(
            f"NEW_DAY date={candle_date_msk} (prev={daily_ctx.date_msk}) resetting daily context"
        )
        daily_ctx = OrbDailyContext(date_msk=candle_date_msk)
        open_trade = None  # fresh day, no carry-over trades

    # ── OR window: before start ────────────────────────────────────────────────
    if candle_time < or_start_msk:
        daily_ctx.state = OrbDayState.WAITING_FOR_OR_START
        return daily_ctx, None, logs

    # ── OR window: inside opening range ───────────────────────────────────────
    if or_start_msk <= candle_time < or_end_msk:
        daily_ctx.state = OrbDayState.BUILDING_OPENING_RANGE
        h = float(candle["high"])
        l = float(candle["low"])
        daily_ctx.or_high = max(daily_ctx.or_high, h) if daily_ctx.or_high is not None else h
        daily_ctx.or_low = min(daily_ctx.or_low, l) if daily_ctx.or_low is not None else l
        daily_ctx.or_candles_count += 1
        daily_ctx.last_processed_candle_ts = str(candle_ts_utc.isoformat())
        return daily_ctx, None, logs

    # ── After OR window ────────────────────────────────────────────────────────

    # If already done for today, skip everything
    if daily_ctx.done_for_day:
        return daily_ctx, None, logs

    # Update last processed timestamp
    daily_ctx.last_processed_candle_ts = str(candle_ts_utc.isoformat())

    # Validate OR was built
    if daily_ctx.or_high is None or daily_ctx.or_candles_count < MIN_OR_CANDLES:
        logs.append(
            f"OR_INVALID date={daily_ctx.date_msk} or_candles={daily_ctx.or_candles_count} "
            f"(min={MIN_OR_CANDLES}) — marking done_for_day"
        )
        daily_ctx.done_for_day = True
        daily_ctx.state = OrbDayState.DONE_FOR_DAY
        return daily_ctx, None, logs

    or_range = (daily_ctx.or_high or 0.0) - (daily_ctx.or_low or 0.0)
    if or_range < MIN_OR_RANGE_POINTS:
        logs.append(
            f"OR_RANGE_TOO_SMALL date={daily_ctx.date_msk} range={or_range:.1f} "
            f"(min={MIN_OR_RANGE_POINTS}) — marking done_for_day"
        )
        daily_ctx.done_for_day = True
        daily_ctx.state = OrbDayState.DONE_FOR_DAY
        return daily_ctx, None, logs

    # ── Manage open trade: check exit conditions ───────────────────────────────
    if open_trade is not None and open_trade.status == OrbTradeStatus.OPEN:
        daily_ctx.state = OrbDayState.IN_TRADE
        open_trade.bars_held += 1

        # TIME_EXIT: candle starts at or after time_exit_msk
        if candle_time >= time_exit_msk:
            exit_price = float(candle["close"])
            if direction.upper() == "SHORT":
                pnl_points = open_trade.entry_price - exit_price
            else:
                pnl_points = exit_price - open_trade.entry_price
            pnl_rub = pnl_points * point_value_rub - commission_rub
            open_trade.status = OrbTradeStatus.CLOSED
            open_trade.exit_timestamp = candle_ts_utc
            open_trade.exit_price = exit_price
            open_trade.exit_reason = OrbExitReason.TIME_EXIT
            open_trade.pnl_points = pnl_points
            open_trade.pnl_rub = pnl_rub
            daily_ctx.trade_closed = True
            daily_ctx.done_for_day = True
            daily_ctx.state = OrbDayState.DONE_FOR_DAY
            logs.append(
                f"TIME_EXIT ticker={ticker} entry={open_trade.entry_price} "
                f"exit={exit_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
            )
            return daily_ctx, open_trade, logs

        # Check stop/take for SHORT
        if direction.upper() == "SHORT":
            candle_high = float(candle["high"])
            candle_low = float(candle["low"])
            stop_hit = candle_high >= open_trade.stop_price
            take_hit = candle_low <= open_trade.take_price

            if stop_hit:
                # STOP wins even if take also hit
                exit_price = open_trade.stop_price
                pnl_points = open_trade.entry_price - exit_price
                pnl_rub = pnl_points * point_value_rub - commission_rub
                open_trade.status = OrbTradeStatus.CLOSED
                open_trade.exit_timestamp = candle_ts_utc
                open_trade.exit_price = exit_price
                open_trade.exit_reason = OrbExitReason.STOP
                open_trade.pnl_points = pnl_points
                open_trade.pnl_rub = pnl_rub
                daily_ctx.trade_closed = True
                daily_ctx.done_for_day = True
                daily_ctx.state = OrbDayState.DONE_FOR_DAY
                logs.append(
                    f"STOP_HIT ticker={ticker} entry={open_trade.entry_price} "
                    f"stop={open_trade.stop_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
                )
                return daily_ctx, open_trade, logs

            if take_hit:
                exit_price = open_trade.take_price
                pnl_points = open_trade.entry_price - exit_price
                pnl_rub = pnl_points * point_value_rub - commission_rub
                open_trade.status = OrbTradeStatus.CLOSED
                open_trade.exit_timestamp = candle_ts_utc
                open_trade.exit_price = exit_price
                open_trade.exit_reason = OrbExitReason.TAKE
                open_trade.pnl_points = pnl_points
                open_trade.pnl_rub = pnl_rub
                daily_ctx.trade_closed = True
                daily_ctx.done_for_day = True
                daily_ctx.state = OrbDayState.DONE_FOR_DAY
                logs.append(
                    f"TAKE_HIT ticker={ticker} entry={open_trade.entry_price} "
                    f"take={open_trade.take_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
                )
                return daily_ctx, open_trade, logs
        elif direction.upper() == "LONG":
            candle_high = float(candle["high"])
            candle_low = float(candle["low"])
            stop_hit = candle_low <= open_trade.stop_price
            take_hit = candle_high >= open_trade.take_price

            if stop_hit:
                exit_price = open_trade.stop_price
                pnl_points = exit_price - open_trade.entry_price
                pnl_rub = pnl_points * point_value_rub - commission_rub
                open_trade.status = OrbTradeStatus.CLOSED
                open_trade.exit_timestamp = candle_ts_utc
                open_trade.exit_price = exit_price
                open_trade.exit_reason = OrbExitReason.STOP
                open_trade.pnl_points = pnl_points
                open_trade.pnl_rub = pnl_rub
                daily_ctx.trade_closed = True
                daily_ctx.done_for_day = True
                daily_ctx.state = OrbDayState.DONE_FOR_DAY
                logs.append(
                    f"STOP_HIT ticker={ticker} entry={open_trade.entry_price} "
                    f"stop={open_trade.stop_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
                )
                return daily_ctx, open_trade, logs

            if take_hit:
                exit_price = open_trade.take_price
                pnl_points = exit_price - open_trade.entry_price
                pnl_rub = pnl_points * point_value_rub - commission_rub
                open_trade.status = OrbTradeStatus.CLOSED
                open_trade.exit_timestamp = candle_ts_utc
                open_trade.exit_price = exit_price
                open_trade.exit_reason = OrbExitReason.TAKE
                open_trade.pnl_points = pnl_points
                open_trade.pnl_rub = pnl_rub
                daily_ctx.trade_closed = True
                daily_ctx.done_for_day = True
                daily_ctx.state = OrbDayState.DONE_FOR_DAY
                logs.append(
                    f"TAKE_HIT ticker={ticker} entry={open_trade.entry_price} "
                    f"take={open_trade.take_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
                )
                return daily_ctx, open_trade, logs

        # Trade still open, no exit this candle
        return daily_ctx, open_trade, logs

    # ── No open trade: look for breakout ──────────────────────────────────────
    if not daily_ctx.trade_opened:
        daily_ctx.state = OrbDayState.WAITING_FOR_BREAKOUT

        # No more signals after time_exit_msk
        if candle_time >= time_exit_msk:
            logs.append(
                f"NO_SIGNAL_AFTER_TIME_EXIT ticker={ticker} candle_time={candle_time} "
                f"time_exit={time_exit_msk} — marking done_for_day"
            )
            daily_ctx.done_for_day = True
            daily_ctx.state = OrbDayState.DONE_FOR_DAY
            return daily_ctx, None, logs

        or_high = daily_ctx.or_high
        or_low = daily_ctx.or_low
        risk_points = or_high - or_low

        if direction.upper() == "SHORT":
            # Breakout: candle low breaks below OR low
            if float(candle["low"]) < or_low:
                entry_price = or_low
                stop_price = or_high
                take_price = entry_price - take_r * risk_points
                trade_id = f"orb:{ticker}:{experiment_name}:{candle_ts_utc.isoformat()}"
                new_trade = OrbPaperTrade(
                    trade_id=trade_id,
                    strategy_name="ORB",
                    experiment_name=experiment_name,
                    ticker=ticker,
                    direction=direction.upper(),
                    entry_timestamp=candle_ts_utc,
                    entry_price=entry_price,
                    or_high=or_high,
                    or_low=or_low,
                    stop_price=stop_price,
                    take_price=take_price,
                    status=OrbTradeStatus.OPEN,
                    bars_held=0,
                )
                daily_ctx.trade_opened = True
                daily_ctx.state = OrbDayState.IN_TRADE
                logs.append(
                    f"BREAKOUT SHORT ticker={ticker} entry={entry_price} "
                    f"stop={stop_price} take={take_price} "
                    f"risk={risk_points:.1f} take_r={take_r}"
                )
                return daily_ctx, new_trade, logs

        elif direction.upper() == "LONG":
            # Breakout: candle high breaks above OR high
            if float(candle["high"]) > or_high:
                entry_price = or_high
                stop_price = or_low
                take_price = entry_price + take_r * risk_points
                trade_id = f"orb:{ticker}:{experiment_name}:{candle_ts_utc.isoformat()}"
                new_trade = OrbPaperTrade(
                    trade_id=trade_id,
                    strategy_name="ORB",
                    experiment_name=experiment_name,
                    ticker=ticker,
                    direction=direction.upper(),
                    entry_timestamp=candle_ts_utc,
                    entry_price=entry_price,
                    or_high=or_high,
                    or_low=or_low,
                    stop_price=stop_price,
                    take_price=take_price,
                    status=OrbTradeStatus.OPEN,
                    bars_held=0,
                )
                daily_ctx.trade_opened = True
                daily_ctx.state = OrbDayState.IN_TRADE
                logs.append(
                    f"BREAKOUT LONG ticker={ticker} entry={entry_price} "
                    f"stop={stop_price} take={take_price} "
                    f"risk={risk_points:.1f} take_r={take_r}"
                )
                return daily_ctx, new_trade, logs

    return daily_ctx, None, logs
