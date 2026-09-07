# Claude Code Prompt — HammerTrade Research Roadmap: Continue Hammer + Start New Strategy Branches

## Контекст

Проект: `HammerTrade / MOEXF`.

Это исследовательская платформа для торговых стратегий на MOEX futures через T-Bank Invest API.

Изначальная стратегия:

```text
Hammer / inverted hammer / upper wick reversal pattern
Текущий live/paper режим: SiM6 SELL
Timeframe: 1m
Profile: balanced
Mode: paper only
Orders: disabled
```

Текущий сервер:

```text
Server: 158.160.204.201
User: vorontsov
Project path: /opt/hammertrade
Virtualenv: /opt/hammertrade/.venv
```

Текущие paper-сервисы:

```text
Baseline:
  service: hammertrade-paper.service
  ticker: SiM6
  direction: SELL
  max_hold_bars: None
  db: data/paper/paper_state.sqlite
  status: runtime/paper_status_SiM6_SELL.json

Maxhold5:
  service: hammertrade-paper-maxhold5.service
  ticker: SiM6
  direction: SELL
  max_hold_bars: 5
  db: data/paper/paper_state_maxhold5.sqlite
  status: runtime/paper_status_SiM6_SELL_maxhold5.json
```

Важно:

```text
Текущие сервисы baseline и maxhold5 нельзя ломать, менять или перезапускать без необходимости.
Все новые исследования должны быть read-only / offline research, пока отдельно не будет принято решение о новом paper service.
```

---

## Текущие итоги hammer-стратегии

По live paper отчёту за 3 недели:

## Baseline

```text
Period: 2026-05-04 — 2026-05-29
Closed trades: 86
Winrate: 60.5%
Net PnL: +55.70 RUB
Profit Factor: 1.01
Avg PnL / trade: +0.65 RUB
Worst trade: -1 140.05 RUB
Avg bars held: 3.7
```

## Maxhold5

```text
Period: 2026-05-13 — 2026-05-29
Closed trades: 57
Winrate: 63.2%
Net PnL: +867.15 RUB
Profit Factor: 1.19
Avg PnL / trade: +15.21 RUB
Worst trade: -960.05 RUB
Avg bars held: 2.5
```

## Correct A/B window

Maxhold5 стартовал 2026-05-13, поэтому корректное сравнение:

```text
Baseline May 13–29: -862.80 RUB
Maxhold5 May 13–29: +867.15 RUB
Delta in favor of maxhold5: +1 729.95 RUB
```

---

## MVP-2.3 Hour 12 Targeted Audit — результат

Итог аудита:

```text
Historical Jan-Apr:
  all hours: PF 3.39, +19754 RUB
  hour 12: PF 0.73, -591 RUB, 11 trades
  without hour 12: PF 4.37, +20345 RUB

Baseline live:
  all hours: PF 1.01, +56 RUB
  hour 12: PF 0.21, -1460 RUB, 7 trades, LOW_SAMPLE
  without hour 12: PF 1.19, +1516 RUB

Maxhold5 live:
  all hours: PF 1.19, +867 RUB
  hour 12: PF 1.28, +139 RUB, 5 trades, LOW_SAMPLE
  without hour 12: PF 1.17, +727 RUB
```

Candidate decision:

```text
B — Weak candidate / observe more
Overfit risk: HIGH
```

Key insight:

```text
maxhold5 уже частично исправил проблему часа 12.
Добавлять exclude_hour_12 в maxhold5 сейчас не нужно.
```

Вывод:

```text
Не запускать maxhold5 + exclude12 сейчас.
Продолжать maxhold5 без новых фильтров до 60–70 сделок.
Если PF < 1.25 после ≥60 сделок или 4 недель — hammer-стратегию замораживать как основной торговый кандидат.
```

---

## Текущие operational MVPs

## MVP-2.3a Trading Liveness Guard — готово

Добавлены:

```text
trading_liveness_status: OK / DEGRADED / STALLED
consecutive_api_errors
total_api_errors
last_successful_fetch_at
minutes_since_last_successful_fetch
market_open_since grace period
check_paper_status.py exit codes
paper_error_report.py liveness summary
```

