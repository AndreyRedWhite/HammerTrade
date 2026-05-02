from pathlib import Path

import pandas as pd

from src.backtest.stability import calculate_period_stability, calculate_profit_concentration


# ─── Single walk-forward report ───────────────────────────────────────────────

def generate_walkforward_report(
    period_results_df: pd.DataFrame,
    all_period_trades_df: pd.DataFrame,
    output_path: str,
    params: dict,
) -> None:
    stab = calculate_period_stability(period_results_df)
    conc = calculate_profit_concentration(all_period_trades_df, period_results_df)
    lines = []

    lines.append("# Walk-forward Backtest Report\n")

    lines.append("## Parameters\n")
    lines.append("| Parameter | Value |")
    lines.append("|---|---:|")
    for key, label in [
        ("period", "Period"), ("entry_mode", "Entry mode"),
        ("entry_horizon_bars", "Entry horizon bars"), ("max_hold_bars", "Max hold bars"),
        ("take_r", "Take R"), ("stop_buffer_points", "Stop buffer points"),
        ("slippage_points", "Slippage points"), ("point_value_rub", "Point value RUB"),
        ("commission_per_trade", "Commission per trade"), ("contracts", "Contracts"),
        ("allow_overlap", "Allow overlap"),
    ]:
        v = params.get(key, "")
        if isinstance(v, bool):
            v = str(v).lower()
        lines.append(f"| {label} | {v} |")
    lines.append("")

    lines.append("## Stability Summary\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    pf = stab["period_profit_factor"]
    lines.append(f"| Periods total | {stab['periods_total']} |")
    lines.append(f"| Profitable periods | {stab['profitable_periods']} |")
    lines.append(f"| Losing periods | {stab['losing_periods']} |")
    lines.append(f"| Flat periods | {stab['flat_periods']} |")
    lines.append(f"| Profitable periods % | {stab['profitable_periods_pct']:.1%} |")
    lines.append(f"| Total net PnL RUB | {stab['total_net_pnl_rub']:.2f} |")
    lines.append(f"| Avg period net PnL RUB | {stab['avg_period_net_pnl_rub']:.2f} |")
    lines.append(f"| Median period net PnL RUB | {stab['median_period_net_pnl_rub']:.2f} |")
    lines.append(f"| Best period net PnL RUB | {stab['best_period_net_pnl_rub']:.2f} |")
    lines.append(f"| Worst period net PnL RUB | {stab['worst_period_net_pnl_rub']:.2f} |")
    lines.append(f"| Std period net PnL RUB | {stab['std_period_net_pnl_rub']:.2f} |")
    lines.append(f"| Max period drawdown RUB | {stab['max_period_drawdown_rub']:.2f} |")
    lines.append(f"| Period profit factor | {'inf' if pf == float('inf') else f'{pf:.2f}'} |")
    lines.append("")

    lines.append("## Profit Concentration\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Top 10% trades profit share | {conc['top_10pct_trades_profit_share']:.1%} |")
    lines.append(f"| Top 20% trades profit share | {conc['top_20pct_trades_profit_share']:.1%} |")
    lines.append(f"| Best trade profit share | {conc['best_trade_profit_share']:.1%} |")
    lines.append(f"| Best period profit share | {conc['best_period_profit_share']:.1%} |")
    lines.append(f"| Top 2 periods profit share | {conc['top_2_periods_profit_share']:.1%} |")
    lines.append("")

    lines.append("## Period Results\n")
    cols = [
        "period_key", "period_start", "period_end", "signals", "closed_trades",
        "winrate", "net_pnl_rub", "profit_factor", "max_drawdown_rub",
        "buy_net_pnl_rub", "sell_net_pnl_rub",
    ]
    lines.append(_table(period_results_df, cols))
    lines.append("")

    lines.append("## Worst Periods\n")
    worst_cols = ["period_key", "net_pnl_rub", "closed_trades", "winrate", "profit_factor", "max_drawdown_rub"]
    worst = period_results_df.nsmallest(5, "net_pnl_rub")
    lines.append(_table(worst, worst_cols))
    lines.append("")

    lines.append("## Best Periods\n")
    best = period_results_df.nlargest(5, "net_pnl_rub")
    lines.append(_table(best, worst_cols))
    lines.append("")

    lines.append("## Direction Breakdown\n")
    buy_periods = int((period_results_df["buy_net_pnl_rub"] > 0).sum()) if "buy_net_pnl_rub" in period_results_df.columns else 0
    sell_periods = int((period_results_df["sell_net_pnl_rub"] > 0).sum()) if "sell_net_pnl_rub" in period_results_df.columns else 0
    buy_trades = int(period_results_df["buy_trades"].sum()) if "buy_trades" in period_results_df.columns else 0
    sell_trades = int(period_results_df["sell_trades"].sum()) if "sell_trades" in period_results_df.columns else 0
    buy_pnl = stab["buy_total_net_pnl_rub"]
    sell_pnl = stab["sell_total_net_pnl_rub"]
    lines.append("| Direction | Total net PnL RUB | Profitable periods | Trades |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| BUY | {buy_pnl:.2f} | {buy_periods} | {buy_trades} |")
    lines.append(f"| SELL | {sell_pnl:.2f} | {sell_periods} | {sell_trades} |")
    lines.append("")

    lines.append("## Notes\n")
    lines.append("This is an offline walk-forward / multi-period analysis.")
    lines.append("Periods are isolated: trades do not carry over across period boundaries.")
    lines.append(
        "The report does not include live trading, sandbox orders, order book liquidity, "
        "queue position, partial fills or real broker execution."
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─── Walk-forward grid report ─────────────────────────────────────────────────

def generate_walkforward_grid_report(
    walkforward_grid_df: pd.DataFrame,
    output_path: str,
    source_path: str,
    period: str,
) -> None:
    # Build per-scenario stability table
    stab_rows = []
    for scenario_id, group in walkforward_grid_df.groupby("scenario_id"):
        n = len(group)
        pos = int((group["net_pnl_rub"] > 0).sum())
        pos_sum = float(group[group["net_pnl_rub"] > 0]["net_pnl_rub"].sum())
        neg_sum = float(group[group["net_pnl_rub"] < 0]["net_pnl_rub"].sum())
        pf = pos_sum / abs(neg_sum) if neg_sum < 0 else (float("inf") if pos_sum > 0 else 0.0)
        row0 = group.iloc[0]
        total_pnl = float(group["net_pnl_rub"].sum())
        worst = float(group["net_pnl_rub"].min())
        stab_rows.append({
            "scenario_id": int(scenario_id),
            "entry_mode": row0["entry_mode"],
            "take_r": row0["take_r"],
            "max_hold_bars": row0["max_hold_bars"],
            "stop_buffer_points": row0["stop_buffer_points"],
            "slippage_points": row0["slippage_points"],
            "periods_total": n,
            "profitable_periods_pct": pos / n,
            "total_net_pnl_rub": total_pnl,
            "worst_period_net_pnl_rub": worst,
            "period_profit_factor": pf,
        })
    stab_df = pd.DataFrame(stab_rows)
    stab_df = stab_df.sort_values(
        ["profitable_periods_pct", "total_net_pnl_rub"], ascending=[False, False]
    ).reset_index(drop=True)

    n_scenarios = len(stab_df)
    n_periods = walkforward_grid_df["period_key"].nunique()

    lines = []
    lines.append("# Walk-forward Grid Report\n")

    lines.append("## Input\n")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Source | {source_path} |")
    lines.append(f"| Period | {period} |")
    lines.append(f"| Scenarios | {n_scenarios} |")
    lines.append(f"| Periods | {n_periods} |")
    lines.append("")

    lines.append("## Scenario Stability Ranking (top 20)\n")
    rank_cols = [
        "scenario_id", "entry_mode", "take_r", "max_hold_bars",
        "stop_buffer_points", "slippage_points",
        "periods_total", "profitable_periods_pct",
        "total_net_pnl_rub", "worst_period_net_pnl_rub", "period_profit_factor",
    ]
    lines.append(_table(stab_df.head(20), rank_cols))
    lines.append("")

    # Robust scenarios
    robust_mask = (
        (stab_df["periods_total"] >= 4) &
        (stab_df["profitable_periods_pct"] >= 0.6) &
        (stab_df["total_net_pnl_rub"] > 0) &
        (stab_df["period_profit_factor"] >= 1.2) &
        (stab_df["worst_period_net_pnl_rub"] > -stab_df["total_net_pnl_rub"].abs())
    )
    robust = stab_df[robust_mask]

    lines.append("## Robust Scenarios\n")
    lines.append(
        "Scenarios that satisfy: periods_total >= 4, profitable_periods_pct >= 60%, "
        "total_net_pnl_rub > 0, period_profit_factor >= 1.2, "
        "worst_period not catastrophically negative.\n"
    )
    robust_cols = [
        "scenario_id", "entry_mode", "take_r", "max_hold_bars",
        "stop_buffer_points", "slippage_points",
        "profitable_periods_pct", "total_net_pnl_rub",
        "worst_period_net_pnl_rub", "period_profit_factor",
    ]
    if len(robust) > 0:
        lines.append(_table(robust, robust_cols))
    else:
        lines.append("No scenarios satisfied all robustness criteria.")
    lines.append("")

    # Fragile scenarios: profitable overall but poor period stability
    fragile_mask = (
        (stab_df["total_net_pnl_rub"] > 0) &
        (
            (stab_df["profitable_periods_pct"] < 0.6) |
            (stab_df["period_profit_factor"] < 1.2)
        )
    )
    fragile = stab_df[fragile_mask]

    lines.append("## Fragile Scenarios\n")
    lines.append("Scenarios that are profitable overall but have poor period stability.\n")
    fragile_cols = [
        "scenario_id", "entry_mode", "take_r", "max_hold_bars",
        "stop_buffer_points", "slippage_points",
        "total_net_pnl_rub", "profitable_periods_pct", "worst_period_net_pnl_rub",
    ]
    if len(fragile) > 0:
        lines.append(_table(fragile.head(20), fragile_cols))
    else:
        lines.append("No fragile scenarios found.")
    lines.append("")

    lines.append("## Notes\n")
    lines.append("Grid walk-forward is used to evaluate robustness, not to overfit parameters.")
    lines.append(
        "Period isolation: trades do not carry over across period boundaries. "
        "Each period is an independent backtest."
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─── Shared table helper ──────────────────────────────────────────────────────

def _table(df: pd.DataFrame, cols: list) -> str:
    avail = [c for c in cols if c in df.columns]
    df = df[avail].copy()

    header = "| " + " | ".join(avail) + " |"
    seps = []
    for c in avail:
        dtype = df[c].dtype
        seps.append("---" if dtype == object else "---:")
    sep_line = "| " + " | ".join(seps) + " |"

    data_lines = [header, sep_line]
    for _, row in df.iterrows():
        cells = []
        for c in avail:
            v = row[c]
            try:
                is_na = pd.isna(v)
            except (TypeError, ValueError):
                is_na = False
            if is_na:
                cells.append("")
            elif isinstance(v, float):
                if c in ("winrate", "profitable_periods_pct"):
                    cells.append(f"{v:.1%}")
                elif c == "period_profit_factor" and v == float("inf"):
                    cells.append("inf")
                elif c in ("profit_factor",) and v == float("inf"):
                    cells.append("inf")
                else:
                    cells.append(f"{v:.2f}")
            else:
                cells.append(str(v))
        data_lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(data_lines)
