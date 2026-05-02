#!/usr/bin/env python3
"""Cross-run comparison: reads archives and builds a comparison report."""
import sys
import glob
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from src.analytics.cross_run_comparison import build_comparison_df, generate_comparison_report

_LATEST_GLOB = "archives/latest/Actual_*.zip"


def parse_args():
    p = argparse.ArgumentParser(
        description="Cross-run research comparison — offline, reads local archives"
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--latest", action="store_true",
                       help=f"Compare all archives in {_LATEST_GLOB}")
    group.add_argument("--archives", nargs="+", metavar="ZIP",
                       help="Explicit list of archive zip files (supports glob patterns)")
    p.add_argument("--output", default="out/cross_run_comparison.csv")
    p.add_argument("--report-output", default="reports/cross_run_comparison.md")
    return p.parse_args()


def main():
    args = parse_args()

    if args.latest:
        zip_paths = sorted(glob.glob(_LATEST_GLOB))
        if not zip_paths:
            print(f"No archives found matching: {_LATEST_GLOB}", file=sys.stderr)
            sys.exit(1)
    else:
        zip_paths = []
        for pattern in args.archives:
            matched = sorted(glob.glob(pattern))
            if matched:
                zip_paths.extend(matched)
            elif Path(pattern).exists():
                zip_paths.append(pattern)
            else:
                print(f"Warning: no files matched: {pattern}", file=sys.stderr)

    if not zip_paths:
        print("No archive files found.", file=sys.stderr)
        sys.exit(1)

    print(f"Comparing {len(zip_paths)} archive(s):")
    for zp in zip_paths:
        print(f"  {zp}")
    print()

    df = build_comparison_df(zip_paths)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)

    created_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    generate_comparison_report(df, args.report_output, created_at=created_at)

    print(f"Comparison CSV:    {args.output}")
    print(f"Comparison report: {args.report_output}")
    print()

    if "ticker" in df.columns and "net_pnl_rub" in df.columns:
        sorted_df = df.sort_values("net_pnl_rub", ascending=False)
        print("Runs by Net PnL:")
        for _, row in sorted_df.iterrows():
            ticker = row.get("ticker", row.get("run_id", "?"))
            direction = row.get("direction_filter", "all")
            pnl = row.get("net_pnl_rub")
            pnl_str = f"{pnl:.2f}" if pnl is not None and pnl == pnl else "N/A"
            print(f"  {ticker:<12} direction={direction:<6} net_pnl={pnl_str} RUB")


if __name__ == "__main__":
    main()
