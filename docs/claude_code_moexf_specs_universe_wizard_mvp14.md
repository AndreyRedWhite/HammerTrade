# Задача MVP-1.4: Instrument specs-aware backtest + interactive runner + liquid futures universe

## Контекст проекта

Мы разрабатываем исследовательский Python-проект для фьючерсов MOEXF через Т-Инвестиции.

Текущий статус:

```text
MVP-0:
CSV candles -> candle geometry -> HammerDetector -> out/debug_simple_all.csv

MVP-0.1:
debug report

MVP-0.2:
T-Bank historical candles loader

MVP-0.3:
clearing timezone fix

MVP-1:
single backtest

MVP-1.1:
grid robustness

MVP-1.2:
walk-forward / multi-period analysis

MVP-1.3:
parameterized full research pipeline + zip archive
```

После нескольких прогонов выяснилось:

1. Для SiM6 стратегия выглядит перспективно.
2. SELL-сигналы стабильнее BUY-сигналов.
3. Для других инструментов нельзя честно сравнивать рублёвый PnL, пока используется общий fallback:

```text
point_value_rub = 10
commission_per_trade = 0.025
```

4. Для кросс-инструментального исследования нужно брать реальные спецификации фьючерса:
   - min_price_increment;
   - min_price_increment_amount;
   - lot;
   - currency;
   - expiration_date;
   - first_trade_date;
   - last_trade_date;
   - first_1min_candle_date;
   - uid;
   - ticker;
   - class_code.

Также хочется не запускать длинный скрипт с кучей аргументов. Нужен интерактивный режим, в котором скрипт сам спрашивает тикер/период/профиль, предлагая значения по умолчанию.

---

## Важное организационное ограничение

Claude Code НЕ должен запускать полный pipeline с T-Bank API.

Причина:

1. пользователь запускает Claude Code с включенным VPN;
2. при включенном VPN доступ к T-Bank API может отсутствовать;
3. загрузку свечей и реальные API-запросы пользователь будет запускать сам локально.

Поэтому:

```text
НЕ запускать T-Bank API из Claude Code.
НЕ запускать полный pipeline, если он делает сетевые вызовы.
НЕ требовать токены у пользователя.
НЕ печатать токены.
```

Разрешено:

```text
pytest
локальные unit-тесты
проверка --help
проверка dry-run / mock / skip-load режимов
```

---

## Цель MVP-1.4

Сделать 3 больших улучшения:

1. Instrument specs-aware backtest:
   - автоматически получать и сохранять спецификации фьючерсов;
   - корректно считать `point_value_rub` через `min_price_increment_amount / min_price_increment`;
   - не использовать `point_value_rub=10` как универсальную истину для всех инструментов.

2. Interactive pipeline runner:
   - запуск без длинных аргументов;
   - скрипт сам спрашивает тикер, период, timeframe, profile;
   - везде предлагает дефолты;
   - при желании можно запускать как раньше через CLI-аргументы.

3. Liquid futures universe:
   - найти доступные фьючерсы SPBFUT;
   - оценить ликвидность за выбранный период;
   - сформировать список top-N ликвидных инструментов;
   - позже использовать этот universe для массовых research-прогонов.

---

## Документация T-Bank, которую нужно учитывать

Перед реализацией сверься с актуальной документацией T-Invest API:

```text
https://developer.tbank.ru/invest/intro/intro/faq_identification
https://developer.tbank.ru/invest/services/instruments/methods
https://developer.tbank.ru/invest/services/market-data/methods
```

Важные факты:

1. Основной идентификатор торгового инструмента — `uid` / `instrument_uid`, FIGI считается устаревшим для новых интеграций.
2. `ticker + '_' + class_code` можно использовать как `instrument_id`.
3. Для фьючерсов MOEX class_code:

```text
SPBFUT
```

4. В Instruments service есть методы:
   - `Futures`;
   - `FutureBy`;
   - `GetFuturesMargin`;
   - `GetInstrumentBy`;
   - `FindInstrument`.
5. Для фьючерса важны поля:
   - `uid`;
   - `ticker`;
   - `class_code`;
   - `lot`;
   - `currency`;
   - `min_price_increment`;
   - `min_price_increment_amount`;
   - `expiration_date`;
   - `first_trade_date`;
   - `last_trade_date`;
   - `first_1min_candle_date`;
   - `first_1day_candle_date`;
   - `api_trade_available_flag`;
   - `buy_available_flag`;
   - `sell_available_flag`.

