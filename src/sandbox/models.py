"""Data models for the sandbox execution layer (MVP-L1a)."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class SandboxOrderStatus(str, Enum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class SandboxOrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SandboxOrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class SandboxTradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SandboxExitReason(str, Enum):
    STOP = "STOP"
    TAKE = "TAKE"
    MAX_HOLD_EXIT = "MAX_HOLD_EXIT"
    RISK_EXIT = "RISK_EXIT"
    MANUAL_CLOSE = "MANUAL_CLOSE"  # operator-forced flatten, not a strategy exit


class ReconciliationStatus(str, Enum):
    OK = "OK"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"


@dataclass
class SandboxOrder:
    order_id: str
    signal_id: str
    strategy: str
    ticker: str
    figi: Optional[str]
    instrument_uid: Optional[str]
    direction: str  # SandboxTradeStatus direction context (BUY/SELL of underlying trade)
    order_side: str  # SandboxOrderSide — actual side of this order (BUY/SELL)
    order_type: str  # SandboxOrderType
    requested_qty: int
    requested_price: Optional[float]
    submitted_at: datetime
    status: SandboxOrderStatus
    filled_qty: int = 0
    avg_fill_price: Optional[float] = None
    commission_rub: Optional[float] = None
    slippage_points: Optional[float] = None
    slippage_rub: Optional[float] = None
    raw_response_json: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class SandboxFill:
    fill_id: str
    order_id: str
    ticker: str
    direction: str  # SandboxOrderSide
    qty: int
    price: float
    commission_rub: float
    fill_time: datetime
    raw_response_json: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass
class SandboxPosition:
    ticker: str
    figi: Optional[str]
    instrument_uid: Optional[str]
    direction: str  # "FLAT" | "LONG" | "SHORT"
    qty: int
    avg_price: Optional[float]
    updated_at: Optional[datetime] = None


@dataclass
class SandboxTrade:
    trade_id: str
    signal_id: str
    entry_order_id: Optional[str]
    exit_order_id: Optional[str]
    ticker: str
    direction: str  # BUY/SELL of the strategy trade
    qty: int
    entry_time: datetime
    entry_price: float
    stop_price: float
    take_price: float
    status: SandboxTradeStatus
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[SandboxExitReason] = None
    gross_pnl_rub: Optional[float] = None
    commission_rub: Optional[float] = None
    net_pnl_rub: Optional[float] = None
    bars_held: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class SandboxEvent:
    event_id: str
    timestamp: datetime
    ticker: str
    event_type: str
    message: str
    payload_json: Optional[str] = None


@dataclass
class SandboxDailyRisk:
    date_msk: str
    trades_today: int = 0
    realized_pnl_rub: float = 0.0
    consecutive_losses: int = 0
    daily_loss_breached: bool = False


@dataclass
class SandboxRiskState:
    """Persisted cumulative risk state, survives daemon restarts."""
    total_pnl_rub: float = 0.0
    consecutive_errors: int = 0
    consecutive_losses: int = 0
    exit_error_count: int = 0
    trading_paused: bool = False
    trading_paused_reason: Optional[str] = None
    reconciliation_status: str = ReconciliationStatus.OK.value
    last_reconciliation_at: Optional[str] = None


@dataclass
class RiskCheckResult:
    allowed: bool
    reason: Optional[str] = None
