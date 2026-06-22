"""Serve the read-only fleet dashboard via waitress (production WSGI).

Binds 127.0.0.1 by default — public exposure + TLS is handled by nginx.
Requires DASHBOARD_USER / DASHBOARD_PASS in the environment (fail-closed).

Usage:
    python scripts/run_dashboard.py --host 127.0.0.1 --port 8787
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description="HammerTrade read-only fleet dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    args = p.parse_args()

    if not os.environ.get("DASHBOARD_USER") or not os.environ.get("DASHBOARD_PASS"):
        print("ERROR: DASHBOARD_USER and DASHBOARD_PASS must be set (fail-closed).",
              file=sys.stderr)
        return 1

    from waitress import serve
    from src.dashboard.app import create_app

    app = create_app()
    print(f"Dashboard serving on http://{args.host}:{args.port} (read-only, basic auth)")
    serve(app, host=args.host, port=args.port, threads=4, ident="hammertrade-dashboard")
    return 0


if __name__ == "__main__":
    sys.exit(main())
