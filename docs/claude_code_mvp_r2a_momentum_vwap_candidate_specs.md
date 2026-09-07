# Claude Code Prompt — MVP-R2a: Momentum + VWAP Reversion Paper Candidate Specs

## Контекст проекта

Проект: `HammerTrade / MOEXF`.

Это исследовательская платформа для торговых стратегий на MOEX futures через T-Bank Invest API.

Текущий сервер:

```text
Server: 158.160.204.201
User: vorontsov
Project path: /opt/hammertrade
Virtualenv: /opt/hammertrade/.venv
```

Сейчас работают три paper-сервиса:

```text
1. hammer-baseline
   systemd: hammertrade-paper.service
   ticker: SiM6
   direction: SELL
   max_hold_bars: None
   db: data/paper/paper_state.sqlite
   status: runtime/paper_status_SiM6_SELL.json

2. hammer-maxhold5
   systemd: hammertrade-paper-maxhold5.service
   ticker: SiM6
   direction: SELL
   max_hold_bars: 5
   db: data/paper/paper_state_maxhold5.sqlite
   status: runtime/paper_status_SiM6_SELL_maxhold5.json

3. orb-paper
   systemd: hammertrade-paper-orb.service
   strategy: opening_range_breakout
   ticker: SiM6
   direction: SHORT
   opening range: 10:00–11:00 MSK
   take_r: 2.0
   orders_enabled: false
   db: data/paper/paper_state_orb.sqlite
   status: runtime/paper_status_SiM6_ORB.json
```

Важно:

```text
Текущие paper-сервисы НЕ менять.
Новые paper-сервисы НЕ запускать в этом MVP.
Sandbox/real orders НЕ запускать.
```

---

## Текущий статус стратегий

## Hammer maxhold5

Последний decision report:

```text
Decision: CONTINUE

May 13 – Jun 2:
  Trades: 61
  PF: 1.396
  Net: +1 877 RUB
  Baseline same window: +317 RUB
  MaxDD: 1 120 RUB vs baseline 3 231 RUB
```

Вывод:

```text
hammer-maxhold5 продолжает работать как основной hammer-кандидат.
```

## ORB paper

ORB уже запущен как третий paper service.

Профиль:

```text
Opening Range Breakout
Ticker: SiM6
Direction: SHORT
Opening Range: 10:00–11:00 MSK
Take R: 2.0
Stop: opposite_range
Entry: breakout_level
Time exit: 18:40 MSK
Max trades/day: 1
Orders enabled: false
```

Первый торговый день прошёл корректно:

```text
2026-06-01:
  OR high=72 231
  OR low=71 690
  range=541 pts
  breakout вниз не было
  0 trades
  DONE_FOR_DAY корректно
```

---

## MVP-R2 Multi-Strategy Research Pack — результаты

В R2 были исследованы новые стратегии offline.

Результаты:

```text
Momentum MC_atr2.0_vol2.0_r2.0:
  PF_train: 1.519
  Trades_train: 60
  PF_OOS: 2.883
  Trades_OOS: 20
  Decision: NEEDS_MORE_DATA

VWAP Reversion VR_d1.0_s1.0_1.5R:
  PF_train: 1.294
  Trades_train: 180
  PF_OOS: 1.475
  Trades_OOS: 55
  Decision: NEEDS_MORE_DATA

Opening Range Fade ORF_10:00-10:30_n5:
  PF_train: 1.443
  Trades_train: 38
  PF_OOS: 0.682
  Trades_OOS: 10
  Decision: REJECT / not active candidate

VWAP Hammer Filter high_above_vwap:
  PF_train: 3.240
  Trades_train: 66
  Decision: helper / secondary quality check, not standalone paper strategy
```

Ключевые выводы:

```text
1. Momentum Continuation — самый сильный OOS-сигнал, PF 2.883 на May OOS, но выборка 20 сделок и высокая концентрация.
2. VWAP Reversion — наиболее статистически устойчивая, 180 train trades и 55 OOS trades, но чувствительна к slippage.
3. OR Fade развалился на OOS и пока отклонён.
4. VWAP Hammer Filter полезен как аналитический признак, но не повод менять live hammer сейчас.
```

