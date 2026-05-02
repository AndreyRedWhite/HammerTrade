import re
import time
import warnings
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from src.tbank.money import quotation_to_float

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

CHUNK_SIZES: dict[str, timedelta] = {
    "1m":  timedelta(days=1),
    "5m":  timedelta(days=7),
    "15m": timedelta(days=21),
    "1h":  timedelta(days=90),
    "1d":  timedelta(days=365 * 6),
}

_INTERVAL_MAP: dict[str, str] = {
    "1m":  "CANDLE_INTERVAL_1_MIN",
    "5m":  "CANDLE_INTERVAL_5_MIN",
    "15m": "CANDLE_INTERVAL_15_MIN",
    "1h":  "CANDLE_INTERVAL_HOUR",
    "1d":  "CANDLE_INTERVAL_DAY",
}

EMPTY_CANDLES_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def get_interval_config(timeframe: str) -> dict:
    if timeframe not in CHUNK_SIZES:
        raise ValueError(
            f"Unsupported timeframe '{timeframe}'. "
            f"Supported: {sorted(CHUNK_SIZES.keys())}"
        )
    return {
        "timeframe": timeframe,
        "chunk_size": CHUNK_SIZES[timeframe],
        "interval_name": _INTERVAL_MAP[timeframe],
    }


def _ensure_aware(dt: datetime, tz=MOSCOW_TZ) -> datetime:
    if dt.tzinfo is None:
        raise ValueError(
            f"Naive datetime provided: {dt!r}. "
            "Please pass timezone-aware datetime (e.g., use Europe/Moscow timezone)."
        )
    return dt


def build_time_chunks(
    start: datetime,
    end: datetime,
    timeframe: str,
) -> list[tuple[datetime, datetime]]:
    start = _ensure_aware(start)
    end = _ensure_aware(end)

    if start >= end:
        raise ValueError(
            f"start ({start.isoformat()}) must be before end ({end.isoformat()})"
        )

    chunk_size = CHUNK_SIZES[timeframe]
    chunks = []
    current = start

    while current < end:
        chunk_end = min(current + chunk_size, end)
        chunks.append((current, chunk_end))
        current = chunk_end

    return chunks


def _candle_to_row(candle) -> dict:
    return {
        "timestamp": candle.time,
        "open":   quotation_to_float(candle.open),
        "high":   quotation_to_float(candle.high),
        "low":    quotation_to_float(candle.low),
        "close":  quotation_to_float(candle.close),
        "volume": candle.volume,
    }


_MAX_RETRIES = 3


def _fetch_chunk_with_retry(client, instrument_uid, chunk_start, chunk_end, interval, all_rows):
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = client.market_data.get_candles(
                instrument_id=instrument_uid,
                from_=chunk_start,
                to=chunk_end,
                interval=interval,
            )
            for candle in resp.candles:
                all_rows.append(_candle_to_row(candle))
            return
        except Exception as e:
            s = str(e)
            if "RESOURCE_EXHAUSTED" in s and attempt < _MAX_RETRIES:
                m = re.search(r"ratelimit_reset=(\d+)", s)
                wait = int(m.group(1)) + 2 if m else 60
                warnings.warn(
                    f"Rate limit hit, waiting {wait}s "
                    f"(attempt {attempt + 1}/{_MAX_RETRIES})..."
                )
                time.sleep(wait)
                continue
            warnings.warn(
                f"Failed to fetch chunk "
                f"{chunk_start.isoformat()} - {chunk_end.isoformat()}: {e}"
            )
            return


def fetch_historical_candles(
    client,
    instrument_uid: str,
    start: datetime,
    end: datetime,
    timeframe: str,
) -> pd.DataFrame:
    try:
        from t_tech.invest import CandleInterval
    except ImportError:
        from src.tbank.client import _SDK_INSTALL_HINT
        raise ImportError(_SDK_INSTALL_HINT)

    config = get_interval_config(timeframe)
    interval = getattr(CandleInterval, config["interval_name"])

    start = _ensure_aware(start)
    end = _ensure_aware(end)

    chunks = build_time_chunks(start, end, timeframe)
    all_rows: list[dict] = []

    for chunk_start, chunk_end in chunks:
        _fetch_chunk_with_retry(
            client, instrument_uid, chunk_start, chunk_end, interval, all_rows
        )

    if not all_rows:
        warnings.warn(
            f"No candles returned for {instrument_uid} "
            f"{start.isoformat()} — {end.isoformat()} [{timeframe}]"
        )
        return pd.DataFrame(columns=EMPTY_CANDLES_COLUMNS)

    df = pd.DataFrame(all_rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
    return df
