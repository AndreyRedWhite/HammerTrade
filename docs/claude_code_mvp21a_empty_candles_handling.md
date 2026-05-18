# Claude Code Prompt — MVP-2.1a: T-Bank Empty Candles / `No columns to parse from file` Hardening

## Контекст проекта

Проект: `HammerTrade / MOEXF`.

Это исследовательский trading/paper-trading бот для MOEX futures.

Текущий основной инструмент:

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
Baseline service: hammertrade-paper.service
Maxhold5 service: hammertrade-paper-maxhold5.service
Baseline DB: data/paper/paper_state.sqlite
Maxhold5 DB: data/paper/paper_state_maxhold5.sqlite
Baseline status file: runtime/paper_status_SiM6_SELL.json
Maxhold5 status file: runtime/paper_status_SiM6_SELL_maxhold5.json
```

Важно: сейчас идёт A/B paper experiment:

```text
A: baseline без max_hold_bars
B: maxhold5 с max_hold_bars=5
```

Оба сервиса живые. Эксперимент не трогать.

---

## Что уже сделано

## MVP-1.7 — Paper trading daemon

```text
data/paper/paper_state.sqlite
out/paper/paper_trades_SiM6_SELL.csv
scripts/run_paper_trader.py
scripts/paper_report.py
src/paper/engine.py
src/paper/repository.py
src/paper/report.py
```

## MVP-1.8 — Operational Safety Layer

```text
configs/market_hours/moex_futures.yaml
src/market/market_hours.py
scripts/check_paper_status.py
runtime/paper_status_SiM6_SELL.json
docs/paper_trader_operational.md
```

## MVP-1.9 — Paper Trading Diagnostics

```text
src/paper/diagnostics.py
scripts/paper_diagnostics.py
tests/test_paper_diagnostics.py
docs/paper_trader_diagnostics.md
```

## MVP-2.0 — Backtest Diagnostic Filters

```text
src/backtest/diagnostic_filters.py
src/backtest/diagnostic_grid.py
scripts/backtest_diagnostic_filters.py
configs/backtest_diagnostic_filters_sim6_sell.yaml
tests/test_backtest_diagnostic_filters.py
docs/backtest_diagnostic_filters.md
```

## MVP-2.0a — Audit `max_hold_bars`

```text
src/backtest/max_hold_audit.py
scripts/audit_max_hold_bars.py
tests/test_max_hold_audit.py
docs/max_hold_bars_audit.md
```

Audit result:

```text
Look-ahead audit: PASS
Exit priority audit: PASS
Paper readiness: READY_WITH_WARNINGS
Verdict: PASS_WITH_WARNINGS
```

## MVP-2.1 — Parallel Paper maxhold5 Experiment

Создан и запущен второй сервис:

```text
hammertrade-paper-maxhold5.service
```

Maxhold5 paths:

```text
data/paper/paper_state_maxhold5.sqlite
runtime/paper_status_SiM6_SELL_maxhold5.json
out/paper/paper_trades_SiM6_SELL_maxhold5.csv
logs/paper_SiM6_SELL_maxhold5.log
```

Создан:

```text
scripts/compare_paper_experiments.py
tests/test_paper_max_hold.py
```

---

## Текущий статус A/B эксперимента

Claude собрал статистику за период 2026-05-13 — 2026-05-18.

Оба сервиса живые:

```text
hammertrade-paper: active, last cycle ~13 sec ago
hammertrade-paper-maxhold5: active, last cycle ~13 sec ago
```

Оба сейчас:

```text
IDLE
open positions: 0
pending signal: 0
market: OPEN
```

Справедливое сравнение с 2026-05-13:

```text
baseline за 13–15 мая:
  10 сделок
  net = -420 RUB

maxhold5 за 13–15 мая:
  11 сделок
  net = +249 RUB
