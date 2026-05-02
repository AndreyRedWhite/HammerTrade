"""Paper trading daemon — polls T-Bank API and manages virtual trades.

No real or sandbox orders are placed. Uses READONLY_TOKEN only.
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_params
from src.strategy.hammer_detector import HammerDetector
from src.paper.engine import process_candle
from src.paper.models import PaperTradeStatus
from src.paper.repository import PaperRepository


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


def _run_cycle(args, repo, logger):
    from src.paper.market_data import fetch_recent_candles

    ticker = args.ticker
    class_code = args.class_code
    timeframe = args.timeframe
    profile = args.profile
    direction = args.direction_filter.upper()

    logger.info(f"Fetching {args.lookback_candles} candles for {ticker} {timeframe}...")
    try:
        df, tick_size = fetch_recent_candles(
            ticker=ticker,
            class_code=class_code,
            timeframe=timeframe,
            lookback_minutes=args.lookback_candles,
            env=args.env,
        )
    except Exception as e:
        logger.error(f"Failed to fetch candles: {e}")
        return

    if df.empty:
        logger.warning("No candles returned, skipping cycle.")
        return

    # Resolve tick_size: use API value, then params fallback
    params = load_params(args.params)
    if tick_size and tick_size > 0:
        params.tick_size = tick_size
        params.tick_size_source = "specs"

    logger.info(f"Candles loaded: {len(df)}, last: {df['timestamp'].iloc[-1]}, tick_size={params.effective_tick_size}")

    # Run detector
    detector = HammerDetector(params)
    debug_df = detector.detect_all(df, instrument=ticker, timeframe=timeframe, profile=profile)

    last_closed = debug_df.iloc[-1]
    logger.info(
        f"Last closed candle: {last_closed['timestamp']} "
        f"is_signal={last_closed['is_signal']} direction={last_closed.get('direction_candidate', '-')}"
    )

    if args.dry_run:
        signals = debug_df[debug_df["is_signal"].astype(bool) & (debug_df["fail_reason"].astype(str) == "pass")]
        logger.info(f"Dry-run: {len(signals)} signals in window. Last candle is_signal={last_closed['is_signal']}")
        return

    # Get last processed timestamp
    last_ts_str = repo.get_state(_state_key(ticker, timeframe, profile, direction))
    last_ts = pd.Timestamp(last_ts_str, tz="UTC") if last_ts_str else None

    # Select unprocessed closed candles (exclude the last row — may not be fully closed yet)
    closed_df = debug_df.iloc[:-1] if len(debug_df) > 1 else debug_df
    if last_ts:
        new_candles = closed_df[closed_df["timestamp"] > last_ts]
    else:
        new_candles = closed_df.tail(1)

    if new_candles.empty:
        logger.info("No new closed candles to process. Waiting...")
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
                    ticker=ticker,
                    event_type="ENTRY",
                    message=f"Paper trade opened: {updated_trade.trade_id}",
                )
            elif open_trade is not None:
                repo.update_trade(updated_trade)
                if updated_trade.status == PaperTradeStatus.CLOSED:
                    repo.insert_event(
                        event_id=f"exit:{updated_trade.trade_id}:{updated_trade.exit_reason}",
                        ticker=ticker,
                        event_type="EXIT",
                        message=f"Paper trade closed: {updated_trade.trade_id} pnl={updated_trade.pnl_rub}",
                    )

        _save_pending_signal(repo, new_signal, ticker, timeframe, profile, direction)
        repo.set_state(_state_key(ticker, timeframe, profile, direction), str(candle["timestamp"]))

    _export_csv(repo, args.trades_output, ticker)


def main():
    load_dotenv()
    args = _parse_args()
    logger = _setup_logging(args.log_file, args.dry_run)

    logger.info("=" * 60)
    logger.info("HammerTrade Paper Trader — PAPER MODE ONLY — NO REAL ORDERS")
    logger.info(f"  ticker={args.ticker} class_code={args.class_code}")
    logger.info(f"  timeframe={args.timeframe} profile={args.profile}")
    logger.info(f"  direction={args.direction_filter} entry_mode={args.entry_mode}")
    logger.info(f"  take_r={args.take_r} max_hold_bars={args.max_hold_bars}")
    logger.info(f"  slippage_ticks={args.slippage_ticks} contracts={args.contracts}")
    logger.info(f"  poll_interval={args.poll_interval_seconds}s dry_run={args.dry_run}")
    logger.info("=" * 60)

    if args.dry_run:
        repo = None
    else:
        repo = PaperRepository(args.state_db)
        repo.init_db()

    if args.once or args.dry_run:
        _run_cycle(args, repo, logger)
        return

    while True:
        try:
            _run_cycle(args, repo, logger)
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
        time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    main()
