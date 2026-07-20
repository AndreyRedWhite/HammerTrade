"""Flatten stranded naked legs in the pairs SANDBOX account (virtual money).

The journal says these pairs are flat, but the account carries residue from the
pre-2026-07-02 fill-accounting bug window (RTKMP -470 from 06-30; TATNP +44).
reconcile only HALTs on the mismatch — it never self-heals — so the TATN pair
has been frozen since 07-13. This one-off market-flattens each nonzero balance
back to 0, which clears the HALT.

SANDBOX contour only. Dry-run unless EXECUTE=1 in the environment.
Run from /opt/hammertrade with PYTHONPATH=/opt/hammertrade and the project venv.
"""
import os
import uuid
from dotenv import load_dotenv

from src.sandbox.broker import get_sandbox_broker
from src.tbank.client import get_tbank_client
from src.tbank.settings import load_tbank_settings
from src.tbank.instruments import resolve_instrument

PAIRS_ACCOUNT = "44ecc315-7d9a-4a71-b1de-bf45a5d3e2c3"
CLASS_CODE = "TQBR"
LEGS = ["TATNP", "TATN", "RTKMP", "RTKM", "MTLRP", "MTLR"]
EXECUTE = os.getenv("EXECUTE") == "1"


def main():
    load_dotenv()

    meta = {}
    with get_tbank_client(load_tbank_settings(env="prod")) as c:
        for t in LEGS:
            r = resolve_instrument(c, t, CLASS_CODE)
            meta[t] = {"uid": r["uid"], "figi": r.get("figi"),
                       "lot": int(r.get("lot", 1) or 1)}
    uid_to_ticker = {m["uid"]: t for t, m in meta.items()}
    figi_to_ticker = {m["figi"]: t for t, m in meta.items() if m.get("figi")}
    ticker_lot = {t: m["lot"] for t, m in meta.items()}

    mode = "EXECUTE (real sandbox orders)" if EXECUTE else "DRY-RUN (no orders)"
    print(f"=== flatten pairs strays — {mode} ===")

    with get_sandbox_broker() as broker:
        positions = [p for p in broker.get_positions(PAIRS_ACCOUNT) if p.balance != 0]
        if not positions:
            print("  account already flat — nothing to do.")
            return

        for p in positions:
            tk = uid_to_ticker.get(p.instrument_uid) or figi_to_ticker.get(p.figi)
            if tk is None:
                print(f"  SKIP unknown instrument figi={p.figi} uid={p.instrument_uid} "
                      f"balance={p.balance}")
                continue
            lot = ticker_lot[tk]
            shares = abs(p.balance)
            if lot and shares % lot != 0:
                print(f"  SKIP {tk}: {shares} shares not divisible by lot {lot}")
                continue
            side = "SELL" if p.balance > 0 else "BUY"
            lots = shares // lot
            print(f"  {tk}: balance={p.balance:+d} -> {side} {lots} lots ({shares} shares)")
            if not EXECUTE:
                continue
            res = broker.post_order(
                account_id=PAIRS_ACCOUNT, instrument_uid=p.instrument_uid,
                quantity_lots=lots, direction=side, order_type="MARKET",
                idempotency_key=str(uuid.uuid4()),
            )
            print(f"    -> status={res.status} filled_lots={res.lots_executed} "
                  f"total_rub={res.executed_price} comm={res.commission_rub}")

    if EXECUTE:
        print("\n=== positions after flatten ===")
        with get_sandbox_broker() as broker:
            after = [p for p in broker.get_positions(PAIRS_ACCOUNT) if p.balance != 0]
            if not after:
                print("  FLAT — all pair legs zeroed. Reconcile HALT will clear next cycle.")
            for p in after:
                tk = uid_to_ticker.get(p.instrument_uid) or figi_to_ticker.get(p.figi) or "?"
                print(f"  STILL NONZERO {tk} balance={p.balance:+d}")


if __name__ == "__main__":
    main()
