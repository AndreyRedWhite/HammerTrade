# Claude Code Prompt — MVP-R1b: ORB Parallel Paper Experiment

## Контекст проекта

Проект: `HammerTrade / MOEXF`.

Это исследовательская платформа для trading strategies на MOEX futures через T-Bank Invest API.

Текущий сервер:

```text
Server: 158.160.204.201
User: vorontsov
Project path: /opt/hammertrade
Virtualenv: /opt/hammertrade/.venv
```

Сейчас уже работают два paper-сервиса hammer-ветки:

```text
1. hammer-baseline
   systemd: hammertrade-paper.service
   ticker: SiM6
   direction: SELL
   max_hold_bars: None
   db: data/paper/paper_state.sqlite
   status: runtime/paper_status_SiM6_SELL.json
   csv: out/paper/paper_trades_SiM6_SELL.csv
   log: logs/paper_SiM6_SELL.log

2. hammer-maxhold5
   systemd: hammertrade-paper-maxhold5.service
   ticker: SiM6
   direction: SELL
   max_hold_bars: 5
   db: data/paper/paper_state_maxhold5.sqlite
   status: runtime/paper_status_SiM6_SELL_maxhold5.json
   csv: out/paper/paper_trades_SiM6_SELL_maxhold5.csv
   log: logs/paper_SiM6_SELL_maxhold5.log
```

Нужно добавить третий независимый paper-сервис:

```text
3. orb-paper
   strategy: opening_range_breakout
   ticker: SiM6 initially
   mode: paper only
   orders: disabled
```

Важно:

```text
ORB paper НЕ заменяет hammer.
ORB paper запускается параллельно как третий наблюдательный эксперимент.
```

---

## Что уже сделано

## Hammer live/paper

По последним данным:

```text
Hammer baseline:
  86 trades
  PF 1.01
  Net +55.70 RUB

Hammer maxhold5:
  57 trades
  PF 1.19
  Net +867.15 RUB
```

Решение:

```text
Hammer maxhold5 = OBSERVE_ONLY.
Продолжает работать, но не считается готовым к sandbox/live.
```

## Trading Liveness Guard

Уже реализовано:

```text
trading_liveness_status: OK / DEGRADED / STALLED
consecutive_api_errors
total_api_errors
last_successful_fetch_at
market_open_since grace period
check_paper_status.py exit codes
paper_error_report.py liveness summary
```

Это нужно переиспользовать для ORB paper.

## Strategy Research Lab

Уже реализованы:

```text
src/strategies/base.py
src/strategies/registry.py
src/strategies/opening_range_breakout/
src/research/
scripts/research_strategy.py
```

## ORB research MVP-R1

Train Jan–Apr:

```text
Best scenario:
  OR 10:00–11:00
  Direction: SHORT
  Take R: 2.0
  Trades: 41
  WR: 53.7%
  Net: +36 728 RUB
  PF: 1.639
```

## ORB MVP-R1a Walk-forward + May OOS

May OOS for top train scenario:

```text
Scenario: OR 10:00–11:00 SHORT 2R
Trades: 13
WR: 69.2%
Net: +11 159 RUB
PF: 1.683
```

Slippage sensitivity:

```text
0 pt:  PF 1.683, +11 159
2 pt:  PF 1.645, +10 639
5 pt:  PF 1.589, +9 859
10 pt: PF 1.500, +8 559
```

Candidate decision:

```text
NEEDS_MORE_DATA
```

Reason:

```text
- only 13 OOS trades in May;
- high concentration: top-3 trades = 144% of net;
- best day = 53.6% of net;
- regime/parameter shift noticed.
```

Interpretation:

```text
ORB is not ready for sandbox/live,
but it is ready for a controlled paper experiment.
```

---

## Rollover context

Документ готов:

```text
docs/rollover_siu6_plan.md
```

Important:

```text
SiM6 expiration_date: 2026-06-19
SiU6 expiration_date: 2026-09-18
SiU6 technically available but currently less liquid.
Start monitoring SiU6 liquidity from 2026-06-02.
Target/last switch date: around 2026-06-10.
```

For this MVP:

```text
Start ORB paper on current ticker SiM6 only if safe and useful.
But design paths/configs so rollover to SiU6 is straightforward.
After rollover, ORB paper should be restartable on SiU6 with separate artifacts.
```

---

# Главная цель MVP-R1b

Добавить и запустить третий независимый paper-сервис:

```text
hammer-baseline
hammer-maxhold5
orb-paper
```

Все три должны работать параллельно и генерировать данные.

ORB paper должен:

```text
1. Читать live 1m candles через T-Bank API.
2. Каждый день рассчитывать opening range 10:00–11:00 MSK.
3. После окончания OR искать breakout.
4. Открывать paper trade.
5. Закрывать paper trade по stop/take/time_exit.
6. Писать отдельную SQLite DB, status JSON, CSV trades и log.
7. Иметь liveness guard.
8. Быть видимым в multi-service status/report.
9. Не отправлять real/sandbox orders.
```

---

# Жёсткие ограничения

Строго запрещено:

- менять `hammertrade-paper.service`;
- менять `hammertrade-paper-maxhold5.service`;
- менять текущие hammer DB/status/csv/log;
- сбрасывать hammer state;
- менять HammerDetector;
- менять hammer strategy logic;
- менять hammer `max_hold_bars`;
- менять `.env`;
- печатать токены;
- запускать real trading;
- запускать sandbox orders;
- отправлять заявки;
- смешивать ORB trades с hammer trades;
- писать ORB в существующие hammer DB;
- запускать ORB без отдельного status file;
- удалять старые reports/logs;
- делать вывод “ORB доказал прибыльность”.

Разрешено:

- добавить ORB paper engine;
- добавить отдельный ORB paper DB;
- добавить отдельный ORB status JSON;
- добавить отдельный ORB CSV;
- добавить отдельный ORB log;
- добавить systemd unit example и реальный unit для paper ORB;
- стартовать ORB paper service, если tests/smoke checks passed;
- расширить monitoring/report scripts на несколько сервисов;
- добавить tests/docs.

---

# ORB paper strategy spec

## Initial paper profile

Use conservative initial profile based on research:

```text
strategy: opening_range_breakout
ticker: SiM6
class_code: SPBFUT
timeframe: 1m
timezone: Europe/Moscow

opening_range: 10:00–11:00 MSK
direction: SHORT
take_r: 2.0
stop_mode: opposite_range
entry_mode: breakout_level or breakout_candle_close
time_exit: 18:40 MSK
max_trades_per_day: 1
no_overnight: true
avoid_clearing: true
orders_enabled: false
```

Important:

```text
If existing ORB research used breakout_level vs breakout_candle_close, use the exact same mode that produced reported results.
Do not silently change entry semantics.
If uncertain, inspect MVP-R1 implementation and document chosen mode.
```

## Optional future profiles

Do NOT enable now unless trivial as config-only:

```text
OR-60 LONG 2R
OR-60 BOTH 2R
OR-30 LONG 2R
```

For MVP-R1b, start with one profile:

```text
or_60_short_2r
```

Reason:

```text
This was the best train scenario and survived May OOS.
```

---

# ORB paper state machine

Implement a paper engine that works daily.

Possible states:

```text
WAITING_FOR_OR_START
BUILDING_OPENING_RANGE
WAITING_FOR_BREAKOUT
IN_TRADE
DONE_FOR_DAY
MARKET_CLOSED
ERROR / DEGRADED via liveness
```

## Daily flow

### Before 10:00 MSK

```text
No opening range yet.
State: WAITING_FOR_OR_START
```

### 10:00–11:00 MSK

Collect OR candles:

```text
OR high = max high between 10:00 and 11:00
OR low = min low between 10:00 and 11:00
OR start/end timestamps recorded
```

State:

```text
BUILDING_OPENING_RANGE
```

### After 11:00 MSK

If no trade today:

For SHORT:

```text
breakout condition:
  price breaks below OR low
```

Entry:

```text
entry_price = OR low
or breakout candle close
```

Use same semantics as research.

Stop:

```text
stop_price = OR high
```

Take:

```text
risk_points = stop_price - entry_price
take_price = entry_price - take_r * risk_points
```

