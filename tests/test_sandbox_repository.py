"""Tests for src/sandbox/repository.py (MVP-L1a)."""
from datetime import datetime, timezone

from src.sandbox.models import (
    SandboxExitReason,
    SandboxFill,
    SandboxOrder,
    SandboxOrderStatus,
    SandboxPosition,
    SandboxTrade,
    SandboxTradeStatus,
)
from src.sandbox.repository import SandboxRepository


def _repo(tmp_path):
    repo = SandboxRepository(str(tmp_path / "sandbox_state.sqlite"))
    repo.init_db()
    return repo


def _now():
    return datetime.now(tz=timezone.utc)


def test_init_db_creates_tables(tmp_path):
    repo = _repo(tmp_path)
    with repo._connect() as conn:
        tables = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    expected = {
        "sandbox_state", "sandbox_orders", "sandbox_fills", "sandbox_positions",
        "sandbox_trades", "sandbox_events", "sandbox_daily_risk",
    }
    assert expected.issubset(tables)


def test_insert_and_get_order(tmp_path):
    repo = _repo(tmp_path)
    order = SandboxOrder(
        order_id="order-1", signal_id="sig-1", strategy="hammer_maxhold5",
        ticker="SiU6", figi="FUTSI", instrument_uid="uid-1",
        direction="SELL", order_side="SELL", order_type="MARKET",
        requested_qty=1, requested_price=None, submitted_at=_now(),
        status=SandboxOrderStatus.NEW,
    )
    repo.insert_order(order)

    fetched = repo.get_order("order-1")
    assert fetched is not None
    assert fetched.ticker == "SiU6"
    assert fetched.status == SandboxOrderStatus.NEW
    assert fetched.filled_qty == 0

    fetched.status = SandboxOrderStatus.FILLED
    fetched.filled_qty = 1
    fetched.avg_fill_price = 73000.0
    fetched.commission_rub = 0.5
    repo.update_order(fetched)

    refetched = repo.get_order("order-1")
    assert refetched.status == SandboxOrderStatus.FILLED
    assert refetched.filled_qty == 1
    assert refetched.avg_fill_price == 73000.0


def test_insert_and_list_fills(tmp_path):
    repo = _repo(tmp_path)
    fill = SandboxFill(
        fill_id="fill-1", order_id="order-1", ticker="SiU6", direction="SELL",
        qty=1, price=73000.0, commission_rub=0.5, fill_time=_now(),
    )
    repo.insert_fill(fill)

    fills = repo.list_fills(order_id="order-1")
    assert len(fills) == 1
    assert fills[0].fill_id == "fill-1"
    assert fills[0].price == 73000.0


def test_upsert_and_get_position(tmp_path):
    repo = _repo(tmp_path)
    pos = SandboxPosition(
        ticker="SiU6", figi="FUTSI", instrument_uid="uid-1",
        direction="SHORT", qty=1, avg_price=73000.0,
    )
    repo.upsert_position(pos)

    fetched = repo.get_position("SiU6")
    assert fetched is not None
    assert fetched.direction == "SHORT"
    assert fetched.qty == 1

    flat = SandboxPosition(
        ticker="SiU6", figi="FUTSI", instrument_uid="uid-1",
        direction="FLAT", qty=0, avg_price=None,
    )
    repo.upsert_position(flat)
    refetched = repo.get_position("SiU6")
    assert refetched.direction == "FLAT"
    assert refetched.qty == 0


