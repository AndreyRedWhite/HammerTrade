"""Carry signal and the entry gate that has to be consistent with the roll rule.

THE INCONSISTENCY THIS FIXES
============================
The deployed carry service ran with::

    --min-front-dte 10      # admits a contract with 11 days to expiry
    --roll-dte 7            # forces a roll once fewer than 7 days remain
    --expected-hold-days 10 # the cost gate divides the round trip by TEN days

A contract admitted at DTE 11 is rolled at DTE 6, so the realised hold can be
about five days — but the gate priced the 10 bps round trip over ten. The entry
requirement was therefore ~2 bps/day when the construction actually needed ~4.

``min_front_dte_for()`` derives the constraint instead of leaving two CLI flags
to contradict each other silently.

A CAVEAT THAT MATTERS MORE THAN THE ARITHMETIC
==============================================
``expected_hold_days`` is not a holding *rule*. Nothing forces a ten-day hold:
``CARRY_FLIP`` can close the position on the very next cycle. So satisfying this
constraint is necessary, not sufficient. A correct gate compares the cumulative
conditional PnL to the nearest possible exit — expected funding, plus expected
relative-price change, minus every contractual cashflow (for IMOEXF that
includes the dividend adjustment debited from a short perpetual), minus entry,
exit and roll costs, minus margin funding.
"""
from __future__ import annotations


class CarryGateError(ValueError):
    """The gate parameters are mutually inconsistent."""


def expected_carry_bp(funding_ma_bp: float, perp_px: float, q_px: float, dte: int) -> float:
    """Naive carry in bp/day: funding received minus basis amortisation.

    WARNING — this is the formula the executor has always used, and it is
    incomplete for an index perpetual. It treats the ENTIRE basis as financing.
    A quarterly on a PRICE index also embeds expected dividends, so
    ``basis = rT - qT`` and this returns ``f - r + q`` while the construction
    actually earns ``f - r``. The difference is the dividend yield, which the
    exchange debits back from a short perpetual as a separate adjustment.

    Measured on IMOEXF: the basis is 1.57 bp/day lower for contracts whose life
    spans the May-July dividend season while funding shows no seasonality
    (+0.15 bp/day), so this figure is inflated by ~1.7 bp/day in season against
    an entry gate of 2.0 bp/day.

    Kept here, unchanged and shared with research, so that both sides compute the
    same (imperfect) number until the cashflow replay replaces it.
    """
    if perp_px <= 0:
        raise CarryGateError(f"perp price must be > 0, got {perp_px}")
    basis_bp = (q_px / perp_px - 1) * 1e4
    return funding_ma_bp - basis_bp / max(dte, 1)


def shortest_possible_hold_days(*, min_front_dte: int, roll_dte: int) -> int:
    """Worst-case days from entry to a forced roll.

    ``pick_front`` admits a contract with integer DTE strictly greater than
    ``min_front_dte``, i.e. at best ``min_front_dte + 1``. The roll fires once
    DTE drops below ``roll_dte``, i.e. at ``roll_dte - 1``. The span between them
    is the shortest hold the rules permit.
    """
    if min_front_dte < 0 or roll_dte < 0:
        raise CarryGateError("DTE parameters must be non-negative")
    return max((min_front_dte + 1) - (roll_dte - 1), 0)


def min_front_dte_for(*, roll_dte: int, expected_hold_days: float) -> int:
    """Smallest ``min_front_dte`` that lets the assumed hold actually happen."""
    if expected_hold_days <= 0:
        raise CarryGateError(f"expected_hold_days must be > 0, got {expected_hold_days}")
    # Need (min_front_dte + 1) - (roll_dte - 1) >= expected_hold_days.
    import math
    return int(math.ceil(expected_hold_days + roll_dte - 2))


def front_selection_is_consistent(
    *, min_front_dte: int, roll_dte: int, expected_hold_days: float
) -> tuple[bool, str]:
    """Check the gate horizon against the roll rule.

    Returns ``(ok, detail)``. The caller decides whether to refuse to start; the
    check itself is pure so it can be unit-tested and reused by research.
    """
    shortest = shortest_possible_hold_days(min_front_dte=min_front_dte, roll_dte=roll_dte)
    if shortest >= expected_hold_days:
        return True, (
            f"shortest possible hold {shortest}d >= expected_hold_days "
            f"{expected_hold_days}d"
        )
    required = min_front_dte_for(roll_dte=roll_dte, expected_hold_days=expected_hold_days)
    return False, (
        f"min_front_dte={min_front_dte} with roll_dte={roll_dte} permits a hold of "
        f"only {shortest} days, but the cost gate divides the round trip by "
        f"expected_hold_days={expected_hold_days}. The entry requirement is "
        f"understated by {expected_hold_days / max(shortest, 1):.1f}x. "
        f"Set min_front_dte >= {required}, or lower expected_hold_days to {shortest}."
    )
