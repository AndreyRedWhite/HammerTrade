"""CLI for MVP-2.2 Backtest Exit/Time Filters v2.

Validates live/paper hypotheses on historical data:
  - exclude_hour_12
  - softer max_hold_bars (10, 15)
  - conditional max_hold (progress-to-take, PnL threshold)
  - entry confirmation proxies
  - combined Phase B scenarios

Usage:
    python scripts/backtest_exit_time_filters_v2.py
    python scripts/backtest_exit_time_filters_v2.py --config configs/backtest_exit_time_filters_v2_sim6_sell.yaml
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.exit_time_grid_v2 import (
    BacktestParamsV2,
    build_markdown_report_v2,
    make_phase_a_conditional_configs,
    make_phase_a_confirmation_configs,
    make_phase_a_maxhold_configs,
    make_phase_a_time_configs,
    make_phase_b_configs_v2,
    rank_scenarios_v2,
    run_all_scenarios_v2,
    save_results_v2,
)

_DEFAULT_CONFIG = "configs/backtest_exit_time_filters_v2_sim6_sell.yaml"
_DEFAULT_SIGNALS_CSV = "out/debug_simple_all.csv"
_DEFAULT_OUT_DIR = "out"
_DEFAULT_REPORTS_DIR = "reports"


def _load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_signals(csv_path: str, from_date: str | None, to_date: str | None) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

    if from_date:
        df = df[df["timestamp"] >= pd.Timestamp(from_date, tz="UTC")]
    if to_date:
        df = df[df["timestamp"] < pd.Timestamp(to_date, tz="UTC") + pd.Timedelta(days=1)]

    return df.reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="HammerTrade Backtest Exit/Time Filters v2 (MVP-2.2)")
    parser.add_argument("--config", default=_DEFAULT_CONFIG)
    parser.add_argument("--from", dest="from_date", default=None)
    parser.add_argument("--to", dest="to_date", default=None)
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--direction", default=None, choices=["SELL", "BUY", "all"])
    parser.add_argument("--out-dir", default=_DEFAULT_OUT_DIR)
    parser.add_argument("--reports-dir", default=_DEFAULT_REPORTS_DIR)
    args = parser.parse_args()

    cfg_path = args.config
    if not Path(cfg_path).exists():
        print(f"Config not found: {cfg_path}", file=sys.stderr)
        sys.exit(1)
    cfg = _load_config(cfg_path)

    exp = cfg.get("experiment", {})
    ticker = args.ticker or exp.get("ticker", "SiM6")
    direction = (args.direction or exp.get("direction", "SELL")).upper()

    dr = cfg.get("date_range", {})
    from_date = args.from_date or dr.get("from")
    to_date = args.to_date or dr.get("to")

    exec_cfg = cfg.get("execution", {})
    rep_cfg = cfg.get("reporting", {})
    min_trades_required = int(rep_cfg.get("min_trades_required", 30))

    params = BacktestParamsV2(
        stop_buffer_points=float(exec_cfg.get("stop_buffer_points", 0.0)),
        take_r=float(exec_cfg.get("take_r", 1.0)),
        slippage_points=float(exec_cfg.get("slippage_points", 0.0)),
        point_value_rub=float(exec_cfg.get("point_value_rub", 10.0)),
        commission_per_trade=float(exec_cfg.get("commission_per_trade", 0.025)),
        contracts=int(exec_cfg.get("contracts", 1)),
        entry_horizon_bars=int(exec_cfg.get("entry_horizon_bars", 3)),
        allow_overlap=bool(exec_cfg.get("allow_overlap", False)),
        min_trades_required=min_trades_required,
        direction=direction,
    )

    data_cfg = cfg.get("data", {})
    signals_csv = data_cfg.get("signals_csv", _DEFAULT_SIGNALS_CSV)
    if not Path(signals_csv).exists():
        print(f"Signals CSV not found: {signals_csv}", file=sys.stderr)
        sys.exit(1)

    print("HammerTrade Backtest Exit/Time Filters v2")
    print(f"Ticker      : {ticker}")
    print(f"Direction   : {direction}")
    print(f"Period      : {from_date or 'all'} — {to_date or 'all'}")
    print(f"Config      : {cfg_path}")

    debug_df = _load_signals(signals_csv, str(from_date) if from_date else None, str(to_date) if to_date else None)

    sig_mask = (
        debug_df["is_signal"].astype(bool)
        & (debug_df["fail_reason"].astype(str) == "pass")
        & (debug_df["direction_candidate"].str.upper() == direction)
    )
    n_signals = sig_mask.sum()
    print(f"Signals     : {n_signals} ({direction})")

    if n_signals == 0:
        print("No signals found. Exiting.", file=sys.stderr)
        sys.exit(1)

    n_a1 = len(make_phase_a_time_configs(cfg, params))
    n_a2 = len(make_phase_a_maxhold_configs(cfg, params))
    n_a3 = len(make_phase_a_conditional_configs(cfg, params))
    n_a4 = len(make_phase_a_confirmation_configs(cfg, params))
    n_b = len(make_phase_b_configs_v2(cfg, params))
    n_total = 1 + n_a1 + n_a2 + n_a3 + n_a4 + n_b
    print(f"Scenarios   : 1 baseline + {n_a1} A1(time) + {n_a2} A2(maxhold) + "
          f"{n_a3} A3(cond) + {n_a4} A4(confirm) + {n_b} B = {n_total} total")

    baseline, a1, a2, a3, a4, phase_b, trades_map = run_all_scenarios_v2(debug_df, params, cfg)

    if len(debug_df) > 0:
        actual_from = debug_df["timestamp"].min().strftime("%Y-%m-%d")
        actual_to = debug_df["timestamp"].max().strftime("%Y-%m-%d")
    else:
        actual_from = str(from_date)
        actual_to = str(to_date)

    print(f"Data period : {actual_from} — {actual_to}")
    print(f"Baseline    : trades={baseline.trades}, "
          f"net={baseline.net_pnl_rub:+.0f} руб, "
          f"PF={baseline.profit_factor:.3f}, "
          f"maxDD={baseline.max_drawdown_rub:.0f} руб")

    all_non_baseline = a1 + a2 + a3 + a4 + phase_b
    top_n = int(rep_cfg.get("top_n", 20))
    rankings = rank_scenarios_v2(baseline, all_non_baseline, top_n=top_n)

    report_md = build_markdown_report_v2(
        baseline=baseline,
        phase_a1=a1,
        phase_a2=a2,
        phase_a3=a3,
        phase_a4=a4,
        phase_b=phase_b,
        rankings=rankings,
        ticker=ticker,
        direction=direction,
        period_from=actual_from,
        period_to=actual_to,
        params=params,
        cfg=cfg,
    )

    paths = save_results_v2(
        baseline=baseline,
        phase_a1=a1,
        phase_a2=a2,
        phase_a3=a3,
        phase_a4=a4,
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

    total_warnings = sum(len(r.warnings) for r in [baseline] + all_non_baseline)
    print(f"Warnings    : {total_warnings}")

    print("\nTop 3 by Profit Factor:")
    for r in rankings.get("by_profit_factor", [])[:3]:
        flag = " [LOW_SAMPLE]" if r.is_low_sample else ""
        print(f"  {r.scenario_name}: PF={r.profit_factor:.3f}, "
              f"trades={r.trades}, net={r.net_pnl_rub:+.0f} руб{flag}")

    print("\nTop 3 by Net PnL:")
    for r in rankings.get("by_net_pnl", [])[:3]:
        flag = " [LOW_SAMPLE]" if r.is_low_sample else ""
        print(f"  {r.scenario_name}: net={r.net_pnl_rub:+.0f} руб, "
              f"PF={r.profit_factor:.3f}, trades={r.trades}{flag}")

    print(f"\nBest net    : {rankings['by_net_pnl'][0].scenario_name if rankings['by_net_pnl'] else '—'}")
    print(f"Best PF     : {rankings['by_profit_factor'][0].scenario_name if rankings['by_profit_factor'] else '—'}")
    print(f"Report      : {paths['report_latest']}")
    print("\nDone.")


if __name__ == "__main__":
    main()
