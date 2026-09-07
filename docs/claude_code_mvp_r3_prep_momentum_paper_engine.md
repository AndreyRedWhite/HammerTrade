# Claude Code Prompt — MVP-R3 Prep: Momentum Paper Engine Implementation, Do Not Start Service

## Контекст проекта

Проект: `HammerTrade / MOEXF`.

Это исследовательская multi-strategy платформа для торговых стратегий на MOEX futures через T-Bank Invest API.

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
Текущие 3 сервиса НЕ менять.
Новые сервисы НЕ запускать.
Systemd unit НЕ устанавливать.
Sandbox/real orders НЕ запускать.
```

---

## Текущее состояние проекта

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

Оставшаяся проблема:

```text
ONE_BAR_STOP:
  10 сделок
  WR 0%
  около -1 710 RUB
  max_hold не помогает, потому что стоп срабатывает до 5-го бара.
```

## ORB paper

ORB запущен как третий paper service.

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

## MVP-R2 Multi-Strategy Research Pack

Momentum Continuation оказался главным новым кандидатом:

```text
Momentum MC_atr2.0_vol2.0_r2.0:
  PF_train: 1.519
  Trades_train: 60
  PF_OOS: 2.883
  Trades_OOS: 20
  Decision: NEEDS_MORE_DATA
```

Плюсы:

```text
- лучший OOS PF среди новых стратегий;
- slippage не убивает стратегию;
- логика подходит под high-vol/news-like режим;
- исполнение проще, чем у VWAP Reversion.
```

Риски:

```text
- всего 20 OOS trades;
- top-3 trades = около 79% прибыли;
- январь был слабым/убыточным;
- нужна live paper валидация.
```

## MVP-R2a Candidate Specs

Уже подготовлены:

```text
docs/paper_candidates/momentum_continuation_mc_atr2_vol2_r2.md
docs/paper_candidates/vwap_reversion_vr_d1_s1_1_5r.md
docs/paper_candidates/next_paper_candidates_decision.md
configs/paper/momentum_continuation_siu6_paper_example.yaml
configs/paper/vwap_reversion_siu6_paper_example.yaml
deploy/systemd/hammertrade-paper-momentum.example.service
deploy/systemd/hammertrade-paper-vwap-reversion.example.service
scripts/list_paper_candidates.py
```

Решение:

```text
Momentum Continuation — первый кандидат для запуска после rollover.
VWAP Reversion — второй, но только после dual-fill/limit-fill accounting.
```

---

## Rollover context

Документ:

```text
docs/rollover_siu6_plan.md
```

Важные данные:

```text
SiM6 expiration_date: 2026-06-19
SiU6 expiration_date: 2026-09-18
Плановая подготовка rollover: около 2026-06-10
SiU6 liquidity monitoring идёт
Последнее значение: около 250 лот/бар
Целевой порог: около 500 лот/бар
```

Для этого MVP:

```text
НЕ выполнять rollover.
Но Momentum paper engine должен быть готов к запуску на SiU6 после rollover.
```

---

# Главная цель MVP-R3 Prep

Реализовать Momentum paper engine и всю инфраструктуру для будущего запуска, но НЕ запускать сервис.

Нужно:

```text
1. Реализовать paper engine для Momentum Continuation.
2. Реализовать CLI `scripts/run_momentum_paper_trader.py`.
3. Реализовать отдельное хранилище/репозиторий или переиспользовать generic paper storage.
4. Реализовать status JSON с liveness.
5. Реализовать CSV/log output.
6. Реализовать diagnostics script.
7. Подготовить systemd example, но НЕ устанавливать.
8. Подготовить SiU6-ready config.
9. Добавить tests.
10. Провести safe smoke run в режиме `--once` или `--dry-run`, без запуска постоянного сервиса.
```

---

# Жёсткие ограничения

Строго запрещено:

- менять `hammertrade-paper.service`;
- менять `hammertrade-paper-maxhold5.service`;
- менять `hammertrade-paper-orb.service`;
- менять текущие systemd unit files;
- останавливать текущие сервисы без необходимости;
- менять текущие paper DB/status/csv/log;
- сбрасывать state;
- менять HammerDetector;
- менять hammer strategy logic;
- менять ORB paper strategy params;
- устанавливать `hammertrade-paper-momentum.service`;
- запускать постоянный Momentum service;
- выполнять `systemctl enable/start` для momentum;
- запускать sandbox orders;
- запускать real orders;
- выполнять rollover;
- менять `.env`;
- печатать токены;
- удалять SQLite/CSV/reports/logs;
- обещать прибыль;
- делать вывод “Momentum доказан”.

Разрешено:

- реализовать Momentum paper engine;
- реализовать CLI;
- создать отдельную DB для smoke/dry-run;
- создать status/CSV/log для smoke/dry-run;
- создать diagnostics;
- создать systemd example;
- создать docs;
- добавить tests;
- выполнить one-shot smoke/dry-run;
- проверить current service status.

---

# Что изучить перед реализацией

Изучи:

```text
docs/paper_candidates/momentum_continuation_mc_atr2_vol2_r2.md
configs/paper/momentum_continuation_siu6_paper_example.yaml
deploy/systemd/hammertrade-paper-momentum.example.service