---

# Часть 1. Instrument specs module

Добавить/расширить модуль:

```text
src/tbank/instrument_specs.py
```

Реализовать dataclass:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass(frozen=True)
class FutureInstrumentSpec:
    ticker: str
    class_code: str
    uid: str
    figi: Optional[str]
    name: str
    lot: int
    currency: str
    min_price_increment: float
    min_price_increment_amount: Optional[float]
    point_value_rub: Optional[float]
    initial_margin_on_buy: Optional[float]
    initial_margin_on_sell: Optional[float]
    expiration_date: Optional[datetime]
    first_trade_date: Optional[datetime]
    last_trade_date: Optional[datetime]
    first_1min_candle_date: Optional[datetime]
    first_1day_candle_date: Optional[datetime]
    api_trade_available_flag: Optional[bool]
    buy_available_flag: Optional[bool]
    sell_available_flag: Optional[bool]
```

## Расчёт point_value_rub

Для фьючерсов:

```text
point_value_rub = min_price_increment_amount / min_price_increment
```

Пример:

```text
min_price_increment = 1
min_price_increment_amount = 10
point_value_rub = 10
```

Если `min_price_increment_amount` недоступен:

```text
point_value_rub = None
```

И дальше pipeline/backtest должен явно предупреждать, что используется fallback.

---

# Часть 2. Получение specs из T-Bank

В `src/tbank/instrument_specs.py` реализовать:

```python
def fetch_future_spec(
    client,
    ticker: str,
    class_code: str = "SPBFUT",
) -> FutureInstrumentSpec:
    ...
```

Логика:

1. Найти фьючерс по ticker/class_code.
2. Получить основные поля из `FutureBy` или `GetInstrumentBy`.
3. Получить margin/specs через `GetFuturesMargin`, чтобы достать:
   - `initial_margin_on_buy`;
   - `initial_margin_on_sell`;
   - `min_price_increment`;
   - `min_price_increment_amount`.
4. Конвертировать `Quotation` / `MoneyValue` через уже существующие функции.
5. Рассчитать `point_value_rub`.
6. Вернуть `FutureInstrumentSpec`.

Если инструмент не найден:

```text
понятная ошибка + подсказка проверить ticker/class_code
```

Если margin/specs недоступны:

```text
не падать, а вернуть spec с point_value_rub=None и warning
```

---

# Часть 3. Локальный кэш спецификаций

Создать каталог:

```text
data/instruments/
```

Сохранять specs в CSV:

```text
data/instruments/futures_specs.csv
```

Колонки:

```text
ticker
class_code
uid
figi
name
lot
currency
min_price_increment
min_price_increment_amount
point_value_rub
initial_margin_on_buy
initial_margin_on_sell
expiration_date
first_trade_date
last_trade_date
first_1min_candle_date
first_1day_candle_date
api_trade_available_flag
buy_available_flag
sell_available_flag
updated_at
```

Реализовать функции:

```python
def load_specs_cache(path: str = "data/instruments/futures_specs.csv") -> pandas.DataFrame:
    ...
```

```python
def upsert_future_spec(spec: FutureInstrumentSpec, path: str = "data/instruments/futures_specs.csv") -> None:
    ...
```

```python
def get_cached_future_spec(
    ticker: str,
    class_code: str = "SPBFUT",
    path: str = "data/instruments/futures_specs.csv",
) -> Optional[FutureInstrumentSpec]:
    ...
