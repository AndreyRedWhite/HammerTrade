"""Low-turnover volatility-breakout trader for the T-Bank sandbox.

Market data comes from the read-only production contour; orders are sent only
to ``client.sandbox``.  The service refuses to start without its dedicated
enable flag and refuses whenever a live-trading token is present.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.market_data import fetch_recent_candles
from src.sandbox.broker import get_sandbox_broker
from src.strategies.volatility_breakout import (
    VolatilityBreakoutConfig,
    prepare_breakout_frame,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Volatility-breakout SANDBOX trader")
    p.add_argument("--ticker", default="IMOEXF")
    p.add_argument("--class-code", default="SPBFUT")
    p.add_argument("--timeframe", choices=["15m", "1h"], default="1h")
    p.add_argument("--direction", choices=["BOTH", "LONG", "SHORT"], default="BOTH")
    p.add_argument("--atr-window", type=int, default=14)
    p.add_argument("--channel-window", type=int, default=20)
    p.add_argument("--compression-lookback", type=int, default=100)
    p.add_argument("--compression-quantile", type=float, default=0.25)
    p.add_argument("--compression-recent-bars", type=int, default=5)
    p.add_argument("--exit-channel-window", type=int, default=10)
    p.add_argument("--stop-atr", type=float, default=2.0)
    p.add_argument("--take-r", type=float, default=3.0)
    p.add_argument("--contracts", type=int, default=10)
    p.add_argument("--lookback-minutes", type=int, default=180 * 24 * 60)
    p.add_argument("--account-id-env", default="SANDBOX_ACCOUNT_ID_VOLBREAK")
    p.add_argument("--account-id")
    p.add_argument("--trading-enabled-env", default="SANDBOX_VOLBREAK_ENABLED")
    p.add_argument("--state-db", default="data/sandbox/sandbox_volbreak.sqlite")
    p.add_argument("--status-file", default="runtime/sandbox_status_VOLBREAK.json")
    p.add_argument("--log-file", default="logs/sandbox_VOLBREAK.log")
    p.add_argument("--poll-interval-seconds", type=int, default=300)
    p.add_argument("--market-hours-config", default="configs/market_hours/moex_futures.yaml")
    p.add_argument("--ignore-market-hours", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--once", action="store_true")
    return p.parse_args()


def _logger(path: str) -> logging.Logger:
    log = logging.getLogger("volbreak_sandbox")
    log.setLevel(logging.INFO)
    if not log.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s [volbreak] %(message)s")
        sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); log.addHandler(sh)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path); fh.setFormatter(fmt); log.addHandler(fh)
    return log


class BreakoutDB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS volatility_breakout_trades (
          trade_id TEXT PRIMARY KEY, ticker TEXT, direction TEXT, status TEXT,
          qty INTEGER, entry_ts TEXT, entry_fill REAL, signal_atr REAL,
          stop REAL, take REAL, exit_ts TEXT, exit_fill REAL, exit_reason TEXT,
          gross_pnl_rub REAL, commission_rub REAL, net_pnl_rub REAL,
          created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS volatility_breakout_state (
          ticker TEXT PRIMARY KEY, last_bar_ts TEXT);
        CREATE TABLE IF NOT EXISTS volatility_breakout_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, message TEXT);
        """)
        self.con.commit()

    def open_trade(self, ticker: str):
        return self.con.execute(
            "SELECT * FROM volatility_breakout_trades WHERE ticker=? AND status='OPEN' "
            "ORDER BY entry_ts DESC LIMIT 1", (ticker,)
        ).fetchone()

    def upsert(self, row: dict) -> None:
        cols = list(row)
        update = ",".join(f"{c}=excluded.{c}" for c in cols if c != "trade_id")
        self.con.execute(
            f"INSERT INTO volatility_breakout_trades({','.join(cols)}) "
            f"VALUES({','.join('?' for _ in cols)}) ON CONFLICT(trade_id) DO UPDATE SET {update}",
            [row[c] for c in cols],
        )
        self.con.commit()

    def last_bar(self, ticker: str):
        r = self.con.execute(
            "SELECT last_bar_ts FROM volatility_breakout_state WHERE ticker=?", (ticker,)
        ).fetchone()
        return r["last_bar_ts"] if r else None

    def set_last_bar(self, ticker: str, ts: str) -> None:
        self.con.execute(
            "INSERT INTO volatility_breakout_state(ticker,last_bar_ts) VALUES(?,?) "
            "ON CONFLICT(ticker) DO UPDATE SET last_bar_ts=excluded.last_bar_ts", (ticker, ts)
        )
        self.con.commit()

    def closed(self):
        return self.con.execute(
            "SELECT * FROM volatility_breakout_trades WHERE status='CLOSED'"
        ).fetchall()

    def event(self, kind: str, message: str) -> None:
        self.con.execute(
            "INSERT INTO volatility_breakout_events(ts,kind,message) VALUES(?,?,?)",
            (datetime.now(tz=timezone.utc).isoformat(), kind, message),
        )
        self.con.commit()


