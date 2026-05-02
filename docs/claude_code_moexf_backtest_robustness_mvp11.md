# Задача MVP-1.1: Backtest Robustness / Sensitivity Analysis

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
```

Первый backtest v1 на SiM6 1m показал позитивный результат:

```text
Signals: 41
Closed trades: 40
Skipped trades: 1
Entry mode: breakout
Take R: 1.0
Net PnL RUB: 5708.00
Winrate: 75.0%
Profit factor: 3.21
```

Но это пока слишком идеальная модель исполнения:

```text
entry = ровно по breakout price
exit = ровно по stop/take price
slippage = 0
order book liquidity не учитывается
partial fills не учитываются
```

Теперь нужно проверить устойчивость результата к разным параметрам входа/выхода и к проскальзыванию.

---

## Цель MVP-1.1

Добавить пакетный backtest по сетке параметров и простую модель slippage.

Главный вопрос:

```text
стратегия остаётся положительной при менее идеальных условиях или результат ломается от небольшого изменения параметров?
```

Нужно получить таблицу сценариев:

```text
entry_mode
take_r
max_hold_bars
stop_buffer_points
slippage_points
closed_trades
winrate
net_pnl_rub
profit_factor
avg_net_pnl_rub
max_drawdown_rub
buy_net_pnl_rub
sell_net_pnl_rub
```

И Markdown-отчёт с выводами.

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
- автоподбор параметров с целью максимизации прибыли;
- изменение логики HammerDetector;
- изменение `debug_simple_all.csv`;
- работу с full-access token;
- подключение брокерских order endpoints.

Эта задача только про offline robustness-анализ на уже готовом `out/debug_simple_all.csv`.

---

# Входные данные

Основной вход:

```text
out/debug_simple_all.csv
```

Файл содержит сигналы детектора.

Уже есть backtest engine:

```text
src/backtest/
  models.py
  engine.py
  metrics.py
  report.py
```

И CLI:

```text
scripts/run_backtest.py
```

Нужно аккуратно расширить текущий backtest, не ломая существующий CLI.

---

# Часть 1. Добавить slippage model

## Требование

Добавить параметр:

```text
--slippage-points
```

По умолчанию:

```text
0
```

Slippage должен ухудшать цену входа и выхода.

## Правила slippage

### BUY

Вход хуже:

```text
entry_price_adjusted = entry_price + slippage_points
```

Выход хуже:

- если exit по take:

```text
exit_price_adjusted = exit_price - slippage_points
```

- если exit по stop:

```text
exit_price_adjusted = exit_price - slippage_points
```

- если exit по timeout/end_of_data:

```text
exit_price_adjusted = exit_price - slippage_points
```

То есть для BUY выход всегда хуже вниз.

### SELL

Вход хуже:

```text
entry_price_adjusted = entry_price - slippage_points
```

Выход хуже:

- если exit по take:

```text
exit_price_adjusted = exit_price + slippage_points
```

- если exit по stop:

```text
exit_price_adjusted = exit_price + slippage_points
```

- если exit по timeout/end_of_data:

```text
exit_price_adjusted = exit_price + slippage_points
```

То есть для SELL выход всегда хуже вверх.

## Важный момент

В trade output нужно сохранить и оригинальные цены, и adjusted prices.

Добавить колонки:

```text
entry_price_raw
exit_price_raw
entry_price
exit_price
slippage_points
```

Где:

```text
entry_price_raw / exit_price_raw — цена по старой модели
entry_price / exit_price — цена после применения slippage
```

Если сейчас в проекте уже есть `entry_price` и `exit_price`, можно:

1. оставить их как adjusted;
2. добавить `entry_price_raw`, `exit_price_raw`;
3. обновить отчёт и тесты.

---

# Часть 2. Max drawdown

Добавить расчёт max drawdown по equity curve.

## Требование

В `src/backtest/metrics.py` добавить:

```python
max_drawdown_rub
max_drawdown_pct
```

Логика:

- учитывать только closed trades;
- equity curve = cumulative sum `net_pnl_rub`;
- max drawdown = максимальное падение от предыдущего equity peak;
- если equity никогда не была выше 0, считать аккуратно без деления на ноль;
- `max_drawdown_pct` считать относительно equity peak, если peak > 0, иначе 0.

Также желательно добавить:

```text
ending_equity_rub
min_equity_rub
max_equity_rub
```

---

# Часть 3. Batch backtest runner

Добавить новый модуль:

```text
src/backtest/batch.py
```

И CLI:

```text
scripts/run_backtest_grid.py
```

## CLI-пример

```bash
python scripts/run_backtest_grid.py \
  --input out/debug_simple_all.csv \
  --output out/backtest_grid_results.csv \
  --report-output reports/backtest_grid_report.md \
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

