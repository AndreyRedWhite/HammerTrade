# Claude Code Prompt — MVP-L1a: Sandbox Execution Architecture for Hammer MaxHold5

## Контекст

Проект: `HammerTrade / MOEXF`.

Сервер:

```text
Server: 158.160.204.201
User: vorontsov
Project path: /opt/hammertrade
Virtualenv: /opt/hammertrade/.venv
```

## Текущее состояние

Rollover уже выполнен:

```text
SiM6 → SiU6
```

Текущие paper-сервисы:

```text
1. hammer-baseline
   systemd: hammertrade-paper.service
   ticker: SiU6
   direction: SELL
   liveness: OK

2. hammer-maxhold5
   systemd: hammertrade-paper-maxhold5.service
   ticker: SiU6
   direction: SELL
   max_hold_bars: 5
   liveness: OK

3. orb-paper
   systemd: hammertrade-paper-orb.service
   ticker: SiU6
   direction: SHORT
   strategy: opening_range_breakout
   liveness: OK

4. momentum-paper
   prepared but not launched
```

First SiU6 validation:

```text
Decision: VALIDATION_OK_WITH_WARNINGS
All 3 active services are on SiU6.
No active SiM6 leakage.
Hammer already produced first SiU6 TAKE trades.
ORB builds OR on SiU6 correctly.
Momentum not launched.
```

---

# Цель MVP-L1a

Начать подготовку к sandbox execution для `hammer-maxhold5`.

Важно:

```text
Текущий hammer-maxhold5 paper service НЕ переводить в sandbox.
Он должен остаться как контрольный paper-сервис.

Нужно создать отдельный sandbox execution runner/service для hammer-maxhold5.
```

Архитектура после MVP-L1a должна быть:

```text
paper:
  hammer-baseline      SiU6 SELL
  hammer-maxhold5      SiU6 SELL
  orb-paper            SiU6 SHORT
  momentum-paper       not launched / later

sandbox:
  hammer-maxhold5      SiU6 SELL
  separate DB/status/log/CSV
  sandbox orders only
  no real orders
```

---

# Важное про токен

Пользователь предоставит новый T-Invest token отдельным сообщением / отдельной операцией.

В этом промпте токена нет.

Claude не должен просить вставлять токен в код или в git-tracked файлы.

Нужно подготовить безопасную схему:

```text
TINVEST_SANDBOX_TOKEN=<provided separately by user>
```

или, если проект уже использует другой нейминг, выбрать совместимое имя и явно объяснить.

Требования:

```text
1. Не логировать токен.
2. Не печатать токен.
3. Не сохранять токен в отчётах.
4. Не коммитить токен.
5. Не добавлять токен в docs/examples.
6. Проверить, что .env не tracked by git.
7. Добавить .env.example только с placeholder, если нужно.
8. Если токен отсутствует — sandbox runner должен hard fail с понятной ошибкой.
```

---

# Ключевой принцип безопасности

Этот MVP НЕ должен отправлять реальные заявки.

Разрешён только sandbox.

Live trading должен быть невозможен в рамках MVP-L1a.

Если в конфиге/CLI кто-то попытается включить live:

```text
mode=live
orders_mode=live
TINVEST_LIVE_TRADING_TOKEN
```

то приложение должно:

```text
hard fail before any API order call
```

---

# Жёсткие ограничения

Строго запрещено:

- запускать real orders;
- использовать live trading token;
- менять текущие paper service unit files;
- останавливать текущие paper-сервисы;
- менять стратегию hammer-maxhold5;
- менять hammer detector params;
- менять max_hold_bars=5;
- запускать Momentum;
- запускать ORB risk cap changes;
- смешивать paper DB и sandbox DB;
- писать sandbox trades в paper DB;
- писать paper trades в sandbox DB;
- удалять старые DB/CSV/logs;
- печатать токены;
- добавлять токены в git;
- делать systemctl enable/start нового sandbox service без отдельного подтверждения.

Разрешено:

- создать sandbox execution layer;
- создать sandbox runner CLI;
- создать отдельные DB/status/log/CSV;
- создать sandbox config;
- создать systemd example, но НЕ устанавливать;
- создать dry-run/smoke mode;
- использовать sandbox API методы;
- создать risk manager;
- создать order/fill journal;
- создать position reconciliation;
- создать kill switch;
- создать tests;
- создать docs/report.

