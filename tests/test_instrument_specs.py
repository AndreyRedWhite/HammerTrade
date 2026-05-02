import os
import tempfile

import pandas as pd
import pytest

from src.tbank.instrument_specs import (
    FutureInstrumentSpec,
    _compute_point_value_rub,
    load_specs_cache,
    upsert_future_spec,
    get_cached_future_spec,
)


def _make_spec(ticker="SiM6", pvr=10.0, mpi=1.0, mpia=10.0):
    return FutureInstrumentSpec(
        ticker=ticker,
        class_code="SPBFUT",
        uid="test-uid-123",
        figi="FUTSI0626",
        name="Si-6.26",
        lot=1,
        currency="rub",
        min_price_increment=mpi,
        min_price_increment_amount=mpia,
        point_value_rub=pvr,
        initial_margin_on_buy=5000.0,
        initial_margin_on_sell=5000.0,
        expiration_date=None,
        first_trade_date=None,
        last_trade_date=None,
        first_1min_candle_date=None,
        first_1day_candle_date=None,
        api_trade_available_flag=True,
        buy_available_flag=True,
        sell_available_flag=True,
    )


def test_compute_point_value_rub_basic():
    result = _compute_point_value_rub(1.0, 10.0)
    assert result == pytest.approx(10.0)


def test_compute_point_value_rub_fractional():
    result = _compute_point_value_rub(0.5, 5.0)
    assert result == pytest.approx(10.0)


def test_compute_point_value_rub_none_amount():
    result = _compute_point_value_rub(1.0, None)
    assert result is None


def test_compute_point_value_rub_none_increment():
    result = _compute_point_value_rub(None, 10.0)
    assert result is None


def test_compute_point_value_rub_zero_increment():
    result = _compute_point_value_rub(0.0, 10.0)
    assert result is None


def test_upsert_and_load_cache():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        spec = _make_spec()
        upsert_future_spec(spec, path)
        df = load_specs_cache(path)
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "SiM6"
    finally:
        os.unlink(path)


def test_upsert_no_duplicates():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        spec = _make_spec()
        upsert_future_spec(spec, path)
        upsert_future_spec(spec, path)
        df = load_specs_cache(path)
        assert len(df) == 1
    finally:
        os.unlink(path)


def test_upsert_updates_existing():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        spec1 = _make_spec(pvr=10.0)
        upsert_future_spec(spec1, path)

        spec2 = FutureInstrumentSpec(
            **{**vars(spec1), "point_value_rub": 20.0}
        )
        upsert_future_spec(spec2, path)

        df = load_specs_cache(path)
        assert len(df) == 1
        assert float(df.iloc[0]["point_value_rub"]) == pytest.approx(20.0)
    finally:
        os.unlink(path)


def test_get_cached_future_spec_found():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        spec = _make_spec()
        upsert_future_spec(spec, path)
        cached = get_cached_future_spec("SiM6", "SPBFUT", path)
        assert cached is not None
        assert cached.ticker == "SiM6"
        assert cached.point_value_rub == pytest.approx(10.0)
    finally:
        os.unlink(path)


def test_get_cached_future_spec_not_found():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        spec = _make_spec("SiM6")
        upsert_future_spec(spec, path)
        cached = get_cached_future_spec("BRM6", "SPBFUT", path)
        assert cached is None
    finally:
        os.unlink(path)


def test_get_cached_future_spec_empty_file():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        cached = get_cached_future_spec("SiM6", "SPBFUT", path)
        assert cached is None
    finally:
        os.unlink(path)


def test_multiple_tickers_in_cache():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        upsert_future_spec(_make_spec("SiM6", pvr=10.0), path)
        upsert_future_spec(_make_spec("BRM6", pvr=66.67), path)
        df = load_specs_cache(path)
        assert len(df) == 2
        si = get_cached_future_spec("SiM6", "SPBFUT", path)
        br = get_cached_future_spec("BRM6", "SPBFUT", path)
        assert si.point_value_rub == pytest.approx(10.0)
        assert br.point_value_rub == pytest.approx(66.67)
    finally:
        os.unlink(path)
