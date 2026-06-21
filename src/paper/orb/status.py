"""Build and write ORB paper trader status JSON."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.paper.orb.models import OrbDailyContext, OrbPaperTrade


def build_orb_status(
    ticker: str,
    experiment_name: str,
    direction: str,
    or_start: str,
    or_end: str,
    take_r: float,
    daily_ctx: OrbDailyContext,
    open_trade: Optional[OrbPaperTrade],
    closed_trades_total: int,
    net_pnl_total: float,
    market_open: bool,
    session: str,
    fetch_status: str,
    last_successful_fetch_at: Optional[str],
    consecutive_api_errors: int,
    total_api_errors: int,
    last_api_error_at: Optional[str],
    last_api_error_message: Optional[str],
    market_open_since: Optional[str],
    pid: int,
) -> dict:
    """Build ORB status dict. Compute liveness using compute_liveness()."""
    from src.paper.liveness import compute_liveness

    now_utc = datetime.now(tz=timezone.utc)
    liveness_status, liveness_reason = compute_liveness(
        is_market_open=market_open,
        consecutive_api_errors=consecutive_api_errors,
        last_successful_fetch_at=last_successful_fetch_at,
        market_open_since=market_open_since,
        now_utc=now_utc,
    )

    open_trade_dict = None
    if open_trade is not None:
        open_trade_dict = {
            "trade_id": open_trade.trade_id,
            "direction": open_trade.direction,
            "entry_price": open_trade.entry_price,
            "stop_price": open_trade.stop_price,
            "take_price": open_trade.take_price,
            "bars_held": open_trade.bars_held,
            "entry_timestamp": (
                open_trade.entry_timestamp.isoformat()
                if open_trade.entry_timestamp
                else None
            ),
        }

    return {
        "service": "hammertrade-paper-orb",
        "mode": "paper",
        "strategy": "ORB",
        "experiment_name": experiment_name,
        "ticker": ticker,
        "direction": direction,
        "opening_range": {
            "start": or_start,
            "end": or_end,
        },
        "take_r": take_r,
        "market_open": market_open,
        "session": session,
        "fetch_status": fetch_status,
        "last_cycle_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_successful_fetch_at": last_successful_fetch_at,
        "consecutive_api_errors": consecutive_api_errors,
        "total_api_errors": total_api_errors,
        "last_api_error_at": last_api_error_at,
        "last_api_error_message": last_api_error_message,
        "market_open_since": market_open_since,
        "trading_liveness_status": liveness_status,
        "trading_liveness_reason": liveness_reason,
        "daily_state": {
            "date_msk": daily_ctx.date_msk,
            "state": daily_ctx.state.value if hasattr(daily_ctx.state, "value") else daily_ctx.state,
            "or_high": daily_ctx.or_high,
            "or_low": daily_ctx.or_low,
            "or_candles_count": daily_ctx.or_candles_count,
            "trade_opened": daily_ctx.trade_opened,
            "trade_closed": daily_ctx.trade_closed,
            "done_for_day": daily_ctx.done_for_day,
            "last_processed_candle_ts": daily_ctx.last_processed_candle_ts,
        },
        "open_trade": open_trade_dict,
        "closed_trades_total": closed_trades_total,
        "net_pnl_total_rub": round(net_pnl_total, 2),
        "pid": pid,
    }


def write_orb_status(status: dict, path: str) -> None:
    """Atomically write status dict to JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)
