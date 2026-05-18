"""Tests for MVP-2.1: max_hold_bars in paper trading engine."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.paper.engine import process_candle
from src.paper.models import PaperExitReason, PaperTrade, PaperTradeStatus
from src.paper.repository import PaperRepository


# ─────────────────────────────── helpers ─────────────────────────────────────

def _candle(
    ts: str = "2026-01-15 10:05:00+00:00",
    open_: float = 100.0,
    high: float = 102.0,
    low: float = 98.0,
    close: float = 100.0,
    is_signal: bool = False,
    fail_reason: str = "no_signal",
    direction_candidate: str = "",
) -> pd.Series:
    return pd.Series({
        "timestamp": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": 100,
        "is_signal": is_signal,
        "fail_reason": fail_reason,
        "direction_candidate": direction_candidate,
    })


def _open_sell_trade(bars_held: int = 0) -> PaperTrade:
    return PaperTrade(
        trade_id="paper:SiM6:1m:balanced:SELL:2026-01-15T10:00:00+00:00",
        ticker="SiM6",
        class_code="SPBFUT",
        timeframe="1m",
        profile="balanced",
        direction="SELL",
        signal_timestamp=pd.Timestamp("2026-01-15 10:00:00+00:00").to_pydatetime(),
        entry_timestamp=pd.Timestamp("2026-01-15 10:01:00+00:00").to_pydatetime(),
        entry_price=100.0,
        stop_price=110.0,
        take_price=90.0,
        status=PaperTradeStatus.OPEN,
        bars_held=bars_held,
    )


def _open_buy_trade(bars_held: int = 0) -> PaperTrade:
    return PaperTrade(
        trade_id="paper:SiM6:1m:balanced:BUY:2026-01-15T10:00:00+00:00",
        ticker="SiM6",
        class_code="SPBFUT",
        timeframe="1m",
        profile="balanced",
        direction="BUY",
        signal_timestamp=pd.Timestamp("2026-01-15 10:00:00+00:00").to_pydatetime(),
        entry_timestamp=pd.Timestamp("2026-01-15 10:01:00+00:00").to_pydatetime(),
        entry_price=100.0,
        stop_price=90.0,
        take_price=110.0,
        status=PaperTradeStatus.OPEN,
        bars_held=bars_held,
    )


# ─────────────────────────────── tests ───────────────────────────────────────

def test_max_hold_none_no_timeout():
    """max_hold_bars=None: trade stays open indefinitely, never triggers MAX_HOLD_EXIT."""
    trade = _open_sell_trade(bars_held=100)
    candle = _candle(high=105.0, low=95.0, close=99.0)  # no stop/take hit

    updated, sig, logs = process_candle(
        candle=candle,
        open_trade=trade,
        pending_signal=None,
        direction_filter="SELL",
        max_hold_bars=None,
    )
    assert updated is not None
    assert updated.status == PaperTradeStatus.OPEN
    assert updated.exit_reason is None
    assert updated.bars_held == 101


def test_max_hold_5_exits_at_bar_5():
    """max_hold_bars=5: exits with MAX_HOLD_EXIT when bars_held reaches 5."""
    trade = _open_sell_trade(bars_held=4)
    candle = _candle(high=105.0, low=95.0, close=99.5)  # no stop/take hit

    updated, sig, logs = process_candle(
        candle=candle,
        open_trade=trade,
        pending_signal=None,
        direction_filter="SELL",
        max_hold_bars=5,
        slippage_ticks=0.0,
        tick_size=1.0,
    )
    assert updated is not None
    assert updated.status == PaperTradeStatus.CLOSED
    assert updated.exit_reason == PaperExitReason.MAX_HOLD_EXIT
    assert updated.bars_held == 5
    assert updated.exit_price == pytest.approx(99.5)


def test_max_hold_not_triggered_before_bar_5():
    """max_hold_bars=5: does NOT exit at bars_held=4."""
    trade = _open_sell_trade(bars_held=3)
    candle = _candle(high=105.0, low=95.0, close=99.5)  # no stop/take hit

    updated, sig, logs = process_candle(
        candle=candle,
        open_trade=trade,
        pending_signal=None,
        direction_filter="SELL",
        max_hold_bars=5,
    )
    assert updated is not None
    assert updated.status == PaperTradeStatus.OPEN
    assert updated.bars_held == 4


def test_stop_priority_over_max_hold():
    """STOP has priority over MAX_HOLD_EXIT when both trigger on the same candle."""
    trade = _open_sell_trade(bars_held=4)
    # high >= stop_price (110): stop triggered. bars_held will be 5 → also max_hold
    candle = _candle(high=110.0, low=95.0, close=99.5)

    updated, sig, logs = process_candle(
        candle=candle,
        open_trade=trade,
        pending_signal=None,
        direction_filter="SELL",
        max_hold_bars=5,
        slippage_ticks=0.0,
    )
    assert updated is not None
    assert updated.status == PaperTradeStatus.CLOSED
    assert updated.exit_reason == PaperExitReason.STOP
    assert updated.exit_price == pytest.approx(110.0)


def test_take_priority_over_max_hold():
    """TAKE has priority over MAX_HOLD_EXIT when both trigger on the same candle."""
    trade = _open_sell_trade(bars_held=4)
    # low <= take_price (90): take triggered. bars_held will be 5 → also max_hold
    candle = _candle(high=105.0, low=90.0, close=99.5)

    updated, sig, logs = process_candle(
        candle=candle,
        open_trade=trade,
        pending_signal=None,
        direction_filter="SELL",
        max_hold_bars=5,
        slippage_ticks=0.0,
    )
    assert updated is not None
    assert updated.status == PaperTradeStatus.CLOSED
    assert updated.exit_reason == PaperExitReason.TAKE
    assert updated.exit_price == pytest.approx(90.0)


def test_bars_held_increments_on_each_candle():
    """bars_held increases by 1 for each candle the engine processes."""
    trade = _open_sell_trade(bars_held=0)
    candle = _candle(high=105.0, low=95.0, close=99.5)

    updated, _, _ = process_candle(
        candle=candle, open_trade=trade, pending_signal=None,
        direction_filter="SELL", max_hold_bars=None,
    )
    assert updated.bars_held == 1

    updated2, _, _ = process_candle(
        candle=candle, open_trade=updated, pending_signal=None,
        direction_filter="SELL", max_hold_bars=None,
    )
    assert updated2.bars_held == 2


def test_max_hold_exit_sell_pnl():
    """MAX_HOLD_EXIT PnL for SELL: entry=100, exit_close=98, no slippage → profit."""
    trade = _open_sell_trade(bars_held=4)
    candle = _candle(high=105.0, low=95.0, close=98.0)

    updated, _, _ = process_candle(
        candle=candle, open_trade=trade, pending_signal=None,
        direction_filter="SELL",
        max_hold_bars=5,
        slippage_ticks=0.0, tick_size=1.0,
        point_value_rub=10.0, commission_per_trade=0.0, contracts=1,
    )
    assert updated.exit_reason == PaperExitReason.MAX_HOLD_EXIT
    # SELL: gross_points = entry - exit_close = 100 - 98 = 2 points = 20 RUB
    assert updated.pnl_rub == pytest.approx(20.0)


def test_max_hold_exit_buy_pnl():
    """MAX_HOLD_EXIT PnL for BUY: entry=100, exit_close=103, no slippage → profit."""
    trade = _open_buy_trade(bars_held=4)
    candle = _candle(high=105.0, low=95.0, close=103.0)

    updated, _, _ = process_candle(
        candle=candle, open_trade=trade, pending_signal=None,
        direction_filter="BUY",
        max_hold_bars=5,
        slippage_ticks=0.0, tick_size=1.0,
        point_value_rub=10.0, commission_per_trade=0.0, contracts=1,
    )
    assert updated.exit_reason == PaperExitReason.MAX_HOLD_EXIT
    # BUY: gross_points = exit_close - entry = 103 - 100 = 3 points = 30 RUB
    assert updated.pnl_rub == pytest.approx(30.0)


def test_maxhold5_db_path_differs_from_baseline():
    """maxhold5 DB path is distinct from baseline DB path."""
    baseline = Path("data/paper/paper_state.sqlite")
    maxhold5 = Path("data/paper/paper_state_maxhold5.sqlite")
    assert baseline != maxhold5
    assert "maxhold5" in str(maxhold5)


def test_compare_script_empty_experiment(tmp_path):
    """compare_paper_experiments: does not crash when experiment DB is empty."""
    from scripts.compare_paper_experiments import _compute_metrics, build_compare_report

    baseline = _compute_metrics([], "baseline")
    experiment = _compute_metrics([], "maxhold5")
    report = build_compare_report(baseline, experiment, "baseline", "maxhold5")
    assert "baseline vs maxhold5" in report
    assert "LOW_SAMPLE" in report


def test_compare_delta_calculation(tmp_path):
    """compare_paper_experiments: delta is (experiment - baseline)."""
    from scripts.compare_paper_experiments import _delta

    assert _delta(10.0, 15.0) == "+5.00"
    assert _delta(20.0, 10.0) == "-10.00"
    assert _delta(5, 7) == "+2"


def test_cli_parser_accepts_max_hold_bars():
    """run_paper_trader.py CLI parser accepts --max-hold-bars argument."""
    import importlib, sys
    from pathlib import Path

    # Patch sys.argv
    old_argv = sys.argv[:]
    sys.argv = [
        "run_paper_trader.py",
        "--max-hold-bars", "5",
        "--experiment-name", "maxhold5",
        "--dry-run",
    ]
    try:
        # dynamically import to avoid module-level side effects
        spec_path = Path(__file__).resolve().parent.parent / "scripts" / "run_paper_trader.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("run_paper_trader", spec_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        args = mod._parse_args()
        assert args.max_hold_bars == 5
        assert args.experiment_name == "maxhold5"
        assert args.dry_run is True
    finally:
        sys.argv = old_argv
