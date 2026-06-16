"""Tests for src/sandbox/reconciliation.py (MVP-L1a)."""
from src.sandbox.reconciliation import (
    PositionView,
    position_from_signed_qty,
    reconcile_position,
)


def test_expected_flat_actual_flat_ok():
    result = reconcile_position(PositionView("FLAT", 0), PositionView("FLAT", 0))
    assert result.allowed is True
    assert result.reason is None


def test_expected_position_actual_same_ok():
    expected = PositionView("SHORT", 1)
    actual = PositionView("SHORT", 1)
    result = reconcile_position(expected, actual)
    assert result.allowed is True


def test_expected_flat_actual_position_fails():
    result = reconcile_position(PositionView("FLAT", 0), PositionView("SHORT", 1))
    assert result.allowed is False
    assert "expected_flat_actual_position" in result.reason


def test_expected_position_actual_flat_fails():
    result = reconcile_position(PositionView("SHORT", 1), PositionView("FLAT", 0))
    assert result.allowed is False
    assert "expected_position_actual_flat" in result.reason


def test_direction_mismatch_fails():
    result = reconcile_position(PositionView("SHORT", 1), PositionView("LONG", 1))
    assert result.allowed is False
    assert "direction_mismatch" in result.reason


def test_qty_mismatch_fails():
    result = reconcile_position(PositionView("SHORT", 1), PositionView("SHORT", 2))
    assert result.allowed is False
    assert "qty_mismatch" in result.reason


def test_position_from_signed_qty():
    assert position_from_signed_qty(0) == PositionView("FLAT", 0)
    assert position_from_signed_qty(1) == PositionView("LONG", 1)
    assert position_from_signed_qty(-1) == PositionView("SHORT", 1)
    assert position_from_signed_qty(-3) == PositionView("SHORT", 3)
