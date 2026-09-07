# Claude Code Prompt — MVP-2.3: Hour 12 Targeted Audit

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

Baseline service: hammertrade-paper.service
Maxhold5 service: hammertrade-paper-maxhold5.service

Baseline DB: data/paper/paper_state.sqlite
Maxhold5 DB: data/paper/paper_state_maxhold5.sqlite

Baseline status: runtime/paper_status_SiM6_SELL.json
Maxhold5 status: runtime/paper_status_SiM6_SELL_maxhold5.json
```

Сейчас работают два paper-сервиса:

```text
baseline: max_hold_bars=None
maxhold5: max_hold_bars=5
```

Важно: в этом MVP нельзя менять работающие сервисы, стратегию, paper trader, systemd units или параметры торговли. Это только targeted audit / backtest.

---

## Текущий статус проекта

По live paper отчёту за 3 недели:

### Baseline

```text
Период: 2026-05-04 — 2026-05-29
Closed trades: 86
Winrate: 60.5%
Net PnL: +55.70 RUB
Profit Factor: 1.01
Avg PnL / trade: +0.65 RUB
Worst trade: -1 140.05 RUB
Avg bars held: 3.7
```

### Maxhold5

```text
Период: 2026-05-13 — 2026-05-29
Closed trades: 57
Winrate: 63.2%
Net PnL: +867.15 RUB
Profit Factor: 1.19
Avg PnL / trade: +15.21 RUB
Worst trade: -960.05 RUB
Avg bars held: 2.5
```

### Корректное A/B сравнение

Maxhold5 стартовал 2026-05-13, поэтому корректное сравнение только на общем периоде:

```text
Baseline May 13–29: -862.80 RUB
Maxhold5 May 13–29: +867.15 RUB
Delta in favor of maxhold5: +1 729.95 RUB
```

### Главные наблюдения

```text
1. Baseline за 3 недели практически в ноль: PF 1.01.
2. Maxhold5 заметно лучше baseline на общем периоде, но PF 1.19 — всё ещё слабый.
3. Сделки, удерживаемые >3 баров, в baseline убыточны.
4. ONE_BAR_STOP — 14 сделок, все убыточные, около -2400 RUB.
5. BIG_RISK / risk >50 pts даёт и лучшие сделки, и худшие; грубо резать нельзя.
6. Самый токсичный временной слот — 12:xx MSK.
```

---

## Почему нужен MVP-2.3

По live/paper baseline:

```text
12:xx MSK:
  trades: 7
  winrate: 28.6%
  net: -1 460.35 RUB
  PF: 0.21
```

Это сильнейшая текущая гипотеза для фильтрации.

В MVP-2.2 Backtest Exit/Time Filters v2 уже было:

```text
Historical baseline:
  113 trades
  PF = 3.391
  net = +19 754 RUB
  MaxDD = 1 250 RUB

exclude_hour_12:
  PF = 4.368
  net = +20 345 RUB
  MaxDD = 800 RUB
```

То есть `exclude_hour_12` выглядел полезно и на истории, и на live paper, но time filters имеют высокий риск переобучения.

Теперь нужен не общий grid, а targeted audit:

```text
а) глубже разобрать именно час 12;
б) проверить историческую устойчивость;
в) проверить live/paper baseline;
г) проверить live/paper maxhold5;
д) понять, не режет ли фильтр большие прибыльные сделки;
е) понять, можно ли запускать следующий paper experiment maxhold5 + exclude_hour_12.
```

---

## Главная цель MVP-2.3

Сделать targeted audit:

```text
MVP-2.3 — Hour 12 Targeted Audit
```

Ответить:

```text
Стоит ли рассматривать exclude_hour_12 как следующий controlled paper experiment?
```

Не внедрять фильтр. Только анализ и рекомендация.

---

## Жёсткие ограничения

Строго запрещено:

- менять `hammertrade-paper.service`;
- менять `hammertrade-paper-maxhold5.service`;
- менять их systemd unit files;
- перезапускать сервисы без необходимости;
- менять текущий A/B experiment;
- менять `max_hold_bars=5`;
- включать `exclude_hour_12` в paper trader;
- запускать третий service;
- менять HammerDetector;
- менять core candle pattern logic;
- менять entry logic;
- менять stop/take logic;
- менять `.env`;
- печатать токены;
- удалять SQLite/CSV/reports;
- запускать real trading;
- запускать sandbox orders;
- делать вывод “стратегия доказана”.

Разрешено:

- читать historical backtest artifacts;
- читать live/paper SQLite;
- читать CSV/reports;
- добавлять read-only analysis scripts;
- создавать CSV/Markdown reports;
- добавлять tests;
- добавлять docs.

---

## Core strategy must stay unchanged

Core strategy:

```text
Hammer / inverted hammer / upper wick reversal pattern on MOEX futures.
Small body + long shadow / wick.
Candle geometry based reversal signal.
Current paper mode focuses on SiM6 SELL side.
```

В этом MVP нельзя менять:

```text
HammerDetector
core candle pattern logic
entry signal source
stop/take geometry
direction filter
```

---

## Что изучить перед реализацией

Изучи:

```text
src/backtest/exit_time_filters_v2.py
src/backtest/exit_time_grid_v2.py
scripts/backtest_exit_time_filters_v2.py
configs/backtest_exit_time_filters_v2_sim6_sell.yaml
reports/backtest_exit_time_filters_v2_SiM6_SELL_latest.md
out/backtest_exit_time_filters_v2_SiM6_SELL_latest.csv
out/backtest_exit_time_filters_v2_trades_SiM6_SELL_latest.csv

