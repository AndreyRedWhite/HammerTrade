"""Tests for the fleet status checker's halt detection (scripts/check_all_paper_status.py)."""
import scripts.check_all_paper_status as c


def test_health_flags_trading_paused():
    assert c._health({"trading_state": "TRADING_PAUSED", "market_open": True}, 1.0, 600) == "PAUSED"


def test_health_flags_reconciliation_failed():
    assert c._health({"trading_state": "RECONCILIATION_FAILED"}, 1.0, 600) == "RECON_FAIL"


def test_health_flags_kill_switch():
    assert c._health({"trading_state": "KILL_SWITCH_ACTIVE"}, 1.0, 600) == "KILLED"


def test_health_ok_when_running():
    assert c._health({"trading_state": "WAITING_FOR_SIGNAL", "market_open": True}, 1.0, 600) == "OK"


def test_health_halt_takes_priority_over_stale():
    # A paused service that is also stale should report the halt, not STALE.
    s = {"trading_state": "TRADING_PAUSED", "market_open": True}
    assert c._health(s, age_sec=99999, stale_sec=600) == "PAUSED"
