"""Momentum Continuation Paper Trading Diagnostics.

Reads MomentumRepository and produces a diagnostics report with key metrics.

Usage:
    python scripts/momentum_paper_diagnostics.py \\
        --state-db data/paper/paper_state_siu6_momentum.sqlite \\
        --ticker SiU6 \\
        --experiment-name momentum_mc_atr2_vol2_r2
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.momentum.models import MomentumExitReason, MomentumTradeStatus
from src.paper.momentum.repository import MomentumRepository


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Momentum paper trading diagnostics")
    p.add_argument("--state-db", default="data/paper/paper_state_siu6_momentum.sqlite")
    p.add_argument("--ticker", default="SiU6")
    p.add_argument("--experiment-name", default="momentum_mc_atr2_vol2_r2")
    p.add_argument(
        "--output",
        default=None,
        help="Output MD file path (default: auto-generated with timestamp)",
    )
    p.add_argument("--out-dir", default="out/paper")
    p.add_argument("--reports-dir", default="reports")
    return p.parse_args()


def _compute_drawdown(trades: list) -> float:
    """Compute maximum drawdown from closed trades (in RUB)."""
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.entry_timestamp):
        equity += t.pnl_rub or 0.0
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return max_dd


def build_diagnostics_report(
    trades: list,
    ticker: str,
    experiment_name: str,
    db_path: str,
) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = []

    closed = [t for t in trades if t.status == MomentumTradeStatus.CLOSED]
    open_trades = [t for t in trades if t.status == MomentumTradeStatus.OPEN]

    lines.append(f"# Momentum Continuation Paper Diagnostics — {ticker} — {experiment_name}")
    lines.append("")
    lines.append(f"_Generated: {ts}_")
    lines.append(f"_DB: {db_path}_")
    lines.append("")

    if len(closed) == 0:
        lines.append("## No closed trades yet.")
        lines.append("")
        lines.append(f"Total trades in DB: {len(trades)}")
        lines.append(f"Open trades: {len(open_trades)}")
        lines.append("")
        lines.append("> Strategy has not generated any completed trades yet.")
        return "\n".join(lines)

    wins = [t for t in closed if (t.pnl_rub or 0) > 0]
    losses = [t for t in closed if (t.pnl_rub or 0) < 0]
    gross_p = sum(t.pnl_rub for t in wins) if wins else 0.0
    gross_l = sum(t.pnl_rub for t in losses) if losses else 0.0
    net_pnl = sum(t.pnl_rub or 0 for t in closed)
    pf = (gross_p / abs(gross_l)) if gross_l != 0 else float("inf")
    expectancy = net_pnl / len(closed) if closed else 0.0
    best = max((t.pnl_rub or 0 for t in closed), default=0.0)
    worst = min((t.pnl_rub or 0 for t in closed), default=0.0)
    winrate = 100.0 * len(wins) / len(closed) if closed else 0.0
    max_dd = _compute_drawdown(closed)

    # ATR and range stats
    atr_vals = [t.atr_value for t in closed if t.atr_value]
    avg_atr = sum(atr_vals) / len(atr_vals) if atr_vals else 0.0
    range_vals = [t.candle_range for t in closed if t.candle_range]
    avg_range = sum(range_vals) / len(range_vals) if range_vals else 0.0

    # Exit reason breakdown
    exit_reasons: dict[str, int] = defaultdict(int)
    for t in closed:
        r = (
            t.exit_reason.value
            if t.exit_reason and hasattr(t.exit_reason, "value")
            else str(t.exit_reason)
        ) or "UNKNOWN"
        exit_reasons[r] += 1

    # Daily breakdown
    daily: dict[str, dict] = defaultdict(lambda: {"trades": 0, "net": 0.0, "wins": 0})
    for t in closed:
        if t.entry_timestamp:
            d = t.entry_timestamp.date().isoformat()
        else:
            d = "?"
        daily[d]["trades"] += 1
        daily[d]["net"] += t.pnl_rub or 0.0
        if (t.pnl_rub or 0) > 0:
            daily[d]["wins"] += 1

    # First/last trade dates
    dated = [t for t in closed if t.entry_timestamp]
    first_date = min(t.entry_timestamp for t in dated).date().isoformat() if dated else "—"
    last_date = max(t.entry_timestamp for t in dated).date().isoformat() if dated else "—"

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Ticker | {ticker} |")
    lines.append(f"| Experiment | {experiment_name} |")
    lines.append(f"| Period | {first_date} – {last_date} |")
    lines.append(f"| Closed trades | {len(closed)} |")
    lines.append(f"| Open trades | {len(open_trades)} |")
    lines.append(f"| Wins | {len(wins)} |")
    lines.append(f"| Losses | {len(losses)} |")
    lines.append(f"| Winrate | {winrate:.1f}% |")
    lines.append(f"| Gross profit, RUB | {gross_p:+.2f} |")
    lines.append(f"| Gross loss, RUB | {gross_l:+.2f} |")
    lines.append(f"| Net PnL, RUB | {net_pnl:+.2f} |")
    pf_str = f"{pf:.3f}" if pf != float("inf") else "∞"
    lines.append(f"| Profit factor | {pf_str} |")
    lines.append(f"| Expectancy, RUB | {expectancy:+.2f} |")
    lines.append(f"| Best trade, RUB | {best:+.2f} |")
    lines.append(f"| Worst trade, RUB | {worst:+.2f} |")
    lines.append(f"| Max drawdown, RUB | {max_dd:.2f} |")
    lines.append(f"| Avg ATR at signal, pts | {avg_atr:.2f} |")
    lines.append(f"| Avg candle range, pts | {avg_range:.2f} |")
    lines.append("")

    lines.append("## Exit Reason Breakdown")
    lines.append("")
    lines.append("| Exit Reason | Count |")
    lines.append("|---|---:|")
    for reason, count in sorted(exit_reasons.items()):
        lines.append(f"| {reason} | {count} |")
    lines.append("")

    lines.append("## Daily Breakdown")
    lines.append("")
    lines.append("| Date | Trades | Wins | Net PnL, RUB | WR% |")
    lines.append("|---|---:|---:|---:|---:|")
    for d in sorted(daily.keys()):
        dd = daily[d]
        wr = 100.0 * dd["wins"] / dd["trades"] if dd["trades"] else 0.0
        lines.append(
            f"| {d} | {dd['trades']} | {dd['wins']} | {dd['net']:+.2f} | {wr:.0f}% |"
        )
    lines.append("")

    if len(closed) < 20:
        lines.append(
            f"> **LOW_SAMPLE**: only {len(closed)} closed trades. Results not statistically significant."
        )
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    args = _parse_args()

    ts_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = reports_dir / f"momentum_paper_diagnostics_{ts_str}.md"

    latest_path = reports_dir / "momentum_paper_diagnostics_latest.md"

    db_path = Path(args.state_db)
    if not db_path.exists():
        print(f"DB not found: {db_path}. No data to report.", file=sys.stderr)
        report = (
            f"# Momentum Continuation Paper Diagnostics — {args.ticker} — {args.experiment_name}\n\n"
            f"_No data yet. DB not found: {db_path}_\n\n"
            f"> No closed trades yet.\n"
        )
    else:
        repo = MomentumRepository(str(db_path))
        repo.init_db()
        trades = repo.list_all_trades(ticker=args.ticker)
        report = build_diagnostics_report(
            trades=trades,
            ticker=args.ticker,
            experiment_name=args.experiment_name,
            db_path=str(db_path),
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    latest_path.write_text(report, encoding="utf-8")

    # Export CSV
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_ts_path = out_dir / f"momentum_paper_trades_diagnostics_{ts_str}.csv"
    csv_latest_path = out_dir / "momentum_paper_trades_diagnostics_latest.csv"

    if db_path.exists():
        repo = MomentumRepository(str(db_path))
        repo.init_db()
        repo.export_csv(str(csv_ts_path), ticker=args.ticker)
        import shutil
        shutil.copy2(str(csv_ts_path), str(csv_latest_path))
        print(f"CSV: {csv_ts_path}")
        print(f"CSV (latest): {csv_latest_path}")
    else:
        # Write empty CSV header
        with open(str(csv_ts_path), "w", encoding="utf-8") as f:
            f.write(
                "trade_id,strategy_name,experiment_name,ticker,direction,"
                "signal_timestamp,entry_timestamp,entry_price,stop_price,take_price,"
                "atr_value,volume_value,volume_avg,candle_range,close_position,"
                "status,exit_timestamp,exit_price,exit_reason,pnl_points,pnl_rub,"
                "bars_held,created_at,updated_at\n"
            )
        import shutil
        shutil.copy2(str(csv_ts_path), str(csv_latest_path))

    print(f"Report: {out_path}")
    print(f"Report (latest): {latest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
