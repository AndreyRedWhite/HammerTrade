# Claude Code Prompt — MVP-2.0: Backtest Diagnostic Filters

## Контекст проекта

Проект: `HammerTrade / MOEXF`.

Это исследовательский trading/paper-trading бот для MOEX futures.

Текущий основной инструмент:

```text
Ticker: SiM6
Class code: SPBFUT
Timeframe: 1m
Profile: balanced
Direction filter: SELL
Mode: paper only
Orders: disabled
```

Проект работает на сервере Yandex Cloud:

```text
Server: 158.160.204.201
User: vorontsov
Project path: /opt/hammertrade
Virtualenv: /opt/hammertrade/.venv
Systemd service: hammertrade-paper.service
State DB: /opt/hammertrade/data/paper/paper_state.sqlite
Status file: /opt/hammertrade/runtime/paper_status_SiM6_SELL.json
```

Важно: текущий `hammertrade-paper.service` должен продолжать работать. В этом MVP нельзя менять live/paper execution.

---

## Уже реализовано

В проекте уже есть pipeline:

```text
загрузка свечей T-Bank Invest API
data quality report
HammerDetector
debug CSV
single backtest
grid backtest
walk-forward
walk-forward grid
paper trading
paper diagnostics
```

Ориентировочные существующие директории и модули:

```text
data/raw/tbank/
out/
out/paper/
reports/
scripts/
src/
src/strategy/
src/backtest/
src/paper/
```

## MVP-1.7 — Paper trading daemon

Основные артефакты:

```text
data/paper/paper_state.sqlite
out/paper/paper_trades_SiM6_SELL.csv
scripts/paper_report.py
src/paper/report.py
```

Таблица:

```text
paper_trades
```

## MVP-1.8 — Operational Safety Layer

Основные артефакты:

```text
configs/market_hours/moex_futures.yaml
src/market/market_hours.py
scripts/check_paper_status.py
runtime/paper_status_SiM6_SELL.json
docs/paper_trader_operational.md
```

## MVP-1.9 — Paper Trading Diagnostics

Основные артефакты:

```text
src/paper/diagnostics.py
scripts/paper_diagnostics.py
tests/test_paper_diagnostics.py
docs/paper_trader_diagnostics.md
```

Диагностика генерирует:

```text
reports/paper_diagnostics_SiM6_SELL_latest.md
out/paper/paper_trades_diagnostics_SiM6_SELL_latest.csv
```

---

## Текущий paper trading срез

Свежий срез на 13.05.2026:

```text
Period: 2026-05-04 – 2026-05-12
Total trades: 30
Closed trades: 30
Open trades: 0
WIN / LOSS: 19 / 11
Winrate: 63.3%
Gross profit: +3149.05 RUB
Gross loss: -2230.55 RUB
Net PnL: +918.50 RUB
Profit Factor: 1.41
Expectancy: +30.62 RUB/trade
Best trade: +699.95 RUB
Worst trade: -580.05 RUB
Avg R/R: 0.84
Avg bars held: 2.9
Warnings: 0
```

Динамика по срезам:

```text
08.05 morning: 17 trades, winrate 70.6%, net +1049 RUB, PF 1.79, expectancy +61.7
08.05 evening: 22 trades, winrate 63.6%, net +699 RUB, PF 1.37, expectancy +31.8
13.05 current: 30 trades, winrate 63.3%, net +919 RUB, PF 1.41, expectancy +30.6
```

Новые выводы из diagnostics:

```text
TINY_TAKE:
  reward_points < 5
  4 trades
  1W / 3L
  net -170.20 RUB
  PF 0.15

LOW_RR:
  R/R < 0.8
  9 trades
  5W / 4L
  net -50.45 RUB
  PF 0.83

ONE_BAR_STOP:
  5 trades
  0W / 5L
  net -780.25 RUB
  PF 0.00

BIG_RISK:
  risk_points > 40
  3 trades
  2W / 1L
  net +559.85 RUB
  PF 1.97

BARS_001:
  16 trades
  11W / 5L
  net +809.20 RUB
  PF 2.04

BARS_002_003:
  7 trades
  net -30.35 RUB
  PF 0.95

BARS_004_010:
  5 trades
  net -280.25 RUB
  PF 0.65

BARS_011_PLUS:
  2 trades
  net +419.90 RUB
```

