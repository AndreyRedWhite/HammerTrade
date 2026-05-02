# Задача MVP-0.2: T-Bank Historical Candles Loader для MOEXF Hammer Bot

## Контекст проекта

Мы разрабатываем исследовательский Python-проект для торговли/исследования фьючерсов MOEXF через Т-Инвестиции.

Текущий статус проекта:

```text
MVP-0:
CSV candles -> candle geometry -> HammerDetector -> out/debug_simple_all.csv

MVP-0.1:
out/debug_simple_all.csv -> reports/debug_report.md
```

Сейчас нужно добавить слой загрузки исторических свечей из T-Invest API, чтобы перестать зависеть только от вручную подготовленных CSV.

Важно: проект пока остаётся research/backtest/debug-проектом.

Live trading, реальные заявки и broker execution запрещены.

---

## Что уже есть в проекте

В проекте уже есть:

```text
configs/
  hammer_detector_balanced.env
  hammer_detector_strict.env
  hammer_detector_loose.env
  hammer_detector_sell_upper_wick.env

src/
  main.py
  config.py
  market_data/
    loader.py
  strategy/
    candle_geometry.py
    hammer_detector.py
    signal.py
  risk/
    clearing.py
  storage/
    debug_repository.py
  analytics/
    summary.py
    debug_report.py

out/
  debug_simple_all.csv

reports/
  debug_report.md
```

Детектор уже ожидает CSV формата:

```text
timestamp,open,high,low,close,volume
```

Твоя задача — добавить загрузчик исторических свечей из T-Bank API, который сохраняет данные именно в этом формате, чтобы существующий детектор работал без изменений.

---

## Важные вводные

Пользователь уже выпустил два токена и положил их в `.env` в корень проекта:

```env
SANDBOX_TOKEN=...
READONLY_TOKEN=...
```

Нужно использовать именно эти имена переменных.

Не переименовывай их в `TBANK_SANDBOX_TOKEN` или `TBANK_READONLY_TOKEN`.

Можно добавить новые переменные в `.env.example`, но код должен читать существующие:

```env
SANDBOX_TOKEN
READONLY_TOKEN
```

---

## Официальная документация, которую нужно учитывать

Перед реализацией сверься с актуальной документацией T-Invest API:

```text
https://developer.tbank.ru/invest/intro/intro/
https://developer.tbank.ru/invest/sdk/python_sdk/faq_python/
https://developer.tbank.ru/invest/intro/intro/token
https://developer.tbank.ru/invest/intro/intro/load_history
https://developer.tbank.ru/invest/intro/intro/faq_identification
https://developer.tbank.ru/invest/intro/developer/sandbox
https://developer.tbank.ru/invest/intro/developer/sandbox/url_difference
```

Важные факты из документации:

1. T-Invest API — gRPC API.
2. Prod endpoint:

```text
invest-public-api.tbank.ru:443
```

3. Sandbox endpoint:

```text
sandbox-invest-public-api.tbank.ru:443
```

4. Для Python SDK используется пакет:

```bash
pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple
```

5. Read-only token можно использовать для получения информации, исторических данных, котировок и расписаний, но нельзя использовать для выставления торговых поручений.

6. Sandbox token предназначен для песочницы. Его нельзя использовать как обычный prod-токен.

7. Для фьючерсов Московской биржи class_code:

```text
SPBFUT
```

8. Основной идентификатор инструмента лучше хранить как `uid` / `instrument_uid`, а не как FIGI.

9. Комбинацию ticker + class_code можно использовать как `instrument_id` в формате:

```text
ticker_class_code
```

Пример для фьючерса:

```text
SiM6_SPBFUT
```

10. Исторические свечи загружаются через `GetCandles`.

11. Для минутных свечей есть ограничение периода запроса: от 1 минуты до 1 дня, максимальный `limit` — 2400.

12. Для 5-минутных свечей период до недели, для 15-минутных — до 3 недель, для 1h — до 3 месяцев.

Из-за этих ограничений загрузчик должен уметь нарезать период на чанки.

---

## Главная цель задачи

Реализовать модуль:

```text
T-Bank API -> historical candles -> normalized CSV
```

Выходной CSV должен быть совместим с уже существующим детектором.

Пример результата:

```text
data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv
```

Формат файла:

```csv
timestamp,open,high,low,close,volume
2026-04-01T10:00:00+03:00,92000.0,92050.0,91980.0,92020.0,123
...
```

---

## Что строго запрещено в этой задаче

Не делать:

- live trading;
- реальные заявки;
- sandbox-заявки;
- postOrder;
- postSandboxOrder;
- cancelOrder;
- cancelSandboxOrder;
- работу с full-access token;
- риск-менеджер для реальных заявок;
- executor;
- paper trading;
- backtest;
- автоматическую торговлю;
- хранение токенов в коде;
- коммит `.env`.

