# Cost-Reality Audit & Sandbox Fixes — 2026-06-28

Full report of a single session that started from "the server seems broken /
paper is profitable but sandbox always loses" and ended by uncovering that the
entire apparent profitability of the futures strategies was a costing artifact.

**TL;DR**
1. Server had hung from an OOM (a `whisper` process on a swap-less 3.8 GB box) — recovered, added a 4 GB swap file.
2. Sandbox lost (while paper "won") because of a **sticky consecutive-loss circuit breaker** that never reset → permanent lockout. Fixed: it's now a daily breaker.
3. The sandbox computed PnL from **idealized engine prices with a placeholder commission** and never used real fills. Fixed: it now recomputes from actual broker fills + real commission, and records slippage.
4. Real T-Bank futures commission is **0.025 % of contract value per leg (~38 ₽/round-trip on SiU6)** — the model assumed ~0.
5. **`point_value_rub` for Si was 10, must be 1** (MOEX Si step value = 1 ₽/point). This overstated all Si PnL 10×. Fixed across the fleet.
6. **Re-ran all backtests net of the corrected economics.** Only **ORB breakout** (large targets) and the **market-neutral pairs basket** survive real costs. Hammer, momentum, VWAP-reversion, ORF are all net-negative — the apparent edges were the 10× point-value error plus ~0 commission.

---

## 0. Context

- Project: `/Users/Andrey.Vorontsov/PycharmProjects/HammerTrade` — multi-strategy research + paper/sandbox trading on MOEX futures. No live trading; T-Bank **sandbox-contour** orders (virtual money) allowed.
- Server: Yandex Cloud `158.160.204.201`, app at `/opt/hammertrade`, `.venv/bin/python`. Deploy = scp (server is not a clean git checkout). User commits straight to `main`.
- ~28 long-running services + report timers + a public HTTPS dashboard.

---

## 1. Server outage — OOM on a swap-less box

**Symptom:** SSH and the HTTPS dashboard both hung. Ping OK and TCP ports 22/443 accepted (kernel-level SYN/ACK), but neither sshd gave its banner nor nginx finished TLS. That pattern = userspace resource starvation, not a network/firewall problem.

**Root cause:** a `whisper` process (OpenAI speech-to-text, UID 1000 = user) consumed ~1.4 GB RSS on a **3.8 GB box with NO swap**. The OOM-killer fired twice (`dmesg -T | grep -i oom`); 15-min `load average` hit **89.78**. The OOM-killer killed whisper itself (largest), so the **trading fleet was untouched (28 services active, 0 restarts)** and the host recovered on its own.

**Fix:** added a **4 GB swap file** — `/swapfile` (dd, chmod 600, mkswap, swapon), persisted in `/etc/fstab` (`/swapfile none swap sw 0 0`), `vm.swappiness=10` in `/etc/sysctl.d/99-swappiness.conf`. Memory pressure now degrades gracefully instead of hanging SSH.

**Lesson:** pingable + ports open but daemons silent (banner-exchange timeout, curl 000) ⇒ suspect OOM/CPU/disk starvation, not firewall. Don't run heavy ML on this box (or cap it: `systemd-run --scope -p MemoryMax=…`).

---

## 2. Why sandbox lost while paper "won" — the sticky circuit breaker

**Investigation:** a like-for-like comparison of SiU6 hammer SELL baseline in paper (`data/paper/paper_state_siu6.sqlite`) vs sandbox (`data/sandbox/sandbox_state_hammer_baseline_siu6.sqlite`). Every matched trade was identical to the point (same entry/exit/PnL). Sandbox took only **10 of 22 signals**; the 12 it skipped netted **+1779 ₽** (mostly winners). Skips were all `RISK_BLOCK: trading_paused reason=max_consecutive_losses_exceeded`.

**Bug:** `src/sandbox/risk.py update_after_trade()` set `trading_paused=True` after `max_consecutive_losses` (=3) losing trades, and **nothing ever reset it**. `consecutive_losses` only cleared on a win, but once paused no trade can happen → permanent deadlock. For a positive-expectancy strategy a 3-loss streak is normal variance (~9 % at WR 55 %), so the strategy permanently disabled itself mid-drawdown and never joined the recovery → a steady net loss. Paper has no such breaker.

**Fix (commit `707e446`):** made it a **daily** circuit breaker.
- `risk.reset_for_new_day(risk_state)` lifts only daily-scoped pauses (`max_consecutive_losses_exceeded`, `max_daily_loss_exceeded`) and zeroes `consecutive_losses`. Hard halts (reconciliation_failed, max_total_loss_exceeded, max_exit_retries_exceeded, max_consecutive_errors) are NOT auto-cleared (manual review).
- The runner calls it on the first market-open cycle of a new trading day, tracked via `last_active_day` in the `sandbox_state` kv store. An unset key self-heals an already-stuck pause on restart.
- `max_consecutive_losses` 3 → **6** in both sandbox configs (genuine-anomaly guard, P≈0.8 %).
- This immediately self-healed the baseline (paused since Jun 25) on restart.

