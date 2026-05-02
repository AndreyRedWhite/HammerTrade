# HammerTrade: Operational Safety Layer v1 для paper trader

## Контекст

Ты работаешь в проекте HammerTrade.

Это исследовательский paper-trading бот для фьючерсов MOEX / MOEXF. Реальная торговля сейчас не нужна и запрещена. На текущем этапе цель — безопасно гонять стратегию в live paper-mode, собирать статистику и проверять поведение стратегии на реальных рыночных данных без выставления реальных заявок.

Текущий рабочий сценарий:

```bash
cd /opt/hammertrade

/opt/hammertrade/.venv/bin/python scripts/run_paper_trader.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --timeframe 1m \
  --profile balanced \
  --direction-filter SELL \
  --env prod
```

Также уже настроен systemd-сервис:

```bash
sudo systemctl status hammertrade-paper
journalctl -u hammertrade-paper -n 100 --no-pager
```

Сервис уже проверен:
- стартует через systemd;
- включён в автозапуск;
- переживает `sudo reboot`;
- после перезагрузки автоматически поднимается;
- работает в paper-mode;
- реальных заявок не выставляет.

В логах сейчас видно, что в выходной день бот продолжает каждые 20 секунд ходить за свечами:

```text
Fetching 300 candles for SiM6 1m...
No candles returned, skipping cycle.
```

Это ожидаемо для выходного дня, но для автономного paper-демона такое поведение плохое: бот не отличает закрытый рынок от проблем API, stale data, неактивного инструмента или ошибки получения данных.

## Что показало ревью

Ревью кодовой базы выявило такие важные пробелы:

1. Нет market hours guard.
2. Нет явного таймаута на API-вызов получения свечей.
3. Нет нормальной диагностики причины пропуска цикла.
4. Нет status-файла для быстрой проверки состояния демона.
5. Нет нормального operational health-check.
6. Potential issue: pending signal после рестарта может быть обработан некорректно.
7. Potential issue: транзакционная граница fetch → detect → persist → update state требует проверки.
8. Некоторые skip-причины в paper-mode логируются недостаточно явно.

Сейчас нужно реализовать только первый безопасный слой эксплуатационной надёжности.

## Главная цель задачи

Добавить Operational Safety Layer v1 для paper trader:

1. Конфигурируемое расписание торгов MOEX futures.
2. Market hours guard перед запросом свечей.
3. Таймаут на API-запрос свечей.
4. Stale candle guard.
5. JSON status-файл по состоянию paper trader-а.
6. Более понятные логи причин пропуска цикла.
7. Набор тестов.
8. Команды проверки для пользователя.

Важно: не пытайся сразу чинить всё из ревью. Не надо переписывать архитектуру. Нужен аккуратный минимально-инвазивный патч.

## Жёсткие ограничения

- Не добавлять real trading.
- Не вызывать методы выставления заявок.
- Не добавлять работу с реальными ордерами.
- Не менять стратегическую логику detector / backtest без необходимости.
- Не ломать существующие CLI-команды.
- Не ломать существующие тесты.
- Не удалять текущие логи.
- Не менять формат существующих CSV/SQLite без необходимости.
- Если нужно новое поведение — добавляй его расширением, а не ломкой старого.
- Все новые параметры должны иметь разумные дефолты.
- Все новые изменения должны быть покрыты тестами.

## Важное замечание по расписанию MOEX

Не хардкодить старую схему вида:

```text
09:50–23:50 минус 14:00–14:05
```

Расписание срочного рынка может меняться. Есть утренняя, основная, вечерняя сессии, а также возможные выходные сессии. Поэтому расписание должно быть конфигурируемым.

Для v1 создай YAML-конфиг:

```text
configs/market_hours/moex_futures.yaml
```

Содержимое по умолчанию:

