"""ORB Fade (ORF) Paper Trading Daemon — polls T-Bank API, tracks virtual SHORT fade trades.

No real or sandbox orders are placed. Uses READONLY_TOKEN only.
Fades false breakouts above the Opening Range high: enters SHORT when price
breaks above OR_high then returns inside the OR within n_return_bars.
"""
import argparse
import concurrent.futures
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, time as dtime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.orf.engine import process_candle_orf
from src.paper.orf.models import OrfDailyContext, OrfTradeStatus
from src.paper.orf.repository import OrfRepository


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ORB Fade Paper trading daemon. No real orders. READONLY_TOKEN only."
    )
    p.add_argument("--ticker", default="SiU6")
    p.add_argument("--class-code", default="SPBFUT")
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--opening-range-start", default="10:00",
                   help="OR start time in MSK (HH:MM)")
    p.add_argument("--opening-range-end", default="11:00",
                   help="OR end time in MSK (HH:MM)")
    p.add_argument("--n-return-bars", type=int, default=3,
                   help="Bars after breakout to watch for return inside OR")
    p.add_argument("--take-mode", default="midpoint", choices=["midpoint", "one_r"],
                   help="Take profit target: OR midpoint or 1×risk")
    p.add_argument("--stop-buffer", type=float, default=1.0,
                   help="Points added above breakout_high for stop")
    p.add_argument("--point-value-rub", type=float, default=10.0)
    p.add_argument("--commission-rub", type=float, default=0.05)
    p.add_argument("--state-db", default="data/paper/paper_state_siu6_orf.sqlite")
    p.add_argument("--status-file", default="runtime/paper_status_SiU6_ORF.json")
    p.add_argument("--csv-output", default="out/paper/paper_trades_SiU6_ORF.csv")
    p.add_argument("--log-file", default="logs/paper_SiU6_ORF.log")
    p.add_argument("--experiment-name", default="orf_siu6_or60_n3_midpoint")
    p.add_argument("--poll-interval-seconds", type=int, default=30)
    p.add_argument("--lookback-candles", type=int, default=300)
    p.add_argument("--env", default="prod")
    p.add_argument("--once", action="store_true")
    p.add_argument("--market-hours-config",
                   default="configs/market_hours/moex_futures.yaml")
    p.add_argument("--ignore-market-hours", action="store_true")
    p.add_argument("--api-timeout-sec", type=int, default=10)
    return p.parse_args()