Эта задача только про historical market data loader.

---

# Требуемая структура файлов

Добавить/обновить:

```text
src/
  tbank/
    __init__.py
    settings.py
    client.py
    instruments.py
    candles.py
    money.py
  market_data/
    tbank_loader.py
  analytics/
    data_quality_report.py

scripts/
  load_tbank_candles.py

data/
  raw/
    tbank/
  instruments/

reports/

.env.example
.gitignore
requirements.txt
README.md
tests/
  test_tbank_settings.py
  test_tbank_candle_conversion.py
  test_tbank_chunking.py
  test_data_quality_report.py
```

Если текущая структура проекта отличается, адаптируй аккуратно, но не ломай уже существующие модули.

---

# Зависимости

Обновить `requirements.txt`.

Сейчас там уже есть:

```text
pandas
python-dotenv
pytest
```

Добавить T-Bank SDK.

Если пакет ставится из отдельного index-url, добавь комментарий в `requirements.txt` или README с инструкцией установки.

Вариант в README:

```bash
pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple
```

Если `pip install -r requirements.txt` с таким пакетом требует отдельного index-url и ломается, не делай хрупкую магию. Лучше явно напиши отдельную команду установки в README.

---

# .env.example

Создать/обновить `.env.example`:

```env
# T-Bank API tokens
# Real token with read-only access to prod contour.
READONLY_TOKEN=

# Sandbox token for sandbox contour.
SANDBOX_TOKEN=

# Environment mode for T-Bank connection.
# Allowed values: prod, sandbox
TBANK_ENV=prod

# API targets.
TBANK_PROD_TARGET=invest-public-api.tbank.ru:443
TBANK_SANDBOX_TARGET=sandbox-invest-public-api.tbank.ru:443

# Safety flags.
LIVE_TRADING_ENABLED=false
SANDBOX_TRADING_ENABLED=false
```

Обновить `.gitignore`, если нужно:

```gitignore
.env
.env.*
!.env.example
data/raw/tbank/*.csv
reports/*.md
```

Если в проекте уже есть `.gitignore`, не удаляй существующие правила, только добавь недостающие.

---

# Модуль settings

Файл:

```text
src/tbank/settings.py
```

Реализовать:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class TBankSettings:
    env: str
    token: str
    target: str
    readonly_token_present: bool
    sandbox_token_present: bool
```

Функция:

```python
def load_tbank_settings(env: str = "prod") -> TBankSettings:
    ...
```

Логика:

- читать `.env` через `python-dotenv`;
- если `env == "prod"`:
  - использовать `READONLY_TOKEN`;
  - target — `TBANK_PROD_TARGET` или дефолт `invest-public-api.tbank.ru:443`;
- если `env == "sandbox"`:
  - использовать `SANDBOX_TOKEN`;
  - target — `TBANK_SANDBOX_TARGET` или дефолт `sandbox-invest-public-api.tbank.ru:443`;
- если токен отсутствует — понятная ошибка;
- если env не `prod` и не `sandbox` — понятная ошибка.

Важно:

В рамках этой задачи prod означает только read-only доступ. Код не должен использовать full-access token.

---

# Модуль client

Файл:

```text
src/tbank/client.py
```

Реализовать аккуратную фабрику клиента T-Bank SDK.

Примерная идея:

```python
from contextlib import contextmanager

@contextmanager
def get_tbank_client(settings):
    ...
```

Требования:

- использовать официальный Python SDK `t-tech-investments`;
- не хардкодить токен;
- не печатать токен в логи;
- target выбирать из `settings`;
- код должен быть изолирован: если SDK не установлен, должна быть понятная ошибка с инструкцией установки.

Пример сообщения:

```text
T-Bank SDK is not installed. Install it with:
pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple
```

---

# Модуль money / quotation conversion

Файл:

```text
src/tbank/money.py
```

В T-Invest API цены часто приходят как `Quotation` / `MoneyValue` с полями `units` и `nano`.

Реализовать функцию:

```python
def quotation_to_float(value) -> float:
    ...
```

Она должна корректно конвертировать:

```text
units + nano / 1_000_000_000
```

Учитывать отрицательные значения.

Также можно реализовать:

```python
def money_value_to_float(value) -> float:
    ...
```

Тесты обязательны.

---

# Модуль instruments

Файл:

```text
src/tbank/instruments.py
```

Цель — найти инструмент и сохранить его метаданные.

Реализовать функцию:

```python
def resolve_instrument(client, ticker: str, class_code: str = "SPBFUT") -> dict:
    ...
