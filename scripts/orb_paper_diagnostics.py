"""ORB Paper Trading Diagnostics.

Reads OrbRepository and produces a diagnostics report with key metrics.

Usage:
    python scripts/orb_paper_diagnostics.py \\
        --state-db data/paper/paper_state_orb.sqlite \\
        --ticker SiM6 \\
        --experiment-name orb_or60_short2r \\
        --output reports/orb_paper_diagnostics_SiM6_latest.md
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.orb.models import OrbExitReason, OrbTradeStatus
from src.paper.orb.repository import OrbRepository


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ORB paper trading diagnostics")
    p.add_argument("--state-db", default="data/paper/paper_state_orb.sqlite")
    p.add_argument("--ticker", default="SiM6")
    p.add_argument("--experiment-name", default="orb_or60_short2r")
    p.add_argument("--output", default="reports/orb_paper_diagnostics_SiM6_latest.md")
    p.add_argument("--out-dir", default="out/paper")
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


def _or_range_avg(trades: list) -> float:
    ranges = []
    for t in trades:
        if t.or_high is not None and t.or_low is not None:
            ranges.append(t.or_high - t.or_low)
    return sum(ranges) / len(ranges) if ranges else 0.0


def build_diagnostics_report(
    trades: list,
    ticker: str,
    experiment_name: str,
    db_path: str,
) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = []

    closed = [t for t in trades if t.status == OrbTradeStatus.CLOSED]
    open_trades = [t for t in trades if t.status == OrbTradeStatus.OPEN]

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
    avg_or_range = _or_range_avg(trades)

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

    lines.append(f"# ORB Paper Diagnostics — {ticker} — {experiment_name}")
    lines.append("")
    lines.append(f"_Generated: {ts}_")
    lines.append(f"_DB: {db_path}_")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
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
    lines.append(f"| Avg OR range, pts | {avg_or_range:.1f} |")
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
        lines.append(f"> **LOW_SAMPLE**: only {len(closed)} closed trades. Results not statistically significant.")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    args = _parse_args()

    db_path = Path(args.state_db)
    if not db_path.exists():
        print(f"DB not found: {db_path}. No data to report.", file=sys.stderr)
        # Still write an empty report
        report = f"# ORB Paper Diagnostics — {args.ticker} — {args.experiment_name}\n\n_No data yet. DB not found: {db_path}_\n"
    else:
        repo = OrbRepository(str(db_path))
        repo.init_db()
        trades = repo.list_all_trades(ticker=args.ticker)
        report = build_diagnostics_report(
            trades=trades,
            ticker=args.ticker,
            experiment_name=args.experiment_name,
            db_path=str(db_path),
        )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    # Also export CSV to out_dir
    if db_path.exists():
        csv_path = Path(args.out_dir) / f"orb_diagnostics_{args.ticker}_{args.experiment_name}.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        repo = OrbRepository(str(db_path))
        repo.init_db()
        repo.export_csv(str(csv_path), ticker=args.ticker)
        print(f"CSV: {csv_path}")

    closed_count = report.count("| Closed trades |")
    print(f"Report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
