import os
import tempfile
import pandas as pd
import pytest
from src.analytics.debug_report import load_debug_csv, build_report, build_markdown


def make_debug_df(rows):
    base = {
        "instrument": "TEST",
        "timeframe": "1m",
        "open": 100.0,
        "high": 110.0,
        "low": 90.0,
        "close": 105.0,
        "volume": 500,
        "range": 20.0,
        "body": 5.0,
        "upper_shadow": 5.0,
        "lower_shadow": 10.0,
        "body_frac": 0.25,
        "upper_frac": 0.25,
        "lower_frac": 0.50,
        "close_pos": 0.75,
        "fail_reasons": "pass",
        "params_profile": "balanced",
    }
    records = [{**base, **r} for r in rows]
    df = pd.DataFrame(records)
    df["timestamp"] = pd.date_range("2024-01-01 10:00", periods=len(df), freq="1min")
    df["is_signal"] = df["is_signal"].astype(bool)
    return df


SAMPLE_ROWS = [
    {"direction_candidate": "BUY", "is_signal": True, "fail_reason": "pass"},
    {"direction_candidate": "BUY", "is_signal": False, "fail_reason": "doji"},
    {"direction_candidate": "BUY", "is_signal": False, "fail_reason": "ext"},
    {"direction_candidate": "SELL", "is_signal": True, "fail_reason": "pass"},
    {"direction_candidate": "SELL", "is_signal": False, "fail_reason": "dom_fail"},
]


def test_report_row_count():
    df = make_debug_df(SAMPLE_ROWS)
    r = build_report(df)
    assert r["total"] == 5


def test_report_signal_count():
    df = make_debug_df(SAMPLE_ROWS)
    r = build_report(df)
    assert r["n_signals"] == 2
    assert r["n_buy"] == 1
    assert r["n_sell"] == 1


def test_fail_reason_distribution():
    df = make_debug_df(SAMPLE_ROWS)
    r = build_report(df)
    fail_counts = r["fail_counts"]
    assert fail_counts["doji"] == 1
    assert fail_counts["ext"] == 1
    assert fail_counts["dom_fail"] == 1


def test_report_created_when_no_signals():
    rows = [
        {"direction_candidate": "BUY", "is_signal": False, "fail_reason": "doji"},
        {"direction_candidate": "SELL", "is_signal": False, "fail_reason": "ext"},
    ]
    df = make_debug_df(rows)
    r = build_report(df)
    assert r["n_signals"] == 0

    md = build_markdown(r, "test_input.csv")
    assert "# Hammer Detector Debug Report" in md
    assert "_No signals detected._" in md


def test_markdown_report_file_created():
    df = make_debug_df(SAMPLE_ROWS)
    r = build_report(df)
    md = build_markdown(r, "test_input.csv")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(md)
        path = f.name

    try:
        assert os.path.exists(path)
        content = open(path).read()
        assert "Rows processed" in content
        assert "fail_reason" in content
        assert "BUY candidates" in content
        assert "SELL candidates" in content
    finally:
        os.unlink(path)


def test_load_debug_csv_missing_file():
    from src.analytics.debug_report import load_debug_csv
    with pytest.raises(FileNotFoundError):
        load_debug_csv("/nonexistent/path/file.csv")


def test_load_debug_csv_missing_columns():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("timestamp,open\n2024-01-01,100\n")
        path = f.name
    try:
        with pytest.raises(ValueError, match="missing required columns"):
            load_debug_csv(path)
    finally:
        os.unlink(path)
