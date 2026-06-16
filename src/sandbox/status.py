"""Build and write the sandbox status JSON for hammer-maxhold5 (MVP-L1a).

Never include token values in the status dict — only *_present booleans.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def build_sandbox_status(
    *,
    strategy: str,
    ticker: str,
    direction: str,
    max_hold_bars: int,
    orders_enabled: bool,
    real_orders_enabled: bool,
    paper_control_service: str,
    trading_state: str,
    kill_switch_active: bool,
    sandbox_account_id_present: bool,
    token_present: bool,
    open_positions_expected: int,
    open_positions_actual: int,
    open_orders: int,
    daily_pnl_rub: float,
    total_pnl_rub: float,
    daily_loss_limit_rub: float,
    total_loss_limit_rub: float,
    trades_today: int,
    max_trades_per_day: int,
    reconciliation_status: str,
    market_open: bool,
    consecutive_api_errors: int,
    last_successful_fetch_at: Optional[str] = None,
    market_open_since: Optional[str] = None,
    last_successful_reconciliation_at: Optional[str] = None,
    last_order_event_at: Optional[str] = None,
    last_error_at: Optional[str] = None,
    last_error_message: Optional[str] = None,
    pid: Optional[int] = None,
) -> dict:
    """Build the sandbox status dict. Liveness is computed via compute_liveness()."""
    from src.paper.liveness import compute_liveness

    now_utc = datetime.now(tz=timezone.utc)
    liveness_status, liveness_reason = compute_liveness(
        is_market_open=market_open,
        consecutive_api_errors=consecutive_api_errors,
        last_successful_fetch_at=last_successful_fetch_at,
        market_open_since=market_open_since,
        now_utc=now_utc,
    )

    return {
        "service": "hammertrade-sandbox-maxhold5",
        "mode": "sandbox",
        "strategy": strategy,
        "ticker": ticker,
        "direction": direction,
        "max_hold_bars": max_hold_bars,
        "orders_enabled": orders_enabled,
        "real_orders_enabled": real_orders_enabled,
        "paper_control_service": paper_control_service,
        "last_cycle_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "liveness": liveness_status,
        "liveness_reason": liveness_reason,
        "trading_state": trading_state,
        "kill_switch_active": kill_switch_active,
        "sandbox_account_id_present": sandbox_account_id_present,
        "token_present": token_present,
        "reconciliation_status": reconciliation_status,
        "open_positions_expected": open_positions_expected,
        "open_positions_actual": open_positions_actual,
        "open_orders": open_orders,
        "daily_pnl_rub": round(daily_pnl_rub, 2),
        "total_pnl_rub": round(total_pnl_rub, 2),
        "daily_loss_limit_rub": daily_loss_limit_rub,
        "total_loss_limit_rub": total_loss_limit_rub,
        "trades_today": trades_today,
        "max_trades_per_day": max_trades_per_day,
        "market_open": market_open,
        "market_open_since": market_open_since,
        "last_successful_fetch_at": last_successful_fetch_at,
        "last_successful_reconciliation_at": last_successful_reconciliation_at,
        "last_order_event_at": last_order_event_at,
        "last_error_at": last_error_at,
        "last_error_message": last_error_message,
        "pid": pid,
    }


def write_sandbox_status(status: dict, path: str) -> None:
    """Atomically write status dict to JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)
