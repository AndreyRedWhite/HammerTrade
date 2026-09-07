# Claude Code Prompt — MVP-2.4a: First SiU6 Trading Day Validation

## Контекст

Проект: `HammerTrade / MOEXF`.

Сервер:

```text
Server: 158.160.204.201
User: vorontsov
Project path: /opt/hammertrade
Virtualenv: /opt/hammertrade/.venv
```

## Что уже произошло

2026-06-09 был выполнен rollover:

```text
SiM6 → SiU6
```

Итог после rollover:

```text
Status: 2026-06-09 16:04 UTC

hammer-baseline    SiU6   SELL   OK
hammer-maxhold5    SiU6   SELL   OK
orb-paper          SiU6   SHORT  OK
momentum-paper     SiU6   not launched
```

Что было сделано:

```text
1. Pre-flight: все позиции = 0, сервисы OK.
2. Заархивированы SiM6 артефакты с suffix ARCHIVED_20260609.
3. Обновлены systemd unit-файлы: SiM6 → SiU6.
4. Для всех трёх сервисов заданы новые DB/status/CSV/log paths.
5. Каждый сервис перезапущен и проверен индивидуально.
6. Обновлены дефолты в check_all_paper_status.py и paper_error_report.py.
7. Momentum не запущен.
```

Новые активные SiU6 artifacts:

```text
baseline:
  db:     data/paper/paper_state_siu6.sqlite
  status: runtime/paper_status_SiU6_SELL.json
  csv:    out/paper/paper_trades_SiU6_SELL.csv
  log:    logs/paper_SiU6_SELL.log

maxhold5:
  db:     data/paper/paper_state_siu6_maxhold5.sqlite
  status: runtime/paper_status_SiU6_SELL_maxhold5.json
  csv:    out/paper/paper_trades_SiU6_SELL_maxhold5.csv
  log:    logs/paper_SiU6_SELL_maxhold5.log

orb-paper:
  db:     data/paper/paper_state_siu6_orb.sqlite
  status: runtime/paper_status_SiU6_ORB.json
  csv:    out/paper/paper_trades_SiU6_ORB.csv
  log:    logs/paper_SiU6_ORB.log
```

---

# Главная цель

Провести первую полноценную проверку торгового дня после rollover.

Нужно убедиться, что сервисы не просто `active`, а реально корректно работают на `SiU6`:

```text
1. Все три сервиса живы.
2. Все три сервиса читают именно SiU6.
3. last_successful_fetch_at свежий.
4. Нет API errors.
5. Новые SiU6 DB реально используются.
6. Новые SiU6 CSV/log/status обновляются.
7. Hammer baseline и maxhold5 корректно обрабатывают свечи SiU6.
8. ORB корректно строит opening range уже по SiU6.
9. В активных status/log/report нет старого SiM6 как рабочего ticker.
10. Momentum остаётся not launched.
```

---

# Жёсткие ограничения

Строго запрещено:

- запускать Momentum service;
- запускать sandbox orders;
- запускать real orders;
- менять стратегические параметры;
- менять systemd units;
- выполнять повторный rollover;
- откатываться на SiM6 без критической причины;
- удалять DB/CSV/log/status/reports;
- переносить старую SiM6 историю в новые SiU6 DB;
- смешивать SiM6 и SiU6 history;
- менять `.env`;
- печатать токены;
- чинить что-то «по ходу» без отдельного вывода, если это не мелкий безопасный reporting bug.

Разрешено:

- читать status files;
- читать SQLite DB;
- читать CSV;
- читать logs;
- запускать diagnostics scripts;
- читать T-Bank API для instruments/candles/orderbook;
- создавать Markdown report;
- создавать CSV diagnostics;
- давать рекомендации.

---

# Этап 1 — Service health check

Выполнить:

```bash
cd /opt/hammertrade
source .venv/bin/activate

sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
sudo systemctl status hammertrade-paper-orb --no-pager

python scripts/check_all_paper_status.py
python scripts/paper_error_report.py
```

Проверить:

```text
active/running
liveness
ticker
direction
strategy
last_successful_fetch_at
last_processed_candle_ts
consecutive_api_errors
total_api_errors
open_trades
closed_trades_total
market_status
```

Expected:

```text
hammer-baseline:
  ticker = SiU6
  direction = SELL
  liveness = OK / MARKET_CLOSED_OK depending session

hammer-maxhold5:
  ticker = SiU6
  direction = SELL
  max_hold_bars = 5
  liveness = OK / MARKET_CLOSED_OK depending session

orb-paper:
  ticker = SiU6
  strategy = opening_range_breakout
  direction = SHORT
  liveness = OK / MARKET_CLOSED_OK depending session

momentum-paper:
  not launched
```

---

# Этап 2 — Verify active artifacts

Проверить, что активные файлы существуют и обновляются:

```bash
ls -lah data/paper/*siu6*
ls -lah runtime/*SiU6*
ls -lah out/paper/*SiU6*
ls -lah logs/*SiU6*
```

Проверить mtimes:

```text
runtime/paper_status_SiU6_SELL.json
runtime/paper_status_SiU6_SELL_maxhold5.json
runtime/paper_status_SiU6_ORB.json

logs/paper_SiU6_SELL.log
logs/paper_SiU6_SELL_maxhold5.log
logs/paper_SiU6_ORB.log
```

Если рынок открыт, status/log должны обновляться регулярно.

---

# Этап 3 — Verify SQLite DB state

Проверить таблицы и базовое состояние новых DB:

```bash
sqlite3 data/paper/paper_state_siu6.sqlite '.tables'
sqlite3 data/paper/paper_state_siu6_maxhold5.sqlite '.tables'
sqlite3 data/paper/paper_state_siu6_orb.sqlite '.tables'
```

Проверить:

```text
open trades count
closed trades count
latest trade
latest processed candle / daily state if stored
```

Примерно:

```bash
sqlite3 data/paper/paper_state_siu6.sqlite 'SELECT COUNT(*) FROM paper_trades WHERE status="OPEN";'
sqlite3 data/paper/paper_state_siu6_maxhold5.sqlite 'SELECT COUNT(*) FROM paper_trades WHERE status="OPEN";'
sqlite3 data/paper/paper_state_siu6_orb.sqlite 'SELECT COUNT(*) FROM orb_paper_trades WHERE status="OPEN";'
```

Если имена таблиц отличаются, определить реальные имена через `.tables`.

---

# Этап 4 — Verify no active SiM6 leakage

Проверить, что активные status/log/default scripts больше не считают SiM6 активным тикером.

Искать осторожно:

```bash
grep -R "SiM6" runtime/*.json logs/paper_*.log scripts/check_all_paper_status.py scripts/paper_error_report.py | tail -100
```

Важно:

```text
SiM6 может встречаться в archived filenames, старых логах и reports.
Это нормально.

Проблема только если:
  - active status для текущего сервиса показывает SiM6;
  - check_all_paper_status.py показывает SiM6 как активный;
  - новые SiU6 logs пишут SiM6 как ticker;
  - active unit всё ещё запускает --ticker SiM6.
```

Проверить active units:

```bash
systemctl cat hammertrade-paper
systemctl cat hammertrade-paper-maxhold5
systemctl cat hammertrade-paper-orb
```

Expected:

```text
--ticker SiU6
новые SiU6 paths
```

---

# Этап 5 — Verify market data on SiU6

Через существующие project scripts или короткий безопасный Python snippet проверить, что API отдаёт свежие SiU6 candles.

Нужно получить для `SiU6`:

```text
last 5 candles 1m
last candle timestamp
volume
open/high/low/close
```

Проверить:

```text
candles не пустые;
timestamp свежий;
volume > 0 хотя бы в части свечей;
цены соответствуют SiU6, а не SiM6.
```

Также проверить instrument metadata:

```text
ticker = SiU6
class_code = SPBFUT
lot = 1
min_price_increment = 1.0
expiration_date = 2026-09-18
```

---

# Этап 6 — ORB-specific validation

ORB после rollover особенно важен.

Если проверка выполняется:

## До 11:00 МСК

Проверить, что ORB в состоянии:

```text
COLLECTING_OPENING_RANGE
```

или эквивалентном состоянии.

Проверить, что он собирает диапазон по `SiU6`.

## После 11:00 МСК

Проверить, что ORB построил opening range по `SiU6`.

Нужно извлечь:

```text
date
or_start
or_end
or_high
or_low
or_range
state
expected breakout level
open_trades
trades_today
```