```yaml
timezone: Europe/Moscow

weekday_sessions:
  - name: morning
    start: "09:00"
    end: "10:00"
  - name: main
    start: "10:00"
    end: "19:00"
  - name: evening
    start: "19:00"
    end: "23:50"

weekend_sessions:
  - name: weekend
    start: "10:00"
    end: "19:00"

stale_candle_grace_minutes: 3
```

Если в проекте уже есть место для конфигов — используй существующий стиль проекта. Если нет — создай директорию `configs/market_hours`.

## Часть 1. Модуль market hours

Создай модуль:

```text
src/market/market_hours.py
```

Если директории `src/market` нет — создай.

Нужная функциональность:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path


@dataclass(frozen=True)
class MarketSession:
    name: str
    start: time
    end: time


@dataclass(frozen=True)
class MarketHoursConfig:
    timezone: str
    weekday_sessions: tuple[MarketSession, ...]
    weekend_sessions: tuple[MarketSession, ...]
    stale_candle_grace_minutes: int


def load_market_hours_config(path: Path) -> MarketHoursConfig:
    ...


def is_session_open(ts: datetime, config: MarketHoursConfig) -> bool:
    ...


def get_session_name(ts: datetime, config: MarketHoursConfig) -> str:
    ...


def to_market_timezone(ts: datetime, config: MarketHoursConfig) -> datetime:
    ...
