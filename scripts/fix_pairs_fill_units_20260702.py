"""One-off migration (2026-07-02): pair_trades fills stored as TOTAL RUB → per-share.

Before this date run_pairs_sandbox_trader stored the API's `executed_order_price`
(TOTAL executed value) in pref/ord_*_fill and multiplied by qty again in the PnL
math — inflating pair PnL ~×qty (RTKM showed +56k where reality was ~+8 ₽ net).

Converts every fill to per-share (value / qty) and recomputes gross/net for
CLOSED trades (commission unchanged). Idempotent: marks the DB with a
FILL_UNITS_MIGRATED event and refuses to run twice.

Usage:
    python scripts/fix_pairs_fill_units_20260702.py data/sandbox/sandbox_pairs_*.sqlite         # dry-run
    python scripts/fix_pairs_fill_units_20260702.py --apply data/sandbox/sandbox_pairs_*.sqlite
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone

MARKER = "FILL_UNITS_MIGRATED"
# rows created after this instant were written by the FIXED trader (per-share
# fills) and must never be divided again
CUTOFF = "2026-07-02T11:00:00+00:00"


def recompute(row: dict) -> dict:
    """Per-share fills + recomputed PnL for one pair_trades row (dict in/out)."""
    out = dict(row)
    psh, osh = row["pref_qty"], row["ord_qty"]
    for col, sh in (("pref_entry_fill", psh), ("ord_entry_fill", osh),
                    ("pref_exit_fill", psh), ("ord_exit_fill", osh)):
        if row.get(col) is not None:
            out[col] = row[col] / sh
    if row["status"] == "CLOSED" and out.get("pref_exit_fill") is not None:
        if row["direction"] == "LONG_SPREAD":
            pref_pnl = (out["pref_exit_fill"] - out["pref_entry_fill"]) * psh
            ord_pnl = (out["ord_entry_fill"] - out["ord_exit_fill"]) * osh
        else:
            pref_pnl = (out["pref_entry_fill"] - out["pref_exit_fill"]) * psh
            ord_pnl = (out["ord_exit_fill"] - out["ord_entry_fill"]) * osh
        gross = pref_pnl + ord_pnl
        out["gross_pnl_rub"] = round(gross, 2)
        out["net_pnl_rub"] = round(gross - (row["commission_rub"] or 0), 2)
    return out


def migrate(path: str, apply: bool) -> None:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    done = con.execute("SELECT 1 FROM events WHERE kind=?", (MARKER,)).fetchone()
    if done:
        print(f"{path}: already migrated — skipping")
        return
    rows = [dict(r) for r in con.execute("SELECT * FROM pair_trades")]
    if not rows:
        print(f"{path}: no trades")
    skipped = [r for r in rows if str(r.get("created_at", "")) >= CUTOFF]
    if skipped:
        print(f"{path}: {len(skipped)} row(s) created after {CUTOFF} — written by the "
              f"fixed trader, left untouched")
    rows = [r for r in rows if str(r.get("created_at", "")) < CUTOFF]
    for r in rows:
        new = recompute(r)
        print(f"{path}: {r['trade_id']} [{r['status']}]"
              f"\n  fills {r['pref_entry_fill']}/{r['ord_entry_fill']}"
              f" -> {new['pref_entry_fill']:.2f}/{new['ord_entry_fill']:.2f}"
              f"\n  gross {r['gross_pnl_rub']} -> {new['gross_pnl_rub']}"
              f"  net {r['net_pnl_rub']} -> {new['net_pnl_rub']}")
        if apply:
            con.execute(
                "UPDATE pair_trades SET pref_entry_fill=?, ord_entry_fill=?, "
                "pref_exit_fill=?, ord_exit_fill=?, gross_pnl_rub=?, net_pnl_rub=?, "
                "updated_at=? WHERE trade_id=?",
                (new["pref_entry_fill"], new["ord_entry_fill"], new["pref_exit_fill"],
                 new["ord_exit_fill"], new["gross_pnl_rub"], new["net_pnl_rub"],
                 datetime.now(tz=timezone.utc).isoformat(), r["trade_id"]))
    if apply:
        con.execute("INSERT INTO events(ts,kind,message) VALUES(?,?,?)",
                    (datetime.now(tz=timezone.utc).isoformat(), MARKER,
                     f"{len(rows)} trade(s) converted total→per-share"))
        con.commit()
        print(f"{path}: APPLIED ({len(rows)} trade(s))")
    con.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("dbs", nargs="+", help="sandbox_pairs_*.sqlite paths")
    p.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = p.parse_args()
    for db in args.dbs:
        migrate(db, args.apply)


if __name__ == "__main__":
    main()
