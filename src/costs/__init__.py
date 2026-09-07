"""Single authority for transaction costs and contract multipliers.

Import cost numbers from here. Never redefine them at a call site, and never
give them a default value in a function signature — see `src/costs/model.py`
for why that rule exists.
"""
from src.costs.model import (  # noqa: F401
    EQUITY_COMMISSION_BPS_PER_SIDE,
    FUTURES_COMMISSION_BPS_PER_SIDE,
    AssetClass,
    CostModel,
    UnknownInstrumentError,
    cost_model_for,
    hurdle_bps,
    point_value_rub,
    required_daily_carry_bps,
    roundtrip_bps,
)
