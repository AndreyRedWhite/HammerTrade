# Задача MVP-1.2: Multi-period / Walk-forward Backtest Report

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
Backtest robustness / grid analysis -> out/backtest_grid_results.csv -> reports/backtest_grid_report.md
```

MVP-1.1 показал очень хороший первый результат на коротком участке SiM6 1m:

```text
512 сценариев
511 прибыльных
лучший: +11 437 RUB
худший: -137 RUB
```

Но это всего несколько торговых дней. Теперь нужно проверить, является ли результат устойчивым на разных периодах рынка, а не эффектом одного удачного куска истории.

---

## Цель MVP-1.2

Добавить multi-period / walk-forward анализ.

Главный вопрос:

```text
прибыль распределена стабильно по периодам или весь результат сделан одним удачным участком?
```

Нужно уметь:

1. брать большой `debug_simple_all.csv`;
2. разбивать его на периоды:
   - по дням;
   - по неделям;
   - по месяцам;
3. запускать backtest или grid backtest на каждом периоде отдельно;
4. сохранять таблицу результатов по периодам;
5. строить Markdown-отчёт;
6. считать устойчивость стратегии;
7. считать концентрацию прибыли;
8. отдельно анализировать BUY и SELL;
9. находить худшие периоды.

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
- изменение правил детектора;
- изменение `debug_simple_all.csv`;
- работу с full-access token;
- автоподбор параметров с целью максимизации прибыли.

Эта задача только про offline multi-period research/backtest.

---

# Входные данные

Основной вход:

```text
out/debug_simple_all.csv
```

Файл содержит свечи, геометрию, сигналы и причины отказа.

Обязательные колонки:

```text
timestamp
instrument
timeframe
open
high
low
close
volume
direction_candidate
is_signal
fail_reason
params_profile
```

Backtest engine уже есть:

```text
src/backtest/
  models.py
  engine.py
  metrics.py
  report.py
  batch.py
  grid_report.py
```

Нужно использовать существующую логику backtest/grid, а не писать второй независимый backtest с нуля.

---

# Важное требование по timestamp

`timestamp` может быть UTC:

```text
2026-04-01 06:50:00+00:00
```

Для группировки по торговым дням и неделям нужно использовать московское время:

```text
Europe/Moscow
```

То есть:

```text
любой timestamp -> Europe/Moscow -> period key
```

Примеры:

```text
UTC 2026-04-01 20:49:00+00:00 = MSK 2026-04-01 23:49:00
```

Период должен определяться по MSK, а не по UTC.

---

# Часть 1. Period splitter

Добавить модуль:

```text
src/backtest/periods.py
```

Реализовать функции:

```python
def add_moscow_timestamp(df, timestamp_col: str = "timestamp") -> pandas.DataFrame:
    ...
```

```python
def assign_period(df, period: str, timezone: str = "Europe/Moscow") -> pandas.DataFrame:
    ...
```

Поддержать `period`:

```text
day
week
month
```

## period_key

Для `day`:

```text
YYYY-MM-DD
```

Пример:

```text
2026-04-01
```

Для `week`:

```text
YYYY-Www
```

Пример:

```text
2026-W14
```

Для `month`:

```text
YYYY-MM
```

Пример:

```text
2026-04
```

Добавить колонки:

```text
timestamp_msk
period_key
period_start
period_end
```

`period_start` и `period_end` должны быть в MSK.

---

# Часть 2. Multi-period single backtest

Добавить модуль:

```text
src/backtest/walkforward.py
```

Реализовать:

```python
def run_period_backtests(
    debug_df,
    period: str = "week",
    entry_mode: str = "breakout",
    entry_horizon_bars: int = 3,
    max_hold_bars: int = 30,
    take_r: float = 1.0,
    stop_buffer_points: float = 0.0,
    slippage_points: float = 0.0,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
    allow_overlap: bool = False,
) -> tuple[pandas.DataFrame, pandas.DataFrame]:
    ...
