"""Fetch 1m candles for MOEX equities via T-Bank READONLY_TOKEN.

Saves to data/raw/tbank/<TICKER>_1m_<from>_<to>.csv

Examples:
  # default set, Jan15–Apr10
  python scripts/fetch_stock_candles.py
  # custom tickers + dates (e.g. May OOS)
  python scripts/fetch_stock_candles.py --tickers SBER,SBERP --from 2026-05-01 --to 2026-05-30
"""
import argparse
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

OUT_DIR = Path("data/raw/tbank")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch MOEX equity 1m candles (READONLY_TOKEN).")
    p.add_argument("--tickers", default="SBER,SBERP,GAZP,LKOH",
                   help="Comma-separated tickers (all assumed TQBR class).")
    p.add_argument("--class-code", default="TQBR")
    p.add_argument("--from", dest="from_date", default="2026-01-15", help="YYYY-MM-DD (UTC)")
    p.add_argument("--to", dest="to_date", default="2026-04-10", help="YYYY-MM-DD (UTC)")
    p.add_argument("--timeframe", default="1m")
    return p.parse_args()


def main():
    args = _parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from_dt = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    to_dt = datetime.strptime(args.to_date, "%Y-%m-%d").replace(
        hour=23, minute=59, tzinfo=timezone.utc)
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]

    settings = load_tbank_settings("prod")
    print(f"Using READONLY_TOKEN (prod), target={settings.target}")

    with get_tbank_client(settings) as client:
        for ticker in tickers:
            print(f"\nFetching {ticker} ({args.class_code}) {from_dt.date()} → {to_dt.date()}...",
                  flush=True)
            try:
                instrument = resolve_instrument(client, ticker, args.class_code)
                uid = instrument["uid"]
                print(f"  uid={uid}")
                df = fetch_historical_candles(client, uid, from_dt, to_dt, args.timeframe)
                if df.empty:
                    print(f"  WARNING: 0 candles returned for {ticker}")
                    continue
                out_path = OUT_DIR / f"{ticker}_{args.timeframe}_{args.from_date}_{args.to_date}.csv"
                df.to_csv(out_path, index=False)
                print(f"  {ticker}: {len(df)} candles → {out_path}")
            except Exception as e:
                print(f"  ERROR {ticker}: {e}")
                import traceback; traceback.print_exc()

    print("\nDone.")


if __name__ == "__main__":
    main()