src/strategies/momentum_continuation/
src/strategies/base.py
src/strategies/registry.py

scripts/run_orb_paper_trader.py
src/strategies/opening_range_breakout/
data/paper/paper_state_orb.sqlite
runtime/paper_status_SiM6_ORB.json

src/paper/liveness.py
src/paper/status.py
scripts/check_all_paper_status.py
scripts/compare_all_paper_experiments.py
scripts/orb_paper_diagnostics.py
```

Нужно понять:

```text
1. Как ORB paper engine устроен.
2. Как реализована state machine ORB.
3. Как реализован liveness/status.
4. Как хранить trades в отдельной DB.
5. Как экспортировать CSV.
6. Как лучше переиспользовать существующую Strategy Research Lab.
7. Какие точные параметры Momentum scenario из R2.
```

---

# Momentum paper profile

Использовать точные параметры из R2 / R2a spec.

Known profile:

```text
strategy: momentum_continuation
scenario: MC_atr2.0_vol2.0_r2.0
ticker after launch: SiU6
initial implementation can support any ticker from CLI
class_code: SPBFUT
timeframe: 1m
timezone: Europe/Moscow
orders_enabled: false
```

Known research params:

```text
ATR multiplier: 2.0
Volume multiplier: 2.0
Take R: 2.0
Close near extreme: exact from implementation/spec
Entry mode: exact from implementation/spec
Stop mode: exact from implementation/spec
Time exit: exact from implementation/spec, likely 18:40
No overnight: true
Max trades per day: exact from implementation/spec
Direction: exact from implementation/spec
```

Important:

```text
Do not invent missing values.
Read exact values from:
  docs/paper_candidates/momentum_continuation_mc_atr2_vol2_r2.md
  configs/paper/momentum_continuation_siu6_paper_example.yaml
  src/strategies/momentum_continuation/
  configs/research/multistrategy_r2_sim6.yaml
```

If any value is ambiguous, fail loudly in final response and do not hide it.

---

# Momentum signal logic

Use existing `src/strategies/momentum_continuation/` logic.

Expected concept:

```text
Bearish/bullish impulse candle:
  candle range >= ATR * multiplier
  close near low/high
  volume >= rolling volume * multiplier
```

For SHORT:

```text
large bearish impulse
close near low
volume spike
entry according to R2 implementation
stop according to R2 implementation
take = take_r * risk
```

For LONG:

```text
large bullish impulse
close near high
volume spike
entry according to R2 implementation
stop according to R2 implementation
take = take_r * risk
```

If R2 candidate was only SHORT or only BOTH, use exact candidate behavior.

---

# Momentum paper state machine

Use simple state machine.

Possible states:

```text
WAITING_FOR_SIGNAL
IN_TRADE
DONE_FOR_DAY
MARKET_CLOSED
ERROR / DEGRADED via liveness
```

Daily reset:

```text
On new MSK trading date:
  reset daily trade count
  state WAITING_FOR_SIGNAL if market open
```

Signal scanning:

```text
During allowed session:
  fetch latest 1m candles
  compute ATR / rolling volume / impulse features
  if signal and no open trade and daily trades < max_trades_per_day:
    open paper trade
```

Trade management:

```text
Exit priority:
  STOP > TAKE > TIME_EXIT
