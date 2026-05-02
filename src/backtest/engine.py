from dataclasses import asdict
from typing import Optional

import pandas as pd

from src.backtest.models import BacktestTrade


def run_backtest(
    debug_df: pd.DataFrame,
    entry_mode: str = "breakout",
    entry_horizon_bars: int = 3,
    max_hold_bars: int = 30,
    take_r: float = 1.0,
    stop_buffer_points: float = 0.0,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
    allow_overlap: bool = False,
    slippage_points: float = 0.0,
    slippage_ticks: Optional[float] = None,
    tick_size: Optional[float] = None,
    direction_filter: str = "all",
) -> pd.DataFrame:
    if direction_filter not in ("all", "BUY", "SELL"):
        raise ValueError(f"direction_filter must be 'all', 'BUY', or 'SELL', got: '{direction_filter}'")

    if slippage_ticks is not None:
        if slippage_ticks < 0:
            raise ValueError(f"slippage_ticks must be >= 0, got {slippage_ticks}")
        if tick_size is None or tick_size <= 0:
            raise ValueError("slippage_ticks requires tick_size > 0")
        effective_slippage = slippage_ticks * tick_size
    else:
        if slippage_points < 0:
            raise ValueError(f"slippage_points must be >= 0, got {slippage_points}")
        effective_slippage = slippage_points

    df = debug_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    signals_mask = (df["is_signal"].astype(bool)) & (df["fail_reason"].astype(str) == "pass")
    if direction_filter != "all":
        signals_mask = signals_mask & (df["direction_candidate"].str.upper() == direction_filter.upper())
    signal_indices = df.index[signals_mask].tolist()

    trades = []
    commission_rub = commission_per_trade * 2 * contracts
    last_closed_exit_idx = -1
    trade_id = 0

    for sig_idx in signal_indices:
        trade_id += 1
        sig_row = df.iloc[sig_idx]
        direction = sig_row["direction_candidate"]

        # --- Overlap check ---
        if not allow_overlap and sig_idx <= last_closed_exit_idx:
            trades.append(_skipped(trade_id, sig_row, "skipped_overlap"))
            continue

        # --- Stop price ---
        if direction == "BUY":
            stop_price = sig_row["low"] - stop_buffer_points
        else:
            stop_price = sig_row["high"] + stop_buffer_points

        # --- Entry (raw price) ---
        if entry_mode == "close":
            entry_bar_idx = sig_idx
            entry_price_raw = float(sig_row["close"])
            entry_time = sig_row["timestamp"]
        else:  # breakout
            entry_trigger = float(sig_row["high"]) if direction == "BUY" else float(sig_row["low"])
            entry_bar_idx, entry_price_raw, entry_time = _find_breakout_entry(
                df, sig_idx, direction, entry_trigger, entry_horizon_bars
            )
            if entry_bar_idx is None:
                trades.append(_skipped(trade_id, sig_row, "skipped_no_entry"))
                continue

        # --- Apply slippage to entry ---
        if direction == "BUY":
            entry_price = entry_price_raw + effective_slippage
        else:
            entry_price = entry_price_raw - effective_slippage

        # --- Risk / take (based on raw entry — trigger levels unchanged by slippage) ---
        if direction == "BUY":
            risk_points = entry_price_raw - stop_price
        else:
            risk_points = stop_price - entry_price_raw

        if risk_points <= 0:
            trades.append(_skipped(trade_id, sig_row, "skipped_invalid_risk"))
            continue

        if direction == "BUY":
            take_price = entry_price_raw + risk_points * take_r
        else:
            take_price = entry_price_raw - risk_points * take_r

        # --- Exit ---
        exit_bar_idx, exit_price_raw, exit_reason, bars_held = _find_exit(
            df, entry_bar_idx, direction, stop_price, take_price, max_hold_bars
        )

        # --- Apply slippage to exit ---
        if direction == "BUY":
            exit_price = exit_price_raw - effective_slippage
        else:
            exit_price = exit_price_raw + effective_slippage

        # --- PnL (adjusted prices) ---
        if direction == "BUY":
            gross_points = exit_price - entry_price
        else:
            gross_points = entry_price - exit_price

        gross_pnl_rub = gross_points * point_value_rub * contracts
        net_pnl_rub = gross_pnl_rub - commission_rub

        exit_time = df.iloc[exit_bar_idx]["timestamp"] if exit_bar_idx < len(df) else entry_time

        trade = BacktestTrade(
            trade_id=trade_id,
            instrument=str(sig_row.get("instrument", "")),
            timeframe=str(sig_row.get("timeframe", "")),
            direction=direction,
            signal_time=sig_row["timestamp"],
            entry_time=entry_time,
            exit_time=exit_time,
            signal_open=float(sig_row["open"]),
            signal_high=float(sig_row["high"]),
            signal_low=float(sig_row["low"]),
            signal_close=float(sig_row["close"]),
            entry_price=entry_price,
            stop_price=stop_price,
            take_price=take_price,
            exit_price=exit_price,
            status="closed",
            exit_reason=exit_reason,
            risk_points=risk_points,
            gross_points=gross_points,
            gross_pnl_rub=gross_pnl_rub,
            commission_rub=commission_rub,
            net_pnl_rub=net_pnl_rub,
            bars_held=bars_held,
            entry_price_raw=entry_price_raw,
            exit_price_raw=exit_price_raw,
            slippage_points=slippage_points,
            tick_size=tick_size,
            slippage_ticks=slippage_ticks,
            effective_slippage_points=effective_slippage,
        )
        trades.append(trade)
        last_closed_exit_idx = exit_bar_idx

    if not trades:
        return pd.DataFrame(columns=list(BacktestTrade.__dataclass_fields__.keys()))

    return pd.DataFrame([asdict(t) for t in trades])


