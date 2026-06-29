"""Thin wrapper around the T-Bank SandboxService (MVP-L1a).

This module talks to the **sandbox contour only** (sandbox-invest-public-api,
SANDBOX_TOKEN). It must never be used for live/prod order placement.

All SDK types are imported lazily inside functions/methods so that this
module can be imported (and the sandbox runner can run in --dry-run mode)
even when the t_tech SDK is not installed locally.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

from src.tbank.client import get_tbank_client
from src.tbank.settings import load_tbank_settings


@dataclass
class SandboxOrderResult:
    """Result of post_sandbox_order / get_sandbox_order_state, in plain types."""
    order_id: str
    status: str  # execution_report_status name, e.g. "EXECUTION_REPORT_STATUS_FILL"
    lots_requested: int
    lots_executed: int
    executed_price: Optional[float] = None
    commission_rub: Optional[float] = None


@dataclass
class SandboxPositionView:
    """A single instrument position as reported by the sandbox account."""
    figi: str
    instrument_uid: Optional[str]
    balance: int  # signed lot balance: positive=long, negative=short


def _money_to_float(money) -> Optional[float]:
    """Convert a t_tech MoneyValue (units/nano) to a float, or None."""
    if money is None:
        return None
    return float(money.units) + float(money.nano) / 1e9


def _quotation_to_float(quotation) -> Optional[float]:
    """Convert a t_tech Quotation (units/nano) to a float, or None."""
    if quotation is None:
        return None
    return float(quotation.units) + float(quotation.nano) / 1e9


def _rub_money_value(amount_rub: float):
    from t_tech.invest import MoneyValue

    units = int(amount_rub)
    nano = int(round((amount_rub - units) * 1e9))
    return MoneyValue(currency="rub", units=units, nano=nano)


def _price_quotation(price: float):
    from t_tech.invest import Quotation

    units = int(price)
    nano = int(round((price - units) * 1e9))
    return Quotation(units=units, nano=nano)


def _order_direction(side: str):
    from t_tech.invest import OrderDirection

    side = side.upper()
    if side == "BUY":
        return OrderDirection.ORDER_DIRECTION_BUY
    if side == "SELL":
        return OrderDirection.ORDER_DIRECTION_SELL
    raise ValueError(f"Unknown order side: {side!r}. Expected 'BUY' or 'SELL'.")


def _order_type(order_type: str):
    from t_tech.invest import OrderType

    order_type = order_type.upper()
    if order_type == "MARKET":
        return OrderType.ORDER_TYPE_MARKET
    if order_type == "LIMIT":
        return OrderType.ORDER_TYPE_LIMIT
    raise ValueError(f"Unknown order type: {order_type!r}. Expected 'MARKET' or 'LIMIT'.")


def _status_name(status) -> str:
    return status.name if hasattr(status, "name") else str(status)


def _coerce_idempotency_key(idempotency_key: Optional[str]) -> str:
    """Return a valid UUID string for the T-Bank sandbox ``order_id`` field.

    The T-Bank API requires the request ``order_id`` (idempotency key) to be
    empty or a valid UUID; passing an internal journal id like
    ``sandbox:SiU6:entry:abc123`` is rejected with
    ``INVALID_ARGUMENT: order_id should be empty or uuid``. We never want an
    internal id to reach the API, and we never want a malformed value to crash
    order placement, so: a valid UUID is passed through, anything else (or
    ``None``) yields a freshly generated UUID.
    """
    if idempotency_key:
        try:
            return str(uuid.UUID(str(idempotency_key)))
        except (ValueError, AttributeError, TypeError):
            pass
    return str(uuid.uuid4())


class SandboxBroker:
    """Wraps `client.sandbox.*` (T-Bank SandboxService) with plain Python types.

    `client` must be a connected t_tech.invest.Client obtained from
    `get_tbank_client(load_tbank_settings(env="sandbox"))` — see
    `get_sandbox_broker()` below for the convenience contextmanager.
    """

    def __init__(self, client):
        self._client = client

    def get_accounts(self) -> list[dict]:
        """List sandbox accounts as [{"id": ..., "name": ..., "status": ...}, ...]."""
        response = self._client.sandbox.get_sandbox_accounts()
        return [
            {
                "id": account.id,
                "name": account.name,
                "status": _status_name(account.status),
            }
            for account in response.accounts
        ]

    def open_account(self, name: str = "hammertrade-sandbox") -> str:
        """Open a new sandbox account and return its account_id."""
        response = self._client.sandbox.open_sandbox_account(name=name)
        return response.account_id

    def pay_in(self, account_id: str, amount_rub: float) -> Optional[float]:
        """Top up a sandbox account with RUB. Returns the new balance if reported."""
        response = self._client.sandbox.sandbox_pay_in(
            account_id=account_id,
            amount=_rub_money_value(amount_rub),
        )
        return _money_to_float(getattr(response, "balance", None))

    def get_positions(self, account_id: str) -> list[SandboxPositionView]:
        """Return all non-money positions (futures + securities) for the account."""
        response = self._client.sandbox.get_sandbox_positions(account_id=account_id)
        positions: list[SandboxPositionView] = []
        for fut in getattr(response, "futures", []) or []:
            positions.append(
                SandboxPositionView(
                    figi=fut.figi,
                    instrument_uid=getattr(fut, "instrument_uid", None) or None,
                    balance=int(fut.balance),
                )
            )
        for sec in getattr(response, "securities", []) or []:
            positions.append(
                SandboxPositionView(
                    figi=sec.figi,
                    instrument_uid=getattr(sec, "instrument_uid", None) or None,
                    balance=int(sec.balance),
                )
            )
        return positions

    def post_order(
        self,
        *,
        account_id: str,
        instrument_uid: str,
        quantity_lots: int,
        direction: str,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        idempotency_key: Optional[str] = None,
    ) -> SandboxOrderResult:
        """Submit a sandbox order. direction/order_type are 'BUY'/'SELL' and 'MARKET'/'LIMIT'.

        ``idempotency_key`` is the API request id (T-Bank ``order_id``); it must
        be a valid UUID. It is independent of any internal journal order id.
        A missing or malformed key is replaced with a fresh UUID so the API
        never rejects the request on ``order_id`` grounds.
        """
        kwargs = dict(
            instrument_id=instrument_uid,
            quantity=quantity_lots,
            direction=_order_direction(direction),
            account_id=account_id,
            order_type=_order_type(order_type),
            order_id=_coerce_idempotency_key(idempotency_key),
        )
        if price is not None:
            kwargs["price"] = _price_quotation(price)

        response = self._client.sandbox.post_sandbox_order(**kwargs)
        return SandboxOrderResult(
            order_id=response.order_id,
            status=_status_name(getattr(response, "execution_report_status", None)),
            lots_requested=quantity_lots,
            lots_executed=int(getattr(response, "lots_executed", 0)),
            executed_price=_money_to_float(getattr(response, "executed_order_price", None)),
            commission_rub=_money_to_float(getattr(response, "executed_commission", None)),
        )

    def get_order_state(self, account_id: str, order_id: str) -> SandboxOrderResult:
        """Fetch the current state of a previously submitted sandbox order."""
        response = self._client.sandbox.get_sandbox_order_state(
            account_id=account_id, order_id=order_id,
        )
        return SandboxOrderResult(
            order_id=response.order_id,
            status=_status_name(getattr(response, "execution_report_status", None)),
            lots_requested=int(getattr(response, "lots_requested", 0)),
            lots_executed=int(getattr(response, "lots_executed", 0)),
            executed_price=_money_to_float(getattr(response, "executed_order_price", None)),
            commission_rub=_money_to_float(getattr(response, "initial_commission", None)),
        )

    def cancel_order(self, account_id: str, order_id: str) -> None:
        """Cancel a working sandbox order (e.g. an unfilled LIMIT). Idempotent-ish:
        the API may raise if the order is already filled/cancelled — caller should
        treat exceptions as best-effort."""
        self._client.sandbox.cancel_sandbox_order(account_id=account_id, order_id=order_id)


@contextmanager
def get_sandbox_broker():
    """Connect to the sandbox contour and yield a SandboxBroker.

    Hard fails if SANDBOX_TOKEN is missing (via load_tbank_settings) or the
    t_tech SDK is not installed (via get_tbank_client -> _require_sdk).
    """
    settings = load_tbank_settings(env="sandbox")
    with get_tbank_client(settings) as client:
        yield SandboxBroker(client)