По часам paper trading:

```text
Good / promising:
  10 MSK: +1139.90 RUB
  15 MSK: +269.90 RUB
  18 MSK: +369.85 RUB
  22 MSK: +309.80 RUB

Bad / suspicious:
  12 MSK: -870.10 RUB
  13 MSK: -210.05 RUB
  19 MSK: -330.20 RUB
  21 MSK: -310.25 RUB
```

Важно: paper trading выборка всё ещё маленькая. Нельзя по ней менять стратегию. Но гипотезы повторяются, поэтому пора проверить их на историческом backtest/grid.

---

## Главная цель MVP-2.0

Сделать historical validation диагностических фильтров, выявленных в paper trading.

Нужно проверить на исторических данных, улучшают ли фильтры:

```text
MIN_REWARD_POINTS
MIN_RR
entry confirmation scenarios для снижения ONE_BAR_STOP-like входов
max_hold_bars / time-based exit scenarios
experimental time filters
```

Главный принцип:

```text
MVP-2.0 ничего не меняет в paper trader.
MVP-2.0 ничего не включает в live/paper execution.
MVP-2.0 только проверяет гипотезы на истории и формирует отчёты.
```

---

## Жёсткие ограничения

Строго запрещено:

- менять `hammertrade-paper.service`;
- останавливать paper trader;
- менять live/paper trading logic;
- менять текущие параметры paper trader;
- включать фильтры в paper trader;
- менять production config paper trader;
- запускать real trading;
- запускать sandbox orders;
- вызывать broker execution;
- менять `.env`;
- печатать токены;
- удалять текущие SQLite/CSV/reports;
- перезаписывать существующие отчёты без timestamp;
- ломать текущий backtest/grid/walk-forward pipeline.

Разрешено:

- добавлять experimental backtest modules;
- добавлять CLI-скрипты;
- добавлять YAML/JSON configs для experiments;
- читать исторические свечи;
- читать debug CSV / signals CSV;
- запускать detector/backtest на истории;
- создавать новые CSV/Markdown отчёты;
- добавлять tests/smoke checks;
- добавлять документацию;
- переиспользовать existing backtest engine;
- расширить backtest trade model только безопасно и backward-compatible.

---

## Что нужно изучить перед реализацией

Перед кодингом обязательно изучить текущую структуру:

```bash
cd /opt/hammertrade
find . -maxdepth 3 -type f | sort | sed -n '1,240p'
```

Найти и изучить:

```text
scripts/run_full_research_pipeline.sh
scripts/*backtest*.py
scripts/*grid*.py
scripts/*walk*.py
src/backtest/
src/strategy/
src/paper/diagnostics.py
out/debug_simple_all.csv
out/backtest_trades_*.csv
reports/backtest_report_*.md
reports/grid_report_*.md
reports/walk_forward_*.md
```

Особенно важно понять:

1. Где генерируются signals.
2. Где формируется trade entry/stop/take/exit.
3. Где задаётся `hold_bars`.
4. Где считается `bars_held`.
5. Где считается PnL.
6. Как в проекте устроены profiles (`balanced` и другие).
7. Как включается direction filter `SELL`.
8. Есть ли уже grid runner.
9. Есть ли уже walk-forward group by day/week/month.
10. Есть ли timestamp conversion UTC → MSK.
11. Есть ли уже комиссионная модель и slippage.
12. Какие исторические данные уже лежат локально.

Не плодить параллельный backtest engine, если можно аккуратно переиспользовать существующий.

---

## Основная идея реализации

