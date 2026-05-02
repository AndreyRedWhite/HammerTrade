import argparse
import sys

from src.config import load_params
from src.market_data.loader import load_candles
from src.strategy.hammer_detector import HammerDetector
from src.storage.debug_repository import save_debug_csv
from src.analytics.summary import print_summary


def parse_args():
    parser = argparse.ArgumentParser(description="MOEXF Hammer Bot — MVP-0 Explainable Detector")
    parser.add_argument("--input", required=True, help="Path to input CSV with candles")
    parser.add_argument("--output", required=True, help="Path to output debug CSV")
    parser.add_argument("--params", required=True, help="Path to .env config file")
    parser.add_argument("--instrument", default="", help="Instrument name (e.g. SiM6)")
    parser.add_argument("--timeframe", default="", help="Timeframe (e.g. 1m)")
    parser.add_argument("--profile", default="", help="Profile name for labeling")
    parser.add_argument("--tick-size", default=None,
                        help="Instrument tick size (min_price_increment), or 'auto' to use S_FALLBACK_TICK. Default: use S_FALLBACK_TICK from config.")
    parser.add_argument("--tick-size-source", default="cli",
                        help="Source label for tick_size: cli|specs|fallback|user")
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        params = load_params(args.params)
    except Exception as e:
        print(f"ERROR loading params: {e}", file=sys.stderr)
        sys.exit(1)

    if args.tick_size is not None and args.tick_size != "auto":
        try:
            tick_size_val = float(args.tick_size)
        except ValueError:
            print(f"ERROR: --tick-size must be a number or 'auto', got '{args.tick_size}'", file=sys.stderr)
            sys.exit(1)
        if tick_size_val <= 0:
            print(f"ERROR: --tick-size must be > 0, got {tick_size_val}", file=sys.stderr)
            sys.exit(1)
        params.tick_size = tick_size_val
        params.tick_size_source = args.tick_size_source

    print(f"Tick size:        {params.effective_tick_size}")
    print(f"Tick size source: {params.tick_size_source}")

    try:
        candles = load_candles(args.input)
    except Exception as e:
        print(f"ERROR loading candles: {e}", file=sys.stderr)
        sys.exit(1)

    detector = HammerDetector(params)
    result_df = detector.detect_all(
        candles,
        instrument=args.instrument,
        timeframe=args.timeframe,
        profile=args.profile,
    )

    save_debug_csv(result_df, args.output)
    print_summary(result_df, args.output)


if __name__ == "__main__":
    main()
