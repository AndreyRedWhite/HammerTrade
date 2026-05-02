# Задача MVP-1.5: Instrument-aware detector / tick-size auto

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

MVP-1.4:
instrument specs-aware backtest + interactive wizard + liquid futures universe + direction filter
```

После MVP-1.4 стало понятно:

1. Backtest теперь умеет брать `point_value_rub` из specs.
2. Но сам `HammerDetector` всё ещё использует общий fallback:

```env
S_FALLBACK_TICK=0.5
```

3. Из-за этого на других инструментах top universe почти все свечи отваливаются по `range`.

Примеры:

```text
CRM6:
  signals: 0
  fail_reason range: 23361
  invalid_range: 1383

CNYRUBF:
  signals: 0
  fail_reason range: 22985
  invalid_range: 1758

NRJ6:
  signals: 0
  fail_reason range: 22917
  invalid_range: 4151

BRK6:
  signals: 2
  fail_reason range: 27677

BMK6:
  signals: 1
  fail_reason range: 24765
```

Проблема: detector считает минимальный диапазон примерно так:

```text
min_range = S_MIN_RANGE_TICKS * S_FALLBACK_TICK
```

При текущем:

```text
S_MIN_RANGE_TICKS=2.0
S_FALLBACK_TICK=0.5
```

получается:

```text
min_range = 1.0
```

Для инструментов с `min_price_increment=0.01` это означает требование диапазона в 100 тиков, что слишком жёстко.

---

## Главная цель MVP-1.5

Сделать detector instrument-aware:

```text
tick_size = min_price_increment из specs
```

А не общий:

```text
S_FALLBACK_TICK=0.5
```

Важно различать:

```text
tick_size / min_price_increment — нужен detector'у
point_value_rub — нужен backtest PnL
```

Пример BRK6:

```text
min_price_increment = 0.01
min_price_increment_amount = 7.46947
point_value_rub = 746.947
```

Это значит:

```text
1 tick = 0.01 price point
1 tick стоит 7.46947 RUB
1 price point стоит 746.947 RUB
```

Detector должен использовать:

```text
tick_size = 0.01
```

Backtest PnL должен использовать:

```text
point_value_rub = 746.947
```

---

## Важное организационное ограничение

Claude Code НЕ должен запускать полный pipeline с T-Bank API.

Причина:

1. пользователь запускает Claude Code с включенным VPN;
2. при включенном VPN доступ к T-Bank API может отсутствовать;
3. загрузку свечей, specs и universe scan пользователь будет запускать сам локально.

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
проверка dry-run
проверка --skip-load на уже существующих локальных файлах только если это не требует API
```

---

# Что строго запрещено

Не делать:

- live trading;
- реальные заявки;
- sandbox-заявки;
- postOrder;
- postSandboxOrder;
- broker execution;
- подключение к stream API;
- изменение торговой идеи;
- оптимизацию параметров под прибыль;
- автоматический подбор detector params;
- работу с full-access token;
- запуск T-Bank API из Claude Code.

Эта задача только про корректное использование `tick_size` / `min_price_increment` в detector и pipeline.

---

# Часть 1. Добавить tick_size в параметры detector

Сейчас detector берёт tick size из:

```env
S_FALLBACK_TICK=0.5
```

Нужно добавить явный runtime-параметр:

```text
tick_size
```

Правило:

1. Если `tick_size` передан явно через CLI/pipeline — использовать его.
2. Если `tick_size` не передан — использовать `S_FALLBACK_TICK`.
3. Если `tick_size <= 0` — понятная ошибка.

Обновить config/dataclass, например:

```python
@dataclass
class HammerParams:
    ...
    fallback_tick: float = 0.5
    tick_size: Optional[float] = None

    @property
    def effective_tick_size(self) -> float:
        return self.tick_size if self.tick_size is not None else self.fallback_tick
```

Если текущая структура другая — адаптировать аккуратно.

---

# Часть 2. Обновить все фильтры detector

Все фильтры, которые используют тики, должны использовать:

```text
effective_tick_size
```

А не напрямую `S_FALLBACK_TICK`.

Проверить минимум следующие параметры:

```text
S_MIN_RANGE_TICKS
S_MIN_WICK_TICKS
S_OPP_WICK_MAX_ABS_TICKS
S_EXT_EPS_TICKS
S_NEIGHBOR_EPS_TICKS
S_MIN_EXCURSION_TICKS
```

Примеры:

```python
min_range = params.S_MIN_RANGE_TICKS * params.effective_tick_size
min_wick = params.S_MIN_WICK_TICKS * params.effective_tick_size
opp_abs = params.S_OPP_WICK_MAX_ABS_TICKS * params.effective_tick_size
ext_eps = params.S_EXT_EPS_TICKS * params.effective_tick_size
neighbor_eps = params.S_NEIGHBOR_EPS_TICKS * params.effective_tick_size
min_excursion = params.S_MIN_EXCURSION_TICKS * params.effective_tick_size
```

---

# Часть 3. CLI для detector

Обновить основной detector CLI:

```text
python -m src.main
```

Добавить аргумент:

```text
--tick-size
```