def test_insert_update_and_get_open_trade(tmp_path):
    repo = _repo(tmp_path)
    trade = SandboxTrade(
        trade_id="trade-1", signal_id="sig-1", entry_order_id="order-1", exit_order_id=None,
        ticker="SiU6", direction="SELL", qty=1,
        entry_time=_now(), entry_price=73000.0, stop_price=73100.0, take_price=72900.0,
        status=SandboxTradeStatus.OPEN,
    )
    repo.insert_trade(trade)

    open_trade = repo.get_open_trade("SiU6")
    assert open_trade is not None
    assert open_trade.trade_id == "trade-1"

    open_trade.status = SandboxTradeStatus.CLOSED
    open_trade.exit_order_id = "order-2"
    open_trade.exit_time = _now()
    open_trade.exit_price = 72900.0
    open_trade.exit_reason = SandboxExitReason.TAKE
    open_trade.gross_pnl_rub = 1000.0
    open_trade.commission_rub = 1.0
    open_trade.net_pnl_rub = 999.0
    open_trade.bars_held = 3
    repo.update_trade(open_trade)

    assert repo.get_open_trade("SiU6") is None
    all_trades = repo.list_trades("SiU6")
    assert len(all_trades) == 1
    assert all_trades[0].status == SandboxTradeStatus.CLOSED
    assert all_trades[0].exit_reason == SandboxExitReason.TAKE
    assert all_trades[0].net_pnl_rub == 999.0


def test_events_and_state(tmp_path):
    repo = _repo(tmp_path)
    repo.insert_event("evt-1", "SiU6", "ENTRY", "Sandbox order submitted", payload={"qty": 1})
    events = repo.list_events()
    assert len(events) == 1
    assert events[0].event_type == "ENTRY"

    repo.set_state("foo", "bar")
    assert repo.get_state("foo") == "bar"
    assert repo.get_state("missing") is None


def test_risk_state_roundtrip(tmp_path):
    from src.sandbox.models import SandboxRiskState
    repo = _repo(tmp_path)

    default = repo.load_risk_state()
    assert default.total_pnl_rub == 0.0
    assert default.trading_paused is False

    state = SandboxRiskState(
        total_pnl_rub=-500.0, consecutive_errors=1, consecutive_losses=2,
        trading_paused=True, trading_paused_reason="max_consecutive_losses",
        reconciliation_status="OK",
    )
    repo.save_risk_state(state)

    loaded = repo.load_risk_state()
    assert loaded.total_pnl_rub == -500.0
    assert loaded.trading_paused is True
    assert loaded.trading_paused_reason == "max_consecutive_losses"


def test_daily_risk_roundtrip(tmp_path):
    from src.sandbox.models import SandboxDailyRisk
    repo = _repo(tmp_path)

    empty = repo.load_daily_risk("2026-06-11")
    assert empty.trades_today == 0

    daily = SandboxDailyRisk(
        date_msk="2026-06-11", trades_today=2, realized_pnl_rub=-100.0,
        consecutive_losses=1, daily_loss_breached=False,
    )
    repo.save_daily_risk(daily)

    loaded = repo.load_daily_risk("2026-06-11")
    assert loaded.trades_today == 2
    assert loaded.realized_pnl_rub == -100.0


def test_export_orders_and_trades_csv(tmp_path):
    repo = _repo(tmp_path)
    order = SandboxOrder(
        order_id="order-1", signal_id="sig-1", strategy="hammer_maxhold5",
        ticker="SiU6", figi="FUTSI", instrument_uid="uid-1",
        direction="SELL", order_side="SELL", order_type="MARKET",
        requested_qty=1, requested_price=None, submitted_at=_now(),
        status=SandboxOrderStatus.FILLED, filled_qty=1, avg_fill_price=73000.0,
    )
    repo.insert_order(order)

    trade = SandboxTrade(
        trade_id="trade-1", signal_id="sig-1", entry_order_id="order-1", exit_order_id=None,
        ticker="SiU6", direction="SELL", qty=1,
        entry_time=_now(), entry_price=73000.0, stop_price=73100.0, take_price=72900.0,
        status=SandboxTradeStatus.OPEN,
    )
    repo.insert_trade(trade)

    orders_csv = tmp_path / "orders.csv"
    trades_csv = tmp_path / "trades.csv"
    repo.export_orders_csv(str(orders_csv))
    repo.export_trades_csv(str(trades_csv))

    assert orders_csv.exists()
    assert trades_csv.exists()
    assert "order-1" in orders_csv.read_text()
    assert "trade-1" in trades_csv.read_text()


def test_repository_creates_parent_dir(tmp_path):
    nested = tmp_path / "nested" / "dir" / "sandbox.sqlite"
    repo = SandboxRepository(str(nested))
    repo.init_db()
    assert nested.parent.exists()