```

Функция должна вернуть:

```text
period_results_df
all_period_trades_df
```

## period_results_df

Одна строка на период.

Колонки:

```text
period_key
period_start
period_end
rows
signals
closed_trades
skipped_trades
wins
losses
timeouts
winrate
gross_pnl_rub
net_pnl_rub
avg_net_pnl_rub
median_net_pnl_rub
profit_factor
max_drawdown_rub
max_drawdown_pct
ending_equity_rub
avg_bars_held
buy_trades
sell_trades
buy_net_pnl_rub
sell_net_pnl_rub
```

## all_period_trades_df

Все сделки из всех периодов.

Добавить колонку:

```text
period_key
```

---

# Важный момент про сделки на границе периодов

В MVP-1.2 использовать простое правило:

```text
сделка должна полностью моделироваться только внутри своего периода
```

То есть если сигнал в пятницу вечером и выход был бы уже в следующем периоде, в рамках period backtest сделка закрывается по `end_of_data` внутри текущего периода.

Это сделано намеренно, чтобы каждый период был независимым.

В отчёте явно написать, что period backtest изолирует периоды и не переносит сделки через границы периода.

---

# Часть 3. Multi-period grid backtest

Реализовать:

```python
def run_period_grid_backtests(
    debug_df,
    period: str,
    entry_modes: list[str],
    take_r_values: list[float],
    max_hold_bars_values: list[int],
    stop_buffer_points_values: list[float],
    slippage_points_values: list[float],
    entry_horizon_bars: int = 3,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
) -> pandas.DataFrame:
    ...
```

Результат:

```text
out/walkforward_grid_results.csv
```

Одна строка = один сценарий на один период.

Колонки:

```text
period_key
period_start
period_end
scenario_id
entry_mode
entry_horizon_bars
take_r
max_hold_bars
stop_buffer_points
slippage_points
contracts
rows
total_signals
closed_trades
skipped_trades
wins
losses
timeouts
winrate
gross_pnl_rub
net_pnl_rub
avg_net_pnl_rub
median_net_pnl_rub
profit_factor
max_drawdown_rub
max_drawdown_pct
ending_equity_rub
avg_bars_held
buy_trades
sell_trades
buy_net_pnl_rub
sell_net_pnl_rub
```

---

# Часть 4. Stability metrics

Добавить модуль:

```text
src/backtest/stability.py
```

Реализовать:

```python
def calculate_period_stability(period_results_df) -> dict:
    ...
```

Метрики:

```text
periods_total
profitable_periods
losing_periods
flat_periods
profitable_periods_pct
avg_period_net_pnl_rub
median_period_net_pnl_rub
best_period_net_pnl_rub
worst_period_net_pnl_rub
std_period_net_pnl_rub
total_net_pnl_rub
max_period_drawdown_rub
period_profit_factor
buy_total_net_pnl_rub
sell_total_net_pnl_rub
buy_profitable_periods
sell_profitable_periods
```

## period_profit_factor

Считать по периодам:

```text
sum positive period net pnl / abs(sum negative period net pnl)
```

Если отрицательных периодов нет и положительные есть:

```text
inf
```

---

# Часть 5. Profit concentration

Добавить расчёт концентрации прибыли.

Функция:

```python
def calculate_profit_concentration(trades_df, period_results_df) -> dict:
    ...
```

Метрики:

```text
top_10pct_trades_profit_share
top_20pct_trades_profit_share
best_trade_profit_share
best_period_profit_share
top_2_periods_profit_share
```

## Правила

Считать только closed trades с `net_pnl_rub > 0` для trade concentration.

Пример:

```text
если 4 лучших сделки дают 80% всей положительной прибыли, top_10pct_trades_profit_share может быть высоким
```

Для period concentration:

```text
best_period_profit_share = best positive period pnl / total positive period pnl
```

Если total positive profit = 0, возвращать 0.

---

# Часть 6. Walk-forward report

Добавить модуль:

```text
src/backtest/walkforward_report.py
```

Создать Markdown-отчёт:

```text
reports/walkforward_report.md
```

Структура:

```markdown
# Walk-forward Backtest Report