Пример:

```bash
python -m src.main \
  --input data/raw/tbank/BRK6_1m_2026-03-01_2026-04-10_balanced.csv \
  --output out/debug_simple_all_BRK6.csv \
  --params configs/hammer_detector_balanced.env \
  --instrument BRK6 \
  --timeframe 1m \
  --profile balanced \
  --tick-size 0.01
```

Поведение:

- если `--tick-size` передан — использовать его;
- если не передан — использовать `S_FALLBACK_TICK`;
- в summary вывести:

```text
Tick size: 0.01
Tick size source: cli
```

или:

```text
Tick size: 0.5
Tick size source: fallback
```

---

# Часть 4. Debug CSV / debug report

Добавить в `out/debug_simple_all*.csv` колонки:

```text
tick_size
tick_size_source
```

Где:

```text
tick_size_source = cli | specs | fallback
```

Если удобно, можно также добавить:

```text
min_range_abs
min_wick_abs
min_excursion_abs
```

Это желательно, потому что поможет диагностировать, почему инструмент режется по `range`.

Минимально обязательно:

```text
tick_size
tick_size_source
```

Обновить `src/analytics/debug_report.py`, чтобы в Summary было:

```text
Tick size
Tick size source
```

Если в CSV несколько значений tick_size, report должен показать unique values или warning.

---

# Часть 5. Specs-aware pipeline для tick_size

Обновить:

```text
scripts/run_full_research_pipeline.sh
```

Добавить параметры:

```text
--tick-size auto
--fallback-tick-size
```

Дефолты:

```text
--tick-size auto
--fallback-tick-size берётся из config S_FALLBACK_TICK или 0.5
```

## Поведение

Перед запуском detector pipeline должен определить `TICK_SIZE`.

Логика:

1. Если `--tick-size` передан числом:
   - использовать его;
   - `tick_size_source=user`;
   - вывести warning, что tick_size переопределён вручную.

2. Если `--tick-size auto`:
   - попробовать взять `min_price_increment` из specs cache;
   - если нет в cache и `--auto-specs true`:
     - вызвать specs fetch script;
   - если specs найдены:
     - использовать `min_price_increment`;
     - `tick_size_source=specs`;
   - если specs не найдены:
     - использовать fallback;
     - `tick_size_source=fallback`;
     - вывести warning:

```text
WARNING: Could not determine tick_size from instrument specs.
Using fallback_tick_size=0.5.
Detector filters may be invalid for this instrument.
```

3. Если `tick_size <= 0`:
   - завершиться с ошибкой.

## Важно

`point_value_rub` и `tick_size` решаются отдельно:

```text
point_value_rub = min_price_increment_amount / min_price_increment
tick_size = min_price_increment
```

Не путать эти значения.

---

# Часть 6. Specs script должен уметь печатать tick size

Обновить:

```text
scripts/fetch_future_specs.py
```

Добавить флаг:

```text
--print-tick-size
```

Поведение:

```bash
python scripts/fetch_future_specs.py \
  --ticker BRK6 \
  --class-code SPBFUT \
  --env prod \
  --print-tick-size
```

Вывод должен быть bare float:

```text
0.01
```

Это нужно для bash pipeline.

Уже есть `--print-point-value`; оставить его.

Также можно добавить:

```text
--print-json
```

но это необязательно.

---

# Часть 7. Pipeline должен передавать tick_size в detector

В шаге detector:

```bash
python -m src.main \
  --input ... \
  --output ... \
  --params ... \
  --instrument ... \
  --timeframe ... \
  --profile ... \
  --tick-size "${TICK_SIZE}" \
  --tick-size-source "${TICK_SIZE_SOURCE}"
```

Добавить в `src.main`:

```text
--tick-size-source cli|specs|fallback|user
```

Для ручного запуска по умолчанию:

```text
cli
```

Для pipeline:

```text
specs / fallback / user
```

---

# Часть 8. Universe research должен передавать tick_size

Обновить:

```text
scripts/run_universe_research.py
```

Сейчас он уже передаёт:

```text
--point-value-rub <value>
```

Нужно, чтобы он также передавал:

```text
--tick-size <min_price_increment>
```

Из universe CSV должны быть доступны поля:

```text
min_price_increment
point_value_rub
```

Если `min_price_increment` отсутствует или некорректен:

- не передавать `--tick-size`;
- дать warning;
- pipeline должен сам попытаться взять specs или fallback.

В выводе перед запуском команды показать:

```text
point_value_rub=...
tick_size=...
```

---

# Часть 9. Liquid futures scan report

Обновить report:

```text
reports/liquid_futures_*.md
```

Добавить колонки:

```text
min_price_increment
min_price_increment_amount
point_value_rub
```

Если они уже есть — проверить, что они корректно сохраняются в CSV и report.

---

# Часть 10. Интерактивный wizard

Обновить:

```text
scripts/run_research_wizard.py
```

Добавить вопрос:

```text
Tick size [auto]:
```

И в summary:

```text
Point value RUB: auto
Tick size: auto
```

Если пользователь вводит число — передать:

```text
--tick-size <value>
```

Если Enter — передать:

```text
--tick-size auto
```

---

# Часть 11. Direction filter и tick size в RUN_ID

Сейчас RUN_ID, вероятно:

```text
${TICKER}_${TIMEFRAME}_${START_DATE}_${END_DATE}_${PROFILE}
```

Если direction filter не all, лучше добавлять его в RUN_ID, чтобы BUY/SELL не перетирали друг друга.

Обновить:

```text
if direction_filter != all:
  RUN_ID="${TICKER}_${TIMEFRAME}_${START_DATE}_${END_DATE}_${PROFILE}_${DIRECTION_FILTER}"
else:
  RUN_ID="${TICKER}_${TIMEFRAME}_${START_DATE}_${END_DATE}_${PROFILE}"
```

Это важно: сейчас BUY-only и SELL-only прогоны могут перезаписывать один и тот же архив/отчёты.

Tick size в RUN_ID добавлять не нужно.

---

# Часть 12. Tests

Добавить тесты без реальных API-вызовов.

## tests/test_tick_size_params.py

Проверить:

1. если `tick_size` передан, `effective_tick_size == tick_size`;
2. если `tick_size=None`, используется `fallback_tick`;
3. если `tick_size <= 0`, возникает понятная ошибка;
4. `min_range_abs` считается через effective tick size.

## tests/test_detector_tick_size.py

Synthetic candles.

Проверить главный кейс:

- свеча с range `0.04`;
- `S_MIN_RANGE_TICKS=2`;
- при `tick_size=0.5` она должна отвалиться по `range`;
- при `tick_size=0.01` она не должна отвалиться по `range`.

Это ключевой тест.

## tests/test_debug_tick_size_columns.py

Проверить:

1. debug CSV содержит `tick_size`;
2. debug CSV содержит `tick_size_source`;
3. значения корректны.

## tests/test_pipeline_run_id_direction.py

Проверить, если есть удобный способ:

1. direction_filter=SELL добавляется в RUN_ID;
2. direction_filter=BUY добавляется в RUN_ID;
3. direction_filter=all не добавляется.

Если bash сложно тестировать unit-тестом, можно вынести run_id builder в Python helper или сделать лёгкий shell test.

## tests/test_universe_research_tick_size.py

Проверить:

1. command builder добавляет `--tick-size`, если `min_price_increment` есть;
2. command builder добавляет `--point-value-rub`, если `point_value_rub` есть;
3. при отсутствии `min_price_increment` выводится warning или команда не содержит tick-size.

---

# Часть 13. README

Обновить README.

Добавить раздел:

```markdown
## Instrument-aware detector tick size
```

Объяснить:

1. Чем `tick_size` отличается от `point_value_rub`.

```text
tick_size = min_price_increment, нужен detector'у
point_value_rub = стоимость 1 price point в рублях, нужен backtest PnL
```

2. Почему старый fallback `S_FALLBACK_TICK=0.5` не подходит для всех инструментов.
3. Как запустить detector вручную с tick size:

```bash
python -m src.main \
  --input data/raw/tbank/BRK6_1m_2026-03-01_2026-04-10_balanced.csv \
  --output out/debug_simple_all_BRK6.csv \
  --params configs/hammer_detector_balanced.env \
  --instrument BRK6 \
  --timeframe 1m \
  --profile balanced \
  --tick-size 0.01
```

4. Как pipeline автоматически берёт tick size из specs:

```bash
./scripts/run_full_research_pipeline.sh \
  --ticker BRK6 \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --tick-size auto \
  --point-value-rub auto
```

5. Как проверить в debug report, какой tick size использовался.

---

# Definition of Done

Задача выполнена, если:

1. HammerDetector использует `effective_tick_size`, а не напрямую `S_FALLBACK_TICK`.
2. `python -m src.main` поддерживает:

```text
--tick-size
--tick-size-source
```

3. Debug CSV содержит:

```text
tick_size
tick_size_source
```

4. Debug report показывает tick size.
5. Full pipeline поддерживает:

```text
--tick-size auto
--fallback-tick-size
```

6. Full pipeline берёт `tick_size = min_price_increment` из specs cache/API.
7. Full pipeline отдельно берёт `point_value_rub` для PnL.
8. `fetch_future_specs.py` поддерживает:

```text
--print-tick-size
```

9. `run_universe_research.py` передаёт `--tick-size` для каждого инструмента.
10. Wizard поддерживает tick size.
11. RUN_ID различает BUY/SELL/all, чтобы прогоны не перетирались.
12. Тесты проходят:

```bash
pytest
```

13. Полный pipeline с T-Bank API не запускался внутри Claude Code.

---

# Отчёт после выполнения

После реализации напиши:

```text
Что добавлено:
...

Как теперь определяется tick_size:
...

Как tick_size отличается от point_value_rub:
...

Какие CLI обновлены:
...

Как запустить detector с tick_size вручную:
...

Как запустить full pipeline с tick-size auto:
...

Как изменился RUN_ID для BUY/SELL:
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
- detector теперь tick-size aware, но параметры balanced/strict/loose всё ещё могут требовать отдельной калибровки под разные классы инструментов.
```
