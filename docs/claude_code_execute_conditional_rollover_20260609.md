# Claude Code Prompt — MVP-2.4: Execute Conditional Rollover SiM6 → SiU6 — 2026-06-09

## Контекст

Проект: `HammerTrade / MOEXF`.

Сервер:

```text
Server: 158.160.204.201
User: vorontsov
Project path: /opt/hammertrade
Virtualenv: /opt/hammertrade/.venv
```

Сейчас работают три paper-сервиса на `SiM6`:

```text
1. hammer-baseline
   systemd: hammertrade-paper.service
   ticker: SiM6
   direction: SELL
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

3. orb-paper
   systemd: hammertrade-paper-orb.service
   strategy: opening_range_breakout
   ticker: SiM6
   direction: SHORT
   db: data/paper/paper_state_orb.sqlite
   status: runtime/paper_status_SiM6_ORB.json
   csv: out/paper/paper_trades_SiM6_ORB.csv
   log: logs/paper_SiM6_ORB.log
```

Momentum paper engine уже подготовлен, но НЕ запущен:

```text
scripts/run_momentum_paper_trader.py
configs/paper/momentum_continuation_siu6_paper_example.yaml
deploy/systemd/hammertrade-paper-momentum.example.service
```

Momentum НЕ запускать в рамках этого MVP. Его запуск будет отдельным подтверждением после успешного rollover.

---

## Дата и причина задачи

Сегодня:

```text
2026-06-09, вторник
```

Плановый rollover:

```text
SiM6 → SiU6
```

Сроки:

```text
SiM6 expiration_date: 2026-06-19
SiU6 expiration_date: 2026-09-18
Плановая крайняя дата rollover: 2026-06-10, среда
```

Вчера, 2026-06-08, readiness check дал:

```text
Decision: DO_NOT_ROLL сейчас → PREPARE_FOR_TOMORROW
Reason:
  - orb-paper имел открытую позицию;
  - SiU6 avg vol/bar был около 414, близко к порогу 500;
  - spread/depth были приемлемыми;
  - сервисы были OK.
```

Сегодня нужно повторить проверку и, если условия выполнены, выполнить rollover.

---

# Главная цель

Выполнить **conditional rollover** текущих трёх paper-сервисов с `SiM6` на `SiU6`.

Логика:

```text
1. Сначала проверить условия.
2. Если есть открытые позиции — НЕ роллить.
3. Если сервисы не OK — НЕ роллить.
4. Если SiU6 торгуется и ликвидность приемлема — выполнить rollover.
5. Роллить строго по одному сервису.
6. После каждого сервиса проверять status/liveness.
7. Старые SiM6 artifacts архивировать, не удалять.
8. Новые SiU6 artifacts создавать отдельными файлами.
9. Momentum НЕ запускать.
```

---

# Жёсткие ограничения

Строго запрещено:

- запускать Momentum service;
- запускать sandbox orders;
- запускать real orders;
- менять `.env`;
- печатать токены;
- удалять DB/CSV/logs/reports;
- переносить старую SiM6 DB в новую SiU6 DB;
- смешивать SiM6 и SiU6 trades в одной DB/CSV;
- менять стратегические параметры:
  - hammer detector params;
  - max_hold_bars=5 для maxhold5;
  - ORB opening range/take/stop params;
- запускать все сервисы без промежуточных проверок;
- использовать одну команду `enable --now` без проверки unit;
- делать rollout, если есть open_trades;
- делать вид, что rollover успешен, если хотя бы один сервис STALLED/DEGRADED.

Разрешено:

- читать status files;
- читать SQLite DB;
- читать logs;
- читать T-Bank API для instruments/candles/orderbook;
- останавливать и запускать текущие три paper-сервиса только в рамках rollover;
- создавать backup/archive copies;
- создавать/обновлять systemd units или drop-ins под SiU6;
- создавать новые SiU6 DB/status/csv/log;
- создавать Markdown report;
- запускать diagnostics после переключения.

