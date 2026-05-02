#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

import pandas as pd

from src.backtest.walkforward import run_period_backtests
from src.backtest.stability import calculate_period_stability
from src.backtest.walkforward_report import generate_walkforward_report


def parse_args():
    p = argparse.ArgumentParser(description="Walk-forward backtest — offline, no real orders")
    p.add_argument("--input", required=True)
    p.add_argument("--period", choices=["day", "week", "month"], default="week")
    p.add_argument("--period-results-output", default="out/walkforward_period_results.csv")
    p.add_argument("--trades-output", default="out/walkforward_trades.csv")
    p.add_argument("--report-output", default="reports/walkforward_report.md")
    p.add_argument("--entry-mode", choices=["close", "breakout"], default="breakout")
    p.add_argument("--entry-horizon-bars", type=int, default=3)
    p.add_argument("--max-hold-bars", type=int, default=30)
    p.add_argument("--take-r", type=float, default=1.0)
    p.add_argument("--stop-buffer-points", type=float, default=0.0)
    p.add_argument("--slippage-points", type=float, default=0.0)
    p.add_argument("--slippage-ticks", type=float, default=None,
                   help="Slippage in ticks (overrides --slippage-points when set)")
    p.add_argument("--tick-size", type=float, default=None,
                   help="Instrument tick size; required when --slippage-ticks is used")
    p.add_argument("--point-value-rub", type=float, default=10.0)
    p.add_argument("--commission-per-trade", type=float, default=0.025)
    p.add_argument("--contracts", type=int, default=1)
    p.add_argument("--allow-overlap", action="store_true", default=False)
    p.add_argument("--direction-filter", choices=["all", "BUY", "SELL"], default="all")
    return p.parse_args()


def main():
    args = parse_args()
    debug_df = pd.read_csv(args.input)

    tick_size = args.tick_size
    if tick_size is None and "tick_size" in debug_df.columns:
        vals = debug_df["tick_size"].dropna().unique()
        if len(vals) == 1:
            tick_size = float(vals[0])

    period_results_df, all_trades_df = run_period_backtests(
        debug_df=debug_df,
        period=args.period,
        entry_mode=args.entry_mode,
        entry_horizon_bars=args.entry_horizon_bars,
        max_hold_bars=args.max_hold_bars,
        take_r=args.take_r,
        stop_buffer_points=args.stop_buffer_points,
        slippage_points=args.slippage_points,
        slippage_ticks=args.slippage_ticks,
        tick_size=tick_size,
        point_value_rub=args.point_value_rub,
        commission_per_trade=args.commission_per_trade,
        contracts=args.contracts,
        allow_overlap=args.allow_overlap,
        direction_filter=args.direction_filter,
    )

    Path(args.period_results_output).parent.mkdir(parents=True, exist_ok=True)
    period_results_df.to_csv(args.period_results_output, index=False)

    Path(args.trades_output).parent.mkdir(parents=True, exist_ok=True)
    if len(all_trades_df) > 0:
        all_trades_df.to_csv(args.trades_output, index=False)
    else:
        all_trades_df.to_csv(args.trades_output, index=False)

    params = {
        "period": args.period,
        "entry_mode": args.entry_mode,
        "entry_horizon_bars": args.entry_horizon_bars,
        "max_hold_bars": args.max_hold_bars,
        "take_r": args.take_r,
        "stop_buffer_points": args.stop_buffer_points,
        "slippage_points": args.slippage_points,
        "slippage_ticks": args.slippage_ticks,
        "tick_size": tick_size,
        "point_value_rub": args.point_value_rub,
        "commission_per_trade": args.commission_per_trade,
        "contracts": args.contracts,
        "allow_overlap": args.allow_overlap,
        "direction_filter": args.direction_filter,
    }
    generate_walkforward_report(period_results_df, all_trades_df, args.report_output, params)

    stab = calculate_period_stability(period_results_df)
    total_signals = int(period_results_df["signals"].sum()) if "signals" in period_results_df.columns else 0

    print("Walk-forward Backtest")
    print("=====================")
    print()
    print(f"Input: {args.input}")
    print(f"Period: {args.period}")
    print(f"Periods: {stab['periods_total']}")
    print(f"Total signals: {total_signals}")
    print(f"Total net PnL RUB: {stab['total_net_pnl_rub']:.2f}")
    print(f"Profitable periods: {stab['profitable_periods']}")
    print(f"Losing periods: {stab['losing_periods']}")
    print(f"Profitable periods %: {stab['profitable_periods_pct']:.1%}")
    if stab["periods_total"] > 0:
        best_row = period_results_df.loc[period_results_df["net_pnl_rub"].idxmax()]
        worst_row = period_results_df.loc[period_results_df["net_pnl_rub"].idxmin()]
        print(f"Best period: {best_row['period_key']} ({best_row['net_pnl_rub']:.2f} RUB)")
        print(f"Worst period: {worst_row['period_key']} ({worst_row['net_pnl_rub']:.2f} RUB)")
    print()
    print(f"Period results output: {args.period_results_output}")
    print(f"Trades output: {args.trades_output}")
    print(f"Report output: {args.report_output}")


if __name__ == "__main__":
    main()
