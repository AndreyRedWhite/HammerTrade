"""VWAP Reversion paper trading data models."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class VwapDayState(str, Enum):
    WAITING_FOR_SIGNAL = "WAITING_FOR_SIGNAL"
    IN_TRADE = "IN_TRADE"
    DONE_FOR_DAY = "DONE_FOR_DAY"


class VwapExitReason(str, Enum):
    STOP = "STOP"
    TAKE = "TAKE"
    TIME_EXIT = "TIME_EXIT"


class VwapTradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class VwapDailyContext:
    date_msk: str
    state: VwapDayState = VwapDayState.WAITING_FOR_SIGNAL
    trades_today: int = 0
    done_for_day: bool = False
    last_processed_candle_ts: Optional[str] = None


@dataclass
class VwapPaperTrade:
    trade_id: str
    experiment_name: str
    ticker: str
    direction: str
    entry_timestamp: datetime
    entry_price: float          # theoretical: signal candle close
    stop_price: float
    take_price: float
    atr_value: float
    vwap_at_signal: float
    status: VwapTradeStatus
    market_fill_price: Optional[float] = None   # next candle open — slippage tracking
    exit_timestamp: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[VwapExitReason] = None
    pnl_points: Optional[float] = None
    pnl_rub: Optional[float] = None
    bars_held: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
