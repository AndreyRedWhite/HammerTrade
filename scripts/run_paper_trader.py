"""Paper trading daemon — polls T-Bank API and manages virtual trades.

No real or sandbox orders are placed. Uses READONLY_TOKEN only.
"""
import argparse
import concurrent.futures
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_params
from src.strategy.hammer_detector import HammerDetector
from src.paper.engine import process_candle
from src.paper.models import PaperTradeStatus
from src.paper.repository import PaperRepository
from src.paper.status import StatusWriter, build_status


def _parse_args():
    p = argparse.ArgumentParser(
        description="Paper trading daemon. No real orders. READONLY_TOKEN only."
    )
    p.add_argument("--ticker", default="SiM6")
    p.add_argument("--class-code", default="SPBFUT")
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--profile", default="balanced")
    p.add_argument("--params", default="configs/hammer_detector_balanced.env")
    p.add_argument("--direction-filter", default="SELL")
    p.add_argument("--entry-mode", default="breakout")
    p.add_argument("--take-r", type=float, default=1.0)
    p.add_argument("--max-hold-bars", type=int, default=30)
    p.add_argument("--stop-buffer-points", type=float, default=0.0)
    p.add_argument("--slippage-ticks", type=float, default=1.0)
    p.add_argument("--contracts", type=int, default=1)
    p.add_argument("--poll-interval-seconds", type=int, default=20)
    p.add_argument("--lookback-candles", type=int, default=300)
    p.add_argument("--state-db", default="data/paper/paper_state.sqlite")
    p.add_argument("--trades-output", default="out/paper/paper_trades_SiM6_SELL.csv")
    p.add_argument("--log-file", default="logs/paper_SiM6_SELL.log")
    p.add_argument("--env", default="prod")
    p.add_argument("--once", action="store_true", help="Run one cycle then exit")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch candles and show detector output, do not write state")
    # Operational safety layer
    p.add_argument("--market-hours-config",
                   default="configs/market_hours/moex_futures.yaml",
                   help="Path to market hours YAML config")
    p.add_argument("--ignore-market-hours", action="store_true",
                   help="Disable market hours guard (useful for debugging)")
    p.add_argument("--api-timeout-sec", type=int, default=10,
                   help="Timeout for T-Bank candle fetch API call in seconds")
    p.add_argument("--status-file", default=None,
                   help="Path to JSON status file (default: runtime/paper_status_{ticker}_{direction}.json)")
    return p.parse_args()


def _setup_logging(log_file: str, dry_run: bool) -> logging.Logger:
    logger = logging.getLogger("paper_trader")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    if not logger.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        if not dry_run:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_file)
            fh.setFormatter(fmt)
            logger.addHandler(fh)
    return logger


def _state_key(ticker, timeframe, profile, direction):
    return f"last_processed:{ticker}:{timeframe}:{profile}:{direction}"


def _signal_key(ticker, timeframe, profile, direction):
    return f"pending_signal:{ticker}:{timeframe}:{profile}:{direction}"


def _load_pending_signal(repo: PaperRepository, ticker, timeframe, profile, direction):
    raw = repo.get_state(_signal_key(ticker, timeframe, profile, direction))
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _save_pending_signal(repo: PaperRepository, signal, ticker, timeframe, profile, direction):
    key = _signal_key(ticker, timeframe, profile, direction)
    if signal is None:
        repo.set_state(key, "")
    else:
        repo.set_state(key, json.dumps(signal))


def _export_csv(repo: PaperRepository, output_path: str, ticker: str):
    trades = repo.list_recent_trades(ticker=ticker, limit=10000)
    if not trades:
        return
    rows = []
    for t in trades:
        rows.append({
            "trade_id": t.trade_id,
            "ticker": t.ticker,
            "class_code": t.class_code,
            "timeframe": t.timeframe,
            "profile": t.profile,
            "direction": t.direction,
            "signal_timestamp": t.signal_timestamp,
            "entry_timestamp": t.entry_timestamp,
            "entry_price": t.entry_price,
            "stop_price": t.stop_price,
            "take_price": t.take_price,
            "status": t.status.value if hasattr(t.status, "value") else t.status,
            "exit_timestamp": t.exit_timestamp,
            "exit_price": t.exit_price,
            "exit_reason": t.exit_reason.value if t.exit_reason and hasattr(t.exit_reason, "value") else t.exit_reason,
            "pnl_points": t.pnl_points,
            "pnl_rub": t.pnl_rub,
            "bars_held": t.bars_held,
            "created_at": t.created_at,
            "updated_at": t.updated_at,
        })
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, index=False)


