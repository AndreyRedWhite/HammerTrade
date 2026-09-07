"""CLI: MVP-2.3 Hour filter targeted audit."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analytics.hour_filter_audit import (
    build_csv_rows,
    build_markdown_report,
    load_historical_trades,
    load_paper_trades,
    run_audit,
    write_csv,
)


def _parse_args():
    p = argparse.ArgumentParser(description="HammerTrade Hour Filter Targeted Audit (MVP-2.3)")
    p.add_argument("--hour", type=int, default=12, help="MSK hour to audit (default: 12)")
    p.add_argument("--timezone", default="Europe/Moscow", help="Local timezone (default: Europe/Moscow)")
    p.add_argument("--baseline-db", default="data/paper/paper_state.sqlite",
                   help="Paper baseline SQLite path")
    p.add_argument("--maxhold-db", default="data/paper/paper_state_maxhold5.sqlite",
                   help="Paper maxhold5 SQLite path")
    p.add_argument("--backtest-trades",
                   default="out/backtest_exit_time_filters_v2_trades_SiM6_SELL_latest.csv",
                   help="Historical backtest trades CSV (baseline scenario)")
    p.add_argument("--backtest-summary",
                   default="out/backtest_exit_time_filters_v2_SiM6_SELL_latest.csv",
                   help="Historical backtest summary CSV (not used in audit, for reference)")
    p.add_argument("--ticker", default="SiM6")
    p.add_argument("--direction", default="SELL")
    p.add_argument("--output",
                   default="reports/hour_filter_audit_hour12_SiM6_SELL_latest.md",
                   help="Markdown output path")
    p.add_argument("--out-dir", default="out", help="Directory for CSV output")
    p.add_argument("--reports-dir", default="reports")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    tz = ZoneInfo(args.timezone)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = f"hour{args.hour:02d}_SiM6_{args.direction}"

    print(f"Hour Filter Audit — hour {args.hour} MSK")
    print(f"Timezone : {args.timezone}")
    print(f"Ticker   : {args.ticker} {args.direction}")
    print()

    # ── Load data ──────────────────────────────────────────────────────────────
    hist_trades = []
    if Path(args.backtest_trades).exists():
        hist_trades = load_historical_trades(args.backtest_trades, scenario="baseline", tz=tz)
        print(f"Historical trades loaded: {len(hist_trades)}")
    else:
        print(f"WARNING: backtest trades not found: {args.backtest_trades}")

    baseline_trades = []
    if Path(args.baseline_db).exists():
        baseline_trades = load_paper_trades(args.baseline_db, args.ticker, args.direction)
        print(f"Live baseline trades loaded: {len(baseline_trades)}")
    else:
        print(f"WARNING: baseline DB not found: {args.baseline_db}")

    maxhold_trades = []
    if Path(args.maxhold_db).exists():
        maxhold_trades = load_paper_trades(args.maxhold_db, args.ticker, args.direction)
        print(f"Live maxhold5 trades loaded: {len(maxhold_trades)}")
    else:
        print(f"WARNING: maxhold5 DB not found: {args.maxhold_db}")

    print()

    # ── Run audit ──────────────────────────────────────────────────────────────
    result = run_audit(
        audit_hour=args.hour,
        historical_trades=hist_trades,
        paper_baseline=baseline_trades,
        paper_maxhold5=maxhold_trades,
        tz=tz,
    )

    # ── Write outputs ──────────────────────────────────────────────────────────
    reports_dir = Path(args.reports_dir)
    out_dir = Path(args.out_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    md = build_markdown_report(result, generated_at=generated_at)
    csv_rows = build_csv_rows(result)

    # Timestamped
    md_ts = reports_dir / f"hour_filter_audit_{slug}_{ts}.md"
    csv_ts = out_dir / f"hour_filter_audit_{slug}_{ts}.csv"
    md_ts.write_text(md, encoding="utf-8")
    write_csv(csv_rows, csv_ts)

    # Latest
    md_latest = Path(args.output)
    md_latest.parent.mkdir(parents=True, exist_ok=True)
    md_latest.write_text(md, encoding="utf-8")
    csv_latest = out_dir / f"hour_filter_audit_{slug}_latest.csv"
    write_csv(csv_rows, csv_latest)

    # ── Summary to stdout ──────────────────────────────────────────────────────
    print("=" * 55)
    print(f"AUDIT HOUR {args.hour} MSK — RESULTS")
    print("=" * 55)

    def _print_stats(label: str, s) -> None:
        import math
        pf = "inf" if math.isinf(s.profit_factor) else f"{s.profit_factor:.3f}"
        ls = " [LOW_SAMPLE]" if s.low_sample else ""
        print(f"  {label:30s}  trades={s.trades:3d}  WR={s.winrate:5.1f}%  "
              f"net={s.net_pnl:+8.2f} RUB  PF={pf}{ls}")

    if result.historical:
        print("\n--- Historical ---")
        _print_stats("All hours", result.historical.all_hours)
        _print_stats(f"Hour {args.hour} only", result.historical.audit_hour)
        _print_stats(f"Without hour {args.hour}", result.historical.without_audit_hour)

    if result.live_baseline:
        print("\n--- Live baseline ---")
        _print_stats("All hours", result.live_baseline.all_hours)
        _print_stats(f"Hour {args.hour} only", result.live_baseline.audit_hour)
        _print_stats(f"Without hour {args.hour}", result.live_baseline.without_audit_hour)

    if result.live_maxhold5:
        print("\n--- Live maxhold5 ---")
        _print_stats("All hours", result.live_maxhold5.all_hours)
        _print_stats(f"Hour {args.hour} only", result.live_maxhold5.audit_hour)
        _print_stats(f"Without hour {args.hour}", result.live_maxhold5.without_audit_hour)

    print()
    print(f"Overfit risk      : {result.overfit_risk}")
    print(f"Candidate decision: {result.candidate_decision}")
    print(f"Recommendation    : {result.recommendation}")
    print()
    print(f"Report : {md_ts}")
    print(f"Latest : {md_latest}")
    print(f"CSV    : {csv_ts}")


if __name__ == "__main__":
    main()
