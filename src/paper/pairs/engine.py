"""Pairs stat-arb paper trading engine. No real orders.

Processes one CLOSED aligned bar at a time for a single pair. The caller
(runner) builds the aligned, resampled spread/z-score history for both legs
and feeds each new closed bar in order.

Strategy (validated config: 60m bars, z_window=50, entry_z=2.0, exit_z=0.5,
stop_z=4.0, partial-reversion exit — see research_pairs_basket.py):
  spread = log(pref_close) - log(ord_close)
  z = (spread - rolling_mean) / rolling_std
  z >=  entry_z  -> spread too high -> SHORT_SPREAD (short pref, long ord)
  z <= -entry_z  -> spread too low  -> LONG_SPREAD  (long pref, short ord)
  exit when |z| <= exit_z (mean revert) | |z| >= stop_z (diverge) | held>=max_hold

Dollar-neutral: equal RUB notional per leg. Entry/exit at signal bar CLOSE
(theoretical); market fill (next bar open) recorded for slippage tracking.
"""
from datetime import datetime
from typing import Optional

import pandas as pd

from src.paper.pairs.models import (
    PairExitReason,
    PairPaperTrade,
    PairTradeStatus,
)


def _bar_pnl(direction: str, pref_entry: float, ord_entry: float,
             pref_exit: float, ord_exit: float, notional_per_leg: float,
             cost_bps_per_leg_side: float) -> float:
    """Dollar-neutral 2-leg PnL in RUB, cost-adjusted (4 sides: 2 legs × in+out)."""
    sign = 1.0 if direction == "LONG_SPREAD" else -1.0   # long pref if LONG_SPREAD
    y_ret = (pref_exit / pref_entry - 1.0) * sign
    x_ret = (ord_exit / ord_entry - 1.0) * (-sign)
    gross = (y_ret + x_ret) * notional_per_leg
    cost = 4.0 * (cost_bps_per_leg_side / 1e4) * notional_per_leg
    return gross - cost


def _fill_pending_exit(
    open_trade: PairPaperTrade,
    pref_open: float,
    ord_open: float,
    pair_name: str,
    notional_per_leg: float,
    cost_bps_per_leg_side: float,
    logs: list[str],
) -> tuple[PairPaperTrade, list[str]]:
    """Fill an exit that was signalled on the previous bar's close.

    Both ends of ``pnl_rub_realistic`` are prices a live trader could actually
    get: entry at the open after the entry signal, exit at the open after the
    exit signal.
    """
    open_trade.pref_exit_market_fill = pref_open
    open_trade.ord_exit_market_fill = ord_open
    open_trade.status = PairTradeStatus.CLOSED
    open_trade.pnl_rub_realistic = _bar_pnl(
        open_trade.direction,
        open_trade.pref_market_fill or open_trade.pref_entry_price,
        open_trade.ord_market_fill or open_trade.ord_entry_price,
        pref_open, ord_open, notional_per_leg, cost_bps_per_leg_side,
    )
    theoretical = open_trade.pnl_rub if open_trade.pnl_rub is not None else float("nan")
    logs.append(
        f"PAIR_EXIT_FILLED pair={pair_name} "
        f"reason={open_trade.exit_reason.value if open_trade.exit_reason else '?'} "
        f"pnl_rub_realistic={open_trade.pnl_rub_realistic:.1f} "
        f"(theoretical was {theoretical:.1f})"
    )
    return open_trade, logs


