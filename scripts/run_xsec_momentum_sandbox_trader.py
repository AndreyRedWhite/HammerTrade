"""Cross-sectional 6-1 momentum portfolio in the T-Bank sandbox.

The service owns a dedicated sandbox account, ranks liquid MOEX equities on
daily closes, closes the previous basket and opens equal-notional long/short
legs.  All PnL uses actual sandbox fills and reported commission.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.market_data import fetch_recent_candles
from src.sandbox.broker import get_sandbox_broker

DEFAULT_UNIVERSE = (
    "SBER,SBERP,GAZP,LKOH,TATN,TATNP,ROSN,NVTK,GMKN,PLZL,MOEX,"
    "RTKM,RTKMP,SNGS,SNGSP,MTSS"
)


def _parse_args():
    p = argparse.ArgumentParser(description="D1 cross-sectional momentum SANDBOX trader")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--class-code", default="TQBR")
    p.add_argument("--lookback-days", type=int, default=126)
    p.add_argument("--skip-days", type=int, default=21)
    p.add_argument("--long-count", type=int, default=3)
    p.add_argument("--short-count", type=int, default=3)
    p.add_argument("--rebalance-interval-days", type=int, default=21)
    p.add_argument("--notional-per-name", type=float, default=1_000_000.0)
    p.add_argument("--history-minutes", type=int, default=400 * 24 * 60)
    p.add_argument("--account-id-env", default="SANDBOX_ACCOUNT_ID_XSEC")
    p.add_argument("--account-id")
    p.add_argument("--trading-enabled-env", default="SANDBOX_XSEC_ENABLED")
    p.add_argument("--state-db", default="data/sandbox/sandbox_xsec_momentum.sqlite")
    p.add_argument("--status-file", default="runtime/sandbox_status_XSEC_MOMENTUM.json")
    p.add_argument("--log-file", default="logs/sandbox_XSEC_MOMENTUM.log")
    p.add_argument("--poll-interval-seconds", type=int, default=3600)
    p.add_argument("--market-hours-config", default="configs/market_hours/moex_equities.yaml")
    p.add_argument("--ignore-market-hours", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--once", action="store_true")
    return p.parse_args()


def momentum_score(close: pd.Series, lookback: int = 126, skip: int = 21):
    """6-1 style return using only information available at the latest close."""
    clean = pd.to_numeric(close, errors="coerce").dropna()
    if lookback <= skip or len(clean) <= lookback:
        return None
    old = float(clean.iloc[-lookback - 1])
    recent = float(clean.iloc[-skip - 1])
    if old <= 0:
        return None
    return recent / old - 1.0


def select_basket(scores: dict[str, float], long_count: int, short_count: int):
    if long_count < 0 or short_count < 0 or long_count + short_count > len(scores):
        raise ValueError("invalid basket sizes")
    ranked = sorted(scores, key=scores.get)
    shorts = ranked[:short_count]
    longs = list(reversed(ranked[-long_count:])) if long_count else []
    return longs, shorts


def fill_price(total_rub, lots: int, lot_size: int):
    if total_rub is None or lots <= 0 or lot_size <= 0:
        return None
    return float(total_rub) / (lots * lot_size)


class XsecDB:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path); self.con.row_factory = sqlite3.Row
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS xsec_positions (
          ticker TEXT PRIMARY KEY, uid TEXT, direction TEXT, lots INTEGER, lot_size INTEGER,
          entry_fill REAL, entry_commission REAL, entry_ts TEXT, score REAL);
        CREATE TABLE IF NOT EXISTS xsec_trades (
          trade_id TEXT PRIMARY KEY, direction TEXT, status TEXT, entry_ts TEXT,
          exit_ts TEXT, gross_pnl_rub REAL, commission_rub REAL, net_pnl_rub REAL,
          details_json TEXT);
        CREATE TABLE IF NOT EXISTS xsec_state (
          strategy TEXT PRIMARY KEY, last_rebalance_date TEXT);
        CREATE TABLE IF NOT EXISTS xsec_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, message TEXT);
        """); self.con.commit()

    def positions(self):
        return self.con.execute("SELECT * FROM xsec_positions ORDER BY ticker").fetchall()

    def put_position(self, row):
        cols = list(row)
        self.con.execute(
            f"INSERT OR REPLACE INTO xsec_positions({','.join(cols)}) "
            f"VALUES({','.join('?' for _ in cols)})", [row[c] for c in cols]
        ); self.con.commit()

    def clear_positions(self):
        self.con.execute("DELETE FROM xsec_positions"); self.con.commit()

    def last_rebalance(self):
        r = self.con.execute(
            "SELECT last_rebalance_date FROM xsec_state WHERE strategy='momentum'"
        ).fetchone()
        return r[0] if r else None

    def set_rebalance(self, date):
        self.con.execute(
            "INSERT INTO xsec_state(strategy,last_rebalance_date) VALUES('momentum',?) "
            "ON CONFLICT(strategy) DO UPDATE SET last_rebalance_date=excluded.last_rebalance_date",
            (date,),
        ); self.con.commit()

    def add_trade(self, row):
        cols = list(row)
        self.con.execute(
            f"INSERT OR REPLACE INTO xsec_trades({','.join(cols)}) VALUES({','.join('?' for _ in cols)})",
            [row[c] for c in cols],
        ); self.con.commit()

    def open_trade(self):
        return self.con.execute(
            "SELECT * FROM xsec_trades WHERE status='OPEN' ORDER BY entry_ts DESC LIMIT 1"
        ).fetchone()

    def closed(self):
        return self.con.execute("SELECT * FROM xsec_trades WHERE status='CLOSED'").fetchall()

    def event(self, kind, message):
        self.con.execute("INSERT INTO xsec_events(ts,kind,message) VALUES(?,?,?)",
                         (datetime.now(tz=timezone.utc).isoformat(), kind, message)); self.con.commit()


