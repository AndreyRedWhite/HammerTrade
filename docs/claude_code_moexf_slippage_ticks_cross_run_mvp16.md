# Задача MVP-1.6: Slippage in ticks + normalized cross-run comparison

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

MVP-1.5:
instrument-aware detector / tick-size auto
```

После MVP-1.5 стало ясно:

1. Detector теперь корректно использует `tick_size = min_price_increment`.
2. Backtest корректно использует `point_value_rub`.
3. Universe-инструменты начали давать сигналы:
   - CRM6;
   - BRK6;
   - CNYRUBF;
   - NRJ6;
   - BMK6.
4. Но текущий grid robustness всё ещё некорректно сравнивает slippage между инструментами, потому что использует:

```text
slippage_points
```

а не:

```text
slippage_ticks
```

Проблема:

```text
CRM6 tick_size = 0.001
BRK6 tick_size = 0.01
SiM6 tick_size = 1.0
```

Текущий `slippage_points=1` означает:

```text
SiM6: 1 price point = 1 tick
BRK6: 1 price point = 100 ticks
CRM6: 1 price point = 1000 ticks
```

То есть grid со `slippage_points=1,2,5` нельзя честно сравнивать между инструментами.

---

## Главная цель MVP-1.6

Сделать две вещи:

1. Добавить slippage model в тиках:

```text
slippage_ticks -> slippage_price = slippage_ticks * tick_size
```

2. Добавить cross-run comparison report, который читает архивы из:

```text
archives/latest/Actual_*.zip
```

и строит общую сравнительную таблицу по инструментам и прогонам.

---

## Важное организационное ограничение

Claude Code НЕ должен запускать полный pipeline с T-Bank API.

Причина:

1. пользователь запускает Claude Code с включенным VPN;
2. при включенном VPN доступ к T-Bank API может отсутствовать;
3. загрузку свечей, specs и universe scan пользователь запускает сам локально.

Разрешено:

```text
pytest
локальные unit-тесты
проверка CLI --help
проверка dry-run
работа с локальными архивами/CSV, если они есть
```

Запрещено:

```text
T-Bank API calls
live trading
sandbox orders
broker execution
stream API
отключение TLS verification
установка / доверие Russian Trusted Root CA
```

---

# Часть 1. Slippage в тиках

## Что добавить

В backtest engine добавить параметр:

```python
slippage_ticks: Optional[float] = None
```

и использовать его так:

```python
effective_slippage_points = slippage_ticks * tick_size
```

Если `slippage_ticks` задан, он должен иметь приоритет над `slippage_points`.

Сохранить backward compatibility:

```text
--slippage-points
```

должен продолжать работать, но для cross-instrument анализа использовать лучше `--slippage-ticks`.

---

## Требуемая логика

В `src/backtest/engine.py` сейчас уже есть `slippage_points`.

Добавить:

```python
def run_backtest(
    ...,
    slippage_points: float = 0.0,
    slippage_ticks: Optional[float] = None,
    tick_size: Optional[float] = None,
    ...
)
```

Логика:

```text
if slippage_ticks is not None:
    require tick_size is not None and tick_size > 0
    effective_slippage_points = slippage_ticks * tick_size
else:
    effective_slippage_points = slippage_points