Добавить слой experimental diagnostic filters поверх существующего backtest.

Нужно, чтобы можно было сравнить:

```text
baseline strategy
vs
strategy + min_reward_points
vs
strategy + min_rr
vs
strategy + time filters
vs
strategy + max_hold_bars
vs
strategy + entry confirmation scenario
vs
combinations
```

При этом baseline должен быть идентичен текущей логике backtest/paper, насколько это возможно.

---

## Предпочтительная структура новых файлов

Желательная структура:

```text
src/backtest/diagnostic_filters.py
src/backtest/diagnostic_grid.py
scripts/backtest_diagnostic_filters.py
configs/backtest_diagnostic_filters_sim6_sell.yaml
tests/test_backtest_diagnostic_filters.py
docs/backtest_diagnostic_filters.md
```

Если по текущей архитектуре лучше другое место — адаптироваться, но сохранить понятные имена.

---

## Diagnostic filter config

Создать конфиг:

```text
configs/backtest_diagnostic_filters_sim6_sell.yaml
```

Пример структуры:

```yaml
experiment:
  name: "mvp20_diagnostic_filters_sim6_sell"
  ticker: "SiM6"
  class_code: "SPBFUT"
  timeframe: "1m"
  profile: "balanced"
  direction: "SELL"

data:
  prefer_existing_raw: true
  raw_glob: "data/raw/tbank/*SiM6*1m*.csv"
  signals_csv: "out/debug_simple_all.csv"

date_range:
  from: "2026-03-01"
  to: "2026-05-12"

execution:
  slippage_points: [0.0, 1.0, 2.0, 5.0]
  commission_mode: "current_project_default"

filters_grid:
  min_reward_points: [0, 5, 6, 8]
  min_rr: [0.0, 0.8, 0.85, 0.9]
  max_hold_bars: [null, 3, 5, 10]
  time_filter:
    - name: "all_hours"
      include_hours_msk: null
      exclude_hours_msk: []
    - name: "exclude_bad_paper_hours"
      include_hours_msk: null
      exclude_hours_msk: [12, 13, 19, 21]
    - name: "only_good_paper_hours"
      include_hours_msk: [10, 15, 18, 20, 22]
      exclude_hours_msk: []
  entry_confirmation:
    - "baseline"
    - "next_candle_direction"
    - "breakout_confirmation"

reporting:
  top_n: 20
  min_trades_required: 30
```

Если YAML config style уже есть в проекте — использовать текущий стиль.

---

## Фильтры MVP-2.0

## 1. MIN_REWARD_POINTS

Проверить:

```text
0
5
6
8
```

Логика:

```text
Для SELL:
reward_points = entry_price - take_price

Для BUY:
reward_points = take_price - entry_price
```

Если `reward_points < min_reward_points`, сделка пропускается.

`0` означает baseline/no filter.

Цель: проверить гипотезу `TINY_TAKE`.

---

## 2. MIN_RR

Проверить:

```text
0.0
0.8
0.85
0.9
```

Логика:

```text
rr = reward_points / risk_points
```

Если `rr < min_rr`, сделка пропускается.

`0.0` означает baseline/no filter.

Цель: проверить гипотезу `LOW_RR`.

---

## 3. Time filters

Проверить минимум три режима:

```text
all_hours
exclude_bad_paper_hours
only_good_paper_hours
```

Где:

```text
exclude_bad_paper_hours = [12, 13, 19, 21]
only_good_paper_hours = [10, 15, 18, 20, 22]
```

Часы считать в MSK по entry timestamp.

Важно:
- Это experimental.
- Не делать time filter главным выводом, если сделок мало.
- В отчёте отдельно пометить риск переобучения по часам.

---

## 4. Max hold bars / time-based exit scenarios

Проверить:

```text
current / null
3
5
10
```

Optional, если легко добавить:

```text
1
```

Но `1` не должен быть главным кандидатом, только стресс-тест.

