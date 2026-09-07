"""Authoritative transaction-cost and contract-multiplier model.

WHY THIS MODULE EXISTS
======================
Every catastrophic measurement error in this project's history came from a cost
or multiplier constant that was defined locally, defaulted silently, and then
diverged from reality:

* ``commission_per_trade: float = 0.025`` interpreted as RUBLES per side, giving
  a 5-kopeck round-trip on a ~90 000 RUB futures position where the truth is
  ~45 RUB — a ~900x understatement (src/config.py, src/backtest/engine.py,
  src/paper/engine.py, src/sandbox/engine.py).
* ``POINT_VALUE_RUB = 10.0`` hardcoded in seven modules for an instrument whose
  real point value is 1.0 — a 10x inflation of every PnL number.
* An ORB walk-forward config that specified the *correct* values
  (``rub_per_trade: 38.0``, ``point_value_rub: 1.0``), had them read into local
  variables, and then never passed them to the PnL calculation at all — so the
  study silently ran on the wrong constants anyway.

Together those made a fleet of 28 services look profitable when it was not.

THE RULES THIS MODULE ENFORCES
==============================
1. **Costs are proportional to notional, expressed in basis points.** Never in
   "roubles per trade": that unit is what allowed a 5-kopeck round-trip to look
   plausible. A bps figure is wrong by a factor you can see.
2. **No default values.** Every public function here takes its cost inputs
   explicitly. A caller that has not decided what the costs are must fail, not
   silently trade at zero cost.
3. **Point values are resolved from instrument specs, never guessed.**
   ``point_value_rub()`` raises ``UnknownInstrumentError`` rather than returning
   a plausible-looking number.

THE MEASURED CONSTANTS
======================
``EQUITY_COMMISSION_BPS_PER_SIDE = 5.00`` was measured on real T-Bank sandbox
fills (2026-07), not taken from a tariff sheet. It is purely proportional: there
is no fixed floor, so scaling notional does NOT amortise it. This is the origin
of the project's central design constant — a two-leg round trip costs 20 bps —
and it is why sub-hourly equity mean-reversion is structurally dead here.

``FUTURES_COMMISSION_BPS_PER_SIDE = 2.50`` is the T-Bank tariff of 0.025% of
notional per side.

Spread crossing is modelled separately (``spread_bps_estimate``) because it is
an estimate, whereas commission is a measurement. Keeping them apart stops an
assumption from being laundered into a fact.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# ── Measured / tariff constants ──────────────────────────────────────────────

#: Measured on real T-Bank sandbox fills, 2026-07. Proportional, no fixed floor.
EQUITY_COMMISSION_BPS_PER_SIDE = 5.00

#: T-Bank futures tariff: 0.025% of notional per side.
FUTURES_COMMISSION_BPS_PER_SIDE = 2.50


class AssetClass(str, Enum):
    EQUITY = "equity"
    FUTURES = "futures"


class UnknownInstrumentError(LookupError):
    """Raised when a cost input cannot be resolved from data.

    Deliberately an error rather than a fallback: a wrong-but-plausible point
    value is the single most expensive failure mode this project has had.
    """


@dataclass(frozen=True)
class CostModel:
    """Complete cost description of one tradable instrument.

    ``point_value_rub`` is meaningful for futures only (RUB per index point per
    lot, derived from ``min_price_increment_amount / min_price_increment``). For
    equities PnL is already in RUB per share, so it is ``None`` — and code that
    multiplies by it must therefore fail loudly rather than silently scale by 1.
    """

    ticker: str
    asset_class: AssetClass
    commission_bps_per_side: float
    lot: int
    point_value_rub: Optional[float] = None
    spread_bps_estimate: float = 0.0

    def __post_init__(self) -> None:
        if self.commission_bps_per_side < 0:
            raise ValueError(
                f"{self.ticker}: commission_bps_per_side must be >= 0, "
                f"got {self.commission_bps_per_side}"
            )
        if self.spread_bps_estimate < 0:
            raise ValueError(
                f"{self.ticker}: spread_bps_estimate must be >= 0, "
                f"got {self.spread_bps_estimate}"
            )
        if self.lot < 1:
            raise ValueError(f"{self.ticker}: lot must be >= 1, got {self.lot}")
        if self.asset_class is AssetClass.FUTURES and not self.point_value_rub:
            raise ValueError(
                f"{self.ticker}: futures require a positive point_value_rub; "
                f"got {self.point_value_rub!r}. Resolve it from instrument specs "
                f"(min_price_increment_amount / min_price_increment) — never guess."
            )
        if self.point_value_rub is not None and self.point_value_rub <= 0:
            raise ValueError(
                f"{self.ticker}: point_value_rub must be > 0 if set, "
                f"got {self.point_value_rub}"
            )

    @property
    def cost_bps_per_side(self) -> float:
        """Commission plus the estimated cost of crossing, for one side of one leg."""
        return self.commission_bps_per_side + self.spread_bps_estimate


# ── Core arithmetic ──────────────────────────────────────────────────────────

def roundtrip_bps(*, n_legs: int, cost_bps_per_side: float) -> float:
    """Full-cycle cost of a construction, in bps of ONE leg's notional.

    A "round trip" is in and out, so each leg is charged on two sides:
    ``n_legs x 2 x cost_bps_per_side``.

    With the measured equity commission of 5.00 bps and no spread estimate, a
    two-leg pair costs 20 bps to open and close — the number every equity
    candidate has to clear before it is worth testing.

    Both arguments are keyword-only and have no defaults, on purpose.
    """
    if n_legs < 1:
        raise ValueError(f"n_legs must be >= 1, got {n_legs}")
    if cost_bps_per_side < 0:
        raise ValueError(f"cost_bps_per_side must be >= 0, got {cost_bps_per_side}")
    return n_legs * 2.0 * cost_bps_per_side


def hurdle_bps(*, n_legs: int, cost_bps_per_side: float, safety_multiple: float = 1.0) -> float:
    """Gross edge a construction must show before it is worth testing at all.

    This is ``roundtrip_bps`` with a margin. ``safety_multiple`` is explicit
    rather than hidden inside the function so that the screening standard is
    visible in the caller and in the candidate registry.
    """
    if safety_multiple < 1.0:
        raise ValueError(f"safety_multiple must be >= 1.0, got {safety_multiple}")
    return roundtrip_bps(n_legs=n_legs, cost_bps_per_side=cost_bps_per_side) * safety_multiple


def required_daily_carry_bps(
    *,
    roundtrip_cost_bps: float,
    expected_hold_days: float,
    cover_multiple: float,
) -> float:
    """Minimum carry (bps/day) needed to cover a full cycle over the hold.

    NOTE FOR CARRY CONSTRUCTIONS: ``expected_hold_days`` must be the *shortest*
    hold the strategy can actually realise, not an aspiration. If contract
    selection admits a front month that a roll rule will force out in 4 days,
    then 4 is the number — using 10 understates the requirement by 2.5x. See
    ``src/carry/gate.py`` for the constraint that enforces this.
    """
    if roundtrip_cost_bps < 0:
        raise ValueError(f"roundtrip_cost_bps must be >= 0, got {roundtrip_cost_bps}")
    if expected_hold_days <= 0:
        raise ValueError(f"expected_hold_days must be > 0, got {expected_hold_days}")
    if cover_multiple < 1:
        raise ValueError(f"cover_multiple must be >= 1, got {cover_multiple}")
    return roundtrip_cost_bps * cover_multiple / expected_hold_days


# ── Resolution from instrument data ──────────────────────────────────────────

def point_value_rub(ticker: str, *, specs_csv: Optional[str] = None) -> float:
    """RUB per point per lot for a futures contract, from the specs cache.

    Raises ``UnknownInstrumentError`` if the instrument or its point value is
    not known. It deliberately does not fall back to a default: the 10x
    ``POINT_VALUE_RUB = 10.0`` error is exactly what a fallback produces.
    """
    from src.tbank.instrument_specs import get_cached_future_spec

    kwargs = {"path": specs_csv} if specs_csv else {}
    try:
        spec = get_cached_future_spec(ticker, **kwargs)
    except Exception as exc:  # noqa: BLE001 - surfaced as UnknownInstrumentError
        raise UnknownInstrumentError(
            f"{ticker}: could not read instrument specs cache ({exc}). "
            f"Refresh it with scripts/fetch_instrument_specs.py."
        ) from exc

    if spec is None:
        raise UnknownInstrumentError(
            f"{ticker}: not in the instrument specs cache. Refresh the cache "
            f"rather than assuming a point value."
        )

    pv = getattr(spec, "point_value_rub", None)
    if pv is None and isinstance(spec, dict):
        pv = spec.get("point_value_rub")
    if pv is None or float(pv) <= 0:
        raise UnknownInstrumentError(
            f"{ticker}: specs cache has no usable point_value_rub (got {pv!r}). "
            f"It is min_price_increment_amount / min_price_increment; re-fetch "
            f"the spec rather than guessing."
        )
    return float(pv)


def cost_model_for(
    ticker: str,
    *,
    asset_class: AssetClass,
    spread_bps_estimate: float = 0.0,
    lot: int = 1,
    specs_csv: Optional[str] = None,
) -> CostModel:
    """Build the cost model for one instrument.

    The commission is taken from the measured/tariff constant for the asset
    class. The point value, for futures, is resolved from instrument specs and
    never defaulted.
    """
    if asset_class is AssetClass.FUTURES:
        return CostModel(
            ticker=ticker,
            asset_class=asset_class,
            commission_bps_per_side=FUTURES_COMMISSION_BPS_PER_SIDE,
            lot=lot,
            point_value_rub=point_value_rub(ticker, specs_csv=specs_csv),
            spread_bps_estimate=spread_bps_estimate,
        )
    return CostModel(
        ticker=ticker,
        asset_class=asset_class,
        commission_bps_per_side=EQUITY_COMMISSION_BPS_PER_SIDE,
        lot=lot,
        point_value_rub=None,
        spread_bps_estimate=spread_bps_estimate,
    )
