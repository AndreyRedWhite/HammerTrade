"""Tests for src/analytics/hour_filter_audit.py (MVP-2.3)."""
import math
from zoneinfo import ZoneInfo

import pytest

from src.analytics.hour_filter_audit import (
    HourStats,
    _is_big_risk,
    _is_one_bar_stop,
    _max_drawdown,
    build_csv_rows,
    build_markdown_report,
    compute_stats,
    load_historical_trades,
    msk_hour_from_str,
    run_audit,
)

_MSK = ZoneInfo("Europe/Moscow")


# ── 1. MSK hour extraction from UTC timestamp ──────────────────────────────────

def test_msk_hour_utc_noon():
    # 12:00 UTC == 15:00 MSK (UTC+3)
    ts = "2026-05-07 09:00:00+00:00"
    assert msk_hour_from_str(ts) == 12


def test_msk_hour_midnight_utc():
    ts = "2026-05-07 21:00:00+00:00"
    assert msk_hour_from_str(ts) == 0  # midnight MSK


def test_msk_hour_none_on_empty():
    assert msk_hour_from_str("") is None
    assert msk_hour_from_str(None) is None


def test_msk_hour_naive_treated_as_utc():
    # "2026-05-07 09:00:00" naive => UTC => 12 MSK
    ts = "2026-05-07 09:00:00"
    assert msk_hour_from_str(ts) == 12


# ── 2. Hour filter selects only requested hour ─────────────────────────────────

def _make_trade(hour_utc: int, pnl: float, bars: int = 1, exit_r: str = "TAKE",
                risk: float = 15.0, flags: str = "") -> dict:
    ts = f"2026-05-07 {hour_utc:02d}:00:00+00:00"
    from src.analytics.hour_filter_audit import msk_hour_from_str, _date_str_msk
    msk_h = msk_hour_from_str(ts)
    return {
        "entry_hour_msk": msk_h,
        "entry_date_msk": "2026-05-07",
        "pnl_rub": pnl,
        "exit_reason": exit_r,
        "risk_points": risk,
        "bars_held": bars,
        "diagnostic_flags": flags,
        "status": "CLOSED",
    }


def test_hour_filter_selects_hour():
    trades = [
        _make_trade(9, 100.0),   # 09 UTC = 12 MSK
        _make_trade(10, -50.0),  # 10 UTC = 13 MSK
    ]
    hour12 = [t for t in trades if t["entry_hour_msk"] == 12]
    assert len(hour12) == 1
    assert hour12[0]["pnl_rub"] == 100.0


# ── 3. Excluding hour removes only that hour ───────────────────────────────────

def test_exclude_hour_removes_correct_trades():
    # 09 UTC = 12 MSK (UTC+3), so trades at hour_utc=9 are at MSK hour 12
    trades = [_make_trade(9, 100.0), _make_trade(9, 200.0), _make_trade(10, -50.0)]
    with12 = [t for t in trades if t["entry_hour_msk"] == 12]
    assert len(with12) == 2  # two trades at 09 UTC = 12 MSK
    without = [t for t in trades if t["entry_hour_msk"] != 12]
    assert len(without) == 1  # only the 10 UTC = 13 MSK trade remains


def test_exclude_hour_via_compute_stats():
    trades = [
        _make_trade(9, 100.0),   # 12 MSK
        _make_trade(9, 200.0),   # 12 MSK
        _make_trade(10, -50.0),  # 13 MSK
    ]
    hour12_only = [t for t in trades if t["entry_hour_msk"] == 12]
    without12 = [t for t in trades if t["entry_hour_msk"] != 12]
    s = compute_stats(hour12_only, "test", "hour_12", "2026", "12")
    assert s.trades == 2
    s2 = compute_stats(without12, "test", "without_12", "2026", "without_12")
    assert s2.trades == 1
    assert s2.net_pnl == pytest.approx(-50.0)


# ── 4. PF calculation handles zero loss ───────────────────────────────────────

def test_pf_zero_loss():
    from src.analytics.hour_filter_audit import _safe_pf
    pf = _safe_pf(500.0, 0.0)
    assert math.isinf(pf)


def test_pf_zero_both():
    from src.analytics.hour_filter_audit import _safe_pf
    pf = _safe_pf(0.0, 0.0)
    assert pf == 0.0


