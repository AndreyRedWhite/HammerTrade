# Задача MVP-1.3: Parameterized Research Pipeline Runner + архивирование отчётов

## Контекст проекта

Мы разрабатываем исследовательский Python-проект для фьючерсов MOEXF через Т-Инвестиции.

Текущий статус проекта:

```text
MVP-0:
CSV candles -> candle geometry -> HammerDetector -> out/debug_simple_all.csv

MVP-0.1:
out/debug_simple_all.csv -> reports/debug_report.md

MVP-0.2:
T-Bank historical candles loader -> normalized CSV -> data quality report

MVP-0.3:
Fix clearing timezone

MVP-1:
Backtest v1 -> out/backtest_trades.csv -> reports/backtest_report.md

MVP-1.1:
Backtest robustness / grid analysis

MVP-1.2:
Multi-period / walk-forward backtest
```

Сейчас есть bash-скрипт:

```text
scripts/run_full_research_pipeline.sh
```

Он успешно запускает полный research pipeline, но в нём захардкожены:

```text
ticker
class_code
timeframe
start_date
end_date
profile
params_file
entry/backtest/grid параметры
```

Из-за этого для нового периода или инструмента приходится редактировать сам скрипт.

Нужно сделать скрипт удобным для повторных прогонов.

---

## Важное организационное ограничение

Claude Code НЕ должен сам запускать полный пайплайн, потому что:

1. загрузка свечей требует доступа к T-Bank API;
2. пользователь запускает Claude Code с включенным VPN;
3. при включенном VPN доступ к T-Bank API может отсутствовать;
4. пользователь будет запускать итоговый скрипт сам локально, когда доступ к T-Bank будет работать.

Поэтому:

```text
НЕ запускать scripts/run_full_research_pipeline.sh внутри Claude Code.
НЕ пытаться проверить загрузку данных из T-Bank API.
НЕ делать сетевые вызовы к T-Bank.
НЕ требовать от пользователя токены.
```

Можно запускать только локальные unit-тесты, которые не требуют T-Bank API.

---

## Цель MVP-1.3

Сделать параметризуемый full research pipeline runner.

Нужно, чтобы пользователь мог запускать:

```bash
./scripts/run_full_research_pipeline.sh   --ticker SiM6   --class-code SPBFUT   --from 2026-03-01   --to 2026-04-10   --timeframe 1m   --profile balanced   --env prod
```

И получить:

1. загруженный CSV свечей;
2. data quality report;
3. debug CSV;
4. debug report;
5. single backtest trades/report;
6. grid backtest results/report;
7. weekly walk-forward results/report;
8. daily walk-forward grid results/report;
9. weekly walk-forward grid results/report;
10. единый `.zip` архив со всеми результатами прогона.

---

## Что строго запрещено

Не делать:

- live trading;
- реальные заявки;
- sandbox-заявки;
- postOrder;
- postSandboxOrder;
- broker execution;
- подключение к stream API;
- изменение логики HammerDetector;
- изменение логики backtest;
- изменение торговых параметров по умолчанию без явной причины;
- работу с full-access token;
- запуск T-Bank API из Claude Code.

Эта задача только про удобство запуска research pipeline и упаковку результатов.

---

# Часть 1. Параметризовать bash-скрипт

Обновить:

```text
scripts/run_full_research_pipeline.sh
```

Скрипт должен принимать аргументы:

```text
--ticker
--class-code
--from
--to
--timeframe
--profile
--env
--params-file
--point-value-rub
--commission-per-trade
--contracts
--entry-mode
--entry-horizon-bars
--max-hold-bars
--take-r
--stop-buffer-points
--slippage-points
--grid-entry-modes
--grid-take-r-values
--grid-max-hold-bars-values
--grid-stop-buffer-points-values
--grid-slippage-points-values
--skip-load
--skip-grid
--skip-walkforward-grid
--archive
--help
```

