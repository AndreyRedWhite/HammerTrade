"""Tests for research runner and backtest pipeline (Part G, 3 tests)."""
from __future__ import annotations

import pytest
import pandas as pd
import pytz
from datetime import datetime, timedelta

from src.strategies.opening_range_breakout.backtest import run_orb_backtest
from src.research.reports import build_orb_markdown_report

MSK = pytz.timezone("Europe/Moscow")
UTC = pytz.utc


def make_synthetic_candles(n_days: int = 3) -> pd.DataFrame:
    """Build synthetic 1m candles for multiple days with clear ORB setups."""
    candles = []
    base_day = datetime(2026, 1, 20, 7, 0, 0, tzinfo=UTC)  # 10:00 MSK

    for d in range(n_days):
        day_start = base_day + timedelta(days=d)

        # OR candles 10:00-10:14 MSK (07:00-07:14 UTC)
        for m in range(15):
            dt = day_start + timedelta(minutes=m)
            candles.append({
                "timestamp": pd.Timestamp(dt),
                "open": 82500.0, "high": 82510.0, "low": 82490.0,
                "close": 82500.0, "volume": 100,
            })

        # Post-OR candles 10:15+ MSK — strong upward breakout on bar 3+
        for m in range(15, 15 + 60):
            dt = day_start + timedelta(minutes=m)
            if m >= 15 + 2:  # after false breakout filter
                h = 82600.0  # breaks OR high 82510
                l = 82480.0
            else:
                h = 82511.0
                l = 82490.0
            candles.append({
                "timestamp": pd.Timestamp(dt),
                "open": 82500.0, "high": h, "low": l,
                "close": 82510.0, "volume": 100,
            })

        # Fill until 18:40 MSK (15:40 UTC) — remaining session
        for m in range(75, 75 + 430):
            dt = day_start + timedelta(minutes=m)
            candles.append({
                "timestamp": pd.Timestamp(dt),
                "open": 82510.0, "high": 82520.0, "low": 82500.0,
                "close": 82510.0, "volume": 50,
            })

    return pd.DataFrame(candles)


MINIMAL_CONFIG = {
    "experiment": {"name": "test_orb", "ticker": "SiM6", "timeframe": "1m"},
    "data": {"candles_csv": "test"},
    "opening_ranges": [["10:00", "10:15"]],
    "directions": ["long"],
    "take": {"r": [1.5]},
    "entry": {"min_false_breakout_bars": 2},
    "stop": {"min_range_points": 5.0},
    "exit": {"time_exit": "18:40"},
    # Real Si economics: 1.0 RUB/point (not 10.0), ~38 RUB round trip (not 0.05).
    "commission": {"rub_per_trade": 38.0, "point_value_rub": 1.0},
    "regime": {"enabled": False},
}


def test_orb_backtest_rejects_config_without_costs():
    """A config that does not state its costs must fail, not trade at ~zero cost."""
    candles = make_synthetic_candles(2)
    cfg = {k: v for k, v in MINIMAL_CONFIG.items() if k != "commission"}
    with pytest.raises(ValueError, match="commission.rub_per_trade"):
        run_orb_backtest(candles, cfg)

    partial = dict(MINIMAL_CONFIG, commission={"rub_per_trade": 38.0})
    with pytest.raises(ValueError, match="point_value_rub"):
        run_orb_backtest(candles, partial)


def test_orb_backtest_config_costs_actually_reach_pnl():
    """REGRESSION: the config's costs must change the PnL.

    They used to be read into local variables in backtest.py and never passed to
    simulate_trade(), which fell back to module constants — so a config setting
    the correct 38.0 / 1.0 produced exactly the same (wrong) numbers as one
    setting 0.05 / 10.0. The study looked controlled and was not.
    """
    candles = make_synthetic_candles(2)

    cheap = dict(MINIMAL_CONFIG, commission={"rub_per_trade": 0.05, "point_value_rub": 10.0})
    real = dict(MINIMAL_CONFIG, commission={"rub_per_trade": 38.0, "point_value_rub": 1.0})

    _, cheap_trades = run_orb_backtest(candles, cheap)
    _, real_trades = run_orb_backtest(candles, real)

    assert cheap_trades and real_trades
    assert len(cheap_trades) == len(real_trades)

    # Same price path, same points; only the money differs.
    for c, r in zip(cheap_trades, real_trades):
        assert c["pnl_points"] == r["pnl_points"]
        assert c["pnl_rub"] == pytest.approx(c["pnl_points"] * 10.0 - 0.05)
        assert r["pnl_rub"] == pytest.approx(r["pnl_points"] * 1.0 - 38.0)

    # And the difference is not cosmetic: the same price path reports different money.
    # (The 10x point value scales magnitude in both directions, so this asserts a
    # material gap rather than a sign — on a winning path it inflates the profit.)
    cheap_total = sum(t["pnl_rub"] for t in cheap_trades)
    real_total = sum(t["pnl_rub"] for t in real_trades)
    assert cheap_total != pytest.approx(real_total)


def test_orb_backtest_returns_results():
    """run_orb_backtest on minimal synthetic data returns non-empty scenario results."""
    candles = make_synthetic_candles(n_days=3)
    scenario_results, all_trades = run_orb_backtest(candles, MINIMAL_CONFIG)

    assert len(scenario_results) >= 1, "Expected at least one scenario result"
    result = scenario_results[0]
    assert "trades" in result
    assert "profit_factor" in result
    assert "net_pnl" in result
    assert result["trades"] >= 0


def test_orb_backtest_empty_candles():
    """Empty candles DataFrame returns zero trades and no crash."""
    empty_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    scenario_results, all_trades = run_orb_backtest(empty_df, MINIMAL_CONFIG)

    assert scenario_results == [] or all(r["trades"] == 0 for r in scenario_results)
    assert all_trades == []


def test_report_generation_non_empty():
    """Report generation from scenario results produces non-empty markdown string."""
    candles = make_synthetic_candles(n_days=3)
    scenario_results, all_trades = run_orb_backtest(candles, MINIMAL_CONFIG)

    report = build_orb_markdown_report(scenario_results, all_trades, MINIMAL_CONFIG)

    assert isinstance(report, str)
    assert len(report) > 100, "Report should be non-trivially long"
    assert "ORB Research Report" in report
    assert "Цель" in report
    assert "Ограничения" in report
