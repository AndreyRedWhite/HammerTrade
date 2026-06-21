"""VWAP Reversion Paper Trading Daemon — polls T-Bank API, tracks virtual SHORT trades.

No real or sandbox orders are placed. Uses READONLY_TOKEN only.
Tracks both theoretical fill (signal candle close) and market fill (next candle open)
for slippage analysis.
"""
import argparse
import concurrent.futures
import logging
import os
import sys
import time
from datetime import datetime, timezone, time as dtime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.vwap_reversion.engine import process_candle_vwap
from src.paper.vwap_reversion.models import VwapDailyContext, VwapTradeStatus
from src.paper.vwap_reversion.repository import VwapRepository


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="VWAP Reversion Paper trading daemon. No real orders. READONLY_TOKEN only."
    )
    p.add_argument("--ticker", default="SiU6")
    p.add_argument("--class-code", default="SPBFUT")
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--distance-mult", type=float, default=1.0,
                   help="ATR multiples above VWAP for signal")
    p.add_argument("--stop-mult", type=float, default=1.0,
                   help="ATR multiples for stop placement above entry")
    p.add_argument("--take-r", type=float, default=1.5,
                   help="Risk multiple for take profit")
    p.add_argument("--atr-window", type=int, default=14)
    p.add_argument("--max-trades-per-day", type=int, default=3)
    p.add_argument("--point-value-rub", type=float, default=10.0)
    p.add_argument("--commission-rub", type=float, default=0.05)
    p.add_argument("--state-db", default="data/paper/paper_state_siu6_vwap_reversion.sqlite")
    p.add_argument("--status-file", default="runtime/paper_status_SiU6_VWAP_REVERSION.json")
    p.add_argument("--csv-output", default="out/paper/paper_trades_SiU6_VWAP_REVERSION.csv")
    p.add_argument("--log-file", default="logs/paper_SiU6_VWAP_REVERSION.log")
    p.add_argument("--experiment-name", default="vwap_reversion_vr_d1_s1_1_5r")
    p.add_argument("--poll-interval-seconds", type=int, default=30)
    p.add_argument("--lookback-candles", type=int, default=400)
    p.add_argument("--env", default="prod")
    p.add_argument("--once", action="store_true")
    p.add_argument("--market-hours-config",
                   default="configs/market_hours/moex_futures.yaml")
    p.add_argument("--ignore-market-hours", action="store_true")
    p.add_argument("--api-timeout-sec", type=int, default=10)
    return p.parse_args()


def _setup_logging(log_file: str, experiment_name: str = "") -> logging.Logger:
    label = f"[{experiment_name}]" if experiment_name else "[vwap]"
    logger = logging.getLogger(f"vwap_paper_trader.{experiment_name or 'vwap'}")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(f"%(asctime)s %(levelname)s {label} %(message)s")
    if not logger.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def _fetch_with_timeout(ticker, class_code, timeframe, lookback_candles, env, timeout_sec):
    from src.paper.market_data import fetch_recent_candles
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = executor.submit(fetch_recent_candles, ticker, class_code, timeframe, lookback_candles, env)
    executor.shutdown(wait=False)
    return fut.result(timeout=timeout_sec)


def _get_today_msk() -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(tz=ZoneInfo("Europe/Moscow")).date().isoformat()