```

Важно:

- ключ: `ticker + class_code`;
- при повторном запросе обновлять строку;
- не дублировать строки;
- если CSV отсутствует — создать.

---

# Часть 4. Specs-aware pipeline

Обновить:

```text
scripts/run_full_research_pipeline.sh
```

Добавить параметры:

```text
--auto-specs
--point-value-rub auto
--fallback-point-value-rub 10
--specs-cache data/instruments/futures_specs.csv
```

## Поведение

По умолчанию:

```text
--point-value-rub auto
--auto-specs true
```

Перед backtest pipeline должен определить `POINT_VALUE_RUB`.

Логика:

1. Если `--point-value-rub` передан числом:
   - использовать его;
   - вывести warning, что пользователь переопределил стоимость пункта вручную.
2. Если `--point-value-rub auto`:
   - попытаться взять `point_value_rub` из local specs cache;
   - если нет в cache и `--auto-specs true`:
     - вызвать отдельный script для загрузки specs из T-Bank;
   - если specs успешно получены:
     - использовать spec.point_value_rub;
   - если specs не получены или point_value_rub=None:
     - использовать `--fallback-point-value-rub`;
     - вывести warning:

```text
WARNING: Could not determine point_value_rub from instrument specs.
Using fallback_point_value_rub=10.
PnL may be invalid for this instrument.
```

## Важное ограничение

Если pipeline запускается в Claude Code, он не должен вызывать T-Bank. Поэтому для локальной проверки можно использовать:

```text
--auto-specs false
--skip-load
```

---

# Часть 5. CLI для specs

Создать:

```text
scripts/fetch_future_specs.py
```

Пример запуска:

```bash
python scripts/fetch_future_specs.py   --ticker SiM6   --class-code SPBFUT   --env prod   --output data/instruments/futures_specs.csv
```

Вывод:

```text
Future spec
===========

Ticker: SiM6
Class code: SPBFUT
UID: ...
Name: Si-6.26 Курс доллар - рубль
Min price increment: ...
Min price increment amount: ...
Point value RUB: ...
Initial margin buy: ...
Initial margin sell: ...
Expiration date: ...
Saved to: data/instruments/futures_specs.csv
```

Не печатать токены.

---

# Часть 6. Interactive pipeline runner

Создать новый Python CLI:

```text
scripts/run_research_wizard.py
```

Цель — удобный интерактивный запуск без длинных аргументов.

Пользователь запускает:

```bash
python scripts/run_research_wizard.py
```

Скрипт спрашивает:

```text
Ticker [SiM6]:
Class code [SPBFUT]:
From date [2026-03-01]:
To date [2026-04-10]:
Timeframe [1m]:
Profile [balanced]:
Environment [prod]:
Load candles from T-Bank? [Y/n]:
Run grid backtest? [Y/n]:
Run walk-forward grid? [Y/n]:
Create archive? [Y/n]:
Point value RUB [auto]:
Fallback point value RUB [10]:
Slippage points for baseline [0]:
Take R for baseline [1.0]:
Max hold bars [30]:
```

После этого показывает summary:

```text
About to run:

Ticker: SiM6
Class code: SPBFUT
Period: 2026-03-01 -> 2026-04-10
Timeframe: 1m
Profile: balanced
Point value RUB: auto
Archive: yes

Command:
./scripts/run_full_research_pipeline.sh ...

Run? [Y/n]:
```

Если пользователь подтверждает — запускает bash pipeline.

Если пользователь отвечает `n` — завершает без запуска.

## Требования

1. Не спрашивать токены.
2. Не печатать токены.
3. Дефолты должны быть удобными.
4. Если пользователь просто нажимает Enter — берётся значение по умолчанию.
5. Должен быть флаг:

```bash
python scripts/run_research_wizard.py --dry-run
```

В dry-run режиме:
- собрать команду;
- показать её;
- не запускать.

6. Должен быть флаг:

```bash
python scripts/run_research_wizard.py --yes
```

В этом режиме:
- использовать дефолты;
- не спрашивать финальное подтверждение;
- полезно для локальных прогонов.

Но по умолчанию лучше спрашивать подтверждение.

---

# Часть 7. Liquid futures universe

Добавить модуль:

```text
src/tbank/liquidity_universe.py
```

Цель — найти top-N ликвидных фьючерсов SPBFUT за период.

Важно: это research-инструмент, не торговый модуль.

## Реализовать

```python
def fetch_available_futures(client, class_code: str = "SPBFUT") -> pandas.DataFrame:
    ...
