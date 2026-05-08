"""CLI: generate paper trading diagnostics report."""
import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.diagnostics import (
    _ENRICHED_COLUMNS,
    build_markdown_report,
    run_diagnostics,
)


def _ts_suffix() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")


def main() -> None:
    p = argparse.ArgumentParser(description="HammerTrade Paper Diagnostics")
    p.add_argument("--state-db", default="data/paper/paper_state.sqlite")
    p.add_argument("--csv-fallback", default="out/paper/paper_trades_SiM6_SELL.csv")
    p.add_argument("--ticker", default="SiM6")
    p.add_argument("--direction", default="SELL")
    p.add_argument("--from", dest="from_date", default=None, metavar="YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", default=None, metavar="YYYY-MM-DD")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--out-dir", default="out/paper")
    args = p.parse_args()

    result = run_diagnostics(
        db_path=args.state_db,
        csv_fallback=args.csv_fallback,
        ticker=args.ticker,
        direction=args.direction,
        from_date=args.from_date,
        to_date=args.to_date,
    )

    ts = _ts_suffix()
    slug = f"{args.ticker}_{args.direction}"

    reports_dir = Path(args.reports_dir)
    out_dir = Path(args.out_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / f"paper_trades_diagnostics_{slug}_{ts}.csv"
    csv_latest = out_dir / f"paper_trades_diagnostics_{slug}_latest.csv"
    md_path = reports_dir / f"paper_diagnostics_{slug}_{ts}.md"
    md_latest = reports_dir / f"paper_diagnostics_{slug}_latest.md"

    # Write enriched CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_ENRICHED_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result.enriched)
    # Write latest copy
    with open(csv_latest, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_ENRICHED_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result.enriched)

    # Write Markdown report
    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    md_content = build_markdown_report(
        enriched=result.enriched,
        summary=result.summary,
        groups=result.groups,
        hypotheses=result.hypotheses,
        warnings=result.warnings,
        source_label=result.source_label,
        ticker=args.ticker,
        direction=args.direction,
        generated_at=generated_at,
    )
    md_path.write_text(md_content, encoding="utf-8")
    md_latest.write_text(md_content, encoding="utf-8")

    # CLI summary
    s = result.summary
    total = s["total_trades"]
    closed = s["closed_trades"]
    open_n = s["open_trades"]
    n_warnings = len(result.warnings)

    print("HammerTrade Paper Diagnostics")
    print(f"Source       : {result.source_label or '(none)'}")
    print(f"Ticker       : {args.ticker}")
    print(f"Direction    : {args.direction}")
    print(f"Loaded trades: {total}")
    print(f"Closed trades: {closed}")
    print(f"Open trades  : {open_n}")
    print(f"Enriched CSV : {csv_path}")
    print(f"Report       : {md_path}")
    print(f"Warnings     : {n_warnings}")

    if result.warnings:
        print()
        for w in result.warnings:
            print(f"  WARN: {w}")


if __name__ == "__main__":
    main()
