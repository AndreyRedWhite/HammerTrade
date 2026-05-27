"""Atomic status file writer for the paper trading daemon."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class StatusWriter:
    def __init__(self, status_path: str):
        self.path = Path(status_path)

    def write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        content = json.dumps(data, indent=2, default=str)
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(self.path)  # atomic on POSIX


def build_status(
    *,
    ticker: str,
    class_code: str,
    timeframe: str,
    profile: str,
    direction: str,
    env: str,
    market_hours_enabled: bool,
    market_open: bool,
    session: str,
    market_timezone: str,
    last_fetch_status: str,
    last_candle_ts_utc: Optional[str] = None,
    last_candle_ts_msk: Optional[str] = None,
    last_processed_ts_utc: Optional[str] = None,
    open_trades: int = 0,
    pending_signal: bool = False,
    consecutive_empty_fetches: int = 0,
    consecutive_api_errors: int = 0,
    last_error: Optional[str] = None,
    # Empty-response counters (MVP-2.1a)
    empty_response_count: int = 0,
    consecutive_empty_responses: int = 0,
    last_empty_response_at: Optional[str] = None,
    last_empty_response_message: Optional[str] = None,
    last_successful_fetch_at: Optional[str] = None,
    # Liveness fields (MVP-2.3a)
    total_api_errors: int = 0,
    last_api_error_at: Optional[str] = None,
    last_api_error_message: Optional[str] = None,
) -> dict[str, Any]:
    from src.paper.liveness import compute_liveness
    from zoneinfo import ZoneInfo

    now = datetime.now(tz=timezone.utc)
    msk = now.astimezone(ZoneInfo(market_timezone))

    liveness_status, liveness_reason = compute_liveness(
        is_market_open=market_open,
        consecutive_api_errors=consecutive_api_errors,
        consecutive_empty_responses=consecutive_empty_responses,
        last_successful_fetch_at=last_successful_fetch_at,
        now_utc=now,
    )

    minutes_since_fetch: Optional[float] = None
    if last_successful_fetch_at:
        try:
            ts = datetime.fromisoformat(last_successful_fetch_at.replace("Z", "+00:00"))
            minutes_since_fetch = round((now - ts).total_seconds() / 60, 1)
        except (ValueError, TypeError):
            pass

    return {
        "service": "hammertrade-paper",
        "mode": "paper",
        "ticker": ticker,
        "class_code": class_code,
        "timeframe": timeframe,
        "profile": profile,
        "direction": direction,
        "env": env,
        "market_hours_enabled": market_hours_enabled,
        "market_open": market_open,
        "session": session,
        "market_timezone": market_timezone,
        "last_cycle_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_cycle_at_msk": msk.isoformat(),
        "last_fetch_status": last_fetch_status,
        "last_candle_ts_utc": last_candle_ts_utc,
        "last_candle_ts_msk": last_candle_ts_msk,
        "last_processed_ts_utc": last_processed_ts_utc,
        "open_trades": open_trades,
        "pending_signal": pending_signal,
        "consecutive_empty_fetches": consecutive_empty_fetches,
        "consecutive_api_errors": consecutive_api_errors,
        "last_error": last_error,
        "empty_response_count": empty_response_count,
        "consecutive_empty_responses": consecutive_empty_responses,
        "last_empty_response_at": last_empty_response_at,
        "last_empty_response_message": last_empty_response_message,
        "last_successful_fetch_at": last_successful_fetch_at,
        # Liveness fields (MVP-2.3a)
        "trading_liveness_status": liveness_status,
        "trading_liveness_reason": liveness_reason,
        "total_api_errors": total_api_errors,
        "last_api_error_at": last_api_error_at,
        "last_api_error_message": last_api_error_message,
        "minutes_since_last_successful_fetch": minutes_since_fetch,
        "liveness_checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pid": os.getpid(),
    }
