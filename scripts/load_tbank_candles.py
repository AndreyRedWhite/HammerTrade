"""
CLI script for downloading historical candles from T-Bank API.
Usage:
  python scripts/load_tbank_candles.py \
    --ticker SiM6 --class-code SPBFUT \
    --from 2026-04-01 --to 2026-04-10 \
    --timeframe 1m --env prod \
    --output data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.market_data.tbank_loader import load_tbank_candles_to_csv, _parse_date_arg


def main():
    parser = argparse.ArgumentParser(
        description="T-Bank historical candles loader (read-only, no live trading)"
    )
    parser.add_argument("--ticker", required=True, help="Futures ticker, e.g. SiM6")
    parser.add_argument("--class-code", default="SPBFUT", help="Class code (default: SPBFUT)")
    parser.add_argument("--from", dest="from_date", required=True, metavar="DATE",
                        help="Start date YYYY-MM-DD (inclusive, Moscow time)")
    parser.add_argument("--to", dest="to_date", required=True, metavar="DATE",
                        help="End date YYYY-MM-DD (exclusive, Moscow time)")
    parser.add_argument("--timeframe", default="1m",
                        choices=["1m", "5m", "15m", "1h", "1d"],
                        help="Candle timeframe (default: 1m)")
    parser.add_argument("--env", default="prod", choices=["prod", "sandbox"],
                        help="API environment (default: prod)")
    parser.add_argument("--output", required=True, help="Output CSV path")
    args = parser.parse_args()

    from_dt = _parse_date_arg(args.from_date)
    to_dt = _parse_date_arg(args.to_date)

    print("T-Bank candles loader")
    print("=====================")
    print()
    print(f"Environment:  {args.env}")
    print(f"Ticker:       {args.ticker}")
    print(f"Class code:   {args.class_code}")
    print(f"Timeframe:    {args.timeframe}")
    print(f"From:         {from_dt.isoformat()}")
    print(f"To:           {to_dt.isoformat()}")
    print()

    try:
        output = load_tbank_candles_to_csv(
            ticker=args.ticker,
            start=args.from_date,
            end=args.to_date,
            timeframe=args.timeframe,
            output=args.output,
            env=args.env,
            class_code=args.class_code,
        )
        print(f"Output:       {output}")
    except (FileNotFoundError, ValueError, RuntimeError, ImportError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
