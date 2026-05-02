from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class BacktestTrade:
    trade_id: int
    instrument: str
    timeframe: str
    direction: str
    signal_time: datetime
    entry_time: Optional[datetime]
    exit_time: Optional[datetime]
    signal_open: float
    signal_high: float
    signal_low: float
    signal_close: float
    entry_price: Optional[float]
    stop_price: Optional[float]
    take_price: Optional[float]
    exit_price: Optional[float]
    status: str
    exit_reason: Optional[str]
    risk_points: Optional[float]
    gross_points: Optional[float]
    gross_pnl_rub: Optional[float]
    commission_rub: Optional[float]
    net_pnl_rub: Optional[float]
    bars_held: Optional[int]
    entry_price_raw: Optional[float] = None
    exit_price_raw: Optional[float] = None
    slippage_points: float = 0.0
    tick_size: Optional[float] = None
    slippage_ticks: Optional[float] = None
    effective_slippage_points: float = 0.0


VALID_STATUSES = {"closed", "skipped_no_entry", "skipped_invalid_risk", "skipped_overlap"}
VALID_EXIT_REASONS = {"take", "stop", "stop_same_bar", "timeout", "end_of_data", "none"}
