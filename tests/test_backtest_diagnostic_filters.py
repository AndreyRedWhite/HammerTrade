"""Tests for MVP-2.0 Backtest Diagnostic Filters.

Tests cover: SELL/BUY reward-risk-rr computation, min_reward_points filter,
min_rr filter, time filters (MSK hour), entry confirmation, combined filters,
zero-trades scenario, LOW_SAMPLE flag, report generation, and baseline
passthrough.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.diagnostic_filters import (
    FilterConfig,
    apply_signal_filters,
    compute_signal_reward_risk,
    get_msk_hour,
    run_scenario,
)
from src.backtest.diagnostic_grid import (
    BacktestParams,
    build_markdown_report,
    rank_scenarios,
    run_all_scenarios,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _make_sell_signal_df(
    *,
    high: float = 110.0,
    low: float = 100.0,
    ts: str = "2026-03-15 07:00:00+00:00",  # 10:00 MSK
    n_extra_candles: int = 5,
) -> pd.DataFrame:
    """Creates a minimal debug_df with one SELL signal + follow-on candles."""
    rows = [
        {
            "timestamp": ts,
            "instrument": "SiM6",
            "timeframe": "1m",
            "open": 105.0,
            "high": high,
            "low": low,
            "close": 102.0,
            "volume": 100,
            "direction_candidate": "SELL",
            "is_signal": True,
            "fail_reason": "pass",
        }
    ]
    base_ts = pd.Timestamp(ts)
    for i in range(1, n_extra_candles + 1):
        next_ts = (base_ts + pd.Timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S+00:00")
        rows.append({
            "timestamp": next_ts,
            "instrument": "SiM6",
            "timeframe": "1m",
            "open": 102.0,
            "high": 103.0,
            "low": 95.0,  # low enough to trigger breakout and stop/take
            "close": 98.0,
            "volume": 50,
            "direction_candidate": "SELL",
            "is_signal": False,
            "fail_reason": "no_signal",
        })
    return pd.DataFrame(rows)


def _make_buy_signal_df(
    *,
    high: float = 110.0,
    low: float = 100.0,
    ts: str = "2026-03-15 07:00:00+00:00",
    n_extra_candles: int = 5,
) -> pd.DataFrame:
    rows = [
        {
            "timestamp": ts,
            "instrument": "SiM6",
            "timeframe": "1m",
            "open": 105.0,
            "high": high,
            "low": low,
            "close": 108.0,
            "volume": 100,
            "direction_candidate": "BUY",
            "is_signal": True,
            "fail_reason": "pass",
        }
    ]
    base_ts = pd.Timestamp(ts)
    for i in range(1, n_extra_candles + 1):
        next_ts = (base_ts + pd.Timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S+00:00")
        rows.append({
            "timestamp": next_ts,
            "instrument": "SiM6",
            "timeframe": "1m",
            "open": 108.0,
            "high": 120.0,  # high enough to trigger breakout
            "low": 107.0,
            "close": 115.0,
            "volume": 50,
            "direction_candidate": "BUY",
            "is_signal": False,
            "fail_reason": "no_signal",
        })
    return pd.DataFrame(rows)


def _base_params(direction: str = "SELL", min_trades_required: int = 1) -> BacktestParams:
    return BacktestParams(
        direction=direction,
        take_r=1.0,
        default_max_hold_bars=30,
        min_trades_required=min_trades_required,
    )


# ─── Test 1: SELL reward / risk / RR ─────────────────────────────────────────

def test_sell_reward_risk_rr_basic():
    """SELL: entry=100 (sig_low), stop=110 (sig_high) → risk=10, reward=10, rr=1.0."""
    sig_row = pd.Series({"direction_candidate": "SELL", "high": 110.0, "low": 100.0})
    risk, reward, rr = compute_signal_reward_risk(sig_row, stop_buffer_points=0.0, take_r=1.0)
    assert risk == pytest.approx(10.0)
    assert reward == pytest.approx(10.0)
    assert rr == pytest.approx(1.0)


def test_buy_reward_risk_rr_basic():
    """BUY: entry=110 (sig_high), stop=100 (sig_low) → risk=10, reward=10, rr=1.0."""
    sig_row = pd.Series({"direction_candidate": "BUY", "high": 110.0, "low": 100.0})
    risk, reward, rr = compute_signal_reward_risk(sig_row, stop_buffer_points=0.0, take_r=1.0)
    assert risk == pytest.approx(10.0)
    assert reward == pytest.approx(10.0)
    assert rr == pytest.approx(1.0)


def test_sell_rr_equals_take_r():
    """rr = take_r always (pre-slippage, raw price geometry)."""
    sig_row = pd.Series({"direction_candidate": "SELL", "high": 130.0, "low": 100.0})
    for take_r in [0.5, 0.8, 1.0, 1.5, 2.0]:
        risk, reward, rr = compute_signal_reward_risk(sig_row, stop_buffer_points=0.0, take_r=take_r)
        assert rr == pytest.approx(take_r), f"rr should equal take_r={take_r}"
        assert reward == pytest.approx(risk * take_r)


# ─── Test 2: min_reward_points filter ─────────────────────────────────────────

def test_min_reward_filters_small_reward():
    """min_reward_points=5 filters reward=4 signal (risk=4, take_r=1.0)."""
    df = _make_sell_signal_df(high=104.0, low=100.0)  # risk=4, reward=4*1.0=4
    config = FilterConfig(scenario_name="test", direction="SELL", min_reward_points=5.0)
    _, n_orig, n_after, n_filtered = apply_signal_filters(df, config, stop_buffer_points=0.0, take_r=1.0)
    assert n_orig == 1
    assert n_filtered == 1
    assert n_after == 0


def test_min_reward_passes_exact_boundary():
    """min_reward_points=5 passes reward=5 signal (risk=5, take_r=1.0)."""
    df = _make_sell_signal_df(high=105.0, low=100.0)  # risk=5, reward=5
    config = FilterConfig(scenario_name="test", direction="SELL", min_reward_points=5.0)
    _, n_orig, n_after, n_filtered = apply_signal_filters(df, config, stop_buffer_points=0.0, take_r=1.0)
    assert n_orig == 1
    assert n_filtered == 0
    assert n_after == 1


# ─── Test 3: min_rr filter ────────────────────────────────────────────────────

def test_min_rr_filters_low_take_r():
    """min_rr=0.8 filters signal when take_r=0.79 (rr=take_r=0.79 < 0.8)."""
    df = _make_sell_signal_df(high=110.0, low=100.0)
    config = FilterConfig(scenario_name="test", direction="SELL", min_rr=0.8)
    _, n_orig, n_after, n_filtered = apply_signal_filters(df, config, stop_buffer_points=0.0, take_r=0.79)
    assert n_orig == 1
    assert n_filtered == 1
    assert n_after == 0


def test_min_rr_passes_equal_take_r():
    """min_rr=0.8 passes signal when take_r=0.8 (rr=0.8 >= 0.8)."""
    df = _make_sell_signal_df(high=110.0, low=100.0)
    config = FilterConfig(scenario_name="test", direction="SELL", min_rr=0.8)
    _, n_orig, n_after, n_filtered = apply_signal_filters(df, config, stop_buffer_points=0.0, take_r=0.8)
    assert n_orig == 1
    assert n_filtered == 0
    assert n_after == 1


def test_min_rr_no_effect_at_take_r_10():
    """At take_r=1.0, min_rr<=1.0 never filters any signal (rr=1.0 always)."""
    df = _make_sell_signal_df(high=110.0, low=100.0)
    for min_rr in [0.5, 0.8, 0.9, 1.0]:
        config = FilterConfig(scenario_name="test", direction="SELL", min_rr=min_rr)
        _, _, n_after, _ = apply_signal_filters(df, config, stop_buffer_points=0.0, take_r=1.0)
        assert n_after == 1, f"Expected signal to pass for min_rr={min_rr} at take_r=1.0"


# ─── Test 4: MSK hour computation ─────────────────────────────────────────────

def test_get_msk_hour_utc_to_msk():
    """UTC 07:00 = MSK 10:00 (UTC+3)."""
    hour = get_msk_hour("2026-03-15 07:00:00+00:00")
    assert hour == 10


def test_get_msk_hour_midnight_boundary():
    """UTC 21:00 = MSK 00:00 next day (UTC+3)."""
    hour = get_msk_hour("2026-03-15 21:00:00+00:00")
    assert hour == 0


def test_get_msk_hour_no_tz_treated_as_utc():
    """Naive timestamp treated as UTC: 09:00 naive = 12:00 MSK."""
    hour = get_msk_hour("2026-03-15 09:00:00")
    assert hour == 12


# ─── Test 5: exclude_hours_msk filters bad-hour signal ────────────────────────

def test_exclude_hours_msk_filters_signal():
    """Signal at 10 MSK filtered when exclude_hours_msk=[10]."""
    # UTC 07:00 = MSK 10:00
    df = _make_sell_signal_df(ts="2026-03-15 07:00:00+00:00")
    config = FilterConfig(scenario_name="test", direction="SELL", exclude_hours_msk=[10])
    _, n_orig, n_after, n_filtered = apply_signal_filters(df, config, stop_buffer_points=0.0, take_r=1.0)
    assert n_filtered == 1
    assert n_after == 0


def test_exclude_hours_msk_passes_other_hours():
    """Signal at 10 MSK not filtered when exclude_hours_msk=[12, 13]."""
    df = _make_sell_signal_df(ts="2026-03-15 07:00:00+00:00")  # 10 MSK
    config = FilterConfig(scenario_name="test", direction="SELL", exclude_hours_msk=[12, 13])
    _, n_orig, n_after, n_filtered = apply_signal_filters(df, config, stop_buffer_points=0.0, take_r=1.0)
    assert n_filtered == 0
    assert n_after == 1


# ─── Test 6: include_hours_msk keeps only allowed hours ───────────────────────

def test_include_hours_msk_keeps_only_listed():
    """Signal at 10 MSK passes when include=[10], filtered when include=[15]."""
    df = _make_sell_signal_df(ts="2026-03-15 07:00:00+00:00")  # 10 MSK

    config_pass = FilterConfig(scenario_name="test", direction="SELL", include_hours_msk=[10])
    _, _, n_after_pass, _ = apply_signal_filters(df, config_pass, 0.0, 1.0)
    assert n_after_pass == 1

    config_filter = FilterConfig(scenario_name="test", direction="SELL", include_hours_msk=[15])
    _, _, n_after_filter, _ = apply_signal_filters(df, config_filter, 0.0, 1.0)
    assert n_after_filter == 0


# ─── Test 7: combined filters use AND logic ───────────────────────────────────

def test_combined_filters_and_logic():
    """Signal is filtered if ANY filter condition fails."""
    # Signal at 10 MSK, risk=4 (reward=4 < min_reward=5)
    df = _make_sell_signal_df(high=104.0, low=100.0, ts="2026-03-15 07:00:00+00:00")

    # Only min_reward fails → filtered
    config_rwd = FilterConfig(scenario_name="t", direction="SELL", min_reward_points=5.0)
    _, _, n1, _ = apply_signal_filters(df, config_rwd, 0.0, 1.0)
    assert n1 == 0

    # Only time filter fails → filtered
    config_tf = FilterConfig(scenario_name="t", direction="SELL", exclude_hours_msk=[10])
    _, _, n2, _ = apply_signal_filters(df, config_tf, 0.0, 1.0)
    assert n2 == 0

    # Both conditions would fail, still filtered (AND, so first match wins)
    config_both = FilterConfig(scenario_name="t", direction="SELL", min_reward_points=5.0, exclude_hours_msk=[10])
    _, _, n3, _ = apply_signal_filters(df, config_both, 0.0, 1.0)
    assert n3 == 0

    # No filters → passes
    config_none = FilterConfig(scenario_name="t", direction="SELL")
    _, _, n4, _ = apply_signal_filters(df, config_none, 0.0, 1.0)
    assert n4 == 1


# ─── Test 8: zero-trades scenario doesn't crash ───────────────────────────────

def test_zero_trades_scenario_no_crash():
    """Scenario where all signals are filtered should return ScenarioResult with 0 trades."""
    df = _make_sell_signal_df(high=104.0, low=100.0)  # reward=4
    config = FilterConfig(
        scenario_name="no_trades",
        direction="SELL",
        min_reward_points=100.0,  # very high threshold — filters everything
        min_trades_required=1,
    )
    result, trades_df = run_scenario(df, config, scenario_id=1)
    assert result.trades == 0
    assert result.net_pnl_rub == 0.0
    assert result.profit_factor == 0.0
    assert result.wins == 0
    assert result.losses == 0


# ─── Test 9: LOW_SAMPLE flag ─────────────────────────────────────────────────

def test_low_sample_flag_when_trades_below_threshold():
    """ScenarioResult.is_low_sample=True when trades < min_trades_required."""
    df = _make_sell_signal_df(high=110.0, low=100.0)
    config = FilterConfig(
        scenario_name="low_sample_test",
        direction="SELL",
        min_trades_required=100,  # threshold higher than 1 trade in df
    )
    result, _ = run_scenario(df, config, scenario_id=1)
    assert result.is_low_sample is True
    assert any("LOW_SAMPLE" in w for w in result.warnings)


def test_low_sample_flag_absent_when_enough_trades():
    """ScenarioResult.is_low_sample=False when trades >= min_trades_required."""
    df = _make_sell_signal_df(high=110.0, low=100.0)
    config = FilterConfig(
        scenario_name="enough_trades",
        direction="SELL",
        min_trades_required=1,
    )
    result, _ = run_scenario(df, config, scenario_id=1)
    assert result.is_low_sample is False


# ─── Test 10: report generation on empty scenario ─────────────────────────────

def test_report_generation_empty_scenario_no_crash():
    """build_markdown_report should not crash when all scenarios have 0 trades."""
    df = _make_sell_signal_df(high=110.0, low=100.0)

    cfg = {
        "data": {"signals_csv": "out/debug_simple_all.csv"},
        "filters": {
            "min_reward_points": [0],
            "min_rr": [0.0],
            "max_hold_bars": [],
            "time_filter": [{"name": "all_hours", "exclude_hours_msk": [], "include_hours_msk": None}],
            "entry_confirmation": ["baseline"],
        },
        "phase_b": {"min_reward_points": [0], "min_rr": [0.0], "time_filter": ["all_hours"]},
        "reporting": {"min_trades_required": 1},
    }
    params = _base_params()

    baseline, phase_a, phase_b, trades_map = run_all_scenarios(df, params, cfg)
    rankings = rank_scenarios(baseline, phase_a + phase_b, top_n=5)
    report = build_markdown_report(
        baseline=baseline,
        phase_a=phase_a,
        phase_b=phase_b,
        rankings=rankings,
        ticker="SiM6",
        direction="SELL",
        period_from="2026-03-01",
        period_to="2026-04-09",
        params=params,
        cfg=cfg,
    )
    assert isinstance(report, str)
    assert "Backtest Diagnostic Filters" in report
    assert "Baseline" in report


# ─── Test 11: baseline scenario no filters applied ────────────────────────────

def test_baseline_scenario_does_not_filter():
    """Baseline FilterConfig with defaults should not filter any signals."""
    df = _make_sell_signal_df(high=110.0, low=100.0, ts="2026-03-15 09:00:00+00:00")  # 12 MSK
    config = FilterConfig(scenario_name="baseline", direction="SELL")  # all defaults = no filters
    _, n_orig, n_after, n_filtered = apply_signal_filters(df, config, stop_buffer_points=0.0, take_r=1.0)
    assert n_filtered == 0
    assert n_after == n_orig


# ─── Test 12: unsupported entry_confirmation handled gracefully ───────────────

def test_breakout_confirmation_equivalent_to_baseline():
    """breakout_confirmation scenario should have same trade count as baseline."""
    df = _make_sell_signal_df(high=110.0, low=100.0)

    config_baseline = FilterConfig(scenario_name="baseline", direction="SELL")
    _, n_orig_b, n_after_b, n_filtered_b = apply_signal_filters(df, config_baseline, 0.0, 1.0)

    config_bc = FilterConfig(scenario_name="bc", direction="SELL", entry_confirmation="breakout_confirmation")
    _, n_orig_bc, n_after_bc, n_filtered_bc = apply_signal_filters(df, config_bc, 0.0, 1.0)

    # breakout_confirmation is explicit no-op (same as baseline)
    assert n_after_bc == n_after_b
    assert n_filtered_bc == 0


def test_next_candle_direction_filters_bullish_next_candle():
    """next_candle_direction for SELL: filters signal when next candle is bullish."""
    # Create df where next candle after signal is bullish (close > open)
    rows = [
        {
            "timestamp": "2026-03-15 07:00:00+00:00",
            "instrument": "SiM6", "timeframe": "1m",
            "open": 105.0, "high": 110.0, "low": 100.0, "close": 102.0, "volume": 100,
            "direction_candidate": "SELL", "is_signal": True, "fail_reason": "pass",
        },
        {   # bullish next candle — should trigger filter for SELL
            "timestamp": "2026-03-15 07:01:00+00:00",
            "instrument": "SiM6", "timeframe": "1m",
            "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 50,
            "direction_candidate": "SELL", "is_signal": False, "fail_reason": "no_signal",
        },
    ]
    df = pd.DataFrame(rows)

    config = FilterConfig(scenario_name="ncd", direction="SELL", entry_confirmation="next_candle_direction")
    _, _, n_after, n_filtered = apply_signal_filters(df, config, 0.0, 1.0)
    assert n_filtered == 1, "Bullish next candle should filter SELL signal"


def test_next_candle_direction_passes_bearish_next_candle():
    """next_candle_direction for SELL: passes signal when next candle is bearish."""
    rows = [
        {
            "timestamp": "2026-03-15 07:00:00+00:00",
            "instrument": "SiM6", "timeframe": "1m",
            "open": 105.0, "high": 110.0, "low": 100.0, "close": 102.0, "volume": 100,
            "direction_candidate": "SELL", "is_signal": True, "fail_reason": "pass",
        },
        {   # bearish next candle — should pass for SELL
            "timestamp": "2026-03-15 07:01:00+00:00",
            "instrument": "SiM6", "timeframe": "1m",
            "open": 104.0, "high": 105.0, "low": 98.0, "close": 99.0, "volume": 50,
            "direction_candidate": "SELL", "is_signal": False, "fail_reason": "no_signal",
        },
    ] + [
        {
            "timestamp": f"2026-03-15 07:0{i}:00+00:00",
            "instrument": "SiM6", "timeframe": "1m",
            "open": 99.0, "high": 100.0, "low": 92.0, "close": 94.0, "volume": 30,
            "direction_candidate": "SELL", "is_signal": False, "fail_reason": "no_signal",
        }
        for i in range(2, 7)
    ]
    df = pd.DataFrame(rows)

    config = FilterConfig(scenario_name="ncd", direction="SELL", entry_confirmation="next_candle_direction")
    _, _, n_after, n_filtered = apply_signal_filters(df, config, 0.0, 1.0)
    assert n_filtered == 0, "Bearish next candle should pass SELL signal"
