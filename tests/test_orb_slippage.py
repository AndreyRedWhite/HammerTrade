"""Tests for src/research/slippage.py — MVP-R1a."""
import pytest

SI_POINT_VALUE_RUB = 1.0
SI_COMMISSION_RUB = 38.0

from src.research.slippage import (
    apply_slippage_to_trades,
    slippage_sensitivity,
    slippage_destroyed_edge,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _long_trade(entry: float, exit_price: float, exit_reason: str = "TAKE") -> dict:
    pnl_pts = exit_price - entry
    return {
        "direction": "LONG",
        "entry_price": entry,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pnl_points": pnl_pts,
        "pnl_rub": pnl_pts * 10.0 - 0.05,
        "bars_held": 10,
        "date": "2026-01-20",
    }


def _short_trade(entry: float, exit_price: float, exit_reason: str = "TAKE") -> dict:
    pnl_pts = entry - exit_price
    return {
        "direction": "SHORT",
        "entry_price": entry,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pnl_points": pnl_pts,
        "pnl_rub": pnl_pts * 10.0 - 0.05,
        "bars_held": 10,
        "date": "2026-01-20",
    }


# ---------------------------------------------------------------------------
# Test 1: Long entry worsens with +1pt slippage (entry increases)
# ---------------------------------------------------------------------------

def test_long_entry_worsens():
    trade = _long_trade(entry=80000.0, exit_price=80200.0)
    slipped = apply_slippage_to_trades([trade], slip_pts=1.0,
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB)
    assert len(slipped) == 1
    assert slipped[0]["entry_price_slip"] == pytest.approx(80001.0)


# ---------------------------------------------------------------------------
# Test 2: Short entry worsens with +1pt slippage (entry decreases)
# ---------------------------------------------------------------------------

def test_short_entry_worsens():
    trade = _short_trade(entry=80000.0, exit_price=79800.0)
    slipped = apply_slippage_to_trades([trade], slip_pts=1.0,
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB)
    assert len(slipped) == 1
    assert slipped[0]["entry_price_slip"] == pytest.approx(79999.0)


# ---------------------------------------------------------------------------
# Test 3: Long TAKE exit worsens with slippage (exit decreases)
# ---------------------------------------------------------------------------

def test_long_take_exit_worsens():
    trade = _long_trade(entry=80000.0, exit_price=80200.0, exit_reason="TAKE")
    slipped = apply_slippage_to_trades([trade], slip_pts=2.0,
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB)
    assert slipped[0]["exit_price_slip"] == pytest.approx(80198.0)
    # Entry also worsens: 80002, exit: 80198, pnl_pts = 80198 - 80002 = 196 (vs 200 original)
    assert slipped[0]["pnl_points"] == pytest.approx(196.0)


# ---------------------------------------------------------------------------
# Test 4: Short TAKE exit worsens with slippage (exit increases)
# ---------------------------------------------------------------------------

def test_short_take_exit_worsens():
    trade = _short_trade(entry=80000.0, exit_price=79800.0, exit_reason="TAKE")
    slipped = apply_slippage_to_trades([trade], slip_pts=2.0,
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB)
    assert slipped[0]["exit_price_slip"] == pytest.approx(79802.0)
    # Entry: 79998, exit: 79802, pnl = 79998 - 79802 = 196 (vs 200 original)
    assert slipped[0]["pnl_points"] == pytest.approx(196.0)


# ---------------------------------------------------------------------------
# Test 5: slippage_destroyed_edge returns True when PF drops below 1.1
# ---------------------------------------------------------------------------

def test_slippage_destroyed_edge():
    # Build a set of trades that clearly has PF < 1.1 after large slippage
    # A marginal trade: +10 pts profit, then slippage 5 pts each side = 10 pts destroyed
    trades = [_long_trade(entry=80000.0, exit_price=80010.0)]  # small winner
    slipped = apply_slippage_to_trades(trades, slip_pts=10.0,
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB)
    # Entry: 80010, exit: 80000 — pnl_pts = 80000 - 80010 = -10 (now a loser)
    from src.research.metrics import compute_metrics
    metrics = compute_metrics(slipped)
    assert slippage_destroyed_edge(metrics, threshold_pf=1.1) is True


def test_slippage_destroyed_edge_false_when_profitable():
    # Large winners won't be destroyed by 1pt slip
    trades = [
        _long_trade(entry=80000.0, exit_price=80200.0),  # +200 pts
        _long_trade(entry=80000.0, exit_price=80200.0),
    ]
    slipped = apply_slippage_to_trades(trades, slip_pts=1.0,
        point_value_rub=SI_POINT_VALUE_RUB, commission_rub=SI_COMMISSION_RUB)
    from src.research.metrics import compute_metrics
    metrics = compute_metrics(slipped)
    assert slippage_destroyed_edge(metrics, threshold_pf=1.1) is False
