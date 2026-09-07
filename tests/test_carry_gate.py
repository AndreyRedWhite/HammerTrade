"""Tests for the carry entry gate and its consistency with the roll rule."""
import pytest

from src.carry import (
    CarryGateError,
    expected_carry_bp,
    front_selection_is_consistent,
    min_front_dte_for,
    shortest_possible_hold_days,
)
from src.costs import required_daily_carry_bps


def test_deployed_configuration_is_inconsistent():
    """The live service ran 10 / 7 / 10 — which does not hold together."""
    ok, detail = front_selection_is_consistent(
        min_front_dte=10, roll_dte=7, expected_hold_days=10
    )
    assert ok is False
    assert "understated" in detail
    assert "min_front_dte >= 15" in detail


def test_shortest_hold_under_the_deployed_settings():
    """DTE 11 in, rolled at DTE 6 — about five days, not ten."""
    assert shortest_possible_hold_days(min_front_dte=10, roll_dte=7) == 5


def test_required_carry_doubles_when_the_real_hold_is_five_days():
    """The gate asked for 2 bps/day; five days of hold needs 4."""
    assumed = required_daily_carry_bps(
        roundtrip_cost_bps=10.0, expected_hold_days=10.0, cover_multiple=2.0)
    actual = required_daily_carry_bps(
        roundtrip_cost_bps=10.0, expected_hold_days=5.0, cover_multiple=2.0)
    assert assumed == 2.0
    assert actual == 4.0


def test_min_front_dte_for_makes_the_configuration_consistent():
    required = min_front_dte_for(roll_dte=7, expected_hold_days=10)
    assert required == 15
    ok, _ = front_selection_is_consistent(
        min_front_dte=required, roll_dte=7, expected_hold_days=10)
    assert ok is True


def test_a_consistent_configuration_passes():
    ok, detail = front_selection_is_consistent(
        min_front_dte=30, roll_dte=7, expected_hold_days=10)
    assert ok is True
    assert "shortest possible hold" in detail


def test_expected_carry_subtracts_basis_amortisation():
    # Quarterly 1% rich over 100 days = 100 bps over 100 days = 1 bp/day of decay.
    carry = expected_carry_bp(funding_ma_bp=5.0, perp_px=2000.0, q_px=2020.0, dte=100)
    assert carry == pytest.approx(4.0)


def test_expected_carry_rejects_bad_price():
    with pytest.raises(CarryGateError):
        expected_carry_bp(funding_ma_bp=5.0, perp_px=0.0, q_px=2020.0, dte=100)


def test_live_gold_entry_was_marginal_by_its_own_gate():
    """The GOLD construction opened 2026-09-07 at carry 2.022 vs a gate of 2.00.

    Under the corrected five-day horizon the same round trip demands 4 bps/day,
    so this entry does not clear its own gate.
    """
    gate_as_configured = required_daily_carry_bps(
        roundtrip_cost_bps=10.0, expected_hold_days=10.0, cover_multiple=2.0)
    gate_corrected = required_daily_carry_bps(
        roundtrip_cost_bps=10.0,
        expected_hold_days=shortest_possible_hold_days(min_front_dte=10, roll_dte=7),
        cover_multiple=2.0)
    entered_at = 2.022
    assert entered_at > gate_as_configured
    assert entered_at < gate_corrected