```

Общий maxhold5:

```text
closed trades: 11
PF: 1.42
expectancy: +22.7 RUB
worst trade: -230 RUB
MAX_HOLD_EXIT: 3
MAX_HOLD_EXIT net: +229 RUB
```

Baseline:

```text
closed trades: 40
PF: 1.15
expectancy: +12.5 RUB
worst trade: -580 RUB
ONE_BAR_STOP: 7 trades, -1150 RUB
```

Вывод по стратегии:

```text
A/B эксперимент идёт корректно.
maxhold5 пока выглядит лучше, но выборка маленькая.
Торговую логику сейчас не менять.
```

---

## Почему нужен MVP-2.1a

В логах/статусах появились повторяющиеся ошибки:

```text
API_ERROR: No columns to parse from file
```

По свежей статистике:

```text
baseline: 17 раз
maxhold5: 28 раз
API_TIMEOUT: baseline 5 раз, maxhold5 3 раза
STALE_CANDLES: baseline 9 раз, maxhold5 1 раз
NO_CANDLES_DURING_OPEN_SESSION session=weekend: много, суббота 17 мая, это нормально
```

`No columns to parse from file` предположительно возникает, когда T-Bank API или промежуточный CSV/parser получает пустой ответ / пустой набор свечей.

Сервисы самовосстанавливаются, но частота растёт. Это уже operational-риск.

Особенно важно для maxhold5:

```text
bars_held должен увеличиваться только по валидным торговым свечам.
Пустой ответ API не должен увеличивать bars_held.
Пустой ответ API не должен закрывать сделку по MAX_HOLD_EXIT.
Пустой ответ API не должен создавать ложный сигнал.
```

---

## Главная цель MVP-2.1a

Сделать безопасную обработку пустых ответов свечей / пустого CSV / `No columns to parse from file`.

Нужно:

1. Найти источник ошибки.
2. Отличить пустой ответ API от настоящей ошибки парсинга.
3. Не считать пустой ответ валидной свечой.
4. Не увеличивать `bars_held`.
5. Не закрывать сделки.
6. Не создавать сигналы.
7. Не ломать цикл daemon.
8. Добавить понятные счётчики в status file.
9. Добавить диагностику/отчёт по таким инцидентам.
10. Не трогать торговую стратегию и параметры A/B.

---

## Жёсткие ограничения

Строго запрещено:

- менять entry logic;
- менять exit logic, кроме безопасной обработки отсутствия данных;
- менять `max_hold_bars=5`;
- менять `hammertrade-paper.service` unit;
- менять `hammertrade-paper-maxhold5.service` unit без необходимости;
- останавливать оба сервиса одновременно без необходимости;
- менять production `.env`;
- печатать токены;
- запускать real trading;
- запускать sandbox orders;
- удалять SQLite/CSV/reports;
- сбрасывать state DB;
- менять detector;
- менять backtest;
- менять historical reports;
- делать новые торговые фильтры;
- делать выводы о прибыльности стратегии.

Разрешено:

- исправить обработку пустого ответа API;
- добавить typed exception/status для empty candles response;
- добавить counters в status file;
- добавить logs;
- добавить tests;
- добавить diagnostics script;
- перезапустить сервисы по одному, если нужно;
- добавить документацию;
- улучшить `check_paper_status.py`, если это backward-compatible.

---

## Что изучить перед реализацией

Найти место, где возникает:

```text
No columns to parse from file
```

Команды:

```bash
cd /opt/hammertrade

