"""List all paper candidates with decision, priority, and launch timing."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_CANDIDATES = [
    {
        "name": "hammer-maxhold5",
        "strategy": "Hammer Reversal (max_hold=5)",
        "decision": "CONTINUE",
        "priority": "RUNNING",
        "spec": "docs/hammer_decision_final_20260602.md",
        "timing": "Already running on SiM6 → roll to SiU6 ~2026-06-10",
        "blocker": None,
    },
    {
        "name": "orb-or60-short2r",
        "strategy": "Opening Range Breakout (10:00–11:00, SHORT, 2R)",
        "decision": "NEEDS_MORE_DATA",
        "priority": "RUNNING",
        "spec": "docs/paper_candidates/momentum_continuation_mc_atr2_vol2_r2.md",
        "timing": "Already running on SiM6 → roll to SiU6 ~2026-06-10",
        "blocker": None,
    },
    {
        "name": "momentum-mc-atr2-vol2-r2",
        "strategy": "Momentum Continuation (atr×2.0, vol×2.0, take_r=2.0)",
        "decision": "NEEDS_MORE_DATA",
        "priority": "1 — first after rollover",
        "spec": "docs/paper_candidates/momentum_continuation_mc_atr2_vol2_r2.md",
        "timing": "After SiU6 rollover + hammer/ORB stable >= 3 days",
        "blocker": "scripts/run_momentum_paper_trader.py not yet implemented",
    },
    {
        "name": "vwap-reversion-vr-d1-s1-1_5r",
        "strategy": "VWAP Reversion (distance=1.0×ATR, stop=1.0×ATR, take=1.5R)",
        "decision": "NEEDS_MORE_DATA",
        "priority": "2 — after Momentum >= 2 weeks",
        "spec": "docs/paper_candidates/vwap_reversion_vr_d1_s1_1_5r.md",
        "timing": "After Momentum paper >= 20 trades + dual-fill engine ready",
        "blocker": "Edge destroyed at 2pt slippage; needs dual-fill paper engine",
    },
    {
        "name": "opening-range-fade",
        "strategy": "Opening Range Fade (false breakout)",
        "decision": "REJECT",
        "priority": "NOT recommended",
        "spec": "reports/research_multistrategy_r2_latest.md",
        "timing": "N/A — OOS PF 0.68, regime-dependent failure",
        "blocker": "OOS performance disqualifies",
    },
]


def main() -> None:
    print("Paper Candidates — HammerTrade MOEXF")
    print("=" * 70)
    print()

    running = [c for c in _CANDIDATES if c["priority"] == "RUNNING"]
    candidates = [c for c in _CANDIDATES if c["priority"] not in ("RUNNING", "NOT recommended")]
    rejected = [c for c in _CANDIDATES if c["priority"] == "NOT recommended"]

    print("── RUNNING ─────────────────────────────────────────────────")
    for c in running:
        print(f"  [{c['decision']}] {c['name']}")
        print(f"    Strategy : {c['strategy']}")
        print(f"    Timing   : {c['timing']}")
        print()

    print("── QUEUED FOR PAPER (in priority order) ─────────────────────")
    for c in candidates:
        blocker_str = f"    Blocker  : {c['blocker']}" if c["blocker"] else ""
        print(f"  [{c['priority']}] {c['name']}")
        print(f"    Strategy : {c['strategy']}")
        print(f"    Decision : {c['decision']}")
        print(f"    Timing   : {c['timing']}")
        print(f"    Spec     : {c['spec']}")
        if blocker_str:
            print(blocker_str)
        print()

    print("── REJECTED ────────────────────────────────────────────────")
    for c in rejected:
        print(f"  [REJECT] {c['name']}")
        print(f"    Strategy : {c['strategy']}")
        print(f"    Reason   : {c['timing']}")
        print()

    print("=" * 70)
    print(f"Total: {len(running)} running, {len(candidates)} queued, {len(rejected)} rejected")


if __name__ == "__main__":
    main()