Expected:

```text
ticker = SiU6
opening range based on 10:00–11:00 MSK candles
state = WAITING_FOR_BREAKOUT / IN_TRADE / DONE_FOR_DAY
orders_enabled = false
```

Если ORB уже открыл сделку, не трогать её. Просто зафиксировать:

```text
entry
stop
take
risk points
risk rub
state
latest close/time_exit
```

---

# Этап 7 — Hammer-specific validation

Для hammer-baseline и hammer-maxhold5 проверить:

```text
ticker = SiU6
direction = SELL
max_hold_bars:
  baseline = None / absent
  maxhold5 = 5

last_processed_candle_ts свежий
signals/trades processing не падает
open_trades count корректный
closed_trades count корректный
```

Если за день уже были сделки, вывести последние 5 по каждому:

```text
entry_time
exit_time
exit_reason
pnl_rub
bars_held
```

Если сделок ещё нет:

```text
это нормально, главное candles/status/liveness OK
```

---

# Этап 8 — Compare paper experiments after rollover

Запустить:

```bash
python scripts/compare_all_paper_experiments.py
```

Важно:

```text
После rollover новые SiU6 DB могут быть пустыми или почти пустыми.
Это нормально.

Нужно убедиться, что script не смешивает старую SiM6 историю с новой SiU6 историей.
```

Если compare script показывает combined history, явно отметить limitation.

Preferred:

```text
SiU6 epoch отдельно.
SiM6 archived epoch отдельно.
```

---

# Этап 9 — Create report

Создать:

```text
reports/first_siu6_validation_20260610.md
reports/first_siu6_validation_latest.md
```

Если фактическая дата отличается, использовать текущую дату в имени, но latest обязательно обновить.

Report structure:

```markdown
# First SiU6 Trading Day Validation

## Summary

## Service health

## Active artifacts

## DB state

## Market data validation

## Hammer baseline validation

## Hammer maxhold5 validation

## ORB validation

## SiM6 leakage check

## Compare scripts / diagnostics

## Momentum status

## Issues / warnings

## Recommendation

## Next steps
```

---

# Decision

В конце дать один из статусов:

## VALIDATION_OK

Если:

```text
все 3 сервиса active;
все 3 на SiU6;
liveness OK;
candles свежие;
new artifacts active;
нет API errors;
нет active SiM6 leakage;
Momentum not launched.
```

## VALIDATION_OK_WITH_WARNINGS

Если:

```text
сервисы работают,
но есть некритичные warnings:
  - compare script смешивает old/new history;
  - мало данных после rollover;
  - рынок закрыт и часть проверок ограничена;
  - CSV пока пустой, потому что сделок не было.
```

## VALIDATION_FAILED

Если:

```text
хотя бы один сервис не active;
или active ticker всё ещё SiM6;
или liveness STALLED/DEGRADED;
или candles не fetchятся;
или DB/status paths неправильные;
или есть active SiM6 leakage;
или Momentum случайно запущен.
```

---

# Momentum note

Momentum paper engine готов, но должен оставаться not launched.

Если validation = `VALIDATION_OK` или `VALIDATION_OK_WITH_WARNINGS`, можно рекомендовать отдельную следующую задачу:

```text
MVP-R3 Launch Momentum Paper Service on SiU6
```

Но не запускать его в этой задаче.

---

# Final response format

Claude final response:

```markdown
## MVP-2.4a First SiU6 Validation — готово

### Decision

### Service health

### Active ticker check

### Artifacts

### DB state

### Market data

### Hammer baseline

### Hammer maxhold5

### ORB

### SiM6 leakage check

### Momentum status

### Issues / warnings

### Report

### Recommendation

### Next steps
```

---

# Acceptance Criteria

Задача выполнена, если:

1. Проверены все 3 текущих сервиса.
2. Подтверждено, что все 3 работают на SiU6.
3. Проверены новые DB/status/CSV/log paths.
4. Проверены свежие SiU6 candles.
5. Проверен ORB opening range/state.
6. Проверены hammer baseline/maxhold5 states.
7. Проверено отсутствие active SiM6 leakage.
8. Momentum не запущен.
9. Создан Markdown report.
10. Дано решение `VALIDATION_OK / VALIDATION_OK_WITH_WARNINGS / VALIDATION_FAILED`.