def fill_points(total_rub, lots: int, point_value_rub: float):
    """Convert T-Bank's total executed RUB value to points per contract."""
    if total_rub is None or lots <= 0 or point_value_rub <= 0:
        return None
    return float(total_rub) / (lots * point_value_rub)


def _order(broker, account_id, uid, lots, side, point_value, dry_run, expected, log):
    if dry_run:
        log.info(f"DRY_ORDER side={side} lots={lots} expected={expected:.4f}")
        return expected, 0.0, lots
    res = broker.post_order(
        account_id=account_id, instrument_uid=uid, quantity_lots=lots,
        direction=side, order_type="MARKET", idempotency_key=str(uuid.uuid4()),
    )
    filled = int(res.lots_executed or 0)
    px = fill_points(res.executed_price, filled, point_value)
    log.info(f"ORDER side={side} requested={lots} filled={filled} fill={px} "
             f"commission={res.commission_rub}")
    if filled != lots or px is None:
        raise RuntimeError(f"order not fully filled: requested={lots} filled={filled} fill={px}")
    return px, float(res.commission_rub or 0), filled


def _actual_qty(broker, account_id: str, uid: str) -> int:
    for p in broker.get_positions(account_id):
        if p.instrument_uid == uid:
            return int(p.balance)
    return 0


def _resolve(args, log):
    from src.tbank.client import get_tbank_client
    from src.tbank.instrument_specs import fetch_future_spec
    from src.tbank.settings import load_tbank_settings
    with get_tbank_client(load_tbank_settings("prod")) as client:
        spec = fetch_future_spec(client, args.ticker, args.class_code)
    if not spec.point_value_rub or spec.point_value_rub <= 0:
        raise RuntimeError(f"point_value_rub unavailable for {args.ticker}; refusing to price PnL")
    log.info(f"INSTRUMENT {args.ticker} uid={spec.uid} pv={spec.point_value_rub}")
    return spec.uid, float(spec.point_value_rub)


def _cycle(args, broker, account_id, uid, point_value, db, log):
    df, _ = fetch_recent_candles(
        args.ticker, args.class_code, args.timeframe, args.lookback_minutes, "prod"
    )
    if df is None or df.empty:
        return {"status": "NO_CANDLES"}
    cfg = VolatilityBreakoutConfig(
        atr_window=args.atr_window, channel_window=args.channel_window,
        compression_lookback=args.compression_lookback,
        compression_quantile=args.compression_quantile,
        compression_recent_bars=args.compression_recent_bars,
        exit_channel_window=args.exit_channel_window,
        stop_atr=args.stop_atr, take_r=args.take_r,
    )
    frame = prepare_breakout_frame(df, cfg)
    bar = frame.iloc[-1]
    ts = pd.Timestamp(bar.timestamp).isoformat()
    open_row = db.open_trade(args.ticker)
    trade = dict(open_row) if open_row else None

    if not args.dry_run:
        expected = 0
        if trade:
            expected = trade["qty"] if trade["direction"] == "LONG" else -trade["qty"]
        actual = _actual_qty(broker, account_id, uid)
        if actual != expected:
            detail = f"expected_qty={expected} actual_qty={actual}"
            db.event("RECONCILE_FAIL", detail)
            return {"status": "RECONCILE_FAILED", "detail": detail}

    # Exits are evaluated even when this bar was already seen, allowing an
    # operator restart to complete a previously failed exit.
    if trade:
        direction = trade["direction"]
        reason = None
        if direction == "LONG":
            if float(bar.low) <= trade["stop"]: reason = "STOP"
            elif float(bar.high) >= trade["take"]: reason = "TAKE"
            elif pd.notna(bar.exit_low) and float(bar.close) < float(bar.exit_low): reason = "CHANNEL"
            side = "SELL"
        else:
            if float(bar.high) >= trade["stop"]: reason = "STOP"
            elif float(bar.low) <= trade["take"]: reason = "TAKE"
            elif pd.notna(bar.exit_high) and float(bar.close) > float(bar.exit_high): reason = "CHANNEL"
            side = "BUY"
        if reason:
            expected = trade["stop"] if reason == "STOP" else (
                trade["take"] if reason == "TAKE" else float(bar.close)
            )
            fill, comm, _ = _order(
                broker, account_id, uid, trade["qty"], side, point_value,
                args.dry_run, expected, log,
            )
            sign = 1 if direction == "LONG" else -1
            gross = sign * (fill - trade["entry_fill"]) * point_value * trade["qty"]
            total_comm = float(trade["commission_rub"] or 0) + comm
            trade.update(
                status="CLOSED", exit_ts=datetime.now(tz=timezone.utc).isoformat(),
                exit_fill=fill, exit_reason=reason, gross_pnl_rub=round(gross, 2),
                commission_rub=round(total_comm, 2), net_pnl_rub=round(gross-total_comm, 2),
                updated_at=datetime.now(tz=timezone.utc).isoformat(),
            )
            db.upsert(trade)
            log.info(f"EXIT {direction} reason={reason} net={trade['net_pnl_rub']:+.2f}")
            trade = None

    last_ts = db.last_bar(args.ticker)
    is_new = last_ts is None or pd.Timestamp(ts) > pd.Timestamp(last_ts)
    if trade is None and is_new and pd.notna(bar.atr):
        direction = None
        if args.direction in ("BOTH", "LONG") and bool(bar.long_signal): direction = "LONG"
        elif args.direction in ("BOTH", "SHORT") and bool(bar.short_signal): direction = "SHORT"
        if direction:
            expected = float(bar.close)
            side = "BUY" if direction == "LONG" else "SELL"
            fill, comm, filled = _order(
                broker, account_id, uid, args.contracts, side, point_value,
                args.dry_run, expected, log,
            )
            risk = args.stop_atr * float(bar.atr)
            stop = fill - risk if direction == "LONG" else fill + risk
            take = fill + args.take_r*risk if direction == "LONG" else fill - args.take_r*risk
            now = datetime.now(tz=timezone.utc).isoformat()
            trade = dict(
                trade_id=f"sbvol:{args.ticker}:{ts}:{direction}", ticker=args.ticker,
                direction=direction, status="OPEN", qty=filled, entry_ts=ts,
                entry_fill=fill, signal_atr=float(bar.atr), stop=stop, take=take,
                exit_ts=None, exit_fill=None, exit_reason=None, gross_pnl_rub=None,
                commission_rub=comm, net_pnl_rub=None, created_at=now, updated_at=now,
            )
            db.upsert(trade)
            log.info(f"ENTRY {direction} fill={fill:.4f} stop={stop:.4f} take={take:.4f}")
    if is_new:
        db.set_last_bar(args.ticker, ts)
    return {"status": "OK", "bar": ts, "has_open": trade is not None,
            "long_signal": bool(bar.long_signal), "short_signal": bool(bar.short_signal)}