## Parameters

| Parameter | Value |
|---|---:|
| Period | week |
| Entry mode | breakout |
| Entry horizon bars | 3 |
| Max hold bars | 30 |
| Take R | 1.0 |
| Stop buffer points | 0 |
| Slippage points | 0 |
| Point value RUB | 10 |
| Commission per trade | 0.025 |
| Contracts | 1 |
| Allow overlap | false |

## Stability Summary

| Metric | Value |
|---|---:|
| Periods total | ... |
| Profitable periods | ... |
| Losing periods | ... |
| Profitable periods % | ... |
| Total net PnL RUB | ... |
| Avg period net PnL RUB | ... |
| Median period net PnL RUB | ... |
| Best period net PnL RUB | ... |
| Worst period net PnL RUB | ... |
| Period profit factor | ... |

## Profit Concentration

| Metric | Value |
|---|---:|
| Top 10% trades profit share | ... |
| Top 20% trades profit share | ... |
| Best trade profit share | ... |
| Best period profit share | ... |
| Top 2 periods profit share | ... |

## Period Results

| period_key | period_start | period_end | signals | closed_trades | winrate | net_pnl_rub | profit_factor | max_drawdown_rub | buy_net_pnl_rub | sell_net_pnl_rub |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|

## Worst Periods

| period_key | net_pnl_rub | closed_trades | winrate | profit_factor | max_drawdown_rub |
|---|---:|---:|---:|---:|---:|

## Best Periods

| period_key | net_pnl_rub | closed_trades | winrate | profit_factor | max_drawdown_rub |
|---|---:|---:|---:|---:|---:|

## Direction Breakdown

| Direction | Total net PnL RUB | Profitable periods | Trades |
|---|---:|---:|---:|
| BUY | ... | ... | ... |
| SELL | ... | ... | ... |

## Notes

This is an offline walk-forward / multi-period analysis.
Periods are isolated: trades do not carry over across period boundaries.
The report does not include live trading, sandbox orders, order book liquidity, queue position, partial fills or real broker execution.
```

---

# Часть 7. Walk-forward grid report

Создать Markdown-отчёт:

```text
reports/walkforward_grid_report.md
```

Цель — понять, какие сценарии устойчивы не просто в целом, а по периодам.

Структура:

```markdown
# Walk-forward Grid Report

## Input

| Field | Value |
|---|---|
| Source | out/debug_simple_all.csv |
| Period | week |
| Scenarios | ... |
| Periods | ... |

## Scenario Stability Ranking

| scenario_id | entry_mode | take_r | max_hold_bars | stop_buffer_points | slippage_points | periods_total | profitable_periods_pct | total_net_pnl_rub | worst_period_net_pnl_rub | period_profit_factor |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|

## Robust Scenarios

Scenarios that satisfy:

```text
periods_total >= 4
profitable_periods_pct >= 60%
total_net_pnl_rub > 0
period_profit_factor >= 1.2
worst_period_net_pnl_rub not catastrophically negative
```

| scenario_id | entry_mode | take_r | max_hold_bars | stop_buffer_points | slippage_points | profitable_periods_pct | total_net_pnl_rub | worst_period_net_pnl_rub | period_profit_factor |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|

## Fragile Scenarios

Scenarios that are profitable overall but have poor period stability.

| scenario_id | entry_mode | take_r | max_hold_bars | stop_buffer_points | slippage_points | total_net_pnl_rub | profitable_periods_pct | worst_period_net_pnl_rub |
|---:|---|---:|---:|---:|---:|---:|---:|---:|