## Что должен делать batch runner

Для каждой комбинации параметров:

```text
entry_mode
take_r
max_hold_bars
stop_buffer_points
slippage_points
```

запустить существующий backtest engine.

Собрать одну строку результата со следующими колонками:

```text
scenario_id
entry_mode
entry_horizon_bars
take_r
max_hold_bars
stop_buffer_points
slippage_points
contracts
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
max_win_rub
max_loss_rub
max_drawdown_rub
max_drawdown_pct
avg_bars_held
buy_trades
sell_trades
buy_net_pnl_rub
sell_net_pnl_rub
```

Сохранить:

```text
out/backtest_grid_results.csv
```

---

# Часть 4. Robustness report

Добавить отчёт:

```text
reports/backtest_grid_report.md
```

Структура отчёта:

```markdown
# Backtest Grid Report

## Input

| Field | Value |
|---|---|
| Source | out/debug_simple_all.csv |
| Scenarios | ... |
| Signals | ... |
| Point value RUB | 10 |
| Commission per trade | 0.025 |
| Contracts | 1 |

## Top scenarios by Net PnL

| scenario_id | entry_mode | take_r | max_hold_bars | stop_buffer_points | slippage_points | net_pnl_rub | winrate | profit_factor | max_drawdown_rub |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|

## Worst scenarios by Net PnL

| scenario_id | entry_mode | take_r | max_hold_bars | stop_buffer_points | slippage_points | net_pnl_rub | winrate | profit_factor | max_drawdown_rub |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|

## Slippage sensitivity

| slippage_points | scenarios | profitable_scenarios | avg_net_pnl_rub | median_net_pnl_rub | best_net_pnl_rub | worst_net_pnl_rub |
|---:|---:|---:|---:|---:|---:|---:|

## Take R sensitivity

| take_r | scenarios | profitable_scenarios | avg_net_pnl_rub | median_net_pnl_rub | best_net_pnl_rub | worst_net_pnl_rub |
|---:|---:|---:|---:|---:|---:|---:|

## Entry mode comparison

| entry_mode | scenarios | profitable_scenarios | avg_net_pnl_rub | median_net_pnl_rub | best_net_pnl_rub | worst_net_pnl_rub |
|---|---:|---:|---:|---:|---:|---:|

## Stop buffer sensitivity

| stop_buffer_points | scenarios | profitable_scenarios | avg_net_pnl_rub | median_net_pnl_rub | best_net_pnl_rub | worst_net_pnl_rub |
|---:|---:|---:|---:|---:|---:|---:|

## Robust scenarios

Scenarios that satisfy all conditions:

```text
net_pnl_rub > 0
profit_factor >= 1.2
closed_trades >= 20
max_drawdown_rub не слишком большой относительно net_pnl_rub
```

| scenario_id | entry_mode | take_r | max_hold_bars | stop_buffer_points | slippage_points | net_pnl_rub | profit_factor | max_drawdown_rub |
|---:|---|---:|---:|---:|---:|---:|---:|---:|

## Notes

This report is an offline robustness analysis.
It does not prove that the strategy is profitable in live trading.
It does not include order book liquidity, queue position, partial fills or real broker execution.
```

---

# Часть 5. Single backtest report update

Обновить текущий single backtest report:

```text
reports/backtest_report.md
```

Добавить в Parameters:

```text
Slippage points
```

