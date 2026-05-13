# Claude Code Prompt — Weekly Paper Trading Report: SiM6 SELL

## Контекст

Проект: `HammerTrade / MOEXF`

Это исследовательский trading/paper-trading бот для MOEX futures.

Текущий основной режим:

```text
Ticker: SiM6
Class code: SPBFUT
Timeframe: 1m
Profile: balanced
Direction filter: SELL
Mode: paper only
Orders: disabled
```

Проект работает на сервере Yandex Cloud:

```text
Server: 158.160.204.201
User: vorontsov
Project path: /opt/hammertrade
Virtualenv: /opt/hammertrade/.venv
Systemd service: hammertrade-paper.service
State DB: /opt/hammertrade/data/paper/paper_state.sqlite
Status file: /opt/hammertrade/runtime/paper_status_SiM6_SELL.json
```

В предыдущих MVP уже реализовано:

## MVP-1.7

Paper trading daemon.

Основные артефакты:

```text
data/paper/paper_state.sqlite
out/paper/paper_trades_SiM6_SELL.csv
scripts/paper_report.py
src/paper/report.py
```

Основная таблица:

```text
paper_trades
```

## MVP-1.8

Operational Safety Layer.

Основные артефакты:

```text
configs/market_hours/moex_futures.yaml
src/market/market_hours.py
scripts/check_paper_status.py
runtime/paper_status_SiM6_SELL.json
docs/paper_trader_operational.md
```

## MVP-1.9

Paper Trading Diagnostics.

Основные артефакты:

```text
src/paper/diagnostics.py
scripts/paper_diagnostics.py
tests/test_paper_diagnostics.py
docs/paper_trader_diagnostics.md
```

Диагностика генерирует:

```text
reports/paper_diagnostics_SiM6_SELL_latest.md
out/paper/paper_trades_diagnostics_SiM6_SELL_latest.csv
```

---

## Задача

Прошла примерно неделя paper trading.

Нужно собрать свежую статистику по текущему paper trader, не меняя код стратегии.

Твоя задача:

1. Подключиться к серверу.
2. Проверить, что сервис `hammertrade-paper.service` жив.
3. Проверить status file.
4. Запустить существующую диагностику `scripts/paper_diagnostics.py`.
5. Собрать недельную статистику по накопленным сделкам.
6. Вывести человеку понятный отчёт:
   - в терминале;
   - по возможности сохранить/обновить Markdown-отчёт через существующий скрипт.
7. Дать выводы:
   - что хорошо;
   - что плохо;
   - какие диагностические флаги проявились;
   - какие гипотезы стали сильнее/слабее;
   - стоит ли продолжать paper trading без изменений;
   - какой следующий MVP логичнее делать.

Важно: это операционный анализ, а не разработка нового функционала.

---

## Жёсткие ограничения

Строго запрещено:

- менять торговую логику;
- менять параметры стратегии;
- менять detector;
- менять backtest;
- менять paper trader;
- менять systemd unit;
- останавливать сервис без явной необходимости;
- удалять SQLite/CSV/Markdown-отчёты;
- запускать real trading;
- запускать sandbox orders;
- вызывать broker execution;
- печатать `.env`;
- печатать токены;
- коммитить секреты.

Разрешено:

- выполнять read-only команды;
- запускать `scripts/paper_diagnostics.py`;
- запускать `scripts/paper_report.py`, если полезно;
- читать SQLite через `sqlite3`;
- читать CSV/Markdown-отчёты;
- проверять systemd status;
- проверять logs без изменения сервиса;
- создавать новый Markdown-файл с недельным summary, если это удобно.

---

## Команды проверки

Выполни на сервере:

```bash
ssh -l vorontsov 158.160.204.201
```

Далее:

```bash
cd /opt/hammertrade
pwd
git status --short
```

Проверить сервис:

```bash
sudo systemctl status hammertrade-paper --no-pager
journalctl -u hammertrade-paper -n 80 --no-pager
```

Проверить status file:

```bash
cat runtime/paper_status_SiM6_SELL.json
```

Если есть скрипт проверки статуса:

```bash
.venv/bin/python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json
```

Запустить диагностику:

```bash
.venv/bin/python scripts/paper_diagnostics.py
```

Посмотреть свежие отчёты:

```bash
ls -lah reports | grep paper_diagnostics | tail -10
ls -lah out/paper | grep paper_trades_diagnostics | tail -10
```

Показать latest Markdown:

```bash
sed -n '1,260p' reports/paper_diagnostics_SiM6_SELL_latest.md
```

Если отчёт длиннее, дополнительно показать ключевые секции:

```bash
grep -n "## " reports/paper_diagnostics_SiM6_SELL_latest.md
```

---

## Дополнительные SQLite проверки

Если нужно уточнить статистику напрямую из базы, выполнить:

```bash
sqlite3 data/paper/paper_state.sqlite ".tables"
sqlite3 data/paper/paper_state.sqlite ".schema paper_trades"
```

Количество сделок:

```bash
sqlite3 data/paper/paper_state.sqlite "
SELECT
  COUNT(*) AS total,
  SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) AS closed,
  SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) AS open
FROM paper_trades;
"
```

Сводка по exit_reason:

```bash
sqlite3 data/paper/paper_state.sqlite "
SELECT
  COALESCE(exit_reason, status) AS reason,
  COUNT(*) AS trades,
  ROUND(SUM(COALESCE(pnl_rub, 0)), 2) AS pnl_rub
FROM paper_trades
GROUP BY COALESCE(exit_reason, status)
ORDER BY trades DESC;
"
```

Сводка по дням:

```bash
sqlite3 data/paper/paper_state.sqlite "
SELECT
  substr(entry_timestamp, 1, 10) AS day,
  COUNT(*) AS trades,
  SUM(CASE WHEN pnl_rub > 0 THEN 1 ELSE 0 END) AS wins,
  SUM(CASE WHEN pnl_rub < 0 THEN 1 ELSE 0 END) AS losses,
  ROUND(SUM(COALESCE(pnl_rub, 0)), 2) AS net_pnl_rub
FROM paper_trades
WHERE status = 'CLOSED'
GROUP BY substr(entry_timestamp, 1, 10)
ORDER BY day;
"
```

Последние 20 сделок:

```bash
sqlite3 -header -column data/paper/paper_state.sqlite "
SELECT
  entry_timestamp,
  direction,
  entry_price,
  stop_price,
  take_price,
  exit_price,
  exit_reason,
  ROUND(pnl_rub, 2) AS pnl_rub,
  bars_held
FROM paper_trades
ORDER BY entry_timestamp DESC
LIMIT 20;
"
```

---

## Что нужно извлечь из diagnostics report

Из `reports/paper_diagnostics_SiM6_SELL_latest.md` нужно внимательно посмотреть:

```text
Общая статистика
Статистика по дням
Статистика по часам входа
Статистика по exit_reason
Risk buckets
Reward buckets
R/R buckets
Bars held buckets
Diagnostic flags
Подозрительные сделки
Лучшие сделки
Худшие сделки
Предварительные гипотезы фильтров
Warnings
```

Особенно обратить внимание на:

```text
total_trades
closed_trades
open_trades
winrate_pct
gross_profit_rub
gross_loss_rub
net_pnl_rub
profit_factor
expectancy_rub
best_trade_rub
worst_trade_rub
avg_risk_points
avg_reward_points
avg_rr
avg_bars_held
```

---

## Что нужно проверить по гипотезам MVP-1.9

Сравнить свежий недельный результат с предыдущим срезом.

Предыдущий срез после MVP-1.9:

```text
Trades: 17
Winrate: 70.6%
Net PnL: +1049.15 RUB
Profit Factor: 1.79
Warnings: 0
```

Предыдущие наблюдения:

```text
ONE_BAR_STOP — 3 стопа на первом баре
TINY_TAKE reward < 5 pt — net PnL около -30 RUB
BIG_RISK — суммарно в плюсе около +560 RUB, но включает worst trade
12 МСК — 2 стопа подряд, net около -870 RUB
10 МСК — лучший час, около +1140 RUB
```

Нужно ответить:

1. Увеличился или ухудшился общий результат?
2. Вырос ли Profit Factor?
3. Сохранился ли положительный expectancy?
4. Стали ли `ONE_BAR_STOP` хуже?
5. Остался ли `TINY_TAKE` убыточным?
6. Остался ли `BIG_RISK` спорным, но прибыльным?
7. Подтвердился ли плохой час `12 МСК`?
8. Подтвердился ли хороший час `10 МСК`?
9. Появились ли новые слабые часы?
10. Есть ли открытая сделка?
11. Есть ли warnings?
12. Есть ли признаки, что стратегия деградировала?
13. Есть ли признаки, что она просто попала в один удачный трендовый день?

---

## Недельный отчёт в ответе

В финальном ответе дай отчёт в таком формате:

```markdown
## Weekly Paper Trading Report — SiM6 SELL

### 1. Статус сервиса

- service status:
- uptime:
- last_fetch_status:
- market_status:
- API errors:
- crashes/restarts:

### 2. Файлы отчётов

- diagnostics markdown:
- enriched csv:
- status file:

### 3. Общая статистика

| Метрика | Значение |
|---|---:|
| Total trades | |
| Closed trades | |
| Open trades | |
| TAKE | |
| STOP | |
| Winrate | |
| Gross profit | |
| Gross loss | |
| Net PnL | |
| Profit Factor | |
| Expectancy | |
| Best trade | |
| Worst trade | |

### 4. Динамика относительно прошлого среза

| Метрика | Было | Стало | Вывод |
|---|---:|---:|---|
| Trades | 17 | | |
| Winrate | 70.6% | | |
| Net PnL | +1049.15 RUB | | |
| Profit Factor | 1.79 | | |

### 5. По дням

Краткая таблица по дням.

### 6. По часам

Отметить лучшие и худшие часы.

### 7. Diagnostic flags

Краткая таблица по флагам:

| Flag | Trades | Net PnL | Вывод |
|---|---:|---:|---|

### 8. Лучшие сделки

Top 5.

### 9. Худшие сделки

Worst 5.

### 10. Гипотезы

Разделить на:

#### Усилились

#### Ослабли

#### Пока рано судить

### 11. Рекомендация

Один из вариантов:

- продолжать paper trading без изменений;
- делать MVP-2.0 с backtest diagnostic filters;
- сначала накопить ещё неделю;
- срочно проверить конкретную проблему.

### 12. Следующий шаг

Предложить конкретный следующий MVP.
```

---

## Важная интерпретация

Не делай вывод “стратегия доказана”, даже если результат хороший.

Корректная формулировка:

```text
Paper trading показывает положительную динамику, но выборка всё ещё мала. Результат можно использовать для выбора гипотез и последующего historical validation, но не как основание для live trading.
```

Если результат ухудшился, тоже не делать драматичных выводов.

Корректная формулировка:

```text
Недельный срез ухудшился/просел, но этого недостаточно для окончательного вывода. Нужно смотреть распределение по флагам, risk/reward и рыночному контексту.
```

---

## Финальный формат ответа

В конце обязательно написать:

```markdown
## Итог

- Сервис:
- Сделки:
- PnL:
- PF:
- Главный риск:
- Главная гипотеза:
- Рекомендация:
```
