import os
import tempfile

import pandas as pd
import pytest

from src.analytics.data_quality_report import analyze, load_candle_csv, build_markdown


def make_df(rows):
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


GOOD_ROWS = [
    {"timestamp": "2026-04-01T10:00:00Z", "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100},
    {"timestamp": "2026-04-01T10:01:00Z", "open": 103.0, "high": 107.0, "low": 102.0, "close": 106.0, "volume": 200},
    {"timestamp": "2026-04-01T10:02:00Z", "open": 106.0, "high": 108.0, "low": 105.0, "close": 107.0, "volume": 150},
]


def test_report_created_basic():
    df = make_df(GOOD_ROWS)
    r = analyze(df, "1m")
    assert r["n_rows"] == 3
    assert r["n_dupes"] == 0
    assert r["zero_range"] == 0
    assert r["missing_ohlc"] == 0


def test_duplicate_timestamps_counted():
    rows = GOOD_ROWS + [
        {"timestamp": "2026-04-01T10:00:00Z", "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100},
    ]
    df = make_df(rows)
    r = analyze(df, "1m")
    assert r["n_dupes"] == 1


def test_zero_range_counted():
    rows = GOOD_ROWS + [
        {"timestamp": "2026-04-01T10:03:00Z", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 10},
    ]
    df = make_df(rows)
    r = analyze(df, "1m")
    assert r["zero_range"] == 1


def test_missing_ohlc_counted():
    rows = [
        {"timestamp": "2026-04-01T10:00:00Z", "open": None, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100},
        {"timestamp": "2026-04-01T10:01:00Z", "open": 103.0, "high": 107.0, "low": 102.0, "close": 106.0, "volume": 200},
    ]
    df = make_df(rows)
    r = analyze(df, "1m")
    assert r["missing_ohlc"] == 1


def test_large_gap_detected():
    rows = [
        {"timestamp": "2026-04-01T10:00:00Z", "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100},
        # Gap of 30 minutes — much larger than 1m expected
        {"timestamp": "2026-04-01T10:30:00Z", "open": 103.0, "high": 107.0, "low": 102.0, "close": 106.0, "volume": 200},
        {"timestamp": "2026-04-01T10:31:00Z", "open": 106.0, "high": 108.0, "low": 105.0, "close": 107.0, "volume": 150},
    ]
    df = make_df(rows)
    r = analyze(df, "1m")
    assert len(r["gaps"]) >= 1


def test_no_gap_when_continuous():
    df = make_df(GOOD_ROWS)
    r = analyze(df, "1m")
    assert r["gaps"] == []


def test_markdown_contains_required_sections():
    df = make_df(GOOD_ROWS)
    r = analyze(df, "1m")
    md = build_markdown(r, "test.csv")
    assert "# Data Quality Report" in md
    assert "## Summary" in md
    assert "## Time gaps" in md
    assert "## Notes" in md


def test_load_debug_csv_missing_file():
    with pytest.raises(FileNotFoundError):
        load_candle_csv("/nonexistent/file.csv")


def test_load_debug_csv_missing_columns():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("timestamp,open\n2026-04-01,100\n")
        path = f.name
    try:
        with pytest.raises(ValueError, match="missing required columns"):
            load_candle_csv(path)
    finally:
        os.unlink(path)
