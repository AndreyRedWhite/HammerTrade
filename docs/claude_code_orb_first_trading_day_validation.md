# Claude Code Prompt — ORB First Trading Day Validation

## Контекст

Проект: `HammerTrade / MOEXF`.

Сейчас на сервере работают три paper-сервиса:

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
   stop_mode: opposite_range
   entry_mode: breakout_level
   time_exit: 18:40 MSK
   max_trades_per_day: 1
   orders_enabled: false
   db: data/paper/paper_state_orb.sqlite
   status: runtime/paper_status_SiM6_ORB.json
   csv: out/paper/paper_trades_SiM6_ORB.csv
   log: logs/paper_SiM6_ORB.log
```

ORB был запущен в выходной. Было проверено, что в MARKET_CLOSED он не дёргает T-Bank API, а `check_all_paper_status.py` теперь корректно показывает `N/A (mkt closed)`, если `last_successful_fetch_at = null` и рынок закрыт.

---

## Цель задачи

Проверить, как ORB paper service отработал первый полноценный торговый день после запуска.

Это не новая разработка и не изменение стратегии.

Нужно:

```text
1. Проверить health всех трёх сервисов.
2. Проверить ORB state machine по первому торговому дню.
3. Проверить, что ORB корректно построил opening range 10:00–11:00 MSK.
4. Проверить, был ли breakout.
5. Если была сделка — проверить entry/stop/take/exit/PnL.
6. Если сделки не было — объяснить почему.
7. Проверить DB/CSV/status/log.
8. Проверить, что ORB не отправлял real/sandbox orders.
9. Сформировать короткий Markdown-отчёт.
```

---

## Жёсткие ограничения

Строго запрещено:

- менять hammer services;
- менять orb service без необходимости;
- менять systemd unit files;
- перезапускать сервисы без причины;
- менять ORB strategy params;
- менять HammerDetector;
- менять `.env`;
- удалять DB/CSV/logs/reports;
- отправлять real orders;
- отправлять sandbox orders;
- включать orders;
- делать вывод “стратегия прибыльная” по одному дню.

Разрешено:

- читать status files;
- читать SQLite DB;
- читать CSV;
- читать logs/journalctl;
- запускать diagnostics scripts;
- создавать Markdown/CSV report;
- исправлять только очевидные bugfixes в отчётности/diagnostics, если они не меняют торговую логику.

Если найдёшь критичный баг в ORB paper engine, сначала опиши проблему и предложи фикс, но не меняй стратегию.

---

## Команды для первичной проверки

Выполнить на сервере:

```bash
cd /opt/hammertrade
source .venv/bin/activate

sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
sudo systemctl status hammertrade-paper-orb --no-pager

python scripts/check_all_paper_status.py
python scripts/paper_error_report.py
python scripts/compare_all_paper_experiments.py
python scripts/orb_paper_diagnostics.py
```

Также посмотреть логи ORB:

```bash
journalctl -u hammertrade-paper-orb --since 'today 09:30' --no-pager | tail -200
```

Если проверка делается во вторник, можно так:

```bash
journalctl -u hammertrade-paper-orb --since 'yesterday 09:30' --no-pager | tail -300
```

---

## Что проверить по ORB state machine

Для последнего торгового дня проверить переходы:

```text
WAITING_FOR_OR_START
→ BUILDING_OPENING_RANGE
→ WAITING_FOR_BREAKOUT
→ IN_TRADE, если был пробой
→ DONE_FOR_DAY
```

Нужно явно ответить:

```text
1. В какое время сервис перешёл в BUILDING_OPENING_RANGE?
2. Сколько свечей попало в OR 10:00–11:00?
3. Какие OR high / OR low?
4. В какое время OR был зафиксирован?
5. Был ли breakout ниже OR low?
6. Если breakout был:
   - entry timestamp;
   - entry price;
   - stop price;
   - take price;
   - risk points;
   - take distance;
   - exit timestamp;
   - exit price;
   - exit reason;
   - pnl_points;
   - pnl_rub;
   - bars held.
7. Если breakout не был:
   - был ли день DONE_FOR_DAY;
   - почему сделки нет;
   - было ли корректное no-trade состояние.
8. Не было ли больше одной сделки за день.
9. Не было ли overnight/open trade после 18:40.
```

---

## Что проверить в SQLite

Посмотреть таблицы ORB DB:

```bash
sqlite3 data/paper/paper_state_orb.sqlite ".tables"
```

Проверить daily state:

```bash
sqlite3 -header -column data/paper/paper_state_orb.sqlite "
SELECT *
FROM orb_daily_state
ORDER BY date_msk DESC
LIMIT 5;
"
```

Проверить trades:

```bash
sqlite3 -header -column data/paper/paper_state_orb.sqlite "
SELECT
  trade_id,
  strategy_name,
  experiment_name,
  ticker,
  direction,
  entry_timestamp,
  entry_price,
  or_high,
  or_low,
  stop_price,
  take_price,
  exit_timestamp,
  exit_price,
  exit_reason,
  pnl_points,
  pnl_rub,
  bars_held,
  status
