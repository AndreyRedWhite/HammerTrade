"""Tests for the carry cashflow replay — the falsification of the carry edge."""
import pandas as pd
import pytest

from scripts.research_carry_cashflow_replay import daily_dividend_accrual_bps


def test_dividend_accrual_is_the_total_return_minus_price_gap():
    """The index dividend adjustment compensates exactly this gap.

    Price index flat, total-return index +1% => 100 bps of dividend accrued.
    """
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    price = pd.Series([100.0, 100.0, 100.0], index=idx)
    total = pd.Series([100.0, 101.0, 101.0], index=idx)
    acc = daily_dividend_accrual_bps(price, total)
    assert acc.iloc[0] == pytest.approx(100.0, abs=0.5)
    assert acc.iloc[1] == pytest.approx(0.0, abs=0.5)


def test_no_dividend_means_no_accrual():
    """When both indices move together there is nothing to adjust for."""
    idx = pd.date_range("2026-01-01", periods=4, freq="D")
    price = pd.Series([100.0, 102.0, 99.0, 101.0], index=idx)
    total = pd.Series([200.0, 204.0, 198.0, 202.0], index=idx)
    acc = daily_dividend_accrual_bps(price, total)
    assert acc.abs().max() < 1e-6


def test_accrual_is_positive_when_the_price_index_drops_ex_dividend():
    """Ex-dividend: the price index falls, the total-return index does not.

    A SHORT perpetual gains that fall, so the exchange debits it back — which is
    why this term enters the construction's PnL with a MINUS sign.
    """
    idx = pd.date_range("2026-07-15", periods=2, freq="D")
    price = pd.Series([1000.0, 990.0], index=idx)      # -1% ex-div
    total = pd.Series([1000.0, 1000.0], index=idx)     # unchanged
    acc = daily_dividend_accrual_bps(price, total)
    assert acc.iloc[0] > 0
    assert acc.iloc[0] == pytest.approx(101.0, abs=1.0)


def test_alignment_drops_unmatched_dates():
    idx_a = pd.date_range("2026-01-01", periods=5, freq="D")
    idx_b = idx_a[:3]
    price = pd.Series([100.0] * 5, index=idx_a)
    total = pd.Series([100.0, 101.0, 102.0], index=idx_b)
    acc = daily_dividend_accrual_bps(price, total)
    assert len(acc) == 2
