import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from src.tbank.settings import load_tbank_settings
from src.tbank.client import get_tbank_client
from src.tbank.instruments import resolve_instrument
from src.tbank.candles import fetch_historical_candles

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _parse_date_arg(s: str) -> datetime:
    """Parse YYYY-MM-DD or ISO datetime string into a timezone-aware datetime (Moscow)."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=MOSCOW_TZ)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date/time: '{s}'. Expected YYYY-MM-DD or ISO format.")


def load_tbank_candles_to_csv(
    ticker: str,
    start: str,
    end: str,
    timeframe: str,
    output: str,
    env: str = "prod",
    class_code: str = "SPBFUT",
) -> str:
    settings = load_tbank_settings(env)
    start_dt = _parse_date_arg(start)
    end_dt = _parse_date_arg(end)

    with get_tbank_client(settings) as client:
        instrument = resolve_instrument(client, ticker, class_code)
        uid = instrument["uid"]

        print(f"Instrument UID: {uid}")
        print(f"Name: {instrument['name']}")

        df = fetch_historical_candles(client, uid, start_dt, end_dt, timeframe)

    print(f"Candles loaded: {len(df)}")

    os.makedirs(os.path.dirname(output) if os.path.dirname(output) else ".", exist_ok=True)
    df.to_csv(output, index=False)
    return output
