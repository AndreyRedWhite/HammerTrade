"""SQLite repository for ORB paper trading state and trades."""
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.paper.orb.models import (
    OrbDailyContext,
    OrbDayState,
    OrbExitReason,
    OrbPaperTrade,
    OrbTradeStatus,
)

_DAILY_STATE_DDL = """
CREATE TABLE IF NOT EXISTS orb_daily_state (
    date_msk TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    or_high REAL,
    or_low REAL,
    or_candles_count INTEGER NOT NULL DEFAULT 0,
    trade_opened INTEGER NOT NULL DEFAULT 0,
    trade_closed INTEGER NOT NULL DEFAULT 0,
    done_for_day INTEGER NOT NULL DEFAULT 0,
    last_processed_candle_ts TEXT,
    created_at TEXT,
    updated_at TEXT
)
"""

_TRADES_DDL = """
CREATE TABLE IF NOT EXISTS orb_paper_trades (
    trade_id TEXT PRIMARY KEY,
    strategy_name TEXT,
    experiment_name TEXT,
    ticker TEXT,
    direction TEXT,
    entry_timestamp TEXT,
    entry_price REAL,
    or_high REAL,
    or_low REAL,
    stop_price REAL,
    take_price REAL,
    status TEXT,
    exit_timestamp TEXT,
    exit_price REAL,
    exit_reason TEXT,
    pnl_points REAL,
    pnl_rub REAL,
    bars_held INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
)
"""


