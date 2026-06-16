"""SQLite repository for the sandbox execution layer (MVP-L1a).

Completely separate DB from paper trading. Never shares tables/files with
src/paper/repository.py or src/paper/momentum/repository.py.
"""
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.sandbox.models import (
    ReconciliationStatus,
    SandboxDailyRisk,
    SandboxEvent,
    SandboxExitReason,
    SandboxFill,
    SandboxOrder,
    SandboxOrderStatus,
    SandboxPosition,
    SandboxRiskState,
    SandboxTrade,
    SandboxTradeStatus,
)

_DDL = """
CREATE TABLE IF NOT EXISTS sandbox_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sandbox_orders (
    order_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    strategy TEXT NOT NULL,
    ticker TEXT NOT NULL,
    figi TEXT,
    instrument_uid TEXT,
    direction TEXT NOT NULL,
    order_side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    requested_qty INTEGER NOT NULL,
    requested_price REAL,
    submitted_at TEXT NOT NULL,
    status TEXT NOT NULL,
    filled_qty INTEGER NOT NULL DEFAULT 0,
    avg_fill_price REAL,
    commission_rub REAL,
    slippage_points REAL,
    slippage_rub REAL,
    raw_response_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sandbox_fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    qty INTEGER NOT NULL,
    price REAL NOT NULL,
    commission_rub REAL NOT NULL DEFAULT 0,
    fill_time TEXT NOT NULL,
    raw_response_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sandbox_positions (
    ticker TEXT PRIMARY KEY,
    figi TEXT,
    instrument_uid TEXT,
    direction TEXT NOT NULL,
    qty INTEGER NOT NULL DEFAULT 0,
    avg_price REAL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sandbox_trades (
    trade_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    entry_order_id TEXT,
    exit_order_id TEXT,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    qty INTEGER NOT NULL,
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    take_price REAL NOT NULL,
    status TEXT NOT NULL,
    exit_time TEXT,
    exit_price REAL,
    exit_reason TEXT,
    gross_pnl_rub REAL,
    commission_rub REAL,
    net_pnl_rub REAL,
    bars_held INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sandbox_events (
    event_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS sandbox_daily_risk (
    date_msk TEXT PRIMARY KEY,
    trades_today INTEGER NOT NULL DEFAULT 0,
    realized_pnl_rub REAL NOT NULL DEFAULT 0,
    consecutive_losses INTEGER NOT NULL DEFAULT 0,
    daily_loss_breached INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _ts(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _from_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class SandboxRepository:
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

    # ── Generic key/value state ─────────────────────────────────────────────

    def get_state(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM sandbox_state WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sandbox_state (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, _now_iso()),
            )

    # ── Risk state ───────────────────────────────────────────────────────────

    def load_risk_state(self) -> SandboxRiskState:
        import json
        raw = self.get_state("risk_state")
        if not raw:
            return SandboxRiskState()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return SandboxRiskState()
        return SandboxRiskState(**{**SandboxRiskState().__dict__, **data})

    def save_risk_state(self, state: SandboxRiskState) -> None:
        import json
        from dataclasses import asdict
        self.set_state("risk_state", json.dumps(asdict(state)))

    # ── Daily risk ───────────────────────────────────────────────────────────

    def load_daily_risk(self, date_msk: str) -> SandboxDailyRisk:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sandbox_daily_risk WHERE date_msk = ?", (date_msk,)
            ).fetchone()
        if row is None:
            return SandboxDailyRisk(date_msk=date_msk)
        return SandboxDailyRisk(
            date_msk=row["date_msk"],
            trades_today=row["trades_today"],
            realized_pnl_rub=row["realized_pnl_rub"],
            consecutive_losses=row["consecutive_losses"],
            daily_loss_breached=bool(row["daily_loss_breached"]),
        )

    def save_daily_risk(self, daily: SandboxDailyRisk) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sandbox_daily_risk
                   (date_msk, trades_today, realized_pnl_rub, consecutive_losses,
                    daily_loss_breached, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    daily.date_msk, daily.trades_today, daily.realized_pnl_rub,
                    daily.consecutive_losses, int(daily.daily_loss_breached), _now_iso(),
                ),
            )

    # ── Orders ───────────────────────────────────────────────────────────────

    def insert_order(self, order: SandboxOrder) -> None:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO sandbox_orders
                   (order_id, signal_id, strategy, ticker, figi, instrument_uid,
                    direction, order_side, order_type, requested_qty, requested_price,
                    submitted_at, status, filled_qty, avg_fill_price, commission_rub,
                    slippage_points, slippage_rub, raw_response_json, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    order.order_id, order.signal_id, order.strategy, order.ticker,
                    order.figi, order.instrument_uid, order.direction, order.order_side,
                    order.order_type, order.requested_qty, order.requested_price,
                    _ts(order.submitted_at), order.status.value if isinstance(order.status, SandboxOrderStatus) else order.status,
                    order.filled_qty, order.avg_fill_price, order.commission_rub,
                    order.slippage_points, order.slippage_rub, order.raw_response_json,
                    now, now,
                ),
            )

    def update_order(self, order: SandboxOrder) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE sandbox_orders SET
                   status=?, filled_qty=?, avg_fill_price=?, commission_rub=?,
                   slippage_points=?, slippage_rub=?, raw_response_json=?, updated_at=?
                   WHERE order_id=?""",
                (
                    order.status.value if isinstance(order.status, SandboxOrderStatus) else order.status,
                    order.filled_qty, order.avg_fill_price, order.commission_rub,
                    order.slippage_points, order.slippage_rub, order.raw_response_json,
                    _now_iso(), order.order_id,
                ),
            )

    def get_order(self, order_id: str) -> Optional[SandboxOrder]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sandbox_orders WHERE order_id = ?", (order_id,)
            ).fetchone()
        return _row_to_order(row) if row else None

    def list_orders(self, ticker: Optional[str] = None) -> list[SandboxOrder]:
        with self._connect() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT * FROM sandbox_orders WHERE ticker=? ORDER BY submitted_at", (ticker,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM sandbox_orders ORDER BY submitted_at").fetchall()
        return [_row_to_order(r) for r in rows]

    # ── Fills ────────────────────────────────────────────────────────────────

    def insert_fill(self, fill: SandboxFill) -> None:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO sandbox_fills
                   (fill_id, order_id, ticker, direction, qty, price, commission_rub,
                    fill_time, raw_response_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    fill.fill_id, fill.order_id, fill.ticker, fill.direction,
                    fill.qty, fill.price, fill.commission_rub,
                    _ts(fill.fill_time), fill.raw_response_json, now,
                ),
            )

    def list_fills(self, order_id: Optional[str] = None) -> list[SandboxFill]:
        with self._connect() as conn:
            if order_id:
                rows = conn.execute(
                    "SELECT * FROM sandbox_fills WHERE order_id=? ORDER BY fill_time", (order_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM sandbox_fills ORDER BY fill_time").fetchall()
        return [
            SandboxFill(
                fill_id=r["fill_id"], order_id=r["order_id"], ticker=r["ticker"],
                direction=r["direction"], qty=r["qty"], price=r["price"],
                commission_rub=r["commission_rub"], fill_time=_from_ts(r["fill_time"]),
                raw_response_json=r["raw_response_json"], created_at=_from_ts(r["created_at"]),
            )
            for r in rows
        ]

    # ── Positions ────────────────────────────────────────────────────────────

    def upsert_position(self, position: SandboxPosition) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sandbox_positions
                   (ticker, figi, instrument_uid, direction, qty, avg_price, updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    position.ticker, position.figi, position.instrument_uid,
                    position.direction, position.qty, position.avg_price, _now_iso(),
                ),
            )

    def get_position(self, ticker: str) -> Optional[SandboxPosition]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sandbox_positions WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row is None:
            return None
        return SandboxPosition(
            ticker=row["ticker"], figi=row["figi"], instrument_uid=row["instrument_uid"],
            direction=row["direction"], qty=row["qty"], avg_price=row["avg_price"],
            updated_at=_from_ts(row["updated_at"]),
        )

    # ── Trades ───────────────────────────────────────────────────────────────

    def insert_trade(self, trade: SandboxTrade) -> None:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO sandbox_trades
                   (trade_id, signal_id, entry_order_id, exit_order_id, ticker, direction,
                    qty, entry_time, entry_price, stop_price, take_price, status,
                    exit_time, exit_price, exit_reason, gross_pnl_rub, commission_rub,
                    net_pnl_rub, bars_held, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    trade.trade_id, trade.signal_id, trade.entry_order_id, trade.exit_order_id,
                    trade.ticker, trade.direction, trade.qty,
                    _ts(trade.entry_time), trade.entry_price, trade.stop_price, trade.take_price,
                    trade.status.value if isinstance(trade.status, SandboxTradeStatus) else trade.status,
                    _ts(trade.exit_time), trade.exit_price,
                    trade.exit_reason.value if isinstance(trade.exit_reason, SandboxExitReason) else trade.exit_reason,
                    trade.gross_pnl_rub, trade.commission_rub, trade.net_pnl_rub,
                    trade.bars_held, now, now,
                ),
            )

    def update_trade(self, trade: SandboxTrade) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE sandbox_trades SET
                   exit_order_id=?, status=?, exit_time=?, exit_price=?, exit_reason=?,
                   gross_pnl_rub=?, commission_rub=?, net_pnl_rub=?, bars_held=?, updated_at=?
                   WHERE trade_id=?""",
                (
                    trade.exit_order_id,
                    trade.status.value if isinstance(trade.status, SandboxTradeStatus) else trade.status,
                    _ts(trade.exit_time), trade.exit_price,
                    trade.exit_reason.value if isinstance(trade.exit_reason, SandboxExitReason) else trade.exit_reason,
                    trade.gross_pnl_rub, trade.commission_rub, trade.net_pnl_rub,
                    trade.bars_held, _now_iso(), trade.trade_id,
                ),
            )

    def get_open_trade(self, ticker: str) -> Optional[SandboxTrade]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sandbox_trades WHERE ticker=? AND status=? LIMIT 1",
                (ticker, SandboxTradeStatus.OPEN.value),
            ).fetchone()
        return _row_to_trade(row) if row else None

    def list_trades(self, ticker: Optional[str] = None) -> list[SandboxTrade]:
        with self._connect() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT * FROM sandbox_trades WHERE ticker=? ORDER BY entry_time", (ticker,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM sandbox_trades ORDER BY entry_time").fetchall()
        return [_row_to_trade(r) for r in rows]

    # ── Events ───────────────────────────────────────────────────────────────

    def insert_event(
        self, event_id: str, ticker: str, event_type: str,
        message: str, payload: Optional[dict] = None,
    ) -> None:
        import json
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO sandbox_events
                   (event_id, timestamp, ticker, event_type, message, payload_json)
                   VALUES (?,?,?,?,?,?)""",
                (
                    event_id, _now_iso(), ticker, event_type, message,
                    json.dumps(payload) if payload else None,
                ),
            )

    def list_events(self, limit: int = 100) -> list[SandboxEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sandbox_events ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            SandboxEvent(
                event_id=r["event_id"], timestamp=_from_ts(r["timestamp"]),
                ticker=r["ticker"], event_type=r["event_type"], message=r["message"],
                payload_json=r["payload_json"],
            )
            for r in rows
        ]

    # ── CSV export ───────────────────────────────────────────────────────────

    def export_orders_csv(self, path: str) -> None:
        orders = self.list_orders()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "order_id", "signal_id", "strategy", "ticker", "figi", "instrument_uid",
            "direction", "order_side", "order_type", "requested_qty", "requested_price",
            "submitted_at", "status", "filled_qty", "avg_fill_price", "commission_rub",
            "slippage_points", "slippage_rub", "created_at", "updated_at",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for o in orders:
                writer.writerow({k: getattr(o, k) for k in fieldnames if k != "status"} | {
                    "status": o.status.value if hasattr(o.status, "value") else o.status,
                    "submitted_at": _ts(o.submitted_at) if isinstance(o.submitted_at, datetime) else o.submitted_at,
                    "created_at": _ts(o.created_at) if isinstance(o.created_at, datetime) else o.created_at,
                    "updated_at": _ts(o.updated_at) if isinstance(o.updated_at, datetime) else o.updated_at,
                })

    def export_trades_csv(self, path: str) -> None:
        trades = self.list_trades()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "trade_id", "signal_id", "entry_order_id", "exit_order_id", "ticker", "direction",
            "qty", "entry_time", "entry_price", "stop_price", "take_price", "status",
            "exit_time", "exit_price", "exit_reason", "gross_pnl_rub", "commission_rub",
            "net_pnl_rub", "bars_held", "created_at", "updated_at",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for t in trades:
                row = {k: getattr(t, k) for k in fieldnames}
                row["status"] = t.status.value if hasattr(t.status, "value") else t.status
                row["exit_reason"] = (
                    t.exit_reason.value if t.exit_reason and hasattr(t.exit_reason, "value") else t.exit_reason
                )
                for tf in ("entry_time", "exit_time", "created_at", "updated_at"):
                    if isinstance(row[tf], datetime):
                        row[tf] = _ts(row[tf])
                writer.writerow(row)


