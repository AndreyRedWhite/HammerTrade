#!/usr/bin/env python3
"""Hammer Reversal A/B Decision Report.

Compares baseline vs maxhold5 paper trading performance on the comparable window
and outputs a decision: CONTINUE / OBSERVE_ONLY / FREEZE.

Usage:
    python scripts/hammer_decision_report.py
    python scripts/hammer_decision_report.py \
        --baseline-db data/paper/paper_state.sqlite \
        --maxhold-db data/paper/paper_state_maxhold5.sqlite \
        --maxhold-start 2026-05-13
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPORT_DIR = "reports"


def parse_args():
    parser = argparse.ArgumentParser(description="Hammer Reversal A/B Decision Report")
    parser.add_argument(
        "--baseline-db",
        default="data/paper/paper_state.sqlite",
        help="Path to baseline paper_state.sqlite",
    )
    parser.add_argument(
        "--maxhold-db",
        default="data/paper/paper_state_maxhold5.sqlite",
        help="Path to maxhold5 paper_state_maxhold5.sqlite",
    )
    parser.add_argument(
        "--maxhold-start",
        default="2026-05-13",
        help="Start date for comparable window (ISO date, default 2026-05-13)",
    )
    return parser.parse_args()


def load_trades(db_path: str, since: str | None = None) -> list[dict]:
    """Load closed trades from paper_state SQLite."""
    if not os.path.exists(db_path):
        print(f"[WARN] DB not found: {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if since:
            cursor = conn.execute(
                "SELECT * FROM paper_trades WHERE status='CLOSED' AND signal_timestamp >= ?",
                (since,),
            )
        else:
            cursor = conn.execute("SELECT * FROM paper_trades WHERE status='CLOSED'")
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
    return rows


def load_open_trades(db_path: str) -> list[dict]:
    """Load currently open trades."""
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("SELECT * FROM paper_trades WHERE status='OPEN'")
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
    return rows


def load_status_json(db_path: str) -> dict:
    """Load latest status from paper_state key-value table."""
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("SELECT key, value FROM paper_state")
        rows = {row["key"]: row["value"] for row in cursor.fetchall()}
    finally:
        conn.close()
    return rows


def compute_metrics(trades: list[dict]) -> dict:
    """Compute strategy metrics from closed trades list."""
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0, "winrate": 0.0,
            "net_pnl": 0.0, "profit_factor": 0.0, "expectancy": 0.0,
            "max_drawdown": 0.0, "worst_trade": 0.0, "avg_bars_held": 0.0,
            "exit_reasons": {}, "bars_held_dist": {},
        }

    pnls = [float(t.get("pnl_rub", 0)) for t in trades]
    bars = [int(t.get("bars_held", 0)) for t in trades]

    wins = [p for p in pnls if p > 0]
    losses_list = [p for p in pnls if p <= 0]

    total = len(pnls)
    win_count = len(wins)
    net_pnl = sum(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses_list))

    if gross_loss > 0:
        pf = gross_profit / gross_loss
    elif gross_profit > 0:
        pf = float("inf")
    else:
        pf = 0.0

    expectancy = net_pnl / total if total > 0 else 0.0
    avg_bars = sum(bars) / len(bars) if bars else 0.0

    # Max drawdown
    peak = 0.0
    cum = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    # Exit reasons
    exit_reasons = Counter(t.get("exit_reason", "UNKNOWN") for t in trades)

    # Bars held distribution
    bars_dist: dict = defaultdict(int)
    for b in bars:
        bucket = f"{b}b"
        bars_dist[bucket] += 1

    return {
        "trades": total,
        "wins": win_count,
        "losses": len(losses_list),
        "winrate": round(win_count / total, 4) if total > 0 else 0.0,
        "net_pnl": round(net_pnl, 2),
        "profit_factor": round(pf, 4) if pf != float("inf") else 9999.0,
        "expectancy": round(expectancy, 2),
        "max_drawdown": round(max_dd, 2),
        "worst_trade": round(min(pnls), 2) if pnls else 0.0,
        "avg_bars_held": round(avg_bars, 2),
        "exit_reasons": dict(exit_reasons),
        "bars_held_dist": dict(sorted(bars_dist.items(), key=lambda x: int(x[0][:-1]))),
    }


def make_decision(
    baseline_m: dict,
    maxhold_m: dict,
    open_count: int,
) -> tuple[str, str]:
    """Apply decision rules and return (decision, reason)."""
    pf = maxhold_m["profit_factor"]
    trades = maxhold_m["trades"]
    net = maxhold_m["net_pnl"]
    baseline_net = baseline_m["net_pnl"]

    if trades == 0:
        return "OBSERVE_ONLY", "maxhold5 has no comparable trades yet"

    # FREEZE conditions
    if trades >= 60 and pf < 1.15:
        return (
            "FREEZE",
            f"maxhold5 PF={pf:.3f} < 1.15 after {trades} trades (≥60 threshold reached)"
        )
    if trades >= 10 and net < baseline_net * 0.8 and baseline_net > 0:
        return (
            "FREEZE",
            f"maxhold5 net_pnl={net:.2f} materially worse than baseline={baseline_net:.2f}"
        )

    # CONTINUE conditions
    if pf >= 1.25 and trades >= 3 and net > baseline_net:
        reason = (
            f"maxhold5 PF={pf:.3f} ≥ 1.25, net_pnl={net:.2f} > baseline={baseline_net:.2f}, "
            f"trades={trades}"
        )
        if open_count > 5:
            reason += f" (NOTE: {open_count} open trades — monitor liveness)"
        return "CONTINUE", reason

    # OBSERVE_ONLY
    if trades < 10:
        return "OBSERVE_ONLY", f"Insufficient trades ({trades} < 10) for robust conclusion"

    return (
        "OBSERVE_ONLY",
        f"maxhold5 PF={pf:.3f} (need ≥1.25 for CONTINUE, not yet ≥60 for FREEZE), "
        f"trades={trades}"
    )


def format_metrics_block(name: str, m: dict) -> list[str]:
    lines = [f"### {name}\n"]
    lines.append(f"- Trades: {m['trades']} (wins: {m['wins']}, losses: {m['losses']})")
    lines.append(f"- Winrate: {m['winrate']:.1%}")
    lines.append(f"- Net PnL: {m['net_pnl']:.2f} RUB")
    lines.append(f"- Profit Factor: {m['profit_factor']:.3f}")
    lines.append(f"- Expectancy: {m['expectancy']:.2f} RUB/trade")
    lines.append(f"- Max Drawdown: {m['max_drawdown']:.2f} RUB")
    lines.append(f"- Worst Trade: {m['worst_trade']:.2f} RUB")
    lines.append(f"- Avg Bars Held: {m['avg_bars_held']:.1f}")
    lines.append(f"- Exit Reasons: {m['exit_reasons']}")
    lines.append("")
    return lines


def main():
    args = parse_args()
    now = datetime.now()
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    since_str = args.maxhold_start + "T00:00:00"

    print(f"[hammer_decision_report] Baseline: {args.baseline_db}")
    print(f"[hammer_decision_report] Maxhold5: {args.maxhold_db}")
    print(f"[hammer_decision_report] Comparable window start: {args.maxhold_start}")

    # Load trades
    baseline_trades = load_trades(args.baseline_db, since=since_str)
    maxhold_trades = load_trades(args.maxhold_db, since=None)
    open_baseline = load_open_trades(args.baseline_db)
    open_maxhold = load_open_trades(args.maxhold_db)
    status_baseline = load_status_json(args.baseline_db)
    status_maxhold = load_status_json(args.maxhold_db)

    print(f"[hammer_decision_report] Baseline comparable trades: {len(baseline_trades)}")
    print(f"[hammer_decision_report] Maxhold5 trades: {len(maxhold_trades)}")

    baseline_m = compute_metrics(baseline_trades)
    maxhold_m = compute_metrics(maxhold_trades)

    open_count = len(open_maxhold) + len(open_baseline)
    decision, reason = make_decision(baseline_m, maxhold_m, len(open_maxhold))

    # Build report
    report_lines = []
    report_lines.append(f"# Hammer Reversal A/B Decision Report")
    report_lines.append(f"\nСгенерировано: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"\nСравнимое окно: с {args.maxhold_start} (старт maxhold5)\n")

    report_lines.append("## Решение\n")
    report_lines.append(f"**{decision}**\n")
    report_lines.append(f"Причина: {reason}\n")

    report_lines.append("## Метрики\n")
    report_lines.extend(format_metrics_block(
        f"Baseline (comparable: {args.maxhold_start} onwards)", baseline_m
    ))
    report_lines.extend(format_metrics_block("Maxhold5 (all trades)", maxhold_m))

    report_lines.append("## Операционный статус\n")
    report_lines.append(f"- Open trades baseline: {len(open_baseline)}")
    report_lines.append(f"- Open trades maxhold5: {len(open_maxhold)}")
    report_lines.append(f"- Baseline last processed: {status_baseline.get('last_processed:SiM6:1m:balanced:SELL', 'N/A')}")
    report_lines.append(f"- Maxhold5 last processed: {status_maxhold.get('last_processed:SiM6:1m:balanced:SELL', 'N/A')}")
    report_lines.append("")

    report_lines.append("## Детали maxhold5: выходы по причинам\n")
    for reason_key, count in maxhold_m.get("exit_reasons", {}).items():
        pct = count / maxhold_m["trades"] * 100 if maxhold_m["trades"] > 0 else 0
        report_lines.append(f"- {reason_key}: {count} ({pct:.1f}%)")
    report_lines.append("")

    report_lines.append("## Детали maxhold5: распределение bars_held\n")
    for bucket, count in maxhold_m.get("bars_held_dist", {}).items():
        report_lines.append(f"- {bucket}: {count}")
    report_lines.append("")

    # MAX_HOLD_EXIT contribution
    max_hold_count = maxhold_m.get("exit_reasons", {}).get("MAX_HOLD_EXIT", 0)
    if maxhold_m["trades"] > 0:
        mhe_pct = max_hold_count / maxhold_m["trades"] * 100
        report_lines.append(f"## MAX_HOLD_EXIT contribution\n")
        report_lines.append(f"- MAX_HOLD_EXIT trades: {max_hold_count} ({mhe_pct:.1f}% of total)")

        # Compute PnL for MAX_HOLD_EXIT trades
        mhe_trades = [t for t in maxhold_trades if t.get("exit_reason") == "MAX_HOLD_EXIT"]
        mhe_pnl = sum(float(t.get("pnl_rub", 0)) for t in mhe_trades)
        mhe_wins = sum(1 for t in mhe_trades if float(t.get("pnl_rub", 0)) > 0)
        report_lines.append(f"- MAX_HOLD_EXIT net PnL: {mhe_pnl:.2f} RUB")
        if mhe_trades:
            report_lines.append(f"- MAX_HOLD_EXIT winrate: {mhe_wins/len(mhe_trades):.1%}")
        report_lines.append("")

    report_lines.append("## Ограничения\n")
    report_lines.append(
        "- Сравниваются разные стратегии на одном и том же тикере/периоде, но параметры входа идентичны.\n"
        "- A/B тест не является чистым (нет рандомизации; maxhold5 запущен позже).\n"
        "- Майские данные не охватывают backtest-датасет — сравнение с историческими результатами невозможно напрямую.\n"
    )

    report_text = "\n".join(report_lines)

    # Print to stdout
    print("\n" + "=" * 60)
    print(report_text)
    print("=" * 60)

    # Write to file
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = os.path.join(REPORT_DIR, f"hammer_decision_report_{ts_str}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\n[hammer_decision_report] Report written: {report_path}")

    # Return exit code based on decision
    if decision == "FREEZE":
        sys.exit(2)
    elif decision == "OBSERVE_ONLY":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
