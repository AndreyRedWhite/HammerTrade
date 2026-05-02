#!/usr/bin/env python3
"""Scan SPBFUT for liquid futures and generate a universe report."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from datetime import datetime, timezone


def parse_args():
    p = argparse.ArgumentParser(
        description="Scan liquid futures universe — offline research, no real orders"
    )
    p.add_argument("--from", dest="start", required=True, metavar="YYYY-MM-DD")
    p.add_argument("--to", dest="end", required=True, metavar="YYYY-MM-DD")
    p.add_argument("--class-code", default="SPBFUT")
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--sample-days", type=int, default=5)
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--env", choices=["prod", "sandbox"], default="prod")
    p.add_argument("--output", default=None, help="CSV output path")
    p.add_argument("--report-output", default=None, help="Markdown report path")
    return p.parse_args()


def main():
    args = parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)

    run_id = f"{args.start}_{args.end}"
    output = args.output or f"data/instruments/liquid_futures_{run_id}.csv"
    report_output = args.report_output or f"reports/liquid_futures_{run_id}.md"

    from src.tbank.settings import load_tbank_settings
    from src.tbank.client import get_tbank_client
    from src.tbank.liquidity_universe import (
        fetch_available_futures,
        filter_active_futures,
        estimate_futures_liquidity,
        generate_universe_report,
    )

    settings = load_tbank_settings(env=args.env)
    with get_tbank_client(settings) as client:
        print(f"Fetching futures list for {args.class_code}...")
        futures_df = fetch_available_futures(client, class_code=args.class_code)
        print(f"Found {len(futures_df)} futures total")

        active_df = filter_active_futures(futures_df, start, end)
        print(f"Active in period: {len(active_df)}")

        print(f"Estimating liquidity (sample_days={args.sample_days})...")
        liquidity_df = estimate_futures_liquidity(
            client=client,
            futures_df=active_df,
            start=start,
            end=end,
            timeframe=args.timeframe,
            sample_days=args.sample_days,
        )

    top_df = liquidity_df.head(args.top)

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    liquidity_df.to_csv(output, index=False)

    params = {
        "Class code": args.class_code,
        "Period": f"{args.start} -> {args.end}",
        "Timeframe": args.timeframe,
        "Sample days": args.sample_days,
        "Top N": args.top,
    }
    generate_universe_report(top_df, report_output, params)

    print()
    print("Top liquid futures")
    print("==================")
    print()
    for _, row in top_df.iterrows():
        rank = row.get("rank", "")
        ticker = row.get("ticker", "")
        score = row.get("activity_score", 0)
        pv = row.get("point_value_rub", "?")
        print(f"  {rank:>2}. {ticker:<10}  score={score:.0f}  point_value_rub={pv}")

    print()
    print(f"CSV output:    {output}")
    print(f"Report output: {report_output}")


if __name__ == "__main__":
    main()
