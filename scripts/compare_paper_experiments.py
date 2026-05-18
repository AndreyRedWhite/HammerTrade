"""A/B comparison of two parallel paper trading experiments.

Usage:
    python scripts/compare_paper_experiments.py \\
        --baseline-db  data/paper/paper_state.sqlite \\
        --experiment-db data/paper/paper_state_maxhold5.sqlite \\
        --baseline-name baseline \\
        --experiment-name maxhold5 \\
        --output reports/paper_ab_compare_baseline_vs_maxhold5_latest.md
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.models import PaperTradeStatus
from src.paper.repository import PaperRepository


# ─────────────────────────────── metrics ────────────────────────────────────

def _compute_metrics(trades: list, name: str) -> dict:
    closed = [t for t in trades if t.status == PaperTradeStatus.CLOSED]
    open_n = [t for t in trades if t.status == PaperTradeStatus.OPEN]
    wins = [t for t in closed if (t.pnl_rub or 0) > 0]
    losses = [t for t in closed if (t.pnl_rub or 0) < 0]
    gross_p = sum(t.pnl_rub for t in wins)
    gross_l = sum(t.pnl_rub for t in losses)
    net = sum(t.pnl_rub or 0 for t in closed)
    pf = (gross_p / abs(gross_l)) if gross_l != 0 else float("inf")
    exp = (net / len(closed)) if closed else 0.0
    best = max((t.pnl_rub or 0 for t in closed), default=0.0)
    worst = min((t.pnl_rub or 0 for t in closed), default=0.0)
    bars = [t.bars_held for t in closed if t.bars_held]
    avg_bars = sum(bars) / len(bars) if bars else 0.0

    exit_reasons: dict[str, int] = {}
    for t in closed:
        r = (t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason)) or "?"
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    max_hold_exits = exit_reasons.get("MAX_HOLD_EXIT", 0) + exit_reasons.get("TIMEOUT", 0)

    return {
        "name": name,
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "open_trades": len(open_n),
        "wins": len(wins),
        "losses": len(losses),
        "winrate_pct": round(100.0 * len(wins) / len(closed), 1) if closed else 0.0,
        "gross_profit_rub": round(gross_p, 2),
        "gross_loss_rub": round(gross_l, 2),
        "net_pnl_rub": round(net, 2),
        "profit_factor": round(pf, 3) if pf != float("inf") else "∞",
        "expectancy_rub": round(exp, 2),
        "best_trade_rub": round(best, 2),
        "worst_trade_rub": round(worst, 2),
        "avg_bars_held": round(avg_bars, 1),
        "max_hold_exits": max_hold_exits,
        "exit_reasons": exit_reasons,
    }


def _load(db_path: str) -> list:
    p = Path(db_path)
    if not p.exists():
        return []
    repo = PaperRepository(str(p))
    repo.init_db()
    return repo.list_recent_trades(limit=10000)


# ─────────────────────────────── report ─────────────────────────────────────

def _delta(a, b) -> str:
    if isinstance(a, str) or isinstance(b, str):
        return "n/a"
    d = b - a
    return f"{d:+.2f}" if isinstance(d, float) else f"{d:+}"


def build_compare_report(
    baseline: dict,
    experiment: dict,
    baseline_name: str,
    experiment_name: str,
    period_note: str = "",
) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = []

    lines.append(f"# Paper A/B Compare — {baseline_name} vs {experiment_name}")
    lines.append("")
    lines.append(f"_Сгенерировано: {ts}_")
    lines.append("")

    lines.append("## Period")
    lines.append("")
    if period_note:
        lines.append(period_note)
    else:
        lines.append("Период определяется по данным в БД (первая/последняя сделка).")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    rows = [
        ("total_trades", "Всего сделок"),
        ("closed_trades", "Закрытых"),
        ("open_trades", "Открытых"),
        ("wins", "Wins"),
        ("losses", "Losses"),
        ("winrate_pct", "Winrate %"),
        ("gross_profit_rub", "Gross profit, руб"),
        ("gross_loss_rub", "Gross loss, руб"),
        ("net_pnl_rub", "Net PnL, руб"),
        ("profit_factor", "Profit factor"),
        ("expectancy_rub", "Expectancy, руб"),
        ("best_trade_rub", "Best trade, руб"),
        ("worst_trade_rub", "Worst trade, руб"),
        ("avg_bars_held", "Avg bars held"),
        ("max_hold_exits", "MAX_HOLD_EXIT + TIMEOUT"),
    ]
    lines.append(f"| Метрика | {baseline_name} | {experiment_name} | Δ |")
    lines.append("|---|---:|---:|---:|")
    for key, label in rows:
        a = baseline.get(key, "—")
        b = experiment.get(key, "—")
        d = _delta(a, b)
        lines.append(f"| {label} | {a} | {b} | {d} |")
    lines.append("")

    lines.append("## Exit reason distribution")
    lines.append("")
    all_reasons = sorted(
        set(list(baseline.get("exit_reasons", {}).keys()) + list(experiment.get("exit_reasons", {}).keys()))
    )
    lines.append(f"| exit_reason | {baseline_name} | {experiment_name} |")
    lines.append("|---|---:|---:|")
    for r in all_reasons:
        a = baseline.get("exit_reasons", {}).get(r, 0)
        b = experiment.get("exit_reasons", {}).get(r, 0)
        lines.append(f"| {r} | {a} | {b} |")
    lines.append("")

    lines.append("## Service status")
    lines.append("")
    lines.append(f"- {baseline_name} DB: `data/paper/paper_state.sqlite`")
    lines.append(f"- {experiment_name} DB: `data/paper/paper_state_maxhold5.sqlite`")
    lines.append(
        "- Проверить: `sudo systemctl status hammertrade-paper hammertrade-paper-maxhold5 --no-pager`"
    )
    lines.append("")

    lines.append("## Notes / limitations")
    lines.append("")
    if baseline.get("closed_trades", 0) == 0 or experiment.get("closed_trades", 0) == 0:
        lines.append("- Одна из баз данных пустая или не содержит закрытых сделок.")
    if baseline.get("closed_trades", 0) < 20:
        lines.append(f"- {baseline_name}: мало сделок ({baseline.get('closed_trades', 0)}). LOW_SAMPLE.")
    if experiment.get("closed_trades", 0) < 20:
        lines.append(f"- {experiment_name}: мало сделок ({experiment.get('closed_trades', 0)}). LOW_SAMPLE.")
    lines.append("- Сравнение корректно только если оба сервиса работали одновременно.")
    lines.append("- Не является доказательством прибыльности стратегии.")
    lines.append("")

    return "\n".join(lines)


# ─────────────────────────────── CLI ─────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compare two parallel paper trading experiments")
    p.add_argument("--baseline-db", default="data/paper/paper_state.sqlite")
    p.add_argument("--experiment-db", default="data/paper/paper_state_maxhold5.sqlite")
    p.add_argument("--baseline-name", default="baseline")
    p.add_argument("--experiment-name", default="maxhold5")
    p.add_argument("--output", default="reports/paper_ab_compare_baseline_vs_maxhold5_latest.md")
    p.add_argument("--period-note", default="")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    baseline_trades = _load(args.baseline_db)
    experiment_trades = _load(args.experiment_db)

    baseline = _compute_metrics(baseline_trades, args.baseline_name)
    experiment = _compute_metrics(experiment_trades, args.experiment_name)

    report = build_compare_report(
        baseline=baseline,
        experiment=experiment,
        baseline_name=args.baseline_name,
        experiment_name=args.experiment_name,
        period_note=args.period_note,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    print(f"A/B Compare: {args.baseline_name} vs {args.experiment_name}")
    print(f"  {args.baseline_name}: {baseline['closed_trades']} closed, "
          f"net={baseline['net_pnl_rub']:+.0f} RUB, PF={baseline['profit_factor']}")
    print(f"  {args.experiment_name}: {experiment['closed_trades']} closed, "
          f"net={experiment['net_pnl_rub']:+.0f} RUB, PF={experiment['profit_factor']}")
    print(f"Report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
