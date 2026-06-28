"""Combined fleet status check for ALL paper/sandbox trading services.

Two sections:
  A. systemd units  — source of truth for "is it running" (active + restarts).
     Auto-discovers every hammertrade-*.service. Skipped if systemctl absent.
  B. strategy status — auto-discovers runtime/paper_status_*.json (+ sandbox),
     parses health across all engine schemas (hammer / ORB / ORF / VWAP /
     momentum / pairs / sandbox). Archived (*_ARCHIVED_*) files are skipped;
     very stale files (no live service, e.g. rolled-over SiM6) are bucketed
     separately as leftovers rather than flagged degraded.

Exit code 1 if any systemd unit is not active OR any LIVE status is degraded/stale.

Usage:
    python scripts/check_all_paper_status.py
    python scripts/check_all_paper_status.py --no-systemd   # JSON section only
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fleet status for all paper/sandbox services")
    p.add_argument("--runtime-dir", default="runtime")
    # default > slowest poll interval (pairs basket polls every 300s)
    p.add_argument("--stale-threshold-sec", type=int, default=600)
    # files staler than this have no live service behind them (leftovers)
    p.add_argument("--leftover-threshold-sec", type=int, default=21600)  # 6h
    p.add_argument("--no-systemd", action="store_true",
                   help="Skip the systemd unit section (e.g. when run off-server)")
    return p.parse_args()


# ── helpers ───────────────────────────────────────────────────────────────────

def _load(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _first(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _age_str(ts_str: str | None, now: datetime) -> tuple[str, float | None]:
    if not ts_str:
        return "never", None
    try:
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
    except ValueError:
        return "?", None
    secs = (now - ts).total_seconds()
    if secs < 60:
        return f"{secs:.0f}s ago", secs
    if secs < 3600:
        return f"{secs/60:.0f}m ago", secs
    return f"{secs/3600:.1f}h ago", secs


# Trading halts (sandbox). A halt that nobody notices = a silently dead
# service (e.g. the consecutive-loss pause that kept the sandbox offline for
# days). Daily-scoped pauses now self-heal each trading day, so any halt seen
# here is either a hard halt awaiting manual review or a reset that failed to
# fire — both worth flagging loudly.
_HALT_STATES = {
    "KILL_SWITCH_ACTIVE": "KILLED",
    "RECONCILIATION_FAILED": "RECON_FAIL",
    "TRADING_PAUSED": "PAUSED",
}


def _health(status: dict, age_sec: float | None, stale_sec: int) -> str:
    """Normalize health across schemas → OK / PAUSED / DEGRADED / STALLED / <fetch_status>."""
    market_open = status.get("market_open", True)
    fetch = _first(status, "fetch_status", "last_fetch_status", default="")
    halt = _HALT_STATES.get(status.get("trading_state", ""))
    if halt:
        return halt
    live = status.get("trading_liveness_status")
    if live and live != "OK":
        return live
    if market_open and fetch in ("API_ERROR", "API_TIMEOUT", "NO_CANDLES"):
        return fetch
    if market_open and age_sec is not None and age_sec > stale_sec:
        return "STALE"
    return "OK"


def _summarize(status: dict, now: datetime, stale_sec: int) -> dict:
    label = _first(status, "ticker", "pairs", default="?")
    strat = _first(status, "strategy", "service", default="")
    direction = _first(status, "direction", default="")
    fetch_ts = _first(status, "last_successful_fetch_at", "updated_at",
                      "last_cycle_at_utc")
    age, age_sec = _age_str(fetch_ts, now)
    closed = _first(status, "closed_trades_total", "closed_trades", default="")
    open_n = _first(status, "open_trades_total", "open_trades", default="")
    if open_n == "" and status.get("open_trade") is not None:
        open_n = 1
    pnl = _first(status, "net_pnl_total", "net_pnl_theoretical_rub",
                 "net_pnl_rub", default="")
    return {
        "label": str(label)[:26],
        "strat": str(strat)[:10],
        "dir": str(direction),
        "market_open": status.get("market_open", True),
        "health": _health(status, age_sec, stale_sec),
        "fetch_age": age,
        "age_sec": age_sec,
        "closed": closed,
        "open": open_n,
        "pnl": pnl,
        "pause_reason": status.get("trading_paused_reason"),
    }


# ── section A: systemd ────────────────────────────────────────────────────────

def _systemd_units() -> list[tuple[str, str, str]] | None:
    """Returns [(unit, active_state, restarts)] for hammertrade-*.service, or None."""
    try:
        out = subprocess.run(
            ["systemctl", "list-units", "hammertrade-*.service",
             "--type=service", "--all", "--no-legend", "--no-pager"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    units = []
    for line in out.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0].lstrip("●").strip()
        if not unit.endswith(".service"):
            continue
        # query each property separately — systemctl --value with multiple -p
        # does NOT preserve request order, which silently swaps fields.
        try:
            active = subprocess.run(["systemctl", "is-active", unit],
                                    capture_output=True, text=True, timeout=10).stdout.strip() or "?"
        except subprocess.SubprocessError:
            active = "?"
        try:
            restarts = subprocess.run(["systemctl", "show", unit, "-p", "NRestarts", "--value"],
                                      capture_output=True, text=True, timeout=10).stdout.strip() or "?"
        except subprocess.SubprocessError:
            restarts = "?"
        try:
            props = subprocess.run(["systemctl", "show", unit, "-p", "Type", "-p", "Result"],
                                   capture_output=True, text=True, timeout=10).stdout
            stype = next((l.split("=", 1)[1] for l in props.splitlines() if l.startswith("Type=")), "?")
            result = next((l.split("=", 1)[1] for l in props.splitlines() if l.startswith("Result=")), "?")
        except subprocess.SubprocessError:
            stype, result = "?", "?"
        units.append((unit, active, restarts, stype, result))
    return sorted(units)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    args = _parse_args()
    now = datetime.now(tz=timezone.utc)
    exit_code = 0

    print(f"\nFleet status: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # A. systemd
    if not args.no_systemd:
        units = _systemd_units()
        if units is None:
            print("\n[systemd] unavailable (systemctl not found) — skipping unit section")
        else:
            longrun = [u for u in units if u[3] != "oneshot"]
            oneshots = [u for u in units if u[3] == "oneshot"]
            active_n = sum(1 for u in longrun if u[1] == "active")
            print(f"\n[systemd units]  {active_n}/{len(longrun)} long-running active"
                  + (f" · {len(oneshots)} oneshot (timer-driven)" if oneshots else ""))
            print("-" * 70)
            for unit, active, restarts, stype, result in longrun:
                flag = "" if active == "active" else "  <-- NOT ACTIVE"
                if active != "active":
                    exit_code = 1
                short = unit.replace("hammertrade-", "").replace(".service", "")
                print(f"  {short:46s} {active:10s} restarts={restarts}{flag}")
            for unit, active, restarts, stype, result in oneshots:
                # oneshot services are inactive between timer firings — normal.
                # Only a failed last run is a problem.
                flag = "" if result in ("success", "") else f"  <-- last run {result}"
                if result not in ("success", ""):
                    exit_code = 1
                short = unit.replace("hammertrade-", "").replace(".service", "")
                print(f"  {short:46s} oneshot    last={result or 'n/a'}{flag}")

    # B. status JSONs
    rt = Path(args.runtime_dir)
    files = sorted(rt.glob("paper_status_*.json")) + sorted(rt.glob("sandbox_status_*.json"))
    files = [f for f in files if "ARCHIVED" not in f.name]

    rows, leftovers = [], []
    for f in files:
        status = _load(f)
        name = f.name.replace("paper_status_", "").replace("sandbox_status_", "").replace(".json", "")
        if status is None:
            rows.append((name, None))
            exit_code = 1
            continue
        s = _summarize(status, now, args.stale_threshold_sec)
        if s["age_sec"] is not None and s["age_sec"] > args.leftover_threshold_sec:
            leftovers.append((name, s))
        else:
            rows.append((name, s))

    print(f"\n[strategy status]  {len(rows)} live status files"
          + (f"  (+{len(leftovers)} stale leftovers ignored)" if leftovers else ""))
    print("=" * 104)
    print(f"{'service':<30}{'instr':<20}{'strat':<11}{'dir':<6}"
          f"{'health':<10}{'fetch':<10}{'cl':>4}{'op':>4}{'  pnl_rub':>12}")
    print("=" * 104)

    degraded = []
    for name, s in rows:
        if s is None:
            print(f"{name:<30}{'READ_ERROR':<20}")
            continue
        if s["health"] != "OK":
            exit_code = 1
            reason = s.get("pause_reason")
            label = s["health"] + (f" ({reason})" if reason and s["health"] == "PAUSED" else "")
            degraded.append((name, label))
        pnl_str = f"{s['pnl']:.0f}" if isinstance(s["pnl"], (int, float)) else str(s["pnl"])
        mkt = "" if s["market_open"] else " (mkt closed)"
        print(f"{name:<30}{s['label']:<20}{s['strat']:<11}{s['dir']:<6}"
              f"{s['health']:<10}{s['fetch_age']:<10}{str(s['closed']):>4}{str(s['open']):>4}"
              f"{pnl_str:>12}{mkt}")
    print("=" * 104)

    if degraded:
        print("\nDegraded LIVE services:")
        for name, health in degraded:
            print(f"  [{name}] {health}")
    else:
        print("\nAll live status files OK.")

    if leftovers:
        print(f"\nStale leftovers (>{args.leftover_threshold_sec//3600}h old, "
              f"no live service — e.g. rolled-over): "
              + ", ".join(n for n, _ in leftovers))

    print()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
