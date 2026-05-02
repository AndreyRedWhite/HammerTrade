import tempfile
import os
import pandas as pd
import pytest

from src.config import HammerParams
from src.strategy.hammer_detector import HammerDetector
from src.storage.debug_repository import save_debug_csv, OUTPUT_COLUMNS


def _make_candles():
    return pd.DataFrame([{
        "timestamp": pd.Timestamp("2026-01-01 10:00:00+00:00"),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100,
    }])


def test_output_columns_contains_tick_size():
    assert "tick_size" in OUTPUT_COLUMNS
    assert "tick_size_source" in OUTPUT_COLUMNS


def test_debug_csv_has_tick_size_columns():
    params = HammerParams(tick_size=0.01, tick_size_source="specs", clearing_enable=False)
    result = HammerDetector(params).detect_all(_make_candles(), instrument="TEST")
    assert "tick_size" in result.columns
    assert "tick_size_source" in result.columns


def test_debug_csv_tick_size_value():
    params = HammerParams(tick_size=0.25, tick_size_source="cli", clearing_enable=False)
    result = HammerDetector(params).detect_all(_make_candles())
    assert result["tick_size"].iloc[0] == pytest.approx(0.25)
    assert result["tick_size_source"].iloc[0] == "cli"


def test_save_debug_csv_writes_tick_size():
    params = HammerParams(tick_size=0.01, tick_size_source="specs", clearing_enable=False)
    result = HammerDetector(params).detect_all(_make_candles(), instrument="TEST")

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        save_debug_csv(result, path)
        df = pd.read_csv(path)
        assert "tick_size" in df.columns
        assert "tick_size_source" in df.columns
        assert float(df.iloc[0]["tick_size"]) == pytest.approx(0.01)
        assert df.iloc[0]["tick_size_source"] == "specs"
    finally:
        os.unlink(path)


def test_fallback_tick_size_in_csv():
    params = HammerParams(fallback_tick=0.5, tick_size=None, tick_size_source="fallback",
                          clearing_enable=False)
    result = HammerDetector(params).detect_all(_make_candles())
    assert result["tick_size"].iloc[0] == pytest.approx(0.5)
    assert result["tick_size_source"].iloc[0] == "fallback"