---

## 3. The bigger bug — sandbox PnL ignored real fills and real commission

**Discovery:** the sandbox's closed-trade PnL came from the engine's **idealized prices** (stop/take levels) with a **placeholder commission** (`commission_per_trade=0.025` → ~0.05 ₽/round-trip). The broker's actual `avg_fill_price` and reported commission were recorded on the order rows but **never fed back into the trade PnL** — which is exactly why sandbox matched paper to the point. So the sandbox was not measuring execution realism at all.

Empirically:
- Broker commission ≈ **38.2 ₽/order = 0.05 % of notional** (i.e. notional ≈ price ≈ 76 400 ₽).
- Real fills differed from idealized by ~13 pt entry / ~28 pt exit.
- Sandbox baseline: reported net −1490 vs **TRUE net −2204** (real fills + real commission, −714 drag over 10 trades).

**Fix (commit `71d1df4`):**
- `engine.realized_pnl_from_fills()` recomputes gross/net from actual entry/exit fills + broker commission; `engine.raw_slippage()` gives signed actual-vs-expected fill diff.
- Runner anchors the trade to the real entry fill, recomputes PnL from real fills + real commission at exit, and populates `slippage_points/slippage_rub` on the order rows.
- Forward-only (history not rewritten).

---

## 4. Paused-service alert (so a stuck pause is never silent again)

**Fix (commit `71d1df4`):** sandbox status now carries `trading_paused_reason`; `check_all_paper_status.py._health` flags halted services as **PAUSED / RECON_FAIL / KILLED** (non-OK, exit 1) with the reason. Today's bug (a 3-day-stuck pause) would now be surfaced loudly.

---

## 5. Long-side hammer should NOT be promoted

The funnel verdict for the BUY-side paper service was checked: `paper-long — INSUFFICIENT_DATA, 26 tr, PnL −1051 ₽` (negative even before real commission); `paper-mxu6-buy — HOLD, −3102 ₽`. The in-sample backtest (PF 2.14) did **not** hold out-of-sample. Recommendation: do not promote.

---

## 6. Commission is real and large (user-confirmed)

Real T-Bank futures commission (lowest daily-volume tier): **0.025 % of contract value per leg** (0.020 % > 12 M₽/day, 0.015 % > 17.5 M₽). For SiU6 ~76 400 ₽ notional that is **~19 ₽/leg ≈ 38 ₽/round-trip**. The sandbox had been charging 0.05 %/leg (double). The model assumed ~0.

True-cost on the live paper data (at the then-current pv=10): SiU6 hammer SELL baseline **+983 reported → −1572 net**; maxhold5 +1103 → −1489; BUY long −1053 → −2042. All negative.

---

## 7. The 10× point-value bug (confirmed against the contract spec)

The broker bills 0.05 % of notional and `38.2 = 0.0005 × 76 400`, i.e. it treats contract value ≈ price → **tick value ≈ 1 ₽/point**. The project used `point_value_rub=10` for Si everywhere, while the analogous **EuU6 (EUR/RUB) was already correctly 1**.

**Confirmed** via the MOEX Si spec (moex.com + ATAS): contract = 1000 USD, price step 1 ₽, **step value = 1 ₽/point → point_value must be 1.** The wrong 10 overstated all Si PnL 10× (PF/WR unaffected — scale-invariant).

**Fix (commit `0950168`):** `point_value_rub` 10 → 1 and a realistic commission set for every Si live service:
- `configs/hammer_detector_balanced.env`: POINT_VALUE_RUB 10→1, COMMISSION_PER_TRADE 0.025→19 (per leg, engine ×2). Drives hammer paper (paper/maxhold5/long) + both sandbox services.
- `momentum_continuation_siu6…yaml` + `vwap_reversion_siu6…yaml`: point_value 1.0, rub_per_trade 38.
- Server systemd (CLI flags) for `paper-orb`, `-orb-long`, `-orb-siu6-filtered`, `-vwap-siu6`, `-orf-siu6`: `--point-value-rub 1.0 --commission-rub 38.0` (.bak backups kept, daemon-reloaded). All 11 Si services restarted, active.

Forward-only (historical DB rows keep the old 10× scale).

---

## 8. Full backtest re-run net of corrected economics

Re-ran every backtest with **point_value=1 + real commission (38 ₽/round-trip)**. Because the research scripts ignore the config cost block (see §9), results were recomputed from the invariant `pnl_points`. Data: SiM6 Jan15–Apr9 (train) + May (OOS), in-sample = optimistic.

**Decisive factor = average gross move per trade vs the ~38 ₽ commission floor.**