def _find_breakout_entry(df, sig_idx, direction, entry_trigger, horizon):
    search_end = min(sig_idx + 1 + horizon, len(df))
    for idx in range(sig_idx + 1, search_end):
        row = df.iloc[idx]
        if direction == "BUY" and row["high"] >= entry_trigger:
            return idx, entry_trigger, row["timestamp"]
        if direction == "SELL" and row["low"] <= entry_trigger:
            return idx, entry_trigger, row["timestamp"]
    return None, None, None


def _find_exit(df, entry_bar_idx, direction, stop_price, take_price, max_hold_bars):
    start = entry_bar_idx + 1
    end = min(start + max_hold_bars, len(df))
    last_idx = end - 1

    for idx in range(start, end):
        row = df.iloc[idx]
        if direction == "BUY":
            stop_hit = row["low"] <= stop_price
            take_hit = row["high"] >= take_price
        else:
            stop_hit = row["high"] >= stop_price
            take_hit = row["low"] <= take_price

        if stop_hit and take_hit:
            return idx, stop_price, "stop_same_bar", idx - entry_bar_idx
        if stop_hit:
            return idx, stop_price, "stop", idx - entry_bar_idx
        if take_hit:
            return idx, take_price, "take", idx - entry_bar_idx

    # No stop/take hit
    actual_last = min(last_idx, len(df) - 1)
    exit_price = float(df.iloc[actual_last]["close"])
    reason = "end_of_data" if end > len(df) else "timeout"
    return actual_last, exit_price, reason, actual_last - entry_bar_idx


def _skipped(trade_id, sig_row, status):
    return BacktestTrade(
        trade_id=trade_id,
        instrument=str(sig_row.get("instrument", "")),
        timeframe=str(sig_row.get("timeframe", "")),
        direction=str(sig_row.get("direction_candidate", "")),
        signal_time=sig_row["timestamp"],
        entry_time=None,
        exit_time=None,
        signal_open=float(sig_row["open"]),
        signal_high=float(sig_row["high"]),
        signal_low=float(sig_row["low"]),
        signal_close=float(sig_row["close"]),
        entry_price=None,
        stop_price=None,
        take_price=None,
        exit_price=None,
        status=status,
        exit_reason="none",
        risk_points=None,
        gross_points=None,
        gross_pnl_rub=None,
        commission_rub=None,
        net_pnl_rub=None,
        bars_held=None,
    )
