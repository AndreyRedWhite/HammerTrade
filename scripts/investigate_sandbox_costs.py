"""Investigate the commission discrepancy and slippage in the sandbox layer.

Order-level commission appeared ~38 RUB/order while trade-level was ~0.1 RUB.
Dump the raw broker responses to find the authoritative number, and compare the
engine's expected entry/exit price vs the broker's actual avg_fill_price
(the basis for the unpopulated slippage_points field).

Read-only.
"""
import json
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "data/sandbox/sandbox_state_hammer_baseline_siu6.sqlite"


def rows(q, args=()):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(q, args)]
    finally:
        c.close()


print(f"DB: {DB}")
print("=" * 100)
print("RAW ORDER COMMISSION + FILL detail (filled orders)")
ords = rows(
    "SELECT order_id, order_side, requested_qty, filled_qty, avg_fill_price, "
    "commission_rub, raw_response_json FROM sandbox_orders WHERE filled_qty>0 ORDER BY submitted_at"
)
for o in ords:
    raw = o["raw_response_json"]
    raw_keys = ""
    raw_comm = None
    if raw:
        try:
            d = json.loads(raw)
            raw_keys = ",".join(list(d.keys()))[:80]
            # look for any commission-like field
            for k in ("executed_commission", "initial_commission", "service_commission",
                      "total_order_amount", "executed_order_price", "aci_value"):
                if k in d:
                    raw_comm = (raw_comm or {})
                    raw_comm[k] = d[k]
        except Exception as e:
            raw_keys = f"<unparsable: {e}>"
    print(f"  {o['order_side']:4} qty={o['filled_qty']} fill={o['avg_fill_price']} "
          f"comm_col={o['commission_rub']}  raw_comm={raw_comm}")
    if raw_keys:
        print(f"        raw_keys: {raw_keys}")

print("=" * 100)
print("EXPECTED (engine) vs ACTUAL (broker fill) price per trade  -> slippage basis")
trades = rows("SELECT * FROM sandbox_trades WHERE status='CLOSED' ORDER BY entry_time")
# map order_id -> avg_fill_price
omap = {o["order_id"]: o for o in rows("SELECT order_id, avg_fill_price, commission_rub, order_side FROM sandbox_orders")}
tot_entry_slip = tot_exit_slip = 0.0
for t in trades:
    eo = omap.get(t["entry_order_id"])
    xo = omap.get(t["exit_order_id"])
    e_fill = eo["avg_fill_price"] if eo else None
    x_fill = xo["avg_fill_price"] if xo else None
    e_slip = (e_fill - t["entry_price"]) if e_fill is not None else None
    x_slip = (x_fill - t["exit_price"]) if x_fill is not None else None
    if e_slip is not None:
        tot_entry_slip += abs(e_slip)
    if x_slip is not None:
        tot_exit_slip += abs(x_slip)
    print(f"  {t['entry_time'][:16]} {t['direction']:4} "
          f"entry: eng={t['entry_price']:.0f} fill={e_fill} dslip={e_slip} | "
          f"exit: eng={t['exit_price']:.0f} fill={x_fill} dslip={x_slip}")

print(f"\n  total |entry slippage| pts = {tot_entry_slip:.1f}   total |exit slippage| pts = {tot_exit_slip:.1f}")

print("=" * 100)
print("Commission columns: order-level SUM vs trade-level SUM")
osum = sum((o["commission_rub"] or 0) for o in rows("SELECT commission_rub FROM sandbox_orders WHERE filled_qty>0"))
tsum = sum((t["commission_rub"] or 0) for t in trades)
print(f"  sum(sandbox_orders.commission_rub, filled) = {osum:.2f}")
print(f"  sum(sandbox_trades.commission_rub, closed)  = {tsum:.2f}")
print(f"  closed trades = {len(trades)}, filled orders = {len(ords)}")
