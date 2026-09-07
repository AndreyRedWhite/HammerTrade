"""Tests for the broker-reconciled two-leg ledger.

Each test encodes a specific failure the audit found in the live executors, so
that a regression reads as "we reintroduced the phantom close", not as an
abstract assertion failure.
"""
import pytest

from src.sandbox.twoleg import (
    CashflowKind,
    CashflowSource,
    ConstructionState,
    LedgerError,
    Leg,
    TwoLegLedger,
)

PERP = "uid-perp"
QUART = "uid-quarterly"


@pytest.fixture()
def ledger(tmp_path):
    lg = TwoLegLedger(str(tmp_path / "ledger.sqlite"))
    yield lg
    lg.close()


def _carry_legs(perp_lots=-82, q_lots=79):
    """The live GOLD carry construction: SHORT perp + LONG quarterly."""
    return [
        Leg(instrument_uid=PERP, ticker="GLDRUBF", target_lots=perp_lots,
            unit_scale=1, point_value_rub=1.0),
        Leg(instrument_uid=QUART, ticker="GLZ6", target_lots=q_lots,
            unit_scale=1, point_value_rub=1.0),
    ]


def _open_fully(lg, cid, perp_px=12191.47, q_px=12608.65):
    lg.record_order(cid, instrument_uid=PERP, side="SELL", lots=82,
                    order_id="o1", purpose="ENTRY")
    lg.record_fill(cid, instrument_uid=PERP, side="SELL", lots_filled=82,
                   price_per_unit=perp_px, commission_rub=25.0, order_id="o1")
    lg.record_order(cid, instrument_uid=QUART, side="BUY", lots=79,
                    order_id="o2", purpose="ENTRY")
    lg.record_fill(cid, instrument_uid=QUART, side="BUY", lots_filled=79,
                   price_per_unit=q_px, commission_rub=25.0, order_id="o2")
    lg.record_broker_positions(cid, {PERP: -82, QUART: 79})


# ── Invariant 1: the phantom close ───────────────────────────────────────────

def test_zero_fill_exit_does_not_close_the_construction(ledger):
    """THE bug: exit order filled 0 lots, journal said CLOSED and booked a PnL.

    Old code did `pf, pc, _ = _place(...)` then `exit = pf if pf is not None
    else bar_close`, and wrote CLOSED unconditionally.
    """
    cid = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    _open_fully(ledger, cid)
    assert ledger.state(cid) is ConstructionState.OPEN

    ledger.record_order(cid, instrument_uid=PERP, side="BUY", lots=82,
                        order_id="x1", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=PERP, side="BUY", lots_filled=0,
                       price_per_unit=None, commission_rub=0.0, order_id="x1")

    # Broker still holds everything.
    ledger.record_broker_positions(cid, {PERP: -82, QUART: 79})

    assert ledger.state(cid) is not ConstructionState.CLOSED
    assert ledger.state(cid) is ConstructionState.PARTIALLY_CLOSED
    assert ledger.remainder(cid, {PERP: -82, QUART: 79}) == {PERP: -82, QUART: 79}


def test_a_fill_with_lots_but_no_price_is_refused(ledger):
    """There is no fallback price. Substituting the bar close is the bug."""
    cid = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    with pytest.raises(LedgerError, match="no fallback price"):
        ledger.record_fill(cid, instrument_uid=PERP, side="SELL", lots_filled=82,
                           price_per_unit=None, commission_rub=0.0, order_id="o1")


def test_partial_exit_reports_the_exact_remainder(ledger):
    """Invariant 2: a partial fill has its own state and a per-leg remainder."""
    cid = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    _open_fully(ledger, cid)

    ledger.record_order(cid, instrument_uid=PERP, side="BUY", lots=82,
                        order_id="x1", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=PERP, side="BUY", lots_filled=82,
                       price_per_unit=12200.0, commission_rub=25.0, order_id="x1")
    ledger.record_order(cid, instrument_uid=QUART, side="SELL", lots=79,
                        order_id="x2", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=QUART, side="SELL", lots_filled=30,
                       price_per_unit=12600.0, commission_rub=10.0, order_id="x2")

    positions = {PERP: 0, QUART: 49}
    ledger.record_broker_positions(cid, positions)

    assert ledger.state(cid) is ConstructionState.PARTIALLY_CLOSED
    assert ledger.remainder(cid, positions) == {QUART: 49}


