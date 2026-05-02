#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

import pandas as pd

from src.backtest.engine import run_backtest
from src.backtest.metrics import calculate_backtest_metrics
from src.backtest.report import generate_report


def parse_args():
    p = argparse.ArgumentParser(description="Backtest v1 — offline, no real orders")
    p.add_argument("--input", required=True, help="Path to debug_simple_all.csv")
    p.add_argument("--trades-output", default="out/backtest_trades.csv")
    p.add_argument("--report-output", default="reports/backtest_report.md")
    p.add_argument("--entry-mode", choices=["close", "breakout"], default="breakout")
    p.add_argument("--entry-horizon-bars", type=int, default=3)
    p.add_argument("--max-hold-bars", type=int, default=30)
    p.add_argument("--take-r", type=float, default=1.0)
    p.add_argument("--stop-buffer-points", type=float, default=0.0)
    p.add_argument("--slippage-points", type=float, default=0.0)
    p.add_argument("--slippage-ticks", type=float, default=None,
                   help="Slippage in ticks (overrides --slippage-points when set)")
    p.add_argument("--tick-size", type=float, default=None,
                   help="Instrument tick size (min_price_increment); required when --slippage-ticks is used")
    p.add_argument("--point-value-rub", type=float, default=10.0)
    p.add_argument("--commission-per-trade", type=float, default=0.025)
    p.add_argument("--contracts", type=int, default=1)
    p.add_argument("--allow-overlap", action="store_true", default=False)
    p.add_argument("--direction-filter", choices=["all", "BUY", "SELL"], default="all")
    return p.parse_args()


def main():
    args = parse_args()

    debug_df = pd.read_csv(args.input)

    # Resolve tick_size: CLI > debug CSV column
    tick_size = args.tick_size
    if tick_size is None and "tick_size" in debug_df.columns:
        vals = debug_df["tick_size"].dropna().unique()
        if len(vals) == 1:
            tick_size = float(vals[0])

    trades_df = run_backtest(
        debug_df=debug_df,
        entry_mode=args.entry_mode,
        entry_horizon_bars=args.entry_horizon_bars,
        max_hold_bars=args.max_hold_bars,
        take_r=args.take_r,
        stop_buffer_points=args.stop_buffer_points,
        point_value_rub=args.point_value_rub,
        commission_per_trade=args.commission_per_trade,
        contracts=args.contracts,
        allow_overlap=args.allow_overlap,
        slippage_points=args.slippage_points,
        slippage_ticks=args.slippage_ticks,
        tick_size=tick_size,
        direction_filter=args.direction_filter,
    )

    Path(args.trades_output).parent.mkdir(parents=True, exist_ok=True)
    trades_df.to_csv(args.trades_output, index=False)

    params = {
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
    generate_report(trades_df, args.report_output, params)

    m = calculate_backtest_metrics(trades_df)
    pf = m["profit_factor"]
    pf_str = "inf" if pf == float("inf") else f"{pf:.2f}"

    signals_count = len(debug_df[
        (debug_df["is_signal"].astype(bool)) &
        (debug_df["fail_reason"].astype(str) == "pass")
    ])

    print("Backtest v1")
    print("===========")
    print()
    print(f"Input: {args.input}")
    print(f"Signals: {signals_count}")
    print(f"Closed trades: {m['closed_trades']}")
    print(f"Skipped trades: {m['skipped_trades']}")
    print(f"Entry mode: {args.entry_mode}")
    print(f"Take R: {args.take_r}")
    print(f"Net PnL RUB: {m['net_pnl_rub']:.2f}")
    print(f"Winrate: {m['winrate']:.1%}")
    print(f"Profit factor: {pf_str}")
    print()
    print(f"Trades output: {args.trades_output}")
    print(f"Report output: {args.report_output}")


if __name__ == "__main__":
    main()