```

Если `slippage_ticks < 0` или `slippage_points < 0` — понятная ошибка.

Если `slippage_ticks` задан, но `tick_size` не задан — понятная ошибка:

```text
slippage_ticks requires tick_size
```

---

## Важный момент

Не путать:

```text
tick_size = min_price_increment
point_value_rub = min_price_increment_amount / min_price_increment
```

Расчёт денежного эффекта:

```text
slippage_rub_per_side = slippage_ticks * min_price_increment_amount
```

Но в текущей модели можно считать через price points:

```text
effective_slippage_points = slippage_ticks * tick_size
pnl_rub = price_points * point_value_rub
```

Это должно дать тот же результат:

```text
slippage_ticks * tick_size * point_value_rub
```

---

# Часть 2. Trades CSV / report

Добавить в trades CSV колонки:

```text
tick_size
slippage_points
slippage_ticks
effective_slippage_points
```

Если `slippage_ticks` не задан:

```text
slippage_ticks = empty/null
effective_slippage_points = slippage_points
```

Если `slippage_ticks` задан:

```text
effective_slippage_points = slippage_ticks * tick_size
```

Обновить single backtest report:

```text
Slippage points
Slippage ticks
Effective slippage points
Tick size
```

---

# Часть 3. CLI single backtest

Обновить:

```text
scripts/run_backtest.py
```

Добавить:

```text
--slippage-ticks
--tick-size
```

Пример:

```bash
python scripts/run_backtest.py   --input out/debug_simple_all_BRK6_1m_2026-03-01_2026-04-10_balanced.csv   --trades-output out/backtest_trades_BRK6_slip_ticks.csv   --report-output reports/backtest_report_BRK6_slip_ticks.md   --entry-mode breakout   --take-r 1.0   --slippage-ticks 1   --tick-size 0.01   --point-value-rub 746.947
```

Если debug CSV содержит колонку `tick_size`, можно использовать её как default, если `--tick-size` не передан.

Приоритет:

```text
CLI --tick-size
debug CSV tick_size unique value
None/error if slippage_ticks is used and no tick_size available
```

---

# Часть 4. Grid backtest

Обновить:

```text
scripts/run_backtest_grid.py
src/backtest/batch.py
src/backtest/grid_report.py
```

Добавить поддержку:

```text
--slippage-ticks-values
```

Пример:

```bash
python scripts/run_backtest_grid.py   --input out/debug_simple_all_BRK6_1m_2026-03-01_2026-04-10_balanced.csv   --output out/backtest_grid_results_BRK6_ticks.csv   --report-output reports/backtest_grid_report_BRK6_ticks.md   --entry-modes breakout,close   --take-r-values 0.5,1.0,1.5,2.0   --max-hold-bars-values 5,10,30,60   --stop-buffer-points-values 0,1,2,5   --slippage-ticks-values 0,1,2,5   --tick-size 0.01   --point-value-rub 746.947
```

## Поведение

Если передан `--slippage-ticks-values`, использовать его.

Если он не передан, оставить старое поведение через:

```text
--slippage-points-values
```

В grid results добавить колонки:

```text
slippage_ticks
effective_slippage_points
tick_size
```

В grid report добавить секцию:

```markdown
## Slippage ticks sensitivity
```

С колонками:

```text
slippage_ticks
scenarios
profitable_scenarios
avg_net_pnl_rub
median_net_pnl_rub
best_net_pnl_rub
worst_net_pnl_rub
```

Старую секцию `Slippage sensitivity` можно оставить, но явно назвать:

```text
Slippage points sensitivity
```

---

# Часть 5. Walk-forward / walk-forward grid

Обновить:

```text
scripts/run_walkforward.py
scripts/run_walkforward_grid.py
src/backtest/walkforward.py
src/backtest/walkforward_report.py
```

Добавить:

```text
--slippage-ticks
--slippage-ticks-values
--tick-size
```

В period results / grid results добавить:

```text
slippage_ticks
effective_slippage_points
tick_size
```

В отчётах показывать:

```text
Slippage ticks
Effective slippage points
Tick size
```

---

# Часть 6. Full research pipeline

Обновить:

```text
scripts/run_full_research_pipeline.sh
```

Добавить параметры:

```text
--slippage-ticks
--grid-slippage-ticks-values
```

## Defaults

Для single baseline:

```text
slippage_ticks not set by default
slippage_points default 0
```

Для grid лучше постепенно перейти на ticks.

Добавить новый default:

```text
GRID_SLIPPAGE_TICKS_VALUES="0,1,2,5"
```

И использовать ticks-grid, если `GRID_SLIPPAGE_TICKS_VALUES` задан.

То есть в pipeline grid-команда должна передавать:

```bash
--slippage-ticks-values "${GRID_SLIPPAGE_TICKS_VALUES}"
--tick-size "${TICK_SIZE}"
```

Для backward compatibility можно оставить `--grid-slippage-points-values`, но в основном pipeline лучше использовать ticks.

В summary pipeline вывести:

```text
Slippage points: ...
Slippage ticks: ...
Grid slippage ticks values: 0,1,2,5
```

Manifest тоже обновить:

```text
Slippage points
Slippage ticks
Grid slippage ticks values
```

---

# Часть 7. Universe research

Обновить:

```text
scripts/run_universe_research.py
```

Он уже передаёт:

```text
--point-value-rub
--tick-size
--skip-load
```

Добавить поддержку:

```text
--slippage-ticks
--grid-slippage-ticks-values
```

По умолчанию:

```text
grid_slippage_ticks_values = 0,1,2,5
```

При построении команд передавать:

```text
--grid-slippage-ticks-values 0,1,2,5
--tick-size <min_price_increment>
```

И не передавать старые `--grid-slippage-points-values`, если используется tick-based grid.

---

# Часть 8. Cross-run comparison report

Добавить новый модуль:

```text
src/analytics/cross_run_comparison.py
```

И CLI:

```text
scripts/compare_research_runs.py
```

## Цель

Читать несколько архивов:

```text
archives/latest/Actual_*.zip
```

или явно переданный список zip-файлов, доставать из них reports/CSV и собирать общую таблицу.

Пример запуска:

```bash
python scripts/compare_research_runs.py   --archives "archives/latest/Actual_*.zip"   --output out/cross_run_comparison.csv   --report-output reports/cross_run_comparison.md
```

Также поддержать:

```bash
python scripts/compare_research_runs.py   --archives archives/latest/Actual_SiM6_*.zip archives/latest/Actual_BRK6_*.zip   --output out/cross_run_comparison.csv   --report-output reports/cross_run_comparison.md
```

---

## Что парсить из архивов

Из manifest:

```text
run_id
created_at
ticker
class_code
timeframe
period
profile
direction_filter
point_value_rub
tick_size
tick_size_source
skip_load
skip_grid
skip_walkforward_grid
```

Из debug_report или debug CSV:

```text
rows
signals
buy_signals
sell_signals
top_fail_reason
range_fail_count
body_big_fail_count
invalid_range_count
```

Из backtest_report или trades CSV:

```text
closed_trades
skipped_trades
net_pnl_rub
winrate
profit_factor
max_drawdown_rub
avg_net_pnl_rub
buy_net_pnl_rub
sell_net_pnl_rub
```

Из grid results CSV:

```text
grid_scenarios
grid_profitable_scenarios
grid_profitable_scenarios_pct
best_grid_net_pnl_rub
worst_grid_net_pnl_rub
median_grid_net_pnl_rub
```

Если есть `slippage_ticks` в grid:

```text
worst_net_pnl_slippage_ticks_0
worst_net_pnl_slippage_ticks_1
worst_net_pnl_slippage_ticks_2
worst_net_pnl_slippage_ticks_5
median_net_pnl_slippage_ticks_0
median_net_pnl_slippage_ticks_1
median_net_pnl_slippage_ticks_2
median_net_pnl_slippage_ticks_5
```

Из walkforward period results:

```text
periods_total
profitable_periods
losing_periods
profitable_periods_pct
best_period_net_pnl_rub
worst_period_net_pnl_rub
```

Если walkforward отсутствует — заполнить null и не падать.

---

## Normalized metrics

Добавить нормализованные метрики:

```text
net_pnl_per_trade_rub = net_pnl_rub / closed_trades
net_pnl_per_signal_rub = net_pnl_rub / signals
signals_per_1000_rows = signals / rows * 1000
closed_trades_per_1000_rows = closed_trades / rows * 1000
```

Если есть margin из specs в manifest или cache:

```text
net_pnl_to_initial_margin_pct
```

Если initial margin недоступна — null.

---

## Markdown report structure

Создать:

```text
reports/cross_run_comparison.md
```

Структура:

```markdown
# Cross-run Research Comparison

