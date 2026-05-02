"""Fetch recent closed candles for paper trading."""
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd


def fetch_recent_candles(
    ticker: str,
    class_code: str,
    timeframe: str,
    lookback_minutes: int,
    env: str = "prod",
) -> tuple[pd.DataFrame, Optional[float]]:
    """Fetch recent closed candles via T-Bank API.

    Returns (candles_df, min_price_increment).
    candles_df contains only closed candles (current in-progress candle excluded).
    """
    from src.tbank.settings import load_tbank_settings
    from src.tbank.client import get_tbank_client
    from src.tbank.instruments import resolve_instrument
    from src.tbank.candles import fetch_historical_candles

    settings = load_tbank_settings(env)
    now = datetime.now(tz=timezone.utc)

    # Use candle-aligned boundaries: exclude the currently forming candle
    # by setting end to the start of the current minute
    end = now.replace(second=0, microsecond=0)
    start = end - timedelta(minutes=lookback_minutes)

    with get_tbank_client(settings) as client:
        instrument = resolve_instrument(client, ticker, class_code)
        uid = instrument["uid"]
        min_price_increment = instrument.get("min_price_increment")
        df = fetch_historical_candles(client, uid, start, end, timeframe)

    if df.empty:
        return df, min_price_increment

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df, min_price_increment