Цель:

```text
Не допустить ситуации service active, но бот фактически не торгует.
```

## Rollover SiM6 → SiU6 plan — готово

Документ:

```text
docs/rollover_siu6_plan.md
```

Ключевые данные:

```text
SiM6 expiration_date: 2026-06-19
SiU6 expiration_date: 2026-09-18
SiU6 торгуется, параметры совместимы:
  class_code: SPBFUT
  lot: 1
  min_price_increment: 1.0
```

Текущий вывод:

```text
SiU6 технически готов, но пока примерно 9x хуже по объёму.
Сейчас торговать SiU6 нельзя.
С 2026-06-02 мониторить ликвидность.
Крайняя дата переключения: около 2026-06-10.
```

---

# Главная задача этого большого MVP

Сделать следующий этап проекта структурированным:

```text
1. Hammer-ветку не бросаем, но переводим в bounded observation mode.
2. Не добавляем новые фильтры в hammer без сильного основания.
3. Запускаем новый research track для альтернативных стратегий внутри HammerTrade.
4. Начинаем с Opening Range Breakout.
5. Закладываем архитектуру Strategy Research Lab, чтобы в будущем можно было тестировать много стратегий одинаковым способом.
6. Учитываем специфику РФ-рынка: новости, геополитика, режимы рынка, волатильность.
```

Это НЕ запуск новых live/paper сервисов.

Это НЕ sandbox.

Это НЕ real trading.

Это research/infrastructure MVP.

---

# Жёсткие ограничения

Строго запрещено:

- менять `hammertrade-paper.service`;
- менять `hammertrade-paper-maxhold5.service`;
- менять текущие systemd units;
- менять current paper DB;
- сбрасывать state;
- удалять SQLite/CSV/reports/logs;
- менять HammerDetector;
- менять текущую hammer strategy logic;
- менять `max_hold_bars=5`;
- включать exclude_hour_12 в текущий paper trader;
- запускать третий paper service;
- запускать sandbox orders;
- запускать real orders;
- менять `.env`;
- печатать токены;
- делать вывод “стратегия доказана”;
- обещать прибыль.

Разрешено:

- добавлять read-only research modules;
- добавлять offline backtest scripts;
- создавать новые configs;
- читать historical candles / raw data;
- читать existing paper DB/reports;
- создавать Markdown/CSV reports;
- добавлять tests;
- добавлять docs;
- добавлять Strategy Research Lab abstractions, если они не ломают текущий код.

---

# Часть A — Hammer bounded observation

## Цель

Продолжить текущий A/B hammer experiment без новых изменений.

Нужно добавить/подготовить скрипт итогового decision report, если его ещё нет:

```text
scripts/hammer_decision_report.py
```

Или расширить существующие:

```text
scripts/compare_paper_experiments.py
scripts/paper_diagnostics.py
```

## Что считать

Когда maxhold5 достигнет:

```text
closed_trades >= 60
```

или когда пройдёт:

```text
4 недели с 2026-05-13
```

нужно уметь собрать final bounded report:

```text
baseline all-time
maxhold5 all-time
baseline comparable window since maxhold5 start
maxhold5 comparable window
delta
PF
net
expectancy
max drawdown
worst trade
bars buckets
hour buckets
MAX_HOLD_EXIT contribution
ONE_BAR_STOP
BIG_RISK
operational gaps
liveness status
```

## Decision rules

В отчёте явно вывести:

```text
CONTINUE / OBSERVE_ONLY / FREEZE
```

Правила:

## CONTINUE

Только если:

```text
maxhold5 comparable PF >= 1.25
и net > baseline comparable materially
и результат не держится на 1–2 сделках
и liveness OK
```

## OBSERVE_ONLY

Если:

```text
maxhold5 лучше baseline, но PF < 1.25
или выборка недостаточна
или результаты хрупкие
```

## FREEZE

Если:

```text
maxhold5 PF < 1.15 после >=60 сделок
или comparable result не лучше baseline
или drawdown/worst trade unacceptable
```

Важно:

```text
Даже CONTINUE не означает sandbox/live.
Это означает: можно продолжить research.
```

---