def _log(path):
    log = logging.getLogger("xsec_sandbox"); log.setLevel(logging.INFO)
    if not log.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s [xsec] %(message)s")
        sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); log.addHandler(sh)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path); fh.setFormatter(fmt); log.addHandler(fh)
    return log


def _resolve(tickers, class_code, log):
    from src.tbank.client import get_tbank_client
    from src.tbank.instruments import resolve_instrument
    from src.tbank.settings import load_tbank_settings
    out = {}
    with get_tbank_client(load_tbank_settings("prod")) as client:
        for ticker in tickers:
            r = resolve_instrument(client, ticker, class_code)
            out[ticker] = {"uid": r["uid"], "lot": int(r.get("lot") or 1)}
            log.info(f"INSTRUMENT {ticker} lot={out[ticker]['lot']} uid={r['uid']}")
    return out


def _order(broker, account, uid, lots, lot_size, side, dry_run, expected, log):
    if dry_run:
        log.info(f"DRY_ORDER {side} lots={lots} expected={expected}")
        return expected, 0.0
    res = broker.post_order(
        account_id=account, instrument_uid=uid, quantity_lots=lots,
        direction=side, order_type="MARKET", idempotency_key=str(uuid.uuid4()),
    )
    filled = int(res.lots_executed or 0)
    px = fill_price(res.executed_price, filled, lot_size)
    if filled != lots or px is None:
        raise RuntimeError(f"partial/unpriced order: requested={lots} filled={filled}")
    log.info(f"ORDER {side} lots={lots} fill={px} commission={res.commission_rub}")
    return px, float(res.commission_rub or 0)


def completed_daily_bars(df: pd.DataFrame, session_date=None) -> pd.DataFrame:
    """Return bars known to be complete at the current trading session.

    MOEX can expose today's still-forming D1 candle during the main session.
    Signals and sizing must only use prior closes; otherwise the live decision
    differs from the research definition and changes throughout the day.
    """
    if session_date is None or df is None or df.empty:
        return df
    timestamps = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    dates = timestamps.dt.tz_convert(ZoneInfo("Europe/Moscow")).dt.date
    return df.loc[dates < session_date].copy()