## Summary

| Metric | Value |
|---|---:|
| Runs compared | ... |
| Created at | ... |

## Runs overview

| ticker | period | direction | tick_size | point_value_rub | signals | closed_trades | net_pnl_rub | winrate | profit_factor | profitable_periods_pct |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|

## Ranking by Net PnL

| rank | ticker | direction | net_pnl_rub | profit_factor | closed_trades | grid_profitable_scenarios_pct | worst_grid_net_pnl_rub |
|---:|---|---|---:|---:|---:|---:|---:|

## Ranking by Profit Factor

...

## Signal density

| ticker | rows | signals | signals_per_1000_rows | top_fail_reason |
|---|---:|---:|---:|---|

## Slippage ticks robustness

| ticker | direction | worst_net_pnl_slip_0 | worst_net_pnl_slip_1 | worst_net_pnl_slip_2 | worst_net_pnl_slip_5 |
|---|---|---:|---:|---:|---:|

## Notes

- Cross-run comparison is offline research only.
- Results do not include live execution, order book liquidity, queue position, partial fills or real broker execution.
- Slippage in ticks is more comparable across instruments than slippage in price points.
```

---

# Часть 9. Cross-run comparison по latest архивам

Добавить удобный режим:

```bash
python scripts/compare_research_runs.py --latest
```

Он должен использовать:

```text
archives/latest/Actual_*.zip
```

Пример:

```bash
python scripts/compare_research_runs.py   --latest   --output out/cross_run_comparison_latest.csv   --report-output reports/cross_run_comparison_latest.md
```

---

# Часть 10. Tests

Добавить тесты без T-Bank API.

## tests/test_slippage_ticks.py

Проверить:

1. `slippage_ticks=1`, `tick_size=0.01` даёт `effective_slippage_points=0.01`.
2. BUY result со slippage_ticks хуже, чем без slippage.
3. SELL result со slippage_ticks хуже, чем без slippage.
4. Если `slippage_ticks` задан, но `tick_size=None`, получить понятную ошибку.
5. Если `slippage_ticks < 0`, ошибка.

## tests/test_backtest_grid_slippage_ticks.py

Проверить:

1. grid создаёт сценарии по `slippage_ticks_values`;
2. результат содержит `slippage_ticks`;
3. результат содержит `effective_slippage_points`;
4. tick_size пробрасывается.

## tests/test_cross_run_comparison.py

Создать synthetic zip archives в tmpdir.

Проверить:

1. CLI/функция читает несколько архивов;
2. manifest парсится;
3. debug/backtest/grid/walkforward данные извлекаются;
4. comparison CSV создаётся;
5. markdown report создаётся;
6. если в архиве нет walkforward, скрипт не падает.

---

# Часть 11. README

Обновить README.

Добавить разделы:

```markdown
## Slippage in ticks