```

Требования:

- Использовать `zoneinfo.ZoneInfo`.
- На вход может прийти timezone-aware datetime в UTC или Europe/Moscow.
- Если datetime naive — выбрасывать понятную ошибку, например `ValueError("timezone-aware datetime is required")`.
- Внутри приводить timestamp к timezone из конфига.
- `is_session_open()` возвращает `True`, если timestamp попадает в одну из активных сессий.
- `get_session_name()` возвращает имя сессии: `morning`, `main`, `evening`, `weekend` или `closed`.
- Границы сессии:
  - `start` включительно;
  - `end` исключительно.
- Суббота и воскресенье должны использовать `weekend_sessions`.
- Понедельник–пятница должны использовать `weekday_sessions`.
- Если конфиг отсутствует или некорректен — ошибка должна быть понятной.
- Если `stale_candle_grace_minutes` отсутствует — дефолт `3`.

Если в проекте уже используется `pydantic`, можно использовать его, но не тащи новую зависимость ради этого. Лучше стандартная библиотека + PyYAML, если PyYAML уже есть. Если PyYAML нет, проверь `requirements.txt` и добавь зависимость только если это нормально для проекта.

## Часть 2. Интеграция market hours guard в paper trader

Найди основной цикл paper trader-а. Скорее всего это:

```text
scripts/run_paper_trader.py
```

или модуль, который он вызывает.

Добавь параметры CLI:

```text
--market-hours-config configs/market_hours/moex_futures.yaml
--ignore-market-hours
```

Поведение:

### По умолчанию

Если `--ignore-market-hours` не передан:

1. Загружаем market hours config.
2. В начале каждого цикла проверяем текущее время.
3. Если рынок закрыт:
   - не ходим в T-Bank API за свечами;
   - пишем понятный лог;
   - обновляем status-файл;
   - ждём `poll_interval`;
   - переходим к следующему циклу.

Пример лога:

```text
MARKET_CLOSED ticker=SiM6 session=closed msk_time=2026-05-02T21:50:59+03:00 next_cycle_in=20s
```

### Если передан `--ignore-market-hours`

Бот работает как раньше и ходит за свечами независимо от расписания. Это нужно для отладки.

Пример лога при старте:

```text
Market hours guard disabled by --ignore-market-hours
```

## Часть 3. Таймаут на API-запрос свечей

Сейчас `fetch_recent_candles()` может потенциально зависнуть надолго.

Добавь явный таймаут.

Нужен параметр CLI:

```text
--api-timeout-sec 10
```

Дефолт:

```text
10 секунд
```

Поведение:

- Если API не ответил за timeout:
  - цикл не падает;
  - пишется лог `API_TIMEOUT`;
  - status-файл обновляется;
  - бот ждёт следующий цикл.
- Если таймаут нельзя реализовать прямо внутри SDK-вызова, оберни вызов на уровне paper trader-а так, чтобы основной цикл не зависал бесконечно.
- Не используй небезопасные хаки, которые могут оставить поток в неопределённом состоянии.
- Если в проекте всё синхронное, можно использовать подход через future/thread executor или иной простой безопасный механизм.
- Если уже есть инфраструктура таймаутов в проекте — используй её.

Пример лога:

```text
API_TIMEOUT ticker=SiM6 timeout_sec=10 operation=fetch_recent_candles
```

## Часть 4. Stale candle guard

Добавь проверку свежести последней свечи.

Нужное поведение:

1. Если рынок открыт и свечи получены:
   - найти timestamp последней свечи;
   - сравнить с текущим временем биржи;
   - если последняя свеча старше допустимого grace window, писать `STALE_CANDLES`.

2. Grace window брать из market hours config:

```yaml
stale_candle_grace_minutes: 3
```

3. Если рынок закрыт — stale candle не считать ошибкой.

4. Если свечей нет:
   - при открытом рынке писать `NO_CANDLES_DURING_OPEN_SESSION`;
   - при закрытом рынке до API вообще не ходим, поэтому такого быть не должно, если guard включён.

Примеры логов:

```text
STALE_CANDLES ticker=SiM6 last_candle_msk=2026-05-04T10:15:00+03:00 now_msk=2026-05-04T10:21:10+03:00 max_age_minutes=3
```

```text
NO_CANDLES_DURING_OPEN_SESSION ticker=SiM6 session=main msk_time=2026-05-04T11:30:20+03:00
```

Важно:
- Не открывать pending entries и не обрабатывать сигналы на stale candles.
- При stale candles цикл должен быть пропущен безопасно.

## Часть 5. Status-файл

Добавь JSON status-файл, который обновляется каждый цикл.

CLI параметр:

```text
--status-file runtime/paper_status_SiM6_SELL.json
```

Если параметр не передан, дефолт должен формироваться автоматически:

```text
runtime/paper_status_{ticker}_{direction}.json
```

Например:

```text
runtime/paper_status_SiM6_SELL.json
```

Если директории `runtime` нет — создать.

Файл должен обновляться атомарно:
- сначала писать во временный файл;
- потом `rename` / `replace`.

Пример содержимого:

```json
{
  "service": "hammertrade-paper",
  "mode": "paper",
  "ticker": "SiM6",
  "class_code": "SPBFUT",
  "timeframe": "1m",
  "profile": "balanced",
  "direction": "SELL",
  "env": "prod",

  "market_hours_enabled": true,
  "market_open": false,
  "session": "closed",
  "market_timezone": "Europe/Moscow",

  "last_cycle_at_utc": "2026-05-02T18:50:59Z",
  "last_cycle_at_msk": "2026-05-02T21:50:59+03:00",
  "last_fetch_status": "MARKET_CLOSED",
  "last_candle_ts_utc": null,
  "last_candle_ts_msk": null,
  "last_processed_ts_utc": null,

  "open_trades": 0,
  "pending_signal": false,
  "consecutive_empty_fetches": 0,
  "consecutive_api_errors": 0,

  "last_error": null,
  "pid": 761
}
```

Статусы `last_fetch_status` минимум:

```text
OK
MARKET_CLOSED
API_TIMEOUT
API_ERROR
NO_CANDLES_DURING_OPEN_SESSION
STALE_CANDLES
NO_CANDLES
```

Требования:

- Status-файл должен обновляться:
  - при старте;
  - при закрытом рынке;
  - при успешном fetch;
  - при no candles;
  - при stale candles;
  - при API timeout;
  - при API error;
  - при штатном завершении `--once`.
- Если часть полей пока сложно достать, не делай большой рефакторинг. Лучше заполнять их `null`, но структура файла должна быть стабильной.

## Часть 6. Health-check скрипт

Добавь скрипт:

```text
scripts/check_paper_status.py
```

Он должен читать status-файл и печатать человекочитаемый статус.

Пример запуска:

```bash
python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json
```

Пример вывода:

```text
HammerTrade Paper Status
========================

