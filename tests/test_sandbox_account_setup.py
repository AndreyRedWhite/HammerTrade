"""Tests for scripts/sandbox_account_setup.py (MVP-L1a).

The T-Bank SDK is not available locally, so get_sandbox_broker is mocked
with a fake broker exposing the same plain-Python interface as
src.sandbox.broker.SandboxBroker.
"""
import sys
from contextlib import contextmanager

import pytest

import scripts.sandbox_account_setup as m


class _FakeBroker:
    def __init__(self, accounts=None, opened_account_id="acct-new", pay_in_balance=40000.0):
        self._accounts = accounts if accounts is not None else []
        self._opened_account_id = opened_account_id
        self._pay_in_balance = pay_in_balance
        self.open_account_calls = []
        self.pay_in_calls = []

    def get_accounts(self):
        return self._accounts

    def open_account(self, name="hammertrade-sandbox"):
        self.open_account_calls.append(name)
        return self._opened_account_id

    def pay_in(self, account_id, amount_rub):
        self.pay_in_calls.append((account_id, amount_rub))
        return self._pay_in_balance


def _patch_broker(monkeypatch, fake_broker):
    @contextmanager
    def _fake_get_sandbox_broker():
        yield fake_broker

    monkeypatch.setattr("src.sandbox.broker.get_sandbox_broker", _fake_get_sandbox_broker)


def test_missing_token_hard_fails(monkeypatch, capsys):
    # Use an empty value (not delenv): main() calls load_dotenv(), which would
    # otherwise repopulate SANDBOX_TOKEN from a real local .env file.
    monkeypatch.setenv("SANDBOX_TOKEN", "")
    monkeypatch.setattr(sys, "argv", ["sandbox_account_setup.py"])

    with pytest.raises(SystemExit) as exc:
        m.main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "SANDBOX_TOKEN" in captured.err


def test_uses_existing_account(monkeypatch, capsys):
    monkeypatch.setenv("SANDBOX_TOKEN", "super-secret-token-value")
    fake_broker = _FakeBroker(accounts=[{"id": "acct-1", "name": "x", "status": "ACCOUNT_STATUS_OPEN"}])
    _patch_broker(monkeypatch, fake_broker)
    monkeypatch.setattr(sys, "argv", ["sandbox_account_setup.py"])

    m.main()

    out = capsys.readouterr().out
    assert "Using existing sandbox account: acct-1" in out
    assert "SANDBOX_ACCOUNT_ID=acct-1" in out
    assert fake_broker.open_account_calls == []
    assert "super-secret-token-value" not in out


def test_create_if_missing_creates_account(monkeypatch, capsys):
    monkeypatch.setenv("SANDBOX_TOKEN", "super-secret-token-value")
    fake_broker = _FakeBroker(accounts=[], opened_account_id="acct-new")
    _patch_broker(monkeypatch, fake_broker)
    monkeypatch.setattr(sys, "argv", ["sandbox_account_setup.py", "--create-if-missing"])

    m.main()

    out = capsys.readouterr().out
    assert "Created new sandbox account: acct-new" in out
    assert "SANDBOX_ACCOUNT_ID=acct-new" in out
    assert fake_broker.open_account_calls == ["hammertrade-sandbox"]
    assert "super-secret-token-value" not in out


def test_no_accounts_without_create_flag_exits(monkeypatch, capsys):
    monkeypatch.setenv("SANDBOX_TOKEN", "dummy")
    fake_broker = _FakeBroker(accounts=[])
    _patch_broker(monkeypatch, fake_broker)
    monkeypatch.setattr(sys, "argv", ["sandbox_account_setup.py"])

    with pytest.raises(SystemExit) as exc:
        m.main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "--create-if-missing" in captured.err


def test_top_up_calls_pay_in(monkeypatch, capsys):
    monkeypatch.setenv("SANDBOX_TOKEN", "dummy")
    fake_broker = _FakeBroker(
        accounts=[{"id": "acct-1", "name": "x", "status": "ACCOUNT_STATUS_OPEN"}],
        pay_in_balance=40000.0,
    )
    _patch_broker(monkeypatch, fake_broker)
    monkeypatch.setattr(sys, "argv", ["sandbox_account_setup.py", "--top-up-rub", "40000"])

    m.main()

    out = capsys.readouterr().out
    assert fake_broker.pay_in_calls == [("acct-1", 40000.0)]
    assert "Topped up account acct-1 by 40000.0 RUB" in out
    assert "New balance: 40000.0 RUB" in out


def test_never_prints_token_value(monkeypatch, capsys):
    secret = "tok_super_secret_abc123"
    monkeypatch.setenv("SANDBOX_TOKEN", secret)
    fake_broker = _FakeBroker(accounts=[{"id": "acct-1", "name": "x", "status": "ACCOUNT_STATUS_OPEN"}])
    _patch_broker(monkeypatch, fake_broker)
    monkeypatch.setattr(sys, "argv", ["sandbox_account_setup.py", "--top-up-rub", "1000"])

    m.main()

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_dedicated_creates_named_account_when_other_accounts_exist(monkeypatch, capsys):
    monkeypatch.setenv("SANDBOX_TOKEN", "dummy")
    fake_broker = _FakeBroker(
        accounts=[{"id": "old", "name": "other", "status": "OPEN"}],
        opened_account_id="dedicated-new",
    )
    _patch_broker(monkeypatch, fake_broker)
    monkeypatch.setattr(sys, "argv", ["sandbox_account_setup.py", "--dedicated",
                                      "--account-name", "hammertrade-xsec"])
    m.main()
    assert fake_broker.open_account_calls == ["hammertrade-xsec"]
    assert "SANDBOX_ACCOUNT_ID=dedicated-new" in capsys.readouterr().out


def test_dedicated_reuses_matching_named_account(monkeypatch, capsys):
    monkeypatch.setenv("SANDBOX_TOKEN", "dummy")
    fake_broker = _FakeBroker(accounts=[
        {"id": "other", "name": "other", "status": "OPEN"},
        {"id": "match", "name": "hammertrade-xsec", "status": "OPEN"},
    ])
    _patch_broker(monkeypatch, fake_broker)
    monkeypatch.setattr(sys, "argv", ["sandbox_account_setup.py", "--dedicated",
                                      "--account-name", "hammertrade-xsec"])
    m.main()
    assert fake_broker.open_account_calls == []
    assert "SANDBOX_ACCOUNT_ID=match" in capsys.readouterr().out