# Часть B — Strategy Research Lab architecture

## Цель

Заложить минимальную архитектуру для исследования нескольких стратегий в одном проекте, не вмешиваясь в текущие paper daemons.

Желательная структура:

```text
src/strategies/
  __init__.py
  base.py
  registry.py

src/strategies/hammer_reversal/
  __init__.py
  adapter.py

src/strategies/opening_range_breakout/
  __init__.py
  strategy.py
  backtest.py

src/research/
  __init__.py
  runner.py
  metrics.py
  reports.py

configs/research/
  opening_range_breakout_sim6_sell.yaml

scripts/research_strategy.py
```

Если текущая структура проекта предполагает другое место — адаптироваться.

## Strategy interface

Добавить минимальный интерфейс:

```python
class StrategySignal:
    strategy_name: str
    ticker: str
    direction: str
    timestamp: datetime
    entry_price: float
    stop_price: float | None
    take_price: float | None
    reason: str
    metadata: dict

class Strategy:
    name: str

    def generate_signals(self, candles: pd.DataFrame, context: dict) -> list[StrategySignal]:
        ...

    def required_columns(self) -> list[str]:
        ...
```

Не обязательно делать идеально. Цель — минимальная унификация для research.

## Research result schema

Единый формат результатов:

```text
strategy_name
ticker
direction
timeframe
scenario
trades
wins
losses
winrate
net_pnl
profit_factor
expectancy
max_drawdown
best_trade
worst_trade
avg_bars_held
median_bars_held
profitable_days_pct
profitable_weeks_pct
warnings
```

## Важно

Не надо переписывать текущий hammer код под новый интерфейс полностью.

Можно сделать adapter:

```text
src/strategies/hammer_reversal/adapter.py
```

который просто документирует, что текущая hammer strategy пока legacy/paper-driven.

---

# Часть C — MVP-R1 Opening Range Breakout Research

## Почему именно ORB

Opening Range Breakout — простая альтернативная стратегия:

```text
Берём диапазон начала основной сессии.
Если цена пробивает high/low диапазона — входим по направлению пробоя.
Стоп — за противоположной границей диапазона или ATR.
Тейк — 1R / 1.5R / 2R / trailing / time exit.
```

Плюсы:

```text
- хорошо формализуется;
- хорошо бэктестится;
- подходит для трендовых/новостных дней;
- логика отличается от hammer reversal;
- можно сравнивать режимы рынка.
```

## Цель MVP-R1

Сделать offline research/backtest Opening Range Breakout на доступных исторических данных SiM6.

Не запускать paper service.

Не подключать sandbox.

## Источник данных

Использовать существующие исторические 1m candles, если они есть:

```text
data/raw/tbank/
out/debug_simple_all.csv
любой существующий historical candles CSV
```

Если нет удобного файла — добавить read-only loader, который может загрузить historical candles через T-Bank API по .env токенам, но:

```text
не печатать токены;
не менять .env;
не делать orders.
```

Период:

```text
Jan 15 — Apr 9 2026
May 4 — May 29 2026 if candles are available
```

Если May candles не сохранены, использовать доступную историю и явно указать limitation.

---

## ORB scenarios

Проверить несколько opening ranges:

```text
10:00–10:15 MSK
10:00–10:30 MSK
10:00–11:00 MSK
```

Проверить направления:

```text
breakout_up
breakout_down
both
```

Для текущей первой версии можно начать с:

```text
SiM6 both directions
```

или если проще:

```text
SiM6 SELL only
```

Но в отчёте явно указать.

## Entry logic

Для short:

```text
Если после окончания opening range цена пробивает OR low вниз,
entry = OR low или close пробойной свечи, в зависимости от scenario.
```

Для long:

```text
Если цена пробивает OR high вверх,
entry = OR high или close пробойной свечи.
```

Нельзя использовать look-ahead.

## Stop logic

Scenarios:

```text
stop_opposite_range:
  long stop = OR low
  short stop = OR high

stop_atr:
  stop = entry ± ATR_N * multiplier

stop_mid_range:
  stop = midpoint OR
```

Начать с:

```text
stop_opposite_range
```

## Take / exit logic

