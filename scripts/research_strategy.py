#!/usr/bin/env python3
"""Research runner CLI: runs strategy backtest and produces reports.

Usage:
    python scripts/research_strategy.py \
        --strategy opening_range_breakout \
        --config configs/research/opening_range_breakout_sim6.yaml \
        --output-dir reports \
        --out-dir out
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime

import yaml

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Run strategy research backtest")
    parser.add_argument("--strategy", required=True, help="Strategy name (e.g. opening_range_breakout)")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument("--output-dir", default="reports", help="Directory for Markdown reports")
    parser.add_argument("--out-dir", default="out", help="Directory for CSV outputs")
    args = parser.parse_args()

    # Load config
    with open(args.config) as f:
        config_dict = yaml.safe_load(f)

    ticker = config_dict.get("experiment", {}).get("ticker", "SiM6")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"[research_strategy] Running '{args.strategy}' for {ticker}...")
    print(f"[research_strategy] Config: {args.config}")

    from src.research.runner import run_research
    scenario_results, all_trades = run_research(args.strategy, config_dict)

    print(f"[research_strategy] Scenarios: {len(scenario_results)}, Trades: {len(all_trades)}")

    # Build reports
    from src.research.reports import build_orb_markdown_report, build_orb_csv, build_trades_csv
    md_report = build_orb_markdown_report(scenario_results, all_trades, config_dict)
    scenario_csv_rows = build_orb_csv(scenario_results)
    trades_csv_rows = build_trades_csv(all_trades)

    # Ensure output directories exist
    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)

    # Write Markdown reports
    strategy_label = f"research_{args.strategy}_{ticker}"
    md_ts_path = os.path.join(args.output_dir, f"{strategy_label}_{ts}.md")
    md_latest_path = os.path.join(args.output_dir, f"{strategy_label}_latest.md")

    with open(md_ts_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    with open(md_latest_path, "w", encoding="utf-8") as f:
        f.write(md_report)

    print(f"[research_strategy] Report written: {md_ts_path}")
    print(f"[research_strategy] Report written: {md_latest_path}")

    # Write scenario CSV
    if scenario_csv_rows:
        csv_ts_path = os.path.join(args.out_dir, f"{strategy_label}_{ts}.csv")
        fieldnames = list(scenario_csv_rows[0].keys())
        with open(csv_ts_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(scenario_csv_rows)
        print(f"[research_strategy] Scenarios CSV: {csv_ts_path}")

    # Write trades CSV
    if trades_csv_rows:
        trades_ts_path = os.path.join(
            args.out_dir, f"research_{args.strategy}_trades_{ticker}_{ts}.csv"
        )
        fieldnames = list(trades_csv_rows[0].keys())
        with open(trades_ts_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(trades_csv_rows)
        print(f"[research_strategy] Trades CSV: {trades_ts_path}")

    # Print summary to stdout
    print("\n" + "=" * 60)
    print(f"ORB RESEARCH SUMMARY — {ticker}")
    print("=" * 60)
    if scenario_results:
        sorted_results = sorted(scenario_results, key=lambda x: x.get("profit_factor", 0), reverse=True)
        print(f"\nTop 5 scenarios by Profit Factor:")
        print(f"{'OR Window':<20} {'Dir':<7} {'R':<5} {'Trades':<8} {'PF':<8} {'NetPnL':>10} {'WR':>7}")
        print("-" * 70)
        for r in sorted_results[:5]:
            print(
                f"{r.get('or_window', ''):<20} {r.get('direction', ''):<7} "
                f"{r.get('take_r', ''):<5} {r.get('trades', 0):<8} "
                f"{r.get('profit_factor', 0):<8.3f} {r.get('net_pnl', 0):>10.2f} "
                f"{r.get('winrate', 0):>7.1%}"
            )

        best = sorted_results[0]
        print(f"\nBest scenario: OR={best['or_window']}, {best['direction']}, R={best['take_r']}")
        print(f"  PF={best['profit_factor']:.3f}, Net PnL={best['net_pnl']:.2f} RUB, "
              f"Trades={best['trades']}, Winrate={best['winrate']:.1%}")
        print(f"  Max Drawdown={best.get('max_drawdown', 0):.2f} RUB, "
              f"Expectancy={best.get('expectancy', 0):.2f} RUB/trade")
    else:
        print("No scenario results generated.")

    print("=" * 60)
    print(f"\nDone. Reports in {args.output_dir}/, CSVs in {args.out_dir}/")


if __name__ == "__main__":
    main()
