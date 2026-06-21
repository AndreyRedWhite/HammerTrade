"""ORB (Opening Range Breakout) paper trading data models."""
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional


class OrbDayState(str, Enum):
    WAITING_FOR_OR_START = "WAITING_FOR_OR_START"
    BUILDING_OPENING_RANGE = "BUILDING_OPENING_RANGE"
    WAITING_FOR_BREAKOUT = "WAITING_FOR_BREAKOUT"
    IN_TRADE = "IN_TRADE"
    DONE_FOR_DAY = "DONE_FOR_DAY"
    MARKET_CLOSED = "MARKET_CLOSED"


class OrbExitReason(str, Enum):
    STOP = "STOP"
    TAKE = "TAKE"
    TIME_EXIT = "TIME_EXIT"


class OrbTradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class OrbDailyContext:
    date_msk: str              # "2026-05-30"
    state: OrbDayState = OrbDayState.WAITING_FOR_OR_START
    or_high: Optional[float] = None
    or_low: Optional[float] = None
    or_candles_count: int = 0
    trade_opened: bool = False
    trade_closed: bool = False
    done_for_day: bool = False
    last_processed_candle_ts: Optional[str] = None


@dataclass
class OrbPaperTrade:
    trade_id: str
    strategy_name: str
    experiment_name: str
    ticker: str
    direction: str
    entry_timestamp: datetime
    entry_price: float
    or_high: float
    or_low: float
    stop_price: float
    take_price: float
    status: OrbTradeStatus
    exit_timestamp: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[OrbExitReason] = None
    pnl_points: Optional[float] = None
    pnl_rub: Optional[float] = None
    bars_held: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