Добавить в Summary:

```text
Max drawdown RUB
Max drawdown %
Ending equity RUB
```

Добавить в trades CSV:

```text
entry_price_raw
exit_price_raw
slippage_points
```

---

# Часть 6. Тесты

Добавить/обновить тесты.

## tests/test_backtest_slippage.py

Проверить:

### 1. BUY slippage worsens result

Один BUY trade без slippage и со slippage.

Ожидание:

```text
net_pnl_rub со slippage < net_pnl_rub без slippage
```

### 2. SELL slippage worsens result

Один SELL trade без slippage и со slippage.

Ожидание:

```text
net_pnl_rub со slippage < net_pnl_rub без slippage
```

### 3. Slippage affects both entry and exit

При `slippage_points=1` и `point_value_rub=10` итоговая сделка должна ухудшиться примерно на:

```text
2 * 1 * 10 = 20 RUB
```

без учёта комиссии.

---

## tests/test_backtest_drawdown.py

Проверить equity curve:

```text
trades net pnl: +100, +50, -80, +20, -200, +30
```

Ожидание:

```text
max_drawdown_rub = 230
```

Пояснение:

```text
peak после +100 +50 = 150
после -80 equity = 70 drawdown = 80
после +20 equity = 90 drawdown = 60
после -200 equity = -110 drawdown = 260
```

Если по этой последовательности ожидается 260, используй 260, а не 230. Главное — тест должен быть логически корректным и явно описанным.

---

## tests/test_backtest_grid.py

Проверить:

1. grid runner создаёт несколько сценариев;
2. количество строк равно произведению размеров сеток;
3. результат содержит обязательные колонки;
4. report создаётся;
5. slippage-сценарии присутствуют.

---

# Часть 7. README

Обновить README.

Добавить раздел:

```markdown
## Backtest robustness / grid search
```

Важно: не называть это оптимизацией стратегии.

Формулировка:

```text
Grid backtest используется для проверки устойчивости стратегии к изменению параметров, а не для подгонки параметров под историю.
```

Добавить пример запуска:

```bash
python scripts/run_backtest_grid.py \
  --input out/debug_simple_all.csv \
  --output out/backtest_grid_results.csv \
  --report-output reports/backtest_grid_report.md \
  --entry-modes breakout,close \
  --take-r-values 0.5,1.0,1.5,2.0 \
  --max-hold-bars-values 5,10,30,60 \
  --stop-buffer-points-values 0,1,2,5 \
  --slippage-points-values 0,1,2,5
```

---

# Definition of Done

Задача выполнена, если:

1. Single backtest поддерживает:

```text
--slippage-points
```

2. Trades CSV содержит:

```text
entry_price_raw
exit_price_raw
slippage_points
```

3. Metrics содержат:

```text
max_drawdown_rub
max_drawdown_pct
ending_equity_rub
```

4. Есть новый CLI:

```text
scripts/run_backtest_grid.py
```

5. Команда запускается:

```bash
python scripts/run_backtest_grid.py \
  --input out/debug_simple_all.csv \
  --output out/backtest_grid_results.csv \
  --report-output reports/backtest_grid_report.md \
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

6. Создаются:

```text
out/backtest_grid_results.csv
reports/backtest_grid_report.md
```

7. В grid report есть:
   - top scenarios;
   - worst scenarios;
   - slippage sensitivity;
   - take R sensitivity;
   - entry mode comparison;
   - stop buffer sensitivity;
   - robust scenarios.
8. Тесты проходят:

```bash
pytest
```

9. В проекте не добавлены live trading, sandbox orders, real orders или broker execution.

---

# Отчёт после выполнения

После реализации напиши:

```text
Что добавлено:
...

Как запустить single backtest со slippage:
...

Как запустить grid backtest:
...

Какие файлы создаются:
...

Какие новые метрики появились:
...

Первый результат grid backtest на текущем debug_simple_all.csv:
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
- grid backtest не является доказательством прибыльности стратегии;
- grid backtest нужен для проверки устойчивости, а не для подгонки параметров под историю.
```
