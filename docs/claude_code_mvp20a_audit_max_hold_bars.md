# Claude Code Prompt — MVP-2.0a: Audit `max_hold_bars`

## Контекст проекта

Проект: `HammerTrade / MOEXF`.

Это исследовательский trading/paper-trading бот для MOEX futures.

Текущий основной режим:

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

Важно: работающий `hammertrade-paper.service` не трогать.

---

## Что уже сделано

## MVP-1.7

Paper trading daemon:

```text
data/paper/paper_state.sqlite
out/paper/paper_trades_SiM6_SELL.csv
scripts/paper_report.py
src/paper/report.py
```

## MVP-1.8

Operational Safety Layer:

```text
configs/market_hours/moex_futures.yaml
src/market/market_hours.py
scripts/check_paper_status.py
runtime/paper_status_SiM6_SELL.json
docs/paper_trader_operational.md
```

## MVP-1.9

Paper Trading Diagnostics:

```text
src/paper/diagnostics.py
scripts/paper_diagnostics.py
tests/test_paper_diagnostics.py
docs/paper_trader_diagnostics.md
```

## MVP-2.0

Backtest Diagnostic Filters.

Создано:

```text
src/backtest/diagnostic_filters.py
src/backtest/diagnostic_grid.py
scripts/backtest_diagnostic_filters.py
configs/backtest_diagnostic_filters_sim6_sell.yaml
tests/test_backtest_diagnostic_filters.py
docs/backtest_diagnostic_filters.md
```

Артефакты MVP-2.0:

```text
reports/backtest_diagnostic_filters_SiM6_SELL_latest.md
out/backtest_diagnostic_filters_SiM6_SELL_latest.csv
out/backtest_diagnostic_trades_SiM6_SELL_latest.csv
```

---

## Почему нужен MVP-2.0a

В MVP-2.0 `max_hold_bars` дал слишком сильное улучшение:

```text
Baseline:
  trades: 113
  winrate: 82.3%
  net PnL: +21 024 RUB
  PF: 4.007
  max drawdown: 1 250 RUB
  profitable days: 44/53 (83%)

max_hold_3:
  trades: 114
  net PnL: +22 684 RUB
  PF: 14.826
  max drawdown: 340 RUB
  daily stability: 92%

max_hold_5:
  trades: 114
  net PnL: +22 624 RUB
  PF: 7.772
  max drawdown: 620 RUB
  daily stability: 94%
```

Это выглядит перспективно, но подозрительно сильно. Перед MVP-2.1 нужно проверить, нет ли бага, look-ahead bias, некорректного exit priority или неэквивалентности baseline/paper.

---

## Главная цель MVP-2.0a

Проверить корректность и устойчивость результата `max_hold_bars`.

Это НЕ новый этап оптимизации.

Нужно ответить:

```text
Можно ли доверять результату max_hold_bars=3/5 из MVP-2.0?
Можно ли после аудита рекомендовать max_hold_bars=5 для paper trader MVP-2.1?
```

---

## Жёсткие ограничения

Строго запрещено:

- менять `hammertrade-paper.service`;
- останавливать paper trader;
- менять live/paper trading logic;
- включать `max_hold_bars` в paper trader;
- менять production paper config;
- запускать real trading;
- запускать sandbox orders;
- вызывать broker execution;
- менять `.env`;
- печатать токены;
- удалять существующие SQLite/CSV/reports;
- перезаписывать существующие отчёты без timestamp;
- оптимизировать параметры стратегии;
- делать новые фильтры;
- объявлять стратегию доказанно прибыльной.

Разрешено:

- читать артефакты MVP-2.0;
- читать historical raw data / debug CSV;
- запускать existing backtest diagnostic filters;
- добавлять audit scripts/modules;
- создавать новые audit CSV/Markdown reports;
- добавлять tests/smoke checks;
- обновлять документацию;
- сравнивать baseline vs `max_hold_3` vs `max_hold_5`;
- делать post-trade analysis;
- делать out-of-sample checks.

---

## Что изучить перед реализацией

Изучи:

```text
src/backtest/diagnostic_filters.py
src/backtest/diagnostic_grid.py
scripts/backtest_diagnostic_filters.py
configs/backtest_diagnostic_filters_sim6_sell.yaml
out/backtest_diagnostic_filters_SiM6_SELL_latest.csv
out/backtest_diagnostic_trades_SiM6_SELL_latest.csv
reports/backtest_diagnostic_filters_SiM6_SELL_latest.md
```

Также найти существующие backtest модули:

```bash
find src/backtest -type f | sort
find scripts -maxdepth 1 -type f | grep -E "backtest|grid|walk|diagnostic"
```

Понять:

1. Как baseline сценарий создаёт сделки.
2. Как `max_hold_bars` меняет exit.
3. Как определяется `bars_held`.
4. Как определяется `exit_reason`.
5. Как считается PnL.
6. Используется ли high/low/close свечи выхода корректно.
7. Есть ли возможность, что выход использует будущие данные.
8. Совпадают ли trade_id / signal_id между baseline и max_hold scenarios.
9. Почему baseline дал 113 сделок, а `max_hold_3/5` дали 114 сделок.
10. Что за одна дополнительная сделка и откуда она взялась.

---

## Ожидаемые новые файлы

Желательная структура:

```text
src/backtest/max_hold_audit.py
scripts/audit_max_hold_bars.py
tests/test_max_hold_audit.py
docs/max_hold_bars_audit.md
```

Если по архитектуре лучше другое место — адаптироваться.

---

## CLI

Добавить скрипт:

```text
scripts/audit_max_hold_bars.py
```

Базовый запуск:

```bash
python scripts/audit_max_hold_bars.py
```

Запуск с путями:

```bash
python scripts/audit_max_hold_bars.py \
  --summary-csv out/backtest_diagnostic_filters_SiM6_SELL_latest.csv \
  --trades-csv out/backtest_diagnostic_trades_SiM6_SELL_latest.csv
```

Желательные аргументы:

```bash
--baseline-scenario baseline
--scenario-a max_hold_3
--scenario-b max_hold_5
--group-by month
--top-n 20
```

CLI должен печатать:

```text
HammerTrade max_hold_bars audit
Summary CSV : ...
Trades CSV  : ...
Scenarios   : baseline, max_hold_3, max_hold_5
Baseline    : trades=..., net=..., PF=..., maxDD=...
max_hold_3  : trades=..., net=..., PF=..., maxDD=...
max_hold_5  : trades=..., net=..., PF=..., maxDD=...
Report      : reports/max_hold_bars_audit_SiM6_SELL_YYYYMMDD_HHMMSS.md
Warnings    : N
Verdict     : PASS / PASS_WITH_WARNINGS / FAIL
```

---

## Output files

Создать timestamped артефакты:

```text
reports/max_hold_bars_audit_SiM6_SELL_YYYYMMDD_HHMMSS.md
out/max_hold_bars_audit_trades_SiM6_SELL_YYYYMMDD_HHMMSS.csv
out/max_hold_bars_audit_deltas_SiM6_SELL_YYYYMMDD_HHMMSS.csv
```

Также можно создать latest copies:

```text
reports/max_hold_bars_audit_SiM6_SELL_latest.md
out/max_hold_bars_audit_trades_SiM6_SELL_latest.csv
out/max_hold_bars_audit_deltas_SiM6_SELL_latest.csv
```

Не перезаписывать старые timestamped отчёты.

---

## Что нужно проверить

## 1. Scenario consistency

Сравнить:

```text
baseline
max_hold_3
max_hold_5
```

Показать:

```text
trades
wins
losses
winrate
net_pnl
gross_profit
gross_loss
profit_factor
max_drawdown
expectancy
best_trade
worst_trade
avg_bars_held
exit_reason distribution
```

Особое внимание:

```text
baseline trades = 113
max_hold_3 trades = 114
max_hold_5 trades = 114
```

Нужно объяснить, почему количество сделок отличается.

Если объяснить нельзя — audit verdict должен быть `FAIL` или `PASS_WITH_WARNINGS`.

---

## 2. Exit reason distribution

Для каждого сценария вывести распределение:

```text
TAKE
STOP
HOLD_EXIT
TIME_EXIT
TIMEOUT
EOD_EXIT
UNKNOWN
```

Важно понять:

