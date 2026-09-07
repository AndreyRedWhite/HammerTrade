# Claude Code Prompt — Monday Rollover Readiness Check: SiM6 → SiU6

## Контекст

Проект: `HammerTrade / MOEXF`.

Сейчас на сервере работают три paper-сервиса:

```text
1. hammer-baseline
   systemd: hammertrade-paper.service
   ticker: SiM6
   direction: SELL
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
   db: data/paper/paper_state_orb.sqlite
   status: runtime/paper_status_SiM6_ORB.json
```

Momentum paper engine уже подготовлен, но НЕ запущен:

```text
scripts/run_momentum_paper_trader.py
configs/paper/momentum_continuation_siu6_paper_example.yaml
deploy/systemd/hammertrade-paper-momentum.example.service
```

Momentum запускать только после rollover и отдельного подтверждения.

---

## Важный календарь

```text
SiM6 expiration_date: 2026-06-19
SiU6 expiration_date: 2026-09-18
Сегодня: понедельник, 2026-06-08
Плановая крайняя дата rollover: среда, 2026-06-10
```

Важно: 10 июня — это среда, не понедельник.

---

## Предыдущие наблюдения по SiU6

```text
2026-05-27:
  SiU6 avg vol/bar около 187

2026-06-02:
  SiU6 avg vol/bar около 250

2026-06-04:
  SiU6 avg vol/bar около 375
  spread около 2 pt

2026-06-05:
  SiU6 avg vol/bar около 307
  spread около 4 pt
```

Целевой ориентир для rollover:

```text
SiU6 avg volume/bar за последние 60 минут основной сессии >= 500
```

Но также есть date-based deadline:

```text
Если до 2026-06-10 SiU6 не достигнет 500, всё равно готовиться к переключению по дате,
если нет критичных причин ждать.
```

---

## Цель задачи

Сделать понедельничную проверку готовности к rollover `SiM6 → SiU6`.

Нужно:

```text
1. Проверить health всех трёх текущих paper-сервисов.
2. Проверить, есть ли открытые позиции.
3. Проверить свежую ликвидность SiM6 и SiU6.
4. Проверить spread и стакан SiM6 vs SiU6.
5. Проверить, можно ли безопасно роллировать сегодня.
6. Дать решение:
   - ROLL_TODAY
   - PREPARE_FOR_TOMORROW
   - WAIT_UNTIL_JUN10
   - DO_NOT_ROLL
7. Ничего не переключать без отдельного подтверждения.
```

---

## Жёсткие ограничения

Строго запрещено:

- останавливать сервисы;
- менять systemd units;
- менять ticker в сервисах;
- менять DB/status/csv/log paths;
- выполнять rollover;
- запускать Momentum service;
- запускать sandbox orders;
- запускать real orders;
- менять `.env`;
- печатать токены;
- удалять DB/CSV/logs/reports;
- делать автоматическое переключение.

Разрешено:

- читать status files;
- читать SQLite DB;
- читать logs;
- читать T-Bank API для market data / instruments / candles / orderbook;
- запускать diagnostics scripts;
- создавать Markdown report;
- создавать CSV report;
- давать рекомендацию.

---

## Команды для health check

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

---

## Проверка открытых позиций

Обязательно проверить по всем трём стратегиям:

```text
hammer-baseline
hammer-maxhold5
orb-paper
```

Нужно явно написать:

```text
open_trades = 0 / not 0
```

Если есть открытая позиция:

```text
DO NOT ROLL
```

И указать:

```text
strategy
entry_time
entry_price
stop
take
current status
```

---

## Проверка SiM6 / SiU6 через API

Нужно проверить оба инструмента:

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

Проверить, что SiU6 торгуется и параметры совместимы:

```text
class_code = SPBFUT
lot = 1
min_price_increment = 1.0
```

---

## Проверка ликвидности

Проверить по SiM6 и SiU6:

```text
1. 1m candles за последние 60 минут основной сессии.
2. avg volume/bar.
3. median volume/bar.
4. total volume за 60 минут.
5. number of zero-volume candles.
6. spread сейчас.
7. top-5 depth.
8. top-10 depth.
```

Если проверка идёт до/после основной сессии, явно указать limitation и использовать последний полный час основной сессии.

