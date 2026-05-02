import pandas as pd
import pytest

from src.backtest.periods import add_moscow_timestamp, assign_period


def _df(timestamps):
    return pd.DataFrame({"timestamp": timestamps})


# --- UTC → MSK conversion ---

def test_utc_to_msk_hour():
    # 2026-04-01 21:30:00 UTC = 2026-04-02 00:30:00 MSK (UTC+3)
    df = _df(["2026-04-01 21:30:00+00:00"])
    result = add_moscow_timestamp(df)
    ts = result["timestamp_msk"].iloc[0]
    assert ts.day == 2
    assert ts.hour == 0
    assert ts.minute == 30


def test_utc_to_msk_date_change():
    # UTC 21:00 of April 1 becomes April 2 in MSK
    df = _df(["2026-04-01 21:00:00+00:00"])
    result = add_moscow_timestamp(df)
    ts = result["timestamp_msk"].iloc[0]
    assert ts.strftime("%Y-%m-%d") == "2026-04-02"


# --- Day period key uses MSK ---

def test_day_period_key_is_msk_not_utc():
    # UTC 2026-04-01 21:30:00 = MSK 2026-04-02 00:30:00
    # period=day should give "2026-04-02" NOT "2026-04-01"
    df = _df(["2026-04-01 21:30:00+00:00"])
    result = assign_period(df, "day")
    assert result["period_key"].iloc[0] == "2026-04-02"


def test_day_period_key_midday():
    # UTC 2026-04-05 10:00:00 = MSK 2026-04-05 13:00:00 → same day
    df = _df(["2026-04-05 10:00:00+00:00"])
    result = assign_period(df, "day")
    assert result["period_key"].iloc[0] == "2026-04-05"


# --- Week period key ---

def test_week_period_key():
    # April 1, 2026 MSK (Wednesday) is ISO week 14
    df = _df(["2026-04-01 10:00:00+00:00"])  # 13:00 MSK = same day
    result = assign_period(df, "week")
    assert result["period_key"].iloc[0] == "2026-W14"


def test_week_period_key_monday():
    # April 6, 2026 MSK (Monday) is ISO week 15
    df = _df(["2026-04-06 10:00:00+00:00"])
    result = assign_period(df, "week")
    assert result["period_key"].iloc[0] == "2026-W15"


def test_week_period_start_is_monday():
    # Week 14 starts on Monday March 30, 2026
    df = _df(["2026-04-01 10:00:00+00:00"])
    result = assign_period(df, "week")
    start = result["period_start"].iloc[0]
    assert start.weekday() == 0  # Monday
    assert start.hour == 0 and start.minute == 0


# --- Month period key ---

def test_month_period_key():
    df = _df(["2026-04-15 10:00:00+00:00"])
    result = assign_period(df, "month")
    assert result["period_key"].iloc[0] == "2026-04"


def test_month_period_key_different_month():
    df = _df(["2026-03-31 22:30:00+00:00"])  # = 2026-04-01 01:30 MSK → April
    result = assign_period(df, "month")
    assert result["period_key"].iloc[0] == "2026-04"


# --- Naive datetime treated as MSK ---

def test_naive_datetime_localized_as_msk():
    df = _df(["2026-04-01 10:00:00"])  # naive
    result = add_moscow_timestamp(df)
    ts = result["timestamp_msk"].iloc[0]
    assert str(ts.tz) == "Europe/Moscow"
    assert ts.hour == 10


def test_naive_day_period_key():
    df = _df(["2026-04-05 13:00:00"])  # naive = MSK 13:00
    result = assign_period(df, "day")
    assert result["period_key"].iloc[0] == "2026-04-05"


# --- Invalid period raises ---

def test_invalid_period_raises():
    df = _df(["2026-04-01 10:00:00+00:00"])
    with pytest.raises(ValueError):
        assign_period(df, "quarter")
