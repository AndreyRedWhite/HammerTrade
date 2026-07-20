"""READ-ONLY: list positions in the pairs sandbox account + resolve pair leg lots.

Confirms the stranded naked legs (TATNP +44, RTKMP -470) before any flatten.
Places NO orders. Run from /opt/hammertrade with the project venv + .env.
"""
import os
from dotenv import load_dotenv

from src.sandbox.broker import get_sandbox_broker
from src.tbank.client import get_tbank_client
from src.tbank.settings import load_tbank_settings
from src.tbank.instruments import resolve_instrument

PAIRS_ACCOUNT = "44ecc315-7d9a-4a71-b1de-bf45a5d3e2c3"
CLASS_CODE = "TQBR"
LEGS = ["TATNP", "TATN", "RTKMP", "RTKM", "MTLRP", "MTLR"]


def main():
    load_dotenv()

    # Resolve instrument metadata (uid/figi/lot) via prod market-data contour.
    meta = {}
    with get_tbank_client(load_tbank_settings(env="prod")) as c:
        for t in LEGS:
            try:
                r = resolve_instrument(c, t, CLASS_CODE)
                meta[t] = {"uid": r["uid"], "figi": r.get("figi"),
                           "lot": int(r.get("lot", 1) or 1)}
            except Exception as e:
                meta[t] = {"error": str(e)}
    uid_to_ticker = {m.get("uid"): t for t, m in meta.items() if m.get("uid")}
    figi_to_ticker = {m.get("figi"): t for t, m in meta.items() if m.get("figi")}

    print("=== instrument metadata ===")
    for t in LEGS:
        print(f"  {t:8s} {meta[t]}")

    print("\n=== raw positions in pairs sandbox account ===")
    with get_sandbox_broker() as broker:
        positions = broker.get_positions(PAIRS_ACCOUNT)
        if not positions:
            print("  (none)")
        for p in positions:
            tk = uid_to_ticker.get(p.instrument_uid) or figi_to_ticker.get(p.figi) or "?"
            print(f"  ticker={tk:8s} balance={p.balance:>6d} "
                  f"figi={p.figi} uid={p.instrument_uid}")

    print("\n=== flatten plan (balance in UNITS/shares; lot converts to order qty) ===")
    with get_sandbox_broker() as broker:
        for p in broker.get_positions(PAIRS_ACCOUNT):
            tk = uid_to_ticker.get(p.instrument_uid) or figi_to_ticker.get(p.figi)
            if tk is None or p.balance == 0:
                continue
            lot = meta[tk]["lot"]
            side = "SELL" if p.balance > 0 else "BUY"
            shares = abs(p.balance)
            lots = shares / lot if lot else shares
            ok = "OK" if lot and shares % lot == 0 else "NOT-DIVISIBLE-BY-LOT!"
            print(f"  {tk:8s} balance={p.balance:>6d} -> {side} shares={shares} "
                  f"lot={lot} order_qty={lots} [{ok}]")


if __name__ == "__main__":
    main()
