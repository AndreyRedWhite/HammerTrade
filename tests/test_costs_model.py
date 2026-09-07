"""Tests for src/costs — the single authority on transaction costs.

These tests encode the project's expensive lessons as executable constraints:
the measured 5 bps/leg-side equity commission, the 20 bps two-leg round trip,
and — most importantly — that an unresolvable point value RAISES rather than
falling back to a plausible number.
"""
import pytest

from src.costs import (
    EQUITY_COMMISSION_BPS_PER_SIDE,
    FUTURES_COMMISSION_BPS_PER_SIDE,
    AssetClass,
    CostModel,
    UnknownInstrumentError,
    cost_model_for,
    hurdle_bps,
    point_value_rub,
    required_daily_carry_bps,
    roundtrip_bps,
)


# ── The measured constants ───────────────────────────────────────────────────

def test_equity_commission_is_the_measured_five_bps():
    """5.00 bps/leg-side was measured on real sandbox fills, not taken from a tariff."""
    assert EQUITY_COMMISSION_BPS_PER_SIDE == 5.00


def test_futures_commission_matches_tariff():
    """T-Bank futures tariff is 0.025% of notional = 2.5 bps per side."""
    assert FUTURES_COMMISSION_BPS_PER_SIDE == 2.50


def test_two_leg_equity_roundtrip_is_twenty_bps():
    """THE design constant: a pair round trip costs 20 bps of one leg's notional.

    Every equity candidate is screened against this. If this test changes, the
    conclusion that sub-hourly equity mean-reversion is dead changes with it.
    """
    assert roundtrip_bps(n_legs=2, cost_bps_per_side=EQUITY_COMMISSION_BPS_PER_SIDE) == 20.0


def test_two_leg_futures_roundtrip_is_ten_bps():
    assert roundtrip_bps(n_legs=2, cost_bps_per_side=FUTURES_COMMISSION_BPS_PER_SIDE) == 10.0


def test_roundtrip_scales_with_legs_not_notional():
    """Costs are proportional, so notional cancels; only leg count moves the hurdle.

    This is why the index-vs-constituents and Si/Eu/ED triangle candidates died:
    more legs, not a smaller edge.
    """
    one = roundtrip_bps(n_legs=1, cost_bps_per_side=5.0)
    three = roundtrip_bps(n_legs=3, cost_bps_per_side=5.0)
    assert one == 10.0
    assert three == 30.0


# ── No silent defaults ───────────────────────────────────────────────────────

def test_roundtrip_requires_explicit_keyword_arguments():
    """A caller that has not decided its costs must fail, not trade at zero cost."""
    with pytest.raises(TypeError):
        roundtrip_bps(2, 5.0)  # positional — rejected
    with pytest.raises(TypeError):
        roundtrip_bps(n_legs=2)  # cost omitted — no default exists


def test_negative_and_zero_inputs_rejected():
    with pytest.raises(ValueError):
        roundtrip_bps(n_legs=0, cost_bps_per_side=5.0)
    with pytest.raises(ValueError):
        roundtrip_bps(n_legs=2, cost_bps_per_side=-1.0)


# ── Hurdle and carry gate ────────────────────────────────────────────────────

def test_hurdle_applies_safety_multiple():
    assert hurdle_bps(n_legs=2, cost_bps_per_side=5.0) == 20.0
    assert hurdle_bps(n_legs=2, cost_bps_per_side=5.0, safety_multiple=2.0) == 40.0


def test_hurdle_rejects_multiple_below_one():
    with pytest.raises(ValueError):
        hurdle_bps(n_legs=2, cost_bps_per_side=5.0, safety_multiple=0.5)


def test_required_daily_carry_matches_deployed_gate():
    """The deployed carry gate: 10 bps round trip, 2x cover, 10-day hold = 2 bps/day."""
    assert required_daily_carry_bps(
        roundtrip_cost_bps=10.0, expected_hold_days=10.0, cover_multiple=2.0
    ) == 2.0


def test_required_daily_carry_rises_as_the_real_hold_shortens():
    """A 4-day forced roll needs 2.5x the carry the 10-day assumption implies.

    This is the arithmetic behind the min_front_dte / roll_dte inconsistency.
    """
    ten_day = required_daily_carry_bps(
        roundtrip_cost_bps=10.0, expected_hold_days=10.0, cover_multiple=2.0
    )
    four_day = required_daily_carry_bps(
        roundtrip_cost_bps=10.0, expected_hold_days=4.0, cover_multiple=2.0
    )
    assert ten_day == 2.0
    assert four_day == 5.0
    assert four_day / ten_day == pytest.approx(2.5)


def test_required_daily_carry_rejects_nonpositive_hold():
    with pytest.raises(ValueError):
        required_daily_carry_bps(
            roundtrip_cost_bps=10.0, expected_hold_days=0.0, cover_multiple=2.0
        )


# ── CostModel validation ─────────────────────────────────────────────────────

