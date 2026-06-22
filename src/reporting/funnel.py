"""Research funnel: formal stage/gate evaluation for each strategy.

Pipeline:
  paper/research → candidate → sandbox execution → live candidate
                 → portfolio member → scaled allocation

This module decides, for one strategy, which stage it is in and whether it
meets the GATE to advance — or should FREEZE / KILL. The full criteria are
documented in docs/research_funnel.md; thresholds live in FunnelConfig.

HARD CONSTRAINT: no real-money trading ever. The automated funnel tops out at
"sandbox execution". Reaching the bar for "live candidate" is reported, but the
transition to live (and beyond) is a MANUAL human decision, blocked by policy —
never automated here.

Pure functions (stdlib only) for testability; `decide()` adapts a ServiceReport.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.reporting.metrics import FAMILY_RULES, Metrics, _DEFAULT_RULE

# Stages
STAGE_PAPER = "paper/research"
STAGE_CANDIDATE = "candidate"
STAGE_SANDBOX = "sandbox execution"
STAGE_LIVE_CANDIDATE = "live candidate"
STAGE_PORTFOLIO = "portfolio member"
STAGE_SCALED = "scaled allocation"

# Verdicts
V_INSUFFICIENT = "INSUFFICIENT_DATA"   # too few trades, still within time budget
V_LOW_ACTIVITY = "LOW_ACTIVITY"        # too few trades AND running too long → review
V_HOLD = "HOLD"                        # healthy, accumulating, gate not yet met
V_ADVANCE = "ADVANCE"                  # meets the gate to the next stage
V_FREEZE = "FREEZE"                    # pause / stop trading, keep observing
V_KILL = "KILL"                        # retire — structurally broken


@dataclass
class FunnelConfig:
    candidate_min_trades: int = 30     # paper→sandbox gate min sample
    sandbox_min_trades: int = 40       # sandbox→live gate min sample (real fills)
    promote_pf: float = 1.25
    live_promote_pf: float = 1.30
    freeze_pf: float = 1.0
    kill_pf: float = 0.8
    recovery_min: float = 1.0          # net PnL / MaxDD ("MaxDD acceptable")
    live_recovery_min: float = 1.5
    top1_max: float = 0.40             # best trade ≤ 40% of gross profit
    top3_max: float = 0.65             # top-3 ≤ 65% of gross profit
    max_api_errors: int = 50
    max_restarts: int = 5
    max_eval_days: int = 30            # low-activity staleness window
    kill_trades_mult: float = 2.0      # KILL needs ≥ mult × family min_freeze trades


@dataclass
class Criterion:
    name: str
    ok: bool
    actual: str
    target: str


@dataclass
class FunnelDecision:
    stage: str
    verdict: str
    advance_to: str
    criteria: list[Criterion] = field(default_factory=list)
    rationale: str = ""


# ── PF helpers (PF may be None=undefined or float('inf')) ────────────────────

def _pf_ge(pf: Optional[float], thr: float) -> bool:
    return pf is not None and (pf == float("inf") or pf >= thr)


def _pf_lt(pf: Optional[float], thr: float) -> bool:
    return pf is None or (pf != float("inf") and pf < thr)


def _recovery(pnl: float, max_dd: float) -> float:
    if max_dd <= 0:
        return float("inf") if pnl >= 0 else 0.0
    return pnl / max_dd


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if v == float("inf"):
            return "∞"
        return f"{v:.2f}"
    return str(v)


def evaluate(
    *,
    family: str,
    lifetime: Metrics,
    liveness: str,
    api_errors: int,
    restarts: int,
    observed_days: Optional[int],
    is_sandbox: bool,
    cfg: FunnelConfig = FunnelConfig(),
) -> FunnelDecision:
    rule = FAMILY_RULES.get(family, _DEFAULT_RULE)
    min_freeze = rule["min_freeze"]
    m = lifetime
    n = m.trades

    stage = STAGE_SANDBOX if is_sandbox else STAGE_PAPER
    advance_to = (STAGE_LIVE_CANDIDATE + " (MANUAL — blocked by no-live policy)"
                  if is_sandbox else STAGE_SANDBOX)

    gate_min = cfg.sandbox_min_trades if is_sandbox else cfg.candidate_min_trades
    pf_target = cfg.live_promote_pf if is_sandbox else cfg.promote_pf
    rec_target = cfg.live_recovery_min if is_sandbox else cfg.recovery_min

    recovery = _recovery(m.pnl_rub, m.max_dd_rub)
    tech_ok = (liveness == "OK" and api_errors <= cfg.max_api_errors
               and restarts <= cfg.max_restarts)
    growing_dd = m.max_dd_rub > 0 and m.current_dd >= 0.6 * m.max_dd_rub

    # Gate criteria (shown in the report regardless of verdict)
    crit = [
        Criterion("min trades", n >= gate_min, str(n), f"≥{gate_min}"),
        Criterion("PF", _pf_ge(m.pf, pf_target), _fmt(m.pf), f"≥{pf_target}"),
        Criterion("recovery (net/MaxDD)", recovery >= rec_target,
                  _fmt(recovery), f"≥{rec_target}"),
        Criterion("top-1 trade share", m.top1_share is not None and m.top1_share <= cfg.top1_max,
                  _fmt(m.top1_share), f"≤{cfg.top1_max}"),
        Criterion("top-3 trade share", m.top3_share is not None and m.top3_share <= cfg.top3_max,
                  _fmt(m.top3_share), f"≤{cfg.top3_max}"),
        Criterion("technical health", tech_ok,
                  f"live={liveness},api_err={api_errors},restarts={restarts}", "OK & low errors"),
        Criterion("no growing drawdown", not growing_dd,
                  f"curDD={m.current_dd:.0f}/maxDD={m.max_dd_rub:.0f}", "curDD<60% maxDD"),
    ]

    # ── Verdict precedence: KILL > FREEZE > data-gating > ADVANCE > HOLD ──────
    edge_broken = n >= min_freeze and _pf_lt(m.pf, cfg.freeze_pf)
    health_broken = liveness == "STALLED" or api_errors > cfg.max_api_errors or restarts > cfg.max_restarts
    kill_ready = n >= cfg.kill_trades_mult * min_freeze and _pf_lt(m.pf, cfg.kill_pf)

    if kill_ready:
        verdict = V_KILL
        rationale = (f"PF {_fmt(m.pf)} < {cfg.kill_pf} on {n} trades "
                     f"(≥{int(cfg.kill_trades_mult*min_freeze)}) — edge structurally absent.")
    elif edge_broken or health_broken:
        verdict = V_FREEZE
        reasons = []
        if edge_broken:
            reasons.append(f"PF {_fmt(m.pf)} < {cfg.freeze_pf} on {n}≥{min_freeze} trades")
        if liveness == "STALLED":
            reasons.append("trading STALLED")
        if api_errors > cfg.max_api_errors:
            reasons.append(f"{api_errors} API errors")
        if restarts > cfg.max_restarts:
            reasons.append(f"{restarts} restarts")
        rationale = "FREEZE: " + "; ".join(reasons) + "."
    elif n < gate_min:
        if observed_days is not None and observed_days > cfg.max_eval_days:
            verdict = V_LOW_ACTIVITY
            rationale = (f"Only {n} trades in {observed_days}d (>{cfg.max_eval_days}d) — "
                         f"signal too rare to evaluate; review usefulness.")
        else:
            verdict = V_INSUFFICIENT
            rationale = (f"{n}/{gate_min} trades — accumulating"
                         + (f" ({observed_days}d)" if observed_days is not None else "") + ".")
    elif all(c.ok for c in crit):
        verdict = V_ADVANCE
        rationale = f"All gate criteria met → ready to advance to {advance_to}."
    else:
        verdict = V_HOLD
        failed = [c.name for c in crit if not c.ok]
        rationale = "HOLD: healthy & sampled, but not yet qualifying — failing: " + ", ".join(failed) + "."
        if growing_dd:
            rationale += " ⚠ drawdown near its worst."

    return FunnelDecision(stage=stage, verdict=verdict, advance_to=advance_to,
                          criteria=crit, rationale=rationale)


def decide(report, cfg: FunnelConfig = FunnelConfig(),
           now: Optional[datetime] = None) -> FunnelDecision:
    """Adapt a fleet ServiceReport into a funnel decision."""
    now = now or datetime.now(tz=timezone.utc)
    observed_days = None
    if report.first_trade_ts is not None:
        observed_days = max(0, (now - report.first_trade_ts).days)
    return evaluate(
        family=report.svc.family,
        lifetime=report.lifetime,
        liveness=report.liveness,
        api_errors=report.api_errors,
        restarts=getattr(report, "restarts", 0),
        observed_days=observed_days,
        is_sandbox=(report.svc.family == "sandbox"),
        cfg=cfg,
    )
