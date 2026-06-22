"""Tests for portfolio / exposure analytics."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.reporting.portfolio import (
    analyze, asset_class, daily_matrix, norm_direction,
)

BASE = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)


def _trade(day, pnl):
    return SimpleNamespace(exit_ts=BASE + timedelta(days=day), pnl_rub=pnl, direction="")


def _report(unit, instr, direction, trades):
    return SimpleNamespace(
        svc=SimpleNamespace(unit=f"hammertrade-{unit}.service", instrument=instr,
                            direction=direction, family="hammer"),
        trades=trades,
    )


def test_norm_direction():
    assert norm_direction("SELL") == "SHORT"
    assert norm_direction("BUY") == "LONG"
    assert norm_direction("SHORT_SPREAD") == "SHORT"
    assert norm_direction("NEUTRAL") == "NEUTRAL"


def test_asset_class():
    assert asset_class("SiU6") == "FX/RUB"
    assert asset_class("EuU6") == "FX/RUB"
    assert asset_class("BRQ6") == "Oil"
    assert asset_class("LKOH") == "Equity"
    assert asset_class("ZZZ") == "Other"


def test_daily_matrix_buckets_by_date():
    r = _report("a", "SiU6", "SELL", [_trade(0, 100), _trade(0, 50), _trade(1, -20)])
    dates, mat = daily_matrix([r])
    assert len(dates) == 2
    assert mat["a"][dates[0]] == 150.0
    assert mat["a"][dates[1]] == -20.0


def test_portfolio_totals_and_return_share():
    a = _report("a", "SiU6", "SELL", [_trade(i, 100) for i in range(5)])  # +500
    b = _report("b", "EuU6", "SELL", [_trade(i, -50) for i in range(5)])  # -250
    pr = analyze([a, b])
    assert pr.total_pnl == 250.0
    rc = {c.unit: c for c in pr.contributions}
    assert rc["a"].return_pct == 200.0   # 500/250
    assert rc["b"].return_pct == -100.0  # -250/250


def test_correlation_identical_series():
    a = _report("a", "SiU6", "SELL", [_trade(i, (i % 3) * 10 + 5) for i in range(6)])
    b = _report("b", "EuU6", "SELL", [_trade(i, (i % 3) * 10 + 5) for i in range(6)])
    pr = analyze([a, b])
    # both included, perfectly correlated → a pair ~ +1.0
    pairs = {(x, y): c for x, y, c in pr.corr_pairs}
    assert any(abs(c - 1.0) < 0.01 for c in pairs.values())


def test_low_data_excluded_from_risk():
    a = _report("a", "SiU6", "SELL", [_trade(i, 100) for i in range(6)])
    small = _report("s", "GDU6", "BUY", [_trade(0, 10)])  # 1 trade-day < 4
    pr = analyze([a, small])
    rc = {c.unit: c for c in pr.contributions}
    assert rc["s"].risk_pct is None
    assert "s" in pr.excluded_low_data


def test_exposure_by_direction_and_overload_flag():
    # 3 SHORT strategies on FX/RUB, 0 long → overload flags
    reps = [_report(f"s{i}", "SiU6", "SELL", [_trade(j, 100) for j in range(5)]) for i in range(3)]
    pr = analyze(reps)
    assert "SHORT" in pr.by_direction
    assert pr.by_direction["SHORT"]["n"] == 3
    assert "FX/RUB" in pr.by_asset_class
    assert any("one market" in f or "FX/RUB" in f for f in pr.overload_flags)


def test_empty_reports():
    pr = analyze([])
    assert pr.n_strategies == 0
    assert pr.total_pnl == 0.0
    assert pr.equity_curve == []
