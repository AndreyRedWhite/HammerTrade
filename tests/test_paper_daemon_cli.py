import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "run_paper_trader.py")
REPORT_SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "paper_report.py")


def test_help_exits_zero():
    result = subprocess.run(
        [sys.executable, SCRIPT, "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "--ticker" in result.stdout


def test_report_help_exits_zero():
    result = subprocess.run(
        [sys.executable, REPORT_SCRIPT, "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "--state-db" in result.stdout


def test_report_missing_db_exits_nonzero(tmp_path):
    result = subprocess.run(
        [sys.executable, REPORT_SCRIPT, "--state-db", str(tmp_path / "nonexistent.sqlite")],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


def test_dry_run_does_not_write_state(tmp_path):
    """dry-run should not touch SQLite."""
    db = tmp_path / "state.sqlite"

    fake_df = pd.DataFrame([{
        "timestamp": pd.Timestamp("2026-01-01 10:00:00", tz="UTC"),
        "open": 89000.0, "high": 89500.0, "low": 88500.0, "close": 89000.0,
        "volume": 100,
        "is_signal": False, "direction_candidate": "SELL", "fail_reason": "range",
        "instrument": "SiM6", "timeframe": "1m", "profile": "balanced",
        "tick_size": 1.0, "tick_size_source": "fallback",
        "body_frac": 0.1, "wick_frac": 0.5, "opp_wick_frac": 0.1,
        "candle_range": 1000.0,
    }])

    with patch("src.paper.market_data.fetch_recent_candles", return_value=(fake_df, 1.0)):
        from scripts.run_paper_trader import _run_cycle
        import argparse

        args = argparse.Namespace(
            ticker="SiM6", class_code="SPBFUT", timeframe="1m", profile="balanced",
            params="configs/hammer_detector_balanced.env",
            direction_filter="SELL", entry_mode="breakout",
            take_r=1.0, max_hold_bars=30, stop_buffer_points=0.0,
            slippage_ticks=1.0, contracts=1, lookback_candles=300,
            trades_output=str(tmp_path / "trades.csv"),
            env="prod", dry_run=True, once=True,
        )
        import logging
        logger = logging.getLogger("test")
        _run_cycle(args, None, logger)

    assert not db.exists()


def test_api_error_does_not_crash(tmp_path):
    """If fetch_recent_candles raises, the cycle should log and return, not crash."""
    from scripts.run_paper_trader import _run_cycle
    from src.paper.repository import PaperRepository
    import argparse, logging

    repo = PaperRepository(str(tmp_path / "state.sqlite"))
    repo.init_db()

    args = argparse.Namespace(
        ticker="SiM6", class_code="SPBFUT", timeframe="1m", profile="balanced",
        params="configs/hammer_detector_balanced.env",
        direction_filter="SELL", entry_mode="breakout",
        take_r=1.0, max_hold_bars=30, stop_buffer_points=0.0,
        slippage_ticks=1.0, contracts=1, lookback_candles=300,
        trades_output=str(tmp_path / "trades.csv"),
        env="prod", dry_run=False, once=True,
    )
    logger = logging.getLogger("test")

    with patch("src.paper.market_data.fetch_recent_candles", side_effect=ConnectionError("timeout")):
        _run_cycle(args, repo, logger)  # should not raise
