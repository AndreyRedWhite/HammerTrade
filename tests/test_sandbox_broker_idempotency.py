"""Regression tests for the sandbox order_id / idempotency-key split.

Bug (first sandbox trading day, 2026-06-15): the runner passed its internal
journal id (e.g. ``sandbox:SiU6:entry:abc123``) straight to the T-Bank sandbox
API as ``order_id``. The API requires ``order_id`` to be empty or a UUID, so
every order failed with ``INVALID_ARGUMENT: order_id should be empty or uuid``,
which tripped ``max_consecutive_errors`` and paused the service.

The fix keeps the internal journal id separate from the broker idempotency key
and guarantees that only a valid UUID ever reaches ``post_sandbox_order``.
"""
import uuid

import pytest

from src.sandbox.broker import SandboxBroker, _coerce_idempotency_key


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


# --- pure helper -----------------------------------------------------------

def test_coerce_none_generates_uuid():
    key = _coerce_idempotency_key(None)
    assert _is_uuid(key)


def test_coerce_empty_string_generates_uuid():
    key = _coerce_idempotency_key("")
    assert _is_uuid(key)


def test_coerce_internal_journal_id_generates_uuid():
    # The exact shape that broke production on 2026-06-15.
    internal_id = "sandbox:SiU6:entry:abc123def456"
    key = _coerce_idempotency_key(internal_id)
    assert _is_uuid(key)
    assert key != internal_id


def test_coerce_valid_uuid_passthrough():
    valid = str(uuid.uuid4())
    assert _coerce_idempotency_key(valid) == valid


# --- broker.post_order end-to-end (SDK helpers patched) --------------------

class _FakeOrderResponse:
    order_id = "broker-assigned-id"
    execution_report_status = "EXECUTION_REPORT_STATUS_FILL"
    lots_executed = 1
    executed_order_price = None
    executed_commission = None


class _FakeSandbox:
    def __init__(self):
        self.post_calls = []

    def post_sandbox_order(self, **kwargs):
        self.post_calls.append(kwargs)
        return _FakeOrderResponse()


class _FakeClient:
    def __init__(self):
        self.sandbox = _FakeSandbox()


@pytest.fixture
def patched_sdk_helpers(monkeypatch):
    # post_order calls these lazy-SDK helpers; the SDK is not installed locally.
    monkeypatch.setattr("src.sandbox.broker._order_direction", lambda side: f"DIR_{side}")
    monkeypatch.setattr("src.sandbox.broker._order_type", lambda ot: f"TYPE_{ot}")
    monkeypatch.setattr("src.sandbox.broker._status_name", lambda s: str(s))
    monkeypatch.setattr("src.sandbox.broker._money_to_float", lambda m: None)


def test_post_order_sends_valid_uuid_not_internal_id(patched_sdk_helpers):
    client = _FakeClient()
    broker = SandboxBroker(client)
    internal_id = "sandbox:SiU6:entry:deadbeef0000"

    broker.post_order(
        account_id="acct-1",
        instrument_uid="uid-1",
        quantity_lots=1,
        direction="SELL",
        order_type="MARKET",
        idempotency_key=internal_id,
    )

    sent = client.sandbox.post_calls[0]["order_id"]
    assert _is_uuid(sent)
    assert sent != internal_id


def test_post_order_generates_uuid_when_no_key(patched_sdk_helpers):
    client = _FakeClient()
    broker = SandboxBroker(client)

    broker.post_order(
        account_id="acct-1",
        instrument_uid="uid-1",
        quantity_lots=1,
        direction="BUY",
        order_type="MARKET",
    )

    sent = client.sandbox.post_calls[0]["order_id"]
    assert _is_uuid(sent)


def test_post_order_forwards_valid_uuid_unchanged(patched_sdk_helpers):
    client = _FakeClient()
    broker = SandboxBroker(client)
    valid = str(uuid.uuid4())

    broker.post_order(
        account_id="acct-1",
        instrument_uid="uid-1",
        quantity_lots=2,
        direction="SELL",
        order_type="MARKET",
        idempotency_key=valid,
    )

    assert client.sandbox.post_calls[0]["order_id"] == valid