def _fetch_with_timeout(ticker, class_code, timeframe, lookback_candles, env, timeout_sec):
    """Fetch candles with a thread-based timeout. Returns (df, tick_size) or raises."""
    from src.paper.market_data import fetch_recent_candles
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = executor.submit(fetch_recent_candles, ticker, class_code, timeframe, lookback_candles, env)
    executor.shutdown(wait=False)
    return fut.result(timeout=timeout_sec)


def _run_cycle(args, repo, logger, market_config, sw: Optional[StatusWriter], cycle_state: dict):
    ticker = args.ticker
    class_code = args.class_code
    timeframe = args.timeframe
    profile = args.profile
    direction = args.direction_filter.upper()

    now_utc = datetime.now(tz=timezone.utc)
    market_tz = market_config.timezone if market_config else "Europe/Moscow"

    def _common_status_kwargs(fetch_status, *, market_open=False, session="unknown",
                              last_candle_ts_utc=None, last_candle_ts_msk=None,
                              last_processed=None, open_trades=0, pending=False,
                              last_error=None):
        return dict(
            ticker=ticker, class_code=class_code, timeframe=timeframe,
            profile=profile, direction=direction, env=args.env,
            market_hours_enabled=not args.ignore_market_hours,
            market_open=market_open, session=session, market_timezone=market_tz,
            last_fetch_status=fetch_status,
            last_candle_ts_utc=last_candle_ts_utc, last_candle_ts_msk=last_candle_ts_msk,
            last_processed_ts_utc=last_processed,
            open_trades=open_trades, pending_signal=pending,
            consecutive_empty_fetches=cycle_state.get("empty_fetches", 0),
            consecutive_api_errors=cycle_state.get("api_errors", 0),
            last_error=last_error,
        )

    # ── Market hours guard ───────────────────────────────────────────────────
    session = "unknown"
    market_open = True
    if not args.ignore_market_hours and market_config:
        from src.market.market_hours import is_session_open, get_session_name, to_market_timezone
        session = get_session_name(now_utc, market_config)
        market_open = is_session_open(now_utc, market_config)
        msk_time = to_market_timezone(now_utc, market_config)

        if not market_open:
            logger.info(
                f"MARKET_CLOSED ticker={ticker} session={session} "
                f"msk_time={msk_time.isoformat()} next_cycle_in={args.poll_interval_seconds}s"
            )
            cycle_state["empty_fetches"] = 0
            cycle_state["api_errors"] = 0
            if sw:
                sw.write(build_status(**_common_status_kwargs(
                    "MARKET_CLOSED", session=session, market_open=False
                )))
            return

    # ── Fetch candles with timeout ───────────────────────────────────────────
    logger.info(f"Fetching {args.lookback_candles} candles for {ticker} {timeframe}...")
    try:
        df, tick_size = _fetch_with_timeout(
            ticker, class_code, timeframe,
            args.lookback_candles, args.env,
            args.api_timeout_sec,
        )
        cycle_state["api_errors"] = 0
    except concurrent.futures.TimeoutError:
        cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
        msg = f"API_TIMEOUT ticker={ticker} timeout_sec={args.api_timeout_sec} operation=fetch_recent_candles"
        logger.error(msg)
        if sw:
            sw.write(build_status(**_common_status_kwargs(
                "API_TIMEOUT", session=session, market_open=market_open, last_error=msg
            )))
        return
    except Exception as e:
        cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
        msg = f"API_ERROR ticker={ticker} error={e}"
        logger.error(msg)
        if sw:
            sw.write(build_status(**_common_status_kwargs(
                "API_ERROR", session=session, market_open=market_open, last_error=str(e)
            )))
        return

    # ── Empty / no candles ───────────────────────────────────────────────────
    if df.empty:
        cycle_state["empty_fetches"] = cycle_state.get("empty_fetches", 0) + 1
        if market_open and not args.ignore_market_hours and market_config:
            from src.market.market_hours import to_market_timezone
            msk_time = to_market_timezone(now_utc, market_config)
            logger.warning(
                f"NO_CANDLES_DURING_OPEN_SESSION ticker={ticker} "
                f"session={session} msk_time={msk_time.isoformat()}"
            )
            fetch_status = "NO_CANDLES_DURING_OPEN_SESSION"
        else:
            logger.warning(f"NO_CANDLES ticker={ticker}")
            fetch_status = "NO_CANDLES"
        if sw:
            sw.write(build_status(**_common_status_kwargs(
                fetch_status, session=session, market_open=market_open
            )))
        return

    cycle_state["empty_fetches"] = 0

    # ── Stale candle guard ───────────────────────────────────────────────────
    last_candle_ts = pd.Timestamp(df["timestamp"].iloc[-1]).to_pydatetime()
    if last_candle_ts.tzinfo is None:
        last_candle_ts = last_candle_ts.replace(tzinfo=timezone.utc)

    last_candle_ts_utc_str = last_candle_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    last_candle_ts_msk_str = None

    if not args.ignore_market_hours and market_config and market_open:
        from src.market.market_hours import to_market_timezone
        msk_now = to_market_timezone(now_utc, market_config)
        msk_last = to_market_timezone(last_candle_ts, market_config)
        last_candle_ts_msk_str = msk_last.isoformat()
        grace = market_config.stale_candle_grace_minutes
        age_minutes = (now_utc - last_candle_ts).total_seconds() / 60
        if age_minutes > grace:
            logger.warning(
                f"STALE_CANDLES ticker={ticker} "
                f"last_candle_msk={msk_last.isoformat()} "
                f"now_msk={msk_now.isoformat()} "
                f"max_age_minutes={grace}"
            )
            if sw:
                sw.write(build_status(**_common_status_kwargs(
                    "STALE_CANDLES", session=session, market_open=True,
                    last_candle_ts_utc=last_candle_ts_utc_str,
                    last_candle_ts_msk=last_candle_ts_msk_str,
                )))
            return

    # ── Params + detector ────────────────────────────────────────────────────
    params = load_params(args.params)
    if tick_size and tick_size > 0:
        params.tick_size = tick_size
        params.tick_size_source = "specs"

    logger.info(
        f"Candles loaded: {len(df)}, last: {df['timestamp'].iloc[-1]}, "
        f"tick_size={params.effective_tick_size}"
    )

    detector = HammerDetector(params)
    debug_df = detector.detect_all(df, instrument=ticker, timeframe=timeframe, profile=profile)

    last_closed = debug_df.iloc[-1]
    logger.info(
        f"Last closed candle: {last_closed['timestamp']} "
        f"is_signal={last_closed['is_signal']} direction={last_closed.get('direction_candidate', '-')}"
    )

    if args.dry_run:
        signals = debug_df[
            debug_df["is_signal"].astype(bool) & (debug_df["fail_reason"].astype(str) == "pass")
        ]
        logger.info(f"Dry-run: {len(signals)} signals in window. Last is_signal={last_closed['is_signal']}")
        return

    # ── State machine ────────────────────────────────────────────────────────
    last_ts_str = repo.get_state(_state_key(ticker, timeframe, profile, direction))
    last_ts = pd.Timestamp(last_ts_str, tz="UTC") if last_ts_str else None

    closed_df = debug_df.iloc[:-1] if len(debug_df) > 1 else debug_df
    if last_ts:
        new_candles = closed_df[closed_df["timestamp"] > last_ts]
    else:
        new_candles = closed_df.tail(1)

    if new_candles.empty:
        logger.info("No new closed candles to process. Waiting...")
        open_trade = repo.get_open_trade(ticker, timeframe, profile, direction)
        pending = _load_pending_signal(repo, ticker, timeframe, profile, direction)
        if sw:
            sw.write(build_status(**_common_status_kwargs(
                "OK", session=session, market_open=market_open,
                last_candle_ts_utc=last_candle_ts_utc_str,
                last_candle_ts_msk=last_candle_ts_msk_str,
                last_processed=last_ts_str,
                open_trades=1 if open_trade else 0,
                pending=bool(pending),
            )))
        return

    logger.info(f"Processing {len(new_candles)} new candle(s).")

    engine_params = dict(
        direction_filter=direction,
        entry_mode=args.entry_mode,
        max_hold_bars=args.max_hold_bars,
        take_r=args.take_r,
        stop_buffer_points=args.stop_buffer_points,
        slippage_ticks=args.slippage_ticks,
        tick_size=params.effective_tick_size,
        point_value_rub=params.point_value_rub,
        commission_per_trade=params.commission_per_trade,
        contracts=args.contracts,
        ticker=ticker,
        class_code=class_code,
        timeframe=timeframe,
        profile=profile,
    )

    for _, candle in new_candles.iterrows():
        pending_signal = _load_pending_signal(repo, ticker, timeframe, profile, direction)
        open_trade = repo.get_open_trade(ticker, timeframe, profile, direction)

        updated_trade, new_signal, logs = process_candle(
            candle=candle,
            open_trade=open_trade,
            pending_signal=pending_signal,
            **engine_params,
        )

        for msg in logs:
            logger.info(msg)

        if updated_trade is not None:
            if open_trade is None and updated_trade.status == PaperTradeStatus.OPEN:
                repo.insert_trade(updated_trade)
                repo.insert_event(
                    event_id=f"entry:{updated_trade.trade_id}",
                    ticker=ticker, event_type="ENTRY",
                    message=f"Paper trade opened: {updated_trade.trade_id}",
                )
            elif open_trade is not None:
                repo.update_trade(updated_trade)
                if updated_trade.status == PaperTradeStatus.CLOSED:
                    repo.insert_event(
                        event_id=f"exit:{updated_trade.trade_id}:{updated_trade.exit_reason}",
                        ticker=ticker, event_type="EXIT",
                        message=f"Paper trade closed: {updated_trade.trade_id} pnl={updated_trade.pnl_rub}",
                    )

        _save_pending_signal(repo, new_signal, ticker, timeframe, profile, direction)
        repo.set_state(_state_key(ticker, timeframe, profile, direction), str(candle["timestamp"]))

    _export_csv(repo, args.trades_output, ticker)

    open_trade = repo.get_open_trade(ticker, timeframe, profile, direction)
    pending = _load_pending_signal(repo, ticker, timeframe, profile, direction)
    if sw:
        sw.write(build_status(**_common_status_kwargs(
            "OK", session=session, market_open=market_open,
            last_candle_ts_utc=last_candle_ts_utc_str,
            last_candle_ts_msk=last_candle_ts_msk_str,
            last_processed=str(new_candles["timestamp"].iloc[-1]),
            open_trades=1 if open_trade else 0,
            pending=bool(pending),
        )))


