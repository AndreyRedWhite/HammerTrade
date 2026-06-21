"""VWAP Reversion paper trading state machine engine.

No real orders are placed.

Signal (SHORT): close > VWAP_session + distance_mult × ATR(14)
Entry: signal candle close (theoretical). Also records next-candle open as market_fill_price.
Stop: entry + stop_mult × ATR
Take: entry - risk × take_r  (one_r mode)
Time exit: 18:40 MSK
Max trades per day: configurable (default 3)
"""
from datetime import datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from src.paper.vwap_reversion.models import (
    VwapDailyContext,
    VwapDayState,
    VwapExitReason,
    VwapPaperTrade,
    VwapTradeStatus,
)

MSK = ZoneInfo("Europe/Moscow")


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


def process_candle_vwap(
    candle: pd.Series,
    recent_candles: pd.DataFrame,
    daily_ctx: VwapDailyContext,
    open_trade: Optional[VwapPaperTrade],
    *,
    distance_mult: float,
    stop_mult: float,
    take_r: float,
    atr_window: int,
    time_exit_msk: time,
    ticker: str,
    experiment_name: str,
    max_trades_per_day: int,
    point_value_rub: float = 10.0,
    commission_rub: float = 0.05,
    min_bars_after_session_start: int = 14,
) -> tuple[Optional[VwapDailyContext], Optional[VwapPaperTrade], list[str]]:
    """Process one candle through the VWAP Reversion state machine.

    Returns: (updated_daily_ctx, trade_to_upsert, log_messages)
    trade_to_upsert is None if no trade change.
    """
    from src.research.vwap import compute_session_vwap, compute_atr

    logs: list[str] = []

    candle_ts_utc = _parse_candle_ts(candle)
    candle_msk = candle_ts_utc.astimezone(MSK)
    candle_date_msk = candle_msk.date().isoformat()
    candle_time = candle_msk.time()

    if daily_ctx.date_msk != candle_date_msk:
        logs.append(
            f"NEW_DAY date={candle_date_msk} (prev={daily_ctx.date_msk}) resetting daily context"
        )
        daily_ctx = VwapDailyContext(date_msk=candle_date_msk)
        open_trade = None

    if daily_ctx.done_for_day:
        return daily_ctx, None, logs

    daily_ctx.last_processed_candle_ts = str(candle_ts_utc.isoformat())

    # ── Manage open trade ──────────────────────────────────────────────────────
    if open_trade is not None and open_trade.status == VwapTradeStatus.OPEN:
        daily_ctx.state = VwapDayState.IN_TRADE

        # Fill market_fill_price on the first bar after entry (next candle's open)
        if open_trade.market_fill_price is None:
            open_trade.market_fill_price = float(candle["open"])
            # Return immediately so this candle is the "fill" candle, not exit candle
            return daily_ctx, open_trade, logs

        open_trade.bars_held += 1
        candle_high = float(candle["high"])
        candle_low = float(candle["low"])

        if candle_time >= time_exit_msk:
            exit_price = float(candle["open"])
            pnl_points = open_trade.entry_price - exit_price
            pnl_rub = pnl_points * point_value_rub - commission_rub
            open_trade.status = VwapTradeStatus.CLOSED
            open_trade.exit_timestamp = candle_ts_utc
            open_trade.exit_price = exit_price
            open_trade.exit_reason = VwapExitReason.TIME_EXIT
            open_trade.pnl_points = pnl_points
            open_trade.pnl_rub = pnl_rub
            daily_ctx.done_for_day = True
            daily_ctx.state = VwapDayState.DONE_FOR_DAY
            logs.append(
                f"TIME_EXIT ticker={ticker} entry={open_trade.entry_price} "
                f"exit={exit_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f} "
                f"market_fill={open_trade.market_fill_price}"
            )
            return daily_ctx, open_trade, logs

        # Stop hits before take for SHORT
        if candle_high >= open_trade.stop_price:
            exit_price = open_trade.stop_price
            pnl_points = open_trade.entry_price - exit_price
            pnl_rub = pnl_points * point_value_rub - commission_rub
            open_trade.status = VwapTradeStatus.CLOSED
            open_trade.exit_timestamp = candle_ts_utc
            open_trade.exit_price = exit_price
            open_trade.exit_reason = VwapExitReason.STOP
            open_trade.pnl_points = pnl_points
            open_trade.pnl_rub = pnl_rub
            daily_ctx.done_for_day = True
            daily_ctx.state = VwapDayState.DONE_FOR_DAY
            logs.append(
                f"STOP_HIT ticker={ticker} entry={open_trade.entry_price} "
                f"stop={open_trade.stop_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
            )
            return daily_ctx, open_trade, logs

        if candle_low <= open_trade.take_price:
            exit_price = open_trade.take_price
            pnl_points = open_trade.entry_price - exit_price
            pnl_rub = pnl_points * point_value_rub - commission_rub
            open_trade.status = VwapTradeStatus.CLOSED
            open_trade.exit_timestamp = candle_ts_utc
            open_trade.exit_price = exit_price
            open_trade.exit_reason = VwapExitReason.TAKE
            open_trade.pnl_points = pnl_points
            open_trade.pnl_rub = pnl_rub
            daily_ctx.done_for_day = True
            daily_ctx.state = VwapDayState.DONE_FOR_DAY
            logs.append(
                f"TAKE_HIT ticker={ticker} entry={open_trade.entry_price} "
                f"take={open_trade.take_price} pnl_points={pnl_points:.1f} pnl_rub={pnl_rub:.2f}"
            )
            return daily_ctx, open_trade, logs

        return daily_ctx, open_trade, logs

    # ── No open trade: look for VWAP reversion signal ─────────────────────────
    if daily_ctx.trades_today >= max_trades_per_day:
        return daily_ctx, None, logs

    daily_ctx.state = VwapDayState.WAITING_FOR_SIGNAL

    if candle_time >= time_exit_msk:
        daily_ctx.done_for_day = True
        daily_ctx.state = VwapDayState.DONE_FOR_DAY
        return daily_ctx, None, logs

    if len(recent_candles) < atr_window + 1:
        return daily_ctx, None, logs

    # Compute session VWAP and ATR from full recent history
    vwap_series = compute_session_vwap(recent_candles)
    atr_series = compute_atr(recent_candles, window=atr_window)

    if vwap_series.empty or atr_series.empty:
        return daily_ctx, None, logs

    vwap_val = float(vwap_series.iloc[-1])
    atr_val = float(atr_series.iloc[-1])

    if pd.isna(vwap_val) or pd.isna(atr_val) or vwap_val <= 0 or atr_val <= 0:
        return daily_ctx, None, logs

    # Require minimum bars since session start for ATR to stabilize
    today_candles = recent_candles[
        recent_candles["timestamp"].apply(
            lambda t: (
                t.astimezone(MSK).date() if hasattr(t, "astimezone")
                else pd.Timestamp(t).tz_convert(MSK).date()
            ) == candle_msk.date()
        )
    ]
    if len(today_candles) < min_bars_after_session_start:
        return daily_ctx, None, logs

    close_val = float(candle["close"])
    threshold = vwap_val + distance_mult * atr_val

    # SHORT signal: price significantly above VWAP (mean-reversion SHORT)
    if close_val <= threshold:
        return daily_ctx, None, logs

    entry_price = close_val
    stop_price = entry_price + stop_mult * atr_val
    risk = stop_price - entry_price
    if risk <= 0:
        return daily_ctx, None, logs

    take_price = entry_price - risk * take_r

    trade_id = f"vwap:{ticker}:{experiment_name}:{candle_ts_utc.isoformat()}"
    new_trade = VwapPaperTrade(
        trade_id=trade_id,
        experiment_name=experiment_name,
        ticker=ticker,
        direction="SHORT",
        entry_timestamp=candle_ts_utc,
        entry_price=entry_price,
        market_fill_price=None,    # filled on the next candle's open
        stop_price=stop_price,
        take_price=take_price,
        atr_value=atr_val,
        vwap_at_signal=vwap_val,
        status=VwapTradeStatus.OPEN,
        bars_held=0,
    )
    daily_ctx.trades_today += 1
    daily_ctx.state = VwapDayState.IN_TRADE
    logs.append(
        f"VWAP_SIGNAL SHORT ticker={ticker} entry={entry_price} "
        f"stop={stop_price:.2f} take={take_price:.2f} "
        f"vwap={vwap_val:.2f} atr={atr_val:.2f} threshold={threshold:.2f}"
    )
    return daily_ctx, new_trade, logs
