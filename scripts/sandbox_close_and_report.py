#!/usr/bin/env python3
"""One-shot orchestrator: flatten the stuck sandbox SiU6 short, reconcile the
sandbox DB, run diagnostics, and write a report.

Designed to be fired ONCE by a systemd timer shortly after MOEX open. It is
deliberately conservative:

- Sandbox contour ONLY (SANDBOX_TOKEN). Hard-fails if TINVEST_LIVE_TRADING_TOKEN
  is set. No prod/live order path exists here.
- Does NOT start hammertrade-sandbox-maxhold5.service and does NOT touch the
  paper services.
- Backs up the sandbox DB before doing anything.
- Bounded close attempts (MARKET, then two crossing LIMIT fallbacks). On
  "30034 Not enough balance" it tries the next variant; on any other error
  (e.g. "30079 Instrument is not available for trading" when the market is
  closed) it stops immediately. Never loops forever.
- Reconciles the DB to FLAT/CLOSED ONLY after the live sandbox account is
  actually FLAT. Otherwise it leaves the DB untouched and the position open.
- Always writes a report, even on failure. Exit code 0 = account is FLAT,
  1 = still open / failed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_params  # noqa: E402
from src.sandbox.broker import get_sandbox_broker, _quotation_to_float  # noqa: E402
from src.sandbox.models import (  # noqa: E402
    SandboxExitReason,
    SandboxPosition,
    SandboxTradeStatus,
)
from src.sandbox.repository import SandboxRepository  # noqa: E402

CONFIG = "configs/sandbox/hammer_maxhold5_siu6.yaml"
TICKER = "SiU6"
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


def main() -> int:
    load_dotenv()
    now_utc = datetime.now(timezone.utc)
    now_msk = now_utc.astimezone(MSK)
    lines: list[str] = []

    def log(s: str = "") -> None:
        print(s)
        lines.append(s)

    log(f"# Sandbox Manual Close — {TICKER}")
    log("")
    log(f"_Run at: {now_msk:%Y-%m-%d %H:%M:%S} MSK ({now_utc:%Y-%m-%dT%H:%M:%SZ})_")
    log("")

    # --- safety -----------------------------------------------------------
    if os.getenv("TINVEST_LIVE_TRADING_TOKEN"):
        log("**FATAL:** TINVEST_LIVE_TRADING_TOKEN is set — refusing to run.")
        _write_report(lines, now_msk)
        return 2

    cfg = yaml.safe_load(open(CONFIG))
    db_path = cfg["artifacts"]["db"]
    account_id = os.getenv(cfg.get("orders", {}).get("account_id_env", "SANDBOX_ACCOUNT_ID"))
    if not account_id:
        log("**FATAL:** SANDBOX_ACCOUNT_ID not set.")
        _write_report(lines, now_msk)
        return 2

    figi, uid = _resolve_instrument(TICKER)
    if not figi or not uid:
        log(f"**FATAL:** could not resolve figi/uid for {TICKER}.")
        _write_report(lines, now_msk)
        return 2

    # --- 1. backup DB -----------------------------------------------------
    backup = f"{db_path}.BACKUP_close_{now_utc:%Y%m%dT%H%M%SZ}.sqlite"
    if os.path.exists(db_path):
        shutil.copy2(db_path, backup)
        log(f"## Backup\n\n`{backup}`\n")
    else:
        log(f"## Backup\n\n_DB not found at {db_path}; nothing to back up._\n")

    # --- 2. attempt close -------------------------------------------------
    log("## Close attempts\n")
    attempts_md = ["| # | type | price | result | status | lots | error |",
                   "|---|------|------:|--------|--------|-----:|-------|"]
    fill_price = None
    net_before = None
    net_after = None

    with get_sandbox_broker() as broker:
        client = broker._client
        net_before = _net_lots(client, account_id, figi)
        log(f"Account net lots BEFORE: **{net_before}**\n")

        if net_before != 0:
            side = "BUY" if net_before < 0 else "SELL"
            qty = abs(net_before)
            # MARKET first, then two crossing LIMITs as 30034 fallbacks.
            plan = [("MARKET", None), ("LIMIT", 50), ("LIMIT", 150)]
            for i, (order_type, offset) in enumerate(plan, 1):
                price = None
                if order_type == "LIMIT":
                    ob = client.market_data.get_order_book(figi=figi, depth=1)
                    last = _quotation_to_float(getattr(ob, "last_price", None))
                    if last is None:
                        attempts_md.append(f"| {i} | LIMIT | — | SKIP | no last_price | — | — |")
                        continue
                    price = last + offset if side == "BUY" else last - offset
                try:
                    res = broker.post_order(
                        account_id=account_id, instrument_uid=uid, quantity_lots=qty,
                        direction=side, order_type=order_type, price=price,
                        idempotency_key=str(uuid.uuid4()),
                    )
                    filled = (res.lots_executed or 0) > 0 or "FILL" in (res.status or "")
                    attempts_md.append(
                        f"| {i} | {order_type} | {price if price is not None else '—'} | "
                        f"{'FILLED' if filled else 'ACCEPTED'} | {res.status} | "
                        f"{res.lots_executed} | — |"
                    )
                    if filled:
                        fill_price = res.executed_price or price
                        break
                except Exception as e:  # noqa: BLE001
                    err = str(e)
                    short = "30034 Not enough balance" if "30034" in err else (
                        "30079 Instrument not available" if "30079" in err else err[:60])
                    attempts_md.append(
                        f"| {i} | {order_type} | {price if price is not None else '—'} | "
                        f"ERROR | — | — | {short} |")
                    if "30034" in err:
                        continue  # try the next (limit) variant
                    break  # market closed or anything else: stop, do not spam
        net_after = _net_lots(client, account_id, figi)

    log("\n".join(attempts_md))
    log("")
    log(f"Account net lots AFTER: **{net_after}**\n")

    flat = (net_after == 0)

    # --- 3. reconcile DB ONLY if actually flat ----------------------------
    log("## DB reconciliation\n")
    if not flat:
        log("_Account is NOT flat — DB left untouched, position stays OPEN. "
            "No daemon restart._\n")
    else:
        repo = SandboxRepository(db_path)
        open_trade = repo.get_open_trade(TICKER)
        if open_trade is None:
            log("_Account flat and no OPEN trade in DB — already consistent._\n")
        else:
            params = load_params(cfg.get("params_file", "configs/hammer_detector_balanced.env"))
            pv = params.point_value_rub
            exit_price = fill_price if fill_price is not None else open_trade.entry_price
            if open_trade.direction == "SELL":
                pnl_points = open_trade.entry_price - exit_price
            else:
                pnl_points = exit_price - open_trade.entry_price
            gross = round(pnl_points * pv * open_trade.qty, 2)
            open_trade.status = SandboxTradeStatus.CLOSED
            open_trade.exit_time = datetime.now(timezone.utc)
            open_trade.exit_price = exit_price
            open_trade.exit_reason = SandboxExitReason.MANUAL_CLOSE
            open_trade.gross_pnl_rub = gross
            open_trade.net_pnl_rub = gross  # commissions not separately re-derived; manual cleanup
            repo.update_trade(open_trade)
            repo.upsert_position(SandboxPosition(
                ticker=TICKER, figi=figi, instrument_uid=uid,
                direction="FLAT", qty=0, avg_price=None,
            ))
            rs = repo.load_risk_state()
            rs.exit_error_count = 0
            rs.consecutive_errors = 0
            rs.trading_paused = False
            rs.trading_paused_reason = None
            repo.save_risk_state(rs)
            log(f"Closed DB trade `{open_trade.trade_id}` as MANUAL_CLOSE "
                f"exit_price={exit_price} gross_pnl_rub={gross}. Position→FLAT. "
                f"Reset exit_error_count/consecutive_errors/trading_paused.\n")

    # --- 4. diagnostics ---------------------------------------------------
    log("## Diagnostics\n")
    try:
        out = subprocess.run(
            [sys.executable, "scripts/sandbox_diagnostics.py"],
            capture_output=True, text=True, timeout=120,
        )
        log("```")
        log((out.stdout or "").strip()[:1500])
        if out.returncode != 0:
            log(f"(diagnostics exit={out.returncode})")
            log((out.stderr or "").strip()[:500])
        log("```")
    except Exception as e:  # noqa: BLE001
        log(f"_diagnostics failed: {e!r}_")

    # --- 5. daemon note ---------------------------------------------------
    log("")
    log("## Daemon")
    log("")
    log("`hammertrade-sandbox-maxhold5.service` left **STOPPED** "
        "(not auto-restarted). Restart manually only after reviewing this report.")

    path = _write_report(lines, now_msk)
    print(f"\nReport written: {path}")
    print(f"RESULT: {'FLAT' if flat else 'STILL_OPEN'}")
    return 0 if flat else 1


def _write_report(lines: list[str], now_msk: datetime) -> str:
    os.makedirs("reports", exist_ok=True)
    path = f"reports/sandbox_manual_close_{now_msk:%Y%m%d_%H%M}.md"
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    # stable "latest" copy for convenience
    with open("reports/sandbox_manual_close_latest.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


if __name__ == "__main__":
    sys.exit(main())
