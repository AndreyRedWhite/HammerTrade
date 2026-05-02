# Задача MVP-1: Backtest v1 для MOEXF Hammer Bot

## Контекст проекта

Мы разрабатываем исследовательский Python-проект для фьючерсов MOEXF через Т-Инвестиции.

Текущий статус:

```text
MVP-0:
CSV candles -> candle geometry -> HammerDetector -> out/debug_simple_all.csv

MVP-0.1:
out/debug_simple_all.csv -> reports/debug_report.md

MVP-0.2:
T-Bank historical candles loader -> normalized CSV -> data quality report

MVP-0.3:
Fix clearing timezone
```

Сейчас есть рабочий пайплайн:

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

Теперь нужно добавить первый простой backtest поверх уже готового `out/debug_simple_all.csv`.

---

## Цель MVP-1

Создать простой, объяснимый backtest v1, который:

1. читает `out/debug_simple_all.csv`;
2. берёт только строки, где:

```text
is_signal=True
fail_reason=pass
```

3. моделирует вход после сигнала;
4. моделирует stop-loss и take-profit;
5. считает результат в пунктах и рублях;
6. сохраняет полный список сделок;
7. создаёт Markdown-отчёт.

Главная цель — не оптимизация прибыли, а первичная проверка:

```text
есть ли у сигналов хоть какой-то edge после учёта стопа, тейка, комиссии и клиринговых ограничений
```

---

## Что строго запрещено

Не делать:

- live trading;
- реальные заявки;
- sandbox-заявки;
- postOrder;
- postSandboxOrder;
- broker execution;
- paper trading;
- подключение к stream API;
- автоподбор параметров под максимальную прибыль;
- изменение логики HammerDetector;
- изменение `debug_simple_all.csv`;
- работу с full-access token.

Эта задача только про offline backtest на уже готовом debug CSV.

---

# Входные данные

Backtest должен читать:

```text
out/debug_simple_all.csv
```

В файле есть колонки:

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

Важно:

- timestamp может быть timezone-aware UTC;
- внутри backtest можно хранить UTC, но для отчётов желательно также добавлять Moscow time;
- не менять исходный debug CSV.

---

# Торговая модель v1

## Direction

Если:

```text
direction_candidate = BUY
```

то это long-сделка.

Если:

```text
direction_candidate = SELL
```

то это short-сделка.

---

## Entry rule

Поддержать два режима входа через CLI-параметр:

```text
--entry-mode close
--entry-mode breakout
```

### Режим close

Это самый простой режим.

BUY:

```text
entry_price = close сигнальной свечи
entry_time = timestamp сигнальной свечи
```

SELL:

```text
entry_price = close сигнальной свечи
entry_time = timestamp сигнальной свечи
```

### Режим breakout

Это более реалистичный режим.

BUY:

```text
entry_trigger = high сигнальной свечи
entry происходит на первой следующей свече, где high >= entry_trigger
entry_price = entry_trigger
```

SELL:

```text
entry_trigger = low сигнальной свечи
entry происходит на первой следующей свече, где low <= entry_trigger
entry_price = entry_trigger
```

Если вход не произошёл в течение `--entry-horizon-bars`, сделка считается пропущенной:

```text
status = skipped_no_entry
```

По умолчанию:

```text
entry_horizon_bars = 3
```

---

## Stop-loss

BUY:

```text
stop_price = low сигнальной свечи
```

SELL:

```text
stop_price = high сигнальной свечи
```

Добавить опциональный буфер в пунктах:

```text
--stop-buffer-points 0
```

BUY:

```text
stop_price = signal_low - stop_buffer_points
```

SELL:

```text
stop_price = signal_high + stop_buffer_points
```

---

## Take-profit

Take-profit считать через R-multiple.

CLI-параметр:

```text
--take-r 1.0
```

BUY:

```text
risk_points = entry_price - stop_price
take_price = entry_price + risk_points * take_r
```

SELL:

```text
risk_points = stop_price - entry_price
take_price = entry_price - risk_points * take_r
```

Если `risk_points <= 0`, сделку пропустить:

```text
status = skipped_invalid_risk
```

---

## Exit rule

После входа пройти по следующим свечам максимум `--max-hold-bars`.

По умолчанию:

```text
max_hold_bars = 30
```

Для каждой свечи после entry:

### BUY

Если в одной и той же свече одновременно достигнуты stop и take:

```text
low <= stop_price and high >= take_price
```

