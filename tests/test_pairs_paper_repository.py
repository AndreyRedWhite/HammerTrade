"""Tests for the pairs stat-arb SQLite repository."""
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.paper.pairs.models import (
    PairExitReason,
    PairPaperTrade,
    PairState,
    PairTradeStatus,
)
from src.paper.pairs.repository import PairsRepository


def _repo():
    d = tempfile.mkdtemp()
    repo = PairsRepository(str(Path(d) / "pairs.sqlite"))
    repo.init_db()
    return repo


def _trade(status=PairTradeStatus.OPEN):
    return PairPaperTrade(
        trade_id="pairs:SBER:test:2026-06-01T10:00:00+00:00",
        experiment_name="test", pair_name="SBER",
        pref_ticker="SBERP", ord_ticker="SBER",
        direction="SHORT_SPREAD",
        entry_timestamp=datetime(2026, 6, 1, 10, tzinfo=timezone.utc),
        entry_z=2.5, pref_entry_price=310.0, ord_entry_price=300.0,
        notional_per_leg=100_000.0, cost_bps_per_leg_side=3.5,
        status=status,
    )


def test_init_creates_tables():
    repo = _repo()
    # no exception, and queries work
    assert repo.get_open_trade("SBER") is None
    assert repo.load_state("SBER") is None


def test_state_roundtrip():
    repo = _repo()
    repo.save_state(PairState(pair_name="SBER", last_processed_bar_ts="2026-06-01T10:00:00+00:00"))
    s = repo.load_state("SBER")
    assert s.last_processed_bar_ts == "2026-06-01T10:00:00+00:00"


def test_insert_and_get_open_trade():
    repo = _repo()
    repo.insert_trade(_trade())
    t = repo.get_open_trade("SBER")
    assert t is not None
    assert t.direction == "SHORT_SPREAD"
    assert t.pref_entry_price == 310.0


def test_update_trade_to_closed():
    repo = _repo()
    repo.insert_trade(_trade())
    t = repo.get_open_trade("SBER")
    t.status = PairTradeStatus.CLOSED
    t.exit_reason = PairExitReason.EXIT_MEAN
    t.pnl_rub = 1234.5
    t.pnl_rub_market = 1100.0
    t.pref_market_fill = 309.0
    t.ord_market_fill = 301.0
    repo.update_trade(t)
    assert repo.get_open_trade("SBER") is None
    closed = repo.list_all_trades("SBER")
    assert len(closed) == 1
    assert closed[0].status == PairTradeStatus.CLOSED
    assert closed[0].exit_reason == PairExitReason.EXIT_MEAN
    assert closed[0].pnl_rub == 1234.5
    assert closed[0].pnl_rub_market == 1100.0


def test_export_csv(tmp_path):
    repo = _repo()
    repo.insert_trade(_trade())
    out = tmp_path / "trades.csv"
    repo.export_csv(str(out))
    content = out.read_text()
    assert "trade_id" in content
    assert "SHORT_SPREAD" in content
