"""Error summary report for paper trading daemons.

Reads status JSON files and prints a concise error/health summary.
"""
import argparse
import json
import sys
from pathlib import Path


_DEFAULT_STATUS_FILES = [
    "runtime/paper_status_SiM6_SELL.json",
    "runtime/paper_status_SiM6_SELL_maxhold5.json",
]


def _parse_args():
    p = argparse.ArgumentParser(
        description="Paper error report — reads status files and summarises error counters."
    )
    p.add_argument(
        "--status-files",
        nargs="+",
        default=_DEFAULT_STATUS_FILES,
        metavar="PATH",
        help="One or more status JSON file paths (default: baseline + maxhold5)",
    )
    p.add_argument("--json", action="store_true", help="Output raw JSON list")
    return p.parse_args()


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _fmt(v) -> str:
    return "—" if v is None else str(v)


def _report_one(path: Path) -> dict:
    status = _load(path)
    if status is None:
        return {"file": str(path), "available": False}
    return {
        "file": str(path),
        "available": True,
        "experiment": status.get("experiment_name") or path.stem,
        "ticker": status.get("ticker", "?"),
        "last_fetch_status": status.get("last_fetch_status", "?"),
        "last_cycle_at_utc": status.get("last_cycle_at_utc"),
        "last_successful_fetch_at": status.get("last_successful_fetch_at"),
        "empty_response_count": status.get("empty_response_count", 0),
        "consecutive_empty_responses": status.get("consecutive_empty_responses", 0),
        "last_empty_response_at": status.get("last_empty_response_at"),
        "consecutive_api_errors": status.get("consecutive_api_errors", 0),
        "consecutive_empty_fetches": status.get("consecutive_empty_fetches", 0),
        "last_error": status.get("last_error"),
        "open_trades": status.get("open_trades", 0),
        "pending_signal": status.get("pending_signal", False),
    }


def main() -> int:
    args = _parse_args()
    reports = [_report_one(Path(p)) for p in args.status_files]

    if args.json:
        print(json.dumps(reports, indent=2, default=str))
        return 0

    print("Paper Error Report")
    print("=" * 50)
    for r in reports:
        name = Path(r["file"]).name
        print(f"\n[{name}]")
        if not r["available"]:
            print("  status file not found")
            continue
        print(f"  last_fetch_status          : {_fmt(r['last_fetch_status'])}")
        print(f"  last_cycle_at_utc          : {_fmt(r['last_cycle_at_utc'])}")
        print(f"  last_successful_fetch_at   : {_fmt(r['last_successful_fetch_at'])}")
        print(f"  empty_response_count       : {r['empty_response_count']}")
        print(f"  consecutive_empty_responses: {r['consecutive_empty_responses']}")
        print(f"  last_empty_response_at     : {_fmt(r['last_empty_response_at'])}")
        print(f"  consecutive_api_errors     : {r['consecutive_api_errors']}")
        print(f"  consecutive_empty_fetches  : {r['consecutive_empty_fetches']}")
        if r["last_error"]:
            print(f"  last_error                 : {r['last_error']}")
        print(f"  open_trades                : {r['open_trades']}")
        print(f"  pending_signal             : {r['pending_signal']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
