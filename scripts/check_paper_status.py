"""Health-check script for the paper trading daemon.

Reads the JSON status file written by run_paper_trader.py and outputs a
human-readable summary.  Exit codes:
  0 — daemon is alive and healthy
  1 — status file missing or unreadable (daemon never started or crashed)
  2 — daemon appears stale (no update in > --stale-threshold-sec seconds)
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _parse_args():
    p = argparse.ArgumentParser(
        description="Check paper trading daemon health via status file."
    )
    p.add_argument(
        "--status-file",
        default="runtime/paper_status.json",
        help="Path to the JSON status file (default: runtime/paper_status.json)",
    )
    p.add_argument(
        "--stale-threshold-sec",
        type=int,
        default=120,
        help="Seconds since last cycle before daemon is considered stale (default: 120)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output raw status JSON instead of human-readable text",
    )
    return p.parse_args()


def _load_status(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _age_seconds(last_cycle_at_utc: str) -> float:
    ts = datetime.fromisoformat(last_cycle_at_utc.replace("Z", "+00:00"))
    return (datetime.now(tz=timezone.utc) - ts).total_seconds()


def _fmt(value) -> str:
    if value is None:
        return "—"
    return str(value)


def main() -> int:
    args = _parse_args()
    path = Path(args.status_file)

    if not path.exists():
        print(f"MISSING  status file not found: {path}", file=sys.stderr)
        return 1

    try:
        status = _load_status(path)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR  cannot read status file: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(status, indent=2))
        return 0

    last_cycle = status.get("last_cycle_at_utc", "")
    age: float | None = None
    if last_cycle:
        try:
            age = _age_seconds(last_cycle)
        except ValueError:
            pass

    stale = age is not None and age > args.stale_threshold_sec

    # --- header line ---
    state_label = "STALE" if stale else "OK"
    if status.get("last_error"):
        state_label = "WARN" if not stale else "STALE+ERR"

    ticker = status.get("ticker", "?")
    direction = status.get("direction", "?")
    print(f"[{state_label}]  {ticker} {direction}  pid={_fmt(status.get('pid'))}")

    # --- timing ---
    age_str = f"{age:.0f}s ago" if age is not None else "unknown"
    print(f"  last cycle : {_fmt(last_cycle)}  ({age_str})")
    print(f"  last candle: {_fmt(status.get('last_candle_ts_msk'))} (MSK)")

    # --- market state ---
    market_open = status.get("market_open")
    session = status.get("session", "?")
    mh_enabled = status.get("market_hours_enabled", True)
    if not mh_enabled:
        market_label = "ignored (--ignore-market-hours)"
    elif market_open:
        market_label = f"OPEN  session={session}"
    else:
        market_label = f"CLOSED  session={session}"
    print(f"  market     : {market_label}")

    # --- fetch status ---
    print(f"  fetch      : {_fmt(status.get('last_fetch_status'))}")
    empty = status.get("consecutive_empty_fetches", 0)
    errors = status.get("consecutive_api_errors", 0)
    if empty or errors:
        print(f"  counters   : empty_fetches={empty}  api_errors={errors}")

    # --- trade state ---
    print(f"  open trades: {status.get('open_trades', 0)}")
    print(f"  pending sig: {status.get('pending_signal', False)}")

    # --- error ---
    if status.get("last_error"):
        print(f"  last_error : {status['last_error']}")

    if stale:
        print(
            f"\n  WARNING: last cycle was {age:.0f}s ago "
            f"(threshold={args.stale_threshold_sec}s)",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