---

# Целевой режим sandbox

Стратегия:

```text
strategy: hammer-maxhold5
ticker: SiU6
direction: SELL
max_hold_bars: 5
mode: sandbox
orders_enabled: true only for sandbox
real_orders_enabled: false always
```

Бюджет:

```text
capital_budget_rub: 40_000
```

Важно:

Для фьючерсов `40_000 RUB` — это не “купить на 40к”, а ориентир будущего micro-live капитала / risk budget.

Нужно не пытаться наивно конвертировать 40к в позицию как для spot.

Нужно реализовать параметры:

```text
capital_budget_rub = 40_000
max_position_notional_rub = 40_000
max_order_notional_rub = 40_000
max_daily_loss_rub = 2_000 или 3_000
max_total_loss_rub = 5_000 или 10_000
max_contracts = calculated or explicitly configured
max_open_positions_per_strategy = strategy-aware, default 1 for hammer-maxhold5
max_trades_per_day = 5
max_consecutive_errors = 3
max_consecutive_losses = 3
kill_switch_file = runtime/STOP_SANDBOX_TRADING
```

Если нужно выбрать конкретные значения для MVP, использовать:

```text
capital_budget_rub = 40_000
max_daily_loss_rub = 3_000
max_total_loss_rub = 10_000
max_trades_per_day = 5
max_consecutive_errors = 3
max_consecutive_losses = 3
max_open_positions_per_strategy = 1
```

`max_open_positions_per_strategy=1` — не потому что это финальный prod-лимит, а потому что текущая стратегия hammer-maxhold5 по своей логике не должна держать несколько одновременных позиций.

---

# Что нужно реализовать

## 1. Sandbox config

Создать:

```text
configs/sandbox/hammer_maxhold5_siu6.yaml
```

Примерные поля:

```yaml
mode: sandbox
strategy: hammer_maxhold5
ticker: SiU6
class_code: SPBFUT
direction: SELL
max_hold_bars: 5

orders:
  enabled: true
  environment: sandbox
  real_orders_enabled: false
  order_type: market_or_conservative_limit
  account_id_env: TINVEST_SANDBOX_ACCOUNT_ID
  token_env: TINVEST_SANDBOX_TOKEN

risk:
  capital_budget_rub: 40000
  max_daily_loss_rub: 3000
  max_total_loss_rub: 10000
  max_trades_per_day: 5
  max_consecutive_errors: 3
  max_consecutive_losses: 3
  max_open_positions_per_strategy: 1
  kill_switch_file: runtime/STOP_SANDBOX_TRADING

artifacts:
  db: data/sandbox/sandbox_state_hammer_maxhold5_siu6.sqlite
  status: runtime/sandbox_status_hammer_maxhold5_SiU6.json
  trades_csv: out/sandbox/sandbox_trades_hammer_maxhold5_SiU6.csv
  orders_csv: out/sandbox/sandbox_orders_hammer_maxhold5_SiU6.csv
  log: logs/sandbox_hammer_maxhold5_SiU6.log
```

If exact names differ, keep them consistent and document.

---

## 2. Sandbox account handling

Implement support for sandbox account.

Need to check existing project structure first.

Possible behavior:

```text
If TINVEST_SANDBOX_ACCOUNT_ID exists:
  use it.

If not:
  optionally create/open sandbox account via SandboxService if supported by current SDK,
  then print account_id and tell user to save it into .env.

Do not create multiple sandbox accounts silently.
```

Also provide command:

```bash
python scripts/sandbox_account_setup.py
```

This should:

```text
1. Verify TINVEST_SANDBOX_TOKEN exists.
2. Connect to sandbox.
3. List existing sandbox accounts.
4. If no account exists, optionally open one after explicit CLI flag:
   --create-if-missing
5. Print account_id only, not token.
6. Optionally top up sandbox account to 40_000 RUB if sandbox API supports it.
```

If sandbox API top-up requires exact method/currency handling, implement carefully with tests or provide TODO if SDK behavior unclear.

---

## 3. Sandbox runner

Create:

```text
scripts/run_hammer_maxhold5_sandbox.py
```

Required args:

```text
--config configs/sandbox/hammer_maxhold5_siu6.yaml
--dry-run
--once
--max-cycles
```

