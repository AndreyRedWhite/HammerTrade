"""Pairs (stat-arb) paper trading data models.

Market-neutral mean-reversion of a pref/ordinary spread = log(pref) - log(ord).
A trade holds TWO legs simultaneously and can persist across days (unlike the
hammer/ORB intraday engines). Entry/exit fire on the signal bar CLOSE
(theoretical); the next bar's OPEN is recorded as the market fill so live
slippage can be measured — the edge has a thin cost margin.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class PairTradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PairExitReason(str, Enum):
    EXIT_MEAN = "EXIT_MEAN"          # |z| reverted to <= exit_z
    STOP_DIVERGE = "STOP_DIVERGE"    # |z| diverged to >= stop_z
    STOP_LOSS = "STOP_LOSS"          # unrealized loss >= stop_loss_bps of leg notional
    TIME = "TIME"                    # held >= max_hold_bars


@dataclass
class PairState:
    """Per-pair processing cursor (one row per pair)."""
    pair_name: str
    last_processed_bar_ts: Optional[str] = None


@dataclass
class PairPaperTrade:
    trade_id: str
    experiment_name: str
    pair_name: str
    pref_ticker: str
    ord_ticker: str
    direction: str                  # LONG_SPREAD (long pref / short ord) or SHORT_SPREAD
    entry_timestamp: datetime       # signal bar ts
    entry_z: float
    # theoretical entry = signal bar close of each leg
    pref_entry_price: float
    ord_entry_price: float
    notional_per_leg: float
    cost_bps_per_leg_side: float
    status: PairTradeStatus
    # market fill = first bar AFTER entry, open price (slippage tracking)
    pref_market_fill: Optional[float] = None
    ord_market_fill: Optional[float] = None
    # exit (theoretical = signal bar close)
    exit_timestamp: Optional[datetime] = None
    exit_z: Optional[float] = None
    pref_exit_price: Optional[float] = None
    ord_exit_price: Optional[float] = None
    exit_reason: Optional[PairExitReason] = None
    pnl_rub: Optional[float] = None             # theoretical, cost-adjusted
    pnl_rub_market: Optional[float] = None      # entry at market fill, cost-adjusted
    bars_held: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