---

## Rollover context

Документ готов:

```text
docs/rollover_siu6_plan.md
```

Важные даты:

```text
SiM6 expiration_date: 2026-06-19
SiU6 expiration_date: 2026-09-18
Плановая подготовка rollover: до 2026-06-10
SiU6 liquidity monitoring уже идёт
```

Последняя диагностика:

```text
SiU6 volume около 250 лот/бар
target: 500 лот/бар
роллировать пока рано, но ликвидность растёт
```

Для этого MVP:

```text
Не выполнять rollover.
Но все future paper specs должны быть совместимы с SiU6.
```

---

# Главная цель MVP-R2a

Подготовить Momentum Continuation и VWAP Reversion как paper candidates.

Важно:

```text
НЕ запускать новые сервисы сейчас.
НЕ включать их в systemd.
НЕ делать sandbox/live.
```

Нужно создать:

```text
1. Paper candidate spec для Momentum Continuation.
2. Paper candidate spec для VWAP Reversion.
3. Paper readiness checklist для каждой стратегии.
4. Future artifact naming для SiU6.
5. Systemd unit examples, но не устанавливать их.
6. Config examples для будущего paper-запуска.
7. Execution-risk analysis, особенно для VWAP.
8. Decision memo: что запускать первым после rollover и почему.
```

---

# Жёсткие ограничения

Строго запрещено:

- менять `hammertrade-paper.service`;
- менять `hammertrade-paper-maxhold5.service`;
- менять `hammertrade-paper-orb.service`;
- менять текущие systemd unit files;
- менять текущие paper DB/status/csv/log;
- сбрасывать state;
- менять HammerDetector;
- менять hammer strategy logic;
- менять ORB paper strategy params;
- запускать Momentum paper service;
- запускать VWAP paper service;
- запускать sandbox orders;
- запускать real orders;
- выполнять rollover;
- менять `.env`;
- печатать токены;
- удалять SQLite/CSV/reports/logs;
- обещать прибыль;
- делать вывод “стратегия доказана”.

Разрешено:

- создавать docs;
- создавать config examples;
- создавать systemd example units;
- создавать paper candidate specs;
- создавать readiness checklist;
- добавлять helper scripts только read-only;
- расширять docs/paper_candidates;
- запускать offline reports на существующих R2 artifacts;
- проверять current service status.

---

# Что изучить перед реализацией

Изучи:

```text
reports/research_multistrategy_r2_latest.md
out/research_multistrategy_r2_summary_latest.csv
docs/paper_candidates/
src/strategies/momentum_continuation/
src/strategies/vwap_reversion/
src/research/vwap.py
src/research/slippage.py
src/research/robustness.py
configs/research/multistrategy_r2_sim6.yaml
docs/rollover_siu6_plan.md
deploy/systemd/
scripts/check_all_paper_status.py
scripts/compare_all_paper_experiments.py
```

Нужно понять:

```text
1. Какие точные параметры Momentum сценария дали лучший результат.
2. Какие точные параметры VWAP Reversion сценария дали лучший результат.
3. Какие поля нужны будущему paper engine.
4. Какие artifacts naming использовать после SiU6 rollover.
5. Какие риски исполнения есть у каждой стратегии.
```

---

# Candidate 1 — Momentum Continuation

## Исходный research scenario

```text
strategy: momentum_continuation
scenario: MC_atr2.0_vol2.0_r2.0
direction: exact from R2 implementation
ATR multiplier: 2.0
volume multiplier: 2.0
take_r: 2.0
close near extreme: exact from R2 implementation
entry mode: exact from R2 implementation
stop mode: exact from R2 implementation
time_exit: exact from R2 implementation
no overnight: true
```

Важно:

```text
Не выдумывать параметры.
Взять точные значения из R2 config/code/report.
Если в отчёте не хватает деталей — извлечь из config/code.
```

## Что нужно подготовить

Создать:

```text
docs/paper_candidates/momentum_continuation_mc_atr2_vol2_r2.md
configs/paper/momentum_continuation_siu6_paper_example.yaml
deploy/systemd/hammertrade-paper-momentum.example.service
```

Если `configs/paper/` ещё нет — создать.

## Spec content