## Cross-run comparison
```

Объяснить:

1. Почему `slippage_points` плохо сравнивать между инструментами.
2. Почему `slippage_ticks` лучше.
3. Как запустить single backtest со slippage ticks.
4. Как запустить grid со slippage ticks.
5. Как запустить full pipeline с tick-based grid.
6. Как сравнить latest архивы:

```bash
python scripts/compare_research_runs.py   --latest   --output out/cross_run_comparison_latest.csv   --report-output reports/cross_run_comparison_latest.md
```

---

# Definition of Done

Задача выполнена, если:

1. Backtest engine поддерживает:

```text
slippage_ticks
tick_size
effective_slippage_points
```

2. Single backtest CLI поддерживает:

```text
--slippage-ticks
--tick-size
```

3. Grid backtest CLI поддерживает:

```text
--slippage-ticks-values
--tick-size
```

4. Walk-forward CLI поддерживает tick-based slippage.
5. Full pipeline использует tick-based grid по умолчанию:

```text
--grid-slippage-ticks-values 0,1,2,5
```

6. Universe research передаёт tick-based slippage в pipeline.
7. Trades CSV содержит:

```text
tick_size
slippage_points
slippage_ticks
effective_slippage_points
```

8. Grid results содержит:

```text
tick_size
slippage_ticks
effective_slippage_points
```

9. Есть CLI:

```text
scripts/compare_research_runs.py
```

10. `compare_research_runs.py --latest` сравнивает архивы из:

```text
archives/latest/Actual_*.zip
```

11. Создаются:

```text
out/cross_run_comparison_latest.csv
reports/cross_run_comparison_latest.md
```

12. README обновлён.
13. Тесты проходят:

```bash
pytest
```

14. T-Bank API не запускался из Claude Code.

---

# Отчёт после выполнения

После реализации напиши:

```text
Что добавлено:
...

Как теперь работает slippage_ticks:
...

Как это отличается от slippage_points:
...

Какие CLI обновлены:
...

Как запустить tick-based grid:
...

Как запустить full pipeline с tick-based grid:
...

Как запустить cross-run comparison:
...

Какие файлы создаются:
...

Что проверено:
...

Что НЕ запускалось и почему:
...

Что пока не реализовано:
...
```

В блоке "Что НЕ запускалось и почему" указать:

```text
T-Bank API и полный research pipeline не запускались из Claude Code. Изменения касаются offline backtest/grid/reporting и чтения локальных архивов.
```

В блоке "Что пока не реализовано" указать:

```text
- live trading не реализован;
- sandbox orders не реализованы;
- broker execution не реализован;
- order book liquidity не моделируется;
- partial fills не моделируются;
- queue position не моделируется;
- slippage_ticks остаётся упрощённой моделью и не заменяет реальный стакан;
- margin / ГО пока не используется как полноценная риск-модель.
```
