#!/usr/bin/env python3
"""Batch research runner: reads a liquid futures universe CSV and runs full pipeline per ticker."""
import sys
import subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

import pandas as pd

_PIPELINE = str(Path(__file__).resolve().parent / "run_full_research_pipeline.sh")


def parse_args():
    p = argparse.ArgumentParser(
        description="Batch research runner for liquid futures universe. Does NOT auto-run."
    )
    p.add_argument("--universe", required=True,
                   help="CSV from scan_liquid_futures.py")
    p.add_argument("--top", type=int, default=5,
                   help="Number of top tickers to process")
    p.add_argument("--from", dest="start", required=True, metavar="YYYY-MM-DD")
    p.add_argument("--to", dest="end", required=True, metavar="YYYY-MM-DD")
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--profile", default="balanced")
    p.add_argument("--env", choices=["prod", "sandbox"], default="prod")
    p.add_argument("--class-code", default="SPBFUT")
    p.add_argument("--slippage-points", default="0")
    p.add_argument("--grid-slippage-ticks-values", default="0,1,2,5",
                   help="Grid slippage values in ticks, passed to pipeline. Default: 0,1,2,5")
    p.add_argument("--take-r", default="1.0")
    p.add_argument("--max-hold-bars", default="30")
    p.add_argument("--direction-filter", choices=["all", "BUY", "SELL"], default="all")
    p.add_argument("--skip-walkforward-grid", action="store_true")
    p.add_argument("--skip-grid", action="store_true")
    p.add_argument("--skip-load", action="store_true",
                   help="Do not call T-Bank API inside each pipeline; use existing raw CSV files.")
    p.add_argument("--no-archive", action="store_true")
    p.add_argument("--yes", action="store_true",
                   help="Skip confirmation and run immediately")
    return p.parse_args()


def build_command(ticker: str, point_value_rub, tick_size, args) -> list:
    cmd = ["bash", _PIPELINE]
    cmd += ["--ticker", ticker]
    cmd += ["--class-code", args.class_code]
    cmd += ["--from", args.start]
    cmd += ["--to", args.end]
    cmd += ["--timeframe", args.timeframe]
    cmd += ["--profile", args.profile]
    cmd += ["--env", args.env]
    cmd += ["--direction-filter", args.direction_filter]
    cmd += ["--slippage-points", args.slippage_points]
    cmd += ["--grid-slippage-ticks-values", args.grid_slippage_ticks_values]
    cmd += ["--take-r", args.take_r]
    cmd += ["--max-hold-bars", args.max_hold_bars]

    if point_value_rub is not None and not pd.isna(point_value_rub):
        cmd += ["--point-value-rub", str(point_value_rub)]

    if tick_size is not None and not pd.isna(tick_size):
        cmd += ["--tick-size", str(tick_size)]

    if args.skip_load:
        cmd.append("--skip-load")
    if args.skip_grid:
        cmd.append("--skip-grid")
    if args.skip_walkforward_grid:
        cmd.append("--skip-walkforward-grid")
    if args.no_archive:
        cmd.append("--no-archive")

    return cmd


def main():
    args = parse_args()

    universe_df = pd.read_csv(args.universe)

    if "activity_score" in universe_df.columns:
        universe_df = universe_df.sort_values("activity_score", ascending=False)

    top_df = universe_df.head(args.top).reset_index(drop=True)

    print()
    print("Universe Research Batch Runner")
    print("==============================")
    print()
    print(f"Universe file: {args.universe}")
    print(f"Top N:         {args.top}")
    print(f"Period:        {args.start} -> {args.end}")
    print(f"Timeframe:     {args.timeframe}")
    print(f"Profile:       {args.profile}")
    print(f"Skip load:     {'yes' if args.skip_load else 'no'}")
    print()
    print("Tickers to process:")
    print()

    commands = []
    for i, row in top_df.iterrows():
        ticker = row.get("ticker", "")
        pv = row.get("point_value_rub", None)
        ts = row.get("min_price_increment", None)
        score = row.get("activity_score", "?")
        if ts is None or (isinstance(ts, float) and pd.isna(ts)):
            print(f"  WARNING: min_price_increment not found for {ticker}, --tick-size will not be passed")
            ts = None
        cmd = build_command(ticker, pv, ts, args)
        commands.append((ticker, cmd))
        print(f"  {i+1:>2}. {ticker:<10}  activity_score={score}  point_value_rub={pv}  tick_size={ts}")
        print(f"      Command: {' '.join(cmd[:8])} ...")

    print()
    print("Commands to run:")
    for ticker, cmd in commands:
        print()
        print(f"  # {ticker}")
        print(f"  {' '.join(cmd)}")

    print()
    if not args.yes:
        confirm = input("Run these pipelines? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Aborted.")
            return

    for ticker, cmd in commands:
        print()
        print(f"{'='*60}")
        print(f"Running pipeline for {ticker}...")
        print(f"{'='*60}")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"ERROR: Pipeline for {ticker} failed with exit code {result.returncode}", file=sys.stderr)


if __name__ == "__main__":
    main()