## Notes

Grid walk-forward is used to evaluate robustness, not to overfit parameters.
```

---

# Часть 8. CLI для single walk-forward

Создать:

```text
scripts/run_walkforward.py
```

Пример запуска:

```bash
python scripts/run_walkforward.py \
  --input out/debug_simple_all.csv \
  --period week \
  --period-results-output out/walkforward_period_results.csv \
  --trades-output out/walkforward_trades.csv \
  --report-output reports/walkforward_report.md \
  --entry-mode breakout \
  --entry-horizon-bars 3 \
  --max-hold-bars 30 \
  --take-r 1.0 \
  --stop-buffer-points 0 \
  --slippage-points 0 \
  --point-value-rub 10 \
  --commission-per-trade 0.025 \
  --contracts 1
```

Поддержать:

```text
--period day
--period week
--period month
```

Console summary:

```text
Walk-forward Backtest
=====================

Input: out/debug_simple_all.csv
Period: week
Periods: ...
Total signals: ...
Total net PnL RUB: ...
Profitable periods: ...
Losing periods: ...
Profitable periods %: ...
Best period: ...
Worst period: ...

Period results output: out/walkforward_period_results.csv
Trades output: out/walkforward_trades.csv
Report output: reports/walkforward_report.md
```

---

# Часть 9. CLI для walk-forward grid

Создать:

```text
scripts/run_walkforward_grid.py
```

Пример запуска:

```bash
python scripts/run_walkforward_grid.py \
  --input out/debug_simple_all.csv \
  --period week \
  --output out/walkforward_grid_results.csv \
  --report-output reports/walkforward_grid_report.md \
  --entry-modes breakout,close \
  --take-r-values 0.5,1.0,1.5,2.0 \
  --max-hold-bars-values 5,10,30,60 \
  --stop-buffer-points-values 0,1,2,5 \
  --slippage-points-values 0,1,2,5 \
  --entry-horizon-bars 3 \
  --point-value-rub 10 \
  --commission-per-trade 0.025 \
  --contracts 1
```

Console summary:

```text
Walk-forward Grid Backtest
==========================

Input: out/debug_simple_all.csv
Period: week
Scenarios: ...
Periods: ...
Rows: ...
Profitable scenario-period rows: ...
Output: out/walkforward_grid_results.csv
Report: reports/walkforward_grid_report.md
```

---

# Часть 10. Тесты

Добавить тесты без обращения к T-Bank API.

## tests/test_backtest_periods.py

Проверить:

1. UTC timestamp корректно конвертируется в Europe/Moscow.
2. day period key считается по MSK, а не UTC.
3. week period key считается корректно.
4. month period key считается корректно.
5. naive datetime трактуется как Europe/Moscow или обрабатывается явно и предсказуемо.

Пример важного кейса:

```text
2026-04-01 21:30:00+00:00 = 2026-04-02 00:30:00 MSK
```

Для `period=day` period_key должен быть:

```text
2026-04-02
```

---

## tests/test_walkforward.py

Проверить:

1. данные разбиваются на несколько периодов;
2. для каждого периода считается отдельный backtest;
3. period_results_df содержит нужные колонки;
4. all_period_trades_df содержит `period_key`;
5. период без сигналов не ломает отчёт;
6. сделки не переносятся через границу периода.

---

## tests/test_stability.py

Проверить:

1. profitable_periods;
2. losing_periods;
3. profitable_periods_pct;
4. period_profit_factor;
5. buy/sell aggregation.

---

## tests/test_profit_concentration.py

Проверить:

1. top_10pct_trades_profit_share;
2. top_20pct_trades_profit_share;
3. best_trade_profit_share;
4. best_period_profit_share;
5. если прибыли нет — все shares равны 0.

---

## tests/test_walkforward_grid.py

Проверить:

1. grid создаёт строки для каждого scenario x period;
2. количество строк корректное;
3. report создаётся;
4. robust/fragile sections формируются;
5. обязательные колонки есть.

---

# Часть 11. README

Обновить README.

Добавить раздел:

```markdown
## Walk-forward / multi-period backtest
```

Объяснить:

1. Зачем нужен multi-period анализ.
2. Что периоды считаются по Moscow time.
3. Что сделки не переносятся через границы периода.
4. Как запустить single walk-forward.
5. Как запустить walk-forward grid.
6. Как читать отчёт.
7. Что это не live trading и не доказательство прибыльности.

Пример запуска:

```bash
python scripts/run_walkforward.py \
  --input out/debug_simple_all.csv \
  --period week \
  --period-results-output out/walkforward_period_results.csv \
  --trades-output out/walkforward_trades.csv \
  --report-output reports/walkforward_report.md \
  --entry-mode breakout \
  --max-hold-bars 30 \
  --take-r 1.0 \
  --slippage-points 1
