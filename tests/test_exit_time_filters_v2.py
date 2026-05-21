"""Tests for MVP-2.2: Exit/Time Filters v2."""
import pandas as pd
import pytest

from src.backtest.exit_time_filters_v2 import (
    ConditionalMaxHoldConfig,
    FilterConfigV2,
    ScenarioResultV2,
    _find_exit_v2,
    _should_conditional_exit,
    compute_progress_to_take_pct,
    compute_winner_loser_analysis,
    run_backtest_v2,
    run_scenario_v2,
)
from src.backtest.exit_time_grid_v2 import (
    BacktestParamsV2,
    make_phase_a_conditional_configs,
    make_phase_a_confirmation_configs,
    make_phase_a_time_configs,
    make_phase_b_configs_v2,
    build_markdown_report_v2,
    run_all_scenarios_v2,
    make_baseline_config_v2,
)
from src.backtest.diagnostic_filters import get_msk_hour


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_candles(prices: list[float], is_signals: list[bool] | None = None) -> pd.DataFrame:
    """Create minimal debug_df with OHLC all equal to price value."""
    n = len(prices)
    if is_signals is None:
        is_signals = [False] * n
    timestamps = pd.date_range("2026-01-15 10:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": prices,
        "high": [p + 5 for p in prices],
        "low": [p - 5 for p in prices],
        "close": prices,
        "is_signal": is_signals,
        "fail_reason": ["pass" if s else "body_big" for s in is_signals],
        "direction_candidate": ["SELL" if s else "none" for s in is_signals],
        "instrument": ["SiM6"] * n,
        "timeframe": ["1m"] * n,
        "tick_size": [1.0] * n,
    })


def _make_exit_df(prices: list[float]) -> pd.DataFrame:
    """Create a simple OHLC dataframe where high=price+5, low=price-5."""
    n = len(prices)
    timestamps = pd.date_range("2026-01-15 10:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": prices,
        "high": [p + 5 for p in prices],
        "low": [p - 5 for p in prices],
        "close": prices,
    })


# ── Test 1: exclude_hour_12 skips only MSK hour 12 ───────────────────────────

def test_exclude_hour_12_skips_only_hour_12():
    """Time filter for hour 12 MSK should skip signals at 12:xx and only those."""
    # 09:00 MSK = 06:00 UTC, 12:00 MSK = 09:00 UTC
    ts_09 = pd.Timestamp("2026-01-15 06:00:00", tz="UTC")
    ts_12 = pd.Timestamp("2026-01-15 09:00:00", tz="UTC")
    ts_15 = pd.Timestamp("2026-01-15 12:00:00", tz="UTC")

    assert get_msk_hour(ts_09) == 9
    assert get_msk_hour(ts_12) == 12
    assert get_msk_hour(ts_15) == 15

    fc = FilterConfigV2(
        scenario_name="test_h12",
        direction="SELL",
        exclude_hours_msk=[12],
        time_filter_name="exclude_hour_12",
    )
    assert 12 in fc.exclude_hours_msk
    assert 9 not in fc.exclude_hours_msk
    assert 15 not in fc.exclude_hours_msk


# ── Test 2: time filter does not skip other hours ─────────────────────────────

def test_time_filter_does_not_skip_other_hours():
    """exclude_hour_12 must not affect hours 10, 11, 13, 15."""
    fc = FilterConfigV2(
        scenario_name="test_h12",
        direction="SELL",
        exclude_hours_msk=[12],
    )
    for h in [9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]:
        assert h not in fc.exclude_hours_msk, f"Hour {h} incorrectly excluded"


# ── Test 3: fixed max_hold_10 exits at bar 10, not 5 ─────────────────────────

def test_max_hold_10_exits_at_bar_10():
    """Trade should exit at bar 10 (timeout) when stop/take not hit."""
    # Entry at bar 0, then bars 1-10 don't hit stop/take
    prices = [100.0] * 15
    df = _make_exit_df(prices)

    entry_bar_idx = 0
    stop_price = 200.0   # never hit
    take_price = 0.0     # never hit (SELL take would be below entry, but low=95 > 0)

    exit_idx, exit_price, reason, bars_held = _find_exit_v2(
        df, entry_bar_idx, "SELL",
        entry_price=100.0,
        stop_price=stop_price,
        take_price=-100.0,   # unreachable
        max_hold_bars=10,
        conditional=ConditionalMaxHoldConfig(enabled=False),
    )
    assert bars_held == 10
    assert reason == "timeout"


