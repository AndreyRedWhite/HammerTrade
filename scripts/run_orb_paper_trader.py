"""ORB Paper Trading Daemon — polls T-Bank API and tracks virtual ORB trades.

No real or sandbox orders are placed. Uses READONLY_TOKEN only.
"""
import argparse
import concurrent.futures
import logging
import os
import sys
import time
from datetime import datetime, timezone, time as dtime
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.orb.engine import process_candle_orb
from src.paper.orb.models import OrbDailyContext, OrbTradeStatus
from src.paper.orb.repository import OrbRepository
from src.paper.orb.status import build_orb_status, write_orb_status


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ORB Paper trading daemon. No real orders. READONLY_TOKEN only."
    )
    p.add_argument("--ticker", default="SiM6")
    p.add_argument("--class-code", default="SPBFUT")
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--direction", default="SHORT", choices=["SHORT", "LONG"])
    p.add_argument("--opening-range-start", default="10:00",
                   help="OR start time in MSK (HH:MM)")
    p.add_argument("--opening-range-end", default="11:00",
                   help="OR end time in MSK (HH:MM)")
    p.add_argument("--take-r", type=float, default=2.0,
                   help="Take profit ratio (risk multiple)")
    p.add_argument("--point-value-rub", type=float, default=10.0,
                   help="RUB value per 1 price point (instrument-specific)")
    p.add_argument("--commission-rub", type=float, default=0.05,
                   help="Round-trip commission in RUB per contract")
    p.add_argument("--state-db", default="data/paper/paper_state_orb.sqlite")
    p.add_argument("--status-file", default="runtime/paper_status_SiM6_ORB.json")
    p.add_argument("--csv-output", default="out/paper/paper_trades_SiM6_ORB.csv")
    p.add_argument("--log-file", default="logs/paper_SiM6_ORB.log")
    p.add_argument("--experiment-name", default="orb_or60_short2r")
    p.add_argument("--orders-enabled", action="store_true", default=False,
                   help="MUST ALWAYS BE FALSE — orders are never executed")
    p.add_argument("--poll-interval-seconds", type=int, default=30)
    p.add_argument("--lookback-candles", type=int, default=300)
    p.add_argument("--env", default="prod")
    p.add_argument("--once", action="store_true", help="Run one cycle then exit")
    p.add_argument("--market-hours-config",
                   default="configs/market_hours/moex_futures.yaml")
    p.add_argument("--ignore-market-hours", action="store_true")
    p.add_argument("--api-timeout-sec", type=int, default=10)
    return p.parse_args()


def _parse_time(s: str) -> dtime:
    """Parse 'HH:MM' into datetime.time."""
    h, m = s.split(":")
    return dtime(int(h), int(m))


def _setup_logging(log_file: str, experiment_name: str = "") -> logging.Logger:
    label = f"[{experiment_name}]" if experiment_name else "[orb]"
    logger = logging.getLogger(f"orb_paper_trader.{experiment_name or 'orb'}")
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
    """Fetch candles with a thread-based timeout."""
    from src.paper.market_data import fetch_recent_candles
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = executor.submit(fetch_recent_candles, ticker, class_code, timeframe, lookback_candles, env)
    executor.shutdown(wait=False)
    return fut.result(timeout=timeout_sec)


def _is_empty_candles_error(exc: Exception) -> bool:
    return isinstance(exc, pd.errors.EmptyDataError) or "No columns to parse from file" in str(exc)


def _get_today_msk() -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(tz=ZoneInfo("Europe/Moscow")).date().isoformat()


def _compute_net_pnl(repo: OrbRepository, ticker: str) -> float:
    trades = repo.list_all_trades(ticker=ticker)
    return sum(
        (t.pnl_rub or 0.0)
        for t in trades
        if t.status == OrbTradeStatus.CLOSED
    )


