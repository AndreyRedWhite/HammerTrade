"""Tests for Telegram fleet alerting (src/reporting/telegram_alert.py)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.reporting import telegram_alert as ta

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")


def _sender(sent):
    def send(text):
        sent.append(text)
        return True
    return send


def test_not_configured_is_silent(monkeypatch, tmp_path):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    sent = []
    action = ta.alert_on_problems(["service x: PAUSED"], tmp_path / "s.json",
                                  now=NOW, send=_sender(sent))
    assert action == "not_configured"
    assert sent == []


def test_first_problem_sends_and_persists_state(configured, tmp_path):
    sent = []
    state = tmp_path / "s.json"
    action = ta.alert_on_problems(["service x: PAUSED"], state, now=NOW, send=_sender(sent))
    assert action == "sent"
    assert "PAUSED" in sent[0] and "🚨" in sent[0]
    assert json.loads(state.read_text())["problems"] == ["service x: PAUSED"]


def test_same_problems_suppressed_within_window(configured, tmp_path):
    sent = []
    state = tmp_path / "s.json"
    ta.alert_on_problems(["service x: PAUSED"], state, now=NOW, send=_sender(sent))
    action = ta.alert_on_problems(["service x: PAUSED"], state,
                                  now=NOW + timedelta(minutes=10), send=_sender(sent))
    assert action == "suppressed"
    assert len(sent) == 1


def test_same_problems_realert_after_window(configured, tmp_path):
    sent = []
    state = tmp_path / "s.json"
    ta.alert_on_problems(["service x: PAUSED"], state, now=NOW, send=_sender(sent))
    action = ta.alert_on_problems(["service x: PAUSED"], state,
                                  now=NOW + timedelta(hours=5), send=_sender(sent))
    assert action == "sent"
    assert len(sent) == 2


def test_changed_problem_set_alerts_immediately(configured, tmp_path):
    sent = []
    state = tmp_path / "s.json"
    ta.alert_on_problems(["service x: PAUSED"], state, now=NOW, send=_sender(sent))
    action = ta.alert_on_problems(["service x: PAUSED", "unit y: failed"], state,
                                  now=NOW + timedelta(minutes=10), send=_sender(sent))
    assert action == "sent"
    assert "unit y: failed" in sent[1]


def test_recovery_sends_once_and_clears_state(configured, tmp_path):
    sent = []
    state = tmp_path / "s.json"
    ta.alert_on_problems(["service x: PAUSED"], state, now=NOW, send=_sender(sent))
    action = ta.alert_on_problems([], state, now=NOW + timedelta(minutes=20), send=_sender(sent))
    assert action == "recovered"
    assert "✅" in sent[1]
    assert not state.exists()
    # healthy again with no pending state → nothing sent
    action = ta.alert_on_problems([], state, now=NOW + timedelta(minutes=30), send=_sender(sent))
    assert action == "none"
    assert len(sent) == 2


def test_send_failure_keeps_state_for_retry(configured, tmp_path):
    state = tmp_path / "s.json"
    action = ta.alert_on_problems(["service x: PAUSED"], state,
                                  now=NOW, send=lambda t: False)
    assert action == "send_failed"
    assert not state.exists()  # nothing recorded → next run retries