## Обязательные аргументы

Минимальный запуск должен быть таким:

```bash
./scripts/run_full_research_pipeline.sh   --ticker SiM6   --class-code SPBFUT   --from 2026-03-01   --to 2026-04-10   --timeframe 1m   --profile balanced   --env prod
```

## Значения по умолчанию

Если аргумент не передан:

```text
class_code = SPBFUT
timeframe = 1m
profile = balanced
env = prod
params_file = configs/hammer_detector_${profile}.env

point_value_rub = 10
commission_per_trade = 0.025
contracts = 1

entry_mode = breakout
entry_horizon_bars = 3
max_hold_bars = 30
take_r = 1.0
stop_buffer_points = 0
slippage_points = 0

grid_entry_modes = breakout,close
grid_take_r_values = 0.5,1.0,1.5,2.0
grid_max_hold_bars_values = 5,10,30,60
grid_stop_buffer_points_values = 0,1,2,5
grid_slippage_points_values = 0,1,2,5

archive = true
skip_load = false
skip_grid = false
skip_walkforward_grid = false
```

## Валидация

Скрипт должен проверять:

1. `--ticker` задан;
2. `--from` задан;
3. `--to` задан;
4. `--profile` задан или имеет default;
5. `params_file` существует;
6. если `--skip-load` не задан, то будет вызван T-Bank loader;
7. если `--skip-load` задан, то raw candles file должен уже существовать;
8. директории `data/raw/tbank`, `out`, `reports`, `archives` должны создаваться автоматически.

При ошибке выводить понятное сообщение и завершаться с exit code != 0.

---

# Часть 2. Help

Добавить нормальный help:

```bash
./scripts/run_full_research_pipeline.sh --help
```

Пример help:

```text
MOEXF Hammer Research Pipeline

Usage:
  ./scripts/run_full_research_pipeline.sh --ticker SiM6 --from 2026-03-01 --to 2026-04-10 [options]

Required:
  --ticker VALUE              Futures ticker, e.g. SiM6
  --from YYYY-MM-DD           Start date
  --to YYYY-MM-DD             End date

Common options:
  --class-code VALUE          Default: SPBFUT
  --timeframe VALUE           Default: 1m
  --profile VALUE             Default: balanced
  --env VALUE                 prod or sandbox, default: prod
  --params-file PATH          Default: configs/hammer_detector_<profile>.env

Backtest options:
  --entry-mode VALUE          breakout or close, default: breakout
  --take-r VALUE              Default: 1.0
  --max-hold-bars VALUE       Default: 30
  --slippage-points VALUE     Default: 0

Grid options:
  --grid-entry-modes VALUE
  --grid-take-r-values VALUE
  --grid-max-hold-bars-values VALUE
  --grid-stop-buffer-points-values VALUE
  --grid-slippage-points-values VALUE

Flags:
  --skip-load                 Do not call T-Bank API, use existing raw CSV
  --skip-grid                 Skip single grid backtest
  --skip-walkforward-grid     Skip daily/weekly walk-forward grid
  --no-archive                Do not create zip archive
  --help                      Show this help
```

---

# Часть 3. Run ID и файлы результатов

Скрипт должен формировать `RUN_ID`:

```text
${TICKER}_${TIMEFRAME}_${START_DATE}_${END_DATE}_${PROFILE}
```

Например:

```text
SiM6_1m_2026-03-01_2026-04-10_balanced
```

Все файлы должны сохраняться с этим `RUN_ID`.

## Важное изменение

Сейчас debug CSV сохраняется как:

```text
out/debug_simple_all.csv
```

Нужно сохранить совместимость, но также сохранять архивируемую копию.

Сделать так:

```text
DEBUG_CSV="out/debug_simple_all.csv"
DEBUG_CSV_RUN="out/debug_simple_all_${RUN_ID}.csv"
```

После шага детектора:

```bash
cp "${DEBUG_CSV}" "${DEBUG_CSV_RUN}"
```

