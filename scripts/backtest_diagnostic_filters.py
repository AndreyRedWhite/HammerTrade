"""CLI for MVP-2.0 Backtest Diagnostic Filters.

Loads a YAML config, filters historical signals, runs Phase A + B scenarios,
and saves CSV + Markdown report artifacts.

Usage:
    python scripts/backtest_diagnostic_filters.py
    python scripts/backtest_diagnostic_filters.py --config configs/backtest_diagnostic_filters_sim6_sell.yaml
    python scripts/backtest_diagnostic_filters.py --from 2026-03-01 --to 2026-04-09 --ticker SiM6 --direction SELL
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.diagnostic_filters import FilterConfig
from src.backtest.diagnostic_grid import (
    BacktestParams,
    build_markdown_report,
    make_phase_a_configs,
    make_phase_b_configs,
    rank_scenarios,
    run_all_scenarios,
    save_results,
)

_DEFAULT_CONFIG = "configs/backtest_diagnostic_filters_sim6_sell.yaml"
_DEFAULT_SIGNALS_CSV = "out/debug_simple_all.csv"
_DEFAULT_OUT_DIR = "out"
_DEFAULT_REPORTS_DIR = "reports"


def _load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_signals(csv_path: str, direction: str, from_date: str | None, to_date: str | None) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

    if from_date:
        from_ts = pd.Timestamp(from_date, tz="UTC")
        df = df[df["timestamp"] >= from_ts]
    if to_date:
        to_ts = pd.Timestamp(to_date, tz="UTC") + pd.Timedelta(days=1)
        df = df[df["timestamp"] < to_ts]

    return df.reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="HammerTrade Backtest Diagnostic Filters (MVP-2.0)")
    parser.add_argument("--config", default=_DEFAULT_CONFIG)
    parser.add_argument("--from", dest="from_date", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--direction", default=None, choices=["SELL", "BUY", "all"])
    parser.add_argument("--out-dir", default=_DEFAULT_OUT_DIR)
    parser.add_argument("--reports-dir", default=_DEFAULT_REPORTS_DIR)
    args = parser.parse_args()

    # Load config
    cfg_path = args.config
    if not Path(cfg_path).exists():
        print(f"Config not found: {cfg_path}", file=sys.stderr)
        sys.exit(1)
    cfg = _load_config(cfg_path)

    # Resolve parameters (CLI overrides config)
    exp = cfg.get("experiment", {})
    ticker = args.ticker or exp.get("ticker", "SiM6")
    direction = (args.direction or exp.get("direction", "SELL")).upper()

    dr = cfg.get("date_range", {})
    from_date = args.from_date or dr.get("from")
    to_date = args.to_date or dr.get("to")

    exec_cfg = cfg.get("execution", {})
    rep_cfg = cfg.get("reporting", {})
    min_trades_required = int(rep_cfg.get("min_trades_required", 30))

    params = BacktestParams(
        stop_buffer_points=float(exec_cfg.get("stop_buffer_points", 0.0)),
        take_r=float(exec_cfg.get("take_r", 1.0)),
        slippage_points=float(exec_cfg.get("slippage_points", 0.0)),
        slippage_ticks=exec_cfg.get("slippage_ticks") or None,
        tick_size=exec_cfg.get("tick_size") or None,
        point_value_rub=float(exec_cfg.get("point_value_rub", 10.0)),
        commission_per_trade=float(exec_cfg.get("commission_per_trade", 0.025)),
        contracts=int(exec_cfg.get("contracts", 1)),
        entry_horizon_bars=int(exec_cfg.get("entry_horizon_bars", 3)),
        default_max_hold_bars=int(exec_cfg.get("default_max_hold_bars", 30)),
        allow_overlap=bool(exec_cfg.get("allow_overlap", False)),
        min_trades_required=min_trades_required,
        direction=direction,
    )

    # Load signals CSV
    data_cfg = cfg.get("data", {})
    signals_csv = data_cfg.get("signals_csv", _DEFAULT_SIGNALS_CSV)
    if not Path(signals_csv).exists():
        print(f"Signals CSV not found: {signals_csv}", file=sys.stderr)
        sys.exit(1)

    print("HammerTrade Backtest Diagnostic Filters")
    print(f"Ticker      : {ticker}")
    print(f"Direction   : {direction}")
    print(f"Period      : {from_date or 'all'} — {to_date or 'all'}")
    print(f"Config      : {cfg_path}")
    print(f"Signals CSV : {signals_csv}")

    debug_df = _load_signals(signals_csv, direction, str(from_date) if from_date else None, str(to_date) if to_date else None)

    # Count signals
    sig_count_mask = (
        debug_df["is_signal"].astype(bool)
        & (debug_df["fail_reason"].astype(str) == "pass")
        & (debug_df["direction_candidate"].str.upper() == direction)
    )
    n_signals = sig_count_mask.sum()
    print(f"Signals ({direction}) : {n_signals}")

    if n_signals == 0:
        print("No signals found in the specified date range. Exiting.", file=sys.stderr)
        sys.exit(1)

    # Run all scenarios
    n_phase_a = len(make_phase_a_configs(cfg, params))
    n_phase_b = len(make_phase_b_configs(cfg, params))
    print(f"Scenarios   : 1 baseline + {n_phase_a} Phase A + {n_phase_b} Phase B = {1 + n_phase_a + n_phase_b} total")

    baseline, phase_a, phase_b, trades_map = run_all_scenarios(debug_df, params, cfg)

    # Actual date range from data
    if len(debug_df) > 0:
        actual_from = debug_df["timestamp"].min().strftime("%Y-%m-%d")
        actual_to = debug_df["timestamp"].max().strftime("%Y-%m-%d")
    else:
        actual_from = str(from_date)
        actual_to = str(to_date)

    print(f"Actual data : {actual_from} — {actual_to}")
    print(f"Baseline    : trades={baseline.trades}, "
          f"net={baseline.net_pnl_rub:+.0f} руб, "
          f"PF={baseline.profit_factor:.3f}, "
          f"maxDD={baseline.max_drawdown_rub:.0f} руб")

    # Rankings
    all_non_baseline = phase_a + phase_b
    top_n = int(rep_cfg.get("top_n", 10))
    rankings = rank_scenarios(baseline, all_non_baseline, top_n=top_n)

    # Build report
    report_md = build_markdown_report(
        baseline=baseline,
        phase_a=phase_a,
        phase_b=phase_b,
        rankings=rankings,
        ticker=ticker,
        direction=direction,
        period_from=actual_from,
        period_to=actual_to,
        params=params,
        cfg=cfg,
    )

    # Save artifacts
    paths = save_results(
        baseline=baseline,
        phase_a=phase_a,
        phase_b=phase_b,
        trades_map=trades_map,
        out_dir=args.out_dir,
        reports_dir=args.reports_dir,
        ticker=ticker,
        direction=direction,
        report_md=report_md,
    )

    print(f"Results CSV : {paths['summary_csv']}")
    print(f"Trades CSV  : {paths['trades_csv']}")
    print(f"Report      : {paths['report_md']}")

    # Count warnings
    all_results = [baseline] + phase_a + phase_b
    total_warnings = sum(len(r.warnings) for r in all_results)
    print(f"Warnings    : {total_warnings}")

    # Print top 3 by PF
    top_pf = rankings.get("by_profit_factor", [])[:3]
    if top_pf:
        print("\nTop 3 by Profit Factor:")
        for r in top_pf:
            flag = " [LOW_SAMPLE]" if r.is_low_sample else ""
            print(f"  {r.scenario_name}: PF={r.profit_factor:.3f}, trades={r.trades}, "
                  f"net={r.net_pnl_rub:+.0f} руб{flag}")

    print("\nDone.")


if __name__ == "__main__":
    main()