def test_futures_cost_model_requires_point_value():
    """A futures model without a point value must not be constructible.

    The 10x PnL inflation came from a module-level POINT_VALUE_RUB = 10.0 that
    was never checked against the instrument.
    """
    with pytest.raises(ValueError, match="point_value_rub"):
        CostModel(
            ticker="SiM6",
            asset_class=AssetClass.FUTURES,
            commission_bps_per_side=2.5,
            lot=1,
            point_value_rub=None,
        )


def test_equity_cost_model_has_no_point_value():
    m = CostModel(
        ticker="TATN",
        asset_class=AssetClass.EQUITY,
        commission_bps_per_side=EQUITY_COMMISSION_BPS_PER_SIDE,
        lot=1,
    )
    assert m.point_value_rub is None
    assert m.cost_bps_per_side == 5.0


def test_spread_estimate_is_additive_and_separate_from_commission():
    """Commission is measured; spread is estimated. They stay distinguishable."""
    m = CostModel(
        ticker="TATN",
        asset_class=AssetClass.EQUITY,
        commission_bps_per_side=5.0,
        lot=1,
        spread_bps_estimate=1.5,
    )
    assert m.commission_bps_per_side == 5.0
    assert m.cost_bps_per_side == 6.5
    assert roundtrip_bps(n_legs=2, cost_bps_per_side=m.cost_bps_per_side) == 26.0


def test_cost_model_rejects_bad_inputs():
    with pytest.raises(ValueError):
        CostModel(ticker="X", asset_class=AssetClass.EQUITY,
                  commission_bps_per_side=-1.0, lot=1)
    with pytest.raises(ValueError):
        CostModel(ticker="X", asset_class=AssetClass.EQUITY,
                  commission_bps_per_side=5.0, lot=0)
    with pytest.raises(ValueError):
        CostModel(ticker="X", asset_class=AssetClass.EQUITY,
                  commission_bps_per_side=5.0, lot=1, spread_bps_estimate=-0.1)


# ── Point value resolution ───────────────────────────────────────────────────

def _write_specs(tmp_path, rows):
    header = (
        "ticker,class_code,uid,figi,name,lot,currency,min_price_increment,"
        "min_price_increment_amount,point_value_rub,initial_margin_on_buy,"
        "initial_margin_on_sell,expiration_date,first_trade_date,last_trade_date,"
        "first_1min_candle_date,first_1day_candle_date,api_trade_available_flag,"
        "buy_available_flag,sell_available_flag,updated_at\n"
    )
    p = tmp_path / "specs.csv"
    p.write_text(header + "".join(rows), encoding="utf-8")
    return str(p)


def test_point_value_resolved_from_specs(tmp_path):
    """Si is 1.0 RUB/point — the value seven modules hardcoded as 10.0."""
    csv = _write_specs(tmp_path, [
        "SiM6,SPBFUT,uid1,FIGI1,Si,1,rub,1.0,1.0,1.0,,,,,,,,true,true,true,2026-09-07T00:00:00Z\n",
        "IMOEXF,SPBFUT,uid2,FIGI2,IMOEXF,10,rub,0.5,5.0,10.0,,,,,,,,true,true,true,2026-09-07T00:00:00Z\n",
    ])
    assert point_value_rub("SiM6", specs_csv=csv) == 1.0
    assert point_value_rub("IMOEXF", specs_csv=csv) == 10.0


def test_unknown_instrument_raises_instead_of_defaulting(tmp_path):
    """The whole point of the module: no plausible fallback."""
    csv = _write_specs(tmp_path, [
        "SiM6,SPBFUT,uid1,FIGI1,Si,1,rub,1.0,1.0,1.0,,,,,,,,true,true,true,2026-09-07T00:00:00Z\n",
    ])
    with pytest.raises(UnknownInstrumentError, match="not in the instrument specs cache"):
        point_value_rub("GLDRUBF", specs_csv=csv)


def test_missing_point_value_raises(tmp_path):
    csv = _write_specs(tmp_path, [
        "BRM6,SPBFUT,uid3,FIGI3,Brent,1,rub,0.01,,,,,,,,,,true,true,true,2026-09-07T00:00:00Z\n",
    ])
    with pytest.raises(UnknownInstrumentError, match="no usable point_value_rub"):
        point_value_rub("BRM6", specs_csv=csv)


def test_cost_model_for_futures_resolves_point_value(tmp_path):
    csv = _write_specs(tmp_path, [
        "SiM6,SPBFUT,uid1,FIGI1,Si,1,rub,1.0,1.0,1.0,,,,,,,,true,true,true,2026-09-07T00:00:00Z\n",
    ])
    m = cost_model_for("SiM6", asset_class=AssetClass.FUTURES, specs_csv=csv)
    assert m.point_value_rub == 1.0
    assert m.commission_bps_per_side == FUTURES_COMMISSION_BPS_PER_SIDE


def test_cost_model_for_equity_needs_no_specs():
    m = cost_model_for("TATN", asset_class=AssetClass.EQUITY, lot=1)
    assert m.commission_bps_per_side == EQUITY_COMMISSION_BPS_PER_SIDE
    assert m.point_value_rub is None
