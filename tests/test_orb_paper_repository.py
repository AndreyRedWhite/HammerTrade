"""Tests for ORB paper trading SQLite repository."""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.orb.models import (
    OrbDailyContext,
    OrbDayState,
    OrbExitReason,
    OrbPaperTrade,
    OrbTradeStatus,
)
from src.paper.orb.repository import OrbRepository


def _make_trade(trade_id: str, status: OrbTradeStatus = OrbTradeStatus.OPEN) -> OrbPaperTrade:
    return OrbPaperTrade(
        trade_id=trade_id,
        strategy_name="ORB",
        experiment_name="test_exp",
        ticker="SiM6",
        direction="SHORT",
        entry_timestamp=datetime(2026, 5, 30, 9, 0, 0, tzinfo=timezone.utc),
        entry_price=100.0,
        or_high=120.0,
        or_low=100.0,
        stop_price=120.0,
        take_price=60.0,
        status=status,
        bars_held=0,
    )


def _make_closed_trade(trade_id: str, pnl_rub: float = 10.0) -> OrbPaperTrade:
    t = _make_trade(trade_id, status=OrbTradeStatus.CLOSED)
    t.exit_timestamp = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    t.exit_price = 99.0
    t.exit_reason = OrbExitReason.TAKE
    t.pnl_points = 1.0
    t.pnl_rub = pnl_rub
    return t


# ─────────────────────────────── 1 ────────────────────────────────────────────
def test_init_creates_tables(tmp_path):
    """init_db() creates orb_daily_state and orb_paper_trades tables."""
    db = str(tmp_path / "test.sqlite")
    repo = OrbRepository(db)
    repo.init_db()

    import sqlite3
    conn = sqlite3.connect(db)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "orb_daily_state" in tables
    assert "orb_paper_trades" in tables


# ─────────────────────────────── 2 ────────────────────────────────────────────
def test_save_and_load_daily_state(tmp_path):
    """save_daily_state → load_daily_state returns matching fields."""
    db = str(tmp_path / "test.sqlite")
    repo = OrbRepository(db)
    repo.init_db()

    ctx = OrbDailyContext(
        date_msk="2026-05-30",
        state=OrbDayState.WAITING_FOR_BREAKOUT,
        or_high=125.0,
        or_low=98.0,
        or_candles_count=7,
        trade_opened=False,
        trade_closed=False,
        done_for_day=False,
        last_processed_candle_ts="2026-05-30T08:30:00+00:00",
    )
    repo.save_daily_state(ctx)

    loaded = repo.load_daily_state("2026-05-30")
    assert loaded is not None
    assert loaded.date_msk == "2026-05-30"
    assert loaded.state == OrbDayState.WAITING_FOR_BREAKOUT
    assert loaded.or_high == 125.0
    assert loaded.or_low == 98.0
    assert loaded.or_candles_count == 7
    assert loaded.trade_opened is False
    assert loaded.done_for_day is False
    assert loaded.last_processed_candle_ts == "2026-05-30T08:30:00+00:00"


# ─────────────────────────────── 3 ────────────────────────────────────────────
def test_insert_and_get_trade(tmp_path):
    """insert_trade → get_open_trade returns the trade."""
    db = str(tmp_path / "test.sqlite")
    repo = OrbRepository(db)
    repo.init_db()

    trade = _make_trade("orb:SiM6:test:001")
    repo.insert_trade(trade)

    loaded = repo.get_open_trade("SiM6")
    assert loaded is not None
    assert loaded.trade_id == "orb:SiM6:test:001"
    assert loaded.status == OrbTradeStatus.OPEN
    assert loaded.entry_price == 100.0
    assert loaded.stop_price == 120.0
    assert loaded.take_price == 60.0


# ─────────────────────────────── 4 ────────────────────────────────────────────
def test_update_trade_closes_it(tmp_path):
    """insert OPEN trade, update to CLOSED, get_open_trade returns None."""
    db = str(tmp_path / "test.sqlite")
    repo = OrbRepository(db)
    repo.init_db()

    trade = _make_trade("orb:SiM6:test:002")
    repo.insert_trade(trade)

    # Update to closed
    trade.status = OrbTradeStatus.CLOSED
    trade.exit_price = 90.0
    trade.exit_reason = OrbExitReason.STOP
    trade.pnl_points = -10.0
    trade.pnl_rub = -100.05
    trade.exit_timestamp = datetime(2026, 5, 30, 11, 0, 0, tzinfo=timezone.utc)
    repo.update_trade(trade)

    # Should not be returned as open
    open_trade = repo.get_open_trade("SiM6")
    assert open_trade is None

    # Should appear in list_all_trades
    all_trades = repo.list_all_trades(ticker="SiM6")
    assert len(all_trades) == 1
    assert all_trades[0].status == OrbTradeStatus.CLOSED
    assert all_trades[0].exit_reason == OrbExitReason.STOP


# ─────────────────────────────── 5 ────────────────────────────────────────────
def test_export_csv(tmp_path):
    """Insert 2 closed trades, export_csv → file with correct header and 2 rows."""
    db = str(tmp_path / "test.sqlite")
    repo = OrbRepository(db)
    repo.init_db()

    trade1 = _make_closed_trade("orb:SiM6:test:003", pnl_rub=50.0)
    trade2 = _make_closed_trade("orb:SiM6:test:004", pnl_rub=-30.0)
    repo.insert_trade(trade1)
    repo.insert_trade(trade2)

    csv_path = str(tmp_path / "export.csv")
    repo.export_csv(csv_path, ticker="SiM6")

    assert Path(csv_path).exists()

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 2
    assert "trade_id" in rows[0]
    assert "ticker" in rows[0]
    assert "pnl_rub" in rows[0]
    assert "exit_reason" in rows[0]
    trade_ids = {r["trade_id"] for r in rows}
    assert "orb:SiM6:test:003" in trade_ids
    assert "orb:SiM6:test:004" in trade_ids
