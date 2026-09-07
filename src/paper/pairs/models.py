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
    #: Exit signalled on a closed bar but not yet filled. A live trader cannot
    #: trade the close that produced its own exit signal, so the position is
    #: still held here and is closed at the NEXT bar's open.
    PENDING_EXIT = "PENDING_EXIT"
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
    # exit market fill = first bar AFTER the exit signal, open price
    pref_exit_market_fill: Optional[float] = None
    ord_exit_market_fill: Optional[float] = None
    # ── The three PnL metrics, weakest to strongest ──────────────────────────
    #: Theoretical: entry AND exit at the signal bar's close. Both ends are
    #: untradeable. Kept only for comparison with historical reports.
    pnl_rub: Optional[float] = None
    #: Entry at the next bar's open, exit STILL at the signal close. Half-fixed,
    #: and the remaining half is one-sided in our favour.
    pnl_rub_market: Optional[float] = None
    #: Entry AND exit at the next bar's open. The only metric a funnel verdict
    #: may use. Measured 2026-09: the difference between this and pnl_rub is
    #: 4.5-22.2 bps/trade — the size of the entire claimed pairs edge — and it
    #: flips three of four tested configurations from positive to negative.
    pnl_rub_realistic: Optional[float] = None
    bars_held: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
