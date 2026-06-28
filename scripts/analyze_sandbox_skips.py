"""Why does sandbox take fewer trades than paper, and where do entries differ?

Read-only diagnostic. No orders, no writes.
"""
import sqlite3
from collections import Counter, defaultdict

PAPER_DB = "data/paper/paper_state_siu6.sqlite"
SB_DB = "data/sandbox/sandbox_state_hammer_baseline_siu6.sqlite"
WINDOW_START = "2026-06-22"


def rows(db, q, args=()):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(q, args)]
    finally:
        c.close()


def norm(ts):
    # both schemas store ISO-ish; align to 'YYYY-MM-DDTHH:MM'
    return (ts or "")[:16].replace(" ", "T")


# 1) sandbox event types in the live window
print("=" * 90)
print("SANDBOX baseline event_type histogram (whole life)")
evs = rows(SB_DB, "SELECT event_type, message FROM sandbox_events ORDER BY timestamp")
print("  ", Counter(e["event_type"] for e in evs))
print("  --- non-routine events (pause/skip/reject/error) ---")
for e in evs:
    et = (e["event_type"] or "").upper()
    msg = (e["message"] or "")
    if any(k in et for k in ("PAUSE", "SKIP", "REJECT", "ERROR", "BLOCK", "LIMIT", "FAIL")) or \
       any(k in msg.lower() for k in ("pause", "skip", "reject", "error", "block", "not enough", "limit", "fail")):
        print(f"    {et}: {msg[:110]}")

# 2) sandbox_state risk flags
print("=" * 90)
print("SANDBOX baseline sandbox_state rows")
for r in rows(SB_DB, "SELECT key, value, updated_at FROM sandbox_state"):
    print(f"  {r['key']} = {str(r['value'])[:120]}  ({r['updated_at']})")
print("  sandbox_daily_risk:")
for r in rows(SB_DB, "SELECT * FROM sandbox_daily_risk ORDER BY date_msk"):
    print(f"    {dict(r)}")

# 3) like-for-like entries: match sandbox trades to paper trades by entry minute
print("=" * 90)
print("ENTRY MATCHING: paper SiU6 SELL trades vs sandbox baseline, window >= " + WINDOW_START)
ptr = rows(PAPER_DB, "SELECT * FROM paper_trades WHERE status='CLOSED' AND direction='SELL' AND entry_timestamp>=? ORDER BY entry_timestamp", (WINDOW_START,))
str_ = rows(SB_DB, "SELECT * FROM sandbox_trades WHERE status='CLOSED' AND direction='SELL' AND entry_time>=? ORDER BY entry_time", (WINDOW_START,))
sb_by_min = {norm(t["entry_time"]): t for t in str_}
print(f"  paper trades in window: {len(ptr)}   sandbox trades in window: {len(str_)}")
print(f"  {'entry_min':17} {'P_entry':>8} {'S_entry':>8} {'dEntry':>6} | {'P_exit':>8} {'S_exit':>8} | {'P_pnl':>7} {'S_pnl':>7} {'reason':>10}")
matched = 0
paper_only_pnl = 0.0
for p in ptr:
    key = norm(p["entry_timestamp"])
    s = sb_by_min.get(key)
    if s is None:
        # try +-2 min tolerance
        for dk, sv in sb_by_min.items():
            if abs(int(dk[11:13]) * 60 + int(dk[14:16]) - (int(key[11:13]) * 60 + int(key[14:16]))) <= 2 and dk[:10] == key[:10]:
                s = sv
                break
    if s is None:
        paper_only_pnl += p["pnl_rub"] or 0
        print(f"  {key:17} {p['entry_price']:8.0f} {'--':>8} {'--':>6} | {p['exit_price']:8.0f} {'--':>8} | {p['pnl_rub']:7.0f} {'--':>7} {'PAPER-ONLY':>10}")
    else:
        matched += 1
        de = (s["entry_price"] or 0) - (p["entry_price"] or 0)
        print(f"  {key:17} {p['entry_price']:8.0f} {s['entry_price']:8.0f} {de:6.0f} | {p['exit_price']:8.0f} {s['exit_price']:8.0f} | {p['pnl_rub']:7.0f} {s['net_pnl_rub']:7.0f} {s['exit_reason']:>10}")

print(f"\n  matched={matched}  paper-only (skipped by sandbox)={len(ptr)-matched}  paper-only PnL sum={paper_only_pnl:+.1f}")
