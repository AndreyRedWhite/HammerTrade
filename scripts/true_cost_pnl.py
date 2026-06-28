"""True cost-adjusted PnL: how much of the reported edge survives real costs?

Reported PnL models ~0 commission (commission_per_trade=0.025 -> 0.05 RUB/round
trip) and, for sandbox, idealized engine fills rather than actual broker fills.
This shows the headline strategies' net PnL under a range of per-round-trip
commission assumptions, plus the sandbox baseline recomputed from ACTUAL fills.

Read-only.
"""
import sqlite3

PV = 10.0  # SiU6 point value RUB


def rows(db, q):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(q)]
    finally:
        c.close()


def paper_net(db, comm_round_trip):
    tr = rows(db, "SELECT pnl_rub FROM paper_trades WHERE status='CLOSED'")
    # reported pnl_rub already nets the modeled 0.05 comm; add back ~0, then apply real comm
    n = len(tr)
    reported = sum(t["pnl_rub"] or 0 for t in tr)
    # strip modeled comm (~0.05/rt) then apply assumed real comm
    return reported + n * 0.05 - n * comm_round_trip, n


print("PAPER strategies — net PnL vs assumed commission per round-trip (RUB)")
print(f"{'strategy':28} {'n':>4}  " + "  ".join(f"@{c:>5}" for c in (0.1, 5, 10, 20, 76.4)))
for name, db in (
    ("hammer SELL baseline", "data/paper/paper_state_siu6.sqlite"),
    ("hammer SELL maxhold5", "data/paper/paper_state_siu6_maxhold5.sqlite"),
    ("hammer BUY long", "data/paper/paper_state_siu6_long.sqlite"),
):
    line = f"{name:28}"
    n0 = None
    cells = []
    for c in (0.1, 5, 10, 20, 76.4):
        net, n = paper_net(db, c)
        n0 = n
        cells.append(f"{net:>7.0f}")
    print(f"{name:28} {n0:>4}  " + "  ".join(cells))

print()
print("0.05% of ~76000 notional = 38.0 RUB/order = 76.0 RUB/round-trip (the sandbox rate)")
print()

# Sandbox baseline: recompute from ACTUAL broker fills + ACTUAL broker commission
db = "data/sandbox/sandbox_state_hammer_baseline_siu6.sqlite"
trades = rows(db, "SELECT * FROM sandbox_trades WHERE status='CLOSED' ORDER BY entry_time")
omap = {o["order_id"]: o for o in rows(db, "SELECT order_id, avg_fill_price, commission_rub FROM sandbox_orders")}
print("SANDBOX baseline — reported (idealized) vs TRUE (actual fills + real commission)")
rep_net = true_gross = true_comm = true_net = 0.0
for t in trades:
    eo = omap.get(t["entry_order_id"])
    xo = omap.get(t["exit_order_id"])
    if not eo or not xo or eo["avg_fill_price"] is None or xo["avg_fill_price"] is None:
        continue
    ef, xf = eo["avg_fill_price"], xo["avg_fill_price"]
    g = (ef - xf) * PV * t["qty"] if t["direction"] == "SELL" else (xf - ef) * PV * t["qty"]
    comm = (eo["commission_rub"] or 0) + (xo["commission_rub"] or 0)
    rep_net += t["net_pnl_rub"] or 0
    true_gross += g
    true_comm += comm
    true_net += g - comm
print(f"  reported net (idealized, ~0 comm) : {rep_net:+.1f}")
print(f"  TRUE gross (actual fills)         : {true_gross:+.1f}")
print(f"  TRUE commission (broker)          : -{true_comm:.1f}")
print(f"  TRUE net (fills - commission)     : {true_net:+.1f}")
print(f"  => execution + cost drag vs reported: {true_net - rep_net:+.1f} over {len(trades)} trades")
