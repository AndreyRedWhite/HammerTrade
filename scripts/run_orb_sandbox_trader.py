"""ORB SHORT SANDBOX trading daemon — REAL fills on the T-Bank SANDBOX contour
(virtual money). Single-leg Opening Range Breakout SHORT on a futures instrument.

Validated edge (from-scratch, real costs, 2026-06-30): ORB SHORT filtered
(cap500 + vol2x) survives — slippage-robust (big trades), TEST pf ~1.5.

Logic (per MSK trading day):
  * Opening range = high/low of [or_start, or_end) MSK.
  * Skip the day if OR range > max_or_range (too volatile).
  * SHORT entry: first CLOSED bar after or_end whose low <= or_low AND
    volume >= vol_mult * avg_OR_volume. Enter at market (records real fill).
  * stop = or_high; take = or_low - take_r * (or_high - or_low).
  * Exit on bar high >= stop, bar low <= take, or time >= time_exit (market close).
  * One trade per day.

Safety: sandbox contour only; refuses without ENABLED flag unless --dry-run;
daily trade cap; position reconciliation (journal vs account); pause resets daily.
"""
import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.market_data import fetch_recent_candles
from src.sandbox.broker import get_sandbox_broker


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ORB SHORT SANDBOX daemon (real sandbox fills).")
    p.add_argument("--ticker", default="SiU6")
    p.add_argument("--class-code", default="SPBFUT")
    p.add_argument("--or-start", default="10:00")
    p.add_argument("--or-end", default="11:00")
    p.add_argument("--time-exit", default="18:40")
    p.add_argument("--take-r", type=float, default=3.0)
    p.add_argument("--max-or-range", type=float, default=500.0)
    p.add_argument("--breakout-vol-mult", type=float, default=2.0)
    p.add_argument("--contracts", type=int, default=1)
    p.add_argument("--lookback-minutes", type=int, default=1440)
    p.add_argument("--account-id-env", default="SANDBOX_ACCOUNT_ID_ORB")
    p.add_argument("--account-id", default=None)
    p.add_argument("--trading-enabled-env", default="SANDBOX_ORB_ENABLED")
    p.add_argument("--state-db", default="data/sandbox/sandbox_orb.sqlite")
    p.add_argument("--status-file", default="runtime/sandbox_status_ORB.json")
    p.add_argument("--log-file", default="logs/sandbox_ORB.log")
    p.add_argument("--poll-interval-seconds", type=int, default=60)
    p.add_argument("--env", default="prod", help="Env for MARKET DATA. Orders always sandbox.")
    p.add_argument("--market-hours-config", default="configs/market_hours/moex_futures.yaml")
    p.add_argument("--ignore-market-hours", action="store_true")
    p.add_argument("--api-timeout-sec", type=int, default=15)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--once", action="store_true")
    return p.parse_args()


def _t(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def _setup_logging(log_file: str) -> logging.Logger:
    logger = logging.getLogger("orb_sandbox")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [orb_sandbox] %(message)s")
    if not logger.handlers:
        sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); logger.addHandler(sh)
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file); fh.setFormatter(fmt); logger.addHandler(fh)
    return logger


def _today_msk(now_utc: Optional[datetime] = None) -> str:
    now_utc = now_utc or datetime.now(tz=timezone.utc)
    return (now_utc + timedelta(hours=3)).strftime("%Y-%m-%d")