Основная сессия:

```text
10:00–19:00 MSK
```

---

## Формат таблицы ликвидности

Сформировать таблицу:

```text
Metric                      SiM6        SiU6        Ratio/Comment
avg volume/bar 60m
median volume/bar 60m
total volume 60m
zero-volume candles
current spread
top-5 depth bid+ask
top-10 depth bid+ask
min_price_increment
lot
expiration_date
```

---

## Rollover decision rules

## ROLL_TODAY

Только если одновременно:

```text
open_trades = 0 по всем сервисам
все сервисы liveness OK
SiU6 trading_status OK
SiU6 avg volume/bar >= 500
SiU6 spread <= SiM6 spread * 2
SiU6 top-5/top-10 depth acceptable
нет критичных ошибок API
```

## PREPARE_FOR_TOMORROW

Если:

```text
open_trades = 0
сервисы OK
SiU6 avg volume/bar близко к порогу, например 400–500
spread/depth приемлемые
но лучше дождаться ещё одного дня
```

## WAIT_UNTIL_JUN10

Если:

```text
SiU6 avg volume/bar < 400
или spread/depth хуже ожиданий
но до date deadline ещё есть время
```

## DO_NOT_ROLL

Если:

```text
есть открытые позиции
или SiU6 не торгуется
или SiU6 spread/depth критично плохие
или API/data quality unstable
или один из сервисов STALLED/DEGRADED
```

---

## Что подготовить, если решение PREPARE или ROLL_TODAY

Если решение `PREPARE_FOR_TOMORROW` или `ROLL_TODAY`, дать список команд для будущего rollover, но НЕ выполнять их.

Команды должны быть безопасно разделены на шаги:

```text
1. Проверить open_trades = 0.
2. Остановить один сервис.
3. Архивировать старые SiM6 artifacts.
4. Обновить/создать unit/drop-in для SiU6.
5. Запустить сервис.
6. Проверить status.
7. Повторить для следующего сервиса.
8. Momentum запускать только отдельным решением после успешного rollover.
```

Важно:

```text
Не давать команду enable --now одной строкой без проверки.
```

---

## ORB текущие риски

В отчёте отдельно отметить текущий статус ORB:

За неделю были сделки:

```text
Jun 3: STOP -6 770 RUB
Jun 4: TIME_EXIT +4 290 RUB
Jun 5: STOP -5 240 RUB
Итого: -7 720 RUB
```

Вывод:

```text
ORB технически работает, но риск зависит от ширины opening range.
Нужен отдельный ORB Range / Risk Cap Audit.
```

Не менять ORB в этой задаче.

---

## Momentum текущий статус

Отметить:

```text
Momentum paper engine готов.
Dry-run OK.
Systemd не установлен.
Сервис не запущен.
Ждёт rollover и отдельного подтверждения.
```

Не запускать Momentum в этой задаче.

---

## Отчёт

Создать:

```text
reports/rollover_readiness_20260608.md
reports/rollover_readiness_latest.md
```

Структура:

```markdown
# Rollover Readiness Check — SiM6 → SiU6 — 2026-06-08

## Краткий вывод

## Service health

## Open trades

## Instrument check

## Liquidity comparison

## Orderbook / spread

## Rollover decision

## Reasoning

## If prepare/roll: proposed runbook

## ORB note

## Momentum note

## Risks / limitations

## Recommendation
```

---

## Финальный ответ Claude

В финальном ответе дать:

```markdown
## Rollover readiness check — готово

### Краткий вывод

### Service health

### Open trades

### SiM6 vs SiU6 liquidity

### Spread / depth

### Decision

### Why

### Recommended next action

### Artifacts

### What was NOT changed
```

---

## Acceptance Criteria

Задача выполнена, если:

1. Проверены все три сервиса.
2. Проверены открытые позиции.
3. Проверены инструменты SiM6 и SiU6.
4. Проверена ликвидность SiM6 и SiU6.
5. Проверены spread/depth.
6. Дано решение `ROLL_TODAY / PREPARE_FOR_TOMORROW / WAIT_UNTIL_JUN10 / DO_NOT_ROLL`.
7. Создан Markdown report.
8. Ничего не переключено.
9. Momentum не запущен.
10. Current services unchanged.