- за счёт чего вырос PF;
- стало ли сильно меньше STOP;
- появилось ли много HOLD_EXIT;
- как считаются HOLD_EXIT;
- по какой цене закрываются HOLD_EXIT.

Обязательно показать:

```text
exit_reason
trades
net_pnl
avg_pnl
winrate
```

---

## 3. Trade-level matching

Нужно сопоставить сделки baseline vs max_hold_3/max_hold_5.

Сопоставлять по лучшему доступному ключу:

```text
signal_id
signal_timestamp
entry_timestamp
entry_price
direction
```

Если trade_id меняется между сценариями, использовать composite key.

Для каждой сделки в audit CSV вывести:

```text
match_key
signal_timestamp
entry_timestamp
direction
entry_price
baseline_exit_timestamp
baseline_exit_price
baseline_exit_reason
baseline_pnl_rub
baseline_bars_held
max_hold_3_exit_timestamp
max_hold_3_exit_price
max_hold_3_exit_reason
max_hold_3_pnl_rub
max_hold_3_bars_held
delta_pnl_hold3_vs_baseline
max_hold_5_exit_timestamp
max_hold_5_exit_price
max_hold_5_exit_reason
max_hold_5_pnl_rub
max_hold_5_bars_held
delta_pnl_hold5_vs_baseline
classification
```

Classification examples:

```text
SAME_RESULT
MAX_HOLD_SAVED_STOP
MAX_HOLD_CUT_WINNER
MAX_HOLD_SMALLER_WIN
MAX_HOLD_SMALLER_LOSS
MAX_HOLD_LARGER_LOSS
MAX_HOLD_CHANGED_EXIT_REASON
UNMATCHED_BASELINE
UNMATCHED_MAX_HOLD
```

---

## 4. What exactly improves result

Вывести:

```text
Top 20 improvements for max_hold_3 vs baseline
Top 20 degradations for max_hold_3 vs baseline
Top 20 improvements for max_hold_5 vs baseline
Top 20 degradations for max_hold_5 vs baseline
```

Обязательно ответить:

1. Сколько STOP baseline были “спасены” max_hold?
2. Сколько TAKE baseline были “обрезаны” max_hold?
3. Сколько больших winners max_hold уменьшил?
4. Сколько больших losers max_hold уменьшил?
5. Сколько сделок стали хуже?
6. Сколько сделок стали лучше?

---

## 5. Look-ahead bias audit

Проверить и описать:

1. На какой свече выполняется entry.
2. С какой свечи начинается отсчёт `bars_held`.
3. На какой свече разрешён `max_hold` exit.
4. Используется ли цена close текущей свечи или будущей свечи.
5. Не используется ли информация о future high/low для решения, закрывать ли по hold.
6. Если на одной свече одновременно достижимы stop/take/hold, какой порядок приоритета.
7. Одинаков ли порядок приоритета exit в baseline и max_hold scenarios.

Нужно явно написать:

```text
Look-ahead check: PASS / PASS_WITH_WARNINGS / FAIL
```

---

## 6. Exit priority audit

Проверить порядок exit conditions.

Нужно зафиксировать:

```text
Actual exit priority:
1.
2.
3.
```

Проверить, что `max_hold_bars` не перетирает stop/take, которые должны были сработать раньше.

Особенно важно:

```text
Если stop или take достигнуты на той же свече, где наступил max_hold, что происходит?
```

В отчёте написать:

```text
Exit priority check: PASS / PASS_WITH_WARNINGS / FAIL
```

---

## 7. Period stability

Разбить результат по периодам:

```text
month
week
```

Минимум по месяцам:

```text
January
February
March
April
```

Для каждого сценария:

```text
trades
net_pnl
PF
max_drawdown
winrate
profitable_days_pct
```

Нужно ответить:

1. `max_hold_3/5` улучшает результат во всех месяцах или только в одном?
2. Есть ли месяц, где max_hold хуже baseline?
3. Не держится ли весь эффект на одном периоде?
4. Что происходит в out-of-sample месяце?

---

## 8. Simple out-of-sample check

Если данных хватает, сделать простой split:

```text
Train: 2026-01-15 – 2026-03-31
Test:  2026-04-01 – 2026-04-09
```

Если период другой — адаптировать под доступные данные.