Safety:

```text
default mode should not send orders unless environment=sandbox and orders.enabled=true.
real/live mode hard fail.
missing token hard fail.
missing account_id hard fail unless setup command used.
kill switch present => do not trade.
```

The runner should:

```text
1. Fetch SiU6 candles.
2. Reuse existing hammer-maxhold5 signal logic.
3. When paper signal would open a trade:
   - pass risk manager;
   - submit sandbox order;
   - save order journal;
   - update sandbox position state.
4. Manage exits:
   - TAKE;
   - STOP;
   - MAX_HOLD_EXIT;
   - forced risk exit if needed.
5. Reconcile expected bot state vs sandbox account/positions/orders.
6. Update status JSON each cycle.
```

Important:

```text
Do not reuse paper DB.
Do not write to paper CSV.
Do not modify paper services.
```

---

## 4. Order/fill journal

Create DB tables, for example:

```text
sandbox_orders
sandbox_fills
sandbox_positions
sandbox_trades
sandbox_events
sandbox_daily_risk
```

Minimum fields for orders:

```text
order_id
signal_id
strategy
ticker
figi
instrument_uid
direction
order_side
order_type
requested_qty
requested_price
submitted_at
status
filled_qty
avg_fill_price
commission_rub
slippage_points
slippage_rub
raw_response_json
created_at
updated_at
```

Minimum fields for sandbox trades:

```text
trade_id
signal_id
entry_order_id
exit_order_id
ticker
direction
qty
entry_time
entry_price
stop_price
take_price
exit_time
exit_price
exit_reason
gross_pnl_rub
commission_rub
net_pnl_rub
bars_held
status
created_at
updated_at
```

---

## 5. Position reconciliation

Implement reconciliation every cycle:

Compare:

```text
bot expected position
sandbox account actual position
open orders
last known fills
```

If mismatch:

```text
1. status = RECONCILIATION_FAILED
2. stop opening new trades
3. do not send more entry orders
4. optionally allow controlled exit only if safe
5. write clear event/log
```

For MVP-L1a, conservative behavior is OK:

```text
on mismatch: stop trading and require manual intervention
```

---

## 6. Risk manager

Implement:

```text
src/sandbox/risk.py
```

or project-consistent location.

Checks before entry:

```text
kill switch absent
market session valid
daily loss not exceeded
total loss not exceeded
max trades/day not exceeded
max open positions not exceeded
max consecutive errors not exceeded
max consecutive losses not exceeded
order notional/contract limit not exceeded
no reconciliation failure
```

Checks after each trade/fill:

```text
update realized pnl
update daily pnl
update consecutive losses
if limits breached => trading_paused=true
```

---

## 7. Status JSON

Create status:

```text
runtime/sandbox_status_hammer_maxhold5_SiU6.json
```

Fields:

```json
{
  "mode": "sandbox",
  "strategy": "hammer_maxhold5",
  "ticker": "SiU6",
  "direction": "SELL",
  "max_hold_bars": 5,
  "orders_enabled": true,
  "real_orders_enabled": false,
  "paper_control_service": "hammertrade-paper-maxhold5.service",

  "liveness": "OK",
  "trading_state": "WAITING_FOR_SIGNAL",
  "kill_switch_active": false,

  "sandbox_account_id_present": true,
  "token_present": true,

  "open_positions_expected": 0,
  "open_positions_actual": 0,
  "open_orders": 0,

  "daily_pnl_rub": 0,
  "total_pnl_rub": 0,
  "daily_loss_limit_rub": 3000,
  "total_loss_limit_rub": 10000,
  "trades_today": 0,
  "max_trades_per_day": 5,

  "last_successful_fetch_at": "...",
  "last_successful_reconciliation_at": "...",
  "last_order_event_at": null,
  "last_error_at": null,
  "last_error_message": null
}
```

Do not expose token.

---

## 8. Diagnostics

Create:

```text
scripts/sandbox_diagnostics.py
```

Should report:

```text
service/mode
account_id present
open positions expected/actual
open orders
closed trades
orders submitted
fills
realized pnl
commissions
slippage
risk state
reconciliation state
kill switch
last errors
```

Outputs:

```text
reports/sandbox_diagnostics_hammer_maxhold5_latest.md
out/sandbox/sandbox_diagnostics_hammer_maxhold5_latest.csv
```