def _run_cycle(
    args,
    repo: OrbRepository,
    logger: logging.Logger,
    market_config,
    cycle_state: dict,
    or_start_msk: dtime,
    or_end_msk: dtime,
    time_exit_msk: dtime,
):
    ticker = args.ticker
    class_code = args.class_code
    timeframe = args.timeframe
    direction = args.direction.upper()

    now_utc = datetime.now(tz=timezone.utc)
    market_tz = market_config.timezone if market_config else "Europe/Moscow"

    # ── Market hours guard ─────────────────────────────────────────────────────
    session = "unknown"
    market_open = True
    if not args.ignore_market_hours and market_config:
        from src.market.market_hours import is_session_open, get_session_name, to_market_timezone
        session = get_session_name(now_utc, market_config)
        market_open = is_session_open(now_utc, market_config)

        prev_market_open = cycle_state.get("prev_market_open", None)
        if market_open:
            if prev_market_open is False:
                cycle_state["last_successful_fetch_at"] = None
                cycle_state["market_open_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            elif cycle_state.get("market_open_at") is None:
                cycle_state["market_open_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            cycle_state["market_open_at"] = None
        cycle_state["prev_market_open"] = market_open

        if not market_open:
            msk_time = to_market_timezone(now_utc, market_config)
            logger.info(
                f"MARKET_CLOSED ticker={ticker} session={session} "
                f"msk_time={msk_time.isoformat()} next_cycle_in={args.poll_interval_seconds}s"
            )
            cycle_state["api_errors"] = 0
            _write_status(args, repo, logger, cycle_state, market_open, session,
                          "MARKET_CLOSED", or_start_msk, or_end_msk, time_exit_msk)
            return

    # ── Fetch candles ──────────────────────────────────────────────────────────
    logger.info(f"Fetching {args.lookback_candles} candles for {ticker} {timeframe}...")
    try:
        df, _ = _fetch_with_timeout(
            ticker, class_code, timeframe,
            args.lookback_candles, args.env,
            args.api_timeout_sec,
        )
        cycle_state["api_errors"] = 0
        cycle_state["last_successful_fetch_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    except concurrent.futures.TimeoutError:
        cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
        cycle_state["total_api_errors"] = cycle_state.get("total_api_errors", 0) + 1
        cycle_state["last_api_error_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        msg = f"API_TIMEOUT ticker={ticker} timeout_sec={args.api_timeout_sec}"
        cycle_state["last_api_error_message"] = msg
        logger.error(msg)
        _write_status(args, repo, logger, cycle_state, market_open, session,
                      "API_TIMEOUT", or_start_msk, or_end_msk, time_exit_msk)
        return
    except Exception as e:
        if _is_empty_candles_error(e):
            logger.warning(f"EMPTY_CANDLES_RESPONSE ticker={ticker}")
        else:
            cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
            cycle_state["total_api_errors"] = cycle_state.get("total_api_errors", 0) + 1
            cycle_state["last_api_error_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            cycle_state["last_api_error_message"] = str(e)
            logger.error(f"API_ERROR ticker={ticker} error={e}")
        _write_status(args, repo, logger, cycle_state, market_open, session,
                      "API_ERROR", or_start_msk, or_end_msk, time_exit_msk)
        return

    if df.empty:
        logger.warning(f"NO_CANDLES ticker={ticker}")
        _write_status(args, repo, logger, cycle_state, market_open, session,
                      "NO_CANDLES", or_start_msk, or_end_msk, time_exit_msk)
        return

    logger.info(f"Candles loaded: {len(df)}, last: {df['timestamp'].iloc[-1]}")

    # ── Load daily state ───────────────────────────────────────────────────────
    today_msk = _get_today_msk()
    daily_ctx = repo.load_daily_state(today_msk)
    if daily_ctx is None:
        daily_ctx = OrbDailyContext(date_msk=today_msk)

    open_trade = repo.get_open_trade(ticker)

    # ── Filter new candles ─────────────────────────────────────────────────────
    last_ts_str = daily_ctx.last_processed_candle_ts
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    if last_ts_str:
        try:
            last_ts = pd.Timestamp(last_ts_str).tz_convert("UTC")
            new_candles = df[df["timestamp"] > last_ts]
        except Exception:
            new_candles = df.tail(1)
    else:
        new_candles = df.tail(1)

    if new_candles.empty:
        logger.info("No new candles to process. Waiting...")
        _write_status(args, repo, logger, cycle_state, market_open, session,
                      "OK", or_start_msk, or_end_msk, time_exit_msk)
        return

    logger.info(f"Processing {len(new_candles)} new candle(s).")

    # ── Process each candle through state machine ──────────────────────────────
    for _, candle in new_candles.iterrows():
        updated_ctx, trade_to_upsert, logs = process_candle_orb(
            candle=candle,
            daily_ctx=daily_ctx,
            open_trade=open_trade,
            direction=direction,
            or_start_msk=or_start_msk,
            or_end_msk=or_end_msk,
            take_r=args.take_r,
            time_exit_msk=time_exit_msk,
            ticker=ticker,
            experiment_name=args.experiment_name,
            point_value_rub=args.point_value_rub,
            commission_rub=args.commission_rub,
        )

        for msg in logs:
            logger.info(msg)

        daily_ctx = updated_ctx

        if trade_to_upsert is not None:
            if open_trade is None and trade_to_upsert.status == OrbTradeStatus.OPEN:
                repo.insert_trade(trade_to_upsert)
                open_trade = trade_to_upsert
                logger.info(
                    f"TRADE_OPENED trade_id={trade_to_upsert.trade_id} "
                    f"entry={trade_to_upsert.entry_price}"
                )
            elif open_trade is not None:
                repo.update_trade(trade_to_upsert)
                if trade_to_upsert.status == OrbTradeStatus.CLOSED:
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

    # ── Export CSV ─────────────────────────────────────────────────────────────
    repo.export_csv(args.csv_output, ticker=ticker)

    # ── Write status ───────────────────────────────────────────────────────────
    _write_status(args, repo, logger, cycle_state, market_open, session,
                  "OK", or_start_msk, or_end_msk, time_exit_msk)


def _write_status(
    args,
    repo: OrbRepository,
    logger: logging.Logger,
    cycle_state: dict,
    market_open: bool,
    session: str,
    fetch_status: str,
    or_start_msk: dtime,
    or_end_msk: dtime,
    time_exit_msk: dtime,
) -> None:
    """Build and write ORB status JSON. Also logs liveness transitions."""
    today_msk = _get_today_msk()
    daily_ctx = repo.load_daily_state(today_msk)
    if daily_ctx is None:
        daily_ctx = OrbDailyContext(date_msk=today_msk)

    open_trade = repo.get_open_trade(args.ticker)
    closed_trades = [
        t for t in repo.list_all_trades(ticker=args.ticker)
        if t.status == OrbTradeStatus.CLOSED
    ]
    net_pnl = sum(t.pnl_rub or 0.0 for t in closed_trades)

    status = build_orb_status(
        ticker=args.ticker,
        experiment_name=args.experiment_name,
        direction=args.direction,
        or_start=args.opening_range_start,
        or_end=args.opening_range_end,
        take_r=args.take_r,
        daily_ctx=daily_ctx,
        open_trade=open_trade,
        closed_trades_total=len(closed_trades),
        net_pnl_total=net_pnl,
        market_open=market_open,
        session=session,
        fetch_status=fetch_status,
        last_successful_fetch_at=cycle_state.get("last_successful_fetch_at"),
        consecutive_api_errors=cycle_state.get("api_errors", 0),
        total_api_errors=cycle_state.get("total_api_errors", 0),
        last_api_error_at=cycle_state.get("last_api_error_at"),
        last_api_error_message=cycle_state.get("last_api_error_message"),
        market_open_since=cycle_state.get("market_open_at"),
        pid=os.getpid(),
    )

    write_orb_status(status, args.status_file)

    # Log liveness transitions
    new_liveness = status.get("trading_liveness_status", "OK")
    prev_liveness = cycle_state.get("last_liveness_status", "OK")
    if new_liveness != prev_liveness:
        reason = status.get("trading_liveness_reason", "")
        if new_liveness == "STALLED":
            logger.error(f"TRADING_LIVENESS_STALLED reason={reason}")
        elif new_liveness == "DEGRADED":
            logger.warning(f"TRADING_LIVENESS_DEGRADED reason={reason}")
        elif new_liveness == "OK" and prev_liveness != "OK":
            logger.info(f"TRADING_LIVENESS_RECOVERED prev={prev_liveness}")
        cycle_state["last_liveness_status"] = new_liveness


def main():
    load_dotenv()
    args = _parse_args()

    # Safety check: orders_enabled MUST ALWAYS be False
    if args.orders_enabled:
        print("ERROR: orders_enabled=True is not allowed. ORB paper trader is read-only.", file=sys.stderr)
        sys.exit(1)

    or_start_msk = _parse_time(args.opening_range_start)
    or_end_msk = _parse_time(args.opening_range_end)
    # Time exit: 18:40 MSK (hardcoded, before evening clearing)
    time_exit_msk = dtime(18, 40)

    logger = _setup_logging(args.log_file, args.experiment_name)

    logger.info("=" * 60)
    logger.info("ORB Paper Trader — PAPER MODE ONLY — NO REAL ORDERS")
    logger.info(f"  ticker={args.ticker} class_code={args.class_code}")
    logger.info(f"  timeframe={args.timeframe} direction={args.direction}")
    logger.info(f"  or_window={args.opening_range_start}-{args.opening_range_end} MSK")
    logger.info(f"  take_r={args.take_r} time_exit=18:40 MSK")
    logger.info(f"  experiment={args.experiment_name}")
    logger.info(f"  poll_interval={args.poll_interval_seconds}s")
    logger.info(f"  state_db={args.state_db}")
    logger.info(f"  status_file={args.status_file}")
    logger.info(f"  csv_output={args.csv_output}")
    logger.info(f"  orders_enabled={args.orders_enabled} (must be False)")
    logger.info("=" * 60)

    # Market hours config
    market_config = None
    if not args.ignore_market_hours:
        try:
            from src.market.market_hours import load_market_hours_config
            market_config = load_market_hours_config(Path(args.market_hours_config))
            logger.info(f"  market_hours_config={args.market_hours_config} tz={market_config.timezone}")
        except FileNotFoundError:
            logger.warning(
                f"Market hours config not found: {args.market_hours_config}. "
                "Running without market hours guard."
            )
    else:
        logger.info("  Market hours guard disabled by --ignore-market-hours")

    # Init DB
    repo = OrbRepository(args.state_db)
    repo.init_db()

    cycle_state: dict = {
        "api_errors": 0,
        "total_api_errors": 0,
        "last_api_error_at": None,
        "last_api_error_message": None,
        "last_successful_fetch_at": None,
        "prev_market_open": None,
        "market_open_at": None,
        "last_liveness_status": "OK",
    }

    if args.once:
        _run_cycle(args, repo, logger, market_config, cycle_state,
                   or_start_msk, or_end_msk, time_exit_msk)
        return

    while True:
        try:
            _run_cycle(args, repo, logger, market_config, cycle_state,
                       or_start_msk, or_end_msk, time_exit_msk)
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
        time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    main()