```

Задача:

- найти фьючерс по ticker и class_code;
- вернуть словарь с полями:

```text
ticker
class_code
uid
figi
name
lot
min_price_increment
expiration_date
first_1min_candle_date
first_1day_candle_date
```

Если по точному ticker/class_code не найдено:

- вывести понятную ошибку;
- желательно показать близкие найденные варианты, если SDK позволяет через FindInstrument.

Сохранить/обновить локальный справочник:

```text
data/instruments/moex_futures.csv
```

Колонки:

```text
ticker,class_code,uid,figi,name,lot,min_price_increment,expiration_date,first_1min_candle_date,first_1day_candle_date
```

Важно:

Для дальнейшей работы основной идентификатор — `uid`.

---

# Модуль candles

Файл:

```text
src/tbank/candles.py
```

Цель — загрузить исторические свечи чанками.

Реализовать:

```python
def get_interval_config(timeframe: str) -> dict:
    ...
```

Поддержать минимум:

```text
1m
5m
15m
1h
1d
```

Маппинг на enum SDK сделать внутри модуля.

Ограничения чанков:

```text
1m  -> максимум 1 день
5m  -> максимум 7 дней
15m -> максимум 21 день
1h  -> максимум 90 дней
1d  -> максимум 6 лет
```

Реализовать:

```python
def build_time_chunks(start: datetime, end: datetime, timeframe: str) -> list[tuple[datetime, datetime]]:
    ...
```

Требования:

- `start < end`;
- чанки не должны пересекаться;
- последний чанк должен заканчиваться ровно на `end`;
- timezone-aware datetime;
- если datetime naive — считать, что это Europe/Moscow или явно нормализовать.

Реализовать:

```python
def fetch_historical_candles(
    client,
    instrument_uid: str,
    start: datetime,
    end: datetime,
    timeframe: str,
) -> pandas.DataFrame:
    ...
```

Требования:

- использовать `GetCandles` / соответствующий метод SDK;
- ходить чанками;
- собирать все свечи в один DataFrame;
- конвертировать цены через `quotation_to_float`;
- итоговые колонки:

```text
timestamp
open
high
low
close
volume
```

- сортировать по `timestamp`;
- удалять дубли по `timestamp`;
- сохранять timezone;
- не падать на пустом чанке;
- если вообще нет свечей — вернуть пустой DataFrame с нужными колонками и понятным предупреждением.

---

# Модуль market_data/tbank_loader.py

Файл:

```text
src/market_data/tbank_loader.py
```

Реализовать высокоуровневую функцию:

```python
def load_tbank_candles_to_csv(
    ticker: str,
    start: str,
    end: str,
    timeframe: str,
    output: str,
    env: str = "prod",
    class_code: str = "SPBFUT",
) -> str:
    ...
```

Она должна:

1. загрузить настройки;
2. создать клиента;
3. найти инструмент;
4. загрузить свечи;
5. сохранить CSV;
6. вернуть путь к файлу.

---

# CLI-скрипт

Создать:

```text
scripts/load_tbank_candles.py
```

Команда запуска:

```bash
python scripts/load_tbank_candles.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --from 2026-04-01 \
  --to 2026-04-10 \
  --timeframe 1m \
  --env prod \
  --output data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv
```

Также должна работать песочница:

```bash
python scripts/load_tbank_candles.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --from 2026-04-01 \
  --to 2026-04-10 \
  --timeframe 1m \
  --env sandbox \
  --output data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10_sandbox.csv
```

Важно:

- `--from` и `--to` можно принимать как дату `YYYY-MM-DD`;
- если время не указано:
  - `from` = начало дня по Europe/Moscow;
  - `to` = начало следующего дня или указанная дата по Europe/Moscow;
- выводить понятный summary:

```text
T-Bank candles loader
=====================

Environment: prod
Ticker: SiM6
Class code: SPBFUT
Timeframe: 1m
From: 2026-04-01T00:00:00+03:00
To: 2026-04-10T00:00:00+03:00
Instrument UID: ...
Candles loaded: ...
Output: data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv
```

Не выводить токен.

---

# Data quality report

Добавить:

```text
src/analytics/data_quality_report.py
```

Цель — проверить качество загруженного CSV.

CLI:

```bash
python -m src.analytics.data_quality_report \
  --input data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv \
  --output reports/data_quality_SiM6_1m.md \
  --timeframe 1m
```

Отчёт должен содержать:

```markdown
# Data Quality Report

## Summary

| Metric | Value |
|---|---:|
| Rows | ... |
| First timestamp | ... |
| Last timestamp | ... |
| Duplicate timestamps | ... |
| Missing OHLC values | ... |
| Zero range candles | ... |
| Zero volume candles | ... |

## Time gaps

| gap_start | gap_end | expected_delta | actual_delta |
|---|---|---:|---:|

## Notes