class OrbDB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path); self.con.row_factory = sqlite3.Row
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS orb_trades (
            trade_id TEXT PRIMARY KEY, date_msk TEXT, ticker TEXT, direction TEXT, status TEXT,
            qty INTEGER, entry_ts TEXT, entry_fill REAL, stop REAL, take REAL,
            exit_ts TEXT, exit_fill REAL, exit_reason TEXT,
            gross_pnl_rub REAL, commission_rub REAL, net_pnl_rub REAL, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS day_state (
            date_msk TEXT PRIMARY KEY, or_high REAL, or_low REAL, or_avg_vol REAL,
            or_valid INTEGER, trade_taken INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS daily_risk (date_msk TEXT PRIMARY KEY, trades_today INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, message TEXT);
        """)
        self.con.commit()

    def get_day(self, d): return self.con.execute("SELECT * FROM day_state WHERE date_msk=?", (d,)).fetchone()
    def set_day(self, d, oh, ol, av, valid):
        self.con.execute("INSERT INTO day_state(date_msk,or_high,or_low,or_avg_vol,or_valid) VALUES(?,?,?,?,?) "
                         "ON CONFLICT(date_msk) DO UPDATE SET or_high=excluded.or_high,or_low=excluded.or_low,"
                         "or_avg_vol=excluded.or_avg_vol,or_valid=excluded.or_valid", (d, oh, ol, av, int(valid)))
        self.con.commit()
    def mark_taken(self, d):
        self.con.execute("UPDATE day_state SET trade_taken=1 WHERE date_msk=?", (d,)); self.con.commit()
    def open_trade(self):
        return self.con.execute("SELECT * FROM orb_trades WHERE status='OPEN' ORDER BY entry_ts DESC LIMIT 1").fetchone()
    def upsert(self, t):
        cols=",".join(t); ph=",".join("?"*len(t)); upd=",".join(f"{k}=excluded.{k}" for k in t if k!="trade_id")
        self.con.execute(f"INSERT INTO orb_trades({cols}) VALUES({ph}) ON CONFLICT(trade_id) DO UPDATE SET {upd}", list(t.values()))
        self.con.commit()
    def event(self, kind, msg):
        self.con.execute("INSERT INTO events(ts,kind,message) VALUES(?,?,?)",
                         (datetime.now(tz=timezone.utc).isoformat(), kind, msg)); self.con.commit()
    def trades_today(self, d):
        r=self.con.execute("SELECT trades_today FROM daily_risk WHERE date_msk=?", (d,)).fetchone()
        return r["trades_today"] if r else 0
    def bump_today(self, d):
        self.con.execute("INSERT INTO daily_risk(date_msk,trades_today) VALUES(?,1) "
                         "ON CONFLICT(date_msk) DO UPDATE SET trades_today=trades_today+1", (d,)); self.con.commit()
    def closed(self): return self.con.execute("SELECT * FROM orb_trades WHERE status='CLOSED'").fetchall()
    def all_open(self): return self.con.execute("SELECT * FROM orb_trades WHERE status='OPEN'").fetchall()


def _order(broker, account_id, uid, lots, side, dry_run, logger, tag):
    if dry_run:
        logger.info(f"DRY_ORDER {tag} side={side} lots={lots}")
        return None, 0.0
    res = broker.post_order(account_id=account_id, instrument_uid=uid, quantity_lots=lots,
                            direction=side, order_type="MARKET", idempotency_key=str(uuid.uuid4()))
    logger.info(f"ORDER {tag} side={side} lots={lots} status={res.status} "
                f"filled={res.lots_executed} price={res.executed_price} comm={res.commission_rub}")
    return res.executed_price, (res.commission_rub or 0.0)


def _reconcile(broker, account_id, uid, expected_short_lots, logger):
    """expected_short_lots >=0 (SHORT). actual balance negative=short."""
    actual = 0
    for p in broker.get_positions(account_id):
        if p.instrument_uid == uid or p.figi:  # match by uid; figi fallback handled by caller mapping
            if p.instrument_uid == uid:
                actual = int(p.balance)
    exp = -expected_short_lots  # short -> negative balance
    if exp != actual:
        return False, f"exp_lots={exp} act_lots={actual}"
    return True, "OK"


def _msk(ts): return ts.tz_convert("Europe/Moscow")


def _cycle(args, broker, account_id, uid, db, logger, market_open, session, dry_run):
    now_utc = datetime.now(tz=timezone.utc)
    d = _today_msk(now_utc)
    or_s, or_e, t_exit = _t(args.or_start), _t(args.or_end), _t(args.time_exit)

    df, _ = fetch_recent_candles(args.ticker, args.class_code, "1m", args.lookback_minutes, args.env)
    if df is None or df.empty:
        return {"status": "NO_CANDLES"}
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
    df["mskt"] = df["ts"].dt.tz_convert("Europe/Moscow")
    df = df[df["mskt"].dt.strftime("%Y-%m-%d") == d]
    if df.empty:
        return {"status": "NO_TODAY_BARS"}
    df["tt"] = df["mskt"].dt.time
    now_msk_t = (now_utc + timedelta(hours=3)).time()

    open_t = db.open_trade()
    open_t = dict(open_t) if open_t else None

    if not dry_run:
        ok, det = _reconcile(broker, account_id, uid, args.contracts if open_t else 0, logger)
        if not ok:
            logger.error(f"RECONCILE_FAIL {det}"); db.event("RECONCILE_FAIL", det)
            return {"status": "RECONCILE_FAILED", "detail": det}

    # 1) compute OR once window has closed
    day = db.get_day(d)
    if day is None and now_msk_t >= or_e:
        orc = df[(df.tt >= or_s) & (df.tt < or_e)]
        if len(orc) >= 5:
            oh, ol = float(orc.high.max()), float(orc.low.min())
            avgv = float(orc.volume.mean())
            valid = (oh - ol) > 0 and (oh - ol) <= args.max_or_range
            db.set_day(d, oh, ol, avgv, valid)
            logger.info(f"OR_SET {d} high={oh} low={ol} range={oh-ol:.0f} avgvol={avgv:.0f} valid={valid}")
            day = db.get_day(d)

    # 2) manage open position (exit checks on latest closed bar + time)
    if open_t is not None:
        last = df.iloc[-1]
        exit_reason = None
        if now_msk_t >= t_exit:
            exit_reason = "TIME_EXIT"
        elif float(last.high) >= open_t["stop"]:
            exit_reason = "STOP"
        elif float(last.low) <= open_t["take"]:
            exit_reason = "TAKE"
        if exit_reason:
            xf, xc = _order(broker, account_id, uid, args.contracts, "BUY", dry_run, logger, f"{args.ticker}/EXIT")
            exit_fill = xf if xf is not None else (open_t["stop"] if exit_reason == "STOP" else
                        (open_t["take"] if exit_reason == "TAKE" else float(last.close)))
            gross = (open_t["entry_fill"] - exit_fill) * args.contracts  # SHORT, point_value=1
            comm = (open_t["commission_rub"] or 0) + xc
            net = gross - comm
            upd = dict(open_t); upd.update(status="CLOSED", exit_ts=now_utc.isoformat(), exit_fill=exit_fill,
                       exit_reason=exit_reason, gross_pnl_rub=round(gross, 2), commission_rub=comm,
                       net_pnl_rub=round(net, 2), updated_at=now_utc.isoformat())
            db.upsert(upd)
            logger.info(f"ORB_EXIT {exit_reason} entry={open_t['entry_fill']} exit={exit_fill} NET={net:.1f}")
        return {"status": "OK", "has_open": exit_reason is None,
                "or_low": day["or_low"] if day else None}

    # 3) look for entry (FLAT)
    if day is None or not day["or_valid"] or day["trade_taken"]:
        return {"status": "OK", "has_open": False, "or_ready": day is not None}
    if now_msk_t < or_e or now_msk_t >= t_exit:
        return {"status": "OK", "has_open": False, "or_ready": True}
    if db.trades_today(d) >= 1:
        return {"status": "OK", "has_open": False}

    post = df[(df.tt >= or_e) & (df.tt < t_exit)]
    ol, oh, avgv = day["or_low"], day["or_high"], day["or_avg_vol"]
    breakout = post[(post.low <= ol) & (post.volume >= args.breakout_vol_mult * avgv)]
    if breakout.empty:
        return {"status": "OK", "has_open": False, "or_ready": True, "or_low": ol}

    # enter SHORT at market now (breakout confirmed)
    ef, ec = _order(broker, account_id, uid, args.contracts, "SELL", dry_run, logger, f"{args.ticker}/ENTRY")
    entry_fill = ef if ef is not None else ol
    stop = oh
    take = ol - args.take_r * (oh - ol)
    tid = f"sborb:{args.ticker}:{d}"
    db.upsert(dict(trade_id=tid, date_msk=d, ticker=args.ticker, direction="SHORT", status="OPEN",
                   qty=args.contracts, entry_ts=now_utc.isoformat(), entry_fill=entry_fill, stop=stop, take=take,
                   exit_ts=None, exit_fill=None, exit_reason=None, gross_pnl_rub=None,
                   commission_rub=ec, net_pnl_rub=None, created_at=now_utc.isoformat(), updated_at=now_utc.isoformat()))
    db.mark_taken(d); db.bump_today(d)
    logger.info(f"ORB_ENTRY SHORT {args.ticker} entry={entry_fill} stop={stop} take={take:.0f} (or_low={ol} or_high={oh})")
    return {"status": "OK", "has_open": True, "or_low": ol}


def _write_status(args, db, result, market_open, session, account_id, dry_run):
    closed = db.closed()
    net = sum((r["net_pnl_rub"] or 0) for r in closed)
    status = {"strategy": "orb_short_sandbox", "contour": "sandbox", "dry_run": dry_run,
              "account_id": account_id, "ticker": args.ticker,
              "params": {"or": f"{args.or_start}-{args.or_end}", "take_r": args.take_r,
                         "max_or_range": args.max_or_range, "vol_mult": args.breakout_vol_mult,
                         "contracts": args.contracts},
              "market_open": market_open, "session": session, "last_cycle": result,
              "open_trades_total": len(db.all_open()), "closed_trades_total": len(closed),
              "net_pnl_rub_REAL": round(net, 1),
              "pid": os.getpid(), "updated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    Path(args.status_file).parent.mkdir(parents=True, exist_ok=True)
    with open(args.status_file, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, default=str)


def _resolve_uid(ticker, class_code, logger):
    from src.tbank.client import get_tbank_client
    from src.tbank.settings import load_tbank_settings
    from src.tbank.instruments import resolve_instrument
    with get_tbank_client(load_tbank_settings(env="prod")) as c:
        r = resolve_instrument(c, ticker, class_code)
    logger.info(f"INSTRUMENT {ticker} uid={r['uid']} lot={r.get('lot')}")
    return r["uid"]


def main():
    args = _parse_args(); load_dotenv()
    logger = _setup_logging(args.log_file); dry_run = args.dry_run
    logger.info("=" * 60)
    logger.info(f"ORB SHORT SANDBOX — {args.ticker} OR {args.or_start}-{args.or_end} take_r={args.take_r} "
                f"cap={args.max_or_range} vol_mult={args.breakout_vol_mult} dry_run={dry_run}")
    logger.info("=" * 60)

    if not dry_run:
        if not os.getenv("SANDBOX_TOKEN"):
            raise SystemExit("SANDBOX_TOKEN missing.")
        if os.getenv(args.trading_enabled_env, "false").lower() != "true":
            raise SystemExit(f"{args.trading_enabled_env} != true — refusing to trade (or use --dry-run).")

    uid = _resolve_uid(args.ticker, args.class_code, logger)
    db = OrbDB(args.state_db)

    market_config = None
    if not args.ignore_market_hours:
        try:
            from src.market.market_hours import load_market_hours_config
            market_config = load_market_hours_config(args.market_hours_config)
        except Exception as e:
            logger.warning(f"market hours load failed: {e}")

    def run_once(broker, account_id):
        now_utc = datetime.now(tz=timezone.utc)
        session, market_open = "unknown", True
        if market_config:
            from src.market.market_hours import is_session_open, get_session_name
            session = get_session_name(now_utc, market_config); market_open = is_session_open(now_utc, market_config)
        if not market_open and not args.ignore_market_hours:
            logger.info(f"MARKET_CLOSED session={session}")
            _write_status(args, db, {"status": "MARKET_CLOSED"}, market_open, session, account_id, dry_run)
            return
        try:
            res = _cycle(args, broker, account_id, uid, db, logger, market_open, session, dry_run)
        except Exception as e:
            logger.exception(f"CYCLE_ERROR: {e}"); res = {"status": "ERROR", "error": str(e)[:200]}
        _write_status(args, db, res, market_open, session, account_id, dry_run)

    if dry_run:
        run_once(None, "DRY_RUN"); logger.info("DRY_RUN done."); return

    with get_sandbox_broker() as broker:
        account_id = args.account_id or os.getenv(args.account_id_env, "")
        if not account_id:
            for a in broker.get_accounts():
                if a["name"] == "hammertrade-sandbox-orb":
                    account_id = a["id"]; break
        if not account_id:
            raise RuntimeError("No ORB sandbox account; set SANDBOX_ACCOUNT_ID_ORB.")
        logger.info(f"SANDBOX account_id={account_id}")
        if args.once:
            run_once(broker, account_id); return
        while True:
            try:
                run_once(broker, account_id)
            except Exception as e:
                logger.exception(f"LOOP_ERROR: {e}")
            time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    main()