def test_full_exit_confirmed_by_broker_closes(ledger):
    cid = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    _open_fully(ledger, cid)

    ledger.record_order(cid, instrument_uid=PERP, side="BUY", lots=82,
                        order_id="x1", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=PERP, side="BUY", lots_filled=82,
                       price_per_unit=12200.0, commission_rub=25.0, order_id="x1")
    ledger.record_order(cid, instrument_uid=QUART, side="SELL", lots=79,
                        order_id="x2", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=QUART, side="SELL", lots_filled=79,
                       price_per_unit=12600.0, commission_rub=25.0, order_id="x2")
    ledger.record_broker_positions(cid, {PERP: 0, QUART: 0})

    assert ledger.state(cid) is ConstructionState.CLOSED
    assert ledger.verify(cid, {PERP: 0, QUART: 0}) == []


def test_orders_alone_never_close_a_construction(ledger):
    """Invariant 4: an order response is not a position read."""
    cid = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    _open_fully(ledger, cid)
    ledger.record_order(cid, instrument_uid=PERP, side="BUY", lots=82,
                        order_id="x1", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=PERP, side="BUY", lots_filled=82,
                       price_per_unit=12200.0, commission_rub=25.0, order_id="x1")
    ledger.record_order(cid, instrument_uid=QUART, side="SELL", lots=79,
                        order_id="x2", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=QUART, side="SELL", lots_filled=79,
                       price_per_unit=12600.0, commission_rub=25.0, order_id="x2")
    # No position snapshot yet.
    assert ledger.state(cid) is ConstructionState.CLOSING


# ── Invariant 5/6: REAL vs MODEL, and the IndexDiv omission ──────────────────

def test_model_cashflow_never_counts_as_real(ledger):
    """Modelled funding must not land in a REAL total.

    The carry executor published a SWAPRATE figure it computed from ISS in a
    field named ``net_pnl_rub_REAL``.
    """
    cid = ledger.open_intent(name="carry:IMOEXF", legs=_carry_legs())
    _open_fully(ledger, cid)
    ledger.record_cashflow(cid, kind=CashflowKind.SWAP_RATE, amount_rub=1500.0,
                           source=CashflowSource.MODEL, note="ISS SWAPRATE")

    p = ledger.pnl(cid)
    assert p.cashflow_model_rub == 1500.0
    assert p.cashflow_broker_rub == 0.0
    assert p.net_with_model_rub - p.net_real_rub == pytest.approx(1500.0)


def test_broker_confirmed_cashflow_does_count_as_real(ledger):
    cid = ledger.open_intent(name="carry:IMOEXF", legs=_carry_legs())
    _open_fully(ledger, cid)
    ledger.record_cashflow(cid, kind=CashflowKind.SWAP_RATE, amount_rub=1500.0,
                           source=CashflowSource.BROKER, note="broker operation")
    p = ledger.pnl(cid)
    assert p.cashflow_broker_rub == 1500.0
    assert p.net_real_rub == pytest.approx(p.net_with_model_rub)


def test_declared_missing_indexdiv_marks_pnl_incomplete(ledger):
    """IMOEXF debits IndexDiv from a short perp; ISS history does not expose it.

    A PnL that silently drops a known obligation is worse than one that refuses
    to call itself complete.
    """
    cid = ledger.open_intent(name="carry:IMOEXF", legs=_carry_legs())
    _open_fully(ledger, cid)
    ledger.declare_missing_cashflow(
        cid, kind=CashflowKind.INDEX_DIV,
        reason="MOEX debits IndexDiv from short IMOEXF; ISS history exposes SWAPRATE only")

    p = ledger.pnl(cid)
    assert not p.is_complete
    assert CashflowKind.INDEX_DIV.value in p.missing_cashflow_kinds


