"""Sandbox execution engine (MVP-L1a).

The hammer-maxhold5 signal/entry/exit state machine is NOT reimplemented
here: this module reuses src.paper.engine.process_candle unchanged and
translates between SandboxTrade (sandbox journal) and PaperTrade (the shape
process_candle expects). The runner uses the returned decision to decide
whether to place a sandbox order, update the journal, and re-run
reconciliation.
"""
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from src.paper.engine import process_candle
from src.paper.models import PaperExitReason, PaperTrade, PaperTradeStatus
from src.sandbox.models import SandboxExitReason, SandboxTrade, SandboxTradeStatus
from src.sandbox.reconciliation import PositionView

_EXIT_REASON_MAP = {
    PaperExitReason.STOP: SandboxExitReason.STOP,
    PaperExitReason.TAKE: SandboxExitReason.TAKE,
    PaperExitReason.MAX_HOLD_EXIT: SandboxExitReason.MAX_HOLD_EXIT,
}


@dataclass
class SandboxCandleResult:
    """Outcome of process_sandbox_candle for one closed candle.

    decision is one of:
      "NONE"    - nothing changed, no pending signal
      "PENDING" - a breakout signal is now (or still) pending entry
      "ENTRY"   - a new trade should be opened (submit entry order)
      "HOLD"    - an existing open trade is still open (bars_held updated)
      "EXIT"    - an existing open trade just closed (submit exit order)
    """
    decision: str
    trade: Optional[SandboxTrade]
    pending_signal: Optional[dict]
    logs: list[str]


def sandbox_trade_to_paper_trade(
    trade: SandboxTrade, class_code: str, timeframe: str, profile: str,
) -> PaperTrade:
    """Convert a persisted open SandboxTrade into the PaperTrade shape process_candle expects."""
    return PaperTrade(
        trade_id=trade.trade_id,
        ticker=trade.ticker,
        class_code=class_code,
        timeframe=timeframe,
        profile=profile,
        direction=trade.direction,
        signal_timestamp=trade.entry_time,
        entry_timestamp=trade.entry_time,
        entry_price=trade.entry_price,
        stop_price=trade.stop_price,
        take_price=trade.take_price,
        status=PaperTradeStatus.OPEN if trade.status == SandboxTradeStatus.OPEN else PaperTradeStatus.CLOSED,
        bars_held=trade.bars_held,
        created_at=trade.created_at,
        updated_at=trade.updated_at,
    )


def paper_trade_to_sandbox_trade(trade: PaperTrade, signal_id: str, qty: int) -> SandboxTrade:
    """Convert a freshly-opened PaperTrade (from process_candle) into a new SandboxTrade."""
    return SandboxTrade(
        trade_id=trade.trade_id,
        signal_id=signal_id,
        entry_order_id=None,
        exit_order_id=None,
        ticker=trade.ticker,
        direction=trade.direction,
        qty=qty,
        entry_time=trade.entry_timestamp,
        entry_price=trade.entry_price,
        stop_price=trade.stop_price,
        take_price=trade.take_price,
        status=SandboxTradeStatus.OPEN,
        bars_held=trade.bars_held,
        created_at=trade.created_at,
        updated_at=trade.updated_at,
    )


def apply_paper_trade_to_sandbox_trade(
    sandbox_trade: SandboxTrade,
    paper_trade: PaperTrade,
    *,
    point_value_rub: float,
    commission_rub_total: float,
) -> SandboxTrade:
    """Apply process_candle's mutations (bars_held, exit fields) onto the SandboxTrade."""
    sandbox_trade.bars_held = paper_trade.bars_held
    sandbox_trade.updated_at = paper_trade.updated_at

    if paper_trade.status == PaperTradeStatus.CLOSED:
        sandbox_trade.status = SandboxTradeStatus.CLOSED
        sandbox_trade.exit_time = paper_trade.exit_timestamp
        sandbox_trade.exit_price = paper_trade.exit_price
        sandbox_trade.exit_reason = _EXIT_REASON_MAP.get(paper_trade.exit_reason, SandboxExitReason.RISK_EXIT)

        gross_pnl_rub = None
        if paper_trade.pnl_points is not None:
            gross_pnl_rub = round(paper_trade.pnl_points * point_value_rub * sandbox_trade.qty, 2)
        sandbox_trade.gross_pnl_rub = gross_pnl_rub
        sandbox_trade.commission_rub = round(commission_rub_total, 2)
        sandbox_trade.net_pnl_rub = paper_trade.pnl_rub

    return sandbox_trade


def expected_position_from_trade(open_trade: Optional[SandboxTrade]) -> PositionView:
    """Map the bot's open SandboxTrade (if any) to the expected sandbox account position."""
    if open_trade is None or open_trade.status != SandboxTradeStatus.OPEN:
        return PositionView("FLAT", 0)
    direction = "LONG" if open_trade.direction == "BUY" else "SHORT"
    return PositionView(direction, open_trade.qty)


def process_sandbox_candle(
    candle: pd.Series,
    open_trade: Optional[SandboxTrade],
    pending_signal: Optional[dict],
    *,
    direction_filter: str,
    entry_mode: str = "breakout",
    entry_horizon_bars: int = 3,
    max_hold_bars: Optional[int] = 5,
    take_r: float = 1.0,
    stop_buffer_points: float = 0.0,
    slippage_ticks: float = 1.0,
    tick_size: float = 1.0,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
    ticker: str = "",
    class_code: str = "",
    timeframe: str = "",
    profile: str = "",
    experiment_name: str = "",
) -> SandboxCandleResult:
    """Process one closed candle through the (unchanged) hammer-maxhold5 state machine."""
    paper_open_trade: Optional[PaperTrade] = None
    if open_trade is not None and open_trade.status == SandboxTradeStatus.OPEN:
        paper_open_trade = sandbox_trade_to_paper_trade(open_trade, class_code, timeframe, profile)

    updated_paper_trade, new_pending, logs = process_candle(
        candle=candle,
        open_trade=paper_open_trade,
        pending_signal=pending_signal,
        direction_filter=direction_filter,
        entry_mode=entry_mode,
        entry_horizon_bars=entry_horizon_bars,
        max_hold_bars=max_hold_bars,
        take_r=take_r,
        stop_buffer_points=stop_buffer_points,
        slippage_ticks=slippage_ticks,
        tick_size=tick_size,
        point_value_rub=point_value_rub,
        commission_per_trade=commission_per_trade,
        contracts=contracts,
        ticker=ticker,
        class_code=class_code,
        timeframe=timeframe,
        profile=profile,
        experiment_name=experiment_name,
    )

    if updated_paper_trade is None:
        decision = "PENDING" if new_pending is not None else "NONE"
        return SandboxCandleResult(decision=decision, trade=None, pending_signal=new_pending, logs=logs)

    if paper_open_trade is None:
        # process_candle created a brand new OPEN trade (entry just triggered).
        new_trade = paper_trade_to_sandbox_trade(
            updated_paper_trade, signal_id=updated_paper_trade.trade_id, qty=contracts,
        )
        return SandboxCandleResult(decision="ENTRY", trade=new_trade, pending_signal=new_pending, logs=logs)

    commission_rub_total = commission_per_trade * 2 * contracts
    updated_trade = apply_paper_trade_to_sandbox_trade(
        open_trade, updated_paper_trade,
        point_value_rub=point_value_rub,
        commission_rub_total=commission_rub_total,
    )
    decision = "EXIT" if updated_trade.status == SandboxTradeStatus.CLOSED else "HOLD"
    return SandboxCandleResult(decision=decision, trade=updated_trade, pending_signal=new_pending, logs=logs)