Scenarios:

```text
take_1R
take_1_5R
take_2R
time_exit_18_40
time_exit_before_clearing
trailing_optional
```

Для MVP-R1 достаточно:

```text
take_r in [1.0, 1.5, 2.0]
time_exit = 18:40 MSK
```

И обязательно:

```text
no overnight
avoid clearing windows
```

## One trade per day

Для MVP-R1:

```text
max_trades_per_day = 1
```

Если оба направления пробиты, брать первый валидный пробой.

---

# Часть D — Regime / News Shock proxy

## Зачем

Рынок РФ сильно зависит от политических/геополитических новостей. Чистый теханализ может ломаться на новостных шоках.

На первом этапе не нужно NLP/парсинг новостей.

Нужно добавить простые proxy-признаки режима:

```text
daily_range
opening_gap
ATR_30m
ATR_60m
volume_vs_average
large_candle_count
spread if orderbook available later
```

## Минимальная классификация дня

Добавить простую функцию:

```text
classify_day_regime(candles) -> regime
```

Режимы:

```text
LOW_VOL_RANGE
NORMAL
HIGH_VOL_TREND
NEWS_SHOCK_PROXY
```

Примерные правила:

```text
NEWS_SHOCK_PROXY:
  opening gap > X * ATR
  or first hour range > Y * median first hour range
  or volume first hour > Z * median volume

HIGH_VOL_TREND:
  daily range > X * median daily range
  and close near high/low

LOW_VOL_RANGE:
  daily range < X * median daily range
```

Пороговые значения в config.

## В отчёте ORB

Показать результат ORB по режимам:

```text
regime
trades
net
PF
winrate
maxDD
```

Цель:

```text
Понять, работает ли ORB в high-vol/trend/news-like days,
и проваливается ли в low-vol/range days.
```

---

# Часть E — Reports

## ORB report

Создать:

```text
reports/research_opening_range_breakout_SiM6_YYYYMMDD_HHMMSS.md
reports/research_opening_range_breakout_SiM6_latest.md

out/research_opening_range_breakout_SiM6_YYYYMMDD_HHMMSS.csv
out/research_opening_range_breakout_trades_SiM6_YYYYMMDD_HHMMSS.csv
```

## Markdown structure

```markdown
# Research — Opening Range Breakout — SiM6

## Цель

## Источник данных

## Scenarios

## Baseline assumptions

## Top scenarios

## Results by opening range

## Results by take_r

## Results by direction

## Results by market regime

## Worst scenarios

## Drawdowns

## Trade examples

## Comparison with Hammer maxhold5

## Limitations

## Recommendation

## Next steps
```

## Сравнение с hammer

В отчёте сравнить ORB с текущими paper numbers:

```text
hammer baseline:
  PF 1.01, +55.70 RUB, 86 trades

hammer maxhold5:
  PF 1.19, +867.15 RUB, 57 trades
```

Но явно написать:

```text
ORB historical/offline result is not directly comparable with live paper.
```

---

# Часть F — CLI

Добавить общий research CLI:

```text
scripts/research_strategy.py
```

Пример запуска:

```bash
python scripts/research_strategy.py \
  --strategy opening_range_breakout \
  --config configs/research/opening_range_breakout_sim6.yaml
```

Можно также сделать отдельный:

```text
scripts/research_opening_range_breakout.py
```

Но общий CLI предпочтительнее.

Config:

```text
configs/research/opening_range_breakout_sim6.yaml
```

Пример:

```yaml
experiment:
  name: opening_range_breakout_sim6
  ticker: SiM6
  class_code: SPBFUT
  timeframe: 1m

data:
  candles_csv: data/raw/tbank/SiM6_1m_latest.csv

session:
  timezone: Europe/Moscow
  main_session_start: "10:00"
  main_session_end: "18:45"
  no_overnight: true

opening_ranges:
  - ["10:00", "10:15"]
  - ["10:00", "10:30"]
  - ["10:00", "11:00"]

directions:
  - long
  - short
  - both

entry:
  mode:
    - breakout_level
    - breakout_candle_close

stop:
  mode:
    - opposite_range

take:
  r:
    - 1.0
    - 1.5
    - 2.0

exit:
  time_exit: "18:40"
  max_trades_per_day: 1

regime:
  enabled: true
  atr_window: 60
  volume_window_days: 20
```

