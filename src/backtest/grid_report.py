from pathlib import Path

import pandas as pd


def generate_grid_report(
    grid_df: pd.DataFrame,
    output_path: str,
    source_path: str,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
    signals_count: int = 0,
) -> None:
    lines = []
    lines.append("# Backtest Grid Report\n")

    lines.append("## Input\n")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Source | {source_path} |")
    lines.append(f"| Scenarios | {len(grid_df)} |")
    lines.append(f"| Signals | {signals_count} |")
    lines.append(f"| Point value RUB | {point_value_rub} |")
    lines.append(f"| Commission per trade | {commission_per_trade} |")
    lines.append(f"| Contracts | {contracts} |")
    lines.append("")

    use_ticks = "slippage_ticks" in grid_df.columns and grid_df["slippage_ticks"].notna().any()
    slip_col = "slippage_ticks" if use_ticks else "slippage_points"

    top_cols = [
        "scenario_id", "entry_mode", "take_r", "max_hold_bars",
        "stop_buffer_points", slip_col,
        "net_pnl_rub", "winrate", "profit_factor", "max_drawdown_rub",
    ]
    top10 = grid_df.nlargest(10, "net_pnl_rub")
    worst10 = grid_df.nsmallest(10, "net_pnl_rub")

    lines.append("## Top scenarios by Net PnL\n")
    lines.append(_table(top10, top_cols))
    lines.append("")

    lines.append("## Worst scenarios by Net PnL\n")
    lines.append(_table(worst10, top_cols))
    lines.append("")

    lines.append("## Slippage points sensitivity\n")
    lines.append(_sensitivity_table(grid_df, "slippage_points"))
    lines.append("")

    if use_ticks:
        lines.append("## Slippage ticks sensitivity\n")
        lines.append(_sensitivity_table(grid_df, "slippage_ticks"))
        lines.append("")

    lines.append("## Take R sensitivity\n")
    lines.append(_sensitivity_table(grid_df, "take_r"))
    lines.append("")

    lines.append("## Entry mode comparison\n")
    lines.append(_sensitivity_table(grid_df, "entry_mode"))
    lines.append("")

    lines.append("## Stop buffer sensitivity\n")
    lines.append(_sensitivity_table(grid_df, "stop_buffer_points"))
    lines.append("")

    lines.append("## Robust scenarios\n")
    lines.append(
        "Scenarios that satisfy: net_pnl_rub > 0, profit_factor >= 1.2, "
        "closed_trades >= 20, max_drawdown_rub <= net_pnl_rub * 2.\n"
    )
    robust_mask = (
        (grid_df["net_pnl_rub"] > 0)
        & (grid_df["profit_factor"] >= 1.2)
        & (grid_df["closed_trades"] >= 20)
        & (grid_df["max_drawdown_rub"] <= grid_df["net_pnl_rub"] * 2)
    )
    robust = grid_df[robust_mask]
    robust_cols = [
        "scenario_id", "entry_mode", "take_r", "max_hold_bars",
        "stop_buffer_points", slip_col,
        "net_pnl_rub", "profit_factor", "max_drawdown_rub",
    ]
    if len(robust) > 0:
        lines.append(_table(robust, robust_cols))
    else:
        lines.append("No scenarios satisfied all robustness criteria.")
    lines.append("")

    lines.append("## Notes\n")
    lines.append("This report is an offline robustness analysis.")
    lines.append("It does not prove that the strategy is profitable in live trading.")
    lines.append(
        "It does not include order book liquidity, queue position, "
        "partial fills or real broker execution."
    )
    lines.append(
        "Grid backtest is used to check strategy robustness, "
        "not to fit parameters to historical data."
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sensitivity_table(grid_df: pd.DataFrame, group_col: str) -> str:
    is_str = grid_df[group_col].dtype == object
    rows = []
    for val, grp in grid_df.groupby(group_col):
        profitable = (grp["net_pnl_rub"] > 0).sum()
        rows.append({
            group_col: val,
            "scenarios": len(grp),
            "profitable_scenarios": int(profitable),
            "avg_net_pnl_rub": grp["net_pnl_rub"].mean(),
            "median_net_pnl_rub": grp["net_pnl_rub"].median(),
            "best_net_pnl_rub": grp["net_pnl_rub"].max(),
            "worst_net_pnl_rub": grp["net_pnl_rub"].min(),
        })
    df = pd.DataFrame(rows)
    cols = [group_col, "scenarios", "profitable_scenarios",
            "avg_net_pnl_rub", "median_net_pnl_rub",
            "best_net_pnl_rub", "worst_net_pnl_rub"]
    return _table(df, cols)


def _table(df: pd.DataFrame, cols: list) -> str:
    df = df[cols].copy()
    header = "| " + " | ".join(cols) + " |"

    seps = []
    for c in cols:
        dtype = df[c].dtype if c in df.columns else "object"
        if dtype == object:
            seps.append("---")
        else:
            seps.append("---:")
    sep_line = "| " + " | ".join(seps) + " |"

    data_lines = [header, sep_line]
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if pd.isna(v) if not isinstance(v, str) else False:
                cells.append("")
            elif isinstance(v, float):
                if c in ("winrate",):
                    cells.append(f"{v:.1%}")
                elif c in ("profit_factor",):
                    cells.append("inf" if v == float("inf") else f"{v:.2f}")
                else:
                    cells.append(f"{v:.2f}")
            else:
                cells.append(str(v))
        data_lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(data_lines)
