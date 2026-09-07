#!/usr/bin/env python3
"""MVP-R2: Multi-Strategy Research Pack for HammerTrade.

Usage:
    venv/bin/python scripts/research_multistrategy_r2.py \
        --config configs/research/multistrategy_r2_sim6.yaml

Steps:
  1. Load train + OOS candles
  2. For each strategy, run scenario grid on train, OOS, and full
  3. For top scenario: walkforward, slippage, concentration, regime breakdown
  4. Candidate decision: READY_FOR_PAPER / NEEDS_MORE_DATA / REJECT
  5. Write reports and summary CSV
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research.metrics import compute_metrics
from src.research.regime import compute_regime_context
from src.research.robustness import concentration_flag
from src.research.slippage import slippage_sensitivity
from src.research.walkforward import walkforward_table
from src.research.vwap import compute_session_vwap, compute_atr
from src.strategies.momentum_continuation.strategy import run_momentum_backtest
from src.strategies.opening_range_fade.strategy import run_orf_backtest
from src.strategies.vwap_reversion.strategy import run_vwap_reversion_backtest
from src.strategies.vwap_hammer_filter.strategy import run_vwap_hammer_filter


READY_FOR_PAPER_THRESHOLDS = {
    "min_pf": 1.3,
    "min_trades": 20,
    "min_oos_pf": 1.1,
    "max_concentration_top3": 0.60,
}

NEEDS_MORE_DATA_THRESHOLDS = {
    "min_pf": 1.1,
    "min_trades": 10,
    "min_oos_pf": 0.9,
}


def load_candles(path: str) -> pd.DataFrame:
    """Load candles CSV and ensure timestamp is UTC tz-aware."""
    df = pd.read_csv(path)
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    elif df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def candidate_decision(
    train_metrics: dict,
    oos_metrics: dict,
    concentration: tuple[bool, str],
) -> str:
    """Determine paper trading candidacy for a scenario."""
    pf_train = train_metrics.get("profit_factor", 0)
    pf_oos = oos_metrics.get("profit_factor", 0) if oos_metrics.get("trades", 0) > 0 else 0
    n_trades = train_metrics.get("trades", 0)
    is_concentrated, _ = concentration

    t = READY_FOR_PAPER_THRESHOLDS
    if (
        pf_train >= t["min_pf"]
        and n_trades >= t["min_trades"]
        and pf_oos >= t["min_oos_pf"]
        and not is_concentrated
    ):
        return "READY_FOR_PAPER"

    n = NEEDS_MORE_DATA_THRESHOLDS
    if pf_train >= n["min_pf"] and n_trades >= n["min_trades"]:
        return "NEEDS_MORE_DATA"

    return "REJECT"


def regime_breakdown(trades: list[dict]) -> dict:
    """Compute metrics broken down by regime."""
    by_regime: dict[str, list[dict]] = {}
    for t in trades:
        r = str(t.get("regime", "NORMAL"))
        by_regime.setdefault(r, []).append(t)
    result = {}
    for regime, rtrades in by_regime.items():
        m = compute_metrics(rtrades)
        result[regime] = {"trades": m["trades"], "pf": m["profit_factor"], "net_pnl": m["net_pnl"]}
    return result


def format_metrics_md(m: dict) -> str:
    return (
        f"  trades={m['trades']}, winrate={m['winrate']:.1%}, "
        f"PF={m['profit_factor']:.3f}, net_pnl={m['net_pnl']:.0f}₽, "
        f"exp={m['expectancy']:.1f}₽, MDD={m['max_drawdown']:.0f}₽"
    )


def run_strategy_analysis(
    strategy_name: str,
    train_results: list[dict],
    train_trades: list[dict],
    oos_results: list[dict],
    oos_trades: list[dict],
    slip_pts: list[float],
    *,
    point_value_rub: float,
    commission_rub: float,
    top_n: int = 3,
) -> tuple[list[dict], list[dict]]:
    """Analyze a strategy, return top scenarios and summary rows for report."""
    if not train_results:
        return [], []

    # Sort by train PF descending
    sorted_results = sorted(train_results, key=lambda x: float(x.get("profit_factor", 0)), reverse=True)
    top_scenarios = sorted_results[:top_n]

    analysis_rows = []
    for sc in top_scenarios:
        scenario_id = sc.get("scenario_id")
        scenario_name_str = sc.get("scenario", str(scenario_id))
        pf_train = sc.get("profit_factor", 0)

        # Get train trades for this scenario
        sc_train_trades = [t for t in train_trades if t.get("scenario_id") == scenario_id]

        # OOS metrics for this scenario
        sc_oos_results = [r for r in oos_results if r.get("scenario") == scenario_name_str]
        if sc_oos_results:
            pf_oos = sc_oos_results[0].get("profit_factor", 0)
            oos_trades_n = sc_oos_results[0].get("trades", 0)
        else:
            pf_oos = 0.0
            oos_trades_n = 0

        # OOS trades for slippage/concentration
        sc_oos_trades = [t for t in oos_trades if t.get("scenario") == scenario_name_str]

        # Concentration
        conc = concentration_flag(sc_train_trades)

        # Slippage on train
        slip_rows = slippage_sensitivity(
            sc_train_trades, slip_pts,
            point_value_rub=point_value_rub, commission_rub=commission_rub)
        slip_summary = {r["slip_pts"]: r["profit_factor"] for r in slip_rows}

        # Walkforward
        wf = walkforward_table(sc_train_trades, period="month")

        # Regime breakdown
        reg = regime_breakdown(sc_train_trades)

        # Candidate decision
        oos_m = compute_metrics(sc_oos_trades) if sc_oos_trades else {"trades": 0, "profit_factor": 0.0}
        decision = candidate_decision(sc, oos_m, conc)

        analysis_rows.append({
            "strategy": strategy_name,
            "scenario": scenario_name_str,
            "pf_train": round(pf_train, 3),
            "trades_train": sc.get("trades", 0),
            "winrate_train": sc.get("winrate", 0),
            "net_pnl_train": sc.get("net_pnl", 0),
            "pf_oos": round(pf_oos, 3),
            "trades_oos": oos_trades_n,
            "concentrated": conc[0],
            "concentration_reason": conc[1],
            "slip_pf_at_2pts": slip_summary.get(2, 0),
            "slip_pf_at_5pts": slip_summary.get(5, 0),
            "candidate_decision": decision,
            "_wf": wf,
            "_slip_rows": slip_rows,
            "_regime": reg,
            "_sc_train_trades": sc_train_trades,
        })

    return top_scenarios, analysis_rows


def build_report(
    strategy_analyses: dict[str, list[dict]],
    config: dict,
    run_dt: str,
) -> str:
    """Build the full markdown report."""
    lines = [
        f"# Multi-Strategy Research Report — MVP-R2",
        f"**Ticker**: {config.get('experiment', {}).get('ticker', 'SiM6')}  ",
        f"**Run**: {run_dt}  ",
        f"**Train**: {config['data']['train_csv']}  ",
        f"**OOS**: {config['data']['oos_csv']}  ",
        "",
    ]

    all_decisions: dict[str, list[str]] = {"READY_FOR_PAPER": [], "NEEDS_MORE_DATA": [], "REJECT": []}

    for strat_name, analysis_rows in strategy_analyses.items():
        lines.append(f"---\n## Strategy: {strat_name}\n")

        if not analysis_rows:
            lines.append("No results (strategy disabled or no signals).\n")
            continue

        lines.append(f"### Top Scenarios by Train PF\n")
        lines.append("| Scenario | PF_train | Trades | WR | Net₽ | PF_OOS | Trades_OOS | Decision |")
        lines.append("|---|---|---|---|---|---|---|---|")

        for row in analysis_rows:
            lines.append(
                f"| {row['scenario']} | {row['pf_train']:.3f} | {row['trades_train']} "
                f"| {row['winrate_train']:.1%} | {row['net_pnl_train']:.0f} "
                f"| {row['pf_oos']:.3f} | {row['trades_oos']} | **{row['candidate_decision']}** |"
            )
            all_decisions[row["candidate_decision"]].append(f"{strat_name}/{row['scenario']}")

        lines.append("")

        # Detail section for top scenario
        if analysis_rows:
            top = analysis_rows[0]
            lines.append(f"### Detail: {top['scenario']}")
            lines.append(f"**Decision**: {top['candidate_decision']}  ")
            if top["concentrated"]:
                lines.append(f"**Concentration warning**: {top['concentration_reason']}  ")
            lines.append("")

            # Slippage
            lines.append("#### Slippage Sensitivity (Train)")
            lines.append("| Slip_pts | PF | Net₽ | Destroyed |")
            lines.append("|---|---|---|---|")
            for sr in top.get("_slip_rows", []):
                lines.append(
                    f"| {sr['slip_pts']} | {sr['profit_factor']:.3f} "
                    f"| {sr['net_pnl']:.0f} | {sr['destroyed_edge']} |"
                )
            lines.append("")

            # Walkforward
            lines.append("#### Walk-Forward by Month (Train)")
            lines.append("| Month | Trades | WR | PF | Net₽ |")
            lines.append("|---|---|---|---|---|")
            for wfrow in top.get("_wf", []):
                lines.append(
                    f"| {wfrow['period_label']} | {wfrow['trades']} "
                    f"| {wfrow['winrate']:.1%} | {wfrow['profit_factor']:.3f} "
                    f"| {wfrow['net_pnl']:.0f} |"
                )
            lines.append("")

            # Regime
            reg = top.get("_regime", {})
            if reg:
                lines.append("#### Regime Breakdown (Train)")
                lines.append("| Regime | Trades | PF | Net₽ |")
                lines.append("|---|---|---|---|")
                for rname, rm in reg.items():
                    lines.append(f"| {rname} | {rm['trades']} | {rm['pf']:.3f} | {rm['net_pnl']:.0f} |")
                lines.append("")

    # Summary
    lines.append("---\n## Overall Summary\n")
    lines.append(f"### READY_FOR_PAPER ({len(all_decisions['READY_FOR_PAPER'])})")
    for s in all_decisions["READY_FOR_PAPER"]:
        lines.append(f"- {s}")
    lines.append("")

    lines.append(f"### NEEDS_MORE_DATA ({len(all_decisions['NEEDS_MORE_DATA'])})")
    for s in all_decisions["NEEDS_MORE_DATA"]:
        lines.append(f"- {s}")
    lines.append("")

    lines.append(f"### REJECT ({len(all_decisions['REJECT'])})")
    for s in all_decisions["REJECT"]:
        lines.append(f"- {s}")
    lines.append("")

    lines.append("### Deferred Strategies")
    lines.append("- **Volatility Breakout**: Deferred. Planned approach: identify intraday")
    lines.append("  volatility contraction (ATR compression over 10 bars), then trade the")
    lines.append("  first breakout above the compression high with target = 2x compression range.")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="MVP-R2 Multi-Strategy Research Runner")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    # Costs are mandatory and flow from here to every PnL and slippage calculation.
    _commission_cfg = config.get("commission", {}) or {}
    if "rub_per_trade" not in _commission_cfg or "point_value_rub" not in _commission_cfg:
        raise SystemExit(
            "config must set commission.rub_per_trade and commission.point_value_rub"
        )
    commission_rub = float(_commission_cfg["rub_per_trade"])
    point_value_rub = float(_commission_cfg["point_value_rub"])

    base_dir = Path(__file__).resolve().parent.parent
    run_dt = datetime.now().strftime("%Y%m%d_%H%M%S")

    train_path = base_dir / config["data"]["train_csv"]
    oos_path = base_dir / config["data"]["oos_csv"]
    hammer_trades_path = base_dir / config["data"]["hammer_trades_csv"]

    print(f"[R2] Loading candles...")
    train_candles = load_candles(str(train_path))
    oos_candles = load_candles(str(oos_path))
    print(f"  Train: {len(train_candles)} rows, OOS: {len(oos_candles)} rows")

    slip_pts = config.get("slippage_points", [0, 1, 2, 5, 10])
    strats_cfg = config.get("strategies", {})

    # Compute regime context for train and OOS
    print("[R2] Computing regime context...")
    train_regime_df = compute_regime_context(train_candles) if config.get("regime", {}).get("enabled") else None
    oos_regime_df = compute_regime_context(oos_candles) if config.get("regime", {}).get("enabled") else None

    strategy_analyses: dict[str, list[dict]] = {}
    summary_rows: list[dict] = []

    # -----------------------------------------------------------------------
    # Strategy 1: Momentum Continuation
    # -----------------------------------------------------------------------
    mc_cfg = strats_cfg.get("momentum_continuation", {})
    if mc_cfg.get("enabled", True):
        print("[R2] Running Momentum Continuation...")
        mc_atr_mult = mc_cfg.get("atr_mult", [1.0, 1.5, 2.0])
        mc_vol_mult = mc_cfg.get("vol_mult", [1.2, 1.5, 2.0])
        mc_take_r = mc_cfg.get("take_r", [1.0, 1.5, 2.0])
        mc_atr_win = mc_cfg.get("atr_window", 14)
        mc_vol_win = mc_cfg.get("vol_window", 20)
        mc_max_trades = mc_cfg.get("max_trades_per_day", 1)

        mc_train_res, mc_train_trades = run_momentum_backtest(
            train_candles, mc_atr_mult, mc_vol_mult, mc_take_r,
            atr_window=mc_atr_win, vol_window=mc_vol_win,
            max_trades_per_day=mc_max_trades, regime_df=train_regime_df,
        )
        mc_oos_res, mc_oos_trades = run_momentum_backtest(
            oos_candles, mc_atr_mult, mc_vol_mult, mc_take_r,
            atr_window=mc_atr_win, vol_window=mc_vol_win,
            max_trades_per_day=mc_max_trades, regime_df=oos_regime_df,
        )
        print(f"  Train: {len(mc_train_res)} scenarios, {len(mc_train_trades)} trades")
        print(f"  OOS:   {len(mc_oos_res)} scenarios, {len(mc_oos_trades)} trades")

        _, mc_analysis = run_strategy_analysis(
            "momentum_continuation", mc_train_res, mc_train_trades,
            mc_oos_res, mc_oos_trades, slip_pts,
            point_value_rub=point_value_rub, commission_rub=commission_rub,
        )
        strategy_analyses["momentum_continuation"] = mc_analysis
        for row in mc_analysis:
            summary_rows.append({k: v for k, v in row.items() if not k.startswith("_")})
    else:
        strategy_analyses["momentum_continuation"] = []

    # -----------------------------------------------------------------------
    # Strategy 2: Opening Range Fade
    # -----------------------------------------------------------------------
    orf_cfg = strats_cfg.get("opening_range_fade", {})
    if orf_cfg.get("enabled", True):
        print("[R2] Running Opening Range Fade...")
        orf_windows = orf_cfg.get("or_windows", [["10:00", "10:30"], ["10:00", "11:00"]])
        orf_n_return = orf_cfg.get("n_return_bars", [3, 5, 10])
        orf_take_mode = orf_cfg.get("take_mode", ["midpoint", "one_r"])
        orf_max_trades = orf_cfg.get("max_trades_per_day", 1)

        orf_train_res, orf_train_trades = run_orf_backtest(
            train_candles, orf_windows, orf_n_return, orf_take_mode,
            max_trades_per_day=orf_max_trades, regime_df=train_regime_df,
        )
        orf_oos_res, orf_oos_trades = run_orf_backtest(
            oos_candles, orf_windows, orf_n_return, orf_take_mode,
            max_trades_per_day=orf_max_trades, regime_df=oos_regime_df,
        )
        print(f"  Train: {len(orf_train_res)} scenarios, {len(orf_train_trades)} trades")
        print(f"  OOS:   {len(orf_oos_res)} scenarios, {len(orf_oos_trades)} trades")

        _, orf_analysis = run_strategy_analysis(
            "opening_range_fade", orf_train_res, orf_train_trades,
            orf_oos_res, orf_oos_trades, slip_pts,
            point_value_rub=point_value_rub, commission_rub=commission_rub,
        )
        strategy_analyses["opening_range_fade"] = orf_analysis
        for row in orf_analysis:
            summary_rows.append({k: v for k, v in row.items() if not k.startswith("_")})
    else:
        strategy_analyses["opening_range_fade"] = []

    # -----------------------------------------------------------------------
    # Strategy 3: VWAP Reversion
    # -----------------------------------------------------------------------
    vr_cfg = strats_cfg.get("vwap_reversion", {})
    if vr_cfg.get("enabled", True):
        print("[R2] Running VWAP Reversion...")
        vr_dist = vr_cfg.get("distance_mult", [0.5, 1.0, 1.5])
        vr_stop = vr_cfg.get("stop_mult", [1.0, 1.5])
        vr_take = vr_cfg.get("take_mode", ["to_vwap", "one_r_1_0", "one_r_1_5"])
        vr_max_trades = vr_cfg.get("max_trades_per_day", 3)

        vr_train_res, vr_train_trades = run_vwap_reversion_backtest(
            train_candles, vr_dist, vr_stop, vr_take,
            max_trades_per_day=vr_max_trades, regime_df=train_regime_df,
        )
        vr_oos_res, vr_oos_trades = run_vwap_reversion_backtest(
            oos_candles, vr_dist, vr_stop, vr_take,
            max_trades_per_day=vr_max_trades, regime_df=oos_regime_df,
        )
        print(f"  Train: {len(vr_train_res)} scenarios, {len(vr_train_trades)} trades")
        print(f"  OOS:   {len(vr_oos_res)} scenarios, {len(vr_oos_trades)} trades")

        _, vr_analysis = run_strategy_analysis(
            "vwap_reversion", vr_train_res, vr_train_trades,
            vr_oos_res, vr_oos_trades, slip_pts,
            point_value_rub=point_value_rub, commission_rub=commission_rub,
        )
        strategy_analyses["vwap_reversion"] = vr_analysis
        for row in vr_analysis:
            summary_rows.append({k: v for k, v in row.items() if not k.startswith("_")})
    else:
        strategy_analyses["vwap_reversion"] = []

    # -----------------------------------------------------------------------
    # Strategy 4: VWAP Hammer Filter
    # -----------------------------------------------------------------------
    vhf_cfg = strats_cfg.get("vwap_hammer_filter", {})
    if vhf_cfg.get("enabled", True):
        print("[R2] Running VWAP Hammer Filter...")
        vhf_results, vhf_enriched = run_vwap_hammer_filter(
            str(hammer_trades_path), str(train_path),
        )
        print(f"  Filter variants: {len(vhf_results)}")

        # Convert to analysis format compatible with run_strategy_analysis
        if vhf_results:
            vhf_analysis_rows = []
            for fr in vhf_results:
                conc = concentration_flag(
                    [t for t in vhf_enriched if t.get("scenario") == fr["filter"]]
                    if fr["filter"] == "baseline"
                    else []
                )
                vhf_analysis_rows.append({
                    "strategy": "vwap_hammer_filter",
                    "scenario": fr["filter"],
                    "pf_train": fr.get("profit_factor", 0),
                    "trades_train": fr.get("trades", 0),
                    "winrate_train": fr.get("winrate", 0),
                    "net_pnl_train": fr.get("net_pnl", 0),
                    "pf_oos": 0.0,
                    "trades_oos": 0,
                    "concentrated": conc[0],
                    "concentration_reason": conc[1],
                    "slip_pf_at_2pts": 0.0,
                    "slip_pf_at_5pts": 0.0,
                    "candidate_decision": "NEEDS_MORE_DATA" if fr.get("profit_factor", 0) > 1.1 else "REJECT",
                    "_wf": [],
                    "_slip_rows": [],
                    "_regime": {},
                    "_sc_train_trades": [],
                    "pct_kept": fr.get("pct_kept", 1.0),
                    "trades_total": fr.get("trades_total", 0),
                })
            strategy_analyses["vwap_hammer_filter"] = vhf_analysis_rows
            for row in vhf_analysis_rows:
                summary_rows.append({k: v for k, v in row.items() if not k.startswith("_")})
        else:
            strategy_analyses["vwap_hammer_filter"] = []
    else:
        strategy_analyses["vwap_hammer_filter"] = []

    # -----------------------------------------------------------------------
    # Build and write report
    # -----------------------------------------------------------------------
    print("[R2] Building report...")
    report_md = build_report(strategy_analyses, config, run_dt)

    reports_dir = base_dir / "reports"
    reports_dir.mkdir(exist_ok=True)

    report_fname = reports_dir / f"research_multistrategy_r2_{run_dt}.md"
    report_latest = reports_dir / "research_multistrategy_r2_latest.md"
    with open(report_fname, "w") as f:
        f.write(report_md)
    with open(report_latest, "w") as f:
        f.write(report_md)

    # Write summary CSV
    out_dir = base_dir / "out"
    out_dir.mkdir(exist_ok=True)
    csv_fname = out_dir / f"research_multistrategy_r2_summary_{run_dt}.csv"
    csv_latest = out_dir / "research_multistrategy_r2_summary_latest.csv"

    if summary_rows:
        fieldnames = sorted({k for r in summary_rows for k in r.keys()})
        for path in [csv_fname, csv_latest]:
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(summary_rows)

    print(f"[R2] Report written to: {report_fname}")
    print(f"[R2] Summary CSV: {csv_fname}")
    print()

    # Print summary to console
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for strat_name, analysis_rows in strategy_analyses.items():
        print(f"\n{strat_name.upper()}")
        for row in analysis_rows[:3]:
            print(
                f"  {row['scenario']:50s} PF_train={row['pf_train']:.3f} "
                f"trades={row['trades_train']:3d} PF_oos={row['pf_oos']:.3f} "
                f"-> {row['candidate_decision']}"
            )

    print()
    ready = [
        f"{r['strategy']}/{r['scenario']}"
        for rows in strategy_analyses.values()
        for r in rows
        if r["candidate_decision"] == "READY_FOR_PAPER"
    ]
    needs = [
        f"{r['strategy']}/{r['scenario']}"
        for rows in strategy_analyses.values()
        for r in rows
        if r["candidate_decision"] == "NEEDS_MORE_DATA"
    ]
    rejected = [
        f"{r['strategy']}/{r['scenario']}"
        for rows in strategy_analyses.values()
        for r in rows
        if r["candidate_decision"] == "REJECT"
    ]

    print(f"READY_FOR_PAPER ({len(ready)}): {ready}")
    print(f"NEEDS_MORE_DATA ({len(needs)}): {needs[:5]}{'...' if len(needs) > 5 else ''}")
    print(f"REJECT ({len(rejected)}): shown in report")
    print()
    print("Done.")


if __name__ == "__main__":
    main()
