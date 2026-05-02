from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.paper.models import PaperTrade, PaperTradeStatus, PaperExitReason
from src.paper.repository import PaperRepository


def _make_repo(tmp_path: Path) -> PaperRepository:
    repo = PaperRepository(str(tmp_path / "test.sqlite"))
    repo.init_db()
    return repo


def _make_trade(trade_id="paper:SiM6:1m:balanced:SELL:2026-01-01T10:00:00") -> PaperTrade:
    now = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    return PaperTrade(
        trade_id=trade_id,
        ticker="SiM6",
        class_code="SPBFUT",
        timeframe="1m",
        profile="balanced",
        direction="SELL",
        signal_timestamp=now,
        entry_timestamp=now,
        entry_price=89000.0,
        stop_price=89500.0,
        take_price=88500.0,
        status=PaperTradeStatus.OPEN,
        bars_held=0,
        created_at=now,
        updated_at=now,
    )


def test_init_db(tmp_path):
    repo = _make_repo(tmp_path)
    assert Path(repo.db_path).exists()


def test_set_get_state(tmp_path):
    repo = _make_repo(tmp_path)
    repo.set_state("foo", "bar")
    assert repo.get_state("foo") == "bar"


def test_get_state_missing(tmp_path):
    repo = _make_repo(tmp_path)
    assert repo.get_state("nonexistent") is None


def test_set_state_overwrite(tmp_path):
    repo = _make_repo(tmp_path)
    repo.set_state("key", "v1")
    repo.set_state("key", "v2")
    assert repo.get_state("key") == "v2"


def test_insert_trade(tmp_path):
    repo = _make_repo(tmp_path)
    trade = _make_trade()
    repo.insert_trade(trade)
    open_t = repo.get_open_trade("SiM6", "1m", "balanced", "SELL")
    assert open_t is not None
    assert open_t.trade_id == trade.trade_id
    assert open_t.entry_price == pytest.approx(89000.0)


def test_no_duplicate_trade_id(tmp_path):
    repo = _make_repo(tmp_path)
    trade = _make_trade()
    repo.insert_trade(trade)
    repo.insert_trade(trade)  # should be ignored (INSERT OR IGNORE)
    trades = repo.list_recent_trades(ticker="SiM6")
    assert len(trades) == 1


def test_update_trade_closes(tmp_path):
    repo = _make_repo(tmp_path)
    trade = _make_trade()
    repo.insert_trade(trade)

    trade.status = PaperTradeStatus.CLOSED
    trade.exit_price = 88600.0
    trade.exit_reason = PaperExitReason.TAKE
    trade.pnl_points = 400.0
    trade.pnl_rub = 4000.0
    trade.bars_held = 5
    repo.update_trade(trade)

    open_t = repo.get_open_trade("SiM6", "1m", "balanced", "SELL")
    assert open_t is None

    all_trades = repo.list_recent_trades(ticker="SiM6")
    assert len(all_trades) == 1
    assert all_trades[0].status == PaperTradeStatus.CLOSED
    assert all_trades[0].exit_reason == PaperExitReason.TAKE


def test_insert_event(tmp_path):
    repo = _make_repo(tmp_path)
    repo.insert_event("evt-1", "SiM6", "ENTRY", "trade opened", {"price": 89000})
    # no error = pass


def test_list_recent_trades_limit(tmp_path):
    repo = _make_repo(tmp_path)
    for i in range(5):
        t = _make_trade(trade_id=f"paper:SiM6:1m:balanced:SELL:2026-01-0{i+1}T10:00:00")
        repo.insert_trade(t)
    trades = repo.list_recent_trades(ticker="SiM6", limit=3)
    assert len(trades) == 3