def test_closing_with_a_missing_contractual_cashflow_is_a_violation(ledger):
    cid = ledger.open_intent(name="carry:IMOEXF", legs=_carry_legs())
    _open_fully(ledger, cid)
    ledger.declare_missing_cashflow(cid, kind=CashflowKind.INDEX_DIV, reason="not observable")

    ledger.record_order(cid, instrument_uid=PERP, side="BUY", lots=82,
                        order_id="x1", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=PERP, side="BUY", lots_filled=82,
                       price_per_unit=12200.0, commission_rub=25.0, order_id="x1")
    ledger.record_order(cid, instrument_uid=QUART, side="SELL", lots=79,
                        order_id="x2", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=QUART, side="SELL", lots_filled=79,
                       price_per_unit=12600.0, commission_rub=25.0, order_id="x2")
    ledger.record_broker_positions(cid, {PERP: 0, QUART: 0})

    codes = [v.code for v in ledger.verify(cid, {PERP: 0, QUART: 0})]
    assert "CLOSED_WITH_MISSING_CASHFLOW" in codes


# ── Invariant 7: PnL reconciles ──────────────────────────────────────────────

def test_pnl_is_signed_cash_and_reconciles_to_the_kopeck(ledger):
    """Round-trip PnL derived from fills alone, with no notion of 'exit price'."""
    cid = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    _open_fully(ledger, cid, perp_px=12000.0, q_px=12500.0)

    ledger.record_order(cid, instrument_uid=PERP, side="BUY", lots=82,
                        order_id="x1", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=PERP, side="BUY", lots_filled=82,
                       price_per_unit=11900.0, commission_rub=25.0, order_id="x1")
    ledger.record_order(cid, instrument_uid=QUART, side="SELL", lots=79,
                        order_id="x2", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=QUART, side="SELL", lots_filled=79,
                       price_per_unit=12450.0, commission_rub=25.0, order_id="x2")
    ledger.record_broker_positions(cid, {PERP: 0, QUART: 0})

    p = ledger.pnl(cid)
    # Short perp gained 100/contract on 82; long quarterly lost 50 on 79.
    expected_price = 82 * 100.0 - 79 * 50.0
    assert p.price_pnl_rub == pytest.approx(expected_price)
    assert p.commission_rub == pytest.approx(100.0)
    assert p.net_real_rub == pytest.approx(expected_price - 100.0)
    assert ledger.verify(cid, {PERP: 0, QUART: 0}) == []


def test_journal_broker_mismatch_is_reported(ledger):
    cid = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    _open_fully(ledger, cid)
    # Broker says something else than the fills imply.
    codes = [v.code for v in ledger.verify(cid, {PERP: -80, QUART: 79})]
    assert "JOURNAL_BROKER_MISMATCH" in codes


# ── Invariant 3: orphan liquidation is charged to its owner ──────────────────

def test_orphan_liquidation_cost_stays_with_the_construction(ledger):
    cid = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    _open_fully(ledger, cid)
    ledger.record_order(cid, instrument_uid=PERP, side="BUY", lots=82,
                        order_id="x1", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=PERP, side="BUY", lots_filled=82,
                       price_per_unit=12200.0, commission_rub=25.0, order_id="x1")
    ledger.record_broker_positions(cid, {PERP: 0, QUART: 79})
    assert ledger.state(cid) is ConstructionState.PARTIALLY_CLOSED

    # The stray quarterly is swept later — charged here, not to whoever finds it.
    ledger.record_order(cid, instrument_uid=QUART, side="SELL", lots=79,
                        order_id="sweep", purpose="ORPHAN_LIQUIDATION")
    ledger.record_fill(cid, instrument_uid=QUART, side="SELL", lots_filled=79,
                       price_per_unit=12400.0, commission_rub=30.0, order_id="sweep")
    ledger.record_broker_positions(cid, {PERP: 0, QUART: 0})

    assert ledger.state(cid) is ConstructionState.CLOSED
    # 25 + 25 entry, 25 perp exit, 30 for the sweep. The sweep's cost lands here
    # rather than disappearing between one trade's close and another's open.
    assert ledger.pnl(cid).commission_rub == pytest.approx(105.0)
    assert ledger.verify(cid, {PERP: 0, QUART: 0}) == []