| Strategy (in-sample SiM6) | avg gross/trade | trades | verdict net of real costs |
|---|---|---|---|
| **ORB SHORT 2R (OR 10:00–11:00)** | hundreds of pt | 41 | ✅ **PF 1.33 train (+2115 ₽) / 1.35 OOS (+622 ₽)** |
| **Pairs basket** (live, 8 closed) | — | 8 | ✅ **real +223 ₽** (market-neutral) |
| Momentum MC_atr2.0_vol2.0_r2.0 | 31 ₽ | 60 | ❌ net −411 (PF_oos 2.88 = 3 outliers, 78.9 % concentration) |
| Opening-Range Fade | 6–18 ₽ | 38 | ❌ OOS PF 0.58–0.73 |
| VWAP-hammer-filter | 14–18 ₽ | 57–113 | ❌ OOS PF 0.00 |
| VWAP reversion | **4.5–5.7 ₽** | 178–180 | ❌ **net −5813** (high-frequency death) |
| Hammer (all profiles, grid) | ~18 ₽ | 232 | ❌ best config +325 (PF 1.09); 3/240 configs net-positive (1 %) |

**Principle:** only large-target / low-frequency strategies (ORB breakout, pairs) clear the commission floor. All high-frequency small-move scalping on 1-minute Si is structurally dead. The headline figures (e.g. hammer PF 3.54 / +18 764) were the 10× point-value error plus ~0 commission.

Artifacts: `reports/backtest_grid_REALCOST_SiM6_SELL.md`, `out/research_orb_walkforward_*`, `out/research_multistrategy_r2_summary_latest.csv`. Helper scripts added: `scripts/analyze_paper_vs_sandbox.py`, `analyze_sandbox_skips.py`, `investigate_sandbox_costs.py`, `true_cost_pnl.py`.

---

## 9. Process bugs discovered (not yet fixed)

1. **Research runners ignore the cost config.** `run_backtest_grid.py`, `research_orb_walkforward.py`, `research_multistrategy_r2.py` hardcode `point_value≈10 / commission≈0.05` and ignore the config `commission` block — so every historical research report was at pv=10 / ~0 commission and overstated. Fix: thread `point_value_rub` + commission through the runners (or always recompute net from `pnl_points`).
2. **Pairs reporting shows the ideal PnL.** The dashboard/fleet reports show pairs `pnl_rub` (ideal/mid, +1133) instead of `pnl_rub_market` (real fills + cost, +223). Switch the reporting to the market metric.
3. **Code defaults still wrong.** `point_value_rub=10.0` remains the default in `src/config.py` and every engine; fine only because live services now set values explicitly. Non-Si point values (BRQ6=734.39, GDU6=73.44) are unverified.

---

## 10. Strategic implications

- Out of ~20 live services, only **two directions have a real cost-adjusted edge: ORB breakout and the market-neutral pairs basket.** Everything else (hammer / momentum / VWAP / ORF on 1-minute Si) should be frozen.
- A viable strategy needs **avg gross move per trade ≫ ~38 ₽/round-trip** — i.e. fewer, bigger trades (higher R / longer holds / higher timeframe), not higher frequency.
- Bake **real commission into every backtest and funnel gate from the start** (e.g. avg win > 3× commission). Re-evaluate all research net of costs.
- The pairs basket also diversifies the otherwise 100 %-SHORT-Si book — the most promising direction to scale (after confirming on a larger sample).

---

## 11. Commits (all on `main`)

| Commit | What |
|---|---|
| `707e446` | fix(sandbox): daily reset of consecutive-loss circuit breaker |
| `71d1df4` | feat(sandbox): real-fill PnL + commission + slippage; paused-service alert |
| `7f277e4` | analysis: real-rate (0.025 %/leg) true-cost PnL |
| `0950168` | fix(si): point_value 10→1 + realistic commission across the fleet |
| `bdc79c4` | research: corrected economics in SiM6 configs + cost-adjusted re-run findings |

Tests: +17 across `test_sandbox_risk_manager`, `test_sandbox_engine`, `test_sandbox_status`, `test_check_all_paper_status`; full suite 748→765 green.

Infra: 4 GB swap added on the server; all Si services restarted and active.

---

## 12. Open follow-ups

- [ ] Freeze/KILL the cost-dead strategies in the funnel (hammer/momentum/VWAP/ORF on Si); keep 1–2 as benchmarks.
- [ ] Thread commission + point_value through the research runners so reports stop overstating.
- [ ] Switch pairs reporting to `pnl_rub_market`.
- [ ] Verify BRQ6/GDU6 point values; fix code defaults (`point_value_rub=10.0`).
- [ ] Restore SiM6 Jan–Apr raw candles to the server if full server-side re-runs are wanted (local has them).
- [ ] Develop ORB + pairs (bigger samples, robustness); consider higher-timeframe variants of the dead strategies where moves clear the commission floor.
