#!/usr/bin/env python3
"""Phase-2 one-shot recovery, fired ~8 min after the close job (09:15 MSK).

Decision logic (sandbox only, never live, never touches paper):

1. Read the live sandbox SiU6 net position.
2. If already FLAT (the 09:07 close job succeeded): re-run the close+report
   orchestrator (a no-op close + DB reconcile when flat), then restart the
   sandbox daemon.
3. If still short (close job hit "30034 Not enough balance"): top up the
   sandbox account to TARGET_BALANCE (500_000 RUB), re-run the close+report
   orchestrator (now with enough buying power), and on success restart the
   daemon.
4. Verify status/diagnostics/logs after restart. Always write a report. If the
   account still is not FLAT, leave the daemon STOPPED.

--dry-run: report the net position and the planned branch only; no top-up, no
close, no restart, no balance change.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sandbox.broker import get_sandbox_broker, _money_to_float  # noqa: E402

CONFIG = "configs/sandbox/hammer_maxhold5_siu6.yaml"
TICKER = "SiU6"
DAEMON = "hammertrade-sandbox-maxhold5.service"
TARGET_BALANCE = 500_000.0
MSK = ZoneInfo("Europe/Moscow")


def _resolve_instrument(ticker: str):
    import csv
    path = "data/instruments/moex_futures.csv"
    if not os.path.exists(path):
        return None, None
    for row in csv.DictReader(open(path)):
        if row.get("ticker") == ticker:
            return (row.get("figi") or None), (row.get("uid") or None)
    return None, None


def _net_lots(client, account_id: str, figi: str) -> int:
    positions = client.sandbox.get_sandbox_positions(account_id=account_id)
    net = 0
    for fut in getattr(positions, "futures", []) or []:
        if fut.figi == figi:
            net += int(fut.balance)
    return net


def _cash_rub(client, account_id: str) -> float:
    p = client.sandbox.get_sandbox_portfolio(account_id=account_id)
    return _money_to_float(getattr(p, "total_amount_currencies", None)) or 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_dotenv()
    now_utc = datetime.now(timezone.utc)
    now_msk = now_utc.astimezone(MSK)
    lines: list[str] = []

    def log(s: str = "") -> None:
        print(s)
        lines.append(s)

    log(f"# Sandbox Post-Close Recovery — {TICKER}")
    log("")
    log(f"_Run at: {now_msk:%Y-%m-%d %H:%M:%S} MSK ({now_utc:%Y-%m-%dT%H:%M:%SZ})_  "
        f"{'**(dry-run)**' if args.dry_run else ''}")
    log("")

    if os.getenv("TINVEST_LIVE_TRADING_TOKEN"):
        log("**FATAL:** TINVEST_LIVE_TRADING_TOKEN is set — refusing to run.")
        _write_report(lines, now_msk)
        return 2

    cfg = yaml.safe_load(open(CONFIG))
    account_id = os.getenv(cfg.get("orders", {}).get("account_id_env", "SANDBOX_ACCOUNT_ID"))
    figi, uid = _resolve_instrument(TICKER)
    if not account_id or not figi:
        log("**FATAL:** missing SANDBOX_ACCOUNT_ID or instrument.")
        _write_report(lines, now_msk)
        return 2

    # --- 1. assess --------------------------------------------------------
    with get_sandbox_broker() as broker:
        client = broker._client
        net0 = _net_lots(client, account_id, figi)
        cash0 = _cash_rub(client, account_id)
    log("## Assessment\n")
    log(f"- Account net lots: **{net0}**")
    log(f"- Cash: **{cash0:,.2f} RUB**")
    branch = "FLAT_RESTART" if net0 == 0 else "TOPUP_RETRY"
    log(f"- Branch: **{branch}**\n")

    if args.dry_run:
        if net0 == 0:
            log("_Dry-run: would re-run close+report (reconcile) and restart daemon._")
        else:
            log(f"_Dry-run: would top up to {TARGET_BALANCE:,.0f} RUB "
                f"(+{max(0.0, TARGET_BALANCE - cash0):,.0f}), re-run close+report, "
                f"then restart daemon if FLAT._")
        _write_report(lines, now_msk)
        return 0

    # --- 2. top up if still short -----------------------------------------
    log("## Top-up\n")
    if net0 != 0:
        delta = round(TARGET_BALANCE - cash0, 2)
        if delta > 0:
            with get_sandbox_broker() as broker:
                new_bal = broker.pay_in(account_id, delta)
            log(f"Topped up +{delta:,.2f} RUB → balance ~{(new_bal or TARGET_BALANCE):,.2f} RUB.\n")
        else:
            log(f"Cash already ≥ target ({cash0:,.2f} ≥ {TARGET_BALANCE:,.0f}); no top-up.\n")
    else:
        log("_Account already FLAT; no top-up needed._\n")

    # --- 3. close + reconcile (delegated to the orchestrator) -------------
    log("## Close + reconcile\n")
    cp = subprocess.run(
        [sys.executable, "scripts/sandbox_close_and_report.py"],
        capture_output=True, text=True, timeout=180,
    )
    log(f"close_and_report exit={cp.returncode} "
        f"(0=FLAT, 1=still open). See reports/sandbox_manual_close_latest.md.\n")
    tail = "\n".join((cp.stdout or "").strip().splitlines()[-6:])
    log("```")
    log(tail)
    log("```")

    # --- 4. re-check + restart daemon -------------------------------------
    with get_sandbox_broker() as broker:
        client = broker._client
        net1 = _net_lots(client, account_id, figi)
    flat = (net1 == 0)
    log(f"\nAccount net lots after close: **{net1}** → {'FLAT' if flat else 'STILL OPEN'}\n")

    log("## Daemon restart\n")
    if not flat:
        log("Account NOT flat — daemon left **STOPPED**. Manual review required.")
        _write_report(lines, now_msk)
        return 1

    r = subprocess.run(["sudo", "-n", "systemctl", "restart", DAEMON],
                       capture_output=True, text=True)
    if r.returncode != 0:
        log(f"`systemctl restart {DAEMON}` FAILED rc={r.returncode}: {r.stderr.strip()[:200]}")
        log("Daemon NOT restarted — manual restart required.")
        _write_report(lines, now_msk)
        return 1
    time.sleep(20)
    active = subprocess.run(["systemctl", "is-active", DAEMON],
                           capture_output=True, text=True).stdout.strip()
    log(f"Restarted `{DAEMON}` → is-active=**{active}**.")

    # status + diagnostics + logs
    log("\n## Verification\n")
    try:
        import json
        st = json.load(open("runtime/sandbox_status_hammer_maxhold5_SiU6.json"))
        log(f"- trading_state={st.get('trading_state')} liveness={st.get('liveness')} "
            f"reconciliation={st.get('reconciliation_status')} "
            f"open_pos_expected={st.get('open_positions_expected')} "
            f"open_pos_actual={st.get('open_positions_actual')} "
            f"last_error={st.get('last_error_message')}")
    except Exception as e:  # noqa: BLE001
        log(f"- status read failed: {e!r}")
    diag = subprocess.run([sys.executable, "scripts/sandbox_diagnostics.py"],
                         capture_output=True, text=True, timeout=120)
    log(f"- diagnostics exit={diag.returncode} → reports/sandbox_diagnostics_hammer_maxhold5_latest.md")

    log("\n**RESULT: FLAT, DB reconciled, daemon restarted.**")
    _write_report(lines, now_msk)
    return 0


def _write_report(lines: list[str], now_msk: datetime) -> str:
    os.makedirs("reports", exist_ok=True)
    path = f"reports/sandbox_postclose_recover_{now_msk:%Y%m%d_%H%M}.md"
    body = "\n".join(lines) + "\n"
    with open(path, "w") as f:
        f.write(body)
    with open("reports/sandbox_postclose_recover_latest.md", "w") as f:
        f.write(body)
    print(f"\nReport written: {path}")
    return path


if __name__ == "__main__":
    sys.exit(main())