Важно:
- Нужно понять, как в текущем backtest задаётся удержание сделки.
- Если текущая логика exit already uses stop/take/hold, max_hold_bars должен быть экспериментальным параметром выхода.
- Если реализация `max_hold_bars` требует слишком большого вмешательства в engine, сделать это отдельным optional блоком и честно указать, что не реализовано в MVP-2.0.

Цель: проверить наблюдение, что BARS_001 был сильнее, а BARS_002_003 и BARS_004_010 хуже.

Но не делать вывод “закрывать всё через 1 бар” без исторической проверки.

---

## 5. Entry confirmation scenarios

Это самый тонкий блок.

Цель: проверить, можно ли уменьшить ONE_BAR_STOP-like входы.

Проверить сценарии:

```text
baseline
next_candle_direction
breakout_confirmation
```

### baseline

Текущая логика без изменений.

### next_candle_direction

Для SELL:
- после сигнальной свечи дождаться следующей свечи;
- вход разрешён только если следующая свеча подтверждает движение вниз.

Варианты допустимой реализации:
- next candle close < next candle open;
- или next candle close < signal candle close;
- выбрать тот вариант, который лучше согласуется с текущей архитектурой и честно описать в отчёте.

Для BUY на будущее:
- mirror logic.

### breakout_confirmation

Для SELL:
- вход только если цена пробивает low сигнальной свечи или рассчитанный breakout level;
- если в текущей архитектуре entry уже является breakout, тогда scenario должен совпасть с baseline или быть пропущен с объяснением.

Для BUY:
- mirror logic.

Важно:
- Не ломать baseline.
- Не менять detector.
- Не менять paper trader.
- Если confirmation logic невозможно корректно реализовать без существенной переработки, сделать только analytic simulation или отложить в отдельный MVP и явно написать почему.

---

## Что НЕ является фильтром первого приоритета

## BIG_RISK

Paper trading показывает:

```text
BIG_RISK: +559.85 RUB, PF 1.97
```

Поэтому нельзя делать `MAX_RISK_POINTS` главным фильтром.

Можно добавить optional grid:

```text
max_risk_points: [null, 40, 50, 60, 80]
```

Но только если это легко и не раздувает число сценариев слишком сильно.

Если добавляешь — в отчёте явно написать:

```text
BIG_RISK не является очевидно плохой зоной по paper trading. MAX_RISK_POINTS проверяется только как risk control experiment.
```

---

## Ограничение размера grid

Не нужно делать гигантскую сетку на тысячи комбинаций, если это замедлит работу или сделает отчёт нечитаемым.

Предпочтительный подход:

### Phase A — single-factor analysis

Сначала проверить каждый фильтр отдельно против baseline:

```text
baseline
min_reward_points only
min_rr only
time_filter only
max_hold_bars only
entry_confirmation only
```

### Phase B — small combined grid

Потом проверить небольшую сетку комбинаций лучших кандидатов:

```text
min_reward_points: [0, 5, 6]
min_rr: [0.0, 0.8]
time_filter: [all_hours, exclude_bad_paper_hours]
entry_confirmation: [baseline, best_confirmation_if_available]
max_hold_bars: [null, 5, 10]
```

Если Phase B получается слишком большой — сократить и объяснить.

---

## Метрики для каждого scenario

Для каждого сценария посчитать:

```text
scenario_id
scenario_name
filters_json
trades
wins
losses
winrate_pct
gross_profit_rub
gross_loss_rub
net_pnl_rub
profit_factor
expectancy_rub
avg_trade_rub
median_trade_rub
best_trade_rub
worst_trade_rub
max_drawdown_rub
max_drawdown_pct_if_available
avg_risk_points
avg_reward_points
avg_rr
avg_bars_held
take_count
stop_count
timeout_count_or_hold_exit_count
skipped_signals
skip_rate_pct
```

Очень важно:

```text
skipped_signals
skip_rate_pct
```

Потому что фильтр может улучшить PF, просто выкинув почти все сделки.

