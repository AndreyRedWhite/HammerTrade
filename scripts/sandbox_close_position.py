#!/usr/bin/env python3
"""Safe, single-shot manual close of an open sandbox futures position.

Context: the hammer-maxhold5 sandbox service opened a SiU6 short on
2026-06-16 but could not place the closing BUY ("30034 Not enough balance"),
leaving the position stuck OPEN. This tool closes that position by hand,
outside the daemon, with no retry loop.

SAFETY
------
- Sandbox contour ONLY. Uses SANDBOX_TOKEN via load_tbank_settings(env="sandbox")
  / SandboxBroker -> client.sandbox.post_sandbox_order. There is no code path to
  the prod/live order endpoints here.
- Hard-fails if TINVEST_LIVE_TRADING_TOKEN is set in the environment.
- DRY-RUN by default: prints the intended order and exits. Only --execute
  actually submits an order.
- Closes exactly the live account position (qty read from the sandbox account,
  not from our DB). Never increases exposure: it always submits the opposite
  side for abs(net qty) lots.
- Does NOT touch the sandbox DB. Reconciling our SQLite journal to FLAT is a
  separate, explicit step after a confirmed flat account.

Usage
-----
    python scripts/sandbox_close_position.py --ticker SiU6              # dry-run
    python scripts/sandbox_close_position.py --ticker SiU6 --execute    # MARKET close
    python scripts/sandbox_close_position.py --ticker SiU6 --execute --limit-offset 50
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sandbox.broker import get_sandbox_broker, _quotation_to_float, _money_to_float  # noqa: E402


def _resolve_instrument(ticker: str) -> tuple[str | None, str | None]:
    """Return (figi, uid) for ticker from the local catalog."""
    import csv
    path = "data/instruments/moex_futures.csv"
    if not os.path.exists(path):
        return None, None
    for row in csv.DictReader(open(path)):
        if row.get("ticker") == ticker:
            return (row.get("figi") or None), (row.get("uid") or None)
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="SiU6")
    ap.add_argument("--execute", action="store_true", help="actually submit the order (default: dry-run)")
    ap.add_argument("--limit-offset", type=int, default=None,
                    help="if set, send a LIMIT order at last_price +/- this many points instead of MARKET")
    args = ap.parse_args()

    load_dotenv()

    if os.getenv("TINVEST_LIVE_TRADING_TOKEN"):
        print("FATAL: TINVEST_LIVE_TRADING_TOKEN is set — refusing to run.", file=sys.stderr)
        sys.exit(2)

    figi, uid = _resolve_instrument(args.ticker)
    if not figi or not uid:
        print(f"FATAL: could not resolve figi/uid for {args.ticker} from local catalog.", file=sys.stderr)
        sys.exit(2)

    account_id = os.getenv("SANDBOX_ACCOUNT_ID")
    if not account_id:
        print("FATAL: SANDBOX_ACCOUNT_ID not set.", file=sys.stderr)
        sys.exit(2)

    with get_sandbox_broker() as broker:
        client = broker._client

        # 1. Read the live account position for this figi.
        positions = client.sandbox.get_sandbox_positions(account_id=account_id)
        net = 0
        for fut in getattr(positions, "futures", []) or []:
            if fut.figi == figi:
                net += int(fut.balance)
        print(f"ticker={args.ticker} figi={figi} uid={uid} account_net_lots={net}")

        if net == 0:
            print("Account is already FLAT for this instrument. Nothing to close.")
            return

        side = "BUY" if net < 0 else "SELL"
        qty = abs(net)
        print(f"Close plan: side={side} qty={qty} (opposite of net={net})")

        # Reference last price for sizing / optional limit.
        order_book = client.market_data.get_order_book(figi=figi, depth=1)
        last_price = _quotation_to_float(getattr(order_book, "last_price", None))
        print(f"last_price={last_price}")

        idempotency_key = str(uuid.uuid4())
        order_type = "MARKET"
        price = None
        if args.limit_offset is not None and last_price is not None:
            order_type = "LIMIT"
            # Cross the spread to fill: BUY above, SELL below.
            price = last_price + args.limit_offset if side == "BUY" else last_price - args.limit_offset
            print(f"LIMIT mode: price={price}")

        if not args.execute:
            print("\nDRY-RUN (no order sent). Re-run with --execute to submit:")
            print(f"  post_sandbox_order(instrument_id={figi}, quantity={qty}, "
                  f"direction={side}, order_type={order_type}, price={price}, "
                  f"order_id=<uuid>)")
            return

        # 2. Submit the close order.
        print(f"\nSubmitting {order_type} {side} {qty} lot(s) idempotency_key={idempotency_key} ...")
        try:
            result = broker.post_order(
                account_id=account_id,
                instrument_uid=uid,  # use uid (same field the working entry order used)
                quantity_lots=qty,
                direction=side,
                order_type=order_type,
                price=price,
                idempotency_key=idempotency_key,
            )
            print(f"RESULT: status={result.status} lots_executed={result.lots_executed} "
                  f"price={result.executed_price} commission={result.commission_rub} "
                  f"order_id={result.order_id}")
        except Exception as e:  # noqa: BLE001
            print(f"ORDER FAILED: {e!r}", file=sys.stderr)
            sys.exit(1)

        # 3. Re-read position to confirm.
        positions2 = client.sandbox.get_sandbox_positions(account_id=account_id)
        net2 = 0
        for fut in getattr(positions2, "futures", []) or []:
            if fut.figi == figi:
                net2 += int(fut.balance)
        print(f"POST-CLOSE account_net_lots={net2} ({'FLAT' if net2 == 0 else 'STILL OPEN'})")


if __name__ == "__main__":
    main()
