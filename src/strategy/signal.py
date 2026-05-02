from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SignalRecord:
    timestamp: object
    instrument: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    range: float
    body: float
    upper_shadow: float
    lower_shadow: float
    body_frac: Optional[float]
    upper_frac: Optional[float]
    lower_frac: Optional[float]
    close_pos: Optional[float]
    direction_candidate: str
    is_signal: bool
    fail_reason: str
    fail_reasons: str
    params_profile: str