def test_unknown_order_purpose_refused(ledger):
    cid = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    with pytest.raises(LedgerError, match="unknown order purpose"):
        ledger.record_order(cid, instrument_uid=PERP, side="BUY", lots=1,
                            order_id="o", purpose="WHATEVER")


# ── Invariant 8: uncertainty blocks entries everywhere ───────────────────────

def test_a_stranded_construction_blocks_new_entries(ledger):
    cid = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    _open_fully(ledger, cid)
    assert ledger.entries_blocked() is None

    ledger.record_order(cid, instrument_uid=PERP, side="BUY", lots=82,
                        order_id="x1", purpose="EXIT")
    ledger.record_fill(cid, instrument_uid=PERP, side="BUY", lots_filled=82,
                       price_per_unit=12200.0, commission_rub=25.0, order_id="x1")
    ledger.record_broker_positions(cid, {PERP: 0, QUART: 79})

    blocked = ledger.entries_blocked()
    assert blocked is not None and "PARTIALLY_CLOSED" in blocked


def test_reconcile_sweeps_every_controlled_instrument_not_just_expected_legs(ledger):
    """An orphan from a previous construction is invisible to an expectation check.

    This is the shape of the 2026-07 incident: reconcile compared the two legs it
    expected, found them consistent, and reported a clean pair while a stray leg
    bled beside it.
    """
    old = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    _open_fully(ledger, old)
    ledger.record_order(old, instrument_uid=PERP, side="BUY", lots=82,
                        order_id="x1", purpose="EXIT")
    ledger.record_fill(old, instrument_uid=PERP, side="BUY", lots_filled=82,
                       price_per_unit=12200.0, commission_rub=25.0, order_id="x1")
    ledger.record_order(old, instrument_uid=QUART, side="SELL", lots=79,
                        order_id="x2", purpose="EXIT")
    ledger.record_fill(old, instrument_uid=QUART, side="SELL", lots_filled=79,
                       price_per_unit=12600.0, commission_rub=25.0, order_id="x2")
    ledger.record_broker_positions(old, {PERP: 0, QUART: 0})
    assert ledger.state(old) is ConstructionState.CLOSED

    # Nothing is expected anywhere — but the account still holds a stray.
    orphans = ledger.find_orphans({PERP: 0, QUART: -12})
    assert QUART in orphans
    assert orphans[QUART] == {"expected": 0, "actual": -12}
    assert PERP in ledger.controlled_uids()


def test_no_orphans_when_positions_match_expectations(ledger):
    cid = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    _open_fully(ledger, cid)
    assert ledger.find_orphans({PERP: -82, QUART: 79}) == {}


# ── Construction hygiene ─────────────────────────────────────────────────────

def test_construction_requires_two_distinct_legs(ledger):
    with pytest.raises(LedgerError, match="at least two legs"):
        ledger.open_intent(name="x", legs=[_carry_legs()[0]])
    dup = [_carry_legs()[0], _carry_legs()[0]]
    with pytest.raises(LedgerError, match="distinct instruments"):
        ledger.open_intent(name="x", legs=dup)


def test_events_are_append_only_and_ordered(ledger):
    cid = ledger.open_intent(name="carry:GLDRUBF", legs=_carry_legs())
    _open_fully(ledger, cid)
    kinds = [e["kind"] for e in ledger.events(cid)]
    assert kinds[0] == "INTENT"
    assert "ORDER" in kinds and "FILL" in kinds and "POSITIONS" in kinds
    assert kinds.count("INTENT") == 1