И дальше для всех последующих шагов лучше использовать:

```text
DEBUG_CSV_RUN
```

То есть backtest/debug_report/walkforward должны читать run-specific debug CSV.

Это позволит не путать результаты разных прогонов.

---

# Часть 4. Структура output-файлов

Скрипт должен создавать:

```text
data/raw/tbank/${RUN_ID}.csv

out/debug_simple_all_${RUN_ID}.csv

out/backtest_trades_${RUN_ID}.csv
out/backtest_grid_results_${RUN_ID}.csv

out/walkforward_period_results_${RUN_ID}_week.csv
out/walkforward_trades_${RUN_ID}_week.csv
out/walkforward_grid_results_${RUN_ID}_day.csv
out/walkforward_grid_results_${RUN_ID}_week.csv

reports/data_quality_${RUN_ID}.md
reports/debug_report_${RUN_ID}.md
reports/backtest_report_${RUN_ID}.md
reports/backtest_grid_report_${RUN_ID}.md
reports/walkforward_report_${RUN_ID}_week.md
reports/walkforward_grid_report_${RUN_ID}_day.md
reports/walkforward_grid_report_${RUN_ID}_week.md

archives/research_${RUN_ID}.zip
```

---

# Часть 5. Архивирование результатов

Добавить в конец скрипта сборку архива:

```text
archives/research_${RUN_ID}.zip
```

В архив должны попасть:

```text
data/raw/tbank/${RUN_ID}.csv

out/debug_simple_all_${RUN_ID}.csv
out/backtest_trades_${RUN_ID}.csv
out/backtest_grid_results_${RUN_ID}.csv
out/walkforward_period_results_${RUN_ID}_week.csv
out/walkforward_trades_${RUN_ID}_week.csv
out/walkforward_grid_results_${RUN_ID}_day.csv
out/walkforward_grid_results_${RUN_ID}_week.csv

reports/data_quality_${RUN_ID}.md
reports/debug_report_${RUN_ID}.md
reports/backtest_report_${RUN_ID}.md
reports/backtest_grid_report_${RUN_ID}.md
reports/walkforward_report_${RUN_ID}_week.md
reports/walkforward_grid_report_${RUN_ID}_day.md
reports/walkforward_grid_report_${RUN_ID}_week.md
```

## Требования к архиву

1. Если флаг `--no-archive` не передан — архив создаётся.
2. Если флаг `--no-archive` передан — архив не создаётся.
3. Если часть шагов пропущена через `--skip-grid` или `--skip-walkforward-grid`, архив должен включить только существующие файлы.
4. Если `zip` не установлен — вывести понятную ошибку.
5. Не включать `.env`.
6. Не включать токены.
7. Не включать служебные кэши Python.
8. В конце вывести путь к архиву.

---

# Часть 6. Skip-load режим

Добавить флаг:

```text
--skip-load
```

Он нужен, чтобы не ходить в T-Bank API повторно.

Поведение:

Если `--skip-load` задан:

1. шаг загрузки свечей пропускается;
2. скрипт ожидает, что файл уже существует:

```text
data/raw/tbank/${RUN_ID}.csv
```

3. если файла нет — ошибка:

```text
--skip-load was provided, but raw candles file does not exist:
data/raw/tbank/${RUN_ID}.csv
```

Пример:

```bash
./scripts/run_full_research_pipeline.sh   --ticker SiM6   --from 2026-03-01   --to 2026-04-10   --profile balanced   --skip-load
```

---

# Часть 7. Skip-grid режимы

Добавить:

```text
--skip-grid
--skip-walkforward-grid
```

## --skip-grid

Пропускает:

```text
scripts/run_backtest_grid.py
```

Но НЕ пропускает:

```text
single backtest
weekly walk-forward
```

## --skip-walkforward-grid

Пропускает:

```text
daily walk-forward grid
weekly walk-forward grid
```

