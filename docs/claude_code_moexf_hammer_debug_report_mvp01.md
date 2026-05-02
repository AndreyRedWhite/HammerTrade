# Задача MVP-0.1: Debug-анализатор для результатов HammerDetector

## Контекст

В проекте уже реализован MVP-0:

```text
CSV candles -> candle geometry -> hammer detector -> out/debug_simple_all.csv
```

Сейчас нужно добавить небольшой аналитический слой поверх `out/debug_simple_all.csv`, чтобы быстро понимать качество работы детектора.

Live trading, broker API и реальные заявки по-прежнему запрещены.

## Цель задачи

Создать CLI-скрипт, который читает `out/debug_simple_all.csv` и выводит понятную статистику:

- сколько всего свечей обработано;
- сколько найдено сигналов;
- сколько BUY и SELL сигналов;
- распределение `fail_reason`;
- распределение `fail_reason` отдельно для BUY-кандидатов и SELL-кандидатов;
- список последних/первых сигналов;
- сохранение краткого отчёта в Markdown.

## Что нужно реализовать

Добавить файл:

```text
src/analytics/debug_report.py
```

И CLI-команду или отдельный режим в `src/main.py`.

Допустимые варианты запуска:

```bash
python -m src.analytics.debug_report \
  --input out/debug_simple_all.csv \
  --output reports/debug_report.md
```

или:

```bash
python -m src.main debug-report \
  --input out/debug_simple_all.csv \
  --output reports/debug_report.md
```

Выбери более простой и надёжный вариант.

## Входной файл

На вход подаётся:

```text
out/debug_simple_all.csv
```

В нём уже есть колонки:

```text
timestamp
instrument
timeframe
open
high
low
close
volume
range
body
upper_shadow
lower_shadow
body_frac
upper_frac
lower_frac
close_pos
direction_candidate
is_signal
fail_reason
fail_reasons
params_profile
```

## Что вывести в консоль

Пример:

```text
Debug report
============

Input: out/debug_simple_all.csv
Rows: 12500
Signals: 42
BUY signals: 25
SELL signals: 17

Top fail_reason:
- no_candidate: 8700
- ext: 1400
- dom_fail: 850
- close_pos: 500
- confirm: 320

BUY candidates fail_reason:
- ext: ...
- close_pos: ...
- confirm: ...

SELL candidates fail_reason:
- ext: ...
- dom_fail: ...
- opp_abs: ...

Signals by hour:
10:00 - 5
11:00 - 8
12:00 - 3
...
```

## Что сохранить в Markdown

Создать файл:

```text
reports/debug_report.md
```

Структура отчёта:

```markdown
# Hammer Detector Debug Report

## Summary

| Metric | Value |
|---|---:|
| Rows processed | ... |
| Signals found | ... |
| BUY signals | ... |
| SELL signals | ... |
| Profile | balanced |
| Instrument | SiM6 |
| Timeframe | 1m |

## Top fail_reason

| fail_reason | count | percent |
|---|---:|---:|
| no_candidate | ... | ... |
| ext | ... | ... |
| dom_fail | ... | ... |

## BUY candidates fail_reason

| fail_reason | count | percent |
|---|---:|---:|

## SELL candidates fail_reason

| fail_reason | count | percent |
|---|---:|---:|

## Signals by hour

| hour | signals |
|---|---:|
| 10:00 | ... |
| 11:00 | ... |

## Signals

| timestamp | direction_candidate | open | high | low | close | fail_reason |
|---|---|---:|---:|---:|---:|---|

## Notes

This report is based on explainable detector output.
It does not include P&L, entries, exits, slippage or backtest results.
```

## Дополнительные требования

1. Если входного файла нет — вывести понятную ошибку.
2. Если нет обязательных колонок — вывести понятную ошибку.
3. Если сигналов нет — отчёт всё равно должен создаваться.
4. Проценты считать от общего количества строк.
5. Для `Signals by hour` использовать час из `timestamp`.
6. Не добавлять broker API.
7. Не добавлять live trading.
8. Не менять логику самого детектора в этой задаче.

## Тесты

Добавить тесты:

```text
tests/test_debug_report.py
```

Проверить:

1. отчёт создаётся;
2. корректно считается количество строк;
3. корректно считается количество сигналов;
4. корректно считается распределение `fail_reason`;
5. если сигналов нет, отчёт всё равно создаётся.

## Definition of Done

Задача выполнена, если:

1. Команда запускается:

```bash
python -m src.analytics.debug_report \
  --input out/debug_simple_all.csv \
  --output reports/debug_report.md
```

2. Создаётся файл:

```text
reports/debug_report.md
```

3. В отчёте есть summary.
4. В отчёте есть top fail_reason.
5. В отчёте есть BUY/SELL-разбивка.
6. В отчёте есть список сигналов или сообщение, что сигналов нет.
7. Тесты проходят:

```bash
pytest
```

8. В проекте по-прежнему нет live trading, broker API и реальных заявок.

## В конце работы дай отчёт

Напиши:

```text
Что добавлено:
...

Как запустить:
...

Какие файлы создаются:
...

Какие тесты добавлены:
...

Что пока не реализовано:
...
```

## Важное ограничение

Эта задача не про улучшение торговой логики и не про backtest.

Не нужно менять параметры детектора, порядок фильтров, условия сигналов или структуру `debug_simple_all.csv`, если это не требуется для чтения отчёта.

Цель задачи — только сделать удобный аналитический отчёт поверх уже существующего debug CSV.