использовать консервативное правило:

```text
сначала stop
exit_reason = stop_same_bar
```

Иначе:

```text
если low <= stop_price -> exit stop
если high >= take_price -> exit take
```

### SELL

Если в одной и той же свече одновременно достигнуты stop и take:

```text
high >= stop_price and low <= take_price
```

использовать консервативное правило:

```text
сначала stop
exit_reason = stop_same_bar
```

Иначе:

```text
если high >= stop_price -> exit stop
если low <= take_price -> exit take
```

Если за `max_hold_bars` не достигнут ни stop, ни take:

```text
exit_price = close последней доступной свечи в окне
exit_reason = timeout
```

Если после entry не хватает свечей:

```text
exit_price = close последней доступной свечи
exit_reason = end_of_data
```

---

## Overlapping trades

В v1 сделать простой режим без одновременных сделок:

```text
--allow-overlap false
```

По умолчанию:

```text
allow_overlap = false
```

Если сделка уже открыта, все сигналы до её выхода пропускаются:

```text
status = skipped_overlap
```

Можно заложить параметр `--allow-overlap true`, но по умолчанию он должен быть выключен.

---

## Cooldown

Не добавлять новый cooldown в backtest, потому что cooldown уже применён в детекторе.

Если текущий код детектора уже отфильтровал сигналы, backtest должен использовать готовые сигналы как есть.

---

# Комиссия и стоимость пункта

Из условий проекта:

```text
1 пункт = 10 рублей
комиссия = 0.025 за сделку с фьючерсами
round-turn комиссия = 0.05
```

В backtest добавить CLI-параметры:

```text
--point-value-rub 10
--commission-per-trade 0.025
--contracts 1
```

Считать:

```text
gross_points
gross_pnl_rub
commission_rub
net_pnl_rub
```

Важно: сейчас комиссия 0.025 трактуется как фиксированная комиссия за одну операцию на 1 контракт, если в проектной документации не указано другое.

Расчёт:

```text
commission_rub = commission_per_trade * 2 * contracts
```

BUY:

```text
gross_points = exit_price - entry_price
gross_pnl_rub = gross_points * point_value_rub * contracts
net_pnl_rub = gross_pnl_rub - commission_rub
```

SELL:

```text
gross_points = entry_price - exit_price
gross_pnl_rub = gross_points * point_value_rub * contracts
net_pnl_rub = gross_pnl_rub - commission_rub
```

---

# Требуемые файлы

Добавить:

```text
src/
  backtest/
    __init__.py
    models.py
    engine.py
    metrics.py
    report.py

scripts/
  run_backtest.py

tests/
  test_backtest_engine.py
  test_backtest_metrics.py
```

Если структура проекта уже отличается, адаптировать аккуратно, но не ломать существующие модули.

---

# Модели

Файл:

```text
src/backtest/models.py
```

Создать dataclass:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class BacktestTrade:
    trade_id: int
    instrument: str
    timeframe: str
    direction: str
    signal_time: datetime
    entry_time: Optional[datetime]
    exit_time: Optional[datetime]
    signal_open: float
    signal_high: float
    signal_low: float
    signal_close: float
    entry_price: Optional[float]
    stop_price: Optional[float]
    take_price: Optional[float]
    exit_price: Optional[float]
    status: str
    exit_reason: Optional[str]
    risk_points: Optional[float]
    gross_points: Optional[float]
    gross_pnl_rub: Optional[float]
    commission_rub: Optional[float]
    net_pnl_rub: Optional[float]
    bars_held: Optional[int]
```

Допустимые `status`:

```text
closed
skipped_no_entry
skipped_invalid_risk
skipped_overlap
```

Допустимые `exit_reason`:

```text
take
stop
stop_same_bar
timeout
end_of_data
none
```

---

# Backtest engine

Файл:

```text
src/backtest/engine.py
```

Реализовать функцию:

```python
def run_backtest(
    debug_df,
    entry_mode: str = "breakout",
    entry_horizon_bars: int = 3,
    max_hold_bars: int = 30,
    take_r: float = 1.0,
    stop_buffer_points: float = 0.0,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
    allow_overlap: bool = False,
) -> pandas.DataFrame:
    ...