def main():
    load_dotenv()
    args = _parse_args()

    # Default status-file path
    if args.status_file is None:
        args.status_file = f"runtime/paper_status_{args.ticker}_{args.direction_filter.upper()}.json"

    logger = _setup_logging(args.log_file, args.dry_run)

    logger.info("=" * 60)
    logger.info("HammerTrade Paper Trader — PAPER MODE ONLY — NO REAL ORDERS")
    logger.info(f"  ticker={args.ticker} class_code={args.class_code}")
    logger.info(f"  timeframe={args.timeframe} profile={args.profile}")
    logger.info(f"  direction={args.direction_filter} entry_mode={args.entry_mode}")
    logger.info(f"  take_r={args.take_r} max_hold_bars={args.max_hold_bars}")
    logger.info(f"  slippage_ticks={args.slippage_ticks} contracts={args.contracts}")
    logger.info(f"  poll_interval={args.poll_interval_seconds}s dry_run={args.dry_run}")
    logger.info(f"  api_timeout={args.api_timeout_sec}s status_file={args.status_file}")

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

    logger.info("=" * 60)

    sw = StatusWriter(args.status_file) if not args.dry_run else None
    repo = None
    if not args.dry_run:
        repo = PaperRepository(args.state_db)
        repo.init_db()

    cycle_state: dict = {"empty_fetches": 0, "api_errors": 0}

    if args.once or args.dry_run:
        _run_cycle(args, repo, logger, market_config, sw, cycle_state)
        return

    while True:
        try:
            _run_cycle(args, repo, logger, market_config, sw, cycle_state)
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
        time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    main()
