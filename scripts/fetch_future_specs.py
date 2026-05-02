#!/usr/bin/env python3
"""Fetch and cache future instrument specifications from T-Bank API."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import warnings

from src.tbank.instrument_specs import (
    fetch_future_spec,
    upsert_future_spec,
    get_cached_future_spec,
    _SPECS_CSV,
)


def parse_args():
    p = argparse.ArgumentParser(
        description="Fetch future instrument specs from T-Bank and save to cache."
    )
    p.add_argument("--ticker", required=True, help="Futures ticker, e.g. SiM6")
    p.add_argument("--class-code", default="SPBFUT")
    p.add_argument("--env", choices=["prod", "sandbox"], default="prod",
                   help="T-Bank environment")
    p.add_argument("--output", default=_SPECS_CSV,
                   help="Path to specs cache CSV")
    p.add_argument("--cache-only", action="store_true",
                   help="Do not call T-Bank API; only read from local cache")
    p.add_argument("--print-point-value", action="store_true",
                   help="Print only the point_value_rub number and exit (for shell use)")
    p.add_argument("--print-tick-size", action="store_true",
                   help="Print only the min_price_increment (tick size) as a bare float and exit (for shell use)")
    return p.parse_args()


def main():
    args = parse_args()

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    # --print-point-value: read from cache only, print bare number
    if args.print_point_value:
        spec = get_cached_future_spec(args.ticker, args.class_code, args.output)
        if spec is not None and spec.point_value_rub is not None:
            print(spec.point_value_rub)
        sys.exit(0)

    # --print-tick-size: read from cache only, print bare min_price_increment
    if args.print_tick_size:
        spec = get_cached_future_spec(args.ticker, args.class_code, args.output)
        if spec is not None and spec.min_price_increment:
            print(spec.min_price_increment)
        sys.exit(0)

    # --cache-only: show cached spec without API call
    if args.cache_only:
        spec = get_cached_future_spec(args.ticker, args.class_code, args.output)
        if spec is None:
            print(f"Not found in cache: {args.ticker} ({args.class_code})")
            print(f"Cache path: {args.output}")
            sys.exit(1)
        _print_spec(spec, args.output)
        sys.exit(0)

    # Normal mode: fetch from T-Bank API
    from src.tbank.settings import load_tbank_settings
    from src.tbank.client import get_tbank_client

    settings = load_tbank_settings(env=args.env)
    with get_tbank_client(settings) as client:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            spec = fetch_future_spec(client, args.ticker, args.class_code)
            for w in caught:
                print(f"WARNING: {w.message}", file=sys.stderr)

    upsert_future_spec(spec, args.output)
    _print_spec(spec, args.output)


def _print_spec(spec, saved_path: str) -> None:
    print()
    print("Future spec")
    print("===========")
    print()
    print(f"Ticker:                    {spec.ticker}")
    print(f"Class code:                {spec.class_code}")
    print(f"UID:                       {spec.uid}")
    print(f"FIGI:                      {spec.figi}")
    print(f"Name:                      {spec.name}")
    print(f"Lot:                       {spec.lot}")
    print(f"Currency:                  {spec.currency}")
    print(f"Min price increment:       {spec.min_price_increment}")
    print(f"Min price increment amount:{spec.min_price_increment_amount}")
    print(f"Point value RUB:           {spec.point_value_rub}")
    print(f"Initial margin buy:        {spec.initial_margin_on_buy}")
    print(f"Initial margin sell:       {spec.initial_margin_on_sell}")
    print(f"Expiration date:           {spec.expiration_date}")
    print(f"First trade date:          {spec.first_trade_date}")
    print(f"Last trade date:           {spec.last_trade_date}")
    print(f"First 1min candle date:    {spec.first_1min_candle_date}")
    print(f"First 1day candle date:    {spec.first_1day_candle_date}")
    print(f"API trade available:       {spec.api_trade_available_flag}")
    print(f"Buy available:             {spec.buy_available_flag}")
    print(f"Sell available:            {spec.sell_available_flag}")
    print()
    print(f"Saved to: {saved_path}")
    print()


if __name__ == "__main__":
    main()
