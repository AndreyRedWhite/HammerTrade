"""Pairs stat-arb Paper Trading Daemon — polls T-Bank API, tracks virtual
market-neutral pref/ordinary spread trades.

NO real or sandbox orders. READONLY_TOKEN only. Two legs per pair; positions
may persist across days. Edge has a thin cost margin → tracks theoretical
(signal close) vs market (next-bar open) fill for live slippage monitoring.

Default basket: SBERP/SBER, TATNP/TATN, SNGSP/SNGS, RTKMP/RTKM.
"""
import argparse
import concurrent.futures
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.pairs.engine import compute_spread_z, process_pair_bar
from src.paper.pairs.models import PairState, PairTradeStatus
from src.paper.pairs.repository import PairsRepository

DEFAULT_PAIRS = "SBERP:SBER,TATNP:TATN,SNGSP:SNGS,RTKMP:RTKM"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pairs stat-arb paper daemon. No real orders. READONLY_TOKEN only."
    )
    p.add_argument("--pairs", default=DEFAULT_PAIRS,
                   help="Comma list of PREF:ORD (e.g. SBERP:SBER,TATNP:TATN)")
    p.add_argument("--class-code", default="TQBR")
    p.add_argument("--bar-timeframe", default="1h",
                   help="Candle timeframe to fetch & trade on (60m validated)")
    p.add_argument("--z-window", type=int, default=50)
    p.add_argument("--entry-z", type=float, default=2.0)
    p.add_argument("--exit-z", type=float, default=0.5)
    p.add_argument("--stop-z", type=float, default=4.0)
    p.add_argument("--hedge-window", type=int, default=None,
                   help="Rolling hedge-ratio window; omitted preserves 1:1 spread")
    p.add_argument("--min-correlation", type=float, default=None)
    p.add_argument("--max-beta-change", type=float, default=None,
                   help="Max relative beta change over hedge_window/4 bars")
    p.add_argument("--stop-loss-bps", type=float, default=None,
                   help="Hard stop on unrealized loss, in bps of ONE leg's notional "
                        "(300 = 3%% = 3000 RUB at 100k/leg). --stop-z cannot bound the "
                        "loss on a trending spread: the rolling mean chases the drift, "
                        "so z decays while the position bleeds. Off by default.")
    p.add_argument("--max-hold-bars", type=int, default=45,
                   help="~5 trading days at 60m (9 bars/day)")
    p.add_argument("--notional-per-leg", type=float, default=100_000.0)
    # 5.0 = measured from sandbox fills (commission is exactly proportional to notional,
    # so a round-trip costs 4 x 5.0 = 20bps of one leg's notional regardless of size).
    p.add_argument("--cost-bps-per-leg-side", type=float, default=5.0)
    p.add_argument("--lookback-minutes", type=int, default=20160,
                   help="History to fetch per leg (default 14 days → ~70+ hourly bars)")
    p.add_argument("--state-db", default="data/paper/paper_state_pairs_basket.sqlite")
    p.add_argument("--status-file", default="runtime/paper_status_PAIRS_BASKET.json")
    p.add_argument("--csv-output", default="out/paper/paper_trades_PAIRS_BASKET.csv")
    p.add_argument("--log-file", default="logs/paper_PAIRS_BASKET.log")
    p.add_argument("--experiment-name", default="pairs_basket_e2.0_x0.5_60m")
    p.add_argument("--poll-interval-seconds", type=int, default=300)
    p.add_argument("--env", default="prod")
    p.add_argument("--once", action="store_true")
    p.add_argument("--market-hours-config",
                   default="configs/market_hours/moex_equities.yaml")
    p.add_argument("--ignore-market-hours", action="store_true")
    p.add_argument("--api-timeout-sec", type=int, default=15)
    return p.parse_args()


def _setup_logging(log_file: str, experiment_name: str) -> logging.Logger:
    logger = logging.getLogger(f"pairs_paper_trader.{experiment_name}")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(f"%(asctime)s %(levelname)s [{experiment_name}] %(message)s")
    if not logger.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def _fetch_leg(ticker, class_code, timeframe, lookback_minutes, env, timeout_sec):
    from src.paper.market_data import fetch_recent_candles
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fetch_recent_candles, ticker, class_code, timeframe, lookback_minutes, env)
    ex.shutdown(wait=False)
    df, _ = fut.result(timeout=timeout_sec)
    return df