```

---

# Definition of Done

Задача выполнена, если:

1. Есть модуль:

```text
src/backtest/periods.py
src/backtest/walkforward.py
src/backtest/stability.py
src/backtest/walkforward_report.py
```

2. Есть CLI:

```text
scripts/run_walkforward.py
scripts/run_walkforward_grid.py
```

3. Single walk-forward запускается:

```bash
python scripts/run_walkforward.py \
  --input out/debug_simple_all.csv \
  --period week \
  --period-results-output out/walkforward_period_results.csv \
  --trades-output out/walkforward_trades.csv \
  --report-output reports/walkforward_report.md \
  --entry-mode breakout \
  --entry-horizon-bars 3 \
  --max-hold-bars 30 \
  --take-r 1.0 \
  --stop-buffer-points 0 \
  --slippage-points 0 \
  --point-value-rub 10 \
  --commission-per-trade 0.025 \
  --contracts 1
```

4. Walk-forward grid запускается:

```bash
python scripts/run_walkforward_grid.py \
  --input out/debug_simple_all.csv \
  --period week \
  --output out/walkforward_grid_results.csv \
  --report-output reports/walkforward_grid_report.md \
  --entry-modes breakout,close \
  --take-r-values 0.5,1.0,1.5,2.0 \
  --max-hold-bars-values 5,10,30,60 \
  --stop-buffer-points-values 0,1,2,5 \
  --slippage-points-values 0,1,2,5 \
  --entry-horizon-bars 3 \
  --point-value-rub 10 \
  --commission-per-trade 0.025 \
  --contracts 1
```

5. Создаются файлы:

```text
out/walkforward_period_results.csv
out/walkforward_trades.csv
reports/walkforward_report.md
out/walkforward_grid_results.csv
reports/walkforward_grid_report.md
```

6. Периоды считаются по Europe/Moscow.
7. Есть метрики устойчивости по периодам.
8. Есть profit concentration metrics.
9. Есть BUY/SELL breakdown по периодам.
10. Тесты проходят:

```bash
pytest
```

11. В проекте не добавлены live trading, sandbox orders, real orders или broker execution.

---

# Отчёт после выполнения

После реализации напиши:

```text
Что добавлено:
...

Как запустить single walk-forward:
...

Как запустить walk-forward grid:
...

Какие файлы создаются:
...

Какие новые метрики появились:
...

Первый результат на текущем debug_simple_all.csv:
...

Какие тесты добавлены:
...

Что пока не реализовано:
...
```

В блоке "Что пока не реализовано" обязательно указать:

```text
- live trading не реализован;
- sandbox orders не реализованы;
- broker execution не реализован;
- order book liquidity не моделируется;
- partial fills не моделируются;
- queue position не моделируется;
- margin requirements / ГО не моделируются;
- walk-forward анализ не является доказательством прибыльности стратегии;
- walk-forward grid нужен для проверки устойчивости, а не для подгонки параметров под историю.
```