```

На выходе DataFrame сделок с колонками из `BacktestTrade`.

Требования:

1. Сортировать данные по `timestamp`.
2. Парсить timestamp как datetime.
3. Брать только сигналы:

```text
is_signal=True
fail_reason=pass
```

4. Для каждой сделки рассчитывать entry/stop/take/exit.
5. Не падать на пустом списке сигналов.
6. Если сигнал последний в датасете и нет будущих свечей — корректно записать `skipped_no_entry` или `end_of_data`.
7. Если `allow_overlap=false`, пропускать сигналы до выхода текущей сделки.
8. Не изменять входной DataFrame inplace.

---

# Metrics

Файл:

```text
src/backtest/metrics.py
```

Реализовать:

```python
def calculate_backtest_metrics(trades_df) -> dict:
    ...
```

Метрики:

```text
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
avg_bars_held
buy_trades
sell_trades
buy_net_pnl_rub
sell_net_pnl_rub
```

Правила:

- wins: `net_pnl_rub > 0`;
- losses: `net_pnl_rub < 0`;
- profit_factor:
  - если gross_loss == 0 и gross_profit > 0 -> `inf`;
  - если gross_profit == 0 и gross_loss == 0 -> `0`;
  - иначе `gross_profit / abs(gross_loss)`.
- skipped trades не включать в PnL-метрики, но учитывать в `total_signals` и `skipped_trades`.

---

# Report

Файл:

```text
src/backtest/report.py
```

Создать Markdown-отчёт:

```text
reports/backtest_report.md
```

Структура:

```markdown
# Backtest Report

## Parameters

| Parameter | Value |
|---|---:|
| Entry mode | breakout |
| Entry horizon bars | 3 |
| Max hold bars | 30 |
| Take R | 1.0 |
| Stop buffer points | 0 |
| Point value RUB | 10 |
| Commission per trade | 0.025 |
| Contracts | 1 |
| Allow overlap | false |

## Summary

| Metric | Value |
|---|---:|
| Total signals | ... |
| Closed trades | ... |
| Skipped trades | ... |
| Wins | ... |
| Losses | ... |
| Winrate | ... |
| Net PnL RUB | ... |
| Profit factor | ... |
| Avg net PnL RUB | ... |
| Median net PnL RUB | ... |
| Avg bars held | ... |

## By Direction

| Direction | Trades | Net PnL RUB |
|---|---:|---:|
| BUY | ... | ... |
| SELL | ... | ... |

## Exit Reasons

| Exit reason | Count |
|---|---:|
| take | ... |
| stop | ... |
| timeout | ... |
| end_of_data | ... |

## Trades

| trade_id | signal_time | direction | entry_time | entry_price | stop_price | take_price | exit_time | exit_price | status | exit_reason | net_pnl_rub |
|---:|---|---|---|---:|---:|---:|---|---:|---|---|---:|

## Notes

This is an offline historical backtest based on detector signals.
It does not place real or sandbox orders.
It does not include slippage, order book liquidity, partial fills or real execution risks.
```

---

# CLI

Создать:

```text
scripts/run_backtest.py
```

Команда запуска:

```bash
python scripts/run_backtest.py \
  --input out/debug_simple_all.csv \
  --trades-output out/backtest_trades.csv \
  --report-output reports/backtest_report.md \
  --entry-mode breakout \
  --entry-horizon-bars 3 \
  --max-hold-bars 30 \
  --take-r 1.0 \
  --stop-buffer-points 0 \
  --point-value-rub 10 \
  --commission-per-trade 0.025 \
  --contracts 1
```

Также должен работать режим close:

```bash
python scripts/run_backtest.py \
  --input out/debug_simple_all.csv \
  --trades-output out/backtest_trades_close.csv \
  --report-output reports/backtest_report_close.md \
  --entry-mode close \
  --max-hold-bars 30 \
  --take-r 1.0
```

CLI должен вывести summary:

```text
Backtest v1
===========

Input: out/debug_simple_all.csv
Signals: 41
Closed trades: ...
Skipped trades: ...
Entry mode: breakout
Take R: 1.0
Net PnL RUB: ...
Winrate: ...
Profit factor: ...

