"""Tests for the pairs stat-arb paper engine."""
import numpy as np
import pandas as pd
import pytest

from src.paper.pairs.engine import compute_spread_z, process_pair_bar, _bar_pnl
from src.paper.pairs.models import PairExitReason, PairTradeStatus


def _bar(ts, z, po, pc, oo, oc):
    return pd.Series({
        "timestamp": pd.Timestamp(ts, tz="UTC"),
        "z": z, "pref_open": po, "pref_close": pc, "ord_open": oo, "ord_close": oc,
    })


COMMON = dict(
    pair_name="SBER", pref_ticker="SBERP", ord_ticker="SBER",
    entry_z=2.0, exit_z=0.5, stop_z=4.0, max_hold_bars=45,
    notional_per_leg=100_000.0, cost_bps_per_leg_side=3.5,
    experiment_name="test",
)


def test_no_entry_when_z_below_threshold():
    trade, logs = process_pair_bar(_bar("2026-06-01T10:00", 1.0, 300, 300, 300, 300),
                                   None, **COMMON)
    assert trade is None


def test_entry_short_spread_when_z_high():
    trade, logs = process_pair_bar(_bar("2026-06-01T10:00", 2.5, 300, 300, 300, 300),
                                   None, **COMMON)
    assert trade is not None
    assert trade.direction == "SHORT_SPREAD"
    assert trade.status == PairTradeStatus.OPEN
    assert trade.pref_market_fill is None  # filled next bar


def test_entry_long_spread_when_z_low():
    trade, _ = process_pair_bar(_bar("2026-06-01T10:00", -2.5, 300, 300, 300, 300),
                                None, **COMMON)
    assert trade.direction == "LONG_SPREAD"


def test_market_fill_set_on_next_bar():
    trade, _ = process_pair_bar(_bar("2026-06-01T10:00", 2.5, 300, 300, 300, 300),
                                None, **COMMON)
    # next bar: still diverged (no exit), market fill should be captured
    trade2, _ = process_pair_bar(_bar("2026-06-01T11:00", 2.4, 301, 301, 299, 299),
                                 trade, **COMMON)
    assert trade2.pref_market_fill == 301
    assert trade2.ord_market_fill == 299
    assert trade2.status == PairTradeStatus.OPEN
    assert trade2.bars_held == 1


def test_exit_on_mean_reversion():
    trade, _ = process_pair_bar(_bar("2026-06-01T10:00", 2.5, 300, 300, 300, 300),
                                None, **COMMON)
    # next bar reverts to |z| <= exit_z → EXIT_MEAN
    trade2, logs = process_pair_bar(_bar("2026-06-01T11:00", 0.3, 301, 301, 299, 299),
                                    trade, **COMMON)
    assert trade2.status == PairTradeStatus.CLOSED
    assert trade2.exit_reason == PairExitReason.EXIT_MEAN
    assert trade2.pnl_rub is not None
    assert trade2.pnl_rub_market is not None


def test_exit_on_stop_diverge():
    trade, _ = process_pair_bar(_bar("2026-06-01T10:00", 2.5, 300, 300, 300, 300),
                                None, **COMMON)
    trade2, _ = process_pair_bar(_bar("2026-06-01T11:00", 4.5, 301, 301, 299, 299),
                                 trade, **COMMON)
    assert trade2.status == PairTradeStatus.CLOSED
    assert trade2.exit_reason == PairExitReason.STOP_DIVERGE


def test_exit_on_time():
    common = dict(COMMON)
    common["max_hold_bars"] = 1
    trade, _ = process_pair_bar(_bar("2026-06-01T10:00", 2.5, 300, 300, 300, 300),
                                None, **common)
    trade2, _ = process_pair_bar(_bar("2026-06-01T11:00", 2.4, 301, 301, 299, 299),
                                 trade, **common)
    assert trade2.status == PairTradeStatus.CLOSED
    assert trade2.exit_reason == PairExitReason.TIME


def test_no_stop_loss_by_default():
    # Same drift as test_stop_loss_fires_when_z_stop_cannot, but stop_loss_bps unset.
    trade, _ = process_pair_bar(_bar("2026-06-01T10:00", 3.12, 37.165, 37.165, 15.49, 15.49),
                                None, **COMMON)
    trade2, _ = process_pair_bar(_bar("2026-06-01T11:00", 1.70, 37.165, 36.015, 15.49, 13.65),
                                 trade, **COMMON)
    assert trade2.status == PairTradeStatus.OPEN  # bleeds on, exactly as SNGS did


