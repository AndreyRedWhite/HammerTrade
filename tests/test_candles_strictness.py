"""A gapped candle series must fail loudly, not arrive silently."""
import warnings

import pytest

from src.tbank.candles import IncompleteCandleHistory, _fetch_chunk_with_retry


class _FailingClient:
    class market_data:
        @staticmethod
        def get_candles(**kw):
            raise RuntimeError("UNAVAILABLE: upstream said no")


def _args():
    from datetime import datetime, timezone
    a = datetime(2026, 1, 1, tzinfo=timezone.utc)
    b = datetime(2026, 1, 2, tzinfo=timezone.utc)
    return _FailingClient(), "uid", a, b, "INTERVAL"


def test_strict_mode_raises_on_a_failed_chunk():
    """Nothing downstream can detect a hole, so the fetch itself must refuse."""
    client, uid, a, b, iv = _args()
    rows = []
    with pytest.raises(IncompleteCandleHistory, match="Failed to fetch chunk"):
        _fetch_chunk_with_retry(client, uid, a, b, iv, rows, strict=True)


def test_strict_is_the_default():
    client, uid, a, b, iv = _args()
    rows = []
    with pytest.raises(IncompleteCandleHistory):
        _fetch_chunk_with_retry(client, uid, a, b, iv, rows)


def test_non_strict_mode_warns_and_says_the_series_has_a_gap():
    """The escape hatch must announce the damage, not just continue."""
    client, uid, a, b, iv = _args()
    rows = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _fetch_chunk_with_retry(client, uid, a, b, iv, rows, strict=False)
    assert rows == []
    assert any("GAP" in str(w.message) for w in caught)