FROM orb_paper_trades
ORDER BY entry_timestamp DESC
LIMIT 10;
"
```

Если названия таблиц отличаются — адаптировать команды и указать реальные названия.

---

## Что проверить в CSV

```bash
ls -lah out/paper/paper_trades_SiM6_ORB.csv
tail -20 out/paper/paper_trades_SiM6_ORB.csv
```

Проверить:

```text
- CSV существует;
- строки соответствуют DB;
- нет дублей;
- нет смешивания с hammer trades;
- поля entry/exit/status выглядят корректно.
```

---

## Что проверить в status JSON

```bash
cat runtime/paper_status_SiM6_ORB.json
```

Нужно проверить:

```text
strategy = opening_range_breakout
experiment_name = orb_or60_short2r
ticker = SiM6
direction = SHORT
opening_range = 10:00–11:00
take_r = 2.0
orders_enabled = false
paper_only = true
trading_liveness_status = OK / MARKET_CLOSED depending time
consecutive_api_errors = 0 or explain if not
day_state корректен
or_high / or_low корректны после 11:00
open_trades корректен
closed_trades_total корректен
last_successful_fetch_at корректен в торговую сессию
```

---

## Что проверить по real/sandbox orders

Нужно подтвердить:

```text
orders_enabled = false
нет кода/логов отправки реальных заявок
нет sandbox orders
нет попыток выставить order через T-Bank API
```

По логам убедиться, что нет строк вида:

```text
POST order
send_order
sandbox_order
real_order
orders_service
```

Если есть похожие строки — объяснить контекст.

---

## Что проверить по трём сервисам вместе

Сформировать мини-сводку:

```text
Service              Status   Liveness   Last fetch   Trades total   Net PnL   Open trades
hammer-baseline      ...
hammer-maxhold5      ...
orb-paper            ...
```

Важно:

```text
Не сравнивать прибыльность ORB с hammer по одному дню.
ORB только начал сбор live paper данных.
```

---

## Отчёт

Создать Markdown-отчёт:

```text
reports/orb_first_trading_day_validation_YYYYMMDD.md
reports/orb_first_trading_day_validation_latest.md
```

Структура:

```markdown
# ORB First Trading Day Validation

## Цель

## Краткий вывод

## Service health

## ORB state machine

## Opening range 10:00–11:00

## Breakout / no breakout

## Trade details, if any

## DB / CSV / Status validation

## Logs validation

## Orders safety check

## Multi-service summary

## Issues found

## Recommendation
```

---

## Возможные выводы

## OK

Если:

```text
ORB корректно построил OR;
state machine корректна;
если была сделка — она корректна;
если сделки не было — no-trade корректен;
DB/CSV/status/log в порядке;
orders disabled;
liveness OK.
```

Рекомендация:

```text
Continue collecting ORB paper data.
```

## OK_WITH_MINOR_ISSUES

Если:

```text
торговая логика корректна,
но есть мелкие проблемы в отображении статуса/diagnostics/log labels.
```

Рекомендация:

```text
Fix diagnostics/reporting only, do not change strategy.
```

## NEEDS_FIX

Если:

```text
ORB неправильно строит OR;
открывает сделку до 11:00;
открывает больше одной сделки;
не закрывает по time_exit;
путает stop/take;
пишет в неправильную DB;
orders_enabled не false.
```

Рекомендация:

```text
Stop ORB service if needed, fix bug, do smoke test, restart.
Do not touch hammer services.
```

---

## Acceptance Criteria

Задача выполнена, если:

1. Проверены все три systemd-сервиса.
2. Проверен `check_all_paper_status.py`.
3. Проверен ORB status JSON.
4. Проверен ORB DB.
5. Проверен ORB CSV.
6. Проверен ORB log/journal.
7. Проверена state machine ORB за торговый день.
8. Проверен opening range 10:00–11:00.
9. Проверен breakout/no breakout.
10. Если была сделка — проверены entry/stop/take/exit/PnL.
11. Подтверждено, что orders disabled.
12. Создан Markdown-отчёт.
13. Дана рекомендация: OK / OK_WITH_MINOR_ISSUES / NEEDS_FIX.
14. Hammer-сервисы не изменены.

---

## Финальный формат ответа Claude

```markdown
## ORB First Trading Day Validation — готово

### Краткий вывод

### Service health

### ORB opening range

### ORB state machine

### Breakout / trade result

### DB / CSV / Status

### Logs

### Orders safety

### Multi-service summary

### Issues found

### Артефакты

### Рекомендация
```
