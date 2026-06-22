"""Portfolio / exposure report — how the strategies work together.

Combined PnL & equity curve, portfolio vol/Sharpe/drawdown, exposure by
instrument/direction/asset-class, overload flags, strategy correlations, and
each strategy's contribution to total return and total (correlation-aware) risk.

Usage:
    python scripts/generate_portfolio_report.py --print
    python scripts/generate_portfolio_report.py --output reports/portfolio.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.fleet import build_reports
from src.reporting.portfolio import analyze


def _f(v):
    return f"{v:+,.0f}" if isinstance(v, (int, float)) else str(v)


def main() -> int:
    p = argparse.ArgumentParser(description="Portfolio / exposure report")
    p.add_argument("--base-dir", default=".")
    p.add_argument("--output", default=None)
    p.add_argument("--latest-symlink", action="store_true")
    p.add_argument("--print", dest="do_print", action="store_true")
    args = p.parse_args()

    base = Path(args.base_dir).resolve()
    now = datetime.now(tz=timezone.utc)
    reports = build_reports(base, now, 7)
    pr = analyze(reports)

    L = [
        "# Portfolio / Exposure Report",
        f"*Generated {now.strftime('%Y-%m-%d %H:%M UTC')} · common unit = realized RUB · "
        "daily PnL by MSK date*",
        "",
        "## Portfolio summary",
        f"- Strategies with trades: **{pr.n_strategies}** over **{pr.n_dates}** trading days",
        f"- Combined PnL: **{_f(pr.total_pnl)}₽**",
        f"- Daily PnL: mean {_f(pr.daily_mean)}₽, vol {pr.daily_vol:,.0f}₽"
        + (f", annualized Sharpe ≈ **{pr.sharpe_annual}**" if pr.sharpe_annual is not None else ""),
        f"- Portfolio max drawdown: {pr.max_dd:,.0f}₽",
        "",
    ]

    if pr.overload_flags:
        L.append("## ⚠️ Overload / concentration flags")
        for f in pr.overload_flags:
            L.append(f"- {f}")
        L.append("")
    else:
        L.append("## Concentration: no overload flags\n")

    # exposures
    def _exp_table(title, g, keyname):
        rows = [f"| {keyname} | #strat | PnL ₽ | risk % |", "|---|---|---|---|"]
        for k, e in g.items():
            rows.append(f"| {k} | {e['n']} | {_f(e['pnl'])} | {e['risk_pct']:.0f} |")
        return f"### {title}\n" + "\n".join(rows) + "\n"

    L.append("## Exposure")
    L.append(_exp_table("By asset class / market", pr.by_asset_class, "market"))
    L.append(_exp_table("By direction", pr.by_direction, "direction"))
    L.append(_exp_table("By instrument", pr.by_instrument, "instrument"))

    # correlations
    L.append("## Strategy correlations (daily PnL, |corr| ≥ 0.5)")
    if pr.corr_pairs:
        L.append("| strategy A | strategy B | corr | note |")
        L.append("|---|---|---|---|")
        for a, b, c in pr.corr_pairs:
            note = "redundant (move together)" if c > 0 else "diversifying (offset)"
            L.append(f"| {a} | {b} | {c:+.2f} | {note} |")
    else:
        L.append("*No strategy pairs above the threshold yet (need ≥4 trade-days each "
                 "and overlapping activity).*")
    L.append("")

    # contributions
    L.append("## Contribution to return & risk")
    L.append("*risk % = share of portfolio variance (correlation-aware); '—' = too few "
             "trade-days to include.*")
    L.append("| strategy | instr | dir | market | trade-days | PnL ₽ | return % | risk % |")
    L.append("|---|---|---|---|---|---|---|---|")
    for c in pr.contributions:
        L.append(f"| {c.unit} | {c.instrument} | {c.direction} | {c.asset_class} | "
                 f"{c.trade_days} | {_f(c.total_pnl)} | {c.return_pct:.0f} | "
                 f"{c.risk_pct if c.risk_pct is not None else '—'} |")
    L.append("")
    if pr.excluded_low_data:
        L.append(f"*Excluded from corr/risk (low data): {', '.join(pr.excluded_low_data)}*")
        L.append("")

    md = "\n".join(L)
    out_dir = base / "reports"
    out_dir.mkdir(exist_ok=True)
    ts = now.strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.output) if args.output else out_dir / f"portfolio_{ts}.md"
    out_path.write_text(md, encoding="utf-8")
    if args.latest_symlink:
        (out_dir / "portfolio_latest.md").write_text(md, encoding="utf-8")

    print(f"Portfolio report written: {out_path}")
    if args.do_print:
        print("\n" + md)
    return 0


if __name__ == "__main__":
    main()
