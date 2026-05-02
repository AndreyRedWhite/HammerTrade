from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class PaperTradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PaperExitReason(str, Enum):
    STOP = "STOP"
    TAKE = "TAKE"
    TIMEOUT = "TIMEOUT"
    MANUAL = "MANUAL"
    END_OF_DATA = "END_OF_DATA"


@dataclass
class PaperTrade:
    trade_id: str
    ticker: str
    class_code: str
    timeframe: str
    profile: str
    direction: str
    signal_timestamp: datetime
    entry_timestamp: datetime
    entry_price: float
    stop_price: float
    take_price: float
    status: PaperTradeStatus
    exit_timestamp: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[PaperExitReason] = None
    pnl_points: Optional[float] = None
    pnl_rub: Optional[float] = None
    bars_held: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