---

# Этап 0 — Pre-flight checks

Выполнить:

```bash
cd /opt/hammertrade
source .venv/bin/activate

sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
sudo systemctl status hammertrade-paper-orb --no-pager

python scripts/check_all_paper_status.py
python scripts/compare_all_paper_experiments.py
python scripts/paper_error_report.py
```

Проверить:

```text
liveness
last_successful_fetch_at
consecutive_api_errors
open_trades
closed_trades_total
market_status
```

## Open trades check

Обязательно проверить open trades по всем трём сервисам:

```text
hammer-baseline
hammer-maxhold5
orb-paper
```

Если хотя бы у одного сервиса:

```text
open_trades > 0
```

то:

```text
Decision: DO_NOT_ROLL_OPEN_POSITION
```

Ничего не переключать.

В отчёте указать:

```text
strategy
entry time
entry price
stop
take
current state
expected latest close/time_exit
```

---

# Этап 1 — Liquidity / instrument check

Проверить инструменты:

```text
SiM6
SiU6
```

Поля:

```text
ticker
name
figi
uid
class_code
lot
min_price_increment
expiration_date
trading_status
```

Проверить совместимость:

```text
class_code = SPBFUT
lot = 1
min_price_increment = 1.0
```

Проверить ликвидность за последний полный час основной сессии или последние 60 минут основной сессии:

```text
main session: 10:00–19:00 MSK
```

Для `SiM6` и `SiU6`:

```text
avg volume/bar
median volume/bar
total volume 60m
zero-volume candles
current spread
top-5 depth bid+ask
top-10 depth bid+ask
```

## Decision rules

## ROLL_TODAY

Можно роллить, если:

```text
open_trades = 0 по всем сервисам
все сервисы liveness OK
SiU6 trading_status OK
SiU6 avg volume/bar >= 400
SiU6 spread <= SiM6 spread * 2
SiU6 top-5/top-10 depth не критично хуже
нет критичных ошибок API
```

Важно: вчера SiU6 был около 414 avg vol/bar. Так как deadline уже завтра, 2026-06-10, порог для rollover сегодня можно считать `>= 400`, если spread/depth приемлемые.

## WAIT_UNTIL_JUN10

Если:

```text
open_trades = 0
сервисы OK
но SiU6 avg volume/bar < 400
или spread/depth явно плохие
```

Тогда не роллить сегодня, но готовиться к повторной проверке 2026-06-10.

## DO_NOT_ROLL

Если:

```text
есть open_trades
или один из сервисов DEGRADED/STALLED
или SiU6 не торгуется
или API/data unstable
```

---

# Этап 2 — Rollover execution plan

Если decision = `ROLL_TODAY`, выполнить rollover по одному сервису.

Рекомендуемый порядок:

```text
1. hammer-baseline
2. hammer-maxhold5
3. orb-paper
```

Momentum не запускать.

---

# Новые SiU6 artifacts

## hammer-baseline SiU6

```text
DB:
  data/paper/paper_state_siu6.sqlite

Status:
  runtime/paper_status_SiU6_SELL.json

CSV:
  out/paper/paper_trades_SiU6_SELL.csv

Log:
  logs/paper_SiU6_SELL.log
```

## hammer-maxhold5 SiU6

```text
DB:
  data/paper/paper_state_siu6_maxhold5.sqlite

Status:
  runtime/paper_status_SiU6_SELL_maxhold5.json

CSV:
  out/paper/paper_trades_SiU6_SELL_maxhold5.csv

Log:
  logs/paper_SiU6_SELL_maxhold5.log
```

## orb-paper SiU6

```text
DB:
  data/paper/paper_state_siu6_orb.sqlite

Status:
  runtime/paper_status_SiU6_ORB.json

CSV:
  out/paper/paper_trades_SiU6_ORB.csv

Log:
  logs/paper_SiU6_ORB.log
```

