import os
import tempfile
from datetime import datetime, timezone

import pandas as pd
import pytest

from src.tbank.liquidity_universe import (
    _calc_liquidity,
    _empty_liquidity,
    filter_active_futures,
    generate_universe_report,
)


def _make_candles(n=100, vol=500):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-03-01", periods=n, freq="1min", tz="UTC"),
        "open": [2800.0] * n,
        "high": [2810.0] * n,
        "low": [2790.0] * n,
        "close": [2805.0] * n,
        "volume": [vol] * n,
    })


def _make_futures_df():
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end = datetime(2026, 4, 10, tzinfo=timezone.utc)
    return pd.DataFrame([
        {
            "ticker": "SiM6", "class_code": "SPBFUT", "uid": "uid1",
            "name": "Si-6.26", "point_value_rub": 10.0,
            "expiration_date": datetime(2026, 6, 15, tzinfo=timezone.utc),
            "first_1min_candle_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "last_trade_date": None, "first_trade_date": None, "first_1day_candle_date": None,
            "api_trade_available_flag": True, "buy_available_flag": True, "sell_available_flag": True,
            "min_price_increment": 1.0, "min_price_increment_amount": 10.0,
        },
        {
            "ticker": "OLD1", "class_code": "SPBFUT", "uid": "uid2",
            "name": "Expired future", "point_value_rub": 5.0,
            "expiration_date": datetime(2025, 12, 31, tzinfo=timezone.utc),  # expired before start
            "first_1min_candle_date": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "last_trade_date": None, "first_trade_date": None, "first_1day_candle_date": None,
            "api_trade_available_flag": True, "buy_available_flag": True, "sell_available_flag": True,
            "min_price_increment": 1.0, "min_price_increment_amount": 5.0,
        },
        {
            "ticker": "NEW1", "class_code": "SPBFUT", "uid": "uid3",
            "name": "Future not yet started", "point_value_rub": 8.0,
            "expiration_date": datetime(2027, 6, 15, tzinfo=timezone.utc),
            "first_1min_candle_date": datetime(2026, 5, 1, tzinfo=timezone.utc),  # after end
            "last_trade_date": None, "first_trade_date": None, "first_1day_candle_date": None,
            "api_trade_available_flag": True, "buy_available_flag": True, "sell_available_flag": True,
            "min_price_increment": 1.0, "min_price_increment_amount": 8.0,
        },
    ])


def test_calc_liquidity_basic():
    candles = _make_candles(100, vol=500)
    result = _calc_liquidity(candles)
    assert result["candles_count"] == 100
    assert result["non_zero_volume_candles"] == 100
    assert result["zero_range_candles"] == 0
    assert result["total_volume"] == pytest.approx(50000.0)
    assert result["activity_score"] == pytest.approx(100 * 500)


def test_calc_liquidity_zero_volume():
    candles = _make_candles(50, vol=0)
    result = _calc_liquidity(candles)
    assert result["non_zero_volume_candles"] == 0
    assert result["activity_score"] == 0.0


def test_calc_liquidity_zero_range():
    candles = pd.DataFrame({
        "high": [100.0] * 10,
        "low": [100.0] * 10,
        "volume": [100] * 10,
    })
    result = _calc_liquidity(candles)
    assert result["zero_range_candles"] == 10


def test_activity_score_formula():
    candles = _make_candles(50, vol=200)
    result = _calc_liquidity(candles)
    expected = 50 * 200
    assert result["activity_score"] == pytest.approx(expected)


def test_filter_active_futures_removes_expired():
    futures_df = _make_futures_df()
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end = datetime(2026, 4, 10, tzinfo=timezone.utc)
    active = filter_active_futures(futures_df, start, end)
    tickers = active["ticker"].tolist()
    assert "SiM6" in tickers
    assert "OLD1" not in tickers


def test_filter_active_futures_removes_future_candles():
    futures_df = _make_futures_df()
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end = datetime(2026, 4, 10, tzinfo=timezone.utc)
    active = filter_active_futures(futures_df, start, end)
    tickers = active["ticker"].tolist()
    assert "NEW1" not in tickers


def test_generate_universe_report():
    futures_df = _make_futures_df().head(1)
    futures_df["candles_count"] = 100
    futures_df["total_volume"] = 50000
    futures_df["median_volume_per_candle"] = 500
    futures_df["zero_range_candles"] = 0
    futures_df["activity_score"] = 50000
    futures_df["rank"] = 1

    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        path = f.name
    try:
        params = {"Class code": "SPBFUT", "Period": "2026-03-01 -> 2026-04-10"}
        generate_universe_report(futures_df, path, params)
        content = open(path).read()
        assert "Liquid Futures Universe Report" in content
        assert "SiM6" in content
        assert "SPBFUT" in content
    finally:
        os.unlink(path)


def test_empty_liquidity_structure():
    empty = _empty_liquidity()
    assert empty["candles_count"] == 0
    assert empty["activity_score"] == 0.0
    assert "non_zero_volume_candles" in empty