def _fetch_scores(args, tickers, log, session_date=None):
    scores, prices, latest_dates = {}, {}, {}
    for ticker in tickers:
        try:
            df, _ = fetch_recent_candles(
                ticker, args.class_code, "1d", args.history_minutes, "prod"
            )
            if df is None or df.empty: continue
            df = df.sort_values("timestamp")
            df = completed_daily_bars(df, session_date)
            if df.empty: continue
            score = momentum_score(df.close, args.lookback_days, args.skip_days)
            if score is None: continue
            scores[ticker] = score
            prices[ticker] = float(df.close.iloc[-1])
            latest_dates[ticker] = pd.Timestamp(df.timestamp.iloc[-1]).date().isoformat()
        except Exception as exc:
            log.warning(f"DATA_SKIP {ticker}: {exc}")
    if not latest_dates:
        return scores, prices, None
    # Require the modal latest date and drop lagging instruments.
    common_date = pd.Series(list(latest_dates.values())).mode().iloc[0]
    for ticker in list(scores):
        if latest_dates[ticker] != common_date:
            scores.pop(ticker); prices.pop(ticker)
    return scores, prices, common_date


def _expected_positions(rows):
    return {r["uid"]: (r["lots"] * r["lot_size"] * (1 if r["direction"] == "LONG" else -1))
            for r in rows}


def _reconcile(broker, account, rows):
    expected = _expected_positions(rows)
    actual = {uid: 0 for uid in expected}
    for p in broker.get_positions(account):
        if p.instrument_uid in actual: actual[p.instrument_uid] = int(p.balance)
    mismatch = [(u, expected[u], actual[u]) for u in expected if expected[u] != actual[u]]
    return mismatch


def _rebalance(args, broker, account, db, instruments, scores, prices, date, log):
    old = [dict(r) for r in db.positions()]
    if not args.dry_run:
        mismatch = _reconcile(broker, account, old)
        if mismatch:
            detail = "; ".join(f"{u[:8]} exp={e} act={a}" for u, e, a in mismatch)
            db.event("RECONCILE_FAIL", detail)
            return {"status": "RECONCILE_FAILED", "detail": detail}

    gross = 0.0; commission = 0.0; details = []
    for pos in old:
        side = "SELL" if pos["direction"] == "LONG" else "BUY"
        expected = prices.get(pos["ticker"])
        if expected is None:
            return {"status": "MISSING_EXIT_PRICE", "ticker": pos["ticker"]}
        fill, comm = _order(broker, account, pos["uid"], pos["lots"], pos["lot_size"],
                            side, args.dry_run, expected, log)
        sign = 1 if pos["direction"] == "LONG" else -1
        pnl = sign * (fill - pos["entry_fill"]) * pos["lots"] * pos["lot_size"]
        gross += pnl; commission += float(pos["entry_commission"] or 0) + comm
        details.append({"ticker": pos["ticker"], "direction": pos["direction"],
                        "entry": pos["entry_fill"], "exit": fill, "gross": pnl})
    if old:
        now = datetime.now(tz=timezone.utc).isoformat()
        existing = db.open_trade()
        db.add_trade({
            "trade_id": existing["trade_id"] if existing else f"sbxsec:{db.last_rebalance()}",
            "direction": "NEUTRAL",
            "status": "CLOSED", "entry_ts": old[0]["entry_ts"], "exit_ts": now,
            "gross_pnl_rub": round(gross, 2), "commission_rub": round(commission, 2),
            "net_pnl_rub": round(gross-commission, 2),
            "details_json": json.dumps(details, ensure_ascii=False),
        })
    db.clear_positions()

    longs, shorts = select_basket(scores, args.long_count, args.short_count)
    opened = []
    for direction, names in (("LONG", longs), ("SHORT", shorts)):
        for ticker in names:
            meta = instruments[ticker]; price = prices[ticker]
            lots = max(1, math.floor(args.notional_per_name / (price * meta["lot"])))
            side = "BUY" if direction == "LONG" else "SELL"
            fill, comm = _order(broker, account, meta["uid"], lots, meta["lot"], side,
                                args.dry_run, price, log)
            row = {"ticker": ticker, "uid": meta["uid"], "direction": direction,
                   "lots": lots, "lot_size": meta["lot"], "entry_fill": fill,
                   "entry_commission": comm, "entry_ts": datetime.now(tz=timezone.utc).isoformat(),
                   "score": scores[ticker]}
            db.put_position(row); opened.append(f"{direction}:{ticker}:{lots}")
    now = datetime.now(tz=timezone.utc).isoformat()
    db.add_trade({
        "trade_id": f"sbxsec:{date}", "direction": "NEUTRAL", "status": "OPEN",
        "entry_ts": now, "details_json": json.dumps(opened, ensure_ascii=False),
    })
    db.set_rebalance(date)
    return {"status": "OK", "date": date, "opened": opened,
            "closed_net": round(gross-commission, 2) if old else None}