For initial profile:

```text
direction = SHORT
take_r = 2.0
```

### Trade management

Exit priority:

```text
STOP > TAKE > TIME_EXIT
```

For SHORT:

```text
STOP if candle.high >= stop_price
TAKE if candle.low <= take_price
TIME_EXIT if current time >= 18:40 MSK
```

No overnight:

```text
If still open near end of allowed session, close by TIME_EXIT.
```

### One trade per day

```text
After one closed trade or one skipped day, state DONE_FOR_DAY.
```

If no breakout by time_exit:

```text
No trade for that day.
State DONE_FOR_DAY.
```

---

# Data / candle handling

Reuse existing candle fetch code from paper trader if possible.

Important:

```text
Do not duplicate T-Bank API logic excessively if existing code can be reused safely.
But do not modify hammer logic in risky ways.
```

Need to handle:

```text
MARKET_CLOSED
EMPTY_CANDLES_RESPONSE
STALE_CANDLES
API_ERROR
```

Use same liveness guard patterns.

---

# Storage

Create separate DB for ORB:

```text
data/paper/paper_state_orb.sqlite
```

Suggested tables:

```text
orb_daily_state
orb_paper_trades
orb_events
```

Or reuse generic paper repository if it supports arbitrary strategy names.

Important:

```text
Do not write ORB trades into hammer paper_state.sqlite.
```

Minimum stored trade fields:

```text
trade_id
strategy_name
experiment_name
ticker
direction
entry_timestamp
entry_price
or_start
or_end
or_high
or_low
stop_price
take_price
exit_timestamp
exit_price
exit_reason
pnl_points
pnl_rub
bars_held
status
metadata_json
created_at
updated_at
```

Daily state fields:

```text
date_msk
state
or_high
or_low
or_candles_count
trade_opened
trade_closed
done_for_day
last_processed_candle_ts
metadata_json
```

---

# Artifacts

Use separate names:

```text
DB:
  data/paper/paper_state_orb.sqlite

Status:
  runtime/paper_status_SiM6_ORB.json

CSV:
  out/paper/paper_trades_SiM6_ORB.csv

Log:
  logs/paper_SiM6_ORB.log

Report:
  reports/paper_diagnostics_SiM6_ORB_latest.md
```

If using experiment name:

```text
experiment_name: orb_or60_short2r
```

Then:

```text
runtime/paper_status_SiM6_ORB_or60_short2r.json
out/paper/paper_trades_SiM6_ORB_or60_short2r.csv
logs/paper_SiM6_ORB_or60_short2r.log
```

Choose a consistent convention and document it.

---

# Status JSON

ORB status should include:

```json
{
  "strategy": "opening_range_breakout",
  "experiment_name": "orb_or60_short2r",
  "ticker": "SiM6",
  "class_code": "SPBFUT",
  "timeframe": "1m",
  "direction": "SHORT",
  "opening_range": ["10:00", "11:00"],
  "take_r": 2.0,
  "orders_enabled": false,
  "paper_only": true,

  "market_status": "...",
  "trading_liveness_status": "OK",
  "trading_liveness_reason": null,

  "day_state": "WAITING_FOR_BREAKOUT",
  "date_msk": "2026-05-30",
  "or_high": null,
  "or_low": null,
  "or_candles_count": 0,
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

---

# Systemd

Create:

```text
deploy/systemd/hammertrade-paper-orb.example.service
```

And install actual service if smoke checks pass:

```text
hammertrade-paper-orb.service
```

Service should run under:

```text
User=vorontsov
WorkingDirectory=/opt/hammertrade
```

Command example:

```text
/opt/hammertrade/.venv/bin/python scripts/run_orb_paper_trader.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --timeframe 1m \
  --direction SHORT \
  --opening-range-start 10:00 \
  --opening-range-end 11:00 \
  --take-r 2.0 \
  --state-db data/paper/paper_state_orb.sqlite \
  --status-file runtime/paper_status_SiM6_ORB.json \
  --csv-output out/paper/paper_trades_SiM6_ORB.csv \
  --log-file logs/paper_SiM6_ORB.log \
  --experiment-name orb_or60_short2r \
  --orders-enabled false
