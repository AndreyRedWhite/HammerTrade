"""Sandbox order-placement runner — Hammer MaxHold5, SiU6 SELL (MVP-L1a).

SANDBOX CONTOUR ONLY. This script never places live/prod orders and refuses
to start (validate_safety) if the config or environment looks like it could.

It reuses the UNCHANGED hammer-maxhold5 signal/entry/exit state machine via
src.sandbox.engine.process_sandbox_candle (which wraps
src.paper.engine.process_candle), so the trading logic is identical to the
existing paper control service hammertrade-paper-maxhold5.service. That
paper service is a read-only reference here: this script never starts,
stops, or modifies it, and never writes to its database/state.

Candle data is fetched via env="prod" (READONLY_TOKEN), exactly like the
paper traders. SANDBOX_TOKEN / SANDBOX_ACCOUNT_ID are used only for sandbox
order placement (src.sandbox.broker.SandboxBroker) and only when --dry-run
is not set.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_params
from src.strategy.hammer_detector import HammerDetector
from src.sandbox.broker import get_sandbox_broker
from src.sandbox.engine import expected_position_from_trade, process_sandbox_candle
from src.sandbox.models import (
    SandboxFill,
    SandboxOrder,
    SandboxOrderStatus,
    SandboxPosition,
    SandboxTrade,
    SandboxTradeStatus,
)
from src.sandbox.reconciliation import position_from_signed_qty, reconcile_position
from src.sandbox.repository import SandboxRepository
from src.sandbox.risk import RiskLimits, RiskManager
from src.sandbox.status import build_sandbox_status, write_sandbox_status


class ConfigError(SystemExit):
    """Hard-fail before any API/order call. Always prefixed "CONFIG ERROR: "."""

    def __init__(self, message: str):
        super().__init__(f"CONFIG ERROR: {message}")


def _parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Sandbox order-placement runner for hammer-maxhold5 (SiU6, SELL). "
            "Places orders on the T-Bank SANDBOX CONTOUR ONLY. Never live."
        )
    )
    p.add_argument("--config", required=True, help="Path to sandbox YAML config")
    p.add_argument(
        "--dry-run", action="store_true",
        help="Fetch candles and log detector output only; no DB, broker, or order access",
    )
    p.add_argument("--once", action="store_true", help="Run one cycle then exit")
    p.add_argument(
        "--max-cycles", type=int, default=None,
        help="Stop after N cycles (mainly for testing; default: run forever)",
    )
    return p.parse_args()


def _load_config(path: str) -> dict:
    if not os.path.exists(path):
        raise ConfigError(f"config file not found: {path}")
    with open(path) as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ConfigError(f"config file is empty or invalid: {path}")
    return cfg


def validate_safety(cfg: dict) -> None:
    """Hard-fail if this config could ever place a real/live order.

    Applies in ALL modes, including --dry-run, and before any API call.
    """
    mode = cfg.get("mode")
    if mode != "sandbox":
        raise ConfigError(
            f"mode={mode!r} is not allowed. Only mode: sandbox is supported "
            "(live trading is not implemented in MVP-L1a)."
        )

    orders = cfg.get("orders", {})
    environment = orders.get("environment")
    if environment != "sandbox":
        raise ConfigError(
            f"orders.environment={environment!r} is not allowed. "
            "Only orders.environment: sandbox is supported in MVP-L1a."
        )

    if orders.get("real_orders_enabled"):
        raise ConfigError(
            "orders.real_orders_enabled=true is not allowed. "
            "MVP-L1a never places real orders."
        )

    if os.getenv("TINVEST_LIVE_TRADING_TOKEN"):
        raise ConfigError(
            "TINVEST_LIVE_TRADING_TOKEN is set in the environment. Refusing to "
            "start while a live trading token is configured."
        )


def check_token_and_account(cfg: dict) -> str:
    """Hard-fail if the sandbox token or account id is missing. Returns account_id.

    Only called in non-dry-run mode.
    """
    orders = cfg.get("orders", {})
    token_env = orders.get("token_env", "SANDBOX_TOKEN")
    account_env = orders.get("account_id_env", "SANDBOX_ACCOUNT_ID")

    if not os.getenv(token_env, ""):
        raise ConfigError(
            f"{token_env} is not set. Add it to your .env file. "
            "Refusing to start without a sandbox token (use --dry-run to test without one)."
        )

    account_id = os.getenv(account_env, "")
    if not account_id:
        raise ConfigError(
            f"{account_env} is not set. Run scripts/sandbox_account_setup.py to "
            "create/select a sandbox account, then set it in your .env file."
        )

    return account_id


def _setup_logging(log_file: str, dry_run: bool) -> logging.Logger:
    logger = logging.getLogger("sandbox_hammer_maxhold5")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [sandbox_hammer_maxhold5] %(message)s")
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


def _state_key(ticker: str) -> str:
    return f"last_processed:{ticker}"


def _signal_key(ticker: str) -> str:
    return f"pending_signal:{ticker}"


def _load_pending_signal(repo: SandboxRepository, ticker: str) -> Optional[dict]:
    raw = repo.get_state(_signal_key(ticker))
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _save_pending_signal(repo: SandboxRepository, signal: Optional[dict], ticker: str) -> None:
    repo.set_state(_signal_key(ticker), "" if signal is None else json.dumps(signal))


def _today_msk(now_utc: Optional[datetime] = None) -> str:
    if now_utc is None:
        now_utc = datetime.now(tz=timezone.utc)
    return now_utc.astimezone(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d")


def _fetch_with_timeout(ticker, class_code, timeframe, lookback_candles, timeout_sec):
    """Fetch candles via env="prod" (READONLY_TOKEN) with a thread-based timeout."""
    from src.paper.market_data import fetch_recent_candles
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = executor.submit(fetch_recent_candles, ticker, class_code, timeframe, lookback_candles, "prod")
    executor.shutdown(wait=False)
    return fut.result(timeout=timeout_sec)


def _load_instrument_from_catalog(ticker: str, class_code: str) -> Optional[dict]:
    from src.tbank.instruments import INSTRUMENTS_CSV
    if not os.path.exists(INSTRUMENTS_CSV):
        return None
    df = pd.read_csv(INSTRUMENTS_CSV, dtype=str)
    matches = df[(df["ticker"] == ticker) & (df["class_code"] == class_code)]
    if matches.empty:
        return None
    row = matches.iloc[0]
    return {"uid": row["uid"], "figi": row["figi"], "lot": int(float(row["lot"]))}


def _resolve_instrument(ticker: str, class_code: str) -> dict:
    """Resolve instrument uid/figi/lot for order placement.

    Prefers the local catalog populated by candle fetches (env=prod /
    READONLY_TOKEN), falling back to a direct prod lookup if not yet cached.
    """
    cached = _load_instrument_from_catalog(ticker, class_code)
    if cached:
        return cached

    from src.tbank.client import get_tbank_client
    from src.tbank.settings import load_tbank_settings
    from src.tbank.instruments import resolve_instrument

    settings = load_tbank_settings(env="prod")
    with get_tbank_client(settings) as client:
        return resolve_instrument(client, ticker, class_code)


@dataclass
class RunnerContext:
    cfg: dict
    dry_run: bool
    ticker: str
    class_code: str
    timeframe: str
    profile: str
    direction: str
    params_file: str
    engine_kwargs: dict
    market_config: object
    repo: Optional[SandboxRepository]
    risk_manager: RiskManager
    account_id: Optional[str]
    instrument: Optional[dict]
    status_path: str
    trades_csv: str
    orders_csv: str
    lookback_candles: int
    api_timeout_sec: int
    poll_interval_seconds: int
    margin_per_lot_rub: float
    logger: logging.Logger


def _build_context(cfg: dict, dry_run: bool, logger: logging.Logger) -> RunnerContext:
    ticker = cfg["ticker"]
    class_code = cfg["class_code"]
    timeframe = cfg["timeframe"]
    profile = cfg["profile"]
    direction = cfg["direction"].upper()

    engine_kwargs = dict(
        direction_filter=direction,
        entry_mode=cfg.get("entry_mode", "breakout"),
        entry_horizon_bars=cfg.get("entry_horizon_bars", 3),
        max_hold_bars=cfg.get("max_hold_bars", 5),
        take_r=cfg.get("take_r", 1.0),
        stop_buffer_points=cfg.get("stop_buffer_points", 0.0),
        slippage_ticks=cfg.get("slippage_ticks", 1.0),
        contracts=cfg.get("contracts", 1),
        ticker=ticker,
        class_code=class_code,
        timeframe=timeframe,
        profile=profile,
        experiment_name="sandbox_hammer_maxhold5",
    )

    market_config = None
    market_cfg_path = cfg.get("session", {}).get("market_hours_config")
    if market_cfg_path:
        from src.market.market_hours import load_market_hours_config
        try:
            market_config = load_market_hours_config(Path(market_cfg_path))
        except FileNotFoundError:
            logger.warning(
                f"Market hours config not found: {market_cfg_path}. "
                "Running without market hours guard."
            )

    fetch_cfg = cfg.get("fetch", {})
    artifacts = cfg.get("artifacts", {})
    risk_cfg = cfg.get("risk", {})

    risk_limits = RiskLimits(
        capital_budget_rub=risk_cfg["capital_budget_rub"],
        max_position_notional_rub=risk_cfg["max_position_notional_rub"],
        max_order_notional_rub=risk_cfg["max_order_notional_rub"],
        max_daily_loss_rub=risk_cfg["max_daily_loss_rub"],
        max_total_loss_rub=risk_cfg["max_total_loss_rub"],
        max_trades_per_day=risk_cfg["max_trades_per_day"],
        max_consecutive_errors=risk_cfg["max_consecutive_errors"],
        max_consecutive_losses=risk_cfg["max_consecutive_losses"],
        max_open_positions_per_strategy=risk_cfg["max_open_positions_per_strategy"],
        kill_switch_file=risk_cfg["kill_switch_file"],
        max_exit_retries=risk_cfg.get("max_exit_retries", 3),
    )

    repo = None
    account_id = None
    if not dry_run:
        repo = SandboxRepository(artifacts["db"])
        repo.init_db()
        account_id = check_token_and_account(cfg)

    return RunnerContext(
        cfg=cfg,
        dry_run=dry_run,
        ticker=ticker,
        class_code=class_code,
        timeframe=timeframe,
        profile=profile,
        direction=direction,
        params_file=cfg.get("params_file", "configs/hammer_detector_balanced.env"),
        engine_kwargs=engine_kwargs,
        market_config=market_config,
        repo=repo,
        risk_manager=RiskManager(risk_limits),
        account_id=account_id,
        instrument=None,
        status_path=artifacts.get("status", f"runtime/sandbox_status_hammer_maxhold5_{ticker}.json"),
        trades_csv=artifacts.get("trades_csv", f"out/sandbox/sandbox_trades_hammer_maxhold5_{ticker}.csv"),
        orders_csv=artifacts.get("orders_csv", f"out/sandbox/sandbox_orders_hammer_maxhold5_{ticker}.csv"),
        lookback_candles=fetch_cfg.get("lookback_candles", 300),
        api_timeout_sec=fetch_cfg.get("api_timeout_sec", 10),
        poll_interval_seconds=fetch_cfg.get("poll_interval_seconds", 20),
        margin_per_lot_rub=risk_cfg.get("margin_per_lot_rub", 0.0),
        logger=logger,
    )


def _compute_trading_state(risk_state, open_trade, pending_signal, kill_switch_active) -> str:
    if kill_switch_active:
        return "KILL_SWITCH_ACTIVE"
    if risk_state.reconciliation_status != "OK":
        return "RECONCILIATION_FAILED"
    if risk_state.trading_paused:
        return "TRADING_PAUSED"
    if open_trade is not None and open_trade.status == SandboxTradeStatus.OPEN:
        return "IN_POSITION"
    if pending_signal is not None:
        return "PENDING_ENTRY"
    return "WAITING_FOR_SIGNAL"


def _write_status(
    ctx: RunnerContext,
    cycle_state: dict,
    *,
    trading_state: str,
    market_open: bool,
    kill_switch_active: bool,
    risk_state=None,
    daily=None,
    open_trade=None,
    pending_signal=None,
    open_positions_actual: int = 0,
    open_orders: int = 0,
    reconciliation_status: Optional[str] = None,
) -> None:
    from src.sandbox.models import SandboxDailyRisk, SandboxRiskState

    if risk_state is None:
        risk_state = SandboxRiskState()
    if daily is None:
        daily = SandboxDailyRisk(date_msk=_today_msk())

    orders_cfg = ctx.cfg.get("orders", {})
    token_env = orders_cfg.get("token_env", "SANDBOX_TOKEN")
    account_env = orders_cfg.get("account_id_env", "SANDBOX_ACCOUNT_ID")

    open_positions_expected = (
        1 if (open_trade is not None and open_trade.status == SandboxTradeStatus.OPEN) else 0
    )

    status = build_sandbox_status(
        strategy="hammer_maxhold5",
        ticker=ctx.ticker,
        direction=ctx.direction,
        max_hold_bars=ctx.engine_kwargs["max_hold_bars"],
        orders_enabled=orders_cfg.get("enabled", False),
        real_orders_enabled=orders_cfg.get("real_orders_enabled", False),
        paper_control_service=ctx.cfg.get("paper_control_service", "hammertrade-paper-maxhold5.service"),
        trading_state=trading_state,
        kill_switch_active=kill_switch_active,
        sandbox_account_id_present=bool(os.getenv(account_env, "")),
        token_present=bool(os.getenv(token_env, "")),
        open_positions_expected=open_positions_expected,
        open_positions_actual=open_positions_actual,
        open_orders=open_orders,
        daily_pnl_rub=daily.realized_pnl_rub,
        total_pnl_rub=risk_state.total_pnl_rub,
        daily_loss_limit_rub=ctx.risk_manager.limits.max_daily_loss_rub,
        total_loss_limit_rub=ctx.risk_manager.limits.max_total_loss_rub,
        trades_today=daily.trades_today,
        max_trades_per_day=ctx.risk_manager.limits.max_trades_per_day,
        reconciliation_status=reconciliation_status or risk_state.reconciliation_status,
        market_open=market_open,
        consecutive_api_errors=cycle_state.get("api_errors", 0),
        last_successful_fetch_at=cycle_state.get("last_successful_fetch_at"),
        market_open_since=cycle_state.get("market_open_at"),
        last_successful_reconciliation_at=cycle_state.get("last_successful_reconciliation_at"),
        last_order_event_at=cycle_state.get("last_order_event_at"),
        last_error_at=cycle_state.get("last_error_at"),
        last_error_message=cycle_state.get("last_error_message"),
        pid=os.getpid(),
    )
    write_sandbox_status(status, ctx.status_path)


def _handle_entry(ctx: RunnerContext, cycle_state: dict, trade: SandboxTrade, risk_state, daily) -> None:
    repo = ctx.repo
    logger = ctx.logger
    ticker = ctx.ticker
    now_utc = datetime.now(tz=timezone.utc)

    margin_rub = ctx.margin_per_lot_rub * trade.qty
    open_positions = 1 if repo.get_open_trade(ticker) is not None else 0

    check = ctx.risk_manager.check_pre_trade(
        risk_state=risk_state, daily_risk=daily, open_positions=open_positions,
        order_notional_rub=margin_rub, position_notional_rub=margin_rub,
    )
    if not check.allowed:
        logger.warning(f"RISK_BLOCK entry trade_id={trade.trade_id} reason={check.reason}")
        repo.insert_event(
            event_id=f"risk_block:{trade.trade_id}", ticker=ticker, event_type="RISK_BLOCK",
            message=f"Entry blocked: {check.reason}",
        )
        cycle_state["last_error_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        cycle_state["last_error_message"] = f"risk_block_entry: {check.reason}"
        return

    # internal_order_id: our own journal id (free-form). Must NOT be sent to the
    # T-Bank API, which requires order_id to be empty or a UUID.
    order_id = f"sandbox:{ticker}:entry:{uuid.uuid4().hex[:12]}"
    # broker idempotency key: a real UUID sent to the API as its order_id.
    idempotency_key = str(uuid.uuid4())
    order = SandboxOrder(
        order_id=order_id,
        signal_id=trade.signal_id,
        strategy="hammer_maxhold5",
        ticker=ticker,
        figi=ctx.instrument["figi"] if ctx.instrument else None,
        instrument_uid=ctx.instrument["uid"] if ctx.instrument else None,
        direction=trade.direction,
        order_side=trade.direction,
        order_type="MARKET",
        requested_qty=trade.qty,
        requested_price=None,
        submitted_at=now_utc,
        status=SandboxOrderStatus.SUBMITTED,
    )

    try:
        with get_sandbox_broker() as broker:
            result = broker.post_order(
                account_id=ctx.account_id,
                instrument_uid=ctx.instrument["uid"],
                quantity_lots=trade.qty,
                direction=trade.direction,
                order_type="MARKET",
                idempotency_key=idempotency_key,
            )
    except Exception as e:
        order.status = SandboxOrderStatus.ERROR
        repo.insert_order(order)
        ctx.risk_manager.update_after_error(risk_state)
        repo.save_risk_state(risk_state)
        msg = f"ORDER_ERROR entry trade_id={trade.trade_id} error={e}"
        logger.error(msg)
        repo.insert_event(event_id=f"order_error:{order_id}", ticker=ticker, event_type="ERROR", message=msg)
        cycle_state["last_error_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        cycle_state["last_error_message"] = msg
        return

    if result.lots_executed >= trade.qty:
        order.status = SandboxOrderStatus.FILLED
    elif result.lots_executed > 0:
        order.status = SandboxOrderStatus.PARTIALLY_FILLED
    else:
        order.status = SandboxOrderStatus.SUBMITTED
    order.filled_qty = result.lots_executed
    order.avg_fill_price = result.executed_price
    order.commission_rub = result.commission_rub

    trade.entry_order_id = order_id

    repo.insert_order(order)
    if result.executed_price is not None:
        repo.insert_fill(SandboxFill(
            fill_id=f"fill:{order_id}", order_id=order_id, ticker=ticker,
            direction=trade.direction, qty=result.lots_executed,
            price=result.executed_price, commission_rub=result.commission_rub or 0.0,
            fill_time=now_utc,
        ))
    repo.insert_trade(trade)

    position_direction = "SHORT" if trade.direction == "SELL" else "LONG"
    repo.upsert_position(SandboxPosition(
        ticker=ticker,
        figi=ctx.instrument["figi"] if ctx.instrument else None,
        instrument_uid=ctx.instrument["uid"] if ctx.instrument else None,
        direction=position_direction, qty=trade.qty, avg_price=trade.entry_price,
    ))

    repo.insert_event(
        event_id=f"entry:{trade.trade_id}", ticker=ticker, event_type="ENTRY",
        message=f"Sandbox entry: {trade.trade_id} order={order_id} status={order.status.value}",
    )

    ctx.risk_manager.reset_errors(risk_state)
    ctx.risk_manager.reset_exit_errors(risk_state)
    repo.save_risk_state(risk_state)
    cycle_state["last_order_event_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info(f"ENTRY trade_id={trade.trade_id} order={order_id} status={order.status.value} qty={trade.qty}")


def _handle_exit(ctx: RunnerContext, cycle_state: dict, trade: SandboxTrade, risk_state, daily) -> None:
    repo = ctx.repo
    logger = ctx.logger
    ticker = ctx.ticker
    now_utc = datetime.now(tz=timezone.utc)

    # Exit retry cap: exits bypass check_pre_trade, so an unfillable close
    # (e.g. sandbox "Not enough balance") would otherwise retry every cycle
    # forever. After max_exit_retries failures, pause and require manual
    # intervention (close the position by hand, then reset state).
    if ctx.risk_manager.exit_retries_exhausted(risk_state):
        if not risk_state.trading_paused:
            risk_state.trading_paused = True
            risk_state.trading_paused_reason = "max_exit_retries_exceeded"
            repo.save_risk_state(risk_state)
        msg = (
            f"EXIT_RETRIES_EXHAUSTED trade_id={trade.trade_id} "
            f"exit_error_count={risk_state.exit_error_count} — position left OPEN, "
            f"manual close required"
        )
        logger.error(msg)
        repo.insert_event(
            event_id=f"exit_retries_exhausted:{trade.trade_id}", ticker=ticker,
            event_type="RISK_BLOCK", message=msg,
        )
        cycle_state["last_error_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        cycle_state["last_error_message"] = msg
        return

    exit_side = "BUY" if trade.direction == "SELL" else "SELL"
    # internal_order_id (journal) vs broker idempotency key (UUID for the API).
    order_id = f"sandbox:{ticker}:exit:{uuid.uuid4().hex[:12]}"
    idempotency_key = str(uuid.uuid4())
    order = SandboxOrder(
        order_id=order_id,
        signal_id=trade.signal_id,
        strategy="hammer_maxhold5",
        ticker=ticker,
        figi=ctx.instrument["figi"] if ctx.instrument else None,
        instrument_uid=ctx.instrument["uid"] if ctx.instrument else None,
        direction=trade.direction,
        order_side=exit_side,
        order_type="MARKET",
        requested_qty=trade.qty,
        requested_price=None,
        submitted_at=now_utc,
        status=SandboxOrderStatus.SUBMITTED,
    )

    try:
        with get_sandbox_broker() as broker:
            result = broker.post_order(
                account_id=ctx.account_id,
                instrument_uid=ctx.instrument["uid"],
                quantity_lots=trade.qty,
                direction=exit_side,
                order_type="MARKET",
                idempotency_key=idempotency_key,
            )
    except Exception as e:
        order.status = SandboxOrderStatus.ERROR
        repo.insert_order(order)
        ctx.risk_manager.update_after_error(risk_state)
        ctx.risk_manager.record_exit_error(risk_state)
        repo.save_risk_state(risk_state)
        msg = f"ORDER_ERROR exit trade_id={trade.trade_id} error={e}"
        logger.error(msg)
        repo.insert_event(event_id=f"order_error:{order_id}", ticker=ticker, event_type="ERROR", message=msg)
        cycle_state["last_error_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        cycle_state["last_error_message"] = msg
        # Trade stays OPEN in our journal (update_trade is not called) so the
        # next cycle retries the exit order.
        return

    if result.lots_executed >= trade.qty:
        order.status = SandboxOrderStatus.FILLED
    elif result.lots_executed > 0:
        order.status = SandboxOrderStatus.PARTIALLY_FILLED
    else:
        order.status = SandboxOrderStatus.SUBMITTED
    order.filled_qty = result.lots_executed
    order.avg_fill_price = result.executed_price
    order.commission_rub = result.commission_rub

    trade.exit_order_id = order_id

    repo.insert_order(order)
    if result.executed_price is not None:
        repo.insert_fill(SandboxFill(
            fill_id=f"fill:{order_id}", order_id=order_id, ticker=ticker,
            direction=exit_side, qty=result.lots_executed,
            price=result.executed_price, commission_rub=result.commission_rub or 0.0,
            fill_time=now_utc,
        ))
    repo.update_trade(trade)

    repo.upsert_position(SandboxPosition(
        ticker=ticker,
        figi=ctx.instrument["figi"] if ctx.instrument else None,
        instrument_uid=ctx.instrument["uid"] if ctx.instrument else None,
        direction="FLAT", qty=0, avg_price=None,
    ))

    exit_reason = trade.exit_reason.value if trade.exit_reason else "unknown"
    repo.insert_event(
        event_id=f"exit:{trade.trade_id}:{exit_reason}", ticker=ticker, event_type="EXIT",
        message=f"Sandbox exit: {trade.trade_id} order={order_id} reason={exit_reason} pnl={trade.net_pnl_rub}",
    )

    ctx.risk_manager.update_after_trade(risk_state, daily, trade.net_pnl_rub or 0.0)
    ctx.risk_manager.reset_errors(risk_state)
    ctx.risk_manager.reset_exit_errors(risk_state)
    repo.save_risk_state(risk_state)
    repo.save_daily_risk(daily)
    cycle_state["last_order_event_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info(f"EXIT trade_id={trade.trade_id} order={order_id} status={order.status.value} pnl={trade.net_pnl_rub}")


def _process_one_candle(ctx: RunnerContext, cycle_state: dict, candle: pd.Series, engine_kwargs: dict) -> None:
    repo = ctx.repo
    ticker = ctx.ticker

    risk_state = repo.load_risk_state()
    daily = repo.load_daily_risk(_today_msk())
    pending_signal = _load_pending_signal(repo, ticker)
    open_trade = repo.get_open_trade(ticker)

    result = process_sandbox_candle(
        candle=candle,
        open_trade=open_trade,
        pending_signal=pending_signal,
        **engine_kwargs,
    )

    for msg in result.logs:
        ctx.logger.info(msg)

    _save_pending_signal(repo, result.pending_signal, ticker)

    if result.decision == "ENTRY":
        _handle_entry(ctx, cycle_state, result.trade, risk_state, daily)
    elif result.decision == "HOLD":
        repo.update_trade(result.trade)
    elif result.decision == "EXIT":
        _handle_exit(ctx, cycle_state, result.trade, risk_state, daily)


def _reconcile(ctx: RunnerContext, cycle_state: dict) -> int:
    """Compare the bot's expected position vs the sandbox account's actual position.

    Returns the actual open lot count for the instrument (0 if flat or unknown).
    On mismatch, marks reconciliation_status=RECONCILIATION_FAILED, which blocks
    new entries via RiskManager.check_pre_trade.
    """
    repo = ctx.repo
    logger = ctx.logger
    now_utc = datetime.now(tz=timezone.utc)

    if ctx.instrument is None:
        return 0

    open_trade = repo.get_open_trade(ctx.ticker)
    expected = expected_position_from_trade(open_trade)

    try:
        with get_sandbox_broker() as broker:
            positions = broker.get_positions(ctx.account_id)
    except Exception as e:
        risk_state = repo.load_risk_state()
        ctx.risk_manager.update_after_error(risk_state)
        repo.save_risk_state(risk_state)
        msg = f"RECONCILIATION_FETCH_ERROR error={e}"
        logger.error(msg)
        cycle_state["last_error_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        cycle_state["last_error_message"] = msg
        return 0

    figi = ctx.instrument.get("figi")
    signed_qty = sum(p.balance for p in positions if p.figi == figi)
    actual = position_from_signed_qty(signed_qty)

    check = reconcile_position(expected, actual)
    risk_state = repo.load_risk_state()
    if check.allowed:
        if risk_state.reconciliation_status != "OK":
            logger.info("RECONCILIATION_RECOVERED")
        ctx.risk_manager.mark_reconciliation_ok(risk_state)
        cycle_state["last_successful_reconciliation_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        logger.error(f"RECONCILIATION_FAILED reason={check.reason}")
        ctx.risk_manager.mark_reconciliation_failed(risk_state)
        repo.insert_event(
            event_id=f"reconciliation_failed:{now_utc.isoformat()}", ticker=ctx.ticker,
            event_type="RECONCILIATION_FAILED", message=check.reason or "",
        )
    repo.save_risk_state(risk_state)
    return abs(signed_qty)


def _run_cycle(ctx: RunnerContext, cycle_state: dict) -> None:
    logger = ctx.logger
    ticker, class_code, timeframe = ctx.ticker, ctx.class_code, ctx.timeframe
    now_utc = datetime.now(tz=timezone.utc)
    kill_switch_active = ctx.risk_manager.kill_switch_active()

    # ── Market hours guard ───────────────────────────────────────────────────
    session = "unknown"
    market_open = True
    if ctx.market_config:
        from src.market.market_hours import get_session_name, is_session_open
        session = get_session_name(now_utc, ctx.market_config)
        market_open = is_session_open(now_utc, ctx.market_config)

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
            logger.info(f"MARKET_CLOSED ticker={ticker} session={session}")
            cycle_state["api_errors"] = 0
            _write_status(
                ctx, cycle_state, trading_state="MARKET_CLOSED",
                market_open=False, kill_switch_active=kill_switch_active,
            )
            return

    # ── Fetch candles (env=prod / READONLY_TOKEN) ────────────────────────────
    logger.info(f"Fetching {ctx.lookback_candles} candles for {ticker} {timeframe}...")
    try:
        df, tick_size = _fetch_with_timeout(
            ticker, class_code, timeframe, ctx.lookback_candles, ctx.api_timeout_sec,
        )
        cycle_state["api_errors"] = 0
        cycle_state["last_successful_fetch_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    except concurrent.futures.TimeoutError:
        cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
        msg = f"API_TIMEOUT ticker={ticker} timeout_sec={ctx.api_timeout_sec}"
        cycle_state["last_error_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        cycle_state["last_error_message"] = msg
        logger.error(msg)
        _write_status(
            ctx, cycle_state, trading_state="API_ERROR",
            market_open=market_open, kill_switch_active=kill_switch_active,
        )
        return
    except Exception as e:
        cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1
        msg = f"API_ERROR ticker={ticker} error={e}"
        cycle_state["last_error_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        cycle_state["last_error_message"] = msg
        logger.error(msg)
        _write_status(
            ctx, cycle_state, trading_state="API_ERROR",
            market_open=market_open, kill_switch_active=kill_switch_active,
        )
        return

    if df.empty:
        logger.warning(f"NO_CANDLES ticker={ticker}")
        _write_status(
            ctx, cycle_state, trading_state="NO_CANDLES",
            market_open=market_open, kill_switch_active=kill_switch_active,
        )
        return

    # ── Params + detector ────────────────────────────────────────────────────
    params = load_params(ctx.params_file)
    if tick_size and tick_size > 0:
        params.tick_size = tick_size
        params.tick_size_source = "specs"

    detector = HammerDetector(params)
    debug_df = detector.detect_all(df, instrument=ticker, timeframe=timeframe, profile=ctx.profile)

    last_closed = debug_df.iloc[-1]
    logger.info(
        f"Last closed candle: {last_closed['timestamp']} "
        f"is_signal={last_closed['is_signal']} direction={last_closed.get('direction_candidate', '-')}"
    )

    if ctx.dry_run:
        signals = debug_df[
            debug_df["is_signal"].astype(bool) & (debug_df["fail_reason"].astype(str) == "pass")
        ]
        logger.info(f"Dry-run: {len(signals)} signals in window. No DB, broker, or order access.")
        _write_status(
            ctx, cycle_state, trading_state="DRY_RUN",
            market_open=market_open, kill_switch_active=kill_switch_active,
        )
        return

    repo = ctx.repo
    engine_kwargs = dict(ctx.engine_kwargs)
    engine_kwargs["tick_size"] = params.effective_tick_size
    engine_kwargs["point_value_rub"] = params.point_value_rub
    engine_kwargs["commission_per_trade"] = params.commission_per_trade

    last_ts_str = repo.get_state(_state_key(ticker))
    last_ts = pd.Timestamp(last_ts_str, tz="UTC") if last_ts_str else None

    closed_df = debug_df.iloc[:-1] if len(debug_df) > 1 else debug_df
    if last_ts:
        new_candles = closed_df[closed_df["timestamp"] > last_ts]
    else:
        new_candles = closed_df.tail(1)

    if new_candles.empty:
        logger.info("No new closed candles to process. Waiting...")
    else:
        logger.info(f"Processing {len(new_candles)} new candle(s).")
        if ctx.instrument is None:
            try:
                ctx.instrument = _resolve_instrument(ticker, class_code)
                logger.info(f"Resolved instrument: uid={ctx.instrument['uid']} figi={ctx.instrument['figi']}")
            except Exception as e:
                msg = f"INSTRUMENT_RESOLUTION_ERROR ticker={ticker} error={e}"
                logger.error(msg)
                cycle_state["last_error_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                cycle_state["last_error_message"] = msg
                _write_status(
                    ctx, cycle_state, trading_state="API_ERROR",
                    market_open=market_open, kill_switch_active=kill_switch_active,
                )
                return

        for _, candle in new_candles.iterrows():
            _process_one_candle(ctx, cycle_state, candle, engine_kwargs)
            repo.set_state(_state_key(ticker), str(candle["timestamp"]))

    # ── Reconciliation + exports ─────────────────────────────────────────────
    open_positions_actual = _reconcile(ctx, cycle_state)
    repo.export_orders_csv(ctx.orders_csv)
    repo.export_trades_csv(ctx.trades_csv)

    risk_state = repo.load_risk_state()
    daily = repo.load_daily_risk(_today_msk(now_utc))
    open_trade = repo.get_open_trade(ticker)
    pending_signal = _load_pending_signal(repo, ticker)
    open_orders_count = sum(
        1 for o in repo.list_orders(ticker=ticker)
        if o.status in (SandboxOrderStatus.NEW, SandboxOrderStatus.SUBMITTED)
    )

    trading_state = _compute_trading_state(risk_state, open_trade, pending_signal, kill_switch_active)
    _write_status(
        ctx, cycle_state, trading_state=trading_state, market_open=market_open,
        kill_switch_active=kill_switch_active, risk_state=risk_state, daily=daily,
        open_trade=open_trade, pending_signal=pending_signal,
        open_positions_actual=open_positions_actual, open_orders=open_orders_count,
        reconciliation_status=risk_state.reconciliation_status,
    )


def main():
    load_dotenv()
    args = _parse_args()
    cfg = _load_config(args.config)

    validate_safety(cfg)

    log_file = cfg.get("artifacts", {}).get("log", "logs/sandbox_hammer_maxhold5_SiU6.log")
    logger = _setup_logging(log_file, args.dry_run)

    logger.info("=" * 60)
    logger.info("HammerTrade Sandbox Runner — SANDBOX CONTOUR ONLY — NEVER LIVE")
    logger.info(f"  strategy={cfg.get('strategy')} ticker={cfg.get('ticker')} direction={cfg.get('direction')}")
    logger.info(f"  max_hold_bars={cfg.get('max_hold_bars')} contracts={cfg.get('contracts')}")
    logger.info(f"  paper_control_service={cfg.get('paper_control_service')} (read-only reference, untouched)")
    logger.info(f"  dry_run={args.dry_run} once={args.once}")
    logger.info("=" * 60)

    ctx = _build_context(cfg, args.dry_run, logger)

    cycle_state: dict = {
        "api_errors": 0,
        "last_successful_fetch_at": None,
        "prev_market_open": None,
        "market_open_at": None,
        "last_successful_reconciliation_at": None,
        "last_order_event_at": None,
        "last_error_at": None,
        "last_error_message": None,
    }

    cycles = 0
    while True:
        try:
            _run_cycle(ctx, cycle_state)
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            cycle_state["api_errors"] = cycle_state.get("api_errors", 0) + 1

        cycles += 1
        if args.once or args.dry_run:
            break
        if args.max_cycles is not None and cycles >= args.max_cycles:
            break
        time.sleep(ctx.poll_interval_seconds)


if __name__ == "__main__":
    main()