```

No overnight:

```text
If open trade near time_exit/end of allowed session, close by TIME_EXIT.
```

Max trades:

```text
Enforce max_trades_per_day from candidate config.
```

---

# Storage

Use separate DB for Momentum.

For future real launch after rollover:

```text
data/paper/paper_state_siu6_momentum.sqlite
runtime/paper_status_SiU6_MOMENTUM.json
out/paper/paper_trades_SiU6_MOMENTUM.csv
logs/paper_SiU6_MOMENTUM.log
```

For this MVP smoke/dry-run, use safe separate test/smoke paths if needed:

```text
data/paper/paper_state_momentum_smoke.sqlite
runtime/paper_status_MOMENTUM_SMOKE.json
out/paper/paper_trades_MOMENTUM_SMOKE.csv
logs/paper_MOMENTUM_SMOKE.log
```

Do not overwrite future/production paths unless explicitly safe.

Suggested tables:

```text
momentum_daily_state
momentum_paper_trades
momentum_events
```

Minimum trade fields:

```text
trade_id
strategy_name
experiment_name
ticker
direction
signal_timestamp
entry_timestamp
entry_price
stop_price
take_price
exit_timestamp
exit_price
exit_reason
pnl_points
pnl_rub
bars_held
status
atr_value
volume_value
volume_avg
candle_range
close_position
metadata_json
created_at
updated_at
```

---

# Status JSON

Momentum status should include:

```json
{
  "strategy": "momentum_continuation",
  "experiment_name": "momentum_mc_atr2_vol2_r2",
  "ticker": "SiU6",
  "class_code": "SPBFUT",
  "timeframe": "1m",
  "orders_enabled": false,
  "paper_only": true,

  "signal_params": {
    "atr_multiplier": 2.0,
    "volume_multiplier": 2.0,
    "take_r": 2.0
  },

  "market_status": "...",
  "trading_liveness_status": "OK",
  "trading_liveness_reason": null,

  "day_state": "WAITING_FOR_SIGNAL",
  "date_msk": "2026-06-10",
  "open_trades": 0,
  "closed_trades_total": 0,
  "net_pnl_rub_total": 0.0,

  "last_successful_fetch_at": "...",
  "last_processed_candle_ts": "...",
  "last_signal_check_at": "...",
  "last_trade_event_at": "...",
  "consecutive_api_errors": 0,
  "total_api_errors": 0,
  "last_api_error_at": null,
  "last_api_error_message": null
}
```

Use actual values, not placeholders.

---

# CLI script

Create:

```text
scripts/run_momentum_paper_trader.py
```

Required args:

```text
--config
```

Preferred:

```bash
python scripts/run_momentum_paper_trader.py \
  --config configs/paper/momentum_continuation_siu6_paper_example.yaml
```

Also support:

```text
--once
--max-cycles
--dry-run
```

Required safety:

```text
orders_enabled must default to false.
If orders_enabled true, script must hard fail in this MVP.
No code path should send real/sandbox orders.
```

---

# Diagnostics

Create:

```text
scripts/momentum_paper_diagnostics.py
```

Should read Momentum DB/CSV and output:

```text
closed trades
open trades
net
PF
winrate
expectancy
best/worst
daily breakdown
exit reason breakdown
signal feature breakdown:
  ATR bucket
  volume spike bucket
  candle range bucket
  close position bucket
```

Outputs:

```text
reports/momentum_paper_diagnostics_latest.md
out/paper/momentum_paper_trades_diagnostics_latest.csv
```

If no trades yet:

```text
report should not crash
should say 0 closed trades
```

---

# Multi-service compatibility

Update `check_all_paper_status.py` to include Momentum only if status file exists.

Do not require Momentum status to exist before service launch.

Expected behavior:

```text
If runtime/paper_status_SiU6_MOMENTUM.json exists:
  include it
Else:
  skip with "not launched"
```

Update `compare_all_paper_experiments.py` similarly if safe.

If risky, create TODO/doc instead of modifying existing scripts.

---

# Systemd example

Update existing example if needed:

```text
deploy/systemd/hammertrade-paper-momentum.example.service
```

It should reference:

```text
scripts/run_momentum_paper_trader.py
configs/paper/momentum_continuation_siu6_paper_example.yaml
```

Clearly mark:

```text
Example only. Do not install before rollover and explicit approval.
```

Do not install.

Do not run:

```bash
sudo systemctl enable/start hammertrade-paper-momentum
```

---

# Documentation

Create:

```text
docs/momentum_paper_engine.md
```

Content:

```markdown
# Momentum Paper Engine