src/paper/diagnostics.py
scripts/paper_diagnostics.py
scripts/compare_paper_experiments.py
data/paper/paper_state.sqlite
data/paper/paper_state_maxhold5.sqlite
```

Нужно понять:

```text
1. Как сейчас считается hour MSK.
2. Как в historical backtest применялся exclude_hour_12.
3. Какие historical trades были в 12:xx MSK.
4. Какие live/paper baseline trades были в 12:xx MSK.
5. Какие live/paper maxhold5 trades были в 12:xx MSK.
6. Есть ли пересечение hour 12 с BIG_RISK.
7. Есть ли пересечение hour 12 с ONE_BAR_STOP.
8. Режет ли hour 12 large winners.
9. Убирает ли hour 12 large losers.
10. Держится ли эффект на одной-двух сделках или распределён.
```

---

## Ожидаемые новые файлы

Желательная структура:

```text
src/analytics/hour_filter_audit.py
scripts/audit_hour_filter.py
tests/test_hour_filter_audit.py
docs/hour_filter_audit.md
```

Если в проекте нет `src/analytics`, можно использовать:

```text
src/backtest/hour_filter_audit.py
```

или другое подходящее место.

Не смешивать этот audit с торговой логикой.

---

## CLI

Добавить скрипт:

```text
scripts/audit_hour_filter.py
```

Базовый запуск:

```bash
python scripts/audit_hour_filter.py
```

Запуск с параметрами:

```bash
python scripts/audit_hour_filter.py \
  --hour 12 \
  --timezone Europe/Moscow \
  --baseline-db data/paper/paper_state.sqlite \
  --maxhold-db data/paper/paper_state_maxhold5.sqlite \
  --backtest-summary out/backtest_exit_time_filters_v2_SiM6_SELL_latest.csv \
  --backtest-trades out/backtest_exit_time_filters_v2_trades_SiM6_SELL_latest.csv \
  --output reports/hour_filter_audit_hour12_SiM6_SELL_latest.md