---

## Stability / robustness checks

Не ограничиваться total metrics.

Нужно добавить устойчивость по периодам:

```text
daily
weekly
monthly if enough data
```

Минимум:

```text
profitable_days_pct
profitable_weeks_pct
worst_day_pnl
best_day_pnl
avg_day_pnl
periods_count
```

Если уже есть walk-forward code — переиспользовать.

Отдельно пометить сценарии, где:

```text
trades < min_trades_required
```

Например:

```text
LOW_SAMPLE
```

По умолчанию:

```text
min_trades_required = 30
```

---

## Ranking scenarios

Сделать ranking, но не только по Net PnL.

Нужны несколько рангов:

## Rank by net PnL

```text
highest net_pnl_rub
```

## Rank by Profit Factor

```text
highest PF, but trades >= min_trades_required
```

## Rank by risk-adjusted score

Простой score:

```text
score = net_pnl_rub - abs(max_drawdown_rub) * 0.5
```

или другой простой и прозрачный score, если уже есть в проекте.

## Rank by robustness

Предпочтение сценариям, где:

```text
PF > baseline PF
net_pnl > baseline net_pnl
max_drawdown better than baseline
trades >= 70% of baseline trades
profitable_periods_pct >= baseline
```

В отчёте обязательно сравнить top scenarios с baseline.

---

## Output files

Создать timestamped артефакты:

```text
out/backtest_diagnostic_filters_SiM6_SELL_YYYYMMDD_HHMMSS.csv
out/backtest_diagnostic_trades_SiM6_SELL_YYYYMMDD_HHMMSS.csv
reports/backtest_diagnostic_filters_SiM6_SELL_YYYYMMDD_HHMMSS.md
```

Также можно создать latest copies:

```text
out/backtest_diagnostic_filters_SiM6_SELL_latest.csv
out/backtest_diagnostic_trades_SiM6_SELL_latest.csv
reports/backtest_diagnostic_filters_SiM6_SELL_latest.md
```

Если в проекте принята другая структура под `out/backtest/`, использовать её, но не перезаписывать старые результаты без timestamp.

---

## Markdown report structure

Отчёт должен быть на русском языке.

Файл:

```text
reports/backtest_diagnostic_filters_SiM6_SELL_YYYYMMDD_HHMMSS.md
```

Структура:

```markdown
# Backtest Diagnostic Filters — SiM6 SELL

## Контекст

## Источник данных

## Baseline

## Phase A — single-factor analysis

### MIN_REWARD_POINTS

### MIN_RR

### Time filters

### Max hold bars

### Entry confirmation

## Phase B — combined scenarios

## Top scenarios by Net PnL

## Top scenarios by Profit Factor

## Top scenarios by risk-adjusted score

## Robustness / period stability

## Comparison with paper trading hypotheses

## Candidate filters for next paper trading config

## Scenarios rejected

## Warnings and limitations

## Recommendation

## Next MVP
```

---

## Обязательные выводы в отчёте

Отчёт должен ответить:

1. Улучшает ли `MIN_REWARD_POINTS >= 5` baseline?
2. Что лучше: `5`, `6`, или `8`?
3. Улучшает ли `MIN_RR >= 0.8` baseline?
4. Что лучше: `0.8`, `0.85`, или `0.9`?
5. Подтверждаются ли плохие time windows `12–13`, `19`, `21`?
6. Не является ли time filter переобучением?
7. Помогает ли `max_hold_bars`?
8. Есть ли вред от слишком раннего time exit?
9. Можно ли уменьшить ONE_BAR_STOP-like потери через confirmation?
10. Какие сценарии дают лучший PF?
11. Какие сценарии дают лучший Net PnL?
12. Какие сценарии уменьшают max drawdown?
13. Какие сценарии слишком сильно режут количество сделок?
14. Какие сценарии выглядят переобученными?
15. Какие 1–2 фильтра можно предложить для следующего paper trading MVP?

