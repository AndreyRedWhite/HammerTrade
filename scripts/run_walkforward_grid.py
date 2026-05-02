#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

import pandas as pd

from src.backtest.walkforward import run_period_grid_backtests
from src.backtest.walkforward_report import generate_walkforward_grid_report


def _floats(s):
    return [float(x.strip()) for x in s.split(",")]


def _ints(s):
    return [int(x.strip()) for x in s.split(",")]


def _strs(s):
    return [x.strip() for x in s.split(",")]


def parse_args():
    p = argparse.ArgumentParser(description="Walk-forward grid — offline robustness analysis")
    p.add_argument("--input", required=True)
    p.add_argument("--period", choices=["day", "week", "month"], default="week")
    p.add_argument("--output", default="out/walkforward_grid_results.csv")
    p.add_argument("--report-output", default="reports/walkforward_grid_report.md")
    p.add_argument("--entry-modes", default="breakout,close", type=_strs)
    p.add_argument("--take-r-values", default="0.5,1.0,1.5,2.0", type=_floats)
    p.add_argument("--max-hold-bars-values", default="5,10,30,60", type=_ints)
    p.add_argument("--stop-buffer-points-values", default="0,1,2,5", type=_floats)
    p.add_argument("--slippage-points-values", default="0,1,2,5", type=_floats)
    p.add_argument("--slippage-ticks-values", default=None, type=_floats,
                   help="Slippage grid in ticks (overrides --slippage-points-values when set)")
    p.add_argument("--tick-size", type=float, default=None,
                   help="Instrument tick size; required when --slippage-ticks-values is used")
    p.add_argument("--entry-horizon-bars", type=int, default=3)
    p.add_argument("--point-value-rub", type=float, default=10.0)
    p.add_argument("--commission-per-trade", type=float, default=0.025)
    p.add_argument("--contracts", type=int, default=1)
    p.add_argument("--direction-filter", choices=["all", "BUY", "SELL"], default="all")
    return p.parse_args()


def main():
    args = parse_args()
    debug_df = pd.read_csv(args.input)

    slip_dim = args.slippage_ticks_values if args.slippage_ticks_values else args.slippage_points_values
    total_scenarios = (
        len(args.entry_modes) * len(args.take_r_values) *
        len(args.max_hold_bars_values) * len(args.stop_buffer_points_values) *
        len(slip_dim)
    )
    print(f"Running {total_scenarios} scenarios across periods...")

    tick_size = args.tick_size
    if tick_size is None and "tick_size" in debug_df.columns:
        vals = debug_df["tick_size"].dropna().unique()
        if len(vals) == 1:
            tick_size = float(vals[0])

    grid_df = run_period_grid_backtests(
        debug_df=debug_df,
        period=args.period,
        entry_modes=args.entry_modes,
        take_r_values=args.take_r_values,
        max_hold_bars_values=args.max_hold_bars_values,
        stop_buffer_points_values=args.stop_buffer_points_values,
        slippage_points_values=args.slippage_points_values,
        slippage_ticks_values=args.slippage_ticks_values,
        tick_size=tick_size,
        entry_horizon_bars=args.entry_horizon_bars,
        point_value_rub=args.point_value_rub,
        commission_per_trade=args.commission_per_trade,
        contracts=args.contracts,
        direction_filter=args.direction_filter,
    )

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    grid_df.to_csv(args.output, index=False)

    generate_walkforward_grid_report(
        walkforward_grid_df=grid_df,
        output_path=args.report_output,
        source_path=args.input,
        period=args.period,
    )

    n_periods = grid_df["period_key"].nunique()
    n_rows = len(grid_df)
    profitable_rows = int((grid_df["net_pnl_rub"] > 0).sum())

    print()
    print("Walk-forward Grid Backtest")
    print("==========================")
    print()
    print(f"Input: {args.input}")
    print(f"Period: {args.period}")
    print(f"Scenarios: {total_scenarios}")
    print(f"Periods: {n_periods}")
    print(f"Rows: {n_rows}")
    print(f"Profitable scenario-period rows: {profitable_rows} / {n_rows}")
    print()
    print(f"Output: {args.output}")
    print(f"Report: {args.report_output}")


if __name__ == "__main__":
    main()
