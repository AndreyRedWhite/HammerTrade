"""Ad-hoc analysis: why is paper profitable but sandbox always negative?

Compares the SiU6 hammer SELL baseline as it runs in BOTH the paper engine
(idealized fills) and the sandbox-execution layer (real sandbox-contour fills),
over the overlapping live window. Quantifies where the edge is lost:
entry slippage, exit slippage, commission, or different exit outcomes.

Read-only. No orders, no writes.
"""
import sqlite3
import sys
from collections import defaultdict

PAPER_DB = "data/paper/paper_state_siu6.sqlite"
SB_BASE_DB = "data/sandbox/sandbox_state_hammer_baseline_siu6.sqlite"
SB_MAX_DB = "data/sandbox/sandbox_state_hammer_maxhold5_siu6.sqlite"
PAPER_MAX_DB = "data/paper/paper_state_siu6_maxhold5.sqlite"


def rows(db, q, args=()):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(q, args)]
    finally:
        c.close()


def summarize_paper(db, since=None):
    q = "SELECT * FROM paper_trades WHERE status='CLOSED'"
    args = ()
    if since:
        q += " AND entry_timestamp >= ?"
        args = (since,)
    q += " ORDER BY entry_timestamp"
    tr = rows(db, q, args)
    net = sum(t["pnl_rub"] or 0 for t in tr)
    wins = [t for t in tr if (t["pnl_rub"] or 0) > 0]
    return tr, net, wins


def summarize_sandbox(db, since=None):
    q = "SELECT * FROM sandbox_trades WHERE status='CLOSED'"
    args = ()
    if since:
        q += " AND entry_time >= ?"
        args = (since,)
    q += " ORDER BY entry_time"
    tr = rows(db, q, args)
    net = sum(t["net_pnl_rub"] or 0 for t in tr)
    gross = sum(t["gross_pnl_rub"] or 0 for t in tr)
    comm = sum(t["commission_rub"] or 0 for t in tr)
    wins = [t for t in tr if (t["net_pnl_rub"] or 0) > 0]
    return tr, net, gross, comm, wins


def order_slippage(db):
    """Aggregate slippage by order_side from sandbox_orders (FILLED only)."""
    ords = rows(db, "SELECT * FROM sandbox_orders WHERE status IN ('EXECUTED','FILL','FILLED') OR filled_qty>0")
    agg = defaultdict(lambda: {"n": 0, "slip_pts": 0.0, "slip_rub": 0.0, "comm": 0.0})
    for o in ords:
        k = (o.get("order_side") or o.get("direction") or "?")
        agg[k]["n"] += 1
        agg[k]["slip_pts"] += o.get("slippage_points") or 0
        agg[k]["slip_rub"] += o.get("slippage_rub") or 0
        agg[k]["comm"] += o.get("commission_rub") or 0
    return agg


def main():
    print("=" * 90)
    print("PAPER baseline (all closed trades in paper_state_siu6.sqlite)")
    ptr, pnet, pwins = summarize_paper(PAPER_DB)
    print(f"  closed={len(ptr)}  net={pnet:+.1f} RUB  WR={len(pwins)/max(1,len(ptr))*100:.0f}%")
    if ptr:
        print(f"  first entry: {ptr[0]['entry_timestamp']}  last: {ptr[-1]['entry_timestamp']}")
        # ticker breakdown
        bt = defaultdict(lambda: [0, 0.0])
        for t in ptr:
            bt[t["ticker"]][0] += 1
            bt[t["ticker"]][1] += t["pnl_rub"] or 0
        for tk, (n, pn) in bt.items():
            print(f"    {tk}: {n} trades, {pn:+.1f} RUB")

    print("=" * 90)
    print("SANDBOX baseline (sandbox_state_hammer_baseline_siu6.sqlite)")
    str_, snet, sgross, scomm, swins = summarize_sandbox(SB_BASE_DB)
    print(f"  closed={len(str_)}  net={snet:+.1f}  gross={sgross:+.1f}  commission={scomm:.1f}  WR={len(swins)/max(1,len(str_))*100:.0f}%")
    if str_:
        print(f"  first entry: {str_[0]['entry_time']}  last: {str_[-1]['entry_time']}")
    print("  --- per-trade detail (sandbox baseline) ---")
    for t in str_:
        print(f"    {t['entry_time'][:16]} {t['direction']:4} entry={t['entry_price']:.0f} "
              f"stop={t['stop_price']:.0f} take={t['take_price']:.0f} exit={t['exit_price']:.0f} "
              f"[{t['exit_reason']}] bars={t['bars_held']} gross={t['gross_pnl_rub']:+.1f} "
              f"comm={t['commission_rub']:.1f} net={t['net_pnl_rub']:+.1f}")
    print("  --- slippage by order side (baseline) ---")
    for k, v in order_slippage(SB_BASE_DB).items():
        print(f"    {k}: n={v['n']} slip_pts_total={v['slip_pts']:+.1f} slip_rub_total={v['slip_rub']:+.1f} comm={v['comm']:.1f}")

    print("=" * 90)
    print("SANDBOX maxhold5 (sandbox_state_hammer_maxhold5_siu6.sqlite)")
    mtr, mnet, mgross, mcomm, mwins = summarize_sandbox(SB_MAX_DB)
    print(f"  closed={len(mtr)}  net={mnet:+.1f}  gross={mgross:+.1f}  commission={mcomm:.1f}  WR={len(mwins)/max(1,len(mtr))*100:.0f}%")
    # exit reason breakdown
    er = defaultdict(lambda: [0, 0.0])
    for t in mtr:
        er[t["exit_reason"]][0] += 1
        er[t["exit_reason"]][1] += t["net_pnl_rub"] or 0
    print("  exit reasons:", {k: f"{n}tr {pn:+.0f}" for k, (n, pn) in er.items()})
    print("  --- slippage by order side (maxhold5) ---")
    for k, v in order_slippage(SB_MAX_DB).items():
        print(f"    {k}: n={v['n']} slip_pts_total={v['slip_pts']:+.1f} slip_rub_total={v['slip_rub']:+.1f} comm={v['comm']:.1f}")

    print("=" * 90)
    print("PAPER maxhold5 (paper_state_siu6_maxhold5.sqlite) for comparison")
    pmtr, pmnet, pmwins = summarize_paper(PAPER_MAX_DB)
    print(f"  closed={len(pmtr)}  net={pmnet:+.1f}  WR={len(pmwins)/max(1,len(pmtr))*100:.0f}%")

    # Match sandbox-baseline trades to paper trades by date for like-for-like
    print("=" * 90)
    print("LIKE-FOR-LIKE: sandbox baseline trades vs paper baseline same-day SiU6 trades")
    paper_siu6 = [t for t in ptr if t["ticker"].startswith("SiU6") or t["ticker"].startswith("Si")]
    p_by_day = defaultdict(list)
    for t in paper_siu6:
        p_by_day[t["entry_timestamp"][:10]].append(t)
    for t in str_:
        day = t["entry_time"][:10]
        matches = p_by_day.get(day, [])
        pm = sum(x["pnl_rub"] or 0 for x in matches)
        print(f"  {day}: sandbox net={t['net_pnl_rub']:+.1f}  | paper same-day {len(matches)}tr net={pm:+.1f}")


if __name__ == "__main__":
    main()