Нужно сравнить:

```text
baseline
max_hold_3
max_hold_5
```

Для train и test отдельно:

```text
trades
net_pnl
PF
max_drawdown
winrate
expectancy
```

Если test слишком маленький, вывести `LOW_SAMPLE`.

---

## 9. Slippage sensitivity

Если в MVP-2.0 уже есть slippage scenarios — использовать их.

Если нет, сделать простой sensitivity check, если это возможно без большой переработки:

```text
slippage_points = 0
slippage_points = 1
slippage_points = 2
slippage_points = 5
```

Сравнить baseline vs max_hold_5.

Если slippage нельзя корректно применить в audit без повторного backtest — не делать костыль, а написать warning:

```text
Slippage sensitivity was not re-run in audit; requires rerunning backtest scenarios.
```

---

## 10. Paper vs backtest equivalence check

Проверить, насколько backtest scenario с `max_hold_bars` можно будет перенести в paper trader.

Ответить:

1. Есть ли в paper trader понятие `bars_held`?
2. Считается ли оно так же, как в backtest?
3. Есть ли в paper trader доступ к нужному candle close для `max_hold` exit?
4. Что будет, если `max_hold_bars=5`, но рынок закрылся/клиринг/market closed?
5. Как это взаимодействует с operational safety layer?
6. Можно ли реализовать `max_hold_bars` в paper без изменения логики entry?
7. Нужен ли config flag?
8. Можно ли быстро откатить?

Вывод:

```text
Paper implementation readiness:
READY / READY_WITH_WARNINGS / NOT_READY
```

---

## Markdown report structure

Отчёт должен быть на русском языке.

Файл:

```text
reports/max_hold_bars_audit_SiM6_SELL_YYYYMMDD_HHMMSS.md
```

Структура:

```markdown
# max_hold_bars Audit — SiM6 SELL

## Цель аудита

## Источник данных

## Проверяемые сценарии

## Executive summary

## Scenario consistency

## Exit reason distribution

## Trade-level matching

## Top improvements

## Top degradations

## Look-ahead bias audit

## Exit priority audit

## Period stability

## Out-of-sample check

## Slippage sensitivity

## Paper vs backtest equivalence

## Findings

## Verdict

## Recommendation for MVP-2.1

## Warnings and limitations
```

---

## Verdict rules

В конце отчёта должен быть один из verdict:

## PASS

Только если:

```text
- количество сделок объяснено;
- нет признаков look-ahead;
- exit priority корректный;
- max_hold улучшает не только один период;
- trade-level deltas логичны;
- реализация переносима в paper trader;
- нет критичных warnings.
```

## PASS_WITH_WARNINGS

Если:

```text
- результат выглядит полезным;
- критичных багов не найдено;
- но есть ограничения:
  - малый out-of-sample;
  - нет slippage sensitivity;
  - эффект частично сконцентрирован;
  - нужна аккуратная реализация в paper.
```

## FAIL

Если:

```text
- найден look-ahead;
- max_hold перетирает stop/take некорректно;
- количество сделок отличается без объяснения;
- baseline не совпадает с ожидаемой логикой;
- trade matching показывает некорректные сделки;
- перенос в paper невозможен без серьёзной переработки.
```

---

## Recommendation for MVP-2.1

Если verdict `PASS` или `PASS_WITH_WARNINGS`, дать рекомендацию:

```text
Recommended candidate:
max_hold_bars = 5
```

Почему `5`, а не `3`:

```text
max_hold_3 может быть слишком агрессивным и подозрительно сильным.
max_hold_5 более консервативен и лучше подходит для paper validation.
```

Если audit не подтверждает:

```text
Do not implement max_hold_bars in paper trader yet.
Fix/extend backtest audit first.
```

---

## Tests / smoke checks

Добавить тесты:

```text
tests/test_max_hold_audit.py
```

Минимум проверить:

1. Trade matching по composite key.
2. Delta PnL считается корректно.
3. Classification `MAX_HOLD_SAVED_STOP`.
4. Classification `MAX_HOLD_CUT_WINNER`.
5. Classification `SAME_RESULT`.
6. Unmatched baseline trade помечается.
7. Unmatched max_hold trade помечается.
8. Exit reason distribution считается корректно.
9. Period split by month работает.
10. Empty scenario не ломает отчёт.
11. Verdict `FAIL`, если есть unexplained unmatched trades.
12. Verdict `PASS_WITH_WARNINGS`, если есть low sample out-of-sample.
13. Markdown report генерируется.