def _closed_bars(pair_df: pd.DataFrame, bar_minutes: int, now_utc: datetime) -> pd.DataFrame:
    """Keep only fully-closed bars (bar end <= now)."""
    if pair_df.empty:
        return pair_df
    horizon = now_utc - timedelta(minutes=bar_minutes)
    return pair_df[pair_df["timestamp"] <= horizon].reset_index(drop=True)


def _bar_minutes(timeframe: str) -> int:
    tf = timeframe.lower()
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("m") or tf.endswith("min"):
        return int(tf.replace("min", "").replace("m", ""))
    return 60


def _process_pair(args, repo, logger, pref, ordn, now_utc) -> dict:
    pair_name = ordn  # use ordinary ticker as pair label (SBER, TATN, ...)

    pref_df = _fetch_leg(pref, args.class_code, args.bar_timeframe,
                         args.lookback_minutes, args.env, args.api_timeout_sec)
    ord_df = _fetch_leg(ordn, args.class_code, args.bar_timeframe,
                        args.lookback_minutes, args.env, args.api_timeout_sec)
    if pref_df is None or ord_df is None or pref_df.empty or ord_df.empty:
        logger.warning(f"NO_CANDLES pair={pair_name} pref_empty={pref_df is None or pref_df.empty} "
                       f"ord_empty={ord_df is None or ord_df.empty}")
        return {"pair": pair_name, "status": "NO_CANDLES"}

    # fetched bars are already at bar-timeframe → no further resample
    pair_df = compute_spread_z(
        pref_df, ord_df, timeframe="1min", z_window=args.z_window,
        hedge_window=args.hedge_window, min_correlation=args.min_correlation,
        max_beta_change=args.max_beta_change,
    )
    pair_df = _closed_bars(pair_df, _bar_minutes(args.bar_timeframe), now_utc)
    if pair_df.empty:
        return {"pair": pair_name, "status": "NO_CLOSED_BARS"}

    state = repo.load_state(pair_name) or PairState(pair_name=pair_name)
    open_trade = repo.get_open_trade(pair_name)

    last_ts = pd.Timestamp(state.last_processed_bar_ts).tz_convert("UTC") \
        if state.last_processed_bar_ts else None
    new_bars = pair_df[pair_df["timestamp"] > last_ts] if last_ts is not None else pair_df.tail(1)

    for _, bar in new_bars.iterrows():
        trade_to_upsert, logs = process_pair_bar(
            bar, open_trade,
            pair_name=pair_name, pref_ticker=pref, ord_ticker=ordn,
            entry_z=args.entry_z, exit_z=args.exit_z, stop_z=args.stop_z,
            max_hold_bars=args.max_hold_bars,
            notional_per_leg=args.notional_per_leg,
            cost_bps_per_leg_side=args.cost_bps_per_leg_side,
            experiment_name=args.experiment_name,
            stop_loss_bps=args.stop_loss_bps,
        )
        for m in logs:
            logger.info(m)
        if trade_to_upsert is not None:
            if open_trade is None and trade_to_upsert.status == PairTradeStatus.OPEN:
                repo.insert_trade(trade_to_upsert)
                open_trade = trade_to_upsert
            else:
                repo.update_trade(trade_to_upsert)
                open_trade = None if trade_to_upsert.status == PairTradeStatus.CLOSED else trade_to_upsert

        state.last_processed_bar_ts = str(pd.Timestamp(bar["timestamp"]).isoformat())
        repo.save_state(state)

    latest_z = float(pair_df["z"].iloc[-1]) if not pd.isna(pair_df["z"].iloc[-1]) else None
    return {"pair": pair_name, "status": "OK", "latest_z": latest_z,
            "has_open": open_trade is not None}


