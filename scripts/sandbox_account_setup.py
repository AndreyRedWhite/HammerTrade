"""Sandbox account setup helper (MVP-L1a).

Connects to the T-Bank SANDBOX CONTOUR ONLY (SANDBOX_TOKEN) to list or create
a sandbox account and optionally top it up with virtual RUB. Places no
orders. Never prints, logs, or persists the token value — only the resulting
account id (which the operator then adds to .env as SANDBOX_ACCOUNT_ID).
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse_args():
    p = argparse.ArgumentParser(
        description=(
            "List/create a T-Bank sandbox account (sandbox contour only, "
            "SANDBOX_TOKEN). Never prints the token."
        )
    )
    p.add_argument(
        "--create-if-missing", action="store_true",
        help="Open a new sandbox account if none exists",
    )
    p.add_argument(
        "--account-name", default="hammertrade-sandbox",
        help="Name for a newly created sandbox account",
    )
    p.add_argument(
        "--dedicated", action="store_true",
        help="Select an account with --account-name or create it even when other accounts exist",
    )
    p.add_argument(
        "--top-up-rub", type=float, default=None,
        help="Top up the (existing or newly created) account with this RUB amount",
    )
    return p.parse_args()


def main():
    load_dotenv()
    args = _parse_args()

    if not os.getenv("SANDBOX_TOKEN", ""):
        print("ERROR: SANDBOX_TOKEN is not set. Add it to your .env file.", file=sys.stderr)
        sys.exit(1)

    from src.sandbox.broker import get_sandbox_broker

    with get_sandbox_broker() as broker:
        accounts = broker.get_accounts()

        named = next((a for a in accounts if a.get("name") == args.account_name), None)
        if args.dedicated and named:
            account_id = named["id"]
            print(f"Using dedicated sandbox account '{args.account_name}': {account_id}")
        elif args.dedicated:
            account_id = broker.open_account(name=args.account_name)
            print(f"Created dedicated sandbox account '{args.account_name}': {account_id}")
        elif accounts:
            account_id = accounts[0]["id"]
            print(f"Using existing sandbox account: {account_id}")
            if len(accounts) > 1:
                print(f"  (found {len(accounts)} accounts total; using the first one)")
            if args.create_if_missing:
                print("  --create-if-missing ignored: an account already exists.")
        elif args.create_if_missing:
            account_id = broker.open_account(name=args.account_name)
            print(f"Created new sandbox account: {account_id}")
        else:
            print(
                "No sandbox accounts found. Re-run with --create-if-missing to create one.",
                file=sys.stderr,
            )
            sys.exit(1)

        if args.top_up_rub is not None:
            balance = broker.pay_in(account_id, args.top_up_rub)
            if balance is not None:
                print(f"Topped up account {account_id} by {args.top_up_rub} RUB. New balance: {balance} RUB")
            else:
                print(f"Topped up account {account_id} by {args.top_up_rub} RUB.")

    print()
    print(f"SANDBOX_ACCOUNT_ID={account_id}")
    print("Add the line above to your .env file (do not commit .env).")


if __name__ == "__main__":
    main()