---

## Backward compatibility

После реализации выполнить:

```bash
.venv/bin/python -m pytest tests/test_max_hold_audit.py
```

И желательно:

```bash
.venv/bin/python -m pytest tests/test_backtest_diagnostic_filters.py tests/test_paper_diagnostics.py tests/test_max_hold_audit.py
```

В финальном ответе указать, что именно запускалось.

---

## Команды проверки на сервере

После реализации выполнить:

```bash
cd /opt/hammertrade
source .venv/bin/activate

python scripts/audit_max_hold_bars.py \
  --summary-csv out/backtest_diagnostic_filters_SiM6_SELL_latest.csv \
  --trades-csv out/backtest_diagnostic_trades_SiM6_SELL_latest.csv
```

Показать артефакты:

```bash
ls -lah reports | grep max_hold_bars_audit | tail
ls -lah out | grep max_hold_bars_audit | tail
```

Проверить, что paper service жив:

```bash
sudo systemctl status hammertrade-paper --no-pager
.venv/bin/python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json
```

Если `check_paper_status.py` недоступен — не считать ошибкой, просто указать.

---

## Acceptance Criteria

MVP-2.0a считается готовым, если:

1. Есть CLI:

```text
scripts/audit_max_hold_bars.py
```

2. Есть audit module:

```text
src/backtest/max_hold_audit.py
```

3. Скрипт запускается на артефактах MVP-2.0.
4. Сравниваются сценарии baseline, max_hold_3, max_hold_5.
5. Объяснена разница в количестве сделок baseline vs max_hold.
6. Есть exit reason distribution.
7. Есть trade-level matching.
8. Есть top improvements/degradations.
9. Есть look-ahead audit.
10. Есть exit priority audit.
11. Есть month/week stability.
12. Есть simple out-of-sample check.
13. Есть paper vs backtest equivalence check.
14. Генерируется Markdown report.
15. Генерируются audit CSV.
16. Есть verdict: PASS / PASS_WITH_WARNINGS / FAIL.
17. Есть рекомендация по MVP-2.1.
18. Текущий paper trader не изменён.
19. Systemd service не изменён.
20. Тесты или smoke checks выполнены.
21. Claude Code в финальном ответе указал:
    - созданные файлы;
    - изменённые файлы;
    - команды запуска;
    - артефакты;
    - verdict;
    - можно ли доверять `max_hold_bars`;
    - можно ли двигаться к MVP-2.1.

---

## Что НЕ делать в MVP-2.0a

Не включать `max_hold_bars` в paper trader.

Не менять:

```text
scripts/run_paper_trader.py
src/paper/engine.py
systemd unit
production paper config
```

Не запускать real/sandbox trading.

Не делать Telegram notifications.

Не делать cron/systemd timers.

Не оптимизировать новые параметры.

Не расширять сетку фильтров.

Не делать вывод “стратегия доказана”.

---

## Важная интерпретация

Даже если audit проходит успешно, правильная формулировка:

```text
max_hold_bars=5 можно проверить в следующем paper trading MVP как контролируемый эксперимент.
```

Нельзя писать:

```text
Можно включать live trading.
```

Если audit выявит проблемы:

```text
Результат MVP-2.0 по max_hold_bars нельзя использовать для изменения paper trader до исправления/уточнения backtest logic.
```

---

## Финальный формат ответа Claude Code

После выполнения задачи ответить так:

```markdown
## MVP-2.0a max_hold_bars Audit — готово

### Что сделано

### Созданные файлы

### Изменённые файлы

### Как запустить

### Источник данных

### Сравнённые сценарии

### Главные находки

### Почему отличалось количество сделок

### Look-ahead audit

### Exit priority audit

### Period stability

### Out-of-sample

### Paper implementation readiness

### Verdict

### Recommendation for MVP-2.1

### Что НЕ было изменено

### Тесты / smoke checks

### Артефакты

### Warnings / limitations
```
