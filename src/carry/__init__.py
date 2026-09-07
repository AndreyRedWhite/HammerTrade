"""Carry-construction signal and gating.

Shared by research and execution so the two cannot compute the edge differently
— a divergence that has already cost this project a false ADVANCE verdict.
"""
from src.carry.gate import (  # noqa: F401
    CarryGateError,
    expected_carry_bp,
    front_selection_is_consistent,
    min_front_dte_for,
    shortest_possible_hold_days,
)