def test_stop_loss_fires_when_z_stop_cannot():
    """Reproduces the SNGS trade of 2026-07-17 that lost ~9k of a 100k leg.

    SHORT_SPREAD at z=3.12; the spread then WIDENED (log 0.875 -> 0.970) but the rolling
    mean chased it, so z fell to 1.70 — below stop_z=4.0 and above exit_z=0.5, meaning no
    z-based exit could ever fire. Only a PnL-space stop catches this.
    """
    common = dict(COMMON, stop_loss_bps=300.0)  # 3% of 100k = 3000 RUB
    trade, _ = process_pair_bar(_bar("2026-06-01T10:00", 3.12, 37.165, 37.165, 15.49, 15.49),
                                None, **common)
    assert trade.direction == "SHORT_SPREAD"
    trade2, logs = process_pair_bar(_bar("2026-06-01T11:00", 1.70, 37.165, 36.015, 15.49, 13.65),
                                    trade, **common)
    assert trade2.status == PairTradeStatus.CLOSED
    assert trade2.exit_reason == PairExitReason.STOP_LOSS
    assert trade2.pnl_rub_market < -3000  # the bar gapped straight through the stop


def test_stop_loss_does_not_fire_on_small_loss():
    common = dict(COMMON, stop_loss_bps=300.0)
    trade, _ = process_pair_bar(_bar("2026-06-01T10:00", 2.5, 300, 300, 300, 300),
                                None, **common)
    # ~0.3% adverse move on one leg → well inside the 3% stop
    trade2, _ = process_pair_bar(_bar("2026-06-01T11:00", 2.4, 300, 301, 300, 300),
                                 trade, **common)
    assert trade2.status == PairTradeStatus.OPEN


def test_stop_loss_takes_priority_over_mean_exit_label():
    # z reverts AND the position is past the stop → labelled STOP_LOSS, not EXIT_MEAN.
    common = dict(COMMON, stop_loss_bps=300.0)
    trade, _ = process_pair_bar(_bar("2026-06-01T10:00", 3.12, 37.165, 37.165, 15.49, 15.49),
                                None, **common)
    trade2, _ = process_pair_bar(_bar("2026-06-01T11:00", 0.3, 37.165, 36.015, 15.49, 13.65),
                                 trade, **common)
    assert trade2.exit_reason == PairExitReason.STOP_LOSS


def test_short_spread_profits_when_spread_narrows():
    # SHORT_SPREAD = short pref, long ord. Profit if pref falls and/or ord rises.
    pnl = _bar_pnl("SHORT_SPREAD", pref_entry=310, ord_entry=300,
                   pref_exit=305, ord_exit=302, notional_per_leg=100_000.0,
                   cost_bps_per_leg_side=0.0)
    # pref -1.61% (short → +), ord +0.67% (long → +) → positive
    assert pnl > 0


def test_long_spread_pnl_sign():
    # LONG_SPREAD = long pref, short ord. Profit if pref rises relative to ord.
    pnl = _bar_pnl("LONG_SPREAD", pref_entry=300, ord_entry=300,
                   pref_exit=306, ord_exit=300, notional_per_leg=100_000.0,
                   cost_bps_per_leg_side=0.0)
    assert pnl == pytest.approx(0.02 * 100_000, rel=1e-3)  # +2% on pref leg


def test_costs_reduce_pnl():
    gross = _bar_pnl("LONG_SPREAD", 300, 300, 306, 300, 100_000.0, 0.0)
    net = _bar_pnl("LONG_SPREAD", 300, 300, 306, 300, 100_000.0, 3.5)
    # 4 sides × 3.5bps × 100k = 140 rub of costs
    assert gross - net == pytest.approx(140.0, rel=1e-6)


def test_compute_spread_z():
    n = 120
    ts = pd.date_range("2026-06-01T07:00", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    base = 300 + np.cumsum(rng.normal(0, 0.2, n))
    pref = pd.DataFrame({"timestamp": ts, "open": base, "high": base, "low": base,
                         "close": base, "volume": 1})
    ordn = pd.DataFrame({"timestamp": ts, "open": base * 1.001, "high": base, "low": base,
                         "close": base * 1.001, "volume": 1})
    out = compute_spread_z(pref, ordn, timeframe="1min", z_window=50)
    assert "z" in out.columns and "spread" in out.columns
    assert out["z"].notna().sum() > 0