def _cycle(args, broker, account, db, instruments, tickers, log, session_date=None):
    scores, prices, date = _fetch_scores(args, tickers, log, session_date)
    if date is None or len(scores) < args.long_count + args.short_count:
        return {"status": "INSUFFICIENT_DATA", "names": len(scores)}
    last = db.last_rebalance()
    if last and (pd.Timestamp(date) - pd.Timestamp(last)).days < args.rebalance_interval_days:
        return {"status": "OK", "date": date, "rebalance": "NOT_DUE", "names": len(scores)}
    return _rebalance(args, broker, account, db, instruments, scores, prices, date, log)


def _status(args, db, result, account, market_open, session):
    closed = db.closed()
    data = {
        "strategy": "xsec_momentum_sandbox", "contour": "sandbox", "dry_run": args.dry_run,
        "ticker": "XSEC_BASKET", "direction": "NEUTRAL", "account_id": account,
        "market_open": market_open, "session": session, "fetch_status": result.get("status"),
        "last_cycle": result, "open_trades_total": 1 if db.open_trade() else 0,
        "closed_trades_total": len(closed),
        "net_pnl_rub_REAL": round(sum(float(r["net_pnl_rub"] or 0) for r in closed), 2),
        "params": {"lookback_days": args.lookback_days, "skip_days": args.skip_days,
                   "long_count": args.long_count, "short_count": args.short_count,
                   "rebalance_interval_days": args.rebalance_interval_days,
                   "notional_per_name": args.notional_per_name},
        "pid": os.getpid(), "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    p = Path(args.status_file); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(data, indent=2)); tmp.replace(p)


def main():
    args = _parse_args(); load_dotenv(); log = _log(args.log_file)
    if os.getenv("TINVEST_LIVE_TRADING_TOKEN"):
        raise SystemExit("live trading token present — refusing to run")
    if not args.dry_run:
        if not os.getenv("SANDBOX_TOKEN"): raise SystemExit("SANDBOX_TOKEN missing")
        if os.getenv(args.trading_enabled_env, "false").lower() != "true":
            raise SystemExit(f"{args.trading_enabled_env} != true")
    tickers = [t.strip().upper() for t in args.universe.split(",") if t.strip()]
    if args.long_count + args.short_count > len(tickers):
        raise SystemExit("basket is larger than universe")
    instruments = _resolve(tickers, args.class_code, log)
    db = XsecDB(args.state_db)
    market_cfg = None
    if not args.ignore_market_hours:
        from src.market.market_hours import load_market_hours_config
        market_cfg = load_market_hours_config(args.market_hours_config)

    def run(broker, account):
        now = datetime.now(tz=timezone.utc); market_open = True; session = "unknown"
        if market_cfg:
            from src.market.market_hours import get_session_name, is_session_open
            session = get_session_name(now, market_cfg); market_open = is_session_open(now, market_cfg)
        # Submit market orders only while the exchange is open. During the main
        # session, exclude today's incomplete D1 bar from ranking and sizing.
        result = {"status": "MARKET_CLOSED_WAIT"}
        if market_open or args.ignore_market_hours:
            session_date = None
            if market_open and not args.ignore_market_hours:
                session_date = now.astimezone(ZoneInfo("Europe/Moscow")).date()
            try:
                result = _cycle(
                    args, broker, account, db, instruments, tickers, log,
                    session_date=session_date,
                )
            except Exception as exc:
                log.exception("cycle failed"); result = {"status": "ERROR", "detail": str(exc)[:200]}
        _status(args, db, result, account, market_open, session)

    if args.dry_run:
        run(None, "DRY_RUN"); return
    with get_sandbox_broker() as broker:
        account = args.account_id or os.getenv(args.account_id_env, "")
        if not account: raise SystemExit(f"sandbox account missing; set {args.account_id_env}")
        while True:
            run(broker, account)
            if args.once: break
            time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    main()
