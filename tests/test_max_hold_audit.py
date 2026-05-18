"""Tests for src/backtest/max_hold_audit.py (MVP-2.0a)."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from src.backtest.max_hold_audit import (
    CHANGED_EXIT,
    CUT_WINNER,
    SAME_RESULT,
    SAVED_STOP,
    SMALLER_LOSS,
    SMALLER_WIN,
    UNLOCKED_SIGNAL,
    UNMATCHED_BASELINE,
    AuditFindings,
    _classify_pair,
    build_audit_report,
    check_exit_priority,
    check_look_ahead_bias,
    check_paper_readiness,
    compute_exit_distribution,
    compute_period_stats,
    determine_verdict,
    load_scenario_trades,
    load_summary,
    match_trades,
)


# ─────────────────────────────── helpers ─────────────────────────────────────

def _make_trades_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "scenario_name": "baseline",
        "status": "closed",
        "signal_time": "2026-01-15 10:00:00+00:00",
        "entry_time": "2026-01-15 10:01:00+00:00",
        "exit_time": "2026-01-15 10:05:00+00:00",
        "entry_price": 100.0,
        "exit_price": 95.0,
        "exit_reason": "take",
        "net_pnl_rub": 50.0,
        "bars_held": 4,
        "stop_price": 105.0,
    }
    records = []
    for r in rows:
        rec = defaults.copy()
        rec.update(r)
        records.append(rec)
    return pd.DataFrame(records)


def _write_trades_csv(df: pd.DataFrame, tmp_path: Path, filename: str = "trades.csv") -> str:
    p = tmp_path / filename
    df.to_csv(str(p), index=False)
    return str(p)


def _write_summary_csv(rows: list[dict], tmp_path: Path) -> str:
    p = tmp_path / "summary.csv"
    pd.DataFrame(rows).to_csv(str(p), index=False)
    return str(p)


# ─────────────────────────────── test: _classify_pair ────────────────────────

def test_classify_same_result():
    c = _classify_pair(100.0, "take", 100.0, "take")
    assert c == SAME_RESULT


def test_classify_same_result_near_threshold():
    c = _classify_pair(100.0, "take", 100.5, "take")
    assert c == SAME_RESULT


def test_classify_saved_stop():
    c = _classify_pair(-500.0, "stop", -200.0, "timeout")
    assert c == SAVED_STOP


def test_classify_cut_winner():
    c = _classify_pair(300.0, "take", 150.0, "timeout")
    assert c == CUT_WINNER


def test_classify_smaller_win():
    c = _classify_pair(200.0, "take", 100.0, "take")
    assert c == SMALLER_WIN


def test_classify_unlocked_signal():
    c = _classify_pair(None, None, 50.0, "take")
    assert c == UNLOCKED_SIGNAL


def test_classify_unmatched_baseline():
    c = _classify_pair(200.0, "take", None, None)
    assert c == UNMATCHED_BASELINE


def test_classify_smaller_loss():
    c = _classify_pair(-300.0, "stop", -100.0, "stop")
    assert c == SMALLER_LOSS


def test_classify_changed_exit():
    # stop → take with large PnL swing — falls into CHANGED_EXIT
    c = _classify_pair(-300.0, "stop", 200.0, "take")
    assert c == CHANGED_EXIT


# ─────────────────────────────── test: match_trades ──────────────────────────

def test_match_trades_same_signals():
    base = _make_trades_df([
        {"signal_time": "2026-01-15 10:00:00+00:00", "net_pnl_rub": 100.0, "exit_reason": "take"},
        {"signal_time": "2026-01-16 11:00:00+00:00", "net_pnl_rub": -200.0, "exit_reason": "stop"},
    ])
    scen = _make_trades_df([
        {"signal_time": "2026-01-15 10:00:00+00:00", "net_pnl_rub": 100.0, "exit_reason": "take",
         "scenario_name": "max_hold_3"},
        {"signal_time": "2026-01-16 11:00:00+00:00", "net_pnl_rub": -50.0, "exit_reason": "timeout",
         "scenario_name": "max_hold_3"},
    ])
    result = match_trades(base, scen, "max_hold_3")
    assert len(result) == 2
    classes = result["classification"].tolist()
    assert SAME_RESULT in classes
    assert SAVED_STOP in classes


def test_match_trades_unlocked_signal():
    base_skipped = _make_trades_df([
        {"signal_time": "2026-01-17 09:00:00+00:00", "status": "skipped_overlap",
         "net_pnl_rub": 0.0, "exit_reason": ""},
    ])
    base_closed = _make_trades_df([
        {"signal_time": "2026-01-15 10:00:00+00:00"},
    ])
    base = pd.concat([base_closed, base_skipped], ignore_index=True)

    scen = _make_trades_df([
        {"signal_time": "2026-01-15 10:00:00+00:00", "scenario_name": "max_hold_3"},
        {"signal_time": "2026-01-17 09:00:00+00:00", "net_pnl_rub": 49.95,
         "exit_reason": "take", "scenario_name": "max_hold_3"},
    ])
    result = match_trades(base, scen, "max_hold_3")
    classes = result["classification"].tolist()
    assert UNLOCKED_SIGNAL in classes


# ─────────────────────────────── test: exit distribution ─────────────────────

def test_exit_distribution_counts():
    df = _make_trades_df([
        {"exit_reason": "take", "net_pnl_rub": 100.0},
        {"exit_reason": "take", "net_pnl_rub": 150.0},
        {"exit_reason": "stop", "net_pnl_rub": -200.0},
        {"exit_reason": "timeout", "net_pnl_rub": 20.0},
    ])
    dist = compute_exit_distribution(df)
    assert len(dist) == 3
    take_row = dist[dist["exit_reason"] == "take"].iloc[0]
    assert take_row["trades"] == 2
    assert abs(take_row["net_pnl_rub"] - 250.0) < 0.01
    assert take_row["winrate_pct"] == 100.0


def test_exit_distribution_empty():
    df = pd.DataFrame(columns=["status", "exit_reason", "net_pnl_rub"])
    dist = compute_exit_distribution(df)
    assert len(dist) == 0


# ─────────────────────────────── test: period stats ──────────────────────────

def test_period_stats_by_month():
    df = _make_trades_df([
        {"signal_time": "2026-01-15 10:00:00+00:00", "net_pnl_rub": 100.0},
        {"signal_time": "2026-01-20 10:00:00+00:00", "net_pnl_rub": 200.0},
        {"signal_time": "2026-02-10 10:00:00+00:00", "net_pnl_rub": -50.0},
    ])
    stats = compute_period_stats(df, "month")
    assert "2026-01" in stats["period"].values
    assert "2026-02" in stats["period"].values
    jan = stats[stats["period"] == "2026-01"].iloc[0]
    assert jan["trades"] == 2
    assert jan["wins"] == 2


# ─────────────────────────────── test: static audits ─────────────────────────

def test_look_ahead_bias_verdict():
    result = check_look_ahead_bias()
    assert result["verdict"] == "PASS"
    assert len(result["notes"]) > 0


def test_exit_priority_verdict():
    result = check_exit_priority()
    assert result["verdict"] == "PASS"
    assert len(result["notes"]) >= 4


def test_paper_readiness_verdict():
    result = check_paper_readiness()
    assert result["verdict"] == "READY_WITH_WARNINGS"
    assert len(result["notes"]) > 0
    assert "warnings" in result
    assert len(result["warnings"]) > 0


# ─────────────────────────────── test: loaders ───────────────────────────────

def test_load_scenario_trades(tmp_path):
    df = _make_trades_df([
        {"scenario_name": "baseline"},
        {"scenario_name": "max_hold_3"},
    ])
    csv_path = _write_trades_csv(df, tmp_path)
    result = load_scenario_trades(csv_path, "baseline")
    assert len(result) == 1
    assert result.iloc[0]["scenario_name"] == "baseline"


def test_load_summary_found(tmp_path):
    rows = [
        {"scenario_name": "baseline", "trades": 113, "profit_factor": 4.0},
        {"scenario_name": "max_hold_3", "trades": 114, "profit_factor": 14.8},
    ]
    csv_path = _write_summary_csv(rows, tmp_path)
    result = load_summary(csv_path, "baseline")
    assert result is not None
    assert result["trades"] == 113


def test_load_summary_not_found(tmp_path):
    rows = [{"scenario_name": "baseline", "trades": 113}]
    csv_path = _write_summary_csv(rows, tmp_path)
    result = load_summary(csv_path, "nonexistent_scenario")
    assert result is None


# ─────────────────────────────── test: verdict ───────────────────────────────

def test_verdict_fail_look_ahead():
    f = AuditFindings()
    f.look_ahead_verdict = "FAIL"
    f.trade_count_explained = True
    assert determine_verdict(f) == "FAIL"


def test_verdict_fail_unexplained_trades():
    f = AuditFindings()
    f.trade_count_explained = False
    assert determine_verdict(f) == "FAIL"


def test_verdict_pass_with_warnings_oos():
    f = AuditFindings()
    f.trade_count_explained = True
    f.oos_verdict = "PASS_WITH_WARNINGS"
    assert determine_verdict(f) == "PASS_WITH_WARNINGS"


def test_verdict_pass():
    f = AuditFindings()
    f.trade_count_explained = True
    f.paper_readiness = "READY"
    f.period_stable = True
    f.oos_verdict = "PASS"
    f.slippage_verdict = "PASS"
    assert determine_verdict(f) == "PASS"


# ─────────────────────────────── test: report generation ─────────────────────

def test_report_generation_no_crash():
    baseline_summary = {
        "scenario_name": "baseline",
        "trades": 113, "winrate_pct": 82.3,
        "net_pnl_rub": 21024.0, "profit_factor": 4.007,
        "max_drawdown_rub": 1250.0,
    }
    mh3_summary = {
        "scenario_name": "max_hold_3",
        "trades": 114, "winrate_pct": 67.5,
        "net_pnl_rub": 22684.0, "profit_factor": 14.826,
        "max_drawdown_rub": 340.0,
    }
    mh5_summary = {
        "scenario_name": "max_hold_5",
        "trades": 114, "winrate_pct": 72.0,
        "net_pnl_rub": 22624.0, "profit_factor": 7.772,
        "max_drawdown_rub": 620.0,
    }
    baseline_df = _make_trades_df([{"net_pnl_rub": 100.0}])
    mh3_df = _make_trades_df([{"net_pnl_rub": 100.0, "scenario_name": "max_hold_3"}])
    mh5_df = _make_trades_df([{"net_pnl_rub": 100.0, "scenario_name": "max_hold_5"}])

    matching_mh3 = match_trades(baseline_df, mh3_df, "max_hold_3")
    matching_mh5 = match_trades(baseline_df, mh5_df, "max_hold_5")

    f = AuditFindings()
    f.trade_count_explained = True
    f.trade_count_note = "Test: trade count explained."
    f.oos_verdict = "PASS_WITH_WARNINGS"
    f.oos_notes = ["Low sample"]
    f.warnings = ["Test warning"]

    look_ahead = check_look_ahead_bias()
    exit_prio = check_exit_priority()
    paper = check_paper_readiness()
    verdict = determine_verdict(f)

    report = build_audit_report(
        baseline_summary=baseline_summary,
        mh3_summary=mh3_summary,
        mh5_summary=mh5_summary,
        baseline_df=baseline_df,
        mh3_df=mh3_df,
        mh5_df=mh5_df,
        matching_mh3=matching_mh3,
        matching_mh5=matching_mh5,
        period_stats={},
        oos_results={},
        slippage_df=pd.DataFrame(),
        look_ahead=look_ahead,
        exit_priority=exit_prio,
        paper_readiness=paper,
        findings=f,
        verdict=verdict,
        ticker="SiM6",
        direction="SELL",
    )
    assert "max_hold_bars Audit" in report
    assert "PASS_WITH_WARNINGS" in report
    assert "Recommendation" in report
