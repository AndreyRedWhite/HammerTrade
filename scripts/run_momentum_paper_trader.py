"""Momentum Continuation Paper Trading Daemon — polls T-Bank API and tracks virtual trades.

No real or sandbox orders are placed. Uses READONLY_TOKEN only.
Config-driven design: all parameters loaded from YAML config file.
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

from src.paper.momentum.engine import process_candle_momentum
from src.paper.momentum.models import MomentumDailyContext, MomentumTradeStatus
from src.paper.momentum.repository import MomentumRepository
from src.paper.momentum.status import build_momentum_status, write_momentum_status


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Momentum Continuation Paper trading daemon. No real orders. READONLY_TOKEN only."
    )
    p.add_argument("--config", required=True, help="Path to YAML config file")
    p.add_argument("--once", action="store_true", help="Run one cycle then exit")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch candles, compute features, log signals, but do NOT write to DB or CSV",
    )
    return p.parse_args()


def _load_config(config_path: str) -> dict:
    """Load YAML config and validate required fields."""
    import yaml

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Validate required top-level sections
    required = ["experiment", "signal", "entry", "stop", "take", "exit", "storage", "orders"]
    for key in required:
        if key not in cfg:
            raise ValueError(f"Config missing required section: '{key}'")

    return cfg


def _parse_time(s: str) -> dtime:
    """Parse 'HH:MM' into datetime.time."""
    h, m = s.split(":")
    return dtime(int(h), int(m))


def _setup_logging(log_file: str, experiment_name: str = "") -> logging.Logger:
    label = f"[{experiment_name}]" if experiment_name else "[momentum]"
    logger = logging.getLogger(f"momentum_paper_trader.{experiment_name or 'momentum'}")
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


def _compute_net_pnl(repo: MomentumRepository, ticker: str) -> float:
    trades = repo.list_all_trades(ticker=ticker)
    return sum(
        (t.pnl_rub or 0.0)
        for t in trades
        if t.status == MomentumTradeStatus.CLOSED
    )


def _run_cycle(
    cfg: dict,
    repo: MomentumRepository,
    logger: logging.Logger,
    market_config,
    cycle_state: dict,
    time_exit_msk: dtime,
    dry_run: bool,
    poll_interval_seconds: int,
    api_timeout_sec: int,
):
    exp = cfg["experiment"]
    sig = cfg["signal"]
    storage = cfg["storage"]
    commission = cfg.get("commission", {})

    ticker = exp["ticker"]
    class_code = exp.get("class_code", "SPBFUT")
    timeframe = exp.get("timeframe", "1m")
    experiment_name = exp["name"]
    env = exp.get("env", "prod")
    lookback_candles = exp.get("lookback_candles", 300)

    atr_mult = float(sig["atr_mult"])
    vol_mult = float(sig["vol_mult"])
    atr_window = int(sig.get("atr_window", 14))
    vol_window = int(sig.get("vol_window", 20))
    max_trades_per_day = int(cfg["exit"].get("max_trades_per_day", 1))
    commission_rub = float(commission.get("rub_per_trade", 0.05))
    point_value_rub = float(commission.get("point_value_rub", 10.0))
    take_r = float(cfg["take"]["take_r"])

    now_utc = datetime.now(tz=timezone.utc)
    market_tz = "Europe/Moscow"

    # ── Market hours guard ─────────────────────────────────────────────────────
    session = "unknown"
    market_open = True
    market_config_loaded = market_config is not None and not cfg.get("ignore_market_hours", False)
    if market_config_loaded:
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
                f"msk_time={msk_time.isoformat()} next_cycle_in={poll_interval_seconds}s"
            )
            cycle_state["api_errors"] = 0
            _write_status(cfg, repo, logger, cycle_state, market_open, session,
                          "MARKET_CLOSED", time_exit_msk, dry_run)
            return

    # ── Fetch candles ──────────────────────────────────────────────────────────
    logger.info(f"Fetching {lookback_candles} candles for {ticker} {timeframe}...")
    try:
        df, _ = _fetch_with_timeout(
            ticker, class_code, timeframe,
            lookback_candles, env,
            api_timeout_sec,
        )
        cycle_state["api_errors"] = 0
        cycle_state["last_successful_fetch_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    except concurrent.futures.TimeoutError:
        cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
        cycle_state["total_api_errors"] = cycle_state.get("total_api_errors", 0) + 1
        cycle_state["last_api_error_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        msg = f"API_TIMEOUT ticker={ticker} timeout_sec={api_timeout_sec}"
        cycle_state["last_api_error_message"] = msg
        logger.error(msg)
        _write_status(cfg, repo, logger, cycle_state, market_open, session,
                      "API_TIMEOUT", time_exit_msk, dry_run)
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
        _write_status(cfg, repo, logger, cycle_state, market_open, session,
                      "API_ERROR", time_exit_msk, dry_run)
        return

    if df.empty:
        logger.warning(f"NO_CANDLES ticker={ticker}")
        _write_status(cfg, repo, logger, cycle_state, market_open, session,
                      "NO_CANDLES", time_exit_msk, dry_run)
        return

    logger.info(f"Candles loaded: {len(df)}, last: {df['timestamp'].iloc[-1]}")

    # ── Prepare DataFrame ──────────────────────────────────────────────────────
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    # ── Load daily state ───────────────────────────────────────────────────────
    today_msk = _get_today_msk()
    if not dry_run:
        daily_ctx = repo.load_daily_state(today_msk)
        if daily_ctx is None:
            daily_ctx = MomentumDailyContext(date_msk=today_msk)
        open_trade = repo.get_open_trade(ticker)
    else:
        daily_ctx = MomentumDailyContext(date_msk=today_msk)
        open_trade = None

    # ── Filter new candles ─────────────────────────────────────────────────────
    last_ts_str = daily_ctx.last_processed_candle_ts
    if last_ts_str and not dry_run:
        try:
            last_ts = pd.Timestamp(last_ts_str).tz_convert("UTC")
            new_candles = df[df["timestamp"] > last_ts]
        except Exception:
            new_candles = df.tail(1)
    else:
        new_candles = df.tail(1)

    if new_candles.empty:
        logger.info("No new candles to process. Waiting...")
        _write_status(cfg, repo, logger, cycle_state, market_open, session,
                      "OK", time_exit_msk, dry_run)
        return

    logger.info(f"Processing {len(new_candles)} new candle(s).")

    # ── Process each candle through state machine ──────────────────────────────
    for _, candle in new_candles.iterrows():
        # Build recent_candles context: all rows up to and including this candle
        candle_ts = candle["timestamp"]
        recent_candles = df[df["timestamp"] <= candle_ts].copy()

        updated_ctx, trade_to_upsert, logs = process_candle_momentum(
            candle=candle,
            recent_candles=recent_candles,
            daily_ctx=daily_ctx,
            open_trade=open_trade,
            atr_mult=atr_mult,
            vol_mult=vol_mult,
            take_r=take_r,
            atr_window=atr_window,
            vol_window=vol_window,
            time_exit_msk=time_exit_msk,
            ticker=ticker,
            experiment_name=experiment_name,
            max_trades_per_day=max_trades_per_day,
            commission_rub=commission_rub,
            point_value_rub=point_value_rub,
        )

        for msg in logs:
            logger.info(msg)

        daily_ctx = updated_ctx

        if trade_to_upsert is not None and not dry_run:
            if open_trade is None and trade_to_upsert.status == MomentumTradeStatus.OPEN:
                repo.insert_trade(trade_to_upsert)
                open_trade = trade_to_upsert
                logger.info(
                    f"TRADE_OPENED trade_id={trade_to_upsert.trade_id} "
                    f"entry={trade_to_upsert.entry_price}"
                )
            elif open_trade is not None:
                repo.update_trade(trade_to_upsert)
                if trade_to_upsert.status == MomentumTradeStatus.CLOSED:
                    logger.info(
                        f"TRADE_CLOSED trade_id={trade_to_upsert.trade_id} "
                        f"exit={trade_to_upsert.exit_price} "
                        f"pnl_rub={trade_to_upsert.pnl_rub:.2f} "
                        f"reason={trade_to_upsert.exit_reason}"
                    )
                    open_trade = None
                else:
                    open_trade = trade_to_upsert
        elif trade_to_upsert is not None and dry_run:
            logger.info(f"DRY_RUN: would have {'opened' if trade_to_upsert.status == MomentumTradeStatus.OPEN else 'updated'} trade {trade_to_upsert.trade_id}")

        if not dry_run:
            repo.save_daily_state(daily_ctx)

    # ── Export CSV ─────────────────────────────────────────────────────────────
    if not dry_run:
        repo.export_csv(storage.get("csv_output", "out/paper/paper_trades_momentum.csv"), ticker=ticker)

    # ── Write status ───────────────────────────────────────────────────────────
    _write_status(cfg, repo, logger, cycle_state, market_open, session,
                  "OK", time_exit_msk, dry_run)


def _write_status(
    cfg: dict,
    repo: MomentumRepository,
    logger: logging.Logger,
    cycle_state: dict,
    market_open: bool,
    session: str,
    fetch_status: str,
    time_exit_msk: dtime,
    dry_run: bool,
) -> None:
    """Build and write Momentum status JSON. Also logs liveness transitions."""
    exp = cfg["experiment"]
    sig = cfg["signal"]
    storage = cfg["storage"]

    ticker = exp["ticker"]
    experiment_name = exp["name"]
    direction = sig.get("direction", "SHORT")
    status_file = storage.get("status_file", "runtime/paper_status_momentum.json")

    today_msk = _get_today_msk()
    if not dry_run:
        daily_ctx = repo.load_daily_state(today_msk)
        if daily_ctx is None:
            daily_ctx = MomentumDailyContext(date_msk=today_msk)
        open_trade = repo.get_open_trade(ticker)
        closed_trades = [
            t for t in repo.list_all_trades(ticker=ticker)
            if t.status == MomentumTradeStatus.CLOSED
        ]
        net_pnl = sum(t.pnl_rub or 0.0 for t in closed_trades)
        closed_trades_total = len(closed_trades)
    else:
        daily_ctx = MomentumDailyContext(date_msk=today_msk)
        open_trade = None
        net_pnl = 0.0
        closed_trades_total = 0

    signal_params = {
        "atr_mult": float(sig["atr_mult"]),
        "vol_mult": float(sig["vol_mult"]),
        "atr_window": int(sig.get("atr_window", 14)),
        "vol_window": int(sig.get("vol_window", 20)),
        "close_near_low_pct": float(sig.get("close_near_low_pct", 0.25)),
        "take_r": float(cfg["take"]["take_r"]),
        "time_exit_msk": str(time_exit_msk),
        "max_trades_per_day": int(cfg["exit"].get("max_trades_per_day", 1)),
    }

    status = build_momentum_status(
        ticker=ticker,
        experiment_name=experiment_name,
        direction=direction,
        signal_params=signal_params,
        daily_ctx=daily_ctx,
        open_trade=open_trade,
        closed_trades_total=closed_trades_total,
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

    if not dry_run:
        write_momentum_status(status, status_file)

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

    # Load config
    cfg = _load_config(args.config)

    # Safety check: orders_enabled MUST ALWAYS be False
    orders_enabled = cfg.get("orders", {}).get("orders_enabled", False)
    if orders_enabled:
        print(
            "ERROR: orders_enabled=True is not allowed. "
            "Momentum paper trader is read-only.",
            file=sys.stderr,
        )
        logger_err = logging.getLogger("momentum_paper_trader")
        logger_err.setLevel(logging.ERROR)
        sh = logging.StreamHandler(sys.stderr)
        logger_err.addHandler(sh)
        logger_err.error(
            "SAFETY GUARD: orders_enabled=True detected in config. Exiting immediately."
        )
        sys.exit(1)

    exp = cfg["experiment"]
    sig = cfg["signal"]
    storage = cfg["storage"]
    session_cfg = cfg.get("session", {})

    ticker = exp["ticker"]
    experiment_name = exp["name"]
    log_file = storage.get("log_file", f"logs/paper_{ticker}_MOMENTUM.log")
    state_db = storage.get("state_db", f"data/paper/paper_state_{ticker.lower()}_momentum.sqlite")
    poll_interval_seconds = exp.get("poll_interval_seconds", 30)
    api_timeout_sec = exp.get("api_timeout_sec", 10)

    time_exit_str = cfg["exit"].get("time_exit_msk", "18:40")
    time_exit_msk = _parse_time(time_exit_str)

    logger = _setup_logging(log_file, experiment_name)

    logger.info("=" * 70)
    logger.info("MOMENTUM PAPER TRADER — PAPER MODE ONLY — NO REAL ORDERS")
    logger.info(f"  ticker={ticker} class_code={exp.get('class_code', 'SPBFUT')}")
    logger.info(f"  timeframe={exp.get('timeframe', '1m')} direction={sig.get('direction', 'SHORT')}")
    logger.info(f"  atr_mult={sig['atr_mult']} vol_mult={sig['vol_mult']} take_r={cfg['take']['take_r']}")
    logger.info(f"  atr_window={sig.get('atr_window', 14)} vol_window={sig.get('vol_window', 20)}")
    logger.info(f"  time_exit={time_exit_str} MSK max_trades_per_day={cfg['exit'].get('max_trades_per_day', 1)}")
    logger.info(f"  experiment={experiment_name}")
    logger.info(f"  poll_interval={poll_interval_seconds}s")
    logger.info(f"  state_db={state_db}")
    logger.info(f"  status_file={storage.get('status_file', 'N/A')}")
    logger.info(f"  csv_output={storage.get('csv_output', 'N/A')}")
    logger.info(f"  orders_enabled=False (must be False)")
    if args.dry_run:
        logger.info("  DRY_RUN=True — no DB writes, no CSV exports")
    logger.info("=" * 70)

    # Market hours config
    market_config = None
    market_hours_path = session_cfg.get("market_hours_config", "configs/market_hours/moex_futures.yaml")
    if not cfg.get("ignore_market_hours", False):
        try:
            from src.market.market_hours import load_market_hours_config
            market_config = load_market_hours_config(Path(market_hours_path))
            logger.info(f"  market_hours_config={market_hours_path} tz={market_config.timezone}")
        except FileNotFoundError:
            logger.warning(
                f"Market hours config not found: {market_hours_path}. "
                "Running without market hours guard."
            )
    else:
        logger.info("  Market hours guard disabled by ignore_market_hours=true in config")

    # Init DB (skip in dry-run)
    if not args.dry_run:
        repo = MomentumRepository(state_db)
        repo.init_db()
    else:
        # Still create a repo object (read-only usage for status building)
        import tempfile
        _tmp_db = tempfile.mktemp(suffix=".sqlite")
        repo = MomentumRepository(_tmp_db)
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
        _run_cycle(
            cfg=cfg,
            repo=repo,
            logger=logger,
            market_config=market_config,
            cycle_state=cycle_state,
            time_exit_msk=time_exit_msk,
            dry_run=args.dry_run,
            poll_interval_seconds=poll_interval_seconds,
            api_timeout_sec=api_timeout_sec,
        )
        return

    while True:
        try:
            _run_cycle(
                cfg=cfg,
                repo=repo,
                logger=logger,
                market_config=market_config,
                cycle_state=cycle_state,
                time_exit_msk=time_exit_msk,
                dry_run=args.dry_run,
                poll_interval_seconds=poll_interval_seconds,
                api_timeout_sec=api_timeout_sec,
            )
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    main()