```

Make sure:

```text
orders_enabled default is false.
There is no code path that sends real/sandbox orders in MVP-R1b.
```

---

# CLI scripts

Create:

```text
scripts/run_orb_paper_trader.py
scripts/orb_paper_diagnostics.py
```

Optionally:

```text
scripts/compare_all_paper_experiments.py
scripts/check_all_paper_status.py
```

## run_orb_paper_trader.py

Must support:

```text
--ticker
--class-code
--timeframe
--direction
--opening-range-start
--opening-range-end
--take-r
--state-db
--status-file
--csv-output
--log-file
--experiment-name
--orders-enabled false
```

## orb_paper_diagnostics.py

Should read ORB DB/CSV and produce:

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
state breakdown if useful
```

Outputs:

```text
reports/orb_paper_diagnostics_SiM6_latest.md
out/paper/orb_paper_trades_diagnostics_SiM6_latest.csv
```

## check_all_paper_status.py

Preferred:

```bash
python scripts/check_all_paper_status.py
```

Should show:

```text
hammer-baseline: OK / DEGRADED / STALLED
hammer-maxhold5: OK / DEGRADED / STALLED
orb-paper: OK / DEGRADED / STALLED
```

This can be a small wrapper around existing `check_paper_status.py`.

## compare_all_paper_experiments.py

Initial version can be simple:

```text
strategy
experiment
ticker
period
trades
net
PF
winrate
maxDD
liveness
```

It should not try to force apples-to-apples comparison if periods differ.

---

# Multi-service monitoring

Extend or add scripts so that daily manual check is easy:

```bash
python scripts/check_all_paper_status.py
python scripts/paper_error_report.py
python scripts/compare_all_paper_experiments.py
```

`paper_error_report.py` should include ORB if status file exists.

If modifying existing script is risky, add separate script:

```text
scripts/paper_error_report_all.py
```

---

# Rollover compatibility

ORB should be easy to roll over to SiU6.

Do NOT execute rollover in this MVP.

But prepare names for future:

```text
data/paper/paper_state_siu6_orb.sqlite
runtime/paper_status_SiU6_ORB.json
out/paper/paper_trades_SiU6_ORB.csv
logs/paper_SiU6_ORB.log
```

Add this to docs.

---

# Documentation

Create:

```text
docs/orb_paper_experiment.md
```

Include:

```markdown
# ORB Paper Experiment

## Purpose

## Why ORB

## Current selected profile

## Difference from hammer paper services

## State machine

## Entry logic

## Stop/take/time exit

## Storage files

## Status fields

## How to start/stop

## How to check status

## How to run diagnostics

## Rollover notes

## Limitations

## Stop conditions
```

Stop conditions for ORB paper:

```text
Observe until:
  at least 30 paper trades after stable launch
  and preferably through SiU6 rollover period

Reject/freeze if:
  PF < 1.1 after >=30 trades
  or liveness unstable
  or result depends on one day only

Continue research if:
  PF > 1.25 after >=30 trades
  and slippage assumptions still reasonable
  and drawdown acceptable
```

Important:

```text
No sandbox/live decision before at least 30–60 paper trades.
```

---

# Tests

Add tests:

```text
tests/test_orb_paper_engine.py
tests/test_orb_paper_repository.py
tests/test_orb_paper_status.py
tests/test_orb_paper_cli.py
```

Minimum:

## Engine

```text
1. State WAITING_FOR_OR_START before 10:00.
2. State BUILDING_OPENING_RANGE during 10:00–11:00.
3. OR high/low updated correctly.
4. No breakout before OR end.
5. SHORT breakout opens trade after OR low break.
6. Stop/take prices calculated correctly.
7. TAKE closes short when candle.low <= take.
8. STOP closes short when candle.high >= stop.
9. STOP priority over TAKE if both touched.
10. TIME_EXIT closes open trade at 18:40.
11. max_trades_per_day=1 enforced.
12. No overnight trade.
```

## Repository

