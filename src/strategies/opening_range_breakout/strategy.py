"""Opening Range Breakout (ORB) strategy for MOEX Si futures, 1m timeframe.

Moscow Exchange session: main trading 10:00–18:45 MSK.
Opening range: configurable window at session start (e.g. 10:00–10:15).
Breakout: first candle after OR that breaks OR high/low.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Optional
import pandas as pd
import pytz

from src.strategies.base import Strategy, StrategySignal
from src.strategies.registry import register

MSK = pytz.timezone("Europe/Moscow")

# NOTE: module-level cost constants deliberately removed.
#
# This file used to define COMMISSION_RUB = 0.05 and POINT_VALUE_RUB = 10.0 and
# use them inside simulate_trade(). Two things were wrong with that:
#   * 0.05 RUB is a ~900x understatement of a real round trip (~45 RUB on a
#     90 000 RUB position), and 10.0 is a 10x overstatement of Si's real point
#     value of 1.0 (see data/instruments/futures_specs.csv);
#   * because they were module constants, the walk-forward config that DID
#     specify the correct values (rub_per_trade: 38.0, point_value_rub: 1.0) was
#     read into local variables in backtest.py and then silently ignored.
# Together those inflated every ORB PnL: a +5-point trade was reported as
# +49.95 RUB when the truth is 5x1 - 38 = -33 RUB. The sign flips.
#
# simulate_trade() now takes both as REQUIRED keyword arguments. See src/costs.


def _to_msk(ts: pd.Timestamp) -> pd.Timestamp:
    """Convert a UTC or tz-aware timestamp to MSK."""
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(MSK)


def compute_opening_range(day_candles: pd.DataFrame, or_start: time, or_end: time) -> Optional[dict]:
    """Compute the opening range (high/low) for a day's candle data.

    Args:
        day_candles: 1m candles for a single trading day (UTC timestamps).
        or_start: Opening range start time in MSK (e.g. time(10, 0)).
        or_end: Opening range end time in MSK (e.g. time(10, 15)).

    Returns:
        dict with keys: or_high, or_low, or_range, candle_count, or_end_idx
        or None if insufficient candles.
    """
    msk_times = day_candles["timestamp"].apply(_to_msk)
    or_mask = msk_times.apply(
        lambda t: or_start <= t.time() < or_end
    )
    or_candles = day_candles[or_mask]

    if len(or_candles) < 5:
        return None

    or_high = float(or_candles["high"].max())
    or_low = float(or_candles["low"].min())
    or_range = or_high - or_low

    return {
        "or_high": or_high,
        "or_low": or_low,
        "or_range": or_range,
        "candle_count": len(or_candles),
        "or_end_idx": or_candles.index[-1],
    }


def simulate_trade(
    signal: StrategySignal,
    post_or_candles: pd.DataFrame,
    time_exit_msk: time,
    *,
    point_value_rub: float,
    commission_rub: float,
) -> dict:
    """Simulate a trade from entry signal to exit.

    Args:
        signal: StrategySignal with entry_price, stop_price, take_price, direction.
        post_or_candles: Candles from entry bar onwards (UTC timestamps).
        time_exit_msk: Force-close time in MSK (e.g. time(18, 40)).
        point_value_rub: RUB per point per contract. REQUIRED — resolve it from
            instrument specs via src.costs.point_value_rub(), never assume.
        commission_rub: Full round-trip commission in RUB for the position.
            REQUIRED, and it is the ROUND TRIP, not one side.

    GAP HANDLING: a stop or take is only fillable at its exact level if price
    trades through it. When a bar OPENS beyond the level, the fill happens at
    the open. Booking such an exit at the stop price credits a price that was
    never available, and it does so precisely on the worst trades — the tail
    that determines profit factor. Exits that gapped are reported with
    ``_GAP``-suffixed reasons so the frequency stays visible.

    Returns:
        Trade outcome dict with: entry_price, stop_price, take_price, exit_price,
        exit_reason, pnl_points, pnl_rub, bars_held, entry_msk, exit_msk.
    """
    if point_value_rub is None or point_value_rub <= 0:
        raise ValueError(
            f"point_value_rub must be > 0, got {point_value_rub!r}. "
            f"Resolve it from instrument specs (src.costs.point_value_rub)."
        )
    if commission_rub is None or commission_rub < 0:
        raise ValueError(f"commission_rub must be >= 0, got {commission_rub!r}")
    entry_price = signal.entry_price
    stop_price = signal.stop_price
    take_price = signal.take_price
    direction = signal.direction  # "LONG" or "SHORT"

    exit_price = None
    exit_reason = None
    bars_held = 0
    entry_ts = signal.timestamp

    for _, candle in post_or_candles.iterrows():
        bars_held += 1
        c_msk = _to_msk(candle["timestamp"])

        # Check time exit first (at or after time_exit)
        if c_msk.time() >= time_exit_msk:
            exit_price = float(candle["open"])
            exit_reason = "TIME_EXIT"
            break

        c_open = float(candle["open"])

        if direction == "LONG":
            # Stop first: a bar that gaps below the stop fills at the open, not
            # at the stop — the stop level was never offered.
            if c_open <= stop_price:
                exit_price = c_open
                exit_reason = "STOP_GAP"
                break
            if float(candle["low"]) <= stop_price:
                exit_price = stop_price
                exit_reason = "STOP"
                break
            if take_price is not None:
                if c_open >= take_price:
                    exit_price = c_open
                    exit_reason = "TAKE_GAP"
                    break
                if float(candle["high"]) >= take_price:
                    exit_price = take_price
                    exit_reason = "TAKE"
                    break
        else:  # SHORT
            if c_open >= stop_price:
                exit_price = c_open
                exit_reason = "STOP_GAP"
                break
            if float(candle["high"]) >= stop_price:
                exit_price = stop_price
                exit_reason = "STOP"
                break
            if take_price is not None:
                if c_open <= take_price:
                    exit_price = c_open
                    exit_reason = "TAKE_GAP"
                    break
                if float(candle["low"]) <= take_price:
                    exit_price = take_price
                    exit_reason = "TAKE"
                    break

    if exit_price is None:
        # End of data — close at last candle close
        if len(post_or_candles) > 0:
            last = post_or_candles.iloc[-1]
            exit_price = float(last["close"])
            exit_reason = "TIME_EXIT"
            bars_held = len(post_or_candles)
        else:
            exit_price = entry_price
            exit_reason = "TIME_EXIT"
            bars_held = 0

    # PnL calculation
    if direction == "LONG":
        pnl_points = exit_price - entry_price
    else:
        pnl_points = entry_price - exit_price

    pnl_rub = pnl_points * point_value_rub - commission_rub

    # Find actual exit timestamp
    exit_ts_msk = None
    if bars_held > 0 and len(post_or_candles) >= bars_held:
        exit_candle = post_or_candles.iloc[bars_held - 1]
        exit_ts_msk = _to_msk(exit_candle["timestamp"])

    entry_ts_msk = _to_msk(pd.Timestamp(entry_ts) if not isinstance(entry_ts, pd.Timestamp) else entry_ts)

    return {
        "entry_price": entry_price,
        "stop_price": stop_price,
        "take_price": take_price,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pnl_points": pnl_points,
        "pnl_rub": pnl_rub,
        "bars_held": bars_held,
        "entry_msk": entry_ts_msk,
        "exit_msk": exit_ts_msk,
    }


@register
class OpeningRangeBreakoutStrategy(Strategy):
    """Opening Range Breakout strategy for MOEX Si futures (1m bars, MSK timezone).

    Logic:
    1. Each trading day: compute OR high/low in the OR window.
    2. Skip if OR has <5 candles or OR range < min_range_points.
    3. After OR ends, first breakout candle triggers entry.
    4. Skip first `false_breakout_bars` candles after OR ends.
    5. Max 1 trade per day (first valid breakout).
    6. Force close at time_exit_msk if trade still open.
    7. No new entry after no_entry_after_msk.
    """

    name = "opening_range_breakout"

    def __init__(self, config: dict):
        """
        config keys:
          or_start_msk: str "HH:MM"
          or_end_msk: str "HH:MM"
          direction: "long" | "short" | "both"
          take_r: float
          min_range_points: float (default 10.0)
          false_breakout_bars: int (default 2)
          time_exit_msk: str "HH:MM" (default "18:40")
          no_entry_after_msk: str "HH:MM" (default "18:30")
        """
        self.config = config
        self.or_start = _parse_time(config.get("or_start_msk", "10:00"))
        self.or_end = _parse_time(config.get("or_end_msk", "10:15"))
        self.direction = config.get("direction", "both")
        self.take_r = float(config.get("take_r", 1.5))
        self.min_range_points = float(config.get("min_range_points", 10.0))
        self.false_breakout_bars = int(config.get("false_breakout_bars", 2))
        self.time_exit_msk = _parse_time(config.get("time_exit_msk", "18:40"))
        self.no_entry_after_msk = _parse_time(config.get("no_entry_after_msk", "18:30"))

    def required_columns(self) -> list[str]:
        return ["timestamp", "open", "high", "low", "close", "volume"]

    def generate_signals(self, candles: pd.DataFrame, context: dict) -> list[StrategySignal]:
        """Generate one StrategySignal per trading day (max 1 per day).

        Signals are generated for the first valid breakout after the OR window.
        The signal is an intent — simulate_trade() must be called separately to
        get trade outcome.
        """
        if candles.empty:
            return []

        # Ensure timestamp column is parsed
        if not pd.api.types.is_datetime64_any_dtype(candles["timestamp"]):
            candles = candles.copy()
            candles["timestamp"] = pd.to_datetime(candles["timestamp"], utc=True)
        elif candles["timestamp"].dt.tz is None:
            candles = candles.copy()
            candles["timestamp"] = candles["timestamp"].dt.tz_localize("UTC")

        # Group by trading day (MSK date)
        candles = candles.copy()
        candles["msk_dt"] = candles["timestamp"].apply(_to_msk)
        candles["msk_date"] = candles["msk_dt"].dt.date

        signals = []

        for date, day_df in candles.groupby("msk_date"):
            day_df = day_df.sort_values("timestamp").reset_index(drop=True)

            # Compute OR
            or_info = compute_opening_range(day_df, self.or_start, self.or_end)
            if or_info is None:
                continue

            or_high = or_info["or_high"]
            or_low = or_info["or_low"]
            or_range = or_info["or_range"]

            # Skip degenerate ranges
            if or_range < self.min_range_points:
                continue

            # Find candles after OR ends
            post_or_mask = day_df["msk_dt"].apply(lambda t: t.time() >= self.or_end)
            post_or = day_df[post_or_mask].reset_index(drop=True)

            if post_or.empty:
                continue

            # Scan for breakout (skip first false_breakout_bars after OR)
            for i, row in post_or.iterrows():
                msk_t = row["msk_dt"].time()

                # No entry after cutoff
                if msk_t >= self.no_entry_after_msk:
                    break

                # Skip false breakout filter candles
                if i < self.false_breakout_bars:
                    continue

                # Check for breakout
                direction_chosen = None
                entry_price = None
                stop_price = None

                if self.direction in ("long", "both"):
                    if float(row["high"]) > or_high:
                        direction_chosen = "LONG"
                        entry_price = or_high
                        stop_price = or_low

                if direction_chosen is None and self.direction in ("short", "both"):
                    if float(row["low"]) < or_low:
                        direction_chosen = "SHORT"
                        entry_price = or_low
                        stop_price = or_high

                if direction_chosen is None:
                    continue

                # Compute take price
                risk = or_range  # entry_price - stop_price (always positive)
                if direction_chosen == "LONG":
                    take_price = entry_price + risk * self.take_r
                else:
                    take_price = entry_price - risk * self.take_r

                signal = StrategySignal(
                    strategy_name=self.name,
                    ticker=context.get("ticker", "SiM6"),
                    direction=direction_chosen,
                    timestamp=row["timestamp"],
                    entry_price=entry_price,
                    stop_price=stop_price,
                    take_price=take_price,
                    reason=f"ORB_{direction_chosen} breakout at {msk_t}",
                    metadata={
                        "date": str(date),
                        "or_high": or_high,
                        "or_low": or_low,
                        "or_range": or_range,
                        "or_candles": or_info["candle_count"],
                        "breakout_bar_idx": i,
                        "msk_time": str(msk_t),
                    },
                )
                signals.append(signal)
                break  # max 1 trade per day

        return signals


def _parse_time(s: str) -> time:
    """Parse 'HH:MM' string to datetime.time."""
    h, m = s.split(":")
    return time(int(h), int(m))