Это полезно, если нужно быстро прогнать только базовый анализ.

---

# Часть 8. Безопасность

Скрипт должен:

1. не печатать `.env`;
2. не печатать токены;
3. не принимать токены аргументами CLI;
4. не сохранять `.env` в архив;
5. не делать real/sandbox orders;
6. не подключаться к broker execution;
7. не вызывать никаких скриптов, связанных с заявками.

---

# Часть 9. README

Обновить README.

Добавить раздел:

```markdown
## Full research pipeline
```

Описать:

1. Что делает full pipeline.
2. Какие шаги он запускает.
3. Как запустить базовый вариант.
4. Как запустить другой период.
5. Как запустить с `--skip-load`.
6. Как отключить архив.
7. Где найти архив.
8. Что запускать должен пользователь локально, потому что T-Bank API может быть недоступен из Claude Code/VPN-окружения.

Пример:

```bash
./scripts/run_full_research_pipeline.sh   --ticker SiM6   --class-code SPBFUT   --from 2026-03-01   --to 2026-04-10   --timeframe 1m   --profile balanced   --env prod
```

Пример с пропуском загрузки:

```bash
./scripts/run_full_research_pipeline.sh   --ticker SiM6   --from 2026-03-01   --to 2026-04-10   --profile balanced   --skip-load
```

---

# Часть 10. Тестирование

Так как это bash-скрипт, достаточно сделать лёгкие проверки.

Не нужно запускать T-Bank API.

## Что можно проверить

1. `./scripts/run_full_research_pipeline.sh --help`
2. запуск без `--ticker` даёт понятную ошибку;
3. запуск с `--skip-load`, когда raw CSV отсутствует, даёт понятную ошибку;
4. `shellcheck`, если доступен;
5. существующие unit-тесты:

```bash
pytest
```

Если `shellcheck` не установлен, не считать это ошибкой, просто указать в отчёте.

## Важно

Не запускать полный pipeline внутри Claude Code.

---

# Definition of Done

Задача выполнена, если:

1. `scripts/run_full_research_pipeline.sh` принимает CLI-аргументы.
2. Минимальный запуск выглядит так:

```bash
./scripts/run_full_research_pipeline.sh   --ticker SiM6   --from 2026-03-01   --to 2026-04-10
```

3. Можно переопределить:

```text
ticker
class_code
from
to
timeframe
profile
env
params_file
entry/backtest/grid parameters
```

4. Есть `--help`.
5. Есть `--skip-load`.
6. Есть `--skip-grid`.
7. Есть `--skip-walkforward-grid`.
8. Есть `--no-archive`.
9. Debug CSV сохраняется в двух вариантах:

```text
out/debug_simple_all.csv
out/debug_simple_all_${RUN_ID}.csv
```

10. Все run-specific результаты сохраняются с `RUN_ID`.
11. Создаётся архив:

```text
archives/research_${RUN_ID}.zip
```

12. Архив не содержит `.env` и токены.
13. README обновлён.
14. Полный pipeline не запускался из Claude Code.
15. Существующие тесты проходят:

```bash
pytest
```

---

# Отчёт после выполнения

После реализации напиши:

```text
Что изменено:
...

Как теперь запускать full pipeline:
...

Как запускать другой период:
...

Как использовать --skip-load:
...

Как отключить тяжёлые grid-шаги:
...

Где создаётся архив:
...

Что попадает в архив:
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
Полный pipeline не запускался из Claude Code, потому что он обращается к T-Bank API, а пользователь запускает Claude Code с VPN, при котором доступ к T-Bank может отсутствовать.
```

В блоке "Что пока не реализовано" указать:

```text
- live trading не реализован;
- sandbox orders не реализованы;
- broker execution не реализован;
- order book liquidity не моделируется;
- partial fills не моделируются;
- queue position не моделируется;
- margin requirements / ГО не моделируются.
```
