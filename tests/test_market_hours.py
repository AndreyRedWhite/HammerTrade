"""Tests for src/market/market_hours.py"""
import pytest
from datetime import datetime, time
from zoneinfo import ZoneInfo
from pathlib import Path

from src.market.market_hours import (
    MarketSession,
    MarketHoursConfig,
    load_market_hours_config,
    to_market_timezone,
    is_session_open,
    get_session_name,
)

MSK = ZoneInfo("Europe/Moscow")
UTC = ZoneInfo("UTC")

_YAML_CONTENT = """
timezone: Europe/Moscow
weekday_sessions:
  - name: morning
    start: "09:00"
    end: "10:00"
  - name: main
    start: "10:00"
    end: "19:00"
  - name: evening
    start: "19:00"
    end: "23:50"
weekend_sessions:
  - name: weekend
    start: "10:00"
    end: "19:00"
stale_candle_grace_minutes: 3
"""


@pytest.fixture()
def config(tmp_path):
    p = tmp_path / "market_hours.yaml"
    p.write_text(_YAML_CONTENT)
    return load_market_hours_config(p)


# --- load_market_hours_config ---

def test_load_config_timezone(config):
    assert config.timezone == "Europe/Moscow"


def test_load_config_weekday_sessions(config):
    names = [s.name for s in config.weekday_sessions]
    assert names == ["morning", "main", "evening"]


def test_load_config_weekend_sessions(config):
    assert len(config.weekend_sessions) == 1
    assert config.weekend_sessions[0].name == "weekend"


def test_load_config_stale_minutes(config):
    assert config.stale_candle_grace_minutes == 3


def test_load_config_missing_file():
    with pytest.raises(FileNotFoundError):
        load_market_hours_config(Path("/nonexistent/path.yaml"))


# --- to_market_timezone ---

def test_to_market_timezone_converts(config):
    ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    result = to_market_timezone(ts, config)
    assert result.tzinfo is not None
    assert result.hour == 13  # UTC+3


def test_to_market_timezone_naive_raises(config):
    ts = datetime(2024, 1, 15, 10, 0, 0)  # naive
    with pytest.raises(ValueError, match="timezone-aware"):
        to_market_timezone(ts, config)


# --- is_session_open (weekday) ---

def test_is_session_open_during_main(config):
    # Monday 14:00 MSK = 11:00 UTC
    ts = datetime(2024, 1, 15, 11, 0, 0, tzinfo=UTC)  # Monday
    assert is_session_open(ts, config) is True


def test_is_session_open_during_morning(config):
    # Monday 09:30 MSK = 06:30 UTC
    ts = datetime(2024, 1, 15, 6, 30, 0, tzinfo=UTC)
    assert is_session_open(ts, config) is True


def test_is_session_open_during_evening(config):
    # Monday 20:00 MSK = 17:00 UTC
    ts = datetime(2024, 1, 15, 17, 0, 0, tzinfo=UTC)
    assert is_session_open(ts, config) is True


def test_is_session_closed_overnight(config):
    # Monday 02:00 MSK = 23:00 UTC previous day
    ts = datetime(2024, 1, 14, 23, 0, 0, tzinfo=UTC)  # Sunday night → MSK Monday 02:00
    assert is_session_open(ts, config) is False


# --- is_session_open (weekend) ---

def test_is_session_open_saturday_inside(config):
    # Saturday 14:00 MSK = 11:00 UTC
    ts = datetime(2024, 1, 20, 11, 0, 0, tzinfo=UTC)  # Saturday
    assert is_session_open(ts, config) is True


def test_is_session_open_saturday_outside(config):
    # Saturday 20:00 MSK = 17:00 UTC  — weekend session ends at 19:00
    ts = datetime(2024, 1, 20, 17, 0, 0, tzinfo=UTC)
    assert is_session_open(ts, config) is False


# --- get_session_name ---

def test_get_session_name_main(config):
    ts = datetime(2024, 1, 15, 11, 0, 0, tzinfo=UTC)
    assert get_session_name(ts, config) == "main"


def test_get_session_name_closed(config):
    ts = datetime(2024, 1, 14, 23, 0, 0, tzinfo=UTC)
    assert get_session_name(ts, config) == "closed"


def test_get_session_name_weekend(config):
    ts = datetime(2024, 1, 20, 11, 0, 0, tzinfo=UTC)
    assert get_session_name(ts, config) == "weekend"