def _row_to_order(row: sqlite3.Row) -> SandboxOrder:
    return SandboxOrder(
        order_id=row["order_id"], signal_id=row["signal_id"], strategy=row["strategy"],
        ticker=row["ticker"], figi=row["figi"], instrument_uid=row["instrument_uid"],
        direction=row["direction"], order_side=row["order_side"], order_type=row["order_type"],
        requested_qty=row["requested_qty"], requested_price=row["requested_price"],
        submitted_at=_from_ts(row["submitted_at"]),
        status=SandboxOrderStatus(row["status"]),
        filled_qty=row["filled_qty"], avg_fill_price=row["avg_fill_price"],
        commission_rub=row["commission_rub"], slippage_points=row["slippage_points"],
        slippage_rub=row["slippage_rub"], raw_response_json=row["raw_response_json"],
        created_at=_from_ts(row["created_at"]), updated_at=_from_ts(row["updated_at"]),
    )


def _row_to_trade(row: sqlite3.Row) -> SandboxTrade:
    exit_reason = None
    if row["exit_reason"]:
        try:
            exit_reason = SandboxExitReason(row["exit_reason"])
        except ValueError:
            exit_reason = row["exit_reason"]
    return SandboxTrade(
        trade_id=row["trade_id"], signal_id=row["signal_id"],
        entry_order_id=row["entry_order_id"], exit_order_id=row["exit_order_id"],
        ticker=row["ticker"], direction=row["direction"], qty=row["qty"],
        entry_time=_from_ts(row["entry_time"]), entry_price=row["entry_price"],
        stop_price=row["stop_price"], take_price=row["take_price"],
        status=SandboxTradeStatus(row["status"]),
        exit_time=_from_ts(row["exit_time"]), exit_price=row["exit_price"],
        exit_reason=exit_reason, gross_pnl_rub=row["gross_pnl_rub"],
        commission_rub=row["commission_rub"], net_pnl_rub=row["net_pnl_rub"],
        bars_held=row["bars_held"],
        created_at=_from_ts(row["created_at"]), updated_at=_from_ts(row["updated_at"]),
    )