def test_pf_normal():
    from src.analytics.hour_filter_audit import _safe_pf
    pf = _safe_pf(300.0, 100.0)
    assert pf == pytest.approx(3.0)


# ── 5. LOW_SAMPLE flag ─────────────────────────────────────────────────────────

def test_low_sample_flag_empty():
    s = compute_stats([], "test", "x", "2026", "all")
    assert s.low_sample is True
    assert s.trades == 0


def test_low_sample_flag_few():
    trades = [_make_trade(9, 10.0 * i) for i in range(1, 6)]  # 5 trades
    s = compute_stats(trades, "test", "x", "2026", "12")
    assert s.low_sample is True
    assert s.trades == 5


def test_not_low_sample_enough():
    trades = [_make_trade(9, 10.0 * i) for i in range(1, 12)]  # 11 trades
    s = compute_stats(trades, "test", "x", "2026", "12")
    assert s.low_sample is False


# ── 6. Counterfactual: without hour differs from all ──────────────────────────

def test_counterfactual_without_hour():
    trades = [
        _make_trade(9, -500.0),  # 12 MSK — big loser
        _make_trade(12, 100.0),  # 15 MSK — winner
        _make_trade(12, 200.0),  # 15 MSK — winner
    ]
    all_s = compute_stats(trades, "t", "all", "2026", "all")
    without12 = [t for t in trades if t["entry_hour_msk"] != 12]
    wo_s = compute_stats(without12, "t", "without", "2026", "without")
    assert wo_s.net_pnl > all_s.net_pnl   # counterfactual without 12MSK is better
    assert wo_s.trades == 2


# ── 7. BIG_RISK intersection via flags ────────────────────────────────────────

def test_big_risk_from_flags():
    t = {"diagnostic_flags": "BIG_RISK;ONE_BAR_TAKE", "risk_points": 10.0}
    assert _is_big_risk(t) is True


def test_big_risk_from_risk_points_no_flags():
    t = {"diagnostic_flags": "", "risk_points": 55.0}
    assert _is_big_risk(t) is True


def test_big_risk_not_big():
    t = {"diagnostic_flags": "", "risk_points": 20.0}
    assert _is_big_risk(t) is False


# ── 8. Missing flags column does not crash ────────────────────────────────────

def test_missing_flags_column():
    t = {"pnl_rub": 100.0, "exit_reason": "TAKE", "bars_held": 1, "risk_points": 15.0}
    # no "diagnostic_flags" key at all
    assert _is_big_risk(t) is False
    assert _is_one_bar_stop(t) is False


# ── 9. Empty dataset does not crash ───────────────────────────────────────────

def test_empty_run_audit():
    result = run_audit(
        audit_hour=12,
        historical_trades=[],
        paper_baseline=[],
        paper_maxhold5=[],
    )
    assert result.audit_hour == 12
    # Empty lists → SourceAudit objects exist but stats are LOW_SAMPLE / zero
    assert result.live_baseline is not None
    assert result.live_maxhold5 is not None
    assert result.historical is not None
    assert result.live_baseline.audit_hour.low_sample is True
    assert result.live_baseline.all_hours.trades == 0


# ── 10. Markdown report generation works ─────────────────────────────────────

def test_markdown_report_not_empty():
    result = run_audit(
        audit_hour=12,
        historical_trades=[],
        paper_baseline=[_make_trade(9, 100.0), _make_trade(9, -50.0)],
        paper_maxhold5=[],
    )
    md = build_markdown_report(result, generated_at="2026-05-30T00:00:00Z")
    assert "Hour 12 Targeted Audit" in md
    assert "Candidate decision" in md
    assert "Overfit risk" in md
    assert "Counterfactual" in md


def test_csv_rows_have_required_fields():
    result = run_audit(
        audit_hour=12,
        historical_trades=[_make_trade(9, 100.0)],
        paper_baseline=[_make_trade(9, -50.0)],
        paper_maxhold5=[],
    )
    rows = build_csv_rows(result)
    assert len(rows) > 0
    required = {"source", "strategy", "net_pnl", "profit_factor", "trades"}
    for row in rows:
        assert required.issubset(set(row.keys())), f"Missing fields in row: {row}"
