"""Momentum Continuation paper trading data models."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class MomentumDayState(str, Enum):
    WAITING_FOR_SIGNAL = "WAITING_FOR_SIGNAL"
    IN_TRADE = "IN_TRADE"
    DONE_FOR_DAY = "DONE_FOR_DAY"
    MARKET_CLOSED = "MARKET_CLOSED"


class MomentumExitReason(str, Enum):
    STOP = "STOP"
    TAKE = "TAKE"
    TIME_EXIT = "TIME_EXIT"


class MomentumTradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class MomentumDailyContext:
    date_msk: str              # "2026-05-30"
    state: MomentumDayState = MomentumDayState.WAITING_FOR_SIGNAL
    trades_today: int = 0
    done_for_day: bool = False
    last_processed_candle_ts: Optional[str] = None


@dataclass
class MomentumPaperTrade:
    trade_id: str
    strategy_name: str
    experiment_name: str
    ticker: str
    direction: str
    signal_timestamp: datetime
    entry_timestamp: datetime
    entry_price: float
    stop_price: float
    take_price: float
    atr_value: float        # ATR at signal time
    volume_value: float     # volume of signal candle
    volume_avg: float       # rolling avg volume at signal time
    candle_range: float     # high-low of signal candle
    close_position: float   # (close-low)/range
    status: MomentumTradeStatus
    exit_timestamp: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[MomentumExitReason] = None
    pnl_points: Optional[float] = None
    pnl_rub: Optional[float] = None
    bars_held: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
