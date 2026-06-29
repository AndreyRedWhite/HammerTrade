"""Pairs stat-arb SANDBOX trading daemon — REAL fills on the T-Bank SANDBOX
contour (virtual money). Two legs per pair (ord/pref mean-reversion).

This is the ground-truth executor: unlike the paper trader it places actual
sandbox orders and records the broker's REAL fill prices and REAL commission,
so net PnL reflects true execution (spread crossing + commission) — the thing
paper cannot measure.

Strategy: spread = log(pref_close) - log(ord_close); z = rolling z-score.
  z >=  entry_z -> SHORT_SPREAD (SELL pref, BUY ord)
  z <= -entry_z -> LONG_SPREAD  (BUY  pref, SELL ord)
  exit when |z| <= exit_z (revert) | |z| >= stop_z (diverge) | bars_held >= max_hold

Safety:
  * sandbox contour only (SANDBOX_TOKEN); refuses to run without
    SANDBOX_TRADING_ENABLED=true unless --dry-run.
  * never leaves a one-legged position: if the 2nd entry leg fails, the 1st
    is immediately flattened.
  * daily trade cap; a pause flag that RESETS each MSK day (no sticky breaker).
"""
import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.market_data import fetch_recent_candles
from src.paper.pairs.engine import compute_spread_z
from src.sandbox.broker import get_sandbox_broker

DEFAULT_PAIRS = "TATNP:TATN@1h,RTKMP:RTKM@15m"


# ───────────────────────── args ─────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pairs stat-arb SANDBOX daemon (real sandbox fills, virtual money).")
    p.add_argument("--pairs", default=DEFAULT_PAIRS,
                   help="Comma list PREF:ORD@TF, e.g. TATNP:TATN@1h,RTKMP:RTKM@15m")
    p.add_argument("--class-code", default="TQBR")
    p.add_argument("--z-window", type=int, default=50)
    p.add_argument("--entry-z", type=float, default=2.0)
    p.add_argument("--exit-z", type=float, default=0.5)
    p.add_argument("--stop-z", type=float, default=4.0)
    p.add_argument("--max-hold-bars", type=int, default=60)
    p.add_argument("--notional-per-leg", type=float, default=20000.0)
    p.add_argument("--lookback-minutes", type=int, default=43200, help="History per leg (~30d)")
    p.add_argument("--account-id-env", default="SANDBOX_ACCOUNT_ID")
    p.add_argument("--account-id", default=None, help="Override sandbox account id")
    p.add_argument("--trading-enabled-env", default="SANDBOX_TRADING_ENABLED",
                   help="Env var that must be 'true' to place orders (isolate from other sandbox services)")
    p.add_argument("--max-trades-per-day", type=int, default=20)
    p.add_argument("--order-type", choices=["market", "limit"], default="market",
                   help="market = cross the spread (baseline); limit = passive @ bar-close, "
                        "poll+cancel, exits fall back to market. v1: validate vs market at open.")
    p.add_argument("--limit-timeout-sec", type=float, default=20.0,
                   help="How long to wait for a LIMIT leg to fill before cancel/abort (entry) "
                        "or market-fallback (exit).")
    p.add_argument("--limit-poll-sec", type=float, default=2.0)
    p.add_argument("--state-db", default="data/sandbox/sandbox_pairs.sqlite")
    p.add_argument("--status-file", default="runtime/sandbox_status_PAIRS.json")
    p.add_argument("--log-file", default="logs/sandbox_PAIRS.log")
    p.add_argument("--poll-interval-seconds", type=int, default=300)
    p.add_argument("--env", default="prod", help="Env for MARKET DATA (candles). Orders always sandbox.")
    p.add_argument("--market-hours-config", default="configs/market_hours/moex_equities.yaml")
    p.add_argument("--ignore-market-hours", action="store_true")
    p.add_argument("--api-timeout-sec", type=int, default=15)
    p.add_argument("--dry-run", action="store_true", help="Compute signals, log intended orders, place NONE.")
    p.add_argument("--once", action="store_true")
    return p.parse_args()


def _parse_pairs(spec: str, default_tf: str = "1h") -> list[tuple[str, str, str]]:
    out = []
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        tf = default_tf
        if "@" in tok:
            tok, tf = tok.split("@", 1)
        pref, ordn = tok.split(":")
        out.append((pref.strip(), ordn.strip(), tf.strip()))
    return out