Service       : hammertrade-paper
Ticker        : SiM6
Direction     : SELL
Mode          : paper
Market        : CLOSED
Session       : closed
Last cycle UTC: 2026-05-02T18:50:59Z
Last fetch    : MARKET_CLOSED
Last candle   : n/a
Open trades   : 0
Pending signal: false
API errors    : 0
Result        : OK
```

Exit codes:

```text
0 = OK
1 = WARNING
2 = CRITICAL
```

Минимальная логика:

- `OK`, если:
  - status-файл есть;
  - JSON валидный;
  - `last_fetch_status` один из `OK`, `MARKET_CLOSED`, `NO_CANDLES`;
- `WARNING`, если:
  - `last_fetch_status` = `NO_CANDLES_DURING_OPEN_SESSION` или `STALE_CANDLES`;
  - status старше заданного порога;
- `CRITICAL`, если:
  - status-файл отсутствует;
  - JSON битый;
  - `last_fetch_status` = `API_TIMEOUT` или `API_ERROR`;
  - есть `last_error`.

Добавь параметры:

```text
--max-status-age-sec 120
```

Дефолт:

```text
120
```

## Часть 7. Логирование причин пропуска цикла

Сейчас часто видно только:

```text
No candles returned, skipping cycle.
```

Нужно сделать причины явными.

Минимальный набор причин:

```text
MARKET_CLOSED
API_TIMEOUT
API_ERROR
NO_CANDLES_DURING_OPEN_SESSION
STALE_CANDLES
NO_CANDLES
```

При этом лог должен быть grep-friendly, то есть причина должна быть отдельным токеном в строке.

Примеры:

```text
MARKET_CLOSED ticker=SiM6 session=closed msk_time=...
API_TIMEOUT ticker=SiM6 timeout_sec=10
NO_CANDLES_DURING_OPEN_SESSION ticker=SiM6 session=main msk_time=...
STALE_CANDLES ticker=SiM6 last_candle_msk=... now_msk=...
```

## Часть 8. Тесты

Добавь тесты.

Минимально нужны:

```text
tests/test_market_hours.py
tests/test_paper_status.py
```

Если в проекте другая структура тестов — следуй текущему стилю.

### Тесты market hours

Проверить:

1. Weekday morning session:
   - `2026-05-04T06:00:00Z` соответствует 09:00 МСК;
   - session open;
   - session name `morning`.

2. Weekday main session:
   - 10:30 МСК;
   - open;
   - session name `main`.

3. Weekday evening session:
   - 20:00 МСК;
   - open;
   - session name `evening`.

4. Closed before session:
   - 08:59 МСК;
   - closed.

5. Closed after evening:
   - 23:50 МСК;
   - closed, потому что end exclusive.

6. Weekend session:
   - суббота 12:00 МСК;
   - open;
   - session name `weekend`.

7. Weekend closed:
   - суббота 20:00 МСК;
   - closed.

8. Naive datetime:
   - должен быть `ValueError`.

9. Boundary behavior:
   - start inclusive;
   - end exclusive.

### Тесты status-файла

Проверить:

1. Status writer создаёт директорию `runtime`, если её нет.
2. JSON пишется валидный.
3. Повторная запись обновляет файл.
4. Atomic write не оставляет битый JSON.
5. Health-check возвращает:
   - `0` для OK;
   - `1` для stale/no candles during open;
   - `2` для API error / missing file / broken JSON.

Если health-check сложно тестировать как subprocess, вынеси логику оценки в функцию и протестируй её напрямую.

## Часть 9. Обновить systemd example при необходимости

Если есть файл:

```text
deploy/systemd/hammertrade-paper.example.service
```

Обнови его так, чтобы новые параметры были явно видны.

Пример:

```ini
ExecStart=/opt/hammertrade/.venv/bin/python scripts/run_paper_trader.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --timeframe 1m \
  --profile balanced \
  --direction-filter SELL \
  --env prod \
  --market-hours-config /opt/hammertrade/configs/market_hours/moex_futures.yaml \
  --api-timeout-sec 10 \
  --status-file /opt/hammertrade/runtime/paper_status_SiM6_SELL.json