def _write_status(args, repo, pair_results, market_open, session, fetch_status):
    closed = [t for t in repo.list_all_trades() if t.status == PairTradeStatus.CLOSED]
    net_theo = sum(t.pnl_rub or 0.0 for t in closed)
    net_mkt = sum(t.pnl_rub_market for t in closed if t.pnl_rub_market is not None)
    # The only figure that prices BOTH ends at a tradeable price. Reported
    # alongside the weaker two so the gap between them stays visible.
    net_real = sum(t.pnl_rub_realistic for t in closed if t.pnl_rub_realistic is not None)
    n_real = sum(1 for t in closed if t.pnl_rub_realistic is not None)
    # PENDING_EXIT is still a held position, so it counts as open here.
    open_trades = [t for t in repo.list_all_trades()
                   if t.status in (PairTradeStatus.OPEN, PairTradeStatus.PENDING_EXIT)]
    status = {
        "strategy": "pairs_statarb",
        "experiment_name": args.experiment_name,
        "pairs": args.pairs,
        "params": {"z_window": args.z_window, "entry_z": args.entry_z,
                   "exit_z": args.exit_z, "stop_z": args.stop_z,
                   "hedge_window": args.hedge_window,
                   "min_correlation": args.min_correlation,
                   "max_beta_change": args.max_beta_change,
                   "max_hold_bars": args.max_hold_bars,
                   "bar_timeframe": args.bar_timeframe,
                   "cost_bps_per_leg_side": args.cost_bps_per_leg_side},
        "market_open": market_open,
        "session": session,
        "fetch_status": fetch_status,
        "per_pair": pair_results,
        "open_trades_total": len(open_trades),
        "closed_trades_total": len(closed),
        "net_pnl_theoretical_rub": round(net_theo, 1),
        "net_pnl_market_rub": round(net_mkt, 1),
        # The one a funnel verdict may use.
        "net_pnl_realistic_rub": round(net_real, 1),
        "trades_with_realistic_pnl": n_real,
        "pid": os.getpid(),
        "updated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    Path(args.status_file).parent.mkdir(parents=True, exist_ok=True)
    with open(args.status_file, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, default=str)


def _run_cycle(args, repo, logger, market_config, cycle_state, pairs):
    now_utc = datetime.now(tz=timezone.utc)
    session, market_open = "unknown", True
    if not args.ignore_market_hours and market_config:
        from src.market.market_hours import is_session_open, get_session_name, to_market_timezone
        session = get_session_name(now_utc, market_config)
        market_open = is_session_open(now_utc, market_config)
        if not market_open:
            msk = to_market_timezone(now_utc, market_config)
            logger.info(f"MARKET_CLOSED session={session} msk_time={msk.isoformat()}")
            _write_status(args, repo, [], market_open, session, "MARKET_CLOSED")
            return

    results = []
    for pref, ordn in pairs:
        try:
            results.append(_process_pair(args, repo, logger, pref, ordn, now_utc))
        except concurrent.futures.TimeoutError:
            logger.error(f"API_TIMEOUT pair={ordn}")
            results.append({"pair": ordn, "status": "API_TIMEOUT"})
        except Exception as e:
            logger.error(f"PAIR_ERROR pair={ordn} error={e}", exc_info=True)
            results.append({"pair": ordn, "status": "ERROR"})

    repo.export_csv(args.csv_output)
    _write_status(args, repo, results, market_open, session, "OK")


def main():
    load_dotenv()
    args = _parse_args()
    pairs = [tuple(p.split(":")) for p in args.pairs.split(",") if ":" in p]

    logger = _setup_logging(args.log_file, args.experiment_name)
    logger.info("=" * 60)
    logger.info("Pairs Stat-Arb Paper Trader — PAPER ONLY — NO REAL ORDERS")
    logger.info(f"  pairs={pairs}")
    logger.info(f"  bar_tf={args.bar_timeframe} z_window={args.z_window} "
                f"entry_z={args.entry_z} exit_z={args.exit_z} stop_z={args.stop_z} "
                f"max_hold={args.max_hold_bars} stop_loss_bps={args.stop_loss_bps}")
    logger.info(f"  notional/leg={args.notional_per_leg} cost_bps={args.cost_bps_per_leg_side}")
    logger.info(f"  experiment={args.experiment_name}")
    logger.info("=" * 60)

    market_config = None
    if not args.ignore_market_hours:
        try:
            from src.market.market_hours import load_market_hours_config
            market_config = load_market_hours_config(Path(args.market_hours_config))
            logger.info(f"  market_hours={args.market_hours_config} tz={market_config.timezone}")
        except FileNotFoundError:
            logger.warning(f"Market hours config not found: {args.market_hours_config}. No guard.")

    repo = PairsRepository(args.state_db)
    repo.init_db()
    cycle_state: dict = {}

    if args.once:
        _run_cycle(args, repo, logger, market_config, cycle_state, pairs)
        return

    while True:
        try:
            _run_cycle(args, repo, logger, market_config, cycle_state, pairs)
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
        time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    main()