```

Дополнительно:

```text
--hours 12
--compare-hours 9,10,11,12,13,15,18,19,20,21,22,23
--min-trades 5
```

---

## Output files

Создать timestamped artifacts:

```text
reports/hour_filter_audit_hour12_SiM6_SELL_YYYYMMDD_HHMMSS.md
out/hour_filter_audit_hour12_SiM6_SELL_YYYYMMDD_HHMMSS.csv
```

И latest copies:

```text
reports/hour_filter_audit_hour12_SiM6_SELL_latest.md
out/hour_filter_audit_hour12_SiM6_SELL_latest.csv
```

---

## Что нужно посчитать

### 1. Historical backtest hour 12

По historical backtest trades:

```text
Jan 15 — Apr 9 2026
SiM6 SELL
```

Посчитать отдельно:

```text
all_hours baseline
hour_12_only
baseline_without_hour_12
exclude_hour_12 scenario from MVP-2.2 if available
```

Метрики:

```text
trades
wins
losses
winrate
net_pnl
gross_profit
gross_loss
PF
expectancy
best_trade
worst_trade
max_drawdown
avg_bars_held
profitable_days_pct
profitable_weeks_pct
```

### 2. Historical period stability

Разбить hour 12 на периоды:

```text
month
week
day if useful
```

Нужно ответить:

```text
1. Hour 12 плохой в каждом месяце или только в одном?
2. Сколько было сделок hour 12 по месяцам?
3. Есть ли месяцы без сделок?
4. Есть ли одна сделка, которая создаёт весь эффект?
5. Что происходит по неделям?
```

Если данных мало, поставить флаг:

```text
LOW_SAMPLE
```

### 3. Live/paper baseline hour 12

По `data/paper/paper_state.sqlite`:

```text
baseline live/paper 2026-05-04 — latest
```

Посчитать:

```text
all baseline
hour_12_only
baseline_without_hour_12
```

Метрики:

```text
trades
wins/losses
net_pnl
PF
expectancy
best/worst trade
diagnostic flags distribution
BIG_RISK count/net
ONE_BAR_STOP count/net
TINY_TAKE count/net
```

Нужно показать конкретные сделки hour 12:

```text
entry_timestamp_msk
entry_price
stop_price
take_price
exit_price
exit_reason
pnl_rub
bars_held
flags
```

### 4. Live/paper maxhold5 hour 12

По `data/paper/paper_state_maxhold5.sqlite`:

```text
maxhold5 live/paper 2026-05-13 — latest
```

Посчитать то же.

Цель:

```text
Понять, является ли hour 12 проблемой только baseline или также maxhold5.
```

### 5. Counterfactual live/paper

Для текущей live/paper baseline посчитать:

```text
actual baseline
baseline_without_hour_12
delta
```

Пример:

```text
actual baseline net: +55.70 RUB
without hour 12: +1516.05 RUB
delta: +1460.35 RUB
```

Для maxhold5 тоже:

```text
actual maxhold5
maxhold5_without_hour_12
delta
```

Обязательно написать:

```text
This is counterfactual on observed paper trades, not live execution proof.
```

### 6. Big winners / big losers impact

Очень важно проверить, что `exclude_hour_12` не режет основные источники прибыли.

Для historical и live отдельно:

```text
large_winner = pnl_rub >= +500
large_loser = pnl_rub <= -500
BIG_RISK flag if available
ONE_BAR_STOP flag if available
```

Посчитать:

```text
hour_12_large_winners_count
hour_12_large_winners_net
hour_12_large_losers_count
hour_12_large_losers_net
hour_12_BIG_RISK_count
hour_12_BIG_RISK_net
hour_12_ONE_BAR_STOP_count
hour_12_ONE_BAR_STOP_net
```

Ответить:

```text
1. Убирает ли exclude_hour_12 large winners?
2. Убирает ли exclude_hour_12 large losers?
3. Убирает ли он BIG_RISK winners, которые нельзя трогать грубо?
4. Убирает ли он ONE_BAR_STOP?
5. Улучшает ли результат потому, что удаляет именно плохие сделки, или просто выкидывает маленькую выборку?
```

### 7. Comparison with other hours

Сравнить hour 12 с другими подозрительными часами:

```text
11
13
18
19
20
21
```

И хорошими часами:

```text
9
10
15
22
23
```

Цель:

```text
Понять, является ли hour 12 уникально плохим,
или это просто один из многих малых срезов.
```

В отчёте показать top/bottom hours:

```text
hour
trades
net
PF
winrate
LOW_SAMPLE flag
```

### 8. Overfit risk assessment

Дать явную оценку риска переобучения.

Факторы за фильтр:

```text
hour 12 repeatedly bad in live/paper
hour 12 improved historical backtest in MVP-2.2
hour 12 removes large losers / ONE_BAR_STOP
hour 12 does not remove key winners
```

Факторы против:

```text
small sample
time filters are high-overfit-risk
market regime may change
hour may be session-specific
effect may be caused by 1–2 trades
```

Итог:

```text
overfit_risk = LOW / MEDIUM / HIGH
```

Скорее всего:

```text
MEDIUM or HIGH
```

Но пусть вывод следует из данных.

### 9. Candidate decision

В отчёте дать один из вариантов.

#### A. Strong candidate for paper experiment

Если:

```text
historical exclude_hour_12 improves PF and net
live/paper without hour_12 improves materially
hour_12 does not contain major BIG_RISK winners
effect is not caused by one single trade only
period stability acceptable
overfit risk not HIGH
```

Рекомендация:

```text
Start next controlled paper experiment:
maxhold5 + exclude_hour_12
```

Но не запускать в этом MVP.

#### B. Weak candidate / observe more

Если:

```text
effect exists but sample too small
or cuts winners
or unstable by period
or overfit risk HIGH
```

Рекомендация:

```text
Continue observing and re-check later.
```

#### C. Reject

Если:

```text
historical does not confirm
or live effect is one trade only
or cuts key winners
```

---

## Не запускать новый service в этом MVP

Даже если рекомендация A:

```text
Do not create hammertrade-paper-exclude12.service in MVP-2.3.
Do not modify current services.
Only produce recommendation.
```

Следующий возможный MVP:

```text
MVP-2.4 — Parallel Paper maxhold5 + exclude12 Experiment
```

---

## Markdown report structure

Отчёт на русском языке:

```markdown
# Hour 12 Targeted Audit — SiM6 SELL

