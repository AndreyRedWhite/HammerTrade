"""Tests for the research-funnel stage/gate evaluation."""
from src.reporting.metrics import Metrics
from src.reporting.funnel import (
    STAGE_PAPER, STAGE_SANDBOX,
    V_ADVANCE, V_FREEZE, V_HOLD, V_INSUFFICIENT, V_KILL, V_LOW_ACTIVITY,
    FunnelConfig, evaluate,
)

CFG = FunnelConfig()


def _m(trades, pf, pnl=10000.0, max_dd=3000.0, top1=0.3, top3=0.5, current_dd=0.0):
    return Metrics(trades=trades, pnl_rub=pnl, pf=pf, max_dd_rub=max_dd,
                   top1_share=top1, top3_share=top3, current_dd=current_dd)


def _ev(m, family="hammer", liveness="OK", api=0, restarts=0, days=10, sandbox=False):
    return evaluate(family=family, lifetime=m, liveness=liveness, api_errors=api,
                    restarts=restarts, observed_days=days, is_sandbox=sandbox, cfg=CFG)


def test_few_trades_never_decide():
    # 4 trades with great PF must NOT advance — stays INSUFFICIENT
    d = _ev(_m(4, 5.0), days=3)
    assert d.verdict == V_INSUFFICIENT


def test_insufficient_then_low_activity():
    assert _ev(_m(10, 1.5), days=5).verdict == V_INSUFFICIENT
    assert _ev(_m(10, 1.5), days=45).verdict == V_LOW_ACTIVITY


def test_advance_all_criteria_pass():
    d = _ev(_m(40, 1.5))
    assert d.verdict == V_ADVANCE
    assert d.stage == STAGE_PAPER
    assert all(c.ok for c in d.criteria)


def test_hold_when_one_criterion_fails():
    # top-1 dependency too high → HOLD (not freeze/kill, sample ok)
    d = _ev(_m(40, 1.5, top1=0.7))
    assert d.verdict == V_HOLD
    assert any(c.name == "top-1 trade share" and not c.ok for c in d.criteria)


def test_freeze_on_broken_edge():
    # ORB min_freeze=30; PF<1.0 at 35 trades → FREEZE
    d = _ev(_m(35, 0.9), family="orb")
    assert d.verdict == V_FREEZE


def test_freeze_on_stalled_liveness():
    d = _ev(_m(40, 1.5), liveness="STALLED")
    assert d.verdict == V_FREEZE


def test_freeze_on_many_api_errors():
    d = _ev(_m(40, 1.5), api=100)
    assert d.verdict == V_FREEZE


def test_kill_large_sample_no_edge():
    # ORB: kill needs >= 2*30=60 trades and PF<0.8
    d = _ev(_m(70, 0.5), family="orb")
    assert d.verdict == V_KILL


def test_recovery_factor_blocks_advance():
    # huge MaxDD vs net → recovery < 1 → HOLD (not advance)
    d = _ev(_m(40, 1.5, pnl=1000, max_dd=5000))
    assert d.verdict == V_HOLD
    assert any(c.name.startswith("recovery") and not c.ok for c in d.criteria)


def test_sandbox_stage_and_manual_gate():
    d = _ev(_m(50, 1.4), family="sandbox", sandbox=True)
    assert d.stage == STAGE_SANDBOX
    assert "live candidate" in d.advance_to
    assert "MANUAL" in d.advance_to


def test_pf_none_with_large_sample_freezes():
    # all-losing (pf None) at big sample → at least FREEZE
    d = _ev(_m(40, None), family="orb")
    assert d.verdict in (V_FREEZE, V_KILL)
