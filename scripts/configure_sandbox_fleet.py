"""Bind dedicated T-Bank sandbox accounts to HammerTrade fleet env keys.

This helper only works with ``SANDBOX_TOKEN`` and never submits orders. It can
reuse or create named sandbox accounts, then atomically updates ``.env``.
Strategy enable switches stay off unless ``--enable`` is passed explicitly.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


FLEET_ACCOUNTS = {
    "SANDBOX_ACCOUNT_ID_ORB_V2": "hammertrade-orb-v2",
    "SANDBOX_ACCOUNT_ID_VOLBREAK": "hammertrade-volbreak",
    "SANDBOX_ACCOUNT_ID_CARRY": "hammertrade-carry",
    "SANDBOX_ACCOUNT_ID_PAIRS_V2": "hammertrade-pairs-v2",
    "SANDBOX_ACCOUNT_ID_XSEC": "hammertrade-xsec",
}

FLEET_SWITCHES = (
    "SANDBOX_ORB_V2_ENABLED",
    "SANDBOX_VOLBREAK_ENABLED",
    "SANDBOX_CARRY_ENABLED",
    "SANDBOX_PAIRS_V2_ENABLED",
    "SANDBOX_XSEC_ENABLED",
)


def update_env_file(path: Path, updates: dict[str, str]) -> Path:
    """Atomically update selected dotenv keys and return the backup path."""
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = original.splitlines()
    seen: set[str] = set()
    rendered: list[str] = []

    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if key in updates and not stripped.startswith("#"):
            rendered.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            rendered.append(line)

    if rendered and rendered[-1] != "":
        rendered.append("")
    for key, value in updates.items():
        if key not in seen:
            rendered.append(f"{key}={value}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.backup_{stamp}")
    if path.exists():
        shutil.copy2(path, backup)

    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return backup


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create/reuse dedicated sandbox accounts and bind them to fleet env keys."
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--create-missing",
        action="store_true",
        help="Create a named sandbox account when it does not exist",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Set every fleet strategy enable switch to 1",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv(args.env_file)
    if not os.getenv("SANDBOX_TOKEN", ""):
        raise SystemExit("ERROR: SANDBOX_TOKEN is not set")
    if os.getenv("TINVEST_LIVE_TRADING_TOKEN", ""):
        raise SystemExit("ERROR: live trading token is present; refusing fleet configuration")

    from src.sandbox.broker import get_sandbox_broker

    resolved: dict[str, str] = {}
    created: list[str] = []
    with get_sandbox_broker() as broker:
        accounts = broker.get_accounts()
        by_name = {account.get("name"): account.get("id") for account in accounts}
        for env_key, account_name in FLEET_ACCOUNTS.items():
            account_id = by_name.get(account_name)
            if not account_id:
                if not args.create_missing:
                    raise SystemExit(
                        f"ERROR: sandbox account '{account_name}' is missing; "
                        "re-run with --create-missing"
                    )
                account_id = broker.open_account(name=account_name)
                created.append(account_name)
            resolved[env_key] = str(account_id)

    switch_value = "true" if args.enable else "false"
    updates = resolved | {key: switch_value for key in FLEET_SWITCHES}
    backup = update_env_file(args.env_file, updates)
    print(f"Configured {len(resolved)} dedicated sandbox accounts in {args.env_file}")
    print(f"Created accounts: {', '.join(created) if created else 'none'}")
    print(f"Strategy switches: {switch_value}")
    if backup.exists():
        print(f"Backup: {backup}")


if __name__ == "__main__":
    main()
