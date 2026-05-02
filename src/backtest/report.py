from pathlib import Path

import pandas as pd

from src.backtest.metrics import calculate_backtest_metrics


def generate_report(
    trades_df: pd.DataFrame,
    output_path: str,
    params: dict,
) -> None:
    m = calculate_backtest_metrics(trades_df)
    lines = []

    lines.append("# Backtest Report\n")

    lines.append("## Parameters\n")
    lines.append("| Parameter | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Entry mode | {params.get('entry_mode', 'breakout')} |")
    lines.append(f"| Entry horizon bars | {params.get('entry_horizon_bars', 3)} |")
    lines.append(f"| Max hold bars | {params.get('max_hold_bars', 30)} |")
    lines.append(f"| Take R | {params.get('take_r', 1.0)} |")
    lines.append(f"| Stop buffer points | {params.get('stop_buffer_points', 0)} |")
    lines.append(f"| Slippage points | {params.get('slippage_points', 0)} |")
    slip_ticks = params.get('slippage_ticks')
    if slip_ticks is not None:
        lines.append(f"| Slippage ticks | {slip_ticks} |")
        lines.append(f"| Tick size | {params.get('tick_size', '')} |")
        eff = slip_ticks * params.get('tick_size', 0) if params.get('tick_size') else 0
        lines.append(f"| Effective slippage points | {eff} |")
    lines.append(f"| Point value RUB | {params.get('point_value_rub', 10)} |")
    lines.append(f"| Commission per trade | {params.get('commission_per_trade', 0.025)} |")
    lines.append(f"| Contracts | {params.get('contracts', 1)} |")
    lines.append(f"| Allow overlap | {str(params.get('allow_overlap', False)).lower()} |")
    lines.append("")

    lines.append("## Summary\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Total signals | {m['total_signals']} |")
    lines.append(f"| Closed trades | {m['closed_trades']} |")
    lines.append(f"| Skipped trades | {m['skipped_trades']} |")
    lines.append(f"| Wins | {m['wins']} |")
    lines.append(f"| Losses | {m['losses']} |")
    lines.append(f"| Timeouts | {m['timeouts']} |")
    lines.append(f"| Winrate | {m['winrate']:.1%} |")
    lines.append(f"| Gross PnL RUB | {m['gross_pnl_rub']:.2f} |")
    lines.append(f"| Net PnL RUB | {m['net_pnl_rub']:.2f} |")
    lines.append(f"| Avg net PnL RUB | {m['avg_net_pnl_rub']:.2f} |")
    lines.append(f"| Median net PnL RUB | {m['median_net_pnl_rub']:.2f} |")
    pf = m['profit_factor']
    lines.append(f"| Profit factor | {'inf' if pf == float('inf') else f'{pf:.2f}'} |")
    lines.append(f"| Max win RUB | {m['max_win_rub']:.2f} |")
    lines.append(f"| Max loss RUB | {m['max_loss_rub']:.2f} |")
    lines.append(f"| Avg bars held | {m['avg_bars_held']:.1f} |")
    lines.append(f"| Max drawdown RUB | {m['max_drawdown_rub']:.2f} |")
    lines.append(f"| Max drawdown % | {m['max_drawdown_pct']:.1%} |")
    lines.append(f"| Ending equity RUB | {m['ending_equity_rub']:.2f} |")
    lines.append("")

    lines.append("## By Direction\n")
    lines.append("| Direction | Trades | Net PnL RUB |")
    lines.append("|---|---:|---:|")
    lines.append(f"| BUY | {m['buy_trades']} | {m['buy_net_pnl_rub']:.2f} |")
    lines.append(f"| SELL | {m['sell_trades']} | {m['sell_net_pnl_rub']:.2f} |")
    lines.append("")

    lines.append("## Exit Reasons\n")
    lines.append("| Exit reason | Count |")
    lines.append("|---|---:|")
    closed = trades_df[trades_df["status"] == "closed"]
    if len(closed):
        reason_counts = closed["exit_reason"].value_counts()
        for reason in ["take", "stop", "stop_same_bar", "timeout", "end_of_data"]:
            count = reason_counts.get(reason, 0)
            lines.append(f"| {reason} | {count} |")
    lines.append("")

    lines.append("## Trades\n")
    cols = [
        "trade_id", "signal_time", "direction", "entry_time",
        "entry_price", "stop_price", "take_price",
        "exit_time", "exit_price", "status", "exit_reason", "net_pnl_rub",
    ]
    header = "| " + " | ".join(cols) + " |"
    sep_parts = []
    for c in cols:
        if c in ("trade_id", "entry_price", "stop_price", "take_price", "exit_price", "net_pnl_rub"):
            sep_parts.append("---:")
        else:
            sep_parts.append("---")
    lines.append(header)
    lines.append("| " + " | ".join(sep_parts) + " |")

    for _, row in trades_df.iterrows():
        def fmt(v, c):
            if not isinstance(v, str) and pd.isna(v):
                return ""
            if c in ("entry_price", "stop_price", "take_price", "exit_price"):
                return f"{v:.1f}"
            if c == "net_pnl_rub":
                return f"{v:.2f}"
            return str(v)

        cells = [fmt(row[c], c) if c in row.index else "" for c in cols]
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("## Notes\n")
    lines.append("This is an offline historical backtest based on detector signals.")
    lines.append("It does not place real or sandbox orders.")
    lines.append(
        "It does not include slippage, order book liquidity, partial fills or real execution risks."
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
