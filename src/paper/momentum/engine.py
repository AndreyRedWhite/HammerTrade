"""Momentum Continuation paper trading state machine engine.

No real orders are placed. This engine processes 1-minute candles and
tracks virtual trades against the Momentum Continuation strategy.

Direction: SHORT only.
Signal: bearish impulse candle — wide range, close near low, high volume.
"""
from datetime import datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from src.paper.momentum.models import (
    MomentumDailyContext,
    MomentumDayState,
    MomentumExitReason,
    MomentumPaperTrade,
    MomentumTradeStatus,
)

MSK = ZoneInfo("Europe/Moscow")
POINT_VALUE_RUB = 10.0
COMMISSION_RUB = 0.05  # per trade round-trip


def _parse_candle_ts(candle: pd.Series) -> datetime:
    """Parse candle timestamp to UTC-aware datetime."""
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


def process_candle_momentum(
    candle: pd.Series,
    recent_candles: pd.DataFrame,
    daily_ctx: MomentumDailyContext,
    open_trade: Optional[MomentumPaperTrade],
    *,
    atr_mult: float,
    vol_mult: float,
    take_r: float,
    atr_window: int,
    vol_window: int,
    time_exit_msk: time,
    ticker: str,
    experiment_name: str,
    max_trades_per_day: int,
    commission_rub: float = 0.05,
    point_value_rub: float = 10.0,
) -> tuple[Optional[MomentumDailyContext], Optional[MomentumPaperTrade], list[str]]:
    """Process one candle through the Momentum Continuation state machine.

    Returns: (updated_daily_ctx, trade_to_upsert, log_messages)
    trade_to_upsert is None if no trade change.
    """
    from src.research.vwap import compute_atr

    logs: list[str] = []

    candle_ts_utc = _parse_candle_ts(candle)
    candle_msk = candle_ts_utc.astimezone(MSK)
    candle_date_msk = candle_msk.date().isoformat()
    candle_time = candle_msk.time()

    # Reset context on date change
    if daily_ctx.date_msk != candle_date_msk:
        logs.append(
            f"NEW_DAY date={candle_date_msk} (prev={daily_ctx.date_msk}) resetting daily context"
        )
        daily_ctx = MomentumDailyContext(date_msk=candle_date_msk)
        open_trade = None  # fresh day, no carry-over trades

    # If done for today, skip everything
    if daily_ctx.done_for_day:
        return daily_ctx, None, logs

    # Update last processed timestamp
    daily_ctx.last_processed_candle_ts = str(candle_ts_utc.isoformat())

    # ── Manage open trade: check exit conditions ───────────────────────────────
    if open_trade is not None and open_trade.status == MomentumTradeStatus.OPEN:
        daily_ctx.state = MomentumDayState.IN_TRADE
        open_trade.bars_held += 1

        # TIME_EXIT: candle starts at or after time_exit_msk
        if candle_time >= time_exit_msk:
            exit_price = float(candle["open"])
            pnl_points = open_trade.entry_price - exit_price  # SHORT
            pnl_rub = pnl_points * point_value_rub - commission_rub
            open_trade.status = MomentumTradeStatus.CLOSED
            open_trade.exit_timestamp = candle_ts_utc
            open_trade.exit_price = exit_price
            open_trade.exit_reason = MomentumExitReason.TIME_EXIT
            open_trade.pnl_points = pnl_points
            open_trade.pnl_rub = pnl_rub
            daily_ctx.done_for_day = True
            daily_ctx.state = MomentumDayState.DONE_FOR_DAY
            logs.append(
                f"TIME_EXIT ticker={ticker} entry={open_trade.entry_price} "
                f"exit={exit_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
            )
            return daily_ctx, open_trade, logs

        # SHORT stop/take checks
        candle_high = float(candle["high"])
        candle_low = float(candle["low"])
        stop_hit = candle_high >= open_trade.stop_price
        take_hit = candle_low <= open_trade.take_price

        if stop_hit:
            # STOP wins even if take also hit
            exit_price = open_trade.stop_price
            pnl_points = open_trade.entry_price - exit_price  # SHORT: negative if stopped
            pnl_rub = pnl_points * point_value_rub - commission_rub
            open_trade.status = MomentumTradeStatus.CLOSED
            open_trade.exit_timestamp = candle_ts_utc
            open_trade.exit_price = exit_price
            open_trade.exit_reason = MomentumExitReason.STOP
            open_trade.pnl_points = pnl_points
            open_trade.pnl_rub = pnl_rub
            daily_ctx.done_for_day = True
            daily_ctx.state = MomentumDayState.DONE_FOR_DAY
            logs.append(
                f"STOP_HIT ticker={ticker} entry={open_trade.entry_price} "
                f"stop={open_trade.stop_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
            )
            return daily_ctx, open_trade, logs

        if take_hit:
            exit_price = open_trade.take_price
            pnl_points = open_trade.entry_price - exit_price  # SHORT: positive if taken
            pnl_rub = pnl_points * point_value_rub - commission_rub
            open_trade.status = MomentumTradeStatus.CLOSED
            open_trade.exit_timestamp = candle_ts_utc
            open_trade.exit_price = exit_price
            open_trade.exit_reason = MomentumExitReason.TAKE
            open_trade.pnl_points = pnl_points
            open_trade.pnl_rub = pnl_rub
            daily_ctx.done_for_day = True
            daily_ctx.state = MomentumDayState.DONE_FOR_DAY
            logs.append(
                f"TAKE_HIT ticker={ticker} entry={open_trade.entry_price} "
                f"take={open_trade.take_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
            )
            return daily_ctx, open_trade, logs

        # Trade still open, no exit this candle
        return daily_ctx, open_trade, logs

    # ── No open trade: look for momentum signal ────────────────────────────────
    if daily_ctx.trades_today < max_trades_per_day:
        daily_ctx.state = MomentumDayState.WAITING_FOR_SIGNAL

        # No new entry at or after time_exit_msk
        if candle_time >= time_exit_msk:
            logs.append(
                f"NO_SIGNAL_AFTER_TIME_EXIT ticker={ticker} candle_time={candle_time} "
                f"time_exit={time_exit_msk} — marking done_for_day"
            )
            daily_ctx.done_for_day = True
            daily_ctx.state = MomentumDayState.DONE_FOR_DAY
            return daily_ctx, None, logs

        # Compute ATR using recent_candles
        if len(recent_candles) < 2:
            return daily_ctx, None, logs

        atr_series = compute_atr(recent_candles, window=atr_window)
        atr_val = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0

        # Compute rolling volume mean
        vol_series = recent_candles["volume"].rolling(window=vol_window, min_periods=1).mean()
        vol_mean_val = float(vol_series.iloc[-1]) if not vol_series.empty else 0.0

        # Guard: ATR and candle range must be valid
        if atr_val <= 0 or vol_mean_val <= 0:
            return daily_ctx, None, logs

        candle_high = float(candle["high"])
        candle_low = float(candle["low"])
        candle_close = float(candle["close"])
        candle_volume = float(candle["volume"])

        candle_range = candle_high - candle_low
        if candle_range <= 0:
            return daily_ctx, None, logs

        close_pos = (candle_close - candle_low) / candle_range

        # Signal conditions (SHORT — bearish impulse)
        range_ok = candle_range >= atr_mult * atr_val
        close_bearish = close_pos <= 0.25
        vol_ok = candle_volume >= vol_mult * vol_mean_val

        if range_ok and close_bearish and vol_ok:
            entry_price = candle_close
            stop_price = candle_high
            risk = stop_price - entry_price
            if risk <= 0:
                return daily_ctx, None, logs

            take_price = entry_price - risk * take_r

            trade_id = f"momentum:{ticker}:{experiment_name}:{candle_ts_utc.isoformat()}"
            new_trade = MomentumPaperTrade(
                trade_id=trade_id,
                strategy_name="momentum_continuation",
                experiment_name=experiment_name,
                ticker=ticker,
                direction="SHORT",
                signal_timestamp=candle_ts_utc,
                entry_timestamp=candle_ts_utc,
                entry_price=entry_price,
                stop_price=stop_price,
                take_price=take_price,
                atr_value=atr_val,
                volume_value=candle_volume,
                volume_avg=vol_mean_val,
                candle_range=candle_range,
                close_position=close_pos,
                status=MomentumTradeStatus.OPEN,
                bars_held=0,
            )
            daily_ctx.trades_today += 1
            daily_ctx.state = MomentumDayState.IN_TRADE
            logs.append(
                f"MOMENTUM_SIGNAL SHORT ticker={ticker} "
                f"entry={entry_price} stop={stop_price} take={take_price} "
                f"atr={atr_val:.2f} range={candle_range:.2f} close_pos={close_pos:.3f} "
                f"vol={candle_volume:.0f} vol_avg={vol_mean_val:.0f}"
            )
            return daily_ctx, new_trade, logs

    return daily_ctx, None, logs