Important:

```text
Do not reuse old SiM6 DBs.
Do not copy last_processed_candle_ts from SiM6 to SiU6.
Start clean on SiU6.
Archive SiM6 artifacts, but do not delete.
```

---

# Этап 3 — Archive SiM6 artifacts

Before switching each service, archive its current SiM6 artifacts.

Use date suffix:

```text
ARCHIVED_20260609
```

Examples:

```bash
cp data/paper/paper_state.sqlite data/paper/paper_state_SiM6_ARCHIVED_20260609.sqlite
cp runtime/paper_status_SiM6_SELL.json runtime/paper_status_SiM6_SELL_ARCHIVED_20260609.json
cp out/paper/paper_trades_SiM6_SELL.csv out/paper/paper_trades_SiM6_SELL_ARCHIVED_20260609.csv
cp logs/paper_SiM6_SELL.log logs/paper_SiM6_SELL_ARCHIVED_20260609.log
```

Do equivalent for maxhold5 and ORB.

If some file does not exist, do not fail the whole rollover; log warning.

---

# Этап 4 — Rollover hammer-baseline

## 4.1 Stop service

```bash
sudo systemctl stop hammertrade-paper.service
```

Verify stopped:

```bash
sudo systemctl status hammertrade-paper --no-pager
```

## 4.2 Update unit or drop-in

Update command args from:

```text
--ticker SiM6
--state-db data/paper/paper_state.sqlite
--status-file runtime/paper_status_SiM6_SELL.json
--csv-output out/paper/paper_trades_SiM6_SELL.csv
--log-file logs/paper_SiM6_SELL.log
```

to:

```text
--ticker SiU6
--state-db data/paper/paper_state_siu6.sqlite
--status-file runtime/paper_status_SiU6_SELL.json
--csv-output out/paper/paper_trades_SiU6_SELL.csv
--log-file logs/paper_SiU6_SELL.log
```

If service uses config file instead of args, update config safely and document exact file.

Do not change strategy params.

## 4.3 Reload and start

```bash
sudo systemctl daemon-reload
sudo systemctl start hammertrade-paper.service
sleep 20
```

## 4.4 Verify

```bash
sudo systemctl status hammertrade-paper --no-pager

python scripts/check_paper_status.py   --status-file runtime/paper_status_SiU6_SELL.json
```

Expected:

```text
ticker = SiU6
liveness OK or MARKET_CLOSED depending session
open_trades = 0
consecutive_api_errors = 0
```

If failed:

```text
STOP and investigate.
Do not proceed to next service until fixed or rolled back.
```

---

# Этап 5 — Rollover hammer-maxhold5

Repeat same pattern.

## New args

```text
--ticker SiU6
--state-db data/paper/paper_state_siu6_maxhold5.sqlite
--status-file runtime/paper_status_SiU6_SELL_maxhold5.json
--csv-output out/paper/paper_trades_SiU6_SELL_maxhold5.csv
--log-file logs/paper_SiU6_SELL_maxhold5.log
--max-hold-bars 5
--experiment-name maxhold5
```

Verify:

```bash
python scripts/check_paper_status.py   --status-file runtime/paper_status_SiU6_SELL_maxhold5.json
```

Expected:

```text
ticker = SiU6
max_hold_bars = 5
liveness OK
open_trades = 0
```

---

# Этап 6 — Rollover orb-paper

Repeat same pattern.

## New args

```text
--ticker SiU6
--state-db data/paper/paper_state_siu6_orb.sqlite
--status-file runtime/paper_status_SiU6_ORB.json
--csv-output out/paper/paper_trades_SiU6_ORB.csv
--log-file logs/paper_SiU6_ORB.log
--experiment-name orb_or60_short2r
```

Keep same ORB strategy params:

```text
direction = SHORT
opening range = 10:00–11:00
take_r = 2.0
stop_mode = opposite_range
entry_mode = breakout_level
time_exit = 18:40
max_trades_per_day = 1
orders_enabled = false
```

Verify:

```bash
python scripts/check_paper_status.py   --status-file runtime/paper_status_SiU6_ORB.json
```

Expected:

```text
ticker = SiU6
strategy = opening_range_breakout
orders_enabled = false
liveness OK
open_trades = 0
```

---

# Этап 7 — Post-rollover verification

After all three services are switched:

```bash
sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
sudo systemctl status hammertrade-paper-orb --no-pager

python scripts/check_all_paper_status.py
python scripts/compare_all_paper_experiments.py
python scripts/paper_error_report.py
```

Expected:

```text
hammer-baseline: SiU6, OK
hammer-maxhold5: SiU6, OK
orb-paper: SiU6, OK
momentum: not launched
```

Also verify files exist:

```bash
ls -lah data/paper/*siu6*
ls -lah runtime/*SiU6*
ls -lah out/paper/*SiU6*
ls -lah logs/*SiU6*
```

---

# Этап 8 — Report

Create:

```text
reports/rollover_simu6_to_siu6_20260609.md
reports/rollover_simu6_to_siu6_latest.md
```

Report structure:

```markdown
# Rollover SiM6 → SiU6 — 2026-06-09

## Decision

## Pre-flight service health

## Open trades

## Liquidity check

## Instrument check

## Actions performed

## Archives created

## New SiU6 artifacts

## Service-by-service verification

## Post-rollover status

## Momentum status

## Issues / warnings

## Rollback plan

## Recommendation
```

---

# Rollback plan

If one service fails after switching:

```text
1. Stop failed service.
2. Restore previous SiM6 unit args/config from archive/backup.
3. daemon-reload.
4. Start service on SiM6.
5. Verify old status.
6. Do not proceed with remaining services.
7. Document failure.
```

If baseline already switched but maxhold5 fails:

```text
Prefer fixing maxhold5 on SiU6.
If cannot fix quickly, rollback maxhold5 only or rollback all services to SiM6 depending severity.
Do not leave unclear mixed state without documenting.
```

Mixed state is acceptable briefly during migration, but final state must be explicit:

```text
all rolled to SiU6
or partial with reason
or all rolled back
```

---

# Momentum note

Momentum paper engine is ready but must remain not launched.

After successful rollover and at least one clean SiU6 trading day:

```text
Prepare separate task:
  MVP-R3 Launch Momentum Paper Service on SiU6
```

Do not do it now.

---

# ORB note

Keep ORB params unchanged despite recent losses.

Known issue:

```text
ORB risk depends on OR range.
Need future ORB Range / Risk Cap Audit.
```

Do not implement risk cap in this task.

---

# Final response format

Claude final response:

```markdown
## MVP-2.4 Rollover SiM6 → SiU6 — готово / не выполнено

### Decision

### Why

### Pre-flight checks

### Liquidity SiM6 vs SiU6

### Open trades

### Actions performed

### Services switched

### New artifacts

### Archives

### Post-rollover status

### Momentum status

### What was NOT changed

### Issues / warnings

### Rollback status

### Next steps
```

If rollover was not executed, use:

```markdown
## Rollover check — не переключали

### Reason

### Current blockers

### Recommended next check
```

---

# Acceptance Criteria

If rollover executed:

1. All three existing services switched to SiU6 or partial state is clearly explained.
2. No open trades existed before switching.
3. SiM6 artifacts archived.
4. New SiU6 DB/status/csv/log paths used.
5. Services active after switch.
6. Liveness OK or market-closed OK.
7. Momentum not launched.
8. Report created.
9. No real/sandbox orders.
10. No deletion of old data.

If rollover not executed:

1. Clear reason.
2. Services unchanged.
3. Momentum not launched.
4. Next recommended time/action stated.
