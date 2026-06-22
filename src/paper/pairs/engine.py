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
) -> tuple[Optional[PairPaperTrade], list[str]]:
    """Process one closed aligned bar. Returns (trade_to_upsert | None, logs).

    `bar` must carry: timestamp, z, pref_open, pref_close, ord_open, ord_close.
    """
    logs: list[str] = []

    z = bar["z"]
    if pd.isna(z):
        return None, logs

    ts = bar["timestamp"]
    if isinstance(ts, str):
        ts = pd.Timestamp(ts)
    ts = ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts

    pref_open = float(bar["pref_open"])
    pref_close = float(bar["pref_close"])
    ord_open = float(bar["ord_open"])
    ord_close = float(bar["ord_close"])

    # ── No open trade: look for entry ─────────────────────────────────────────
    if open_trade is None or open_trade.status == PairTradeStatus.CLOSED:
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
    exit_reason = None
    if abs_z <= exit_z:
        exit_reason = PairExitReason.EXIT_MEAN
    elif abs_z >= stop_z:
        exit_reason = PairExitReason.STOP_DIVERGE
    elif held >= max_hold_bars:
        exit_reason = PairExitReason.TIME

    if exit_reason is None:
        return open_trade, logs  # still open, persist updated bars_held/market fill

    # Close at signal bar close (theoretical)
    open_trade.status = PairTradeStatus.CLOSED
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
    pair["spread"] = np.log(pair["pref_close"]) - np.log(pair["ord_close"])
    pair["mu"] = pair["spread"].rolling(z_window).mean()
    pair["sd"] = pair["spread"].rolling(z_window).std()
    pair["z"] = (pair["spread"] - pair["mu"]) / pair["sd"]
    return pair.reset_index()