```

Важно:
- Если systemd unit в проекте не поддерживает multiline `ExecStart`, сделай в том стиле, который уже принят.
- Не менять реальный `/etc/systemd/system/...`, только example в репозитории.

## Часть 10. Документация

Добавь или обнови документацию:

```text
docs/paper_trader_operational.md
```

В ней кратко описать:

1. Как запустить paper trader.
2. Как включается market hours guard.
3. Как временно отключить guard через `--ignore-market-hours`.
4. Где лежит status-файл.
5. Как запустить health-check.
6. Как смотреть логи через `journalctl`.
7. Что означают статусы:
   - `MARKET_CLOSED`
   - `API_TIMEOUT`
   - `API_ERROR`
   - `NO_CANDLES_DURING_OPEN_SESSION`
   - `STALE_CANDLES`
   - `NO_CANDLES`
   - `OK`

## Часть 11. Проверочные команды

После изменений обязательно выполни:

```bash
cd /opt/hammertrade
source .venv/bin/activate

python -m pytest
```

Потом проверь ручной запуск в one-shot режиме.

### Проверка закрытого рынка

```bash
python scripts/run_paper_trader.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --timeframe 1m \
  --profile balanced \
  --direction-filter SELL \
  --env prod \
  --once \
  --market-hours-config configs/market_hours/moex_futures.yaml \
  --api-timeout-sec 10 \
  --status-file runtime/paper_status_SiM6_SELL.json
```

Ожидаемое поведение, если рынок закрыт:

```text
MARKET_CLOSED ...
```

И status-файл должен существовать:

```bash
cat runtime/paper_status_SiM6_SELL.json
python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json
```

### Проверка обхода market hours guard

```bash
python scripts/run_paper_trader.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --timeframe 1m \
  --profile balanced \
  --direction-filter SELL \
  --env prod \
  --once \
  --ignore-market-hours \
  --api-timeout-sec 10 \
  --status-file runtime/paper_status_SiM6_SELL.json
```

Ожидаемое поведение:

- guard отключён;
- бот пытается получить свечи;
- если свечей нет, причина должна логироваться явно;
- status-файл обновляется.

## Что вернуть в отчёте

В конце работы верни отчёт в таком формате:

```markdown
# Отчёт по задаче Operational Safety Layer v1

## Что изменено

- ...

## Новые файлы

- ...

## Изменённые файлы

- ...

## Как проверить

```bash
...
```

## Результат тестов

```text
...
```

## Важные замечания

- ...

## Что осталось на следующий шаг

- transaction boundary для fetch → detect → persist → update_state
- pending signal recovery после рестарта
- circuit breaker
- расширенный monitoring / Prometheus
```

## Критерии готовности

Задача считается выполненной, если:

- `python -m pytest` проходит.
- Paper trader запускается с новыми параметрами.
- В закрытую сессию бот не ходит в API за свечами.
- В закрытую сессию логируется `MARKET_CLOSED`.
- Создаётся валидный JSON status-файл.
- `scripts/check_paper_status.py` читает status-файл и возвращает корректный exit code.
- При `--ignore-market-hours` бот ведёт себя как раньше, но с улучшенными логами/status.
- Нет реальных торговых действий.
