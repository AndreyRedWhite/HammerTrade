"""SQLite repository for pairs stat-arb paper trading state and trades."""
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.paper.pairs.models import (
    PairExitReason,
    PairPaperTrade,
    PairState,
    PairTradeStatus,
)

_STATE_DDL = """
CREATE TABLE IF NOT EXISTS pairs_state (
    pair_name TEXT PRIMARY KEY,
    last_processed_bar_ts TEXT,
    created_at TEXT,
    updated_at TEXT
)
"""

_TRADES_DDL = """
CREATE TABLE IF NOT EXISTS pairs_trades (
    trade_id TEXT PRIMARY KEY,
    experiment_name TEXT,
    pair_name TEXT,
    pref_ticker TEXT,
    ord_ticker TEXT,
    direction TEXT,
    entry_timestamp TEXT,
    entry_z REAL,
    pref_entry_price REAL,
    ord_entry_price REAL,
    notional_per_leg REAL,
    cost_bps_per_leg_side REAL,
    status TEXT,
    pref_market_fill REAL,
    ord_market_fill REAL,
    exit_timestamp TEXT,
    exit_z REAL,
    pref_exit_price REAL,
    ord_exit_price REAL,
    exit_reason TEXT,
    pnl_rub REAL,
    pnl_rub_market REAL,
    pref_exit_market_fill REAL,
    ord_exit_market_fill REAL,
    pnl_rub_realistic REAL,
    bars_held INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
)
"""


def _col(row, name):
    """Read a column that may not exist in an older journal row."""
    try:
        return row[name]
    except (IndexError, KeyError):
        return None


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


class PairsRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    #: Columns added after the first deployment. Existing sandbox/paper DBs
    #: predate the realistic-fill metric, so they are added in place rather than
    #: requiring the journal to be thrown away.
    _ADDED_COLUMNS = (
        ("pref_exit_market_fill", "REAL"),
        ("ord_exit_market_fill", "REAL"),
        ("pnl_rub_realistic", "REAL"),
    )

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_STATE_DDL)
            conn.execute(_TRADES_DDL)
            existing = {r["name"] for r in conn.execute("PRAGMA table_info(pairs_trades)")}
            for name, decl in self._ADDED_COLUMNS:
                if name not in existing:
                    conn.execute(f"ALTER TABLE pairs_trades ADD COLUMN {name} {decl}")
            conn.commit()

    # ── State cursor ──────────────────────────────────────────────────────────
    def load_state(self, pair_name: str) -> Optional[PairState]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pairs_state WHERE pair_name = ?", (pair_name,)
            ).fetchone()
        if row is None:
            return None
        return PairState(
            pair_name=row["pair_name"],
            last_processed_bar_ts=row["last_processed_bar_ts"],
        )

    def save_state(self, state: PairState) -> None:
        now = _now_utc_str()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT created_at FROM pairs_state WHERE pair_name = ?",
                (state.pair_name,)
            ).fetchone()
            created_at = row["created_at"] if row else now
            conn.execute(
                """INSERT OR REPLACE INTO pairs_state
                   (pair_name, last_processed_bar_ts, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (state.pair_name, state.last_processed_bar_ts, created_at, now),
            )
            conn.commit()

    # ── Trades ────────────────────────────────────────────────────────────────
    def get_open_trade(self, pair_name: str) -> Optional[PairPaperTrade]:
        with self._connect() as conn:
            # PENDING_EXIT is still a HELD position — the exit has signalled but
            # not filled. Excluding it here would hide the position and let the
            # engine open a second one on top of it.
            row = conn.execute(
                "SELECT * FROM pairs_trades WHERE pair_name = ? AND status IN (?, ?) "
                "ORDER BY entry_timestamp LIMIT 1",
                (pair_name, PairTradeStatus.OPEN.value, PairTradeStatus.PENDING_EXIT.value),
            ).fetchone()
        return self._row_to_trade(row) if row else None

    def insert_trade(self, t: PairPaperTrade) -> None:
        now = _now_utc_str()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO pairs_trades
                   (trade_id, experiment_name, pair_name, pref_ticker, ord_ticker,
                    direction, entry_timestamp, entry_z, pref_entry_price, ord_entry_price,
                    notional_per_leg, cost_bps_per_leg_side, status,
                    pref_market_fill, ord_market_fill, exit_timestamp, exit_z,
                    pref_exit_price, ord_exit_price, exit_reason, pnl_rub, pnl_rub_market,
                    pref_exit_market_fill, ord_exit_market_fill, pnl_rub_realistic,
                    bars_held, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    t.trade_id, t.experiment_name, t.pair_name, t.pref_ticker, t.ord_ticker,
                    t.direction, _dt_to_str(t.entry_timestamp), t.entry_z,
                    t.pref_entry_price, t.ord_entry_price,
                    t.notional_per_leg, t.cost_bps_per_leg_side,
                    t.status.value if hasattr(t.status, "value") else t.status,
                    t.pref_market_fill, t.ord_market_fill,
                    _dt_to_str(t.exit_timestamp), t.exit_z,
                    t.pref_exit_price, t.ord_exit_price,
                    t.exit_reason.value if t.exit_reason and hasattr(t.exit_reason, "value") else t.exit_reason,
                    t.pnl_rub, t.pnl_rub_market,
                    t.pref_exit_market_fill, t.ord_exit_market_fill, t.pnl_rub_realistic,
                    t.bars_held, now, now,
                ),
            )
            conn.commit()

    def update_trade(self, t: PairPaperTrade) -> None:
        now = _now_utc_str()
        with self._connect() as conn:
            conn.execute(
                """UPDATE pairs_trades SET
                   status=?, pref_market_fill=?, ord_market_fill=?,
                   exit_timestamp=?, exit_z=?, pref_exit_price=?, ord_exit_price=?,
                   exit_reason=?, pnl_rub=?, pnl_rub_market=?,
                   pref_exit_market_fill=?, ord_exit_market_fill=?, pnl_rub_realistic=?,
                   bars_held=?, updated_at=?
                   WHERE trade_id=?""",
                (
                    t.status.value if hasattr(t.status, "value") else t.status,
                    t.pref_market_fill, t.ord_market_fill,
                    _dt_to_str(t.exit_timestamp), t.exit_z,
                    t.pref_exit_price, t.ord_exit_price,
                    t.exit_reason.value if t.exit_reason and hasattr(t.exit_reason, "value") else t.exit_reason,
                    t.pnl_rub, t.pnl_rub_market,
                    t.pref_exit_market_fill, t.ord_exit_market_fill, t.pnl_rub_realistic,
                    t.bars_held, now, t.trade_id,
                ),
            )
            conn.commit()

    def list_all_trades(self, pair_name: Optional[str] = None) -> list:
        with self._connect() as conn:
            if pair_name:
                rows = conn.execute(
                    "SELECT * FROM pairs_trades WHERE pair_name = ? ORDER BY entry_timestamp",
                    (pair_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM pairs_trades ORDER BY entry_timestamp"
                ).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def export_csv(self, path: str) -> None:
        trades = self.list_all_trades()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "trade_id", "experiment_name", "pair_name", "pref_ticker", "ord_ticker",
            "direction", "entry_timestamp", "entry_z", "pref_entry_price", "ord_entry_price",
            "notional_per_leg", "cost_bps_per_leg_side", "status",
            "pref_market_fill", "ord_market_fill", "exit_timestamp", "exit_z",
            "pref_exit_price", "ord_exit_price", "exit_reason", "pnl_rub", "pnl_rub_market",
            "pref_exit_market_fill", "ord_exit_market_fill", "pnl_rub_realistic",
            "bars_held", "created_at", "updated_at",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for t in trades:
                w.writerow({
                    "trade_id": t.trade_id, "experiment_name": t.experiment_name,
                    "pair_name": t.pair_name, "pref_ticker": t.pref_ticker,
                    "ord_ticker": t.ord_ticker, "direction": t.direction,
                    "entry_timestamp": _dt_to_str(t.entry_timestamp), "entry_z": t.entry_z,
                    "pref_entry_price": t.pref_entry_price, "ord_entry_price": t.ord_entry_price,
                    "notional_per_leg": t.notional_per_leg,
                    "cost_bps_per_leg_side": t.cost_bps_per_leg_side,
                    "status": t.status.value if hasattr(t.status, "value") else t.status,
                    "pref_market_fill": t.pref_market_fill, "ord_market_fill": t.ord_market_fill,
                    "exit_timestamp": _dt_to_str(t.exit_timestamp), "exit_z": t.exit_z,
                    "pref_exit_price": t.pref_exit_price, "ord_exit_price": t.ord_exit_price,
                    "exit_reason": t.exit_reason.value if t.exit_reason and hasattr(t.exit_reason, "value") else t.exit_reason,
                    "pnl_rub": t.pnl_rub, "pnl_rub_market": t.pnl_rub_market,
                    "pref_exit_market_fill": t.pref_exit_market_fill,
                    "ord_exit_market_fill": t.ord_exit_market_fill,
                    "pnl_rub_realistic": t.pnl_rub_realistic,
                    "bars_held": t.bars_held,
                    "created_at": _dt_to_str(t.created_at), "updated_at": _dt_to_str(t.updated_at),
                })

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> PairPaperTrade:
        exit_reason = None
        if row["exit_reason"]:
            try:
                exit_reason = PairExitReason(row["exit_reason"])
            except ValueError:
                exit_reason = row["exit_reason"]
        return PairPaperTrade(
            trade_id=row["trade_id"],
            experiment_name=row["experiment_name"] or "",
            pair_name=row["pair_name"],
            pref_ticker=row["pref_ticker"],
            ord_ticker=row["ord_ticker"],
            direction=row["direction"],
            entry_timestamp=_str_to_dt(row["entry_timestamp"]) or datetime.now(tz=timezone.utc),
            entry_z=row["entry_z"],
            pref_entry_price=row["pref_entry_price"],
            ord_entry_price=row["ord_entry_price"],
            notional_per_leg=row["notional_per_leg"],
            cost_bps_per_leg_side=row["cost_bps_per_leg_side"],
            status=PairTradeStatus(row["status"]),
            pref_market_fill=row["pref_market_fill"],
            ord_market_fill=row["ord_market_fill"],
            exit_timestamp=_str_to_dt(row["exit_timestamp"]),
            exit_z=row["exit_z"],
            pref_exit_price=row["pref_exit_price"],
            ord_exit_price=row["ord_exit_price"],
            exit_reason=exit_reason,
            pnl_rub=row["pnl_rub"],
            pnl_rub_market=row["pnl_rub_market"],
            pref_exit_market_fill=_col(row, "pref_exit_market_fill"),
            ord_exit_market_fill=_col(row, "ord_exit_market_fill"),
            pnl_rub_realistic=_col(row, "pnl_rub_realistic"),
            bars_held=row["bars_held"] or 0,
            created_at=_str_to_dt(row["created_at"]),
            updated_at=_str_to_dt(row["updated_at"]),
        )