```

Возвращает список фьючерсов с полями:

```text
ticker
class_code
uid
name
expiration_date
first_trade_date
last_trade_date
first_1min_candle_date
first_1day_candle_date
min_price_increment
min_price_increment_amount
point_value_rub
api_trade_available_flag
buy_available_flag
sell_available_flag
```

Фильтры:

- class_code = SPBFUT;
- `api_trade_available_flag=True`, если поле доступно;
- дата `last_trade_date` или `expiration_date` должна быть после начала исследуемого периода;
- `first_1min_candle_date` должна быть раньше конца периода.

---

## Оценка ликвидности

Реализовать:

```python
def estimate_futures_liquidity(
    client,
    futures_df: pandas.DataFrame,
    start: datetime,
    end: datetime,
    timeframe: str = "1m",
    sample_days: int = 5,
) -> pandas.DataFrame:
    ...
```

Идея:

1. Не качать полгода по всем фьючерсам сразу.
2. Для каждого инструмента взять sample window:
   - последние `sample_days` торговых дней внутри периода;
   - или первые доступные дни, если последних нет.
3. Загрузить свечи.
4. Посчитать грубые метрики ликвидности:

```text
candles_count
non_zero_volume_candles
zero_range_candles
total_volume
avg_volume_per_candle
median_volume_per_candle
avg_range
median_range
activity_score
```

## activity_score

Простая стартовая формула:

```text
activity_score = non_zero_volume_candles * median_volume_per_candle
```

Можно сделать лучше, но не усложнять.

---

# Часть 8. CLI для universe scan

Создать:

```text
scripts/scan_liquid_futures.py
```

Пример запуска:

```bash
python scripts/scan_liquid_futures.py   --from 2026-03-01   --to 2026-04-10   --class-code SPBFUT   --timeframe 1m   --sample-days 5   --top 20   --env prod   --output data/instruments/liquid_futures_2026-03-01_2026-04-10.csv   --report-output reports/liquid_futures_2026-03-01_2026-04-10.md
```

Выводит top-N по activity_score:

```text
Top liquid futures
==================

1. SiM6  score=...
2. ...
```

Markdown report:

```markdown
# Liquid Futures Universe Report

## Parameters

| Parameter | Value |
|---|---|
| Class code | SPBFUT |
| Period | 2026-03-01 -> 2026-04-10 |
| Timeframe | 1m |
| Sample days | 5 |
| Top N | 20 |

## Top futures by activity_score

| rank | ticker | name | expiration_date | point_value_rub | candles_count | total_volume | median_volume_per_candle | zero_range_candles | activity_score |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|

## Notes

This is a rough liquidity scan based on historical candles.
It does not guarantee live order book liquidity.
```

---

# Часть 9. Batch research for universe

Не обязательно делать полный массовый прогон в этой задаче, но заложить простой CLI можно.

Создать:

```text
scripts/run_universe_research.py
```

Он читает CSV из `scan_liquid_futures.py` и запускает full pipeline по top-N.

Пример:

```bash
python scripts/run_universe_research.py   --universe data/instruments/liquid_futures_2026-03-01_2026-04-10.csv   --top 5   --from 2026-03-01   --to 2026-04-10   --timeframe 1m   --profile balanced   --env prod   --skip-walkforward-grid
```

Важно:

- этот скрипт тоже НЕ запускать внутри Claude Code;
- он может быть создан, но пользователь будет запускать его сам;
- по умолчанию пусть делает dry-run или требует подтверждение.

Поведение:

1. показать список тикеров;
2. показать команды, которые будут запущены;
3. спросить:

```text
Run these pipelines? [y/N]
```

4. при подтверждении запускать по очереди.

---

# Часть 10. BUY-only / SELL-only режимы

Добавить в backtest / pipeline параметр:

```text
--direction-filter all|BUY|SELL
```

По умолчанию:

```text
all
```

Поддержать в:

```text
scripts/run_backtest.py
scripts/run_backtest_grid.py
scripts/run_walkforward.py
scripts/run_walkforward_grid.py
scripts/run_full_research_pipeline.sh
scripts/run_research_wizard.py
```

Логика:

- `all`: использовать все сигналы;
- `BUY`: использовать только `direction_candidate == BUY`;
- `SELL`: использовать только `direction_candidate == SELL`.

В отчётах явно писать:

```text
Direction filter: BUY / SELL / all
```

Это важно, потому что по предыдущим исследованиям SELL выглядит стабильнее BUY.

---

# Часть 11. Tests

Добавить тесты без реальных API-вызовов.

## tests/test_instrument_specs.py

Проверить:

1. `point_value_rub = min_price_increment_amount / min_price_increment`;
2. если `min_price_increment_amount=None`, point_value_rub=None;
3. cache upsert не создаёт дубли;
4. cached spec загружается корректно;
5. fallback warning формируется, если point_value_rub недоступен.

## tests/test_direction_filter.py

Проверить:

1. all даёт все сигналы;
2. BUY даёт только BUY;
3. SELL даёт только SELL;
4. неизвестный direction-filter даёт понятную ошибку.

## tests/test_research_wizard.py

Проверить:

1. dry-run не запускает subprocess;
2. defaults подставляются;
3. command формируется корректно;
4. `--yes` работает без интерактивного подтверждения.

## tests/test_liquidity_universe.py

Без T-Bank API.

На synthetic DataFrame проверить:

1. activity_score считается;
2. сортировка top-N корректная;
3. фильтрация expired instruments работает;
4. report создаётся.

---

# Часть 12. README

Обновить README.

Добавить разделы:

```markdown
## Instrument specs-aware backtest