---

## Candidate filters for next paper trading config

В конце отчёта дать один из вариантов:

### Вариант A — есть сильный кандидат

```text
Recommended for MVP-2.1 paper config:
- min_reward_points = X
- min_rr = Y
- entry_confirmation = Z
```

С объяснением:

```text
Потому что:
- PF выше baseline;
- net PnL не ниже baseline или просадка ниже;
- drawdown ниже;
- количество сделок не схлопнулось;
- результат устойчив по периодам.
```

### Вариант B — кандидаты слабые

```text
Do not change paper trader yet.
Continue collecting paper data and/or extend historical test.
```

### Вариант C — фильтры конфликтуют

```text
MIN_REWARD improves PF but kills Net PnL.
MIN_RR improves drawdown but reduces trade count too much.
Need additional testing before MVP-2.1.
```

---

## CLI

Добавить скрипт:

```text
scripts/backtest_diagnostic_filters.py
```

Базовый запуск:

```bash
python scripts/backtest_diagnostic_filters.py
```

Запуск с конфигом:

```bash
python scripts/backtest_diagnostic_filters.py \
  --config configs/backtest_diagnostic_filters_sim6_sell.yaml
```

Желательные аргументы:

```bash
python scripts/backtest_diagnostic_filters.py \
  --config configs/backtest_diagnostic_filters_sim6_sell.yaml \
  --from 2026-03-01 \
  --to 2026-05-12 \
  --ticker SiM6 \
  --direction SELL
```

CLI должен печатать:

```text
HammerTrade Backtest Diagnostic Filters
Ticker      : SiM6
Direction   : SELL
Period      : 2026-03-01 — 2026-05-12
Baseline    : trades=N, net=..., PF=..., maxDD=...
Scenarios   : N
Results CSV : out/backtest_diagnostic_filters_SiM6_SELL_YYYYMMDD_HHMMSS.csv
Trades CSV  : out/backtest_diagnostic_trades_SiM6_SELL_YYYYMMDD_HHMMSS.csv
Report      : reports/backtest_diagnostic_filters_SiM6_SELL_YYYYMMDD_HHMMSS.md
Warnings    : N
```

---

## Tests / smoke checks

Добавить тесты:

```text
tests/test_backtest_diagnostic_filters.py
```

Минимум проверить:

1. SELL reward/risk/RR filter:

```text
entry=100, stop=110, take=90
risk=10, reward=10, rr=1.0
```

2. `min_reward_points=5` пропускает reward=4 и оставляет reward=5.
3. `min_rr=0.8` пропускает rr=0.79 и оставляет rr=0.8.
4. Time filter считает MSK hour корректно.
5. `exclude_hours_msk` пропускает сигнал в запрещённый час.
6. `include_hours_msk` оставляет только разрешённые часы.
7. Combined filters работают через AND.
8. Scenario with zero trades не падает.
9. LOW_SAMPLE flag ставится, если trades < min_trades_required.
10. Report generation не падает на пустом scenario.
11. Baseline scenario не применяет фильтры.
12. Если entry confirmation scenario не поддержан — он явно помечается как skipped/unsupported, а не ломает весь run.

Если есть существующие тестовые helpers для backtest — переиспользовать.

---

## Backward compatibility

После реализации обязательно прогнать существующие тесты:

```bash
.venv/bin/python -m pytest
```

Если полный pytest слишком долгий:

```bash
.venv/bin/python -m pytest tests/test_backtest_diagnostic_filters.py tests/test_paper_diagnostics.py
```

Но в финальном ответе указать, что именно запускалось.

---

## Команды проверки на сервере

После реализации выполнить:

```bash
cd /opt/hammertrade
source .venv/bin/activate

python scripts/backtest_diagnostic_filters.py \
  --config configs/backtest_diagnostic_filters_sim6_sell.yaml
```

Показать артефакты:

