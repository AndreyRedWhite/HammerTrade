"""Sandbox Execution Diagnostics — Hammer MaxHold5, SiU6 (MVP-L1a).

Reads SandboxRepository and produces a diagnostics report covering trades,
orders, risk state, and reconciliation status. Must not crash if no trades
have been recorded yet (e.g. before the first sandbox order is placed).

Usage:
    python scripts/sandbox_diagnostics.py \\
        --state-db data/sandbox/sandbox_state_hammer_maxhold5_siu6.sqlite \\
        --ticker SiU6 \\
        --experiment-name sandbox_hammer_maxhold5 \\
        --output reports/sandbox_diagnostics_hammer_maxhold5_latest.md \\
        --out-csv out/sandbox/sandbox_diagnostics_hammer_maxhold5_latest.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sandbox.models import SandboxTradeStatus
from src.sandbox.repository import SandboxRepository

_TRADE_CSV_FIELDS = [
    "trade_id", "signal_id", "entry_order_id", "exit_order_id", "ticker", "direction",
    "qty", "entry_time", "entry_price", "stop_price", "take_price", "status",
    "exit_time", "exit_price", "exit_reason", "gross_pnl_rub", "commission_rub",
    "net_pnl_rub", "bars_held", "created_at", "updated_at",
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sandbox execution diagnostics (hammer-maxhold5)")
    p.add_argument("--state-db", default="data/sandbox/sandbox_state_hammer_maxhold5_siu6.sqlite")
    p.add_argument("--ticker", default="SiU6")
    p.add_argument("--experiment-name", default="sandbox_hammer_maxhold5")
    p.add_argument("--output", default="reports/sandbox_diagnostics_hammer_maxhold5_latest.md")
    p.add_argument("--out-csv", default="out/sandbox/sandbox_diagnostics_hammer_maxhold5_latest.csv")
    return p.parse_args()


def _today_msk() -> str:
    return datetime.now(tz=timezone.utc).astimezone(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d")


def _compute_drawdown(trades: list) -> float:
    """Compute maximum drawdown from closed trades (in RUB), in entry_time order."""
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.entry_time or datetime.min.replace(tzinfo=timezone.utc)):
        equity += t.net_pnl_rub or 0.0
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return max_dd


def build_diagnostics_report(
    *,
    trades: list,
    orders: list,
    events: list,
    position,
    risk_state,
    daily_risk_today,
    ticker: str,
    experiment_name: str,
    db_path: str,
) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = []

    closed = [t for t in trades if t.status == SandboxTradeStatus.CLOSED]
    open_trades = [t for t in trades if t.status == SandboxTradeStatus.OPEN]

    wins = [t for t in closed if (t.net_pnl_rub or 0) > 0]
    losses = [t for t in closed if (t.net_pnl_rub or 0) < 0]
    gross_p = sum(t.net_pnl_rub for t in wins) if wins else 0.0
    gross_l = sum(t.net_pnl_rub for t in losses) if losses else 0.0
    net_pnl = sum(t.net_pnl_rub or 0 for t in closed)
    pf = (gross_p / abs(gross_l)) if gross_l != 0 else float("inf")
    expectancy = net_pnl / len(closed) if closed else 0.0
    best = max((t.net_pnl_rub or 0 for t in closed), default=0.0)
    worst = min((t.net_pnl_rub or 0 for t in closed), default=0.0)
    winrate = 100.0 * len(wins) / len(closed) if closed else 0.0
    max_dd = _compute_drawdown(closed)

    dated = [t for t in closed if t.entry_time]
    first_date = min(t.entry_time for t in dated).date().isoformat() if dated else "—"
    last_date = max(t.entry_time for t in dated).date().isoformat() if dated else "—"

    lines.append(f"# Sandbox Execution Diagnostics — {ticker} — {experiment_name}")
    lines.append("")
    lines.append(f"_Generated: {ts}_")
    lines.append(f"_DB: {db_path}_")
    lines.append("")

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
    lines.append("")

    lines.append("## Order Status Breakdown")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|---|---:|")
    order_status_counts: dict[str, int] = defaultdict(int)
    for o in orders:
        status = o.status.value if hasattr(o.status, "value") else str(o.status)
        order_status_counts[status] += 1
    if order_status_counts:
        for status in sorted(order_status_counts):
            lines.append(f"| {status} | {order_status_counts[status]} |")
    else:
        lines.append("| _no orders yet_ | 0 |")
    lines.append("")

    lines.append("## Exit Reason Breakdown")
    lines.append("")
    lines.append("| Exit Reason | Count |")
    lines.append("|---|---:|")
    exit_reasons: dict[str, int] = defaultdict(int)
    for t in closed:
        r = t.exit_reason.value if t.exit_reason and hasattr(t.exit_reason, "value") else str(t.exit_reason)
        exit_reasons[r or "UNKNOWN"] += 1
    if exit_reasons:
        for reason in sorted(exit_reasons):
            lines.append(f"| {reason} | {exit_reasons[reason]} |")
    else:
        lines.append("| _no closed trades yet_ | 0 |")
    lines.append("")

    lines.append("## Daily Breakdown")
    lines.append("")
    lines.append("| Date | Trades | Wins | Net PnL, RUB | WR% |")
    lines.append("|---|---:|---:|---:|---:|")
    daily: dict[str, dict] = defaultdict(lambda: {"trades": 0, "net": 0.0, "wins": 0})
    for t in closed:
        d = t.entry_time.date().isoformat() if t.entry_time else "?"
        daily[d]["trades"] += 1
        daily[d]["net"] += t.net_pnl_rub or 0.0
        if (t.net_pnl_rub or 0) > 0:
            daily[d]["wins"] += 1
    if daily:
        for d in sorted(daily.keys()):
            dd = daily[d]
            wr = 100.0 * dd["wins"] / dd["trades"] if dd["trades"] else 0.0
            lines.append(f"| {d} | {dd['trades']} | {dd['wins']} | {dd['net']:+.2f} | {wr:.0f}% |")
    else:
        lines.append("| _no closed trades yet_ | 0 | 0 | 0.00 | 0% |")
    lines.append("")

    lines.append("## Risk State")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Total PnL, RUB | {risk_state.total_pnl_rub:+.2f} |")
    lines.append(f"| Consecutive errors | {risk_state.consecutive_errors} |")
    lines.append(f"| Consecutive losses | {risk_state.consecutive_losses} |")
    lines.append(f"| Trading paused | {risk_state.trading_paused} |")
    lines.append(f"| Trading paused reason | {risk_state.trading_paused_reason or '—'} |")
    lines.append(f"| Reconciliation status | {risk_state.reconciliation_status} |")
    lines.append(f"| Last reconciliation at | {risk_state.last_reconciliation_at or '—'} |")
    lines.append("")

    lines.append("## Today's Risk")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Date (MSK) | {daily_risk_today.date_msk} |")
    lines.append(f"| Trades today | {daily_risk_today.trades_today} |")
    lines.append(f"| Realized PnL today, RUB | {daily_risk_today.realized_pnl_rub:+.2f} |")
    lines.append(f"| Consecutive losses today | {daily_risk_today.consecutive_losses} |")
    lines.append(f"| Daily loss breached | {daily_risk_today.daily_loss_breached} |")
    lines.append("")

    lines.append("## Current Position")
    lines.append("")
    if position is not None:
        lines.append("| Field | Value |")
        lines.append("|---|---:|")
        lines.append(f"| Direction | {position.direction} |")
        lines.append(f"| Qty | {position.qty} |")
        lines.append(f"| Avg price | {position.avg_price if position.avg_price is not None else '—'} |")
        lines.append(f"| Updated at | {position.updated_at or '—'} |")
    else:
        lines.append("_No position recorded yet (FLAT)._")
    lines.append("")

    lines.append("## Recent Events")
    lines.append("")
    if events:
        lines.append("| Timestamp | Type | Message |")
        lines.append("|---|---|---|")
        for e in events[:20]:
            lines.append(f"| {e.timestamp} | {e.event_type} | {e.message} |")
    else:
        lines.append("_No events recorded yet._")
    lines.append("")

    if len(closed) < 20:
        lines.append(f"> **LOW_SAMPLE**: only {len(closed)} closed trades. Results not statistically significant.")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    args = _parse_args()

    db_path = Path(args.state_db)
    out_csv = Path(args.out_csv)

    if not db_path.exists():
        print(f"DB not found: {db_path}. No data to report yet.", file=sys.stderr)
        report = (
            f"# Sandbox Execution Diagnostics — {args.ticker} — {args.experiment_name}\n\n"
            f"_No data yet. DB not found: {db_path}_\n"
        )
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=_TRADE_CSV_FIELDS).writeheader()
    else:
        repo = SandboxRepository(str(db_path))
        repo.init_db()
        trades = repo.list_trades(ticker=args.ticker)
        orders = repo.list_orders(ticker=args.ticker)
        events = repo.list_events(limit=20)
        position = repo.get_position(args.ticker)
        risk_state = repo.load_risk_state()
        daily_risk_today = repo.load_daily_risk(_today_msk())

        report = build_diagnostics_report(
            trades=trades,
            orders=orders,
            events=events,
            position=position,
            risk_state=risk_state,
            daily_risk_today=daily_risk_today,
            ticker=args.ticker,
            experiment_name=args.experiment_name,
            db_path=str(db_path),
        )

        repo.export_trades_csv(str(out_csv))

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    print(f"Report: {out_path}")
    print(f"CSV: {out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
