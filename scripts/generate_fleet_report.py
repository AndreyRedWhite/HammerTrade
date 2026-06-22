"""Generate a unified daily/weekly fleet report across all paper/sandbox services.

Reads each live service's SQLite trade DB + status JSON, computes lifetime &
windowed metrics (trades, PnL, PF, WR, MaxDD, avg win/loss), classifies each
strategy (ACTIVE / WATCH / FREEZE / PROMOTE) and flags sandbox/live-capable
candidates. Writes a markdown report.

Usage:
    python scripts/generate_fleet_report.py --period daily
    python scripts/generate_fleet_report.py --period weekly --output reports/fleet_weekly.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.fleet import build_reports, render_markdown


def main() -> int:
    p = argparse.ArgumentParser(description="Unified fleet daily/weekly report")
    p.add_argument("--period", choices=["daily", "weekly"], default="daily")
    p.add_argument("--base-dir", default=".", help="App root (where data/ runtime/ live)")
    p.add_argument("--output", default=None, help="Markdown path (default reports/fleet_<period>_<ts>.md)")
    p.add_argument("--latest-symlink", action="store_true",
                   help="Also write reports/fleet_<period>_latest.md")
    p.add_argument("--print", dest="do_print", action="store_true", help="Print to stdout too")
    args = p.parse_args()

    base = Path(args.base_dir).resolve()
    now = datetime.now(tz=timezone.utc)
    window_days = 1 if args.period == "daily" else 7
    label = "Daily (last 24h)" if args.period == "daily" else "Weekly (last 7d)"

    reports = build_reports(base, now, window_days)
    md = render_markdown(reports, now, label, window_days)

    out_dir = base / "reports"
    out_dir.mkdir(exist_ok=True)
    ts = now.strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.output) if args.output else out_dir / f"fleet_{args.period}_{ts}.md"
    out_path.write_text(md, encoding="utf-8")
    if args.latest_symlink:
        (out_dir / f"fleet_{args.period}_latest.md").write_text(md, encoding="utf-8")

    print(f"Report written: {out_path}  ({len(reports)} services)")
    if args.do_print:
        print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
