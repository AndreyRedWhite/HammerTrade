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
) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    from zoneinfo import ZoneInfo
    msk = now.astimezone(ZoneInfo(market_timezone))
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
        "pid": os.getpid(),
    }