grep -R "read_csv" -n src scripts | head -100
grep -R "No columns" -n . | head -100
grep -R "candles" -n src scripts | head -120
grep -R "TINKOFF\\|T-Bank\\|tbank\\|invest" -n src scripts | head -120
```

Изучить:

```text
scripts/run_paper_trader.py
src/paper/engine.py
src/paper/repository.py
src/market/market_hours.py
scripts/check_paper_status.py
```

Также найти модуль загрузки свечей из T-Bank API, ориентировочно:

```text
src/data/
src/tbank/
src/market/
scripts/load_*.py
```

Понять:

1. Где вызывается T-Bank Invest API.
2. Где ответ превращается в DataFrame.
3. Где используется `pandas.read_csv`.
4. Почему пустой ответ превращается в `No columns to parse from file`.
5. Что происходит после exception:
   - цикл продолжается?
   - status file обновляется?
   - consecutive errors растут?
   - bars_held меняется?
   - сделки проверяются на exit?
6. Есть ли разные code paths у baseline и maxhold5.
7. Почему maxhold5 ловит больше таких ошибок, чем baseline.
8. Может ли параллельный запуск двух сервисов увеличить частоту API empty responses.
9. Есть ли rate limit / connection / timeout / CA issue.

---

## Термины и статусы

Добавить отдельный статус/тип ошибки для пустого ответа:

```text
EMPTY_CANDLES_RESPONSE
```

Рекомендуемое название:

```text
EMPTY_CANDLES_RESPONSE
```

Не смешивать с:

```text
API_TIMEOUT
API_ERROR
STALE_CANDLES
MARKET_CLOSED
NO_CANDLES_DURING_OPEN_SESSION
```

`No columns to parse from file` не должен оставаться только сырым текстом pandas.

Нужно классифицировать:

```text
pandas.errors.EmptyDataError: No columns to parse from file
```

как:

```text
EMPTY_CANDLES_RESPONSE
```

если это именно пустой CSV / пустой ответ.

---

## Expected behavior

Если получен пустой ответ свечей:

```text
1. Не создавать candle.
2. Не обновлять last candle timestamp как будто свеча получена.
3. Не вызывать detector на пустом наборе.
4. Не создавать signal.
5. Не проверять новую свечу для exit.
6. Не увеличивать bars_held.
7. Не закрывать open trade.
8. Обновить status file:
   - last_fetch_status = EMPTY_CANDLES_RESPONSE
   - empty_response_count += 1
   - consecutive_empty_responses += 1
   - last_empty_response_at = now
   - last_error_message = normalized short message
9. Записать log warning.
10. Перейти к следующему циклу.
```

Если следующий цикл успешный:

```text
1. last_fetch_status = OK
2. consecutive_empty_responses = 0
3. empty_response_count сохраняется накопительным
4. last_empty_response_at сохраняется как последний факт
```

Если подряд слишком много пустых ответов:

```text
consecutive_empty_responses >= 3
```

status может быть:

```text
DEGRADED_EMPTY_RESPONSES
```

или оставить:

```text
EMPTY_CANDLES_RESPONSE
```

но добавить:

```text
health = DEGRADED
```

Если в проекте уже есть health/status convention — использовать её.

---

## Status file additions

Добавить backward-compatible поля в status JSON:

```json
{
  "empty_response_count": 0,
  "consecutive_empty_responses": 0,
  "last_empty_response_at": null,
  "last_empty_response_message": null,
  "last_fetch_status": "OK",
  "last_successful_fetch_at": "...",
  "consecutive_api_errors": 0
}
```

Важно:

- старые поля не удалять;
- `check_paper_status.py` не должен ломаться;
- diagnostics не должны ломаться;
- baseline и maxhold5 status files должны обновляться одинаково.

---

## Logging

Логировать пустой ответ как warning, но без stack trace при каждом обычном empty response.

Пример:

```text
[baseline] EMPTY_CANDLES_RESPONSE ticker=SiM6 timeframe=1m consecutive=1 total=18 message="No columns to parse from file"
[maxhold5] EMPTY_CANDLES_RESPONSE ticker=SiM6 timeframe=1m consecutive=1 total=29 message="No columns to parse from file"
```

Если `consecutive_empty_responses >= 3`, логировать:

```text
DEGRADED_EMPTY_RESPONSES consecutive=3
```

Не спамить однотипными длинными tracebacks.

---

## Interaction with `bars_held` and `MAX_HOLD_EXIT`

Это критично.

Добавить/проверить тест:

```text
Если open trade есть и пришёл EMPTY_CANDLES_RESPONSE:
- bars_held не увеличился;
- exit_reason не изменился;
- trade остался OPEN;
- MAX_HOLD_EXIT не сработал.
```

Для baseline:

```text
EMPTY_CANDLES_RESPONSE не должен влиять на STOP/TAKE.
```

Для maxhold5:

```text
EMPTY_CANDLES_RESPONSE не должен приближать max_hold_bars.
```

---

## Interaction with market hours

Важно различать:

```text
MARKET_CLOSED
NO_CANDLES_DURING_OPEN_SESSION session=weekend
EMPTY_CANDLES_RESPONSE
STALE_CANDLES
```

Если рынок закрыт по market hours:

```text
MARKET_CLOSED
```

это не ошибка empty response.

Если рынок открыт, но API дал пустой ответ:

```text
EMPTY_CANDLES_RESPONSE
```

Если weekend/holiday и market hours config правильно говорит closed:

```text
MARKET_CLOSED
```

Если market hours говорит open, но свечей нет:

```text
NO_CANDLES_DURING_OPEN_SESSION
```

Если ответ пустой технически / CSV пустой:

```text
EMPTY_CANDLES_RESPONSE
```

Нужно не смешать эти случаи.

---

## Rate limit / parallel services hypothesis

Поскольку теперь работают два daemon:

```text
baseline
maxhold5
```

нужно проверить, не усиливает ли это частоту пустых ответов.

В отчёте дать наблюдение:

1. Есть ли empty responses у обоих сервисов в одно и то же время?
2. Чаще ли maxhold5 ловит empty responses из-за другого timing/cycle?
3. Есть ли признаки rate limit?
4. Есть ли смысл в будущем делать shared candle fetcher/cache, чтобы оба paper experiments читали одни свечи из локального cache?

Не реализовывать shared fetcher в MVP-2.1a, только оценить.

---

## Optional diagnostics script

Желательно добавить скрипт:

```text
scripts/paper_error_report.py
```

Он должен читать:

```text
runtime/paper_status_SiM6_SELL.json
runtime/paper_status_SiM6_SELL_maxhold5.json
```

и выводить краткую сводку:

```text
Paper Error Report