```bash
ls -lah reports | grep backtest_diagnostic_filters | tail
ls -lah out | grep backtest_diagnostic | tail
```

Если out files лежат в поддиректории, использовать правильный путь.

Проверить, что paper service жив:

```bash
sudo systemctl status hammertrade-paper --no-pager
.venv/bin/python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json
```

Если `check_paper_status.py` недоступен — не считать ошибкой MVP-2.0, просто указать.

---

## Acceptance Criteria

MVP-2.0 считается готовым, если:

1. Появился CLI:

```text
scripts/backtest_diagnostic_filters.py
```

2. Есть конфиг:

```text
configs/backtest_diagnostic_filters_sim6_sell.yaml
```

3. Команда запускается:

```bash
python scripts/backtest_diagnostic_filters.py \
  --config configs/backtest_diagnostic_filters_sim6_sell.yaml
```

4. Baseline scenario считается и явно попадает в отчёт.
5. Проверяются `MIN_REWARD_POINTS`.
6. Проверяются `MIN_RR`.
7. Проверяются time filters.
8. Проверяется `max_hold_bars`, либо честно указано, почему не реализовано в этом MVP.
9. Проверяется хотя бы один entry confirmation scenario, либо честно указано, почему не реализовано в этом MVP.
10. Для каждого scenario считаются:
    - trades;
    - winrate;
    - net PnL;
    - PF;
    - expectancy;
    - max drawdown;
    - worst trade;
    - skipped signals.
11. Генерируется CSV со scenario summary.
12. Генерируется CSV с trades/details.
13. Генерируется Markdown report.
14. Отчёт сравнивает scenarios с baseline.
15. Отчёт даёт рекомендацию: какие 1–2 фильтра стоит или не стоит проверять в paper trader.
16. Текущий paper trader не изменён.
17. Systemd service не изменён.
18. Тесты или smoke checks выполнены.
19. В финальном ответе Claude Code указал:
    - созданные файлы;
    - изменённые файлы;
    - команды запуска;
    - артефакты;
    - baseline results;
    - top scenarios;
    - recommendation for MVP-2.1;
    - ограничения и warnings.

---

## Что НЕ делать в MVP-2.0

Не включать фильтры в paper trader.

Не менять:

```text
scripts/run_paper_trader.py
src/paper/engine.py
systemd unit
production paper config
```

Если нужно импортировать функции из этих модулей — можно, но не менять торговую логику.

Не делать live trading.

Не делать sandbox orders.

Не делать Telegram notifications.

Не делать автоматическое изменение `.env`.

Не делать cron/systemd timers.

Не оптимизировать стратегию “на глаз”.

Не объявлять стратегию прибыльной.

---

## Важная интерпретация результата

Даже если какой-то scenario выглядит очень хорошо, нельзя писать:

```text
Стратегия доказана.
Можно включать live trading.
```

Правильная формулировка:

```text
Scenario X улучшил исторический backtest относительно baseline и может быть кандидатом для следующего paper trading MVP. Перед live trading нужно проверить его в paper режиме на новых данных.
```

Если все фильтры ухудшают baseline:

```text
Диагностические фильтры из paper trading не подтвердились на историческом срезе. Не рекомендуется менять paper trader. Нужно продолжать сбор данных или искать другие признаки.
```

Если фильтр улучшает PF, но режет 80–90% сделок:

```text
Фильтр выглядит переобученным или слишком агрессивным. Нужна дополнительная проверка.
```

---

## Финальный формат ответа Claude Code

После выполнения задачи ответить так:

```markdown
## MVP-2.0 Backtest Diagnostic Filters — готово

### Что сделано

### Созданные файлы

### Изменённые файлы

### Как запустить

### Источник данных и период

### Baseline result

### Top scenarios

### Что подтвердилось из paper trading

### Что не подтвердилось

### Candidate filters for MVP-2.1

### Что НЕ было изменено

### Тесты / smoke checks

### Артефакты

### Warnings / limitations

### Рекомендация
```