def _setup_logging(log_file: str) -> logging.Logger:
    logger = logging.getLogger("pairs_sandbox")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [pairs_sandbox] %(message)s")
    if not logger.handlers:
        sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); logger.addHandler(sh)
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file); fh.setFormatter(fmt); logger.addHandler(fh)
    return logger


def _bar_minutes(tf: str) -> int:
    tf = tf.lower()
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("min"):
        return int(tf[:-3])
    if tf.endswith("m"):
        return int(tf[:-1])
    return 60


def _today_msk(now_utc: Optional[datetime] = None) -> str:
    now_utc = now_utc or datetime.now(tz=timezone.utc)
    return (now_utc + timedelta(hours=3)).strftime("%Y-%m-%d")


# ───────────────────────── persistence ─────────────────────────
class PairsDB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS pair_trades (
            trade_id TEXT PRIMARY KEY, pair TEXT, direction TEXT, status TEXT,
            entry_ts TEXT, entry_z REAL,
            pref_ticker TEXT, ord_ticker TEXT,
            pref_qty INTEGER, ord_qty INTEGER,
            pref_entry_fill REAL, ord_entry_fill REAL,
            pref_exit_fill REAL, ord_exit_fill REAL,
            commission_rub REAL, gross_pnl_rub REAL, net_pnl_rub REAL,
            exit_ts TEXT, exit_z REAL, exit_reason TEXT, bars_held INTEGER,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS pair_state (pair TEXT PRIMARY KEY, last_bar_ts TEXT);
        CREATE TABLE IF NOT EXISTS daily_risk (date_msk TEXT PRIMARY KEY,
            trades_today INTEGER DEFAULT 0, paused INTEGER DEFAULT 0, pause_reason TEXT);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, pair TEXT, kind TEXT, message TEXT);
        """)
        self.con.commit()

    def last_bar(self, pair: str) -> Optional[str]:
        r = self.con.execute("SELECT last_bar_ts FROM pair_state WHERE pair=?", (pair,)).fetchone()
        return r["last_bar_ts"] if r else None

    def set_last_bar(self, pair: str, ts: str):
        self.con.execute("INSERT INTO pair_state(pair,last_bar_ts) VALUES(?,?) "
                         "ON CONFLICT(pair) DO UPDATE SET last_bar_ts=excluded.last_bar_ts", (pair, ts))
        self.con.commit()

    def open_trade(self, pair: str) -> Optional[sqlite3.Row]:
        return self.con.execute("SELECT * FROM pair_trades WHERE pair=? AND status='OPEN' "
                                "ORDER BY entry_ts DESC LIMIT 1", (pair,)).fetchone()

    def upsert_trade(self, t: dict):
        cols = ",".join(t.keys()); ph = ",".join("?" * len(t))
        upd = ",".join(f"{k}=excluded.{k}" for k in t if k != "trade_id")
        self.con.execute(f"INSERT INTO pair_trades({cols}) VALUES({ph}) "
                         f"ON CONFLICT(trade_id) DO UPDATE SET {upd}", list(t.values()))
        self.con.commit()

    def event(self, pair: str, kind: str, msg: str):
        self.con.execute("INSERT INTO events(ts,pair,kind,message) VALUES(?,?,?,?)",
                         (datetime.now(tz=timezone.utc).isoformat(), pair, kind, msg))
        self.con.commit()

    def daily(self, date_msk: str) -> sqlite3.Row:
        r = self.con.execute("SELECT * FROM daily_risk WHERE date_msk=?", (date_msk,)).fetchone()
        if r is None:
            self.con.execute("INSERT INTO daily_risk(date_msk) VALUES(?)", (date_msk,))
            self.con.commit()
            r = self.con.execute("SELECT * FROM daily_risk WHERE date_msk=?", (date_msk,)).fetchone()
        return r

    def bump_trades_today(self, date_msk: str):
        self.con.execute("UPDATE daily_risk SET trades_today=trades_today+1 WHERE date_msk=?", (date_msk,))
        self.con.commit()

    def set_pause(self, date_msk: str, paused: bool, reason: str = ""):
        self.con.execute("UPDATE daily_risk SET paused=?, pause_reason=? WHERE date_msk=?",
                         (1 if paused else 0, reason, date_msk))
        self.con.commit()

    def all_closed(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM pair_trades WHERE status='CLOSED'").fetchall()

    def all_open(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM pair_trades WHERE status='OPEN'").fetchall()


# ───────────────────────── execution ─────────────────────────
def _qty_lots(notional: float, price: float, lot: int) -> int:
    lots = int(round(notional / (price * lot)))
    return max(lots, 1)


def _place(broker, account_id, uid, lots, side, dry_run, logger, tag,
           order_type="market", limit_price=None, timeout_sec=20.0, poll_sec=2.0,
           force_fill=False):
    """Place one order leg. Returns (avg_fill_price, total_commission, executed_lots).

    market: single MARKET order (crosses the spread).
    limit:  passive LIMIT @ limit_price; poll up to timeout_sec; cancel remainder.
            If force_fill (exits, which MUST close), market-fallback the unfilled remainder.
    """
    if dry_run:
        logger.info(f"DRY_ORDER {tag} side={side} type={order_type} price={limit_price} lots={lots}")
        return (limit_price if order_type == "limit" else None), 0.0, lots

    if order_type == "limit" and limit_price is not None:
        res = broker.post_order(account_id=account_id, instrument_uid=uid, quantity_lots=lots,
                                direction=side, order_type="LIMIT", price=limit_price,
                                idempotency_key=str(uuid.uuid4()))
        order_id = res.order_id
        filled = res.lots_executed or 0
        fill_px = res.executed_price
        comm = res.commission_rub or 0.0
        deadline = time.time() + timeout_sec
        while filled < lots and time.time() < deadline:
            time.sleep(poll_sec)
            st = broker.get_order_state(account_id, order_id)
            filled = st.lots_executed or filled
            fill_px = st.executed_price or fill_px
            comm = st.commission_rub or comm
        if filled < lots:
            try:
                broker.cancel_order(account_id, order_id)
            except Exception as e:
                logger.warning(f"CANCEL_FAIL {tag}: {e}")
            if force_fill and (lots - filled) > 0:
                m = broker.post_order(account_id=account_id, instrument_uid=uid,
                                      quantity_lots=lots - filled, direction=side,
                                      order_type="MARKET", idempotency_key=str(uuid.uuid4()))
                mf = m.lots_executed or 0
                if mf > 0:
                    mpx = m.executed_price or limit_price
                    fill_px = ((fill_px or mpx) * filled + mpx * mf) / max(filled + mf, 1)
                    comm += m.commission_rub or 0.0
                    filled += mf
                logger.info(f"LIMIT_TO_MARKET {tag} fallback mkt_filled={mf} px={m.executed_price}")
        logger.info(f"ORDER {tag} LIMIT@{limit_price} side={side} lots={lots} filled={filled} "
                    f"avg_px={fill_px} comm={comm}")
        return fill_px, comm, filled

    res = broker.post_order(account_id=account_id, instrument_uid=uid,
                            quantity_lots=lots, direction=side, order_type="MARKET",
                            idempotency_key=str(uuid.uuid4()))
    filled = res.lots_executed or 0
    logger.info(f"ORDER {tag} MARKET side={side} lots={lots} status={res.status} "
                f"filled={filled} price={res.executed_price} comm={res.commission_rub}")
    return res.executed_price, res.commission_rub, filled


def _open_pair(broker, account_id, db, logger, dry_run, *, pair, pref, ordn, direction,
               pref_uid, ord_uid, pref_lot, ord_lot, pref_px, ord_px, notional, z, ts,
               order_type="market", limit_timeout=20.0, limit_poll=2.0):
    """Enter a pair: two orders. Flattens the first leg if the second fails.
    In limit mode the legs are passive @ bar-close; an unfilled entry leg aborts (no force)."""
    pref_lots = _qty_lots(notional, pref_px, pref_lot)
    ord_lots = _qty_lots(notional, ord_px, ord_lot)
    # LONG_SPREAD: BUY pref, SELL ord.  SHORT_SPREAD: SELL pref, BUY ord.
    pref_side = "BUY" if direction == "LONG_SPREAD" else "SELL"
    ord_side = "SELL" if direction == "LONG_SPREAD" else "BUY"

    pf, pc, pfl = _place(broker, account_id, pref_uid, pref_lots, pref_side, dry_run, logger,
                         f"{pair}/ENTRY/pref", order_type=order_type, limit_price=pref_px,
                         timeout_sec=limit_timeout, poll_sec=limit_poll)
    if not dry_run and pfl < pref_lots:
        logger.error(f"ENTRY_LEG1_FAIL pair={pair} pref filled={pfl}/{pref_lots}; flattening")
        if pfl > 0:
            _place(broker, account_id, pref_uid, pfl, "SELL" if pref_side == "BUY" else "BUY",
                   dry_run, logger, f"{pair}/UNWIND/pref")
        db.event(pair, "ENTRY_ABORT", f"leg1 partial {pfl}/{pref_lots}")
        return None
    of, oc, ofl = _place(broker, account_id, ord_uid, ord_lots, ord_side, dry_run, logger,
                         f"{pair}/ENTRY/ord", order_type=order_type, limit_price=ord_px,
                         timeout_sec=limit_timeout, poll_sec=limit_poll)
    if not dry_run and ofl < ord_lots:
        logger.error(f"ENTRY_LEG2_FAIL pair={pair} ord filled={ofl}/{ord_lots}; flattening BOTH")
        _place(broker, account_id, pref_uid, pref_lots, "SELL" if pref_side == "BUY" else "BUY",
               dry_run, logger, f"{pair}/UNWIND/pref")
        if ofl > 0:
            _place(broker, account_id, ord_uid, ofl, "SELL" if ord_side == "BUY" else "BUY",
                   dry_run, logger, f"{pair}/UNWIND/ord")
        db.event(pair, "ENTRY_ABORT", f"leg2 partial {ofl}/{ord_lots}")
        return None

    now = datetime.now(tz=timezone.utc).isoformat()
    trade = dict(
        trade_id=f"sbpair:{pair}:{ts}", pair=pair, direction=direction, status="OPEN",
        entry_ts=str(ts), entry_z=float(z), pref_ticker=pref, ord_ticker=ordn,
        pref_qty=pref_lots * pref_lot, ord_qty=ord_lots * ord_lot,
        pref_entry_fill=pf if pf is not None else pref_px,
        ord_entry_fill=of if of is not None else ord_px,
        pref_exit_fill=None, ord_exit_fill=None,
        commission_rub=(pc or 0) + (oc or 0), gross_pnl_rub=None, net_pnl_rub=None,
        exit_ts=None, exit_z=None, exit_reason=None, bars_held=0,
        created_at=now, updated_at=now,
    )
    db.upsert_trade(trade)
    logger.info(f"PAIR_ENTRY {direction} pair={pair} z={z:.2f} pref={pref}@{trade['pref_entry_fill']} "
                f"ord={ordn}@{trade['ord_entry_fill']} comm={trade['commission_rub']:.2f}")
    return trade


def _close_pair(broker, account_id, db, logger, dry_run, *, t, pref_uid, ord_uid,
                pref_lot, ord_lot, pref_px, ord_px, z, ts, reason,
                order_type="market", limit_timeout=20.0, limit_poll=2.0):
    direction = t["direction"]
    pref_lots = t["pref_qty"] // pref_lot
    ord_lots = t["ord_qty"] // ord_lot
    # reverse of entry
    pref_side = "SELL" if direction == "LONG_SPREAD" else "BUY"
    ord_side = "BUY" if direction == "LONG_SPREAD" else "SELL"
    # exits MUST close → force_fill (limit then market-fallback)
    pf, pc, _ = _place(broker, account_id, pref_uid, pref_lots, pref_side, dry_run, logger,
                       f"{t['pair']}/EXIT/pref", order_type=order_type, limit_price=pref_px,
                       timeout_sec=limit_timeout, poll_sec=limit_poll, force_fill=True)
    of, oc, _ = _place(broker, account_id, ord_uid, ord_lots, ord_side, dry_run, logger,
                       f"{t['pair']}/EXIT/ord", order_type=order_type, limit_price=ord_px,
                       timeout_sec=limit_timeout, poll_sec=limit_poll, force_fill=True)
    pref_exit = pf if pf is not None else pref_px
    ord_exit = of if of is not None else ord_px

    pref_sh, ord_sh = t["pref_qty"], t["ord_qty"]
    if direction == "LONG_SPREAD":
        pref_pnl = (pref_exit - t["pref_entry_fill"]) * pref_sh
        ord_pnl = (t["ord_entry_fill"] - ord_exit) * ord_sh
    else:
        pref_pnl = (t["pref_entry_fill"] - pref_exit) * pref_sh
        ord_pnl = (ord_exit - t["ord_entry_fill"]) * ord_sh
    gross = pref_pnl + ord_pnl
    commission = (t["commission_rub"] or 0) + (pc or 0) + (oc or 0)
    net = gross - commission

    now = datetime.now(tz=timezone.utc).isoformat()
    upd = dict(t)
    upd.update(status="CLOSED", pref_exit_fill=pref_exit, ord_exit_fill=ord_exit,
               commission_rub=commission, gross_pnl_rub=round(gross, 2), net_pnl_rub=round(net, 2),
               exit_ts=str(ts), exit_z=float(z), exit_reason=reason, updated_at=now)
    db.upsert_trade(upd)
    logger.info(f"PAIR_EXIT {direction} pair={t['pair']} reason={reason} z={z:.2f} "
                f"held={t['bars_held']} gross={gross:.1f} comm={commission:.2f} NET={net:.1f}")
    return upd


# ───────────────────────── reconciliation ─────────────────────────
def _reconcile(broker, account_id, open_t, pref_i, ord_i, pref_lot, ord_lot):
    """Compare expected positions (from the journal) vs actual (sandbox account) for
    THIS pair's two legs only. Disjoint instruments → safe on a shared account.
    Returns (ok: bool, detail: str). Positions are signed lot balances."""
    exp = {pref_i["uid"]: 0, ord_i["uid"]: 0}
    if open_t is not None and str(open_t.get("status")) == "OPEN":
        d = open_t["direction"]
        pl = int(open_t["pref_qty"]) // pref_lot
        ol = int(open_t["ord_qty"]) // ord_lot
        exp[pref_i["uid"]] = pl if d == "LONG_SPREAD" else -pl
        exp[ord_i["uid"]] = -ol if d == "LONG_SPREAD" else ol
    figi_to_uid = {i["figi"]: i["uid"] for i in (pref_i, ord_i) if i.get("figi")}
    actual = {pref_i["uid"]: 0, ord_i["uid"]: 0}
    for p in broker.get_positions(account_id):
        uid = p.instrument_uid or figi_to_uid.get(p.figi)
        if uid in actual:
            actual[uid] = int(p.balance)
    mism = [(u, exp[u], actual[u]) for u in exp if exp[u] != actual[u]]
    if mism:
        return False, "; ".join(f"uid={u[:8]} exp_lots={e} act_lots={a}" for u, e, a in mism)
    return True, "OK"


# ───────────────────────── per-pair cycle ─────────────────────────
def _process_pair(args, broker, account_id, db, logger, instruments, now_utc,
                  pref, ordn, tf, dry_run):
    pair = ordn
    pref_i, ord_i = instruments[pref], instruments[ordn]
    pref_df, _ = fetch_recent_candles(pref, args.class_code, tf, args.lookback_minutes, args.env)
    ord_df, _ = fetch_recent_candles(ordn, args.class_code, tf, args.lookback_minutes, args.env)
    if pref_df is None or ord_df is None or pref_df.empty or ord_df.empty:
        return {"pair": pair, "status": "NO_CANDLES"}

    pdf = compute_spread_z(pref_df, ord_df, timeframe="1min", z_window=args.z_window)
    horizon = now_utc - timedelta(minutes=_bar_minutes(tf))
    pdf = pdf[pdf["timestamp"] <= horizon].reset_index(drop=True)
    if pdf.empty or pd.isna(pdf["z"].iloc[-1]):
        return {"pair": pair, "status": "NO_CLOSED_BARS"}

    last = db.last_bar(pair)
    last_ts = pd.Timestamp(last).tz_convert("UTC") if last else None
    new_bars = pdf[pdf["timestamp"] > last_ts] if last_ts is not None else pdf.tail(1)

    open_t = db.open_trade(pair)
    open_t = dict(open_t) if open_t is not None else None
    latest_z = float(pdf["z"].iloc[-1])

    # Position reconciliation: journal vs real account (skip in dry-run). On any
    # mismatch, HALT this pair (no new entries/exits) and alert — manual fix needed.
    if not dry_run:
        ok, detail = _reconcile(broker, account_id, open_t, pref_i, ord_i,
                                pref_i["lot"], ord_i["lot"])
        if not ok:
            logger.error(f"RECONCILE_FAIL pair={pair} {detail}")
            db.event(pair, "RECONCILE_FAIL", detail)
            return {"pair": pair, "status": "RECONCILE_FAILED", "detail": detail,
                    "latest_z": round(latest_z, 3), "has_open": open_t is not None}

    date_msk = _today_msk(now_utc)
    daily = db.daily(date_msk)

    for _, bar in new_bars.iterrows():
        z = float(bar["z"]); ts = pd.Timestamp(bar["timestamp"]).isoformat()
        pref_px, ord_px = float(bar["pref_close"]), float(bar["ord_close"])

        if open_t is None:
            if daily["paused"]:
                pass
            elif daily["trades_today"] >= args.max_trades_per_day:
                logger.info(f"DAILY_CAP pair={pair} trades_today={daily['trades_today']}")
            else:
                direction = "SHORT_SPREAD" if z >= args.entry_z else ("LONG_SPREAD" if z <= -args.entry_z else None)
                if direction:
                    t = _open_pair(broker, account_id, db, logger, dry_run, pair=pair, pref=pref, ordn=ordn,
                                   direction=direction, pref_uid=pref_i["uid"], ord_uid=ord_i["uid"],
                                   pref_lot=pref_i["lot"], ord_lot=ord_i["lot"], pref_px=pref_px, ord_px=ord_px,
                                   notional=args.notional_per_leg, z=z, ts=ts,
                                   order_type=args.order_type, limit_timeout=args.limit_timeout_sec,
                                   limit_poll=args.limit_poll_sec)
                    if t is not None:
                        open_t = t
                        db.bump_trades_today(date_msk)
                        daily = db.daily(date_msk)
        else:
            open_t["bars_held"] = (open_t["bars_held"] or 0) + 1
            db.upsert_trade(open_t)
            reason = None
            if abs(z) <= args.exit_z:
                reason = "EXIT_MEAN"
            elif abs(z) >= args.stop_z:
                reason = "STOP_DIVERGE"
            elif open_t["bars_held"] >= args.max_hold_bars:
                reason = "TIME"
            if reason:
                _close_pair(broker, account_id, db, logger, dry_run, t=open_t,
                            pref_uid=pref_i["uid"], ord_uid=ord_i["uid"],
                            pref_lot=pref_i["lot"], ord_lot=ord_i["lot"],
                            pref_px=pref_px, ord_px=ord_px, z=z, ts=ts, reason=reason,
                            order_type=args.order_type, limit_timeout=args.limit_timeout_sec,
                            limit_poll=args.limit_poll_sec)
                open_t = None

        db.set_last_bar(pair, ts)

    latest_z = float(pdf["z"].iloc[-1])
    return {"pair": pair, "status": "OK", "latest_z": round(latest_z, 3), "has_open": open_t is not None,
            "tf": tf}


def _write_status(args, db, pair_results, market_open, session, fetch_status, account_id, dry_run):
    closed = db.all_closed()
    net = sum((r["net_pnl_rub"] or 0) for r in closed)
    gross = sum((r["gross_pnl_rub"] or 0) for r in closed)
    comm = sum((r["commission_rub"] or 0) for r in closed)
    wins = sum(1 for r in closed if (r["net_pnl_rub"] or 0) > 0)
    status = {
        "strategy": "pairs_statarb_sandbox", "contour": "sandbox", "dry_run": dry_run,
        "account_id": account_id, "pairs": args.pairs,
        "params": {"z_window": args.z_window, "entry_z": args.entry_z, "exit_z": args.exit_z,
                   "stop_z": args.stop_z, "max_hold_bars": args.max_hold_bars,
                   "notional_per_leg": args.notional_per_leg, "order_type": args.order_type},
        "market_open": market_open, "session": session, "fetch_status": fetch_status,
        "per_pair": pair_results, "open_trades_total": len(db.all_open()),
        "closed_trades_total": len(closed), "wins": wins,
        "net_pnl_rub_REAL": round(net, 1), "gross_pnl_rub_REAL": round(gross, 1),
        "commission_rub_REAL": round(comm, 1),
        "pid": os.getpid(), "updated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    Path(args.status_file).parent.mkdir(parents=True, exist_ok=True)
    with open(args.status_file, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, default=str)


# ───────────────────────── main ─────────────────────────
def _resolve_account(args, broker, logger) -> str:
    if args.account_id:
        return args.account_id
    env_id = os.getenv(args.account_id_env, "")
    if env_id:
        return env_id
    accts = broker.get_accounts()
    for a in accts:
        if a["name"] == "hammertrade-sandbox":
            logger.info(f"Using sandbox account '{a['name']}' id={a['id']}")
            return a["id"]
    if accts:
        return accts[0]["id"]
    raise RuntimeError("No sandbox account found; run scripts/sandbox_account_setup.py")


def _resolve_instruments(pairs, class_code, logger) -> dict:
    from src.tbank.client import get_tbank_client
    from src.tbank.settings import load_tbank_settings
    from src.tbank.instruments import resolve_instrument
    tickers = sorted({t for pr in pairs for t in pr[:2]})
    out = {}
    with get_tbank_client(load_tbank_settings(env="prod")) as c:
        for t in tickers:
            r = resolve_instrument(c, t, class_code)
            out[t] = {"uid": r["uid"], "figi": r.get("figi"), "lot": int(r.get("lot", 1) or 1)}
            logger.info(f"INSTRUMENT {t} uid={out[t]['uid']} lot={out[t]['lot']}")
    return out


def main():
    args = _parse_args()
    load_dotenv()
    logger = _setup_logging(args.log_file)
    dry_run = args.dry_run

    logger.info("=" * 60)
    logger.info("Pairs Stat-Arb SANDBOX Trader — SANDBOX contour (virtual money)")
    logger.info(f"  pairs={args.pairs} dry_run={dry_run}")
    logger.info(f"  z_window={args.z_window} entry_z={args.entry_z} exit_z={args.exit_z} "
                f"stop_z={args.stop_z} max_hold={args.max_hold_bars} notional/leg={args.notional_per_leg}")
    logger.info("=" * 60)

    if not dry_run:
        if not os.getenv("SANDBOX_TOKEN"):
            raise SystemExit("SANDBOX_TOKEN missing — refusing to place sandbox orders.")
        if os.getenv(args.trading_enabled_env, "false").lower() != "true":
            raise SystemExit(f"{args.trading_enabled_env} != true — refusing to trade. "
                             f"Set it to 'true' to place sandbox orders, or use --dry-run.")

    pairs = _parse_pairs(args.pairs)
    instruments = _resolve_instruments(pairs, args.class_code, logger)
    db = PairsDB(args.state_db)

    market_config = None
    if not args.ignore_market_hours:
        try:
            from src.market.market_hours import load_market_hours_config
            market_config = load_market_hours_config(args.market_hours_config)
        except Exception as e:
            logger.warning(f"market hours config load failed: {e}; running without gate")

    def cycle():
        now_utc = datetime.now(tz=timezone.utc)
        session, market_open = "unknown", True
        if market_config:
            from src.market.market_hours import is_session_open, get_session_name
            session = get_session_name(now_utc, market_config)
            market_open = is_session_open(now_utc, market_config)
        if not market_open and not args.ignore_market_hours:
            logger.info(f"MARKET_CLOSED session={session}")
            _write_status(args, db, [], market_open, session, "MARKET_CLOSED",
                          getattr(cycle, "account_id", None), dry_run)
            return
        results = []
        for pref, ordn, tf in pairs:
            try:
                results.append(_process_pair(args, cycle.broker, cycle.account_id, db, logger,
                                             instruments, now_utc, pref, ordn, tf, dry_run))
            except Exception as e:
                logger.exception(f"PAIR_ERROR {ordn}: {e}")
                results.append({"pair": ordn, "status": "ERROR", "error": str(e)[:200]})
        _write_status(args, db, results, market_open, session, "OK", cycle.account_id, dry_run)

    if dry_run:
        # dry-run: no broker connection needed for order placement, but we still read account for context
        cycle.broker = None
        cycle.account_id = "DRY_RUN"
        # need a broker for market data? No — candles via fetch_recent_candles (prod). Orders skipped.
        cycle()
        logger.info("DRY_RUN cycle complete.")
        return

    with get_sandbox_broker() as broker:
        cycle.broker = broker
        cycle.account_id = _resolve_account(args, broker, logger)
        logger.info(f"SANDBOX account_id={cycle.account_id}")
        if args.once:
            cycle()
            return
        while True:
            try:
                cycle()
            except Exception as e:
                logger.exception(f"CYCLE_ERROR: {e}")
            time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    main()
