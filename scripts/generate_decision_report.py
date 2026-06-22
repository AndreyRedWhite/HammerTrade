"""Per-strategy research-funnel decision report.

For every live strategy: current stage, verdict (ADVANCE / HOLD /
INSUFFICIENT_DATA / LOW_ACTIVITY / FREEZE / KILL), the gate criteria with
pass/fail, and a rationale. See docs/research_funnel.md.

Usage:
    python scripts/generate_decision_report.py
    python scripts/generate_decision_report.py --output reports/decisions.md --print
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.fleet import build_reports
from src.reporting.funnel import (
    V_ADVANCE, V_FREEZE, V_HOLD, V_INSUFFICIENT, V_KILL, V_LOW_ACTIVITY,
    FunnelConfig, decide,
)

_ORDER = [V_ADVANCE, V_FREEZE, V_KILL, V_LOW_ACTIVITY, V_HOLD, V_INSUFFICIENT]
_EMOJI = {V_ADVANCE: "⬆️", V_FREEZE: "❄️", V_KILL: "🛑",
          V_LOW_ACTIVITY: "🐌", V_HOLD: "⏸️", V_INSUFFICIENT: "⏳"}


def main() -> int:
    p = argparse.ArgumentParser(description="Research-funnel decision report")
    p.add_argument("--base-dir", default=".")
    p.add_argument("--output", default=None)
    p.add_argument("--latest-symlink", action="store_true")
    p.add_argument("--print", dest="do_print", action="store_true")
    args = p.parse_args()

    base = Path(args.base_dir).resolve()
    now = datetime.now(tz=timezone.utc)
    cfg = FunnelConfig()
    reports = build_reports(base, now, 7)
    decisions = [(r, decide(r, cfg, now)) for r in reports]

    counts: dict[str, int] = {}
    for _, d in decisions:
        counts[d.verdict] = counts.get(d.verdict, 0) + 1

    L = [
        "# Research Funnel — Decision Report",
        f"*Generated {now.strftime('%Y-%m-%d %H:%M UTC')} · {len(decisions)} strategies · "
        "see docs/research_funnel.md*",
        "",
        "**Verdicts:** " + " · ".join(
            f"{_EMOJI.get(v,'')} {v}={counts.get(v,0)}" for v in _ORDER if counts.get(v)),
        "",
    ]

    # action items first
    actions = [(r, d) for r, d in decisions if d.verdict in (V_ADVANCE, V_FREEZE, V_KILL, V_LOW_ACTIVITY)]
    L.append("## Action items")
    if actions:
        for r, d in sorted(actions, key=lambda x: _ORDER.index(x[1].verdict)):
            unit = r.svc.unit.replace("hammertrade-", "").replace(".service", "")
            L.append(f"- {_EMOJI.get(d.verdict,'')} **{d.verdict}** — `{unit}` "
                     f"({r.svc.family} {r.svc.instrument} {r.svc.direction}) → {d.rationale}")
    else:
        L.append("- none — nothing to advance/freeze/kill right now.")
    L.append("")

    # per-strategy detail
    L.append("## Per-strategy detail")
    for r, d in sorted(decisions, key=lambda x: (_ORDER.index(x[1].verdict), x[0].svc.unit)):
        unit = r.svc.unit.replace("hammertrade-", "").replace(".service", "")
        L.append(f"### {_EMOJI.get(d.verdict,'')} {unit} — {d.verdict}")
        L.append(f"*stage: {d.stage} → {d.advance_to}*")
        L.append(f"*{r.svc.family} · {r.svc.instrument} · {r.svc.direction or '—'} · "
                 f"lifetime {r.lifetime.trades} tr · PnL {r.lifetime.pnl_rub:+.0f}₽*")
        L.append("")
        L.append("| criterion | value | target | ok |")
        L.append("|---|---|---|---|")
        for c in d.criteria:
            L.append(f"| {c.name} | {c.actual} | {c.target} | {'✅' if c.ok else '❌'} |")
        L.append("")
        L.append(f"➡️ {d.rationale}")
        L.append("")

    md = "\n".join(L)
    out_dir = base / "reports"
    out_dir.mkdir(exist_ok=True)
    ts = now.strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.output) if args.output else out_dir / f"decisions_{ts}.md"
    out_path.write_text(md, encoding="utf-8")
    if args.latest_symlink:
        (out_dir / "decisions_latest.md").write_text(md, encoding="utf-8")

    print(f"Decision report written: {out_path}  ({len(decisions)} strategies)")
    if args.do_print:
        print("\n" + md)
    return 0


if __name__ == "__main__":
    main()