## Цель

## Краткий вывод

## Источники данных

## Historical backtest: hour 12

## Historical period stability

## Live/paper baseline: hour 12

## Live/paper maxhold5: hour 12

## Counterfactual without hour 12

## Big winners / big losers impact

## BIG_RISK and ONE_BAR_STOP intersection

## Comparison with other hours

## Overfit risk assessment

## Candidate decision

## Recommendation

## Next MVP
```

---

## CSV output

CSV should include rows:

```text
source
strategy
period
hour
trades
wins
losses
winrate
net_pnl
gross_profit
gross_loss
profit_factor
expectancy
best_trade
worst_trade
big_risk_count
big_risk_net
one_bar_stop_count
one_bar_stop_net
large_winner_count
large_loser_count
low_sample
```

Sources:

```text
historical
live_baseline
live_maxhold5
```

---

## Tests

Добавить тесты:

```text
tests/test_hour_filter_audit.py
```

Минимум:

1. MSK hour extraction works from UTC timestamp.
2. Hour filter selects only requested hour.
3. Excluding hour removes only that hour.
4. PF calculation handles zero loss.
5. LOW_SAMPLE flag works.
6. Counterfactual without hour works.
7. BIG_RISK intersection count works if flags column exists.
8. Missing flags column does not crash.
9. Empty dataset does not crash.
10. Markdown report generation works.

---

## Backward compatibility

Запустить:

```bash
.venv/bin/python -m pytest tests/test_hour_filter_audit.py
```

Желательно:

```bash
.venv/bin/python -m pytest \
  tests/test_hour_filter_audit.py \
  tests/test_exit_time_filters_v2.py \
  tests/test_paper_diagnostics.py
```

Если feasible:

```bash
.venv/bin/python -m pytest
```

Do not break existing suite.

---

## Commands to run on server

```bash
cd /opt/hammertrade
source .venv/bin/activate

python scripts/audit_hour_filter.py \
  --hour 12 \
  --timezone Europe/Moscow \
  --baseline-db data/paper/paper_state.sqlite \
  --maxhold-db data/paper/paper_state_maxhold5.sqlite \
  --backtest-summary out/backtest_exit_time_filters_v2_SiM6_SELL_latest.csv \
  --backtest-trades out/backtest_exit_time_filters_v2_trades_SiM6_SELL_latest.csv \
  --output reports/hour_filter_audit_hour12_SiM6_SELL_latest.md

ls -lah reports | grep hour_filter_audit
ls -lah out | grep hour_filter_audit
```

Проверить, что сервисы всё ещё живы:

```bash
sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json
python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL_maxhold5.json
```

---

## Acceptance Criteria

MVP-2.3 готов, если:

1. Есть targeted audit для hour 12.
2. Historical hour 12 посчитан.
3. Live baseline hour 12 посчитан.
4. Live maxhold5 hour 12 посчитан.
5. Counterfactual baseline_without_hour_12 посчитан.
6. Counterfactual maxhold5_without_hour_12 посчитан.
7. Проверено влияние на BIG_RISK.
8. Проверено влияние на ONE_BAR_STOP.
9. Проверено влияние на large winners / large losers.
10. Есть comparison with other hours.
11. Есть overfit risk assessment.
12. Есть candidate decision.
13. Есть рекомендация: запускать ли следующий paper experiment exclude12 или нет.
14. Текущие сервисы не изменены.
15. Тесты/smoke checks выполнены.
16. Claude final answer includes:
    - key metrics;
    - candidate decision;
    - overfit risk;
    - next MVP recommendation.

---

## Что НЕ делать в MVP-2.3

Не менять services.

Не запускать новый service.

Не менять strategy.

Не менять paper trader.

Не менять systemd.

Не менять maxhold5.

Не менять HammerDetector.

Не добавлять real/sandbox orders.

Не делать position sizing report.

Не делать liquidity model.

Не обещать прибыль.

---

## Финальный формат ответа Claude Code

```markdown
## MVP-2.3 Hour 12 Targeted Audit — готово

### Что сделано

### Созданные файлы

### Изменённые файлы

### Как запустить

### Historical hour 12

### Live baseline hour 12

### Live maxhold5 hour 12

### Counterfactual without hour 12

### BIG_RISK / ONE_BAR_STOP impact

### Other hours comparison

### Overfit risk

### Candidate decision

### Что НЕ было изменено

### Tests / smoke checks

### Артефакты

### Рекомендация
```
