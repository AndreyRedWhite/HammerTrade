import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

from src.risk.clearing import is_near_clearing

UTC = ZoneInfo("UTC")
MSK = ZoneInfo("Europe/Moscow")


# --- helpers ---

def msk(hour, minute):
    """Naive Moscow timestamp (treated as MSK by clearing module)."""
    return pd.Timestamp(f"2026-04-01 {hour:02d}:{minute:02d}:00")


def utc_dt(hour, minute):
    return datetime(2026, 4, 1, hour, minute, tzinfo=UTC)


def msk_dt(hour, minute):
    return datetime(2026, 4, 1, hour, minute, tzinfo=MSK)


# --- existing naive MSK tests (must keep passing) ---

def test_inside_clearing_1_before():
    assert is_near_clearing(msk(13, 51))


def test_inside_clearing_1_exact():
    assert is_near_clearing(msk(13, 55))


def test_inside_clearing_1_after():
    assert is_near_clearing(msk(13, 59))


def test_inside_clearing_2_before():
    assert is_near_clearing(msk(18, 41))


def test_inside_clearing_2_exact():
    assert is_near_clearing(msk(18, 45))


def test_inside_clearing_2_after():
    assert is_near_clearing(msk(18, 49))


def test_outside_clearing_morning():
    assert not is_near_clearing(msk(10, 0))


def test_outside_clearing_midday():
    assert not is_near_clearing(msk(12, 0))


def test_outside_clearing_afternoon():
    assert not is_near_clearing(msk(15, 30))


def test_boundary_just_outside_clearing_1():
    assert not is_near_clearing(msk(13, 49))


def test_boundary_just_outside_clearing_1_after():
    assert not is_near_clearing(msk(14, 1))


# --- UTC datetime tests (main bug fix) ---

def test_utc_daily_clearing_exact():
    # 10:55 UTC = 13:55 MSK
    assert is_near_clearing(utc_dt(10, 55))


def test_utc_daily_clearing_block_start():
    # 10:50 UTC = 13:50 MSK (5 min before)
    assert is_near_clearing(utc_dt(10, 50))


def test_utc_daily_clearing_block_end():
    # 11:00 UTC = 14:00 MSK (5 min after)
    assert is_near_clearing(utc_dt(11, 0))


def test_utc_daily_clearing_outside():
    # 11:01 UTC = 14:01 MSK (6 min after — outside)
    assert not is_near_clearing(utc_dt(11, 1))


def test_utc_evening_clearing_exact():
    # 15:45 UTC = 18:45 MSK
    assert is_near_clearing(utc_dt(15, 45))


def test_utc_evening_clearing_block_start():
    # 15:40 UTC = 18:40 MSK
    assert is_near_clearing(utc_dt(15, 40))


def test_utc_evening_clearing_block_end():
    # 15:50 UTC = 18:50 MSK
    assert is_near_clearing(utc_dt(15, 50))


def test_utc_evening_clearing_outside():
    # 15:51 UTC = 18:51 MSK (outside)
    assert not is_near_clearing(utc_dt(15, 51))


# --- Naive datetime (treated as MSK) ---

def test_naive_daily_clearing():
    assert is_near_clearing(datetime(2026, 4, 1, 13, 55))


def test_naive_outside():
    assert not is_near_clearing(datetime(2026, 4, 1, 10, 0))


# --- Already Moscow timezone ---

def test_msk_aware_clearing():
    assert is_near_clearing(msk_dt(13, 55))


def test_msk_aware_outside():
    assert not is_near_clearing(msk_dt(10, 0))