## Interactive research wizard

## Liquid futures universe scan

## Direction filter: BUY-only / SELL-only
```

Объяснить:

1. Почему нельзя использовать `point_value_rub=10` для всех инструментов.
2. Как получить спецификацию фьючерса:

```bash
python scripts/fetch_future_specs.py --ticker SiM6 --class-code SPBFUT --env prod
```

3. Как запустить wizard:

```bash
python scripts/run_research_wizard.py
```

4. Как запустить dry-run:

```bash
python scripts/run_research_wizard.py --dry-run
```

5. Как отсканировать ликвидные фьючерсы:

```bash
python scripts/scan_liquid_futures.py   --from 2026-03-01   --to 2026-04-10   --top 20
```

6. Как прогнать только SELL:

```bash
./scripts/run_full_research_pipeline.sh   --ticker SiM6   --from 2026-03-01   --to 2026-04-10   --direction-filter SELL
```

---

# Definition of Done

Задача выполнена, если:

1. Есть модуль:

```text
src/tbank/instrument_specs.py
```

2. Есть кэш:

```text
data/instruments/futures_specs.csv
```

3. Есть CLI:

```text
scripts/fetch_future_specs.py
```

4. Backtest/pipeline умеет `point-value-rub auto`.
5. Если specs доступны, используется реальный `point_value_rub`.
6. Если specs недоступны, выводится warning и используется fallback.
7. Есть интерактивный запуск:

```text
scripts/run_research_wizard.py
```

8. Wizard умеет:
   - спрашивать параметры;
   - подставлять defaults;
   - показывать команду;
   - dry-run;
   - final confirmation.
9. Есть liquidity scan:

```text
scripts/scan_liquid_futures.py
```

10. Есть report:

```text
reports/liquid_futures_*.md
```

11. Есть direction-filter:

```text
all|BUY|SELL
```

12. Direction filter работает в:
   - single backtest;
   - grid backtest;
   - walk-forward;
   - walk-forward grid;
   - full pipeline;
   - wizard.
13. README обновлён.
14. Тесты проходят:

```bash
pytest
```

15. Полный pipeline с T-Bank API не запускался внутри Claude Code.

---

# Отчёт после выполнения

После реализации напиши:

```text
Что добавлено:
...

Как получить specs инструмента:
...

Как теперь считается point_value_rub:
...

Как запустить wizard:
...

Как запустить liquidity scan:
...

Как запустить BUY-only / SELL-only:
...

Что проверено:
...

Что НЕ запускалось и почему:
...

Что пока не реализовано:
...
```

В блоке "Что НЕ запускалось и почему" обязательно указать:

```text
Полный pipeline и T-Bank API-запросы не запускались из Claude Code, потому что пользователь запускает Claude Code с VPN, при котором доступ к T-Bank может отсутствовать. Пользователь запустит эти команды сам локально.
```

В блоке "Что пока не реализовано" указать:

```text
- live trading не реализован;
- sandbox orders не реализованы;
- broker execution не реализован;
- order book liquidity не моделируется;
- partial fills не моделируются;
- queue position не моделируется;
- margin requirements / ГО используются только как справочная информация, но не как полноценная модель риска;
- liquidity scan по свечам не гарантирует реальную ликвидность в стакане.
```