```text
1. DB init creates tables.
2. Daily state saved/loaded.
3. Trade saved/loaded.
4. CSV export works.
5. Existing DB migration/backward-compatible if needed.
```

## Status

```text
1. Status includes strategy fields.
2. Liveness OK when fetch recent.
3. Liveness STALLED when no fetch during open market.
4. Open/closed trade counters correct.
```

## CLI

```text
1. CLI parses required args.
2. orders_enabled defaults false.
3. Invalid direction rejected.
```

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_orb_paper_engine.py \
  tests/test_orb_paper_repository.py \
  tests/test_orb_paper_status.py \
  tests/test_orb_paper_cli.py
```

If feasible:

```bash
.venv/bin/python -m pytest
```

Do not break existing 513 tests.

---

# Safe rollout plan

Do not install/start service until tests pass.

## 1. Tests

```bash
cd /opt/hammertrade
source .venv/bin/activate
python -m pytest tests/test_orb_paper_engine.py tests/test_orb_paper_repository.py tests/test_orb_paper_status.py tests/test_orb_paper_cli.py
python -m pytest
```

## 2. One-shot smoke run

Run ORB trader for short smoke if script supports `--once` or `--max-cycles`.

Preferred:

```bash
.venv/bin/python scripts/run_orb_paper_trader.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --timeframe 1m \
  --direction SHORT \
  --opening-range-start 10:00 \
  --opening-range-end 11:00 \
  --take-r 2.0 \
  --state-db data/paper/paper_state_orb.sqlite \
  --status-file runtime/paper_status_SiM6_ORB.json \
  --csv-output out/paper/paper_trades_SiM6_ORB.csv \
  --log-file logs/paper_SiM6_ORB.log \
  --experiment-name orb_or60_short2r \
  --orders-enabled false \
  --once
```

If `--once` not practical, implement safe `--once`.

## 3. Install service

Only after smoke OK:

```bash
sudo cp deploy/systemd/hammertrade-paper-orb.example.service /etc/systemd/system/hammertrade-paper-orb.service
sudo systemctl daemon-reload
sudo systemctl enable hammertrade-paper-orb.service
sudo systemctl start hammertrade-paper-orb.service
```

## 4. Verify all services

```bash
sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
sudo systemctl status hammertrade-paper-orb --no-pager

.venv/bin/python scripts/check_all_paper_status.py
.venv/bin/python scripts/paper_error_report.py
.venv/bin/python scripts/compare_all_paper_experiments.py
```

Expected:

```text
hammer-baseline: active, OK
hammer-maxhold5: active, OK
orb-paper: active, OK or MARKET_CLOSED depending session
```

---

# Acceptance Criteria

MVP-R1b is ready if:

1. ORB paper engine exists.
2. ORB paper repository/storage exists.
3. ORB status JSON exists.
4. ORB CSV/log paths are separate.
5. ORB liveness works.
6. ORB does not send orders.
7. ORB has separate systemd unit.
8. ORB service starts successfully.
9. Hammer baseline still works.
10. Hammer maxhold5 still works.
11. All three services can be checked together.
12. ORB diagnostics can be generated.
13. ORB docs exist.
14. Tests pass.
15. No secrets printed.
16. No existing state reset.
17. Claude final response includes:
    - files created/changed;
    - ORB config/profile;
    - service status;
    - status file path;
    - DB path;
    - CSV path;
    - log path;
    - how to check all services;
    - what was NOT changed.

---

# What NOT to do

Do not start sandbox.

Do not start real trading.

Do not add order execution.

Do not auto-switch strategies.

Do not implement ORB long/both live in this MVP.

Do not replace hammer.

Do not stop hammer services.

Do not perform rollover.

Do not optimize ORB further after seeing live first signals.

Do not add new filters.

---

# Финальный формат ответа Claude Code

```markdown
## MVP-R1b ORB Parallel Paper Experiment — готово

### Что сделано

### Созданные файлы

### Изменённые файлы

### ORB paper profile

### ORB state machine

### Storage / artifacts

### Systemd service

### How to run/check

### Diagnostics

### Multi-service status

### Service status

### Tests / smoke checks

### Что НЕ было изменено

### Warnings / limitations

### Рекомендация
```