## Purpose

## Candidate source

## Exact parameters

## State machine

## Signal logic

## Entry logic

## Stop / take / time exit

## Storage

## Status fields

## Diagnostics

## How to run once

## How to launch after rollover

## Safety: paper only

## Known risks

## Stop conditions
```

Stop conditions:

```text
Initial paper validation after launch:
  minimum 30 closed trades
  preferably 60 closed trades

FREEZE if:
  PF < 1.1 after >=30 trades
  or liveness unstable
  or drawdown unacceptable

CONTINUE research if:
  PF > 1.25 after >=30 trades
  and result not concentrated in 1–2 days
```

---

# Tests

Add tests:

```text
tests/test_momentum_paper_engine.py
tests/test_momentum_paper_repository.py
tests/test_momentum_paper_status.py
tests/test_momentum_paper_cli.py
```

Minimum:

## Engine

```text
1. WAITING_FOR_SIGNAL when no signal.
2. Momentum signal opens trade.
3. No trade if ATR condition not met.
4. No trade if volume condition not met.
5. No trade if close-extreme condition not met.
6. Stop/take calculated exactly as research logic.
7. TAKE exit works.
8. STOP exit works.
9. STOP priority over TAKE if both touched in same candle.
10. TIME_EXIT closes open trade.
11. max_trades_per_day enforced.
12. No overnight.
```

## Repository

```text
1. DB init creates tables.
2. Daily state saved/loaded.
3. Trade saved/loaded.
4. CSV export works.
```

## Status

```text
1. Status includes strategy fields.
2. Liveness OK when fetch recent.
3. Liveness STALLED when no fetch during open market.
4. Open/closed counters correct.
```

## CLI

```text
1. Config loads.
2. orders_enabled defaults false.
3. orders_enabled true hard fails.
4. --once works.
5. --dry-run works.
```

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_momentum_paper_engine.py \
  tests/test_momentum_paper_repository.py \
  tests/test_momentum_paper_status.py \
  tests/test_momentum_paper_cli.py
```

If feasible:

```bash
.venv/bin/python -m pytest
```

Do not break existing tests.

---

# Smoke run

After tests pass, run one safe smoke:

```bash
cd /opt/hammertrade
source .venv/bin/activate

python scripts/run_momentum_paper_trader.py \
  --config configs/paper/momentum_continuation_siu6_paper_example.yaml \
  --dry-run \
  --once
```

If config uses SiU6 and market/data unavailable, either:

```text
1. Use --dry-run with no API side effects.
2. Or use temporary smoke config with SiM6 and smoke artifact paths.
```

Important:

```text
Do not start daemon.
Do not install unit.
Do not use production/future SiU6 DB if not needed.
```

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
momentum: not launched / no status yet
```

---

# Acceptance Criteria

MVP-R3 Prep is done if:

1. Momentum paper engine implemented.
2. Momentum CLI implemented.
3. Momentum repository/storage implemented.
4. Momentum status JSON builder implemented.
5. Momentum diagnostics implemented.
6. Momentum docs created.
7. Momentum systemd example updated/created.
8. Momentum config example valid.
9. orders_enabled true hard-fails.
10. Tests pass.
11. One-shot/dry-run smoke works.
12. Current three services remain active and unchanged.
13. Momentum service is NOT installed.
14. Momentum service is NOT started.
15. Claude final response includes:
    - files created/changed;
    - exact Momentum params;
    - how to run dry-run;
    - why service was not started;
    - current service status;
    - next step after rollover.

---

# What NOT to do

Do not start Momentum service.

Do not install systemd unit.

Do not perform rollover.

Do not start sandbox.

Do not start real trading.

Do not change current three services.

Do not change existing strategies.

Do not implement VWAP paper engine in this MVP.

Do not leave ambiguous parameters hidden.

Do not claim profitability.

---

# Финальный формат ответа Claude Code

```markdown
## MVP-R3 Prep Momentum Paper Engine — готово

### Что сделано

### Созданные файлы

### Изменённые файлы

### Exact Momentum params

### Momentum state machine

### Storage / artifacts

### CLI

### Diagnostics

### Safety: orders disabled

### Dry-run / smoke result

### Systemd example

### What was NOT started

### Current service status

### Tests

### Warnings / limitations

### Recommendation

### Next step after rollover
```