Trades output: out/backtest_trades.csv
Report output: reports/backtest_report.md
```

---

# Output trades CSV

Сохранять:

```text
out/backtest_trades.csv
```

Колонки:

```text
trade_id
instrument
timeframe
direction
signal_time
entry_time
exit_time
signal_open
signal_high
signal_low
signal_close
entry_price
stop_price
take_price
exit_price
status
exit_reason
risk_points
gross_points
gross_pnl_rub
commission_rub
net_pnl_rub
bars_held
```

---

# Тесты

Добавить тесты без обращения к T-Bank API.

## tests/test_backtest_engine.py

Проверить:

### 1. BUY take-profit

Synthetic dataframe:

- есть BUY сигнал;
- entry-mode close;
- stop ниже;
- следующая свеча достигает take.

Ожидание:

```text
status=closed
exit_reason=take
net_pnl_rub > 0
```

### 2. BUY stop-loss

- BUY сигнал;
- следующая свеча достигает stop.

Ожидание:

```text
status=closed
exit_reason=stop
net_pnl_rub < 0
```

### 3. SELL take-profit

- SELL сигнал;
- следующая свеча идёт вниз и достигает take.

Ожидание:

```text
status=closed
exit_reason=take
net_pnl_rub > 0
```

### 4. SELL stop-loss

- SELL сигнал;
- следующая свеча идёт вверх и достигает stop.

Ожидание:

```text
status=closed
exit_reason=stop
net_pnl_rub < 0
```

### 5. Same-bar stop and take

Если stop и take достигнуты в одной свече, результат должен быть консервативный:

```text
exit_reason=stop_same_bar
net_pnl_rub < 0
```

### 6. Breakout no entry

Для `entry_mode=breakout`, если вход не произошёл в течение `entry_horizon_bars`:

```text
status=skipped_no_entry
```

### 7. Invalid risk

Если stop делает risk <= 0:

```text
status=skipped_invalid_risk
```

### 8. No overlap

Если `allow_overlap=false`, второй сигнал внутри открытой сделки должен быть:

```text
status=skipped_overlap
```

---

## tests/test_backtest_metrics.py

Проверить:

1. total_signals;
2. closed_trades;
3. skipped_trades;
4. wins/losses;
5. winrate;
6. net_pnl_rub;
7. profit_factor;
8. BUY/SELL разбивку.

---

# README

Обновить README.

Добавить раздел:

```markdown
## Backtest v1
```

Описать:

1. Что backtest работает offline поверх `out/debug_simple_all.csv`.
2. Что он не выставляет заявки.
3. Какие есть режимы входа:
   - `close`;
   - `breakout`.
4. Как считается stop.
5. Как считается take через R.
6. Как считается комиссия.
7. Как запустить.
8. Где искать результат.

Пример запуска:

```bash
python scripts/run_backtest.py \
  --input out/debug_simple_all.csv \
  --trades-output out/backtest_trades.csv \
  --report-output reports/backtest_report.md \
  --entry-mode breakout \
  --entry-horizon-bars 3 \
  --max-hold-bars 30 \
  --take-r 1.0
```

---

# Definition of Done

Задача выполнена, если:

1. Есть модуль:

```text
src/backtest/
```

2. Есть CLI:

```text
scripts/run_backtest.py
```

3. Команда запускается:

```bash
python scripts/run_backtest.py \
  --input out/debug_simple_all.csv \
  --trades-output out/backtest_trades.csv \
  --report-output reports/backtest_report.md \
  --entry-mode breakout \
  --entry-horizon-bars 3 \
  --max-hold-bars 30 \
  --take-r 1.0 \
  --stop-buffer-points 0 \
  --point-value-rub 10 \
  --commission-per-trade 0.025 \
  --contracts 1
```

4. Создаётся:

```text
out/backtest_trades.csv
reports/backtest_report.md
```

5. Backtest поддерживает `entry-mode close`.
6. Backtest поддерживает `entry-mode breakout`.
7. В сделках считаются:

```text
gross_points
gross_pnl_rub
commission_rub
net_pnl_rub
```

8. В отчёте есть summary, direction breakdown, exit reasons и таблица сделок.
9. Тесты проходят:

```bash
pytest
```

10. В проекте не добавлены live trading, sandbox orders, real orders или broker execution.

---

# Отчёт после выполнения

После реализации напиши:

```text
Что добавлено:
...

Как запустить:
...

Какие файлы создаются:
...

Какие параметры доступны:
...

Какие тесты добавлены:
...

Первый результат на текущем debug_simple_all.csv:
...

Что пока не реализовано:
...
```

В блоке "Что пока не реализовано" обязательно указать:

```text
- live trading не реализован;
- sandbox orders не реализованы;
- broker execution не реализован;
- slippage не моделируется;
- order book liquidity не моделируется;
- partial fills не моделируются;
- margin requirements / ГО не моделируются;
- backtest v1 не является доказательством прибыльности стратегии.
```