Документ должен включать:

```markdown
# Paper Candidate — Momentum Continuation MC_atr2.0_vol2.0_r2.0

## Why this candidate

## Research result summary

## Exact signal logic

## Entry logic

## Stop logic

## Take / exit logic

## Time/session rules

## Regime dependency

## Slippage sensitivity

## Robustness / concentration

## Expected trade frequency

## Paper artifact names

## Liveness / monitoring

## Stop conditions

## Risks

## Why not live/sandbox yet

## Launch checklist after rollover
```

## Momentum paper artifacts after SiU6 rollover

Prepare names:

```text
DB:
  data/paper/paper_state_siu6_momentum.sqlite

Status:
  runtime/paper_status_SiU6_MOMENTUM.json

CSV:
  out/paper/paper_trades_SiU6_MOMENTUM.csv

Log:
  logs/paper_SiU6_MOMENTUM.log

Experiment name:
  momentum_mc_atr2_vol2_r2
```

## Momentum readiness decision

Expected preliminary decision:

```text
Momentum is first candidate to launch after rollover,
because:
  - strongest OOS PF;
  - survives slippage better than VWAP;
  - aligns with high-vol/news-like regime;
  - execution is less fragile than VWAP reversion.
```

But include caveats:

```text
- only 20 OOS trades;
- concentration top-3 trades 79% of profit;
- January was weak/negative;
- needs paper validation.
```

---

# Candidate 2 — VWAP Reversion

## Исходный research scenario

```text
strategy: vwap_reversion
scenario: VR_d1.0_s1.0_1.5R
distance_to_vwap: 1.0 ATR
stop: 1.0 ATR
take: 1.5R or exact implementation
direction: exact from R2 implementation
session VWAP: anchored session VWAP
```

Важно:

```text
Взять точные параметры из R2 config/code/report.
Не выдумывать.
```

## Что нужно подготовить

Создать:

```text
docs/paper_candidates/vwap_reversion_vr_d1_s1_1_5r.md
configs/paper/vwap_reversion_siu6_paper_example.yaml
deploy/systemd/hammertrade-paper-vwap-reversion.example.service
```

## Spec content

Документ должен включать:

```markdown
# Paper Candidate — VWAP Reversion VR_d1.0_s1.0_1.5R

## Why this candidate

## Research result summary

## Exact signal logic

## Anchored VWAP calculation

## Entry logic

## Stop logic

## Take / exit logic

## Time/session rules

## Regime dependency

## Slippage sensitivity

## Execution risk

## Market order vs limit order model

## Fill / missed-fill risk

## Expected trade frequency

## Paper artifact names

## Liveness / monitoring

## Stop conditions

## Risks

## Why not live/sandbox yet

## Launch checklist after rollover
```

## VWAP paper artifacts after SiU6 rollover

Prepare names:

```text
DB:
  data/paper/paper_state_siu6_vwap_reversion.sqlite

Status:
  runtime/paper_status_SiU6_VWAP_REVERSION.json

CSV:
  out/paper/paper_trades_SiU6_VWAP_REVERSION.csv

Log:
  logs/paper_SiU6_VWAP_REVERSION.log

Experiment name:
  vwap_reversion_vr_d1_s1_1_5r
```

## VWAP execution-risk analysis

This is critical.

R2 showed:

```text
VWAP Reversion:
  PF_train: 1.294
  Trades_train: 180
  PF_OOS: 1.475
  Trades_OOS: 55
  But at 2pt slippage PF drops to around 1.08.
```

Therefore document:

```text
1. VWAP Reversion is execution-sensitive.
2. Market orders may destroy edge.
3. Live/sandbox requires limit-order or realistic fill model.
4. Paper market-fill PnL may be too optimistic or too pessimistic depending assumptions.
5. Need to track:
   - theoretical signal price;
   - simulated market fill;
   - simulated limit fill;
   - missed fill;
   - spread at signal if available;
   - slippage sensitivity.
```

## VWAP paper recommendation

Expected preliminary decision:

```text
VWAP Reversion should NOT be the first new paper service unless paper engine can model limit fills.
It is a strong research candidate but execution fragile.
```

Possible approach:

```text
Paper mode with dual accounting:
  theoretical_pnl
  market_fill_pnl
  conservative_slippage_pnl
  limit_fill_sim_pnl
```

Do not implement full engine in this MVP unless trivial. Document as requirement.

---

# Paper readiness comparison memo

Create:

```text
docs/paper_candidates/next_paper_candidates_decision.md
```

Content:

```markdown
# Next Paper Candidates Decision

## Current running paper services

## Candidate comparison

| Candidate | OOS PF | OOS trades | Slippage robustness | Concentration | Execution complexity | Recommended priority |
|---|---:|---:|---|---|---|---|

## Momentum Continuation

## VWAP Reversion

## Recommendation

## Launch order after rollover

## What to prepare before launch

## What not to launch yet
```

Expected launch order:

```text
1. Momentum Continuation — first after SiU6 rollover.
2. VWAP Reversion — second, only after limit/dual-fill paper model is designed.
```

---

# Config examples

Add config examples.

Important:

```text
Do not leave placeholders.
Use exact values from R2 code/config/report.
If value cannot be resolved, fail loudly in final report instead of writing fake config.
```

Create:

```text
configs/paper/momentum_continuation_siu6_paper_example.yaml
configs/paper/vwap_reversion_siu6_paper_example.yaml
```

---

# Systemd examples

Create examples only, do not install.

```text
deploy/systemd/hammertrade-paper-momentum.example.service
deploy/systemd/hammertrade-paper-vwap-reversion.example.service
```

If actual run scripts do not exist yet, write examples as future templates and clearly mark:

```text
# Example only. Do not install until paper engine is implemented.
```

Do not create broken service files that imply readiness if runner does not exist.

---

# Optional read-only helper

If useful, add:

```text
scripts/list_paper_candidates.py
```

It should print:

```text
candidate name
decision
priority
spec path
recommended launch timing
```

No side effects.

---

# Current service safety check

At end, verify:

```bash
sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
sudo systemctl status hammertrade-paper-orb --no-pager
.venv/bin/python scripts/check_all_paper_status.py
```

Expected:

```text
hammer-baseline: active OK
hammer-maxhold5: active OK
orb-paper: active OK
```

---

# Tests

This is mostly docs/config MVP, but still run relevant tests:

```bash
.venv/bin/python -m pytest
```

If full test suite is too slow, run at least:

```bash
.venv/bin/python -m pytest \
  tests/test_momentum_continuation.py \
  tests/test_vwap_reversion.py \
  tests/test_multistrategy_r2_runner.py \
  tests/test_candidate_decision.py
```

If config validation utilities exist, validate new YAML examples.

---

# Acceptance Criteria

MVP-R2a is done if:

1. Momentum paper candidate spec exists.
2. VWAP Reversion paper candidate spec exists.
3. Next paper candidates decision memo exists.
4. Momentum SiU6 paper config example exists.
5. VWAP SiU6 paper config example exists.
6. Momentum systemd example exists or explicitly deferred if runner not ready.
7. VWAP systemd example exists or explicitly deferred if runner not ready.
8. VWAP execution-risk analysis is explicit.
9. Momentum concentration/regime risk is explicit.
10. Launch order after rollover is explicit.
11. Current services are not changed.
12. Current service status checked.
13. Tests or smoke checks run.
14. Claude final response includes:
    - files created;
    - recommended launch order;
    - why Momentum first;
    - why VWAP second;
    - what is not ready;
    - service status.

---

# What NOT to do

Do not start Momentum service.

Do not start VWAP service.

Do not install systemd units.

Do not implement full paper engines unless already trivial and safe.

Do not perform rollover.

Do not change existing services.

Do not start sandbox.

Do not start real trading.

Do not leave placeholders in configs.

Do not claim profitability.

---

# Финальный формат ответа Claude Code

```markdown
## MVP-R2a Momentum + VWAP Paper Candidate Specs — готово

### Что сделано

### Созданные файлы

### Изменённые файлы

### Momentum candidate

### VWAP Reversion candidate

### Execution risk

### Recommended launch order

### Config examples

### Systemd examples

### What is NOT ready

### Current service status

### Tests / smoke checks

### Артефакты

### Рекомендация
```