If no trades yet, should not crash.

---

## 9. Systemd example only

Create:

```text
deploy/systemd/hammertrade-sandbox-maxhold5.example.service
```

But do NOT install/start it.

It should run:

```bash
/opt/hammertrade/.venv/bin/python /opt/hammertrade/scripts/run_hammer_maxhold5_sandbox.py   --config /opt/hammertrade/configs/sandbox/hammer_maxhold5_siu6.yaml
```

Add comments:

```text
Example only.
Do not install before explicit approval.
Sandbox only.
Never live.
```

---

## 10. Tests

Add tests:

```text
tests/test_sandbox_risk_manager.py
tests/test_sandbox_repository.py
tests/test_sandbox_reconciliation.py
tests/test_hammer_maxhold5_sandbox_cli.py
tests/test_sandbox_status.py
```

Minimum tests:

Risk manager:

```text
- blocks when kill switch exists
- blocks when daily loss exceeded
- blocks when total loss exceeded
- blocks when max trades/day exceeded
- blocks when reconciliation failed
- allows normal trade under limits
```

Repository:

```text
- creates DB tables
- saves order
- saves fill
- saves trade
- exports CSV
```

Reconciliation:

```text
- expected flat / actual flat OK
- expected position / actual same OK
- expected flat / actual position FAIL
- expected position / actual flat FAIL
```

CLI:

```text
- config loads
- missing token hard fails
- live mode hard fails
- dry-run once works
```

Status:

```text
- token_present boolean only, no token value
- account_id_present boolean only or masked account id
- liveness fields present
```

Run:

```bash
.venv/bin/python -m pytest   tests/test_sandbox_risk_manager.py   tests/test_sandbox_repository.py   tests/test_sandbox_reconciliation.py   tests/test_hammer_maxhold5_sandbox_cli.py   tests/test_sandbox_status.py
```

If feasible:

```bash
.venv/bin/python -m pytest
```

---

# Smoke checks

After implementation:

## Without token

Run:

```bash
python scripts/run_hammer_maxhold5_sandbox.py   --config configs/sandbox/hammer_maxhold5_siu6.yaml   --dry-run   --once
```

Expected:

```text
Clear fail if token/account missing,
or dry-run skips API order calls safely depending implementation.
No real/sandbox order should be submitted in dry-run.
```

## With token later

The user will provide token separately after this prompt.

When token is added to `.env`, run only safe setup:

```bash
python scripts/sandbox_account_setup.py
```

Do not start daemon yet.

Do not submit sandbox order yet unless explicit next task asks for it.

---

# Documentation

Create:

```text
docs/sandbox_execution_hammer_maxhold5.md
```

Sections:

```markdown
# Sandbox Execution — Hammer MaxHold5

## Purpose

## Why separate from paper

## Token handling

## Sandbox account

## Config

## Runner

## Risk limits

## Reconciliation

## Kill switch

## Order/fill journal

## Diagnostics

## How to run dry-run

## How to setup sandbox account

## What is still not live

## Path to micro-live

## Safety checklist
```

---

# Report

Create:

```text
reports/mvp_l1a_sandbox_architecture_YYYYMMDD.md
reports/mvp_l1a_sandbox_architecture_latest.md
```

Use actual date.

---

# Final response format

Claude final response:

```markdown
## MVP-L1a Sandbox Execution Architecture — готово

### Summary

### What was created

### Config

### Token handling

### Sandbox account handling

### Runner

### Risk manager

### Reconciliation

### Order/fill journal

### Status

### Diagnostics

### Tests

### Smoke result

### What was NOT started

### What was NOT changed

### How user should provide token

### Next step
```

---

# Acceptance Criteria

MVP-L1a is complete if:

1. Current paper services unchanged and still running.
2. Momentum not launched.
3. Sandbox execution architecture created.
4. Sandbox runner exists.
5. Sandbox config exists.
6. Separate sandbox DB/status/log/CSV paths exist.
7. Token is expected via env and is never logged.
8. Live mode hard fails.
9. Risk manager implemented.
10. Reconciliation implemented.
11. Kill switch implemented.
12. Order/fill journal implemented.
13. Systemd example created but not installed.
14. Tests added and pass.
15. Report and docs created.
16. No sandbox daemon started.
17. No real orders possible.