def process_pair_bar(
    bar: pd.Series,
    open_trade: Optional[PairPaperTrade],
    *,
    pair_name: str,
    pref_ticker: str,
    ord_ticker: str,
    entry_z: float,
    exit_z: float,
    stop_z: float,
    max_hold_bars: int,
    notional_per_leg: float,
    cost_bps_per_leg_side: float,
    experiment_name: str,
    stop_loss_bps: Optional[float] = None,
) -> tuple[Optional[PairPaperTrade], list[str]]:
    """Process one closed aligned bar. Returns (trade_to_upsert | None, logs).

    `bar` must carry: timestamp, z, pref_open, pref_close, ord_open, ord_close.

    `stop_z` alone cannot bound the loss: z is measured against a ROLLING mean, so a
    spread that trends away drags the mean after it and z decays back toward 0 while
    the position bleeds. (Observed 2026-07-17 on SNGS: spread widened 0.875 -> 0.970
    while z fell 3.12 -> 1.70, so |z| >= stop_z never fired and the trade lost ~9k of
    a 100k leg before max_hold_bars timed it out.) `stop_loss_bps` bounds the loss in
    the space it actually lives in — PnL — and is the only exit that does.
    """
    logs: list[str] = []

    z = bar["z"]

    ts = bar["timestamp"]
    if isinstance(ts, str):
        ts = pd.Timestamp(ts)
    ts = ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts

    pref_open = float(bar["pref_open"])
    pref_close = float(bar["pref_close"])
    ord_open = float(bar["ord_open"])
    ord_close = float(bar["ord_close"])

    # A pending exit fills on price alone and must NOT wait for a usable z — the
    # position is already out of the market by intent, and leaving it in
    # PENDING_EXIT because the z-window happens to be short would strand it.
    if open_trade is not None and open_trade.status == PairTradeStatus.PENDING_EXIT:
        return _fill_pending_exit(
            open_trade, pref_open, ord_open,
            pair_name, notional_per_leg, cost_bps_per_leg_side, logs,
        )

    if pd.isna(z):
        return None, logs

    # ── No open trade: look for entry ─────────────────────────────────────────
    if open_trade is None or open_trade.status == PairTradeStatus.CLOSED:
        if "entry_allowed" in bar and not bool(bar["entry_allowed"]):
            logs.append(f"PAIR_ENTRY_BLOCKED pair={pair_name} unstable_relationship")
            return None, logs
        direction = None
        if z >= entry_z:
            direction = "SHORT_SPREAD"
        elif z <= -entry_z:
            direction = "LONG_SPREAD"
        if direction is None:
            return None, logs

        trade_id = f"pairs:{pair_name}:{experiment_name}:{ts.isoformat()}"
        new_trade = PairPaperTrade(
            trade_id=trade_id,
            experiment_name=experiment_name,
            pair_name=pair_name,
            pref_ticker=pref_ticker,
            ord_ticker=ord_ticker,
            direction=direction,
            entry_timestamp=ts,
            entry_z=float(z),
            pref_entry_price=pref_close,
            ord_entry_price=ord_close,
            notional_per_leg=notional_per_leg,
            cost_bps_per_leg_side=cost_bps_per_leg_side,
            status=PairTradeStatus.OPEN,
            bars_held=0,
        )
        logs.append(
            f"PAIR_ENTRY {direction} pair={pair_name} z={z:.2f} "
            f"pref({pref_ticker})={pref_close} ord({ord_ticker})={ord_close}"
        )
        return new_trade, logs

    # ── Open trade ────────────────────────────────────────────────────────────
    open_trade.bars_held += 1

    # First bar after entry → record market fill (next-bar open) for slippage
    if open_trade.pref_market_fill is None:
        open_trade.pref_market_fill = pref_open
        open_trade.ord_market_fill = ord_open

    held = open_trade.bars_held
    abs_z = abs(z)

    # Mark the real position (market fill once known), not the theoretical entry.
    unrealized = _bar_pnl(
        open_trade.direction,
        open_trade.pref_market_fill or open_trade.pref_entry_price,
        open_trade.ord_market_fill or open_trade.ord_entry_price,
        pref_close, ord_close, notional_per_leg, cost_bps_per_leg_side,
    )
    stop_loss_rub = (
        abs(stop_loss_bps) / 1e4 * notional_per_leg if stop_loss_bps is not None else None
    )

    exit_reason = None
    # Checked before EXIT_MEAN so a trade that bled past the stop is labelled honestly
    # even if z happens to revert on the same bar.
    if stop_loss_rub is not None and unrealized <= -stop_loss_rub:
        exit_reason = PairExitReason.STOP_LOSS
    elif abs_z <= exit_z:
        exit_reason = PairExitReason.EXIT_MEAN
    elif abs_z >= stop_z:
        exit_reason = PairExitReason.STOP_DIVERGE
    elif held >= max_hold_bars:
        exit_reason = PairExitReason.TIME

    if exit_reason is None:
        return open_trade, logs  # still open, persist updated bars_held/market fill

    # The exit SIGNAL fires here, on this bar's close. The FILL cannot: a live
    # trader learns the close only once the bar is over. So the trade goes to
    # PENDING_EXIT and is filled at the next bar's open, which is where
    # pnl_rub_realistic comes from. pnl_rub / pnl_rub_market are still recorded
    # at the signal close so old reports remain comparable — but they book a
    # price that was never available and must not drive a funnel verdict.
    open_trade.status = PairTradeStatus.PENDING_EXIT
    open_trade.exit_timestamp = ts
    open_trade.exit_z = float(z)
    open_trade.pref_exit_price = pref_close
    open_trade.ord_exit_price = ord_close
    open_trade.exit_reason = exit_reason
    open_trade.pnl_rub = _bar_pnl(
        open_trade.direction, open_trade.pref_entry_price, open_trade.ord_entry_price,
        pref_close, ord_close, notional_per_leg, cost_bps_per_leg_side,
    )
    if open_trade.pref_market_fill is not None:
        open_trade.pnl_rub_market = _bar_pnl(
            open_trade.direction, open_trade.pref_market_fill, open_trade.ord_market_fill,
            pref_close, ord_close, notional_per_leg, cost_bps_per_leg_side,
        )
    logs.append(
        f"PAIR_EXIT {open_trade.direction} pair={pair_name} reason={exit_reason.value} "
        f"z={z:.2f} held={held} pnl_rub={open_trade.pnl_rub:.1f} "
        f"pnl_rub_market={open_trade.pnl_rub_market}"
    )
    return open_trade, logs


