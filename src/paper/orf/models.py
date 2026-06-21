"""ORB Fade (ORF) paper trading data models."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class OrfDayState(str, Enum):
    WAITING_FOR_OR_START = "WAITING_FOR_OR_START"
    BUILDING_OPENING_RANGE = "BUILDING_OPENING_RANGE"
    WATCHING_FOR_BREAKOUT = "WATCHING_FOR_BREAKOUT"
    IN_BREAKOUT_WINDOW = "IN_BREAKOUT_WINDOW"   # breakout detected, watching for return
    IN_TRADE = "IN_TRADE"
    DONE_FOR_DAY = "DONE_FOR_DAY"


class OrfExitReason(str, Enum):
    STOP = "STOP"
    TAKE = "TAKE"
    TIME_EXIT = "TIME_EXIT"


class OrfTradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class OrfDailyContext:
    date_msk: str
    state: OrfDayState = OrfDayState.WAITING_FOR_OR_START
    or_high: Optional[float] = None
    or_low: Optional[float] = None
    or_candles_count: int = 0
    # Breakout tracking
    in_breakout: bool = False
    breakout_high: Optional[float] = None
    breakout_bars_count: int = 0    # bars since breakout started
    # Trade tracking
    trade_opened: bool = False
    done_for_day: bool = False
    last_processed_candle_ts: Optional[str] = None


@dataclass
class OrfPaperTrade:
    trade_id: str
    experiment_name: str
    ticker: str
    direction: str
    entry_timestamp: datetime
    entry_price: float
    stop_price: float
    take_price: float
    or_high: float
    or_low: float
    breakout_high: float
    status: OrfTradeStatus
    exit_timestamp: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[OrfExitReason] = None
    pnl_points: Optional[float] = None
    pnl_rub: Optional[float] = None
    bars_held: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