---

# Часть G — Tests

Добавить тесты:

```text
tests/test_strategy_base.py
tests/test_opening_range_breakout.py
tests/test_regime_classification.py
tests/test_research_runner.py
```

Минимум:

## Strategy base

```text
1. StrategySignal can be created.
2. Strategy result schema serializes to dict.
```

## ORB

```text
1. Opening range high/low calculated correctly.
2. Long breakout signal generated after OR end.
3. Short breakout signal generated after OR end.
4. No signal before OR end.
5. No look-ahead: OR uses only candles inside range.
6. One trade per day works.
7. Stop opposite range for long works.
8. Stop opposite range for short works.
9. take_r calculation works.
10. time_exit works.
11. clearing/no overnight rule works.
```

## Regime

```text
1. Low vol day classified as LOW_VOL_RANGE.
2. Large gap / huge first-hour range classified as NEWS_SHOCK_PROXY.
3. High range directional day classified as HIGH_VOL_TREND.
4. Normal day classified as NORMAL.
```

## Research runner

```text
1. Runs one scenario and returns metrics.
2. Handles empty data.
3. Saves report.
```

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_strategy_base.py \
  tests/test_opening_range_breakout.py \
  tests/test_regime_classification.py \
  tests/test_research_runner.py
```

If feasible:

```bash
.venv/bin/python -m pytest
```

---

# Часть H — Backward compatibility / service safety

After implementation, verify current services:

```bash
sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager

.venv/bin/python scripts/check_paper_status.py \
  --status-file runtime/paper_status_SiM6_SELL.json

.venv/bin/python scripts/check_paper_status.py \
  --status-file runtime/paper_status_SiM6_SELL_maxhold5.json
```

Expected:

```text
baseline: active, liveness OK, max_hold_bars=None
maxhold5: active, liveness OK, max_hold_bars=5
```

No service restarts required unless imports/shared files changed in a way that affects daemon runtime. Avoid touching daemon code.

---

# Acceptance Criteria

This large MVP is done if:

## Hammer observation

1. There is a clear final decision report mechanism for hammer maxhold5.
2. Decision rules CONTINUE / OBSERVE_ONLY / FREEZE are documented.
3. Current services are unchanged and alive.

## Strategy Research Lab

4. Minimal strategy interface exists.
5. Research result schema exists.
6. Strategy registry or equivalent exists.
7. No current daemon is migrated/broken.

## ORB Research

8. Opening Range Breakout strategy implemented as offline research.
9. ORB config exists.
10. ORB CLI exists.
11. ORB backtest runs on available historical data.
12. ORB tests pass.
13. ORB report and CSV outputs are created.
14. ORB results are broken down by:
    - opening range;
    - take_r;
    - direction;
    - market regime.

## Regime / News proxy

15. Basic regime classifier exists.
16. ORB report includes regime breakdown.
17. Docs explain that this is a proxy, not real news understanding.

## Safety

18. No real/sandbox orders.
19. No service changes.
20. No secrets printed.
21. Existing test suite still passes or failures are explained.

---

# What NOT to do

Do not start any new paper service.

Do not implement sandbox trading.

Do not implement real trading.

Do not auto-switch strategies.

Do not implement Telegram alerts.

Do not implement rollover execution.

Do not modify current systemd units.

Do not turn ORB into live bot.

Do not claim profitability.

Do not overfit by adding many filters after seeing results.

---

# Финальный формат ответа Claude Code

```markdown
## HammerTrade Research Roadmap MVP — готово

### Что сделано

### Созданные файлы

### Изменённые файлы

### Hammer bounded observation

### Strategy Research Lab

### Opening Range Breakout Research

### Regime / news-shock proxy

### Как запустить ORB research

### Источник данных

### ORB top results

### ORB results by regime

### Comparison with hammer maxhold5

### Что НЕ было изменено

### Tests / smoke checks

### Service status

### Артефакты

### Warnings / limitations

### Рекомендация

### Next steps
```