This report validates only candle data quality.
It does not validate strategy performance.
```

Требования:

- проверять обязательные колонки;
- проверять дубли timestamp;
- проверять NaN в OHLC;
- проверять `high < low`;
- проверять `open/high/low/close <= 0`;
- проверять свечи с `range == 0`;
- проверять большие временные гэпы относительно timeframe;
- сохранять отчёт даже если есть проблемы.

---

# Интеграция с существующим пайплайном

После загрузки свечей текущий пайплайн должен работать так:

```bash
python scripts/load_tbank_candles.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --from 2026-04-01 \
  --to 2026-04-10 \
  --timeframe 1m \
  --env prod \
  --output data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv

python -m src.analytics.data_quality_report \
  --input data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv \
  --output reports/data_quality_SiM6_1m.md \
  --timeframe 1m

python -m src.main \
  --input data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv \
  --output out/debug_simple_all.csv \
  --params configs/hammer_detector_balanced.env \
  --instrument SiM6 \
  --timeframe 1m \
  --profile balanced

python -m src.analytics.debug_report \
  --input out/debug_simple_all.csv \
  --output reports/debug_report.md
```

---

# Тесты

Добавить тесты без реального обращения к T-Bank API.

Не нужно мокать всю сеть, достаточно unit-тестов на чистую логику.

## tests/test_tbank_settings.py

Проверить:

1. `load_tbank_settings("prod")` читает `READONLY_TOKEN`.
2. `load_tbank_settings("sandbox")` читает `SANDBOX_TOKEN`.
3. если токен отсутствует — понятная ошибка.
4. если env неизвестный — понятная ошибка.

## tests/test_tbank_candle_conversion.py

Проверить:

1. `quotation_to_float(units=100, nano=250000000) == 100.25`
2. `quotation_to_float(units=0, nano=500000000) == 0.5`
3. отрицательные значения обрабатываются корректно.
4. candle objects конвертируются в DataFrame с колонками:

```text
timestamp,open,high,low,close,volume
```

## tests/test_tbank_chunking.py

Проверить:

1. для 1m период 3 дня разбивается на 3 чанка по 1 дню;
2. для 5m период 15 дней разбивается на чанки не больше 7 дней;
3. последний чанк заканчивается ровно на end;
4. при start >= end возникает понятная ошибка;
5. naive datetime нормализуется или явно отклоняется понятной ошибкой.

## tests/test_data_quality_report.py

Проверить:

1. отчёт создаётся;
2. дубли timestamp считаются;
3. zero range candles считаются;
4. missing OHLC считаются;
5. большие time gaps попадают в отчёт.

---

# README

Обновить README.

Добавить раздел:

```markdown
## T-Bank historical candles loader
```

Описать:

1. Что этот модуль только загружает исторические свечи.
2. Что live trading пока запрещён.
3. Какие токены нужны.
4. Как создать `.env`.
5. Как установить SDK.
6. Как загрузить свечи.
7. Как проверить качество данных.
8. Как запустить существующий детектор на загруженных свечах.

Пример текста:

```markdown
### Tokens

Create `.env` in project root:

```env
READONLY_TOKEN=your_readonly_token
SANDBOX_TOKEN=your_sandbox_token
TBANK_ENV=prod
LIVE_TRADING_ENABLED=false
SANDBOX_TRADING_ENABLED=false
```

Never commit `.env`.
```

Важно: в README не вставлять реальные токены и не просить пользователя присылать токены в чат.

---

# Definition of Done

Задача выполнена, если:

1. В проекте появился модуль `src/tbank/`.
2. Код читает токены из `.env` по именам:

```text
READONLY_TOKEN
SANDBOX_TOKEN
```

3. Есть CLI:

```bash
python scripts/load_tbank_candles.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --from 2026-04-01 \
  --to 2026-04-10 \
  --timeframe 1m \
  --env prod \
  --output data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv
```

4. CLI сохраняет CSV с колонками:

```text
timestamp,open,high,low,close,volume
```

5. Есть data quality report:

```bash
python -m src.analytics.data_quality_report \
  --input data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv \
  --output reports/data_quality_SiM6_1m.md \
  --timeframe 1m
```

6. Существующий детектор может быть запущен на CSV, загруженном из T-Bank API.

7. Тесты проходят:

```bash
pytest
```

8. В проекте нет кода, который выставляет реальные или sandbox-заявки.
9. Токены не выводятся в консоль и не логируются.
10. `.env` не коммитится.
11. README обновлён.

---

# Отчёт после выполнения

В конце работы напиши короткий отчёт:

```text
Что добавлено:
...

Как установить зависимости:
...

Как настроить .env:
...

Как загрузить свечи:
...

Как проверить качество данных:
...

Как запустить детектор на загруженных свечах:
...

Какие тесты добавлены:
...

Что пока не реализовано:
...
```

В блоке "Что пока не реализовано" обязательно укажи:

```text
- live trading не реализован;
- sandbox orders не реализованы;
- реальные заявки не реализованы;
- backtest пока не реализован в этой задаче;
- paper trading пока не реализован.
```
