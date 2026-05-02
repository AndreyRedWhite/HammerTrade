"""Tests for build_time_chunks — pure logic, no SDK required."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.tbank.candles import build_time_chunks, CHUNK_SIZES

MSK = ZoneInfo("Europe/Moscow")


def msk(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=MSK)


def test_1m_three_days_gives_three_chunks():
    start = msk(2026, 4, 1)
    end = msk(2026, 4, 4)  # 3 days
    chunks = build_time_chunks(start, end, "1m")
    assert len(chunks) == 3
    for chunk_start, chunk_end in chunks:
        assert (chunk_end - chunk_start) == timedelta(days=1)


def test_5m_fifteen_days_chunks_max_seven_days():
    start = msk(2026, 4, 1)
    end = msk(2026, 4, 16)  # 15 days
    chunks = build_time_chunks(start, end, "5m")
    for chunk_start, chunk_end in chunks:
        assert (chunk_end - chunk_start) <= CHUNK_SIZES["5m"]


def test_last_chunk_ends_exactly_at_end():
    start = msk(2026, 4, 1)
    end = msk(2026, 4, 9)  # 8 days → for 1m: 8 chunks
    chunks = build_time_chunks(start, end, "1m")
    assert chunks[-1][1] == end


def test_chunks_do_not_overlap():
    start = msk(2026, 4, 1)
    end = msk(2026, 4, 10)
    chunks = build_time_chunks(start, end, "1m")
    for i in range(len(chunks) - 1):
        assert chunks[i][1] == chunks[i + 1][0]


def test_start_equals_end_raises():
    dt = msk(2026, 4, 1)
    with pytest.raises(ValueError, match="must be before"):
        build_time_chunks(dt, dt, "1m")


def test_start_after_end_raises():
    with pytest.raises(ValueError, match="must be before"):
        build_time_chunks(msk(2026, 4, 5), msk(2026, 4, 1), "1m")


def test_naive_datetime_raises():
    naive = datetime(2026, 4, 1, 10, 0)
    aware = msk(2026, 4, 5)
    with pytest.raises(ValueError, match="Naive datetime"):
        build_time_chunks(naive, aware, "1m")


def test_single_chunk_within_limit():
    start = msk(2026, 4, 1, 10, 0)
    end = msk(2026, 4, 1, 11, 0)  # 1 hour, fits in 1-day chunk for 1m
    chunks = build_time_chunks(start, end, "1m")
    assert len(chunks) == 1
    assert chunks[0] == (start, end)


def test_1h_chunk_max_90_days():
    start = msk(2026, 1, 1)
    end = msk(2026, 6, 1)  # ~151 days
    chunks = build_time_chunks(start, end, "1h")
    for s, e in chunks:
        assert (e - s) <= CHUNK_SIZES["1h"]
    assert chunks[-1][1] == end
