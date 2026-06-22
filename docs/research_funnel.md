# Research Funnel — Strategy Promotion / Demotion

Formal pipeline for moving a strategy through lifecycle stages, with explicit,
measurable gates. Implemented in `src/reporting/funnel.py` (thresholds in
`FunnelConfig`); per-strategy decision reports via
`scripts/generate_decision_report.py` and the dashboard "Funnel decisions"
section.

> ⛔ **Hard constraint — no real-money trading, ever.** The *automated* funnel
> tops out at **sandbox execution** (T-Bank sandbox contour, virtual money).
> A strategy can be reported as meeting the bar for **live candidate**, but the
> transition to live and beyond is a **manual human decision, blocked by
> policy** — never performed by this system. `TINVEST_LIVE_TRADING_TOKEN` is
> never set/used.

## Stages

| # | Stage | What it means | Automated? |
|---|-------|----------------|-----------|
| 0 | **paper/research** | Paper service, READONLY data, virtual PnL. Accumulating trades. | yes |
| 1 | **candidate** | Paper strategy that has *passed the paper→sandbox gate* — ready to promote. | yes (flagged) |
| 2 | **sandbox execution** | Runs in the T-Bank sandbox contour with real (virtual-money) order execution → measures fills/slippage. | yes |
| 3 | **live candidate** | Passed the sandbox→live gate on *real execution* data. | **MANUAL — blocked by no-live policy** |
| 4 | **portfolio member** | Allocated real capital alongside other strategies. | **MANUAL / out of scope** |
| 5 | **scaled allocation** | Allocation increased after sustained live performance. | **MANUAL / out of scope** |

Stage is derived from the deployment: paper services → stage 0/1; the sandbox
service → stage 2. Stages 3–5 are documented for completeness but are never
entered automatically.

## Verdicts (per evaluation)

`ADVANCE` (gate met → promote) · `HOLD` (healthy, sampled, not yet qualifying) ·
`INSUFFICIENT_DATA` (too few trades, still within time budget) ·
`LOW_ACTIVITY` (too few trades **and** running too long → review usefulness) ·
`FREEZE` (pause/stop trading, keep observing) · `KILL` (retire).

## Principle: don't decide on 3–5 trades, but don't wait forever

- **Minimum sample** before *any* advance/freeze/kill on edge: a strategy needs
  `≥ candidate_min_trades` (default **30**) for the paper gate and
  `≥ family min_freeze` (hammer 60 / ORB 30 / momentum 40 / …) before an
  edge-based FREEZE, and `≥ 2× min_freeze` before a KILL. So 3–5 trades never
  trigger a decision — verdict stays `INSUFFICIENT_DATA`.
- **Upper time bound**: if a strategy has `< candidate_min_trades` but has been
  running `> max_eval_days` (default **30 days**), it is flagged
  `LOW_ACTIVITY` — the signal is too rare to be worth a slot; review/park/kill.

---

## Gate A — paper/research → sandbox execution

All must hold (on **lifetime** trades):

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| min trades | ≥ 30 | enough signal to trust the stats |
| Profit Factor | ≥ **1.25** | a real edge after modeled commission |
| recovery = net PnL / MaxDD | ≥ 1.0 | drawdown is recoverable / "MaxDD acceptable" |
| top-1 trade share of gross profit | ≤ 0.40 | not carried by one lucky trade |
| top-3 trade share of gross profit | ≤ 0.65 | not dependent on 1–2 trades |
| technical health | liveness OK, ≤ 50 API errors, ≤ 5 restarts | runs cleanly |
| no growing drawdown | current DD < 60% of MaxDD | not deteriorating right now |

Pass ⇒ `ADVANCE` (mark **candidate**, promote to a sandbox service).

> Note on slippage: paper PnL already nets modeled commission, but **true
> slippage is unknown on paper** — that is precisely what stage 2 measures.
> Strategies with a known-thin cost cushion (e.g. the pref/ordinary pairs
> basket, edge breakeven ~5 bps/leg) should be watched closely once in sandbox.

## Gate B — candidate → sandbox execution (operational)

`ADVANCE` at Gate A is the *signal*; actually deploying the sandbox service is
the operational step (new `hammertrade-sandbox-*` unit, funded sandbox account
≥ ~2× contract notional free — see project notes). One sandbox slot at a time
is fine; sandbox order execution has real failure modes (margin, fills).

## Gate C — sandbox execution → live candidate  *(report only; manual)*

Evaluated on **real sandbox fills** (PnL is execution-inclusive):

| Criterion | Threshold |
|-----------|-----------|
| min sandbox trades | ≥ 40 |
| Profit Factor (real fills) | ≥ **1.30** |
| recovery = net / MaxDD | ≥ 1.5 |
| top-1 / top-3 share | ≤ 0.40 / ≤ 0.65 |
| technical health | liveness OK, low errors/restarts |
| slippage drag | edge survives real fills (PF stays ≥ 1.30 net) |

Pass ⇒ reported as **live candidate** — then **STOP**: a human decides, and our
policy forbids live. No automation past here.

---

## FREEZE criteria (pause; keep collecting data)

Any of:
- **Edge gone**: PF < **1.0** after ≥ family `min_freeze` trades.
- **Technical**: trading liveness `STALLED`, or > 50 API errors, or > 5 restarts.
- **(Soft) growing drawdown**: current DD near the worst (≥ 60% of MaxDD) while
  the recent window is negative — surfaced as a ⚠ on `HOLD`, escalates to FREEZE
  if PF is also weak.
- **Edge dies after costs/slippage**: for engines that track theoretical vs
  market fill (pairs: `pnl_rub` vs `pnl_rub_market`; sandbox: real fills), net
  PF < 1.0 while gross PF > 1.0 → execution eats the edge (cf. VWAP reversion,
  which died at ≥2 pt slippage in backtest).

## KILL criteria (retire the strategy)

- PF < **0.8** after ≥ **2× min_freeze** trades (no edge, large sample), or
- Structurally broken / dead-on-arrival (e.g. hammer on tight-tick equities
  SBER/GAZP — PF ~0.2 across an 81-combo grid; never deploy without a different
  signal), or
- `LOW_ACTIVITY` that review concludes will never produce a usable sample.

FREEZE is reversible (re-tune, re-test); KILL means remove the service and
archive its data.

---

## Defaults (tunable in `FunnelConfig`)

```
candidate_min_trades=30   sandbox_min_trades=40
promote_pf=1.25           live_promote_pf=1.30
freeze_pf=1.0             kill_pf=0.8
recovery_min=1.0          live_recovery_min=1.5
top1_max=0.40             top3_max=0.65
max_api_errors=50         max_restarts=5
max_eval_days=30          kill_trades_mult=2.0
```

Family `min_freeze` / `promote` thresholds come from
`src/reporting/metrics.py FAMILY_RULES` (hammer PF<1.25@60, ORB PF<1.1@30, …).
