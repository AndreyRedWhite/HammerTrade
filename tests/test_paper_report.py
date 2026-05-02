from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.paper.models import PaperTrade, PaperTradeStatus, PaperExitReason
from src.paper.repository import PaperRepository
from src.paper.report import generate_paper_report


def _make_repo(tmp_path: Path) -> PaperRepository:
    repo = PaperRepository(str(tmp_path / "test.sqlite"))
    repo.init_db()
    return repo


def _closed_trade(trade_id, pnl_rub, reason=PaperExitReason.TAKE) -> PaperTrade:
    now = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    return PaperTrade(
        trade_id=trade_id,
        ticker="SiM6", class_code="SPBFUT", timeframe="1m",
        profile="balanced", direction="SELL",
        signal_timestamp=now, entry_timestamp=now,
        entry_price=89000.0, stop_price=89500.0, take_price=88000.0,
        status=PaperTradeStatus.CLOSED,
        exit_price=88000.0, exit_reason=reason,
        pnl_points=-1000.0, pnl_rub=pnl_rub,
        bars_held=3, created_at=now, updated_at=now,
        exit_timestamp=now,
    )


def test_report_created(tmp_path):
    repo = _make_repo(tmp_path)
    output = str(tmp_path / "report.md")
    generate_paper_report(repo, output)
    assert Path(output).exists()


def test_report_has_summary(tmp_path):
    repo = _make_repo(tmp_path)
    output = str(tmp_path / "report.md")
    content = generate_paper_report(repo, output)
    assert "# Paper Trading Report" in content
    assert "## Summary" in content


def test_report_metrics_calculated(tmp_path):
    repo = _make_repo(tmp_path)
    repo.insert_trade(_closed_trade("t1", 1000.0, PaperExitReason.TAKE))
    repo.insert_trade(_closed_trade("t2", -500.0, PaperExitReason.STOP))
    repo.insert_trade(_closed_trade("t3", 800.0, PaperExitReason.TAKE))

    output = str(tmp_path / "report.md")
    content = generate_paper_report(repo, output)

    assert "Closed trades" in content
    assert "Net PnL RUB" in content
    assert "1300" in content  # 1000 + 800 - 500


def test_report_shows_closed_trades_table(tmp_path):
    repo = _make_repo(tmp_path)
    repo.insert_trade(_closed_trade("t1", 1000.0))
    output = str(tmp_path / "report.md")
    content = generate_paper_report(repo, output)
    assert "Recent Closed Trades" in content
    assert "SiM6" in content


def test_report_open_trades(tmp_path):
    repo = _make_repo(tmp_path)
    now = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    open_trade = PaperTrade(
        trade_id="open-t1",
        ticker="SiM6", class_code="SPBFUT", timeframe="1m",
        profile="balanced", direction="SELL",
        signal_timestamp=now, entry_timestamp=now,
        entry_price=89000.0, stop_price=89500.0, take_price=88000.0,
        status=PaperTradeStatus.OPEN,
        bars_held=2, created_at=now, updated_at=now,
    )
    repo.insert_trade(open_trade)
    output = str(tmp_path / "report.md")
    content = generate_paper_report(repo, output)
    assert "Open Trades" in content
