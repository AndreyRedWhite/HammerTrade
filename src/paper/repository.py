import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.paper.models import PaperTrade, PaperTradeStatus, PaperExitReason

_DDL = """
CREATE TABLE IF NOT EXISTS paper_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    class_code TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    profile TEXT NOT NULL,
    direction TEXT NOT NULL,
    signal_timestamp TEXT NOT NULL,
    entry_timestamp TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    take_price REAL NOT NULL,
    status TEXT NOT NULL,
    exit_timestamp TEXT,
    exit_price REAL,
    exit_reason TEXT,
    pnl_points REAL,
    pnl_rub REAL,
    bars_held INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_events (
    event_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT
);
"""


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _ts(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _from_ts(s: Optional[str]) -> Optional[datetime]:
    if s is None:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


class PaperRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

    def get_state(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM paper_state WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO paper_state (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, _now_iso()),
            )

    def get_open_trade(
        self, ticker: str, timeframe: str, profile: str, direction: str
    ) -> Optional[PaperTrade]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM paper_trades
                   WHERE ticker=? AND timeframe=? AND profile=? AND direction=?
                   AND status=?""",
                (ticker, timeframe, profile, direction, PaperTradeStatus.OPEN.value),
            ).fetchone()
        return _row_to_trade(row) if row else None

    def insert_trade(self, trade: PaperTrade) -> None:
        now = _now_iso()
        if trade.created_at is None:
            trade.created_at = datetime.fromisoformat(now)
        if trade.updated_at is None:
            trade.updated_at = datetime.fromisoformat(now)
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO paper_trades
                   (trade_id, ticker, class_code, timeframe, profile, direction,
                    signal_timestamp, entry_timestamp, entry_price, stop_price, take_price,
                    status, exit_timestamp, exit_price, exit_reason,
                    pnl_points, pnl_rub, bars_held, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    trade.trade_id, trade.ticker, trade.class_code, trade.timeframe,
                    trade.profile, trade.direction,
                    _ts(trade.signal_timestamp), _ts(trade.entry_timestamp),
                    trade.entry_price, trade.stop_price, trade.take_price,
                    trade.status.value if isinstance(trade.status, PaperTradeStatus) else trade.status,
                    _ts(trade.exit_timestamp), trade.exit_price,
                    trade.exit_reason.value if isinstance(trade.exit_reason, PaperExitReason) else trade.exit_reason,
                    trade.pnl_points, trade.pnl_rub, trade.bars_held,
                    _ts(trade.created_at), _ts(trade.updated_at),
                ),
            )

    def update_trade(self, trade: PaperTrade) -> None:
        trade.updated_at = datetime.fromisoformat(_now_iso())
        with self._connect() as conn:
            conn.execute(
                """UPDATE paper_trades SET
                   status=?, exit_timestamp=?, exit_price=?, exit_reason=?,
                   pnl_points=?, pnl_rub=?, bars_held=?, updated_at=?
                   WHERE trade_id=?""",
                (
                    trade.status.value if isinstance(trade.status, PaperTradeStatus) else trade.status,
                    _ts(trade.exit_timestamp), trade.exit_price,
                    trade.exit_reason.value if isinstance(trade.exit_reason, PaperExitReason) else trade.exit_reason,
                    trade.pnl_points, trade.pnl_rub, trade.bars_held,
                    _ts(trade.updated_at), trade.trade_id,
                ),
            )

    def insert_event(
        self, event_id: str, ticker: str, event_type: str,
        message: str, payload: Optional[dict] = None
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO paper_events
                   (event_id, timestamp, ticker, event_type, message, payload_json)
                   VALUES (?,?,?,?,?,?)""",
                (
                    event_id, _now_iso(), ticker, event_type, message,
                    json.dumps(payload) if payload else None,
                ),
            )

    def list_recent_trades(
        self, ticker: Optional[str] = None, limit: int = 50
    ) -> list[PaperTrade]:
        with self._connect() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT * FROM paper_trades WHERE ticker=? ORDER BY entry_timestamp DESC LIMIT ?",
                    (ticker, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM paper_trades ORDER BY entry_timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [_row_to_trade(r) for r in rows]


def _row_to_trade(row) -> PaperTrade:
    return PaperTrade(
        trade_id=row["trade_id"],
        ticker=row["ticker"],
        class_code=row["class_code"],
        timeframe=row["timeframe"],
        profile=row["profile"],
        direction=row["direction"],
        signal_timestamp=_from_ts(row["signal_timestamp"]),
        entry_timestamp=_from_ts(row["entry_timestamp"]),
        entry_price=row["entry_price"],
        stop_price=row["stop_price"],
        take_price=row["take_price"],
        status=PaperTradeStatus(row["status"]),
        exit_timestamp=_from_ts(row["exit_timestamp"]),
        exit_price=row["exit_price"],
        exit_reason=PaperExitReason(row["exit_reason"]) if row["exit_reason"] else None,
        pnl_points=row["pnl_points"],
        pnl_rub=row["pnl_rub"],
        bars_held=row["bars_held"],
        created_at=_from_ts(row["created_at"]),
        updated_at=_from_ts(row["updated_at"]),
    )
