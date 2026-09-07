"""Broker-reconciled, event-sourced ledger for two-leg constructions.

WHY THIS EXISTS
===============
Both two-leg executors could mark a trade ``CLOSED`` with a PnL computed at the
bar's close price even when the closing order filled ZERO lots::

    pf, pc, _ = _place(...)                        # executed lots discarded
    pref_exit = pf if pf is not None else pref_px  # pref_px = bar close

The trade was then written to the journal as closed and profitable while one or
both legs were still sitting on the account. A later reconcile might liquidate
the remainder, but that fill and its cost never reached the closed trade's PnL.

The consequence is not a rounding error. "Measured on real sandbox fills" was
the project's main reason to trust its two surviving strategies, and the code
did not guarantee it. Until a ledger does, sandbox PnL is telemetry, not
evidence.

THE INVARIANTS
==============
1. ``CLOSED`` is impossible until every leg is confirmed flat to its target by a
   broker position snapshot. Not by an order response — by a position read.
2. A partial fill has its own state (``PARTIALLY_CLOSED`` / ``PARTIALLY_OPEN``)
   carrying the exact per-leg remainder. There is no fallback price.
3. Liquidating an orphan leg is charged to the construction that created it, so
   the cost cannot vanish between one trade's close and another's open.
4. Broker positions and operations are the source of truth; this ledger is a
   projection that is checked against them.
5. ``REAL`` covers only broker-confirmed fills and cashflows. Anything the bot
   computed is tagged ``MODEL`` and is reported separately — never summed into a
   field named ``_REAL``.
6. Contractual cashflows are recorded per kind, so an instrument with more than
   one (IMOEXF has funding AND a dividend adjustment) cannot silently lose one.
7. PnL reconciles to the kopeck against the sum of fills, commissions and
   cashflows.
8. Reconciliation covers every controlled instrument, not just the two legs the
   journal happens to expect — an unjournaled orphan is exactly what an
   expectation-shaped check cannot see. Any uncertainty blocks new entries.

DESIGN
======
Append-only ``events`` table; all state is derived from it in Python. That makes
the history auditable and makes "what did we actually know, and when" answerable
after the fact — which is the question the project could not answer before.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

# Money is compared to the kopeck. Anything below this is float noise.
KOPECK = 0.01


class LedgerError(RuntimeError):
    """A ledger operation was refused because it would break an invariant."""


class ConstructionState(str, Enum):
    INTENT = "INTENT"                      # decided, nothing sent
    OPENING = "OPENING"                    # entry orders sent, fills incomplete
    PARTIALLY_OPEN = "PARTIALLY_OPEN"      # entry stalled with legs mismatched
    OPEN = "OPEN"                          # broker-confirmed at target
    CLOSING = "CLOSING"                    # exit orders sent
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"  # exit incomplete; remainder is held
    CLOSED = "CLOSED"                      # broker-confirmed flat
    HALTED = "HALTED"                      # uncertain; no new entries allowed


#: States in which the construction still holds market exposure.
HOLDING_STATES = frozenset({
    ConstructionState.OPENING,
    ConstructionState.PARTIALLY_OPEN,
    ConstructionState.OPEN,
    ConstructionState.CLOSING,
    ConstructionState.PARTIALLY_CLOSED,
    ConstructionState.HALTED,
})


class CashflowSource(str, Enum):
    #: Confirmed by the broker (an operation, a commission on a fill).
    BROKER = "BROKER"
    #: Computed by us from public data. Never reported as REAL.
    MODEL = "MODEL"


class CashflowKind(str, Enum):
    COMMISSION = "COMMISSION"
    SWAP_RATE = "SWAP_RATE"      # perpetual futures funding
    INDEX_DIV = "INDEX_DIV"      # dividend adjustment; DEBITED from a short perp
    DIVIDEND = "DIVIDEND"        # equity dividend receivable/payable
    BORROW = "BORROW"            # short borrow fee
    OTHER = "OTHER"


@dataclass(frozen=True)
class Leg:
    """One leg of a construction.

    ``target_lots`` is SIGNED: positive = long, negative = short. ``unit_scale``
    converts one lot into the units the broker reports as a position balance
    (shares for equities, contracts for futures).
    """
    instrument_uid: str
    ticker: str
    target_lots: int
    unit_scale: int = 1
    point_value_rub: Optional[float] = None

    @property
    def target_units(self) -> int:
        return self.target_lots * self.unit_scale


@dataclass
class PnlBreakdown:
    """PnL split by what is *confirmed* versus what is *computed*.

    The split is the point. A single net number that silently blends a broker
    fill with a figure we derived from a public data feed is how modelled
    funding ended up in a field called ``net_pnl_rub_REAL``.
    """
    price_pnl_rub: float = 0.0          # from broker fills only
    commission_rub: float = 0.0         # from broker
    cashflow_broker_rub: float = 0.0    # broker-confirmed contractual flows
    cashflow_model_rub: float = 0.0     # our estimates, by kind
    cashflow_model_by_kind: dict = field(default_factory=dict)
    missing_cashflow_kinds: tuple = ()   # contractual flows we know we cannot see

    @property
    def net_real_rub(self) -> float:
        """Everything the broker confirmed. Safe to publish as REAL."""
        return self.price_pnl_rub - self.commission_rub + self.cashflow_broker_rub

    @property
    def net_with_model_rub(self) -> float:
        """REAL plus our estimates. Must be labelled MODEL wherever it appears."""
        return self.net_real_rub + self.cashflow_model_rub

    @property
    def is_complete(self) -> bool:
        """False when a contractual cashflow is known to be unaccounted for."""
        return not self.missing_cashflow_kinds


@dataclass
class InvariantViolation:
    code: str
    detail: str


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


_DDL = """
CREATE TABLE IF NOT EXISTS constructions (
    construction_id TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    legs_json       TEXT NOT NULL,
    state           TEXT NOT NULL,
    opened_at       TEXT,
    closed_at       TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    construction_id TEXT NOT NULL,
    ts              TEXT NOT NULL,
    kind            TEXT NOT NULL,
    payload_json    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_construction
    ON events(construction_id, event_id);
"""


class TwoLegLedger:
    """Append-only ledger; state is always derived, never trusted from a field."""

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(_DDL)
        self.con.commit()

    # ── construction lifecycle ────────────────────────────────────────────────

    def open_intent(self, *, name: str, legs: Iterable[Leg],
                    note: str = "", construction_id: Optional[str] = None) -> str:
        legs = list(legs)
        if len(legs) < 2:
            raise LedgerError("a construction needs at least two legs")
        uids = [l.instrument_uid for l in legs]
        if len(set(uids)) != len(uids):
            raise LedgerError(f"legs must be distinct instruments, got {uids}")
        cid = construction_id or f"{name}:{uuid.uuid4()}"
        now = _now()
        self.con.execute(
            "INSERT INTO constructions(construction_id,name,legs_json,state,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (cid, name, json.dumps([l.__dict__ for l in legs]),
             ConstructionState.INTENT.value, now, now),
        )
        self._event(cid, "INTENT", {"note": note,
                                    "legs": [l.__dict__ for l in legs]})
        self.con.commit()
        return cid

    def legs(self, cid: str) -> list[Leg]:
        row = self.con.execute(
            "SELECT legs_json FROM constructions WHERE construction_id=?", (cid,)
        ).fetchone()
        if row is None:
            raise LedgerError(f"unknown construction {cid}")
        return [Leg(**d) for d in json.loads(row["legs_json"])]

    def state(self, cid: str) -> ConstructionState:
        row = self.con.execute(
            "SELECT state FROM constructions WHERE construction_id=?", (cid,)
        ).fetchone()
        if row is None:
            raise LedgerError(f"unknown construction {cid}")
        return ConstructionState(row["state"])

    def _set_state(self, cid: str, state: ConstructionState, reason: str = "") -> None:
        now = _now()
        extra = ""
        params: tuple
        if state is ConstructionState.CLOSED:
            extra = ", closed_at=?"
            params = (state.value, now, now, cid)
        elif state is ConstructionState.OPEN:
            extra = ", opened_at=COALESCE(opened_at, ?)"
            params = (state.value, now, now, cid)
        else:
            params = (state.value, now, cid)
        self.con.execute(
            f"UPDATE constructions SET state=?{extra}, updated_at=? "
            f"WHERE construction_id=?", params)
        self._event(cid, "STATE", {"state": state.value, "reason": reason})
        self.con.commit()

    def _event(self, cid: str, kind: str, payload: dict) -> None:
        self.con.execute(
            "INSERT INTO events(construction_id,ts,kind,payload_json) VALUES(?,?,?,?)",
            (cid, _now(), kind, json.dumps(payload, default=str)),
        )

    def events(self, cid: str) -> list[sqlite3.Row]:
        return self.con.execute(
            "SELECT * FROM events WHERE construction_id=? ORDER BY event_id", (cid,)
        ).fetchall()

    # ── orders and fills ──────────────────────────────────────────────────────

    def record_order(self, cid: str, *, instrument_uid: str, side: str,
                     lots: int, order_id: str, purpose: str) -> None:
        """``purpose`` is ENTRY, EXIT or ORPHAN_LIQUIDATION.

        ORPHAN_LIQUIDATION exists so that cleaning up a stray leg is charged to
        the construction that stranded it (invariant 3) instead of appearing as
        an unexplained cost with no owner.
        """
        if purpose not in ("ENTRY", "EXIT", "ORPHAN_LIQUIDATION"):
            raise LedgerError(f"unknown order purpose {purpose!r}")
        self._event(cid, "ORDER", {"instrument_uid": instrument_uid, "side": side,
                                   "lots": lots, "order_id": order_id,
                                   "purpose": purpose})
        if purpose == "ENTRY" and self.state(cid) is ConstructionState.INTENT:
            self._set_state(cid, ConstructionState.OPENING, "entry order sent")
        elif purpose == "EXIT" and self.state(cid) is ConstructionState.OPEN:
            self._set_state(cid, ConstructionState.CLOSING, "exit order sent")
        self.con.commit()

    def record_fill(self, cid: str, *, instrument_uid: str, side: str,
                    lots_filled: int, price_per_unit: Optional[float],
                    commission_rub: float, order_id: str) -> None:
        """Record a broker-confirmed fill.

        A zero-lot fill is recorded too — it is the event the old code threw
        away, and it is what distinguishes "the exit happened" from "the exit
        was attempted".
        """
        if lots_filled < 0:
            raise LedgerError(f"lots_filled must be >= 0, got {lots_filled}")
        if lots_filled > 0 and (price_per_unit is None or price_per_unit <= 0):
            raise LedgerError(
                f"a fill of {lots_filled} lots needs a positive price, got "
                f"{price_per_unit!r}. There is no fallback price: substituting a "
                f"bar close is exactly the bug this ledger exists to prevent."
            )
        self._event(cid, "FILL", {"instrument_uid": instrument_uid, "side": side,
                                  "lots_filled": lots_filled,
                                  "price_per_unit": price_per_unit,
                                  "commission_rub": commission_rub,
                                  "order_id": order_id})
        self.con.commit()

    def record_cashflow(self, cid: str, *, kind: CashflowKind, amount_rub: float,
                        source: CashflowSource, note: str = "",
                        value_date: Optional[str] = None) -> None:
        """Record a contractual cashflow. Sign: positive = we receive."""
        self._event(cid, "CASHFLOW", {"kind": kind.value, "amount_rub": amount_rub,
                                      "source": source.value, "note": note,
                                      "value_date": value_date})
        self.con.commit()

    def declare_missing_cashflow(self, cid: str, *, kind: CashflowKind,
                                 reason: str) -> None:
        """Declare that a contractual cashflow exists but we cannot observe it.

        IMOEXF is the case that forced this: MOEX debits an ``IndexDiv`` dividend
        adjustment from a short perpetual, and the ISS history endpoint the
        project reads exposes ``SWAPRATE`` only. A PnL that silently omits a
        known obligation is worse than one that refuses to call itself complete.
        """
        self._event(cid, "MISSING_CASHFLOW", {"kind": kind.value, "reason": reason})
        self.con.commit()

    # ── broker truth ──────────────────────────────────────────────────────────

    def record_broker_positions(self, cid: str, positions: dict) -> None:
        """Record a broker position snapshot: ``{instrument_uid: signed units}``.

        This is the only thing that can move a construction into OPEN or CLOSED.
        An order response cannot: it reports what the exchange said about one
        request, not what the account holds.
        """
        self._event(cid, "POSITIONS", {"positions": positions})
        self.con.commit()
        self._reconcile_state(cid, positions)

    def _reconcile_state(self, cid: str, positions: dict) -> None:
        legs = self.legs(cid)
        state = self.state(cid)
        if state in (ConstructionState.CLOSED, ConstructionState.HALTED):
            return

        at_target = all(
            int(positions.get(l.instrument_uid, 0)) == l.target_units for l in legs)
        all_flat = all(int(positions.get(l.instrument_uid, 0)) == 0 for l in legs)

        if state in (ConstructionState.INTENT, ConstructionState.OPENING,
                     ConstructionState.PARTIALLY_OPEN):
            if at_target:
                self._set_state(cid, ConstructionState.OPEN, "broker confirms target")
            elif not all_flat:
                self._set_state(cid, ConstructionState.PARTIALLY_OPEN,
                                f"legs mismatched: {self.remainder(cid, positions)}")
        elif state in (ConstructionState.OPEN, ConstructionState.CLOSING,
                       ConstructionState.PARTIALLY_CLOSED):
            if all_flat:
                self._set_state(cid, ConstructionState.CLOSED, "broker confirms flat")
            elif state is not ConstructionState.OPEN:
                self._set_state(cid, ConstructionState.PARTIALLY_CLOSED,
                                f"remainder held: {self.remainder(cid, positions)}")
            elif not at_target:
                self._set_state(cid, ConstructionState.PARTIALLY_OPEN,
                                f"drifted off target: {self.remainder(cid, positions)}")

    def remainder(self, cid: str, positions: dict) -> dict:
        """Units still held per leg, from the broker snapshot."""
        return {l.instrument_uid: int(positions.get(l.instrument_uid, 0))
                for l in self.legs(cid)
                if int(positions.get(l.instrument_uid, 0)) != 0}

    def halt(self, cid: str, reason: str) -> None:
        self._set_state(cid, ConstructionState.HALTED, reason)

    # ── PnL ───────────────────────────────────────────────────────────────────

    def pnl(self, cid: str) -> PnlBreakdown:
        """Derive PnL from fills and cashflows only.

        Price PnL is signed cash: a SELL brings cash in, a BUY takes it out.
        Summed over a full round trip that is exactly the realised PnL, and it
        needs no notion of an "exit price" — which is what made it possible to
        book a close at a price that never traded.
        """
        legs = {l.instrument_uid: l for l in self.legs(cid)}
        price = 0.0
        commission = 0.0
        cash_broker = 0.0
        cash_model = 0.0
        by_kind: dict = {}
        missing: list = []

        for ev in self.events(cid):
            p = json.loads(ev["payload_json"])
            if ev["kind"] == "FILL":
                lots = int(p["lots_filled"])
                commission += float(p.get("commission_rub") or 0.0)
                if lots == 0:
                    continue
                leg = legs.get(p["instrument_uid"])
                unit_scale = leg.unit_scale if leg else 1
                pv = (leg.point_value_rub if leg and leg.point_value_rub else 1.0)
                units = lots * unit_scale
                cash = float(p["price_per_unit"]) * units * pv
                price += cash if str(p["side"]).upper() == "SELL" else -cash
            elif ev["kind"] == "CASHFLOW":
                amt = float(p["amount_rub"])
                if p["source"] == CashflowSource.BROKER.value:
                    cash_broker += amt
                else:
                    cash_model += amt
                    by_kind[p["kind"]] = by_kind.get(p["kind"], 0.0) + amt
            elif ev["kind"] == "MISSING_CASHFLOW":
                if p["kind"] not in missing:
                    missing.append(p["kind"])

        return PnlBreakdown(
            price_pnl_rub=round(price, 2),
            commission_rub=round(commission, 2),
            cashflow_broker_rub=round(cash_broker, 2),
            cashflow_model_rub=round(cash_model, 2),
            cashflow_model_by_kind={k: round(v, 2) for k, v in by_kind.items()},
            missing_cashflow_kinds=tuple(missing),
        )

    # ── invariants ────────────────────────────────────────────────────────────

    def verify(self, cid: str, positions: Optional[dict] = None
               ) -> list[InvariantViolation]:
        """Check the ledger's invariants. An empty list means it is consistent."""
        v: list[InvariantViolation] = []
        state = self.state(cid)
        legs = self.legs(cid)

        # Net filled units per leg, derived from fills alone.
        net: dict = {l.instrument_uid: 0 for l in legs}
        for ev in self.events(cid):
            if ev["kind"] != "FILL":
                continue
            p = json.loads(ev["payload_json"])
            lots = int(p["lots_filled"])
            if lots == 0:
                continue
            leg = next((l for l in legs if l.instrument_uid == p["instrument_uid"]), None)
            if leg is None:
                v.append(InvariantViolation(
                    "FILL_ON_UNKNOWN_LEG",
                    f"fill on {p['instrument_uid']} which is not a leg"))
                continue
            signed = lots * leg.unit_scale
            net[leg.instrument_uid] += signed if str(p["side"]).upper() == "BUY" else -signed

        # Invariant 1: CLOSED requires every leg flat, per the FILLS themselves.
        if state is ConstructionState.CLOSED:
            held = {u: n for u, n in net.items() if n != 0}
            if held:
                v.append(InvariantViolation(
                    "CLOSED_WITH_OPEN_LEGS",
                    f"state is CLOSED but fills leave {held} outstanding"))
            if positions:
                still = {u: int(positions.get(u, 0)) for u in net
                         if int(positions.get(u, 0)) != 0}
                if still:
                    v.append(InvariantViolation(
                        "CLOSED_BUT_BROKER_HOLDS",
                        f"state is CLOSED but the broker still reports {still}"))

        # Invariant 4: the journal must agree with the broker snapshot.
        if positions is not None:
            for uid, n in net.items():
                actual = int(positions.get(uid, 0))
                if actual != n:
                    v.append(InvariantViolation(
                        "JOURNAL_BROKER_MISMATCH",
                        f"{uid}: fills imply {n} units, broker reports {actual}"))

        # Invariant 7: PnL must reconcile to the kopeck against its components.
        p = self.pnl(cid)
        recomputed = (p.price_pnl_rub - p.commission_rub
                      + p.cashflow_broker_rub + p.cashflow_model_rub)
        if abs(recomputed - p.net_with_model_rub) > KOPECK:
            v.append(InvariantViolation(
                "PNL_DOES_NOT_RECONCILE",
                f"components sum to {recomputed} but net is {p.net_with_model_rub}"))

        # Invariant 5/6: a construction that is done but knowingly missing a
        # contractual cashflow must not be presented as a finished measurement.
        if state is ConstructionState.CLOSED and p.missing_cashflow_kinds:
            v.append(InvariantViolation(
                "CLOSED_WITH_MISSING_CASHFLOW",
                f"closed but these contractual flows were never observed: "
                f"{list(p.missing_cashflow_kinds)}. net_real is incomplete."))

        return v

    # ── portfolio-level guards ────────────────────────────────────────────────

    def holding_constructions(self) -> list[str]:
        marks = ",".join("?" * len(HOLDING_STATES))
        rows = self.con.execute(
            f"SELECT construction_id FROM constructions WHERE state IN ({marks})",
            tuple(s.value for s in HOLDING_STATES),
        ).fetchall()
        return [r["construction_id"] for r in rows]

    def entries_blocked(self) -> Optional[str]:
        """Reason new entries must be refused, or None.

        Invariant 8: uncertainty anywhere blocks entries everywhere. A stranded
        leg is not a problem local to one construction — it is evidence that the
        bot's picture of the account is wrong.
        """
        rows = self.con.execute(
            "SELECT construction_id, state FROM constructions WHERE state IN (?,?,?)",
            (ConstructionState.HALTED.value,
             ConstructionState.PARTIALLY_OPEN.value,
             ConstructionState.PARTIALLY_CLOSED.value),
        ).fetchall()
        if not rows:
            return None
        return "; ".join(f"{r['construction_id']} is {r['state']}" for r in rows)

    def controlled_uids(self) -> set:
        """Every instrument this ledger has ever touched.

        Reconciliation must sweep these, not only the legs the current
        construction expects. An orphan left by a previous construction is
        invisible to an expectation-shaped check — which is how a stray leg once
        bled for a week behind a reconcile that kept reporting a clean pair.
        """
        uids: set = set()
        for row in self.con.execute("SELECT legs_json FROM constructions"):
            for d in json.loads(row["legs_json"]):
                uids.add(d["instrument_uid"])
        return uids

    def find_orphans(self, positions: dict) -> dict:
        """Controlled instruments the broker holds that no construction expects."""
        expected: dict = {}
        for cid in self.holding_constructions():
            for leg in self.legs(cid):
                expected[leg.instrument_uid] = (
                    expected.get(leg.instrument_uid, 0) + leg.target_units)
        orphans = {}
        for uid in self.controlled_uids():
            actual = int(positions.get(uid, 0))
            if actual != expected.get(uid, 0):
                orphans[uid] = {"expected": expected.get(uid, 0), "actual": actual}
        return orphans

    def close(self) -> None:
        self.con.close()