def _parse_time(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def _setup_logging(log_file: str, experiment_name: str = "") -> logging.Logger:
    label = f"[{experiment_name}]" if experiment_name else "[orf]"
    logger = logging.getLogger(f"orf_paper_trader.{experiment_name or 'orf'}")
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


def _write_status(args, repo: OrfRepository, cycle_state, market_open, session, fetch_status):
    today_msk = _get_today_msk()
    daily_ctx = repo.load_daily_state(today_msk)
    open_trade = repo.get_open_trade(args.ticker)
    closed_trades = [
        t for t in repo.list_all_trades(ticker=args.ticker)
        if t.status == OrfTradeStatus.CLOSED
    ]
    net_pnl = sum(t.pnl_rub or 0.0 for t in closed_trades)

    status = {
        "ticker": args.ticker,
        "experiment_name": args.experiment_name,
        "strategy": "orf",
        "direction": "SHORT",
        "or_window": f"{args.opening_range_start}-{args.opening_range_end}",
        "n_return_bars": args.n_return_bars,
        "take_mode": args.take_mode,
        "market_open": market_open,
        "session": session,
        "fetch_status": fetch_status,
        "state": daily_ctx.state.value if daily_ctx else "UNKNOWN",
        "or_high": daily_ctx.or_high if daily_ctx else None,
        "or_low": daily_ctx.or_low if daily_ctx else None,
        "in_breakout": daily_ctx.in_breakout if daily_ctx else False,
        "breakout_high": daily_ctx.breakout_high if daily_ctx else None,
        "trade_opened_today": daily_ctx.trade_opened if daily_ctx else False,
        "done_for_day": daily_ctx.done_for_day if daily_ctx else False,
        "open_trade": (
            {
                "trade_id": open_trade.trade_id,
                "entry_price": open_trade.entry_price,
                "stop_price": open_trade.stop_price,
                "take_price": open_trade.take_price,
                "or_high": open_trade.or_high,
                "breakout_high": open_trade.breakout_high,
                "bars_held": open_trade.bars_held,
            }
            if open_trade else None
        ),
        "closed_trades_total": len(closed_trades),
        "net_pnl_total": round(net_pnl, 2),
        "last_successful_fetch_at": cycle_state.get("last_successful_fetch_at"),
        "consecutive_api_errors": cycle_state.get("api_errors", 0),
        "pid": os.getpid(),
        "updated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    Path(args.status_file).parent.mkdir(parents=True, exist_ok=True)
    with open(args.status_file, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, default=str)


def _run_cycle(args, repo: OrfRepository, logger, market_config, cycle_state,
               or_start_msk, or_end_msk):
    ticker = args.ticker
    time_exit_msk = dtime(18, 40)

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
            _write_status(args, repo, cycle_state, market_open, session, "MARKET_CLOSED")
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
        _write_status(args, repo, cycle_state, market_open, session, "API_TIMEOUT")
        return
    except Exception as e:
        if "No columns to parse from file" in str(e):
            logger.warning(f"NO_CANDLES_RESPONSE ticker={ticker}")
        else:
            cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
            logger.error(f"API_ERROR ticker={ticker} error={e}")
        _write_status(args, repo, cycle_state, market_open, session, "API_ERROR")
        return

    if df is None or df.empty:
        logger.warning(f"NO_CANDLES ticker={ticker}")
        _write_status(args, repo, cycle_state, market_open, session, "NO_CANDLES")
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    today_msk = _get_today_msk()
    daily_ctx = repo.load_daily_state(today_msk)
    if daily_ctx is None:
        daily_ctx = OrfDailyContext(date_msk=today_msk)

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
        _write_status(args, repo, cycle_state, market_open, session, "OK")
        return

    logger.info(f"Processing {len(new_candles)} new candle(s).")

    for _, candle in new_candles.iterrows():
        updated_ctx, trade_to_upsert, logs = process_candle_orf(
            candle=candle,
            daily_ctx=daily_ctx,
            open_trade=open_trade,
            or_start_msk=or_start_msk,
            or_end_msk=or_end_msk,
            time_exit_msk=time_exit_msk,
            n_return_bars=args.n_return_bars,
            take_mode=args.take_mode,
            stop_buffer=args.stop_buffer,
            ticker=ticker,
            experiment_name=args.experiment_name,
            point_value_rub=args.point_value_rub,
            commission_rub=args.commission_rub,
        )

        for msg in logs:
            logger.info(msg)

        daily_ctx = updated_ctx

        if trade_to_upsert is not None:
            if open_trade is None and trade_to_upsert.status == OrfTradeStatus.OPEN:
                repo.insert_trade(trade_to_upsert)
                open_trade = trade_to_upsert
                logger.info(
                    f"TRADE_OPENED trade_id={trade_to_upsert.trade_id} "
                    f"entry={trade_to_upsert.entry_price}"
                )
            elif open_trade is not None:
                repo.update_trade(trade_to_upsert)
                if trade_to_upsert.status == OrfTradeStatus.CLOSED:
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
    _write_status(args, repo, cycle_state, market_open, session, "OK")


def main():
    load_dotenv()
    args = _parse_args()

    or_start_msk = _parse_time(args.opening_range_start)
    or_end_msk = _parse_time(args.opening_range_end)

    logger = _setup_logging(args.log_file, args.experiment_name)
    logger.info("=" * 60)
    logger.info("ORB Fade Paper Trader — PAPER MODE ONLY — NO REAL ORDERS")
    logger.info(f"  ticker={args.ticker} class_code={args.class_code}")
    logger.info(f"  or_window={args.opening_range_start}-{args.opening_range_end} MSK")
    logger.info(f"  n_return_bars={args.n_return_bars} take_mode={args.take_mode}")
    logger.info(f"  stop_buffer={args.stop_buffer} point_value_rub={args.point_value_rub}")
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

    repo = OrfRepository(args.state_db)
    repo.init_db()

    cycle_state: dict = {
        "api_errors": 0,
        "last_successful_fetch_at": None,
        "prev_market_open": None,
    }

    if args.once:
        _run_cycle(args, repo, logger, market_config, cycle_state, or_start_msk, or_end_msk)
        return

    while True:
        try:
            _run_cycle(args, repo, logger, market_config, cycle_state, or_start_msk, or_end_msk)
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
        time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    main()
