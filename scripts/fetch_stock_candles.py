"""Fetch 1m candles for SBER, SBERP, GAZP, LKOH (Jan 15 – Apr 10 2026).

Uses READONLY_TOKEN from .env. Saves to data/raw/tbank/<TICKER>_1m_*.csv
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.tbank.settings import load_tbank_settings
from src.tbank.client import get_tbank_client
from src.tbank.instruments import resolve_instrument
from src.tbank.candles import fetch_historical_candles

import pandas as pd

TICKERS = [
    ("SBER",  "TQBR"),
    ("SBERP", "TQBR"),
    ("GAZP",  "TQBR"),
    ("LKOH",  "TQBR"),
]

FROM_DT = datetime(2026, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
TO_DT   = datetime(2026, 4, 10, 23, 59, 0, tzinfo=timezone.utc)

OUT_DIR = Path("data/raw/tbank")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    settings = load_tbank_settings("prod")
    print(f"Using READONLY_TOKEN (prod), target={settings.target}")

    with get_tbank_client(settings) as client:
        for ticker, class_code in TICKERS:
            print(f"\nFetching {ticker} ({class_code}) {FROM_DT.date()} → {TO_DT.date()}...", flush=True)
            try:
                instrument = resolve_instrument(client, ticker, class_code)
                uid = instrument["uid"]
                print(f"  uid={uid}")
                df = fetch_historical_candles(client, uid, FROM_DT, TO_DT, "1m")
                if df.empty:
                    print(f"  WARNING: 0 candles returned for {ticker}")
                    continue
                out_path = OUT_DIR / f"{ticker}_1m_2026-01-15_2026-04-10.csv"
                df.to_csv(out_path, index=False)
                print(f"  {ticker}: {len(df)} candles → {out_path}")
            except Exception as e:
                print(f"  ERROR {ticker}: {e}")
                import traceback; traceback.print_exc()

    print("\nDone.")


if __name__ == "__main__":
    main()
