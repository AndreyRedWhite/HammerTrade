import pandas as pd
import pytest
from src.config import HammerParams
from src.strategy.hammer_detector import HammerDetector


def make_params(**overrides) -> HammerParams:
    defaults = dict(
        body_min_frac=0.12,
        body_max_frac=0.33,
        wick_mult=2.3,
        opp_wick_max_frac=0.70,
        wick_dom_ratio=2.0,
        ext_window=2,
        ext_eps_ticks=0.5,
        neighbor_mode="left_or_right",
        neighbor_eps_ticks=0.5,
        min_range_ticks=2.0,
        min_wick_ticks=1.5,
        opp_wick_max_abs_ticks=2.0,
        close_pos_frac=0.60,
        silhouette_min_frac=0.45,
        min_excursion_ticks=2.0,
        excursion_horizon=2,
        fallback_tick=0.5,
        clearing_enable=False,
        confirm_mode="break",
        confirm_horizon=1,
        cooldown_bars=0,
        point_value_rub=10.0,
        commission_per_trade=0.025,
        commission_round_turn=0.05,
        clearing_block_before_min=5,
        clearing_block_after_min=5,
        timezone="Europe/Moscow",
    )
    defaults.update(overrides)
    return HammerParams(**defaults)


def make_candles(rows):
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.date_range("2024-01-01 10:00", periods=len(df), freq="1min")
    df["volume"] = 100
    return df


def test_buy_hammer_signal():
    # descending approach, then clear BUY hammer at bar 3, then breakout bar 4
    candles = make_candles([
        {"open": 110, "high": 111, "low": 108, "close": 109},  # bar 0 - trending down
        {"open": 109, "high": 110, "low": 106, "close": 107},  # bar 1 - trending down
        {"open": 107, "high": 108, "low": 104, "close": 106},  # bar 2 - trending down
        # BUY hammer: low=95, high=104, body top half, long lower shadow
        # open=102, close=103.5 → range=9, body=1.5, body_frac=0.167, lower_shadow=7, upper_shadow=0.5
        {"open": 102, "high": 104, "low": 95, "close": 103.5},  # bar 3 - hammer
        {"open": 103.5, "high": 106, "low": 103, "close": 105},  # bar 4 - breakout (high > 104)
        {"open": 105, "high": 107, "low": 104, "close": 106},   # bar 5
    ])

    params = make_params(
        min_range_ticks=2.0,
        fallback_tick=0.5,
        ext_window=2,
        ext_eps_ticks=0.5,
        opp_wick_max_abs_ticks=3.0,
        excursion_horizon=2,
        min_excursion_ticks=1.5,
        confirm_horizon=1,
        cooldown_bars=0,
    )
    detector = HammerDetector(params)
    result = detector.detect_all(candles, instrument="TEST", timeframe="1m", profile="test")

    signal_row = result.iloc[3]
    assert signal_row["direction_candidate"] == "BUY", f"Expected BUY, got {signal_row['direction_candidate']}"
    assert signal_row["is_signal"], f"Expected is_signal=True, fail_reason={signal_row['fail_reason']}"
    assert signal_row["fail_reason"] == "pass"


def test_doji_rejected():
    # A near-doji candle: body is too small relative to range
    candles = make_candles([
        {"open": 100, "high": 110, "low": 90, "close": 100.5},  # bar 0: body_frac=0.025 < 0.12
        {"open": 100.5, "high": 112, "low": 100, "close": 111},  # bar 1: confirm bar
    ])

    params = make_params(body_min_frac=0.12, fallback_tick=0.5, min_range_ticks=2.0)
    detector = HammerDetector(params)
    result = detector.detect_all(candles, instrument="TEST", timeframe="1m", profile="test")

    row = result.iloc[0]
    assert not row["is_signal"]
    assert row["fail_reason"] == "doji"