baseline:
  empty_response_count:
  consecutive_empty_responses:
  api_timeout_count:
  stale_candles_count:
  last_empty_response_at:
  last_fetch_status:

maxhold5:
  ...
```

Если логи парсить сложно — достаточно status files.

CLI:

```bash
python scripts/paper_error_report.py
```

или:

```bash
python scripts/paper_error_report.py \
  --status-files runtime/paper_status_SiM6_SELL.json runtime/paper_status_SiM6_SELL_maxhold5.json
```

---

## Documentation

Добавить документ:

```text
docs/paper_empty_candles_handling.md
```

Содержание:

```markdown
# Empty candles handling

## Problem

## Symptoms

## Status values

## Expected daemon behavior

## Impact on bars_held

## Impact on max_hold_bars

## How to check status

## When to worry

## Future improvement: shared candle fetch/cache
```

---

## Tests

Добавить тесты:

```text
tests/test_empty_candles_handling.py
```

Минимум:

1. `pandas.errors.EmptyDataError` классифицируется как `EMPTY_CANDLES_RESPONSE`.
2. Пустой DataFrame / пустой список свечей классифицируется как `EMPTY_CANDLES_RESPONSE`.
3. Empty response не создаёт сигнал.
4. Empty response не обновляет last candle timestamp.
5. Empty response не увеличивает `bars_held`.
6. Empty response не закрывает open trade.
7. Empty response не вызывает `MAX_HOLD_EXIT`.
8. После successful fetch `consecutive_empty_responses` сбрасывается в 0.
9. `empty_response_count` накапливается.
10. Status JSON backward-compatible.
11. `check_paper_status.py` не падает на новых полях.
12. `paper_error_report.py` не падает при отсутствующем status file.
13. `paper_error_report.py` корректно отображает baseline/maxhold5.

Если сложно unit-тестировать весь daemon, добавить тесты на изолированные функции обработки fetch result/status update.

---

## Safe rollout

Если меняется код daemon, перезапускать сервисы по одному.

Рекомендуемый порядок:

```bash
cd /opt/hammertrade

sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager

sudo systemctl restart hammertrade-paper-maxhold5
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
cat runtime/paper_status_SiM6_SELL_maxhold5.json

sudo systemctl restart hammertrade-paper
sudo systemctl status hammertrade-paper --no-pager
cat runtime/paper_status_SiM6_SELL.json
```

Важно:

```text
Не останавливать оба сервиса одновременно надолго.
Не удалять DB.
Не сбрасывать state.
```

---

## Post-rollout checks

После перезапуска:

```bash
journalctl -u hammertrade-paper-maxhold5 -n 100 --no-pager
journalctl -u hammertrade-paper -n 100 --no-pager
```

Проверить, что:

```text
- оба сервиса active;
- status files пишутся;
- last_fetch_status обновляется;
- no stack trace spam;
- при empty response логируется EMPTY_CANDLES_RESPONSE;
- если fetch OK, consecutive_empty_responses сбрасывается;
- maxhold5 сохраняет max_hold_bars=5;
- baseline сохраняет max_hold_bars=None.
```

---

## Acceptance Criteria

MVP-2.1a считается готовым, если:

1. Найден источник `No columns to parse from file`.
2. `pandas.errors.EmptyDataError` / пустой ответ классифицируется как `EMPTY_CANDLES_RESPONSE`.
3. Empty response не считается валидной свечой.
4. Empty response не увеличивает `bars_held`.
5. Empty response не закрывает сделку.
6. Empty response не создаёт сигнал.
7. Empty response не вызывает `MAX_HOLD_EXIT`.
8. Status file содержит:
   - `empty_response_count`;
   - `consecutive_empty_responses`;
   - `last_empty_response_at`;
   - `last_empty_response_message`.
9. После успешного fetch `consecutive_empty_responses` сбрасывается.
10. Логи не спамят traceback для обычного empty response.
11. Есть tests/smoke checks.
12. Есть документация.
13. Желательно: есть `scripts/paper_error_report.py`.
14. Baseline service работает после изменений.
15. Maxhold5 service работает после изменений.
16. Baseline остаётся `max_hold_bars=None`.
17. Maxhold5 остаётся `max_hold_bars=5`.
18. A/B experiment не сброшен и не испорчен.
19. Claude Code в финальном ответе указал:
    - что было причиной;
    - какие файлы изменены;
    - какие статусы добавлены;
    - какие тесты прошли;
    - статус обоих сервисов;
    - что делать дальше.

---

## Что НЕ делать в MVP-2.1a

Не менять стратегию.

Не менять:

```text
max_hold_bars=5
entry rules
stop/take rules
detector params
backtest params
systemd units, если не требуется
```

Не отключать A/B.

Не удалять базы.

Не менять формат таблицы `paper_trades`, если не нужно.

Не делать shared candle fetch/cache.

Не делать retry storm.

Не делать бесконечные retries внутри одного цикла.

Не делать выводов о прибыльности.

---

## Future improvement, но НЕ в этом MVP

Если подтвердится, что два daemon провоцируют больше пустых ответов, в будущем можно сделать:

```text
MVP-2.2: shared candle fetch/cache
```

Идея:

```text
один fetcher получает свечи от T-Bank;
пишет локальный cache;
baseline и maxhold5 читают из cache;
меньше API calls;
честнее A/B;
меньше расхождений по пустым ответам.
```

Но в MVP-2.1a это только описать как возможное улучшение, не реализовывать.

---

## Финальный формат ответа Claude Code

После выполнения задачи ответить так:

```markdown
## MVP-2.1a Empty Candles Handling — готово

### Что было причиной

### Что сделано

### Созданные файлы

### Изменённые файлы

### Новые status fields

### Поведение при EMPTY_CANDLES_RESPONSE

### Влияние на bars_held / MAX_HOLD_EXIT

### Как проверить

### Статус baseline service

### Статус maxhold5 service

### Tests / smoke checks

### Артефакты / docs

### Warnings / limitations

### Что делать дальше
```