def test_max_hold_5_exits_at_bar_5():
    prices = [100.0] * 12
    df = _make_exit_df(prices)
    exit_idx, exit_price, reason, bars_held = _find_exit_v2(
        df, 0, "SELL",
        entry_price=100.0,
        stop_price=200.0,
        take_price=-100.0,
        max_hold_bars=5,
        conditional=ConditionalMaxHoldConfig(enabled=False),
    )
    assert bars_held == 5
    assert reason == "timeout"


# ── Test 4: stop/take priority beats max_hold ────────────────────────────────

def test_stop_priority_beats_max_hold():
    """Stop at bar 3 should win over max_hold=10."""
    prices = [100.0, 100.0, 100.0, 115.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
    df = _make_exit_df(prices)
    # high at bar 3 = 120, stop_price = 110 → stop hit at bar 3
    stop_price = 110.0

    exit_idx, exit_price, reason, bars_held = _find_exit_v2(
        df, 0, "SELL",
        entry_price=100.0,
        stop_price=stop_price,
        take_price=-100.0,
        max_hold_bars=10,
        conditional=ConditionalMaxHoldConfig(enabled=False),
    )
    assert bars_held == 3
    assert reason == "stop"
    assert exit_price == stop_price


def test_take_priority_beats_max_hold():
    """Take at bar 2 should win over max_hold=10."""
    prices = [100.0, 100.0, 80.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
    df = _make_exit_df(prices)
    # low at bar 2 = 75, take_price = 80 → take hit
    take_price = 80.0

    exit_idx, exit_price, reason, bars_held = _find_exit_v2(
        df, 0, "SELL",
        entry_price=100.0,
        stop_price=200.0,
        take_price=take_price,
        max_hold_bars=10,
        conditional=ConditionalMaxHoldConfig(enabled=False),
    )
    assert bars_held == 2
    assert reason == "take"


# ── Test 5: compute_progress_to_take_pct ─────────────────────────────────────

def test_compute_progress_sell_at_entry():
    pct = compute_progress_to_take_pct(
        entry_price=100.0, current_price=100.0, take_price=80.0, direction="SELL"
    )
    assert pct == pytest.approx(0.0)


def test_compute_progress_sell_at_take():
    pct = compute_progress_to_take_pct(
        entry_price=100.0, current_price=80.0, take_price=80.0, direction="SELL"
    )
    assert pct == pytest.approx(100.0)


def test_compute_progress_sell_halfway():
    pct = compute_progress_to_take_pct(
        entry_price=100.0, current_price=90.0, take_price=80.0, direction="SELL"
    )
    assert pct == pytest.approx(50.0)


def test_compute_progress_sell_against_signal():
    """If price moved up (against SELL), progress is negative."""
    pct = compute_progress_to_take_pct(
        entry_price=100.0, current_price=105.0, take_price=80.0, direction="SELL"
    )
    assert pct < 0


# ── Test 6: conditional progress rule exits weak trade ───────────────────────

def test_conditional_progress_exits_weak_trade():
    """At bar 5, if progress < 25%, conditional rule should trigger."""
    cond = ConditionalMaxHoldConfig(
        enabled=True, check_bar=5, min_progress_to_take_pct=25.0
    )
    # entry=100, take=80, current_close=99 → progress = (100-99)/(100-80)*100 = 5% < 25%
    should_exit = _should_conditional_exit(
        entry_price=100.0, current_close=99.0, take_price=80.0,
        direction="SELL", cond=cond
    )
    assert should_exit is True


# ── Test 7: conditional progress rule keeps strong trade alive ───────────────

def test_conditional_progress_keeps_strong_trade():
    """At bar 5, if progress >= 25%, conditional rule should NOT trigger."""
    cond = ConditionalMaxHoldConfig(
        enabled=True, check_bar=5, min_progress_to_take_pct=25.0
    )
    # entry=100, take=80, current_close=94 → progress = 30% >= 25%
    should_exit = _should_conditional_exit(
        entry_price=100.0, current_close=94.0, take_price=80.0,
        direction="SELL", cond=cond
    )
    assert should_exit is False


# ── Test 8: conditional PnL rule exits losing/flat trade ─────────────────────

def test_conditional_pnl_exits_flat_trade():
    """At bar 5, if PnL points <= 0, conditional rule should trigger."""
    cond = ConditionalMaxHoldConfig(
        enabled=True, check_bar=5, max_pnl_points=0.0
    )
    # SELL: entry=100, current_close=101 → pnl_pts = -1 <= 0
    assert _should_conditional_exit(100.0, 101.0, 80.0, "SELL", cond) is True
    # SELL: entry=100, current_close=100 → pnl_pts = 0 <= 0
    assert _should_conditional_exit(100.0, 100.0, 80.0, "SELL", cond) is True


# ── Test 9: conditional PnL rule keeps strong winner ────────────────────────

def test_conditional_pnl_keeps_winner():
    """PnL > threshold → no conditional exit."""
    cond = ConditionalMaxHoldConfig(
        enabled=True, check_bar=5, max_pnl_points=0.0
    )
    # SELL: entry=100, current_close=90 → pnl_pts = 10 > 0
    assert _should_conditional_exit(100.0, 90.0, 80.0, "SELL", cond) is False


# ── Test 10: cut winner classification ───────────────────────────────────────

def test_cut_winner_classification():
    base = pd.DataFrame({
        "signal_time": pd.to_datetime(["2026-01-15 10:00", "2026-01-15 11:00"]),
        "net_pnl_rub": [600.0, -100.0],
        "status": ["closed", "closed"],
    })
    scen = pd.DataFrame({
        "signal_time": pd.to_datetime(["2026-01-15 10:00", "2026-01-15 11:00"]),
        "net_pnl_rub": [150.0, -50.0],  # first trade cut from 600 to 150
        "status": ["closed", "closed"],
    })
    result = compute_winner_loser_analysis(base, scen, large_winner_threshold=500.0, cut_winner_threshold=300.0)
    assert result["large_winners_count"] == 1
    assert result["large_winners_cut_count"] == 1
    assert result["cut_winners_rub"] == pytest.approx(150.0 - 600.0)


# ── Test 11: saved loser classification ──────────────────────────────────────

def test_saved_loser_classification():
    base = pd.DataFrame({
        "signal_time": pd.to_datetime(["2026-01-15 10:00"]),
        "net_pnl_rub": [-500.0],
        "status": ["closed"],
    })
    scen = pd.DataFrame({
        "signal_time": pd.to_datetime(["2026-01-15 10:00"]),
        "net_pnl_rub": [-100.0],  # saved from -500 to -100
        "status": ["closed"],
    })
    result = compute_winner_loser_analysis(base, scen, saved_loser_threshold=-300.0)
    assert result["saved_losers_count"] == 1
    assert result["saved_losers_rub"] == pytest.approx(-100.0 - (-500.0))


# ── Test 12: zero trades scenario does not crash ─────────────────────────────

def test_zero_trades_scenario_does_not_crash():
    """run_scenario_v2 with empty debug_df should return ScenarioResultV2 with 0 trades."""
    df = pd.DataFrame(columns=[
        "timestamp", "open", "high", "low", "close",
        "is_signal", "fail_reason", "direction_candidate",
        "instrument", "timeframe", "tick_size"
    ])
    fc = FilterConfigV2(scenario_name="empty_test", direction="SELL", min_trades_required=1)
    result, trades_df = run_scenario_v2(df, fc, scenario_id=1)
    assert isinstance(result, ScenarioResultV2)
    assert result.trades == 0
    assert result.net_pnl_rub == 0.0


# ── Test 13: unsupported confirmation scenario is flagged ────────────────────

def test_unsupported_confirmation_is_flagged():
    """breakout_confirmation must be flagged as unsupported/equivalent."""
    cfg = {
        "filters": {
            "entry_confirmation": [
                {"name": "baseline"},
                {"name": "breakout_confirmation"},
            ]
        }
    }
    params = BacktestParamsV2()
    configs = make_phase_a_confirmation_configs(cfg, params)
    breakout = next((fc for fc in configs if "breakout" in fc.scenario_name), None)
    assert breakout is not None
    assert breakout.is_unsupported is True
    assert "baseline" in breakout.unsupported_reason.lower() or "equivalent" in breakout.unsupported_reason.lower()


# ── Test 14: report generation does not crash ────────────────────────────────

def test_report_generation_does_not_crash():
    """build_markdown_report_v2 with minimal scenario list should produce non-empty string."""
    signals = _make_candles(
        [100.0] * 30,
        [i % 10 == 0 for i in range(30)],
    )
    # Add needed columns
    signals["fail_reasons"] = signals["fail_reason"]
    signals["params_profile"] = "balanced"
    signals["tick_size_source"] = "specs"

    params = BacktestParamsV2(min_trades_required=1)
    cfg = {
        "data": {"signals_csv": "out/debug_simple_all.csv"},
        "filters": {
            "time_filters": [{"name": "all_hours", "exclude_hours_msk": []}],
            "max_hold": [],
            "conditional_max_hold": [],
            "entry_confirmation": [],
        },
        "phase_b": {
            "time_filters": [], "exit_rules": [], "entry_confirmation": []
        },
    }

    baseline_fc = make_baseline_config_v2(params)
    from src.backtest.exit_time_filters_v2 import run_scenario_v2
    baseline_r, baseline_t = run_scenario_v2(signals, baseline_fc, scenario_id=1)

    report = build_markdown_report_v2(
        baseline=baseline_r,
        phase_a1=[], phase_a2=[], phase_a3=[], phase_a4=[], phase_b=[],
        rankings={"by_net_pnl": [baseline_r], "by_profit_factor": [baseline_r],
                  "by_risk_adjusted": [baseline_r], "robust": [baseline_r]},
        ticker="SiM6",
        direction="SELL",
        period_from="2026-01-15",
        period_to="2026-04-09",
        params=params,
        cfg=cfg,
    )
    assert isinstance(report, str)
    assert "# Backtest Exit/Time Filters v2" in report
    assert "Baseline" in report


# ── Test 15: conditional exit fires at correct bar ───────────────────────────

def test_conditional_exit_fires_at_check_bar():
    """Conditional exit should fire exactly at check_bar, not earlier."""
    # Trade open at bar 0. Bars 1-4: no stop/take, progress < 25%.
    # At bar 5: progress < 25% → should exit with conditional_max_hold_exit.
    prices = [100.0] * 15
    df = _make_exit_df(prices)  # all prices 100, so close=100 always

    cond = ConditionalMaxHoldConfig(
        enabled=True, check_bar=5, min_progress_to_take_pct=25.0
    )
    # entry=100, take=80: progress = (100-100)/(100-80)*100 = 0% < 25%
    exit_idx, exit_price, reason, bars_held = _find_exit_v2(
        df, 0, "SELL",
        entry_price=100.0,
        stop_price=200.0,
        take_price=80.0,
        max_hold_bars=None,
        conditional=cond,
    )
    assert bars_held == 5
    assert reason == "conditional_max_hold_exit"


# ── Test 16: phase_a time configs exclude all_hours ──────────────────────────

def test_phase_a_time_configs_exclude_all_hours():
    """all_hours should not appear in Phase A time configs (it's the baseline)."""
    cfg = {
        "filters": {
            "time_filters": [
                {"name": "all_hours", "exclude_hours_msk": []},
                {"name": "exclude_hour_12", "exclude_hours_msk": [12]},
            ]
        }
    }
    configs = make_phase_a_time_configs(cfg, BacktestParamsV2())
    names = [fc.scenario_name for fc in configs]
    assert all("all_hours" not in n for n in names)
    assert any("hour_12" in n for n in names)
