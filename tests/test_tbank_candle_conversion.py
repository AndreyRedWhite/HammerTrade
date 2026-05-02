"""Tests for quotation conversion and candle→DataFrame logic.
No T-Bank SDK required — uses simple mock objects.
"""
from types import SimpleNamespace
from datetime import datetime, timezone

import pandas as pd
import pytest

from src.tbank.money import quotation_to_float, money_value_to_float
from src.tbank.candles import _candle_to_row, EMPTY_CANDLES_COLUMNS


def q(units: int, nano: int):
    return SimpleNamespace(units=units, nano=nano)


def make_candle(open_u, open_n, high_u, high_n, low_u, low_n, close_u, close_n, volume, ts=None):
    if ts is None:
        ts = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        time=ts,
        open=q(open_u, open_n),
        high=q(high_u, high_n),
        low=q(low_u, low_n),
        close=q(close_u, close_n),
        volume=volume,
    )


def test_quotation_basic():
    assert quotation_to_float(q(100, 250_000_000)) == pytest.approx(100.25)


def test_quotation_fractional_only():
    assert quotation_to_float(q(0, 500_000_000)) == pytest.approx(0.5)


def test_quotation_whole():
    assert quotation_to_float(q(92000, 0)) == pytest.approx(92000.0)


def test_quotation_negative_units():
    assert quotation_to_float(q(-1, -500_000_000)) == pytest.approx(-1.5)


def test_quotation_negative_fractional_only():
    assert quotation_to_float(q(0, -250_000_000)) == pytest.approx(-0.25)


def test_money_value_to_float():
    assert money_value_to_float(q(50, 100_000_000)) == pytest.approx(50.1)


def test_candle_to_row_columns():
    candle = make_candle(
        92000, 0,      # open
        92050, 0,      # high
        91980, 0,      # low
        92020, 0,      # close
        volume=123,
    )
    row = _candle_to_row(candle)
    assert set(row.keys()) == {"timestamp", "open", "high", "low", "close", "volume"}
    assert row["open"] == pytest.approx(92000.0)
    assert row["high"] == pytest.approx(92050.0)
    assert row["low"] == pytest.approx(91980.0)
    assert row["close"] == pytest.approx(92020.0)
    assert row["volume"] == 123


def test_candle_to_row_fractional_price():
    candle = make_candle(100, 250_000_000, 100, 500_000_000, 99, 750_000_000, 100, 0, 10)
    row = _candle_to_row(candle)
    assert row["open"] == pytest.approx(100.25)
    assert row["high"] == pytest.approx(100.5)
    assert row["low"] == pytest.approx(99.75)


def test_empty_columns_defined():
    assert set(EMPTY_CANDLES_COLUMNS) == {"timestamp", "open", "high", "low", "close", "volume"}