def compute_spread_z(
    pref_df: pd.DataFrame,
    ord_df: pd.DataFrame,
    *,
    timeframe: str,
    z_window: int,
    hedge_window: Optional[int] = None,
    min_correlation: Optional[float] = None,
    max_beta_change: Optional[float] = None,
) -> pd.DataFrame:
    """Align two legs, resample, compute log-spread and rolling z-score.

    Returns a DataFrame indexed by timestamp with columns:
      timestamp, pref_open, pref_close, ord_open, ord_close, spread, z
    Only fully-closed bars are included (caller fetches closed candles).
    """
    def _prep(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
        d = df.copy()
        d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
        d = d.sort_values("timestamp").set_index("timestamp")
        if timeframe != "1min":
            d = d.resample(timeframe).agg(
                {"open": "first", "high": "max", "low": "min",
                 "close": "last", "volume": "sum"}
            ).dropna(subset=["close"])
        return d[["open", "close"]].rename(
            columns={"open": f"{prefix}_open", "close": f"{prefix}_close"})

    y = _prep(pref_df, "pref")
    x = _prep(ord_df, "ord")
    pair = y.join(x, how="inner").dropna()
    if pair.empty:
        return pair.reset_index()

    import numpy as np
    log_pref = np.log(pair["pref_close"])
    log_ord = np.log(pair["ord_close"])
    stability_window = hedge_window or z_window
    pair["corr"] = log_pref.rolling(stability_window).corr(log_ord)
    if hedge_window:
        variance = log_ord.rolling(hedge_window).var().replace(0, np.nan)
        pair["beta"] = log_pref.rolling(hedge_window).cov(log_ord) / variance
        pair["spread"] = log_pref - pair["beta"] * log_ord
        compare_lag = max(1, hedge_window // 4)
        pair["beta_change"] = (pair["beta"] / pair["beta"].shift(compare_lag) - 1).abs()
    else:
        pair["beta"] = 1.0
        pair["beta_change"] = 0.0
        pair["spread"] = log_pref - log_ord
    pair["mu"] = pair["spread"].rolling(z_window).mean()
    pair["sd"] = pair["spread"].rolling(z_window).std()
    pair["z"] = (pair["spread"] - pair["mu"]) / pair["sd"]
    pair["entry_allowed"] = True
    if min_correlation is not None:
        pair["entry_allowed"] &= pair["corr"].abs() >= min_correlation
    if max_beta_change is not None:
        pair["entry_allowed"] &= pair["beta_change"] <= max_beta_change
    pair["entry_allowed"] = pair["entry_allowed"].fillna(False)
    return pair.reset_index()