def _now_utc_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class OrbRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_DAILY_STATE_DDL)
            conn.execute(_TRADES_DDL)
            conn.commit()

    def save_daily_state(self, ctx: OrbDailyContext) -> None:
        now = _now_utc_str()
        with self._connect() as conn:
            # Check if exists to preserve created_at
            row = conn.execute(
                "SELECT created_at FROM orb_daily_state WHERE date_msk = ?",
                (ctx.date_msk,)
            ).fetchone()
            created_at = row["created_at"] if row else now
            conn.execute(
                """INSERT OR REPLACE INTO orb_daily_state
                   (date_msk, state, or_high, or_low, or_candles_count,
                    trade_opened, trade_closed, done_for_day,
                    last_processed_candle_ts, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ctx.date_msk,
                    ctx.state.value if hasattr(ctx.state, "value") else ctx.state,
                    ctx.or_high,
                    ctx.or_low,
                    ctx.or_candles_count,
                    int(ctx.trade_opened),
                    int(ctx.trade_closed),
                    int(ctx.done_for_day),
                    ctx.last_processed_candle_ts,
                    created_at,
                    now,
                ),
            )
            conn.commit()

    def load_daily_state(self, date_msk: str) -> Optional[OrbDailyContext]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM orb_daily_state WHERE date_msk = ?", (date_msk,)
            ).fetchone()
        if row is None:
            return None
        return OrbDailyContext(
            date_msk=row["date_msk"],
            state=OrbDayState(row["state"]),
            or_high=row["or_high"],
            or_low=row["or_low"],
            or_candles_count=row["or_candles_count"] or 0,
            trade_opened=bool(row["trade_opened"]),
            trade_closed=bool(row["trade_closed"]),
            done_for_day=bool(row["done_for_day"]),
            last_processed_candle_ts=row["last_processed_candle_ts"],
        )

    def get_open_trade(self, ticker: str) -> Optional[OrbPaperTrade]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM orb_paper_trades WHERE ticker = ? AND status = ? LIMIT 1",
                (ticker, OrbTradeStatus.OPEN.value),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_trade(row)

    def insert_trade(self, trade: OrbPaperTrade) -> None:
        now = _now_utc_str()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO orb_paper_trades
                   (trade_id, strategy_name, experiment_name, ticker, direction,
                    entry_timestamp, entry_price, or_high, or_low, stop_price, take_price,
                    status, exit_timestamp, exit_price, exit_reason, pnl_points, pnl_rub,
                    bars_held, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade.trade_id,
                    trade.strategy_name,
                    trade.experiment_name,
                    trade.ticker,
                    trade.direction,
                    _dt_to_str(trade.entry_timestamp),
                    trade.entry_price,
                    trade.or_high,
                    trade.or_low,
                    trade.stop_price,
                    trade.take_price,
                    trade.status.value if hasattr(trade.status, "value") else trade.status,
                    _dt_to_str(trade.exit_timestamp),
                    trade.exit_price,
                    trade.exit_reason.value if trade.exit_reason and hasattr(trade.exit_reason, "value") else trade.exit_reason,
                    trade.pnl_points,
                    trade.pnl_rub,
                    trade.bars_held,
                    now,
                    now,
                ),
            )
            conn.commit()

    def update_trade(self, trade: OrbPaperTrade) -> None:
        now = _now_utc_str()
        with self._connect() as conn:
            conn.execute(
                """UPDATE orb_paper_trades SET
                   status = ?, exit_timestamp = ?, exit_price = ?, exit_reason = ?,
                   pnl_points = ?, pnl_rub = ?, bars_held = ?, updated_at = ?
                   WHERE trade_id = ?""",
                (
                    trade.status.value if hasattr(trade.status, "value") else trade.status,
                    _dt_to_str(trade.exit_timestamp),
                    trade.exit_price,
                    trade.exit_reason.value if trade.exit_reason and hasattr(trade.exit_reason, "value") else trade.exit_reason,
                    trade.pnl_points,
                    trade.pnl_rub,
                    trade.bars_held,
                    now,
                    trade.trade_id,
                ),
            )
            conn.commit()

    def list_all_trades(self, ticker: Optional[str] = None) -> list:
        with self._connect() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT * FROM orb_paper_trades WHERE ticker = ? ORDER BY entry_timestamp",
                    (ticker,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM orb_paper_trades ORDER BY entry_timestamp"
                ).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def export_csv(self, path: str, ticker: Optional[str] = None) -> None:
        trades = self.list_all_trades(ticker=ticker)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "trade_id", "strategy_name", "experiment_name", "ticker", "direction",
            "entry_timestamp", "entry_price", "or_high", "or_low",
            "stop_price", "take_price", "status",
            "exit_timestamp", "exit_price", "exit_reason",
            "pnl_points", "pnl_rub", "bars_held", "created_at", "updated_at",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for t in trades:
                writer.writerow({
                    "trade_id": t.trade_id,
                    "strategy_name": t.strategy_name,
                    "experiment_name": t.experiment_name,
                    "ticker": t.ticker,
                    "direction": t.direction,
                    "entry_timestamp": _dt_to_str(t.entry_timestamp),
                    "entry_price": t.entry_price,
                    "or_high": t.or_high,
                    "or_low": t.or_low,
                    "stop_price": t.stop_price,
                    "take_price": t.take_price,
                    "status": t.status.value if hasattr(t.status, "value") else t.status,
                    "exit_timestamp": _dt_to_str(t.exit_timestamp),
                    "exit_price": t.exit_price,
                    "exit_reason": (
                        t.exit_reason.value
                        if t.exit_reason and hasattr(t.exit_reason, "value")
                        else t.exit_reason
                    ),
                    "pnl_points": t.pnl_points,
                    "pnl_rub": t.pnl_rub,
                    "bars_held": t.bars_held,
                    "created_at": _dt_to_str(t.created_at),
                    "updated_at": _dt_to_str(t.updated_at),
                })

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> OrbPaperTrade:
        exit_reason = None
        if row["exit_reason"]:
            try:
                exit_reason = OrbExitReason(row["exit_reason"])
            except ValueError:
                exit_reason = row["exit_reason"]
        return OrbPaperTrade(
            trade_id=row["trade_id"],
            strategy_name=row["strategy_name"] or "",
            experiment_name=row["experiment_name"] or "",
            ticker=row["ticker"],
            direction=row["direction"],
            entry_timestamp=_str_to_dt(row["entry_timestamp"]) or datetime.now(tz=timezone.utc),
            entry_price=row["entry_price"],
            or_high=row["or_high"],
            or_low=row["or_low"],
            stop_price=row["stop_price"],
            take_price=row["take_price"],
            status=OrbTradeStatus(row["status"]),
            exit_timestamp=_str_to_dt(row["exit_timestamp"]),
            exit_price=row["exit_price"],
            exit_reason=exit_reason,
            pnl_points=row["pnl_points"],
            pnl_rub=row["pnl_rub"],
            bars_held=row["bars_held"] or 0,
            created_at=_str_to_dt(row["created_at"]),
            updated_at=_str_to_dt(row["updated_at"]),
        )