def _write_status(args, repo: VwapRepository, logger, cycle_state, market_open, session, fetch_status):
    import json
    today_msk = _get_today_msk()
    daily_ctx = repo.load_daily_state(today_msk)
    open_trade = repo.get_open_trade(args.ticker)
    closed_trades = [
        t for t in repo.list_all_trades(ticker=args.ticker)
        if t.status == VwapTradeStatus.CLOSED
    ]
    net_pnl = sum(t.pnl_rub or 0.0 for t in closed_trades)

    # Slippage analysis
    fills = [t for t in closed_trades if t.market_fill_price is not None]
    avg_slippage = (
        sum(abs(t.market_fill_price - t.entry_price) for t in fills) / len(fills)
        if fills else None
    )

    status = {
        "ticker": args.ticker,
        "experiment_name": args.experiment_name,
        "strategy": "vwap_reversion",
        "direction": "SHORT",
        "distance_mult": args.distance_mult,
        "stop_mult": args.stop_mult,
        "take_r": args.take_r,
        "market_open": market_open,
        "session": session,
        "fetch_status": fetch_status,
        "state": daily_ctx.state.value if daily_ctx else "UNKNOWN",
        "trades_today": daily_ctx.trades_today if daily_ctx else 0,
        "done_for_day": daily_ctx.done_for_day if daily_ctx else False,
        "open_trade": (
            {
                "trade_id": open_trade.trade_id,
                "entry_price": open_trade.entry_price,
                "stop_price": open_trade.stop_price,
                "take_price": open_trade.take_price,
                "market_fill_price": open_trade.market_fill_price,
                "bars_held": open_trade.bars_held,
            }
            if open_trade else None
        ),
        "closed_trades_total": len(closed_trades),
        "net_pnl_total": round(net_pnl, 2),
        "avg_slippage_pts": round(avg_slippage, 2) if avg_slippage is not None else None,
        "last_successful_fetch_at": cycle_state.get("last_successful_fetch_at"),
        "consecutive_api_errors": cycle_state.get("api_errors", 0),
        "pid": os.getpid(),
        "updated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    from src.paper.orb.status import write_orb_status
    Path(args.status_file).parent.mkdir(parents=True, exist_ok=True)
    with open(args.status_file, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, default=str)


def _run_cycle(args, repo: VwapRepository, logger, market_config, cycle_state):
    ticker = args.ticker

    now_utc = datetime.now(tz=timezone.utc)
    session = "unknown"
    market_open = True

    if not args.ignore_market_hours and market_config:
        from src.market.market_hours import is_session_open, get_session_name, to_market_timezone
        session = get_session_name(now_utc, market_config)
        market_open = is_session_open(now_utc, market_config)
        prev_open = cycle_state.get("prev_market_open", None)
        if market_open and prev_open is False:
            cycle_state["last_successful_fetch_at"] = None
        cycle_state["prev_market_open"] = market_open

        if not market_open:
            msk_t = to_market_timezone(now_utc, market_config)
            logger.info(
                f"MARKET_CLOSED ticker={ticker} session={session} msk_time={msk_t.isoformat()}"
            )
            cycle_state["api_errors"] = 0
            _write_status(args, repo, logger, cycle_state, market_open, session, "MARKET_CLOSED")
            return

    logger.info(f"Fetching {args.lookback_candles} candles for {ticker} {args.timeframe}...")
    try:
        df, _ = _fetch_with_timeout(
            ticker, args.class_code, args.timeframe,
            args.lookback_candles, args.env, args.api_timeout_sec,
        )
        cycle_state["api_errors"] = 0
        cycle_state["last_successful_fetch_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    except concurrent.futures.TimeoutError:
        cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
        logger.error(f"API_TIMEOUT ticker={ticker}")
        _write_status(args, repo, logger, cycle_state, market_open, session, "API_TIMEOUT")
        return
    except Exception as e:
        if "No columns to parse from file" in str(e):
            logger.warning(f"NO_CANDLES_RESPONSE ticker={ticker}")
        else:
            cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
            logger.error(f"API_ERROR ticker={ticker} error={e}")
        _write_status(args, repo, logger, cycle_state, market_open, session, "API_ERROR")
        return

    if df is None or df.empty:
        logger.warning(f"NO_CANDLES ticker={ticker}")
        _write_status(args, repo, logger, cycle_state, market_open, session, "NO_CANDLES")
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    today_msk = _get_today_msk()
    daily_ctx = repo.load_daily_state(today_msk)
    if daily_ctx is None:
        daily_ctx = VwapDailyContext(date_msk=today_msk)

    open_trade = repo.get_open_trade(ticker)

    last_ts_str = daily_ctx.last_processed_candle_ts
    if last_ts_str:
        try:
            last_ts = pd.Timestamp(last_ts_str).tz_convert("UTC")
            new_candles = df[df["timestamp"] > last_ts]
        except Exception:
            new_candles = df.tail(1)
    else:
        new_candles = df.tail(1)

    if new_candles.empty:
        logger.info("No new candles. Waiting...")
        _write_status(args, repo, logger, cycle_state, market_open, session, "OK")
        return

    logger.info(f"Processing {len(new_candles)} new candle(s).")

    for _, candle in new_candles.iterrows():
        # Pass all candles up to and including the current one for indicator computation
        candle_ts = candle["timestamp"]
        recent = df[df["timestamp"] <= candle_ts].copy()

        updated_ctx, trade_to_upsert, logs = process_candle_vwap(
            candle=candle,
            recent_candles=recent,
            daily_ctx=daily_ctx,
            open_trade=open_trade,
            distance_mult=args.distance_mult,
            stop_mult=args.stop_mult,
            take_r=args.take_r,
            atr_window=args.atr_window,
            time_exit_msk=dtime(18, 40),
            ticker=ticker,
            experiment_name=args.experiment_name,
            max_trades_per_day=args.max_trades_per_day,
            point_value_rub=args.point_value_rub,
            commission_rub=args.commission_rub,
        )

        for msg in logs:
            logger.info(msg)

        daily_ctx = updated_ctx

        if trade_to_upsert is not None:
            if open_trade is None and trade_to_upsert.status == VwapTradeStatus.OPEN:
                repo.insert_trade(trade_to_upsert)
                open_trade = trade_to_upsert
                logger.info(
                    f"TRADE_OPENED trade_id={trade_to_upsert.trade_id} "
                    f"entry={trade_to_upsert.entry_price}"
                )
            elif open_trade is not None:
                repo.update_trade(trade_to_upsert)
                if trade_to_upsert.status == VwapTradeStatus.CLOSED:
                    logger.info(
                        f"TRADE_CLOSED trade_id={trade_to_upsert.trade_id} "
                        f"exit={trade_to_upsert.exit_price} "
                        f"pnl_rub={trade_to_upsert.pnl_rub:.2f} "
                        f"reason={trade_to_upsert.exit_reason}"
                    )
                    open_trade = None
                else:
                    open_trade = trade_to_upsert

        repo.save_daily_state(daily_ctx)

    repo.export_csv(args.csv_output, ticker=ticker)
    _write_status(args, repo, logger, cycle_state, market_open, session, "OK")


def main():
    load_dotenv()
    args = _parse_args()

    logger = _setup_logging(args.log_file, args.experiment_name)
    logger.info("=" * 60)
    logger.info("VWAP Reversion Paper Trader — PAPER MODE ONLY — NO REAL ORDERS")
    logger.info(f"  ticker={args.ticker} class_code={args.class_code}")
    logger.info(f"  distance_mult={args.distance_mult} stop_mult={args.stop_mult} take_r={args.take_r}")
    logger.info(f"  atr_window={args.atr_window} max_trades_per_day={args.max_trades_per_day}")
    logger.info(f"  point_value_rub={args.point_value_rub} commission_rub={args.commission_rub}")
    logger.info(f"  experiment={args.experiment_name}")
    logger.info("=" * 60)

    market_config = None
    if not args.ignore_market_hours:
        try:
            from src.market.market_hours import load_market_hours_config
            market_config = load_market_hours_config(Path(args.market_hours_config))
            logger.info(f"  market_hours_config={args.market_hours_config} tz={market_config.timezone}")
        except FileNotFoundError:
            logger.warning(f"Market hours config not found: {args.market_hours_config}. Running without guard.")

    repo = VwapRepository(args.state_db)
    repo.init_db()

    cycle_state: dict = {
        "api_errors": 0,
        "last_successful_fetch_at": None,
        "prev_market_open": None,
    }

    if args.once:
        _run_cycle(args, repo, logger, market_config, cycle_state)
        return

    while True:
        try:
            _run_cycle(args, repo, logger, market_config, cycle_state)
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
        time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    main()
