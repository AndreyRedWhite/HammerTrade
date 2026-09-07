"""Tests for src/paper/momentum/repository.py (MVP-R3)."""
import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.paper.momentum.models import (
    MomentumDailyContext,
    MomentumDayState,
    MomentumPaperTrade,
    MomentumTradeStatus,
    MomentumExitReason,
)
from src.paper.momentum.repository import MomentumRepository

_NOW = datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc)


def _repo(tmp_path) -> MomentumRepository:
    r = MomentumRepository(str(tmp_path / "test_momentum.sqlite"))
    r.init_db()
    return r


def _trade(trade_id: str = "t1", status: MomentumTradeStatus = MomentumTradeStatus.OPEN) -> MomentumPaperTrade:
    return MomentumPaperTrade(
        trade_id=trade_id,
        strategy_name="momentum_continuation",
        experiment_name="test",
        ticker="SiM6",
        direction="SHORT",
        signal_timestamp=_NOW,
        entry_timestamp=_NOW,
        entry_price=72005.0,
        stop_price=72050.0,
        take_price=71915.0,
        atr_value=20.0,
        volume_value=300.0,
        volume_avg=100.0,
        candle_range=50.0,
        close_position=0.1,
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
    )


# ── 1. init_db creates tables ─────────────────────────────────────────────────

def test_init_creates_tables(tmp_path):
    r = _repo(tmp_path)
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test_momentum.sqlite"))
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "momentum_daily_state" in tables
    assert "momentum_paper_trades" in tables


# ── 2. save and load daily state ──────────────────────────────────────────────

def test_save_and_load_daily_state(tmp_path):
    r = _repo(tmp_path)
    ctx = MomentumDailyContext(
        date_msk="2026-06-02",
        state=MomentumDayState.WAITING_FOR_SIGNAL,
        trades_today=0,
        done_for_day=False,
        last_processed_candle_ts="2026-06-02T08:00:00+00:00",
    )
    r.save_daily_state(ctx)
    loaded = r.load_daily_state("2026-06-02")
    assert loaded is not None
    assert loaded.date_msk == "2026-06-02"
    assert loaded.trades_today == 0
    assert loaded.done_for_day is False


# ── 3. insert and get open trade ─────────────────────────────────────────────

def test_insert_and_get_open_trade(tmp_path):
    r = _repo(tmp_path)
    t = _trade("t1", MomentumTradeStatus.OPEN)
    r.insert_trade(t)
    loaded = r.get_open_trade("SiM6")
    assert loaded is not None
    assert loaded.trade_id == "t1"
    assert loaded.entry_price == pytest.approx(72005.0)


# ── 4. update trade closes it ────────────────────────────────────────────────

def test_update_trade_closes_it(tmp_path):
    r = _repo(tmp_path)
    t = _trade("t1", MomentumTradeStatus.OPEN)
    r.insert_trade(t)
    t.status = MomentumTradeStatus.CLOSED
    t.exit_price = 71915.0
    t.exit_reason = MomentumExitReason.TAKE
    t.pnl_points = 90.0
    t.pnl_rub = 899.95
    r.update_trade(t)
    # get_open_trade should now return None
    assert r.get_open_trade("SiM6") is None
    # list_all_trades should return the closed one
    all_trades = r.list_all_trades("SiM6")
    assert len(all_trades) == 1
    assert all_trades[0].exit_reason == MomentumExitReason.TAKE


# ── 5. export_csv creates file with correct headers ───────────────────────────

def test_export_csv(tmp_path):
    r = _repo(tmp_path)
    t1 = _trade("t1", MomentumTradeStatus.CLOSED)
    t1.exit_price = 71915.0
    t1.exit_reason = MomentumExitReason.TAKE
    t1.pnl_points = 90.0
    t1.pnl_rub = 899.95
    r.insert_trade(t1)
    r.update_trade(t1)
    csv_path = str(tmp_path / "trades.csv")
    r.export_csv(csv_path, ticker="SiM6")
    assert Path(csv_path).exists()
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["trade_id"] == "t1"
    assert "entry_price" in rows[0]