def _write_status(args, db, result, market_open, session, account_id, point_value):
    closed = db.closed()
    status = {
        "strategy": "volatility_breakout_sandbox", "contour": "sandbox",
        "ticker": args.ticker, "direction": args.direction, "account_id": account_id,
        "dry_run": args.dry_run, "market_open": market_open, "session": session,
        "fetch_status": result.get("status"), "last_cycle": result,
        "params": {"timeframe": args.timeframe, "channel_window": args.channel_window,
                   "compression_quantile": args.compression_quantile,
                   "stop_atr": args.stop_atr, "take_r": args.take_r,
                   "contracts": args.contracts, "point_value_rub": point_value},
        "open_trades_total": 1 if db.open_trade(args.ticker) else 0,
        "closed_trades_total": len(closed),
        "net_pnl_rub_REAL": round(sum(float(r["net_pnl_rub"] or 0) for r in closed), 2),
        "pid": os.getpid(), "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    p = Path(args.status_file); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(status, indent=2)); tmp.replace(p)


def main() -> None:
    args = _parse_args(); load_dotenv(); log = _logger(args.log_file)
    if os.getenv("TINVEST_LIVE_TRADING_TOKEN"):
        raise SystemExit("live trading token present — refusing to run")
    if not args.dry_run:
        if not os.getenv("SANDBOX_TOKEN"):
            raise SystemExit("SANDBOX_TOKEN missing")
        if os.getenv(args.trading_enabled_env, "false").lower() != "true":
            raise SystemExit(f"{args.trading_enabled_env} != true")
    uid, point_value = _resolve(args, log)
    db = BreakoutDB(args.state_db)
    market_cfg = None
    if not args.ignore_market_hours:
        from src.market.market_hours import load_market_hours_config
        market_cfg = load_market_hours_config(args.market_hours_config)

    def run(broker, account):
        now = datetime.now(tz=timezone.utc); market_open = True; session = "unknown"
        if market_cfg:
            from src.market.market_hours import get_session_name, is_session_open
            session = get_session_name(now, market_cfg); market_open = is_session_open(now, market_cfg)
        result = {"status": "MARKET_CLOSED"}
        if market_open or args.ignore_market_hours:
            try: result = _cycle(args, broker, account, uid, point_value, db, log)
            except Exception as exc:
                log.exception("cycle failed"); result = {"status": "ERROR", "detail": str(exc)[:200]}
        _write_status(args, db, result, market_open, session, account, point_value)

    if args.dry_run:
        run(None, "DRY_RUN")
        return
    with get_sandbox_broker() as broker:
        account = args.account_id or os.getenv(args.account_id_env, "")
        if not account:
            raise SystemExit(f"sandbox account missing; set {args.account_id_env}")
        while True:
            run(broker, account)
            if args.once: break
            time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    main()
