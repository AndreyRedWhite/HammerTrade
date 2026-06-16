"""Tests for scripts/sandbox_diagnostics.py (MVP-L1a).

Covers: drawdown computation, report rendering with no data / with trades,
and the main() entrypoint for both the "no DB yet" and "DB with data" cases.
Must never crash when no sandbox trades exist yet.
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import scripts.sandbox_diagnostics as m
from src.sandbox.models import (
    SandboxDailyRisk,
    SandboxExitReason,
    SandboxOrder,
    SandboxOrderStatus,
    SandboxPosition,
    SandboxRiskState,
    SandboxTrade,
    SandboxTradeStatus,
)
from src.sandbox.repository import SandboxRepository


def _trade(trade_id, status, net_pnl=None, exit_reason=None, entry_time=None):
    return SandboxTrade(
        trade_id=trade_id,
        signal_id=f"sig-{trade_id}",
        entry_order_id=f"order-{trade_id}-entry",
        exit_order_id=f"order-{trade_id}-exit" if status == SandboxTradeStatus.CLOSED else None,
        ticker="SiU6",
        direction="SELL",
        qty=1,
        entry_time=entry_time or datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc),
        entry_price=100.0,
        stop_price=105.0,
        take_price=95.0,
        status=status,
        exit_time=datetime(2026, 6, 11, 10, 30, tzinfo=timezone.utc) if status == SandboxTradeStatus.CLOSED else None,
        exit_price=95.0 if status == SandboxTradeStatus.CLOSED else None,
        exit_reason=exit_reason,
        gross_pnl_rub=net_pnl,
        commission_rub=0.0,
        net_pnl_rub=net_pnl,
        bars_held=3,
    )


def _order(order_id, status):
    return SandboxOrder(
        order_id=order_id,
        signal_id="sig-1",
        strategy="hammer_maxhold5",
        ticker="SiU6",
        figi="FUTSI0625000",
        instrument_uid="uid-1",
        direction="SELL",
        order_side="SELL",
        order_type="MARKET",
        requested_qty=1,
        requested_price=None,
        submitted_at=datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc),
        status=status,
    )


# ── _compute_drawdown ────────────────────────────────────────────────────────

def test_compute_drawdown_empty():
    assert m._compute_drawdown([]) == 0.0


def test_compute_drawdown_sequence():
    trades = [
        _trade("t1", SandboxTradeStatus.CLOSED, net_pnl=100, entry_time=datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc)),
        _trade("t2", SandboxTradeStatus.CLOSED, net_pnl=-150, entry_time=datetime(2026, 6, 11, 11, 0, tzinfo=timezone.utc)),
        _trade("t3", SandboxTradeStatus.CLOSED, net_pnl=20, entry_time=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)),
    ]
    assert m._compute_drawdown(trades) == 150


# ── build_diagnostics_report: no data ───────────────────────────────────────

def test_build_report_no_data_does_not_crash():
    report = m.build_diagnostics_report(
        trades=[],
        orders=[],
        events=[],
        position=None,
        risk_state=SandboxRiskState(),
        daily_risk_today=SandboxDailyRisk(date_msk="2026-06-11"),
        ticker="SiU6",
        experiment_name="sandbox_hammer_maxhold5",
        db_path="data/sandbox/sandbox_state_hammer_maxhold5_siu6.sqlite",
    )

    assert "| Closed trades | 0 |" in report
    assert "| Open trades | 0 |" in report
    assert "_no orders yet_" in report
    assert "_no closed trades yet_" in report
    assert "_No position recorded yet (FLAT)._" in report
    assert "_No events recorded yet._" in report
    assert "LOW_SAMPLE" in report


# ── build_diagnostics_report: with trades ───────────────────────────────────

def test_build_report_with_trades_computes_summary():
    trades = [
        _trade("t1", SandboxTradeStatus.CLOSED, net_pnl=100.0, exit_reason=SandboxExitReason.TAKE,
               entry_time=datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc)),
        _trade("t2", SandboxTradeStatus.CLOSED, net_pnl=-30.0, exit_reason=SandboxExitReason.STOP,
               entry_time=datetime(2026, 6, 11, 11, 0, tzinfo=timezone.utc)),
        _trade("t3", SandboxTradeStatus.OPEN, entry_time=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)),
    ]
    orders = [_order("o1", SandboxOrderStatus.FILLED), _order("o2", SandboxOrderStatus.ERROR)]
    position = SandboxPosition(
        ticker="SiU6", figi="FUTSI0625000", instrument_uid="uid-1",
        direction="FLAT", qty=0, avg_price=None,
        updated_at=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc),
    )

    report = m.build_diagnostics_report(
        trades=trades,
        orders=orders,
        events=[],
        position=position,
        risk_state=SandboxRiskState(),
        daily_risk_today=SandboxDailyRisk(date_msk="2026-06-11"),
        ticker="SiU6",
        experiment_name="sandbox_hammer_maxhold5",
        db_path="data/sandbox/sandbox_state_hammer_maxhold5_siu6.sqlite",
    )

    assert "| Closed trades | 2 |" in report
    assert "| Open trades | 1 |" in report
    assert "| Wins | 1 |" in report
    assert "| Losses | 1 |" in report
    assert "| Winrate | 50.0% |" in report
    assert "| Net PnL, RUB | +70.00 |" in report
    assert "| Profit factor | 3.333 |" in report
    assert "| Max drawdown, RUB | 30.00 |" in report
    assert "| ERROR | 1 |" in report
    assert "| FILLED | 1 |" in report
    assert "| STOP | 1 |" in report
    assert "| TAKE | 1 |" in report
    assert "| Direction | FLAT |" in report
    assert "LOW_SAMPLE" in report


def test_build_report_infinite_profit_factor_when_no_losses():
    trades = [_trade("t1", SandboxTradeStatus.CLOSED, net_pnl=100.0, exit_reason=SandboxExitReason.TAKE)]
    report = m.build_diagnostics_report(
        trades=trades, orders=[], events=[], position=None,
        risk_state=SandboxRiskState(), daily_risk_today=SandboxDailyRisk(date_msk="2026-06-11"),
        ticker="SiU6", experiment_name="sandbox_hammer_maxhold5", db_path="x.sqlite",
    )
    assert "| Profit factor | ∞ |" in report


# ── main(): no DB yet ────────────────────────────────────────────────────────

def test_main_no_db_writes_minimal_report(tmp_path, monkeypatch):
    db_path = tmp_path / "does_not_exist.sqlite"
    out_md = tmp_path / "report.md"
    out_csv = tmp_path / "report.csv"

    monkeypatch.setattr(sys, "argv", [
        "sandbox_diagnostics.py",
        "--state-db", str(db_path),
        "--ticker", "SiU6",
        "--output", str(out_md),
        "--out-csv", str(out_csv),
    ])

    rc = m.main()

    assert rc == 0
    assert not db_path.exists()
    assert "No data yet" in out_md.read_text()

    with open(out_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows == [m._TRADE_CSV_FIELDS]


# ── main(): DB with data ─────────────────────────────────────────────────────

def test_main_with_data_writes_full_report_and_csv(tmp_path, monkeypatch):
    db_path = tmp_path / "sandbox_state.sqlite"
    out_md = tmp_path / "report.md"
    out_csv = tmp_path / "report.csv"

    repo = SandboxRepository(str(db_path))
    repo.init_db()
    repo.insert_trade(_trade(
        "t1", SandboxTradeStatus.CLOSED, net_pnl=100.0, exit_reason=SandboxExitReason.TAKE,
        entry_time=datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc),
    ))
    repo.insert_order(_order("o1", SandboxOrderStatus.FILLED))
    repo.insert_event(event_id="e1", ticker="SiU6", event_type="ENTRY", message="entry filled")
    repo.upsert_position(SandboxPosition(
        ticker="SiU6", figi="FUTSI0625000", instrument_uid="uid-1",
        direction="FLAT", qty=0, avg_price=None,
    ))

    monkeypatch.setattr(sys, "argv", [
        "sandbox_diagnostics.py",
        "--state-db", str(db_path),
        "--ticker", "SiU6",
        "--output", str(out_md),
        "--out-csv", str(out_csv),
    ])

    rc = m.main()

    assert rc == 0
    report = out_md.read_text()
    assert "| Closed trades | 1 |" in report
    assert "| Net PnL, RUB | +100.00 |" in report
    assert "| Direction | FLAT |" in report
    assert "ENTRY" in report

    with open(out_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["trade_id"] == "t1"
