"""Tests for fleet report metrics + classification."""
from datetime import datetime, timedelta, timezone

from src.reporting.metrics import (
    Metrics,
    Trade,
    classify,
    compute_metrics,
    filter_window,
)

NOW = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


def _t(days_ago, pnl):
    return Trade(exit_ts=NOW - timedelta(days=days_ago), pnl_rub=pnl)


def test_empty_metrics():
    m = compute_metrics([])
    assert m.trades == 0 and m.pnl_rub == 0.0 and m.pf is None and m.wr is None


def test_basic_metrics():
    trades = [_t(1, 100), _t(2, -50), _t(3, 200), _t(4, -50)]
    m = compute_metrics(trades)
    assert m.trades == 4
    assert m.pnl_rub == 200.0
    assert m.wr == 50.0
    assert m.pf == round(300 / 100, 3)
    assert m.avg_win == 150.0
    assert m.avg_loss == -50.0


def test_pf_infinite_when_no_losses():
    m = compute_metrics([_t(1, 100), _t(2, 50)])
    assert m.pf == float("inf")
    assert m.wr == 100.0
    assert m.avg_loss is None


def test_max_drawdown():
    # cumulative: +100, +50(peak100 dd50? no), ... build a clear DD
    trades = [_t(5, 100), _t(4, 50), _t(3, -200), _t(2, 30)]
    # cum: 100 -> 150(peak) -> -50 -> -20 ; max dd = 150 - (-50) = 200
    m = compute_metrics(trades)
    assert m.max_dd_rub == 200.0


def test_filter_window():
    trades = [_t(0.5, 10), _t(2, 20), _t(10, 30)]
    daily = filter_window(trades, NOW, 1)
    weekly = filter_window(trades, NOW, 7)
    assert len(daily) == 1
    assert len(weekly) == 2


def test_classify_watch_small_sample():
    m = Metrics(trades=5, pf=3.0)
    assert classify("hammer", m, "OK") == "WATCH"


def test_classify_freeze_broken_edge():
    # hammer: PF<1.25 with >=60 trades → FREEZE
    m = Metrics(trades=70, pf=1.1, wr=50)
    assert classify("hammer", m, "OK") == "FREEZE"


def test_classify_promote_strong_edge():
    m = Metrics(trades=60, pf=1.8, wr=65)
    assert classify("hammer", m, "OK") == "PROMOTE"


def test_classify_active_middle():
    m = Metrics(trades=70, pf=1.35, wr=55)
    assert classify("hammer", m, "OK") == "ACTIVE"


def test_classify_orb_thresholds():
    # ORB freezes below 1.10 at >=30 trades
    assert classify("orb", Metrics(trades=35, pf=1.0), "OK") == "FREEZE"
    assert classify("orb", Metrics(trades=35, pf=1.45), "OK") == "PROMOTE"


def test_classify_freeze_on_none_pf_large_sample():
    # all-losing strategy → pf None with big sample → FREEZE
    assert classify("orb", Metrics(trades=40, pf=None), "OK") == "FREEZE"


def test_gross_win_loss():
    m = compute_metrics([_t(1, 100), _t(2, -40), _t(3, 60)])
    assert m.gross_win == 160.0
    assert m.gross_loss == 40.0


def test_cumulative_curve():
    from src.reporting.metrics import cumulative_curve
    c = cumulative_curve([_t(3, 100), _t(2, -30), _t(1, 50)])
    # ordered by exit_ts ascending: day3(oldest)=+100, day2=+70, day1(newest)=... 
    # exit_ts: _t(days_ago) => smaller days_ago = more recent. sorted ascending by ts
    # = day3 (oldest) -> day2 -> day1. cumulative: 100,70,120
    assert c == [100.0, 70.0, 120.0]


def test_cumulative_curve_downsample():
    from src.reporting.metrics import cumulative_curve
    trades = [_t(100 - i, 1) for i in range(100)]
    c = cumulative_curve(trades, max_points=20)
    assert len(c) == 20
