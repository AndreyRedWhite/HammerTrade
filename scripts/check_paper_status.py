"""Health-check script for the paper trading daemon.

Reads the JSON status file written by run_paper_trader.py and outputs a
human-readable summary.  Exit codes:
  0 — trading liveness OK
  1 — trading liveness DEGRADED
  2 — trading liveness STALLED, status file missing/unreadable, or daemon stale
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


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


def _compute_liveness_fallback(status: dict) -> tuple[str, str | None]:
    """Compute liveness from raw fields when trading_liveness_status not present (old status files)."""
    from src.paper.liveness import compute_liveness
    return compute_liveness(
        is_market_open=status.get("market_open", True),
        consecutive_api_errors=status.get("consecutive_api_errors", 0),
        consecutive_empty_responses=status.get("consecutive_empty_responses", 0),
        last_successful_fetch_at=status.get("last_successful_fetch_at"),
    )


def main() -> int:
    args = _parse_args()
    path = Path(args.status_file)

    if not path.exists():
        print(f"MISSING  status file not found: {path}", file=sys.stderr)
        return 2

    try:
        status = _load_status(path)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR  cannot read status file: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(status, indent=2))
        return 0

    # --- Age check ---
    last_cycle = status.get("last_cycle_at_utc", "")
    age: float | None = None
    if last_cycle:
        try:
            age = _age_seconds(last_cycle)
        except ValueError:
            pass

    stale = age is not None and age > args.stale_threshold_sec

    # --- Liveness status ---
    if "trading_liveness_status" in status:
        liveness = status["trading_liveness_status"]
        liveness_reason = status.get("trading_liveness_reason")
    else:
        liveness, liveness_reason = _compute_liveness_fallback(status)

    if stale:
        # Stale daemon overrides to STALLED regardless
        liveness = "STALLED"
        liveness_reason = f"daemon_stale_{age:.0f}s"

    # --- Header line ---
    ticker = status.get("ticker", "?")
    direction = status.get("direction", "?")
    pid = _fmt(status.get("pid"))
    reason_str = f" ({liveness_reason})" if liveness_reason else ""
    print(f"[{liveness}]{reason_str}  {ticker} {direction}  pid={pid}")

    # --- Timing ---
    age_str = f"{age:.0f}s ago" if age is not None else "unknown"
    print(f"  last cycle : {_fmt(last_cycle)}  ({age_str})")
    print(f"  last candle: {_fmt(status.get('last_candle_ts_msk'))} (MSK)")

    # --- Market state ---
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

    # --- Liveness details ---
    last_ok_fetch = _fmt(status.get("last_successful_fetch_at"))
    minutes_since = status.get("minutes_since_last_successful_fetch")
    minutes_str = f"{minutes_since:.0f}m ago" if minutes_since is not None else "—"
    print(f"  liveness   : {liveness}  fetch={_fmt(status.get('last_fetch_status'))}")
    print(f"  last ok    : {last_ok_fetch}  ({minutes_str})")

    # --- Error counters ---
    consecutive_err = status.get("consecutive_api_errors", 0)
    total_err = status.get("total_api_errors", 0)
    empty_fetches = status.get("consecutive_empty_fetches", 0)
    if consecutive_err or total_err or empty_fetches:
        print(f"  api_errors : consecutive={consecutive_err}  total={total_err}  empty_fetches={empty_fetches}")
    last_err_at = status.get("last_api_error_at")
    if last_err_at:
        print(f"  last err @ : {last_err_at}")

    # --- Empty response counters ---
    empty_resp = status.get("consecutive_empty_responses", 0)
    empty_total = status.get("empty_response_count", 0)
    if empty_resp or empty_total:
        last_at = status.get("last_empty_response_at") or "—"
        print(f"  empty_resp : consecutive={empty_resp}  total={empty_total}  last={last_at}")

    # --- Trade state ---
    print(f"  open trades: {status.get('open_trades', 0)}")
    print(f"  pending sig: {status.get('pending_signal', False)}")

    # --- Last error message ---
    if status.get("last_error"):
        print(f"  last_error : {status['last_error']}")

    # --- Stale warning ---
    if stale:
        print(
            f"\n  WARNING: last cycle was {age:.0f}s ago "
            f"(threshold={args.stale_threshold_sec}s)",
            file=sys.stderr,
        )

    if liveness == "STALLED":
        return 2
    if liveness == "DEGRADED":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
