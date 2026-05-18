# Claude Code Prompt — MVP-2.1: Parallel Paper Experiment with `max_hold_bars=5`

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
Current systemd service: hammertrade-paper.service
Current baseline state DB: /opt/hammertrade/data/paper/paper_state.sqlite
Current baseline status file: /opt/hammertrade/runtime/paper_status_SiM6_SELL.json
```

Важно: текущий `hammertrade-paper.service` — это baseline. Его нельзя ломать, нельзя менять его поведение по умолчанию и нельзя терять накопленную историю.

---

## Уже сделано

## MVP-1.7 — Paper trading daemon

Основные артефакты:

```text
data/paper/paper_state.sqlite
out/paper/paper_trades_SiM6_SELL.csv
scripts/run_paper_trader.py
scripts/paper_report.py
src/paper/engine.py
src/paper/repository.py
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

## MVP-2.0 — Backtest Diagnostic Filters

Проверены диагностические фильтры на истории.

Главный результат:

```text
max_hold_3:
  PF: 14.826
  maxDD: 340 RUB

max_hold_5:
  PF: 7.772
  maxDD: 620 RUB
```

## MVP-2.0a — Audit `max_hold_bars`

Аудит показал:

```text
Look-ahead audit: PASS
Exit priority audit: PASS
Period stability: positive Jan–Apr
OOS: positive, but LOW_SAMPLE
Paper implementation readiness: READY_WITH_WARNINGS
Verdict: PASS_WITH_WARNINGS
```

Главная рекомендация:

```text
Проверить max_hold_bars=5 в следующем paper trading MVP как контролируемый эксперимент.
```

---

## Главная цель MVP-2.1

Добавить `max_hold_bars=5` в paper trader как optional-параметр и запустить **параллельный paper daemon** рядом с baseline.

Нужен A/B paper experiment:

```text
A: baseline paper trader без max_hold_bars
B: max_hold5 paper trader с max_hold_bars=5
```

Оба режима должны работать на одном рынке и в одно время.

Baseline service должен продолжать работать:

```text
hammertrade-paper.service
```

Новый experimental service:

```text
hammertrade-paper-maxhold5.service
```

---

## Почему выбран план B

Нельзя просто заменить baseline на max_hold5, потому что тогда сравнение будет грязным:

```text
до max_hold рынок был один
после max_hold рынок другой
```

Правильный эксперимент — параллельный:

```text
baseline и max_hold5 видят одни и те же свечи;
отличается только параметр max_hold_bars;
у каждого свой state DB, status file, CSV/reports;
потом сравниваем результаты.
```

---

## Жёсткие ограничения

Строго запрещено:

- ломать текущий `hammertrade-paper.service`;
- менять поведение baseline по умолчанию;
- удалять или мигрировать текущую `data/paper/paper_state.sqlite`;
- перезаписывать baseline CSV/reports;
- включать real trading;
- включать sandbox orders;
- вызывать broker execution;
- менять `.env`;
- печатать токены;
- менять detector;
- менять backtest;
- менять historical reports;
- делать `max_hold_bars` обязательным параметром;
- делать `max_hold_bars=5` дефолтом для baseline;
- объявлять стратегию доказанно прибыльной.

Разрешено:

- добавить optional CLI/config параметр `--max-hold-bars`;
- добавить отдельные пути для experimental state DB/status/CSV/reports;
- добавить отдельный systemd unit template/service для maxhold5;
- добавить тесты;
- добавить diagnostics/report support для experiment name;
- запустить новый service после проверки;
- проверять оба сервиса;
- создать документацию по A/B paper experiment.

---

## Главные требования к реализации

## 1. Optional `max_hold_bars`

Добавить в paper trader optional параметр:

```text
max_hold_bars: int | None
```

Default:

```text
None
```

Если `max_hold_bars is None`, поведение должно быть полностью старым.

Если `max_hold_bars = 5`, то для открытой paper-сделки:

```text
1. На каждой новой торговой свече обновляется bars_held.
2. Сначала проверяются STOP/TAKE.
3. Если STOP/TAKE не сработали, проверяется max_hold_bars.
4. Если bars_held >= max_hold_bars, сделка закрывается по close текущей торговой свечи.
5. exit_reason = MAX_HOLD_EXIT или TIMEOUT_MAX_HOLD.
6. pnl_rub считается тем же способом, что и для прочих paper exits.
```

Рекомендуемое название exit reason:

```text
MAX_HOLD_EXIT
```

Если в проекте уже есть convention `TIMEOUT` — можно использовать `TIMEOUT_MAX_HOLD`, но в отчётах должно быть понятно, что это именно max hold.

---

## 2. Exit priority

Критически важно сохранить порядок:

```text
1. STOP
2. TAKE
3. MAX_HOLD_EXIT
```

Или если текущий проект уже использует другой порядок STOP/TAKE, не менять его, но max_hold должен быть после intrabar stop/take.

Принцип:

```text
max_hold_bars не должен перетирать STOP/TAKE, которые сработали внутри окна.
```

Если на той же свече достижим STOP/TAKE и одновременно наступил max_hold, сначала должен применяться существующий stop/take priority, и только если stop/take не сработали — max_hold exit.

---

## 3. Bars counting

`bars_held` должен считаться по торговым свечам, а не по астрономическому времени.

Важно:

```text
market closed
night gap
weekend
clearing gap
no new candles
```

не должны искусственно увеличивать `bars_held`.

Если сделка открыта и рынок закрыт, max_hold не должен срабатывать просто из-за прошедших часов.

`bars_held` увеличивается только когда появляется новая валидная торговая свеча для инструмента/timeframe.

---

## 4. Parallel state isolation

Новый maxhold5 daemon должен использовать отдельные файлы:

```text
data/paper/paper_state_maxhold5.sqlite
runtime/paper_status_SiM6_SELL_maxhold5.json
out/paper/paper_trades_SiM6_SELL_maxhold5.csv
reports/paper_report_SiM6_SELL_maxhold5.md
reports/paper_diagnostics_SiM6_SELL_maxhold5_latest.md
out/paper/paper_trades_diagnostics_SiM6_SELL_maxhold5_latest.csv
```

Если существующие scripts/report paths не поддерживают suffix/experiment name — добавить поддержку аккуратно и backward-compatible.

Baseline пути должны остаться прежними:

```text
data/paper/paper_state.sqlite
runtime/paper_status_SiM6_SELL.json
out/paper/paper_trades_SiM6_SELL.csv
reports/paper_report_SiM6_SELL.md
```

---

## 5. Experiment name / label

Добавить optional experiment label:

```text
experiment_name = "maxhold5"
```

Использовать его в:

```text
status file
CSV names
report names
diagnostics names
log prefix if possible
systemd service name
```

Baseline может иметь:

```text
experiment_name = "baseline"
```

Но если baseline уже работает без label, не ломать.

---

## 6. CLI changes

Нужно изучить текущий `scripts/run_paper_trader.py`.

Добавить аргументы, если их нет:

```bash
--max-hold-bars 5
--state-db data/paper/paper_state_maxhold5.sqlite
--status-file runtime/paper_status_SiM6_SELL_maxhold5.json
--csv-output out/paper/paper_trades_SiM6_SELL_maxhold5.csv
--experiment-name maxhold5
```

Если какие-то аргументы уже есть под другими именами — использовать существующие.

Важно: текущий запуск baseline без этих аргументов должен работать как раньше.

Пример желаемого запуска maxhold5:

```bash
cd /opt/hammertrade
source .venv/bin/activate

python scripts/run_paper_trader.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --timeframe 1m \
  --profile balanced \
  --direction SELL \
  --state-db data/paper/paper_state_maxhold5.sqlite \
  --status-file runtime/paper_status_SiM6_SELL_maxhold5.json \
  --csv-output out/paper/paper_trades_SiM6_SELL_maxhold5.csv \
  --market-hours-config configs/market_hours/moex_futures.yaml \
  --max-hold-bars 5 \
  --experiment-name maxhold5
```

Актуальные реальные аргументы определить по текущему коду.

---

## 7. systemd service

Создать новый unit:

```text
deploy/systemd/hammertrade-paper-maxhold5.example.service
```

Или если в проекте принято хранить реальные unit files иначе — использовать текущую структуру.

Ожидаемый service:

```text
hammertrade-paper-maxhold5.service
```

Он должен:

- работать под `User=vorontsov`;
- запускаться из `/opt/hammertrade`;
- использовать `/opt/hammertrade/.venv/bin/python`;
- писать отдельный status file;
- писать отдельную SQLite DB;
- писать отдельный CSV;
- использовать `--max-hold-bars 5`;
- не конфликтовать с baseline service.

Важно: не менять существующий `hammertrade-paper.service`.

---

## 8. Reports and diagnostics for maxhold5

Нужно обеспечить возможность собирать отчёты отдельно:

```bash
python scripts/paper_report.py \
  --state-db data/paper/paper_state_maxhold5.sqlite \
  --output reports/paper_report_SiM6_SELL_maxhold5.md
```

И diagnostics:

```bash
python scripts/paper_diagnostics.py \
  --state-db data/paper/paper_state_maxhold5.sqlite \
  --csv-fallback out/paper/paper_trades_SiM6_SELL_maxhold5.csv \
  --ticker SiM6 \
  --direction SELL \
  --experiment-name maxhold5
```

Если `paper_diagnostics.py` сейчас не поддерживает `--experiment-name`, добавить backward-compatible поддержку.

Нужно, чтобы baseline diagnostics продолжал работать как раньше:

```bash
python scripts/paper_diagnostics.py
```

---

## 9. A/B comparison report

Желательно добавить простой сравнивающий скрипт:

```text
scripts/compare_paper_experiments.py
```

Он должен сравнить две SQLite базы:

```bash
python scripts/compare_paper_experiments.py \
  --baseline-db data/paper/paper_state.sqlite \
  --experiment-db data/paper/paper_state_maxhold5.sqlite \
  --baseline-name baseline \
  --experiment-name maxhold5 \
  --output reports/paper_ab_compare_baseline_vs_maxhold5_latest.md
```

Минимальный отчёт:

```markdown
# Paper A/B Compare — baseline vs maxhold5

## Period

## Service status

## Summary

| Metric | baseline | maxhold5 | delta |
|---|---:|---:|---:|

## Exit reason distribution

## Daily stats

## Best/worst trades

## Open trades

## Notes / limitations
```

Метрики:

```text
total_trades
closed_trades
open_trades
wins
losses
winrate
gross_profit
gross_loss
net_pnl
profit_factor
expectancy
best_trade
worst_trade
avg_bars_held
exit_reason counts
MAX_HOLD_EXIT count
```

Важно: в первые дни у experiment может быть мало данных. Скрипт не должен падать.

Если compare script сделать слишком долго — можно отложить, но лучше реализовать минимально.

---

## 10. Startup safety

Перед запуском нового service:

1. Проверить, что baseline service жив:

```bash
sudo systemctl status hammertrade-paper --no-pager
```

2. Сделать backup текущей baseline DB:

```bash
cp -a data/paper/paper_state.sqlite data/paper/paper_state.sqlite.bak_$(date +%Y%m%d_%H%M%S)
```

3. Не трогать baseline unit.

4. Проверить, что новая DB либо отсутствует, либо явно является maxhold5 DB.

5. Запустить maxhold5 service.

6. Проверить оба сервиса:

```bash
sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
```

7. Проверить оба status files:

```bash
cat runtime/paper_status_SiM6_SELL.json
cat runtime/paper_status_SiM6_SELL_maxhold5.json
```

---

## 11. Logging

Если возможно, добавить в логи experiment label:

```text
[baseline]
[maxhold5]
```

И при max hold exit логировать:

```text
MAX_HOLD_EXIT trade_id=... bars_held=5 exit_price=... pnl_rub=...
```

Не обязательно делать отдельную сложную logging-систему. Главное — чтобы в `journalctl -u hammertrade-paper-maxhold5` было понятно, что это maxhold5.

---

## Tests

Добавить тесты:

```text
tests/test_paper_max_hold.py
```

Минимум проверить:

1. Default `max_hold_bars=None` не меняет поведение.
2. `max_hold_bars=5` закрывает сделку при `bars_held >= 5`.
3. STOP имеет приоритет над MAX_HOLD_EXIT.
4. TAKE имеет приоритет над MAX_HOLD_EXIT.
5. `bars_held` увеличивается только на новых торговых свечах.
6. MAX_HOLD_EXIT считает PnL для SELL корректно.
7. MAX_HOLD_EXIT считает PnL для BUY корректно, если BUY поддерживается моделью.
8. Новый state DB path не совпадает с baseline.
9. `paper_diagnostics.py` умеет читать maxhold5 DB.
10. Compare script не падает на пустой experiment DB.
11. Compare script корректно считает delta.
12. CLI parser принимает `--max-hold-bars`.

Если какие-то тесты требуют слишком большой перестройки, сделать smoke tests, но не пропускать критичные проверки exit priority.

---

## Backward compatibility checks

Обязательно проверить:

```bash
.venv/bin/python -m pytest tests/test_paper_max_hold.py
```

И желательно:

```bash
.venv/bin/python -m pytest tests/test_paper_diagnostics.py tests/test_max_hold_audit.py tests/test_paper_max_hold.py
```

Если полный suite допустим по времени:

```bash
.venv/bin/python -m pytest
```

Проверить baseline CLI help:

```bash
.venv/bin/python scripts/run_paper_trader.py --help
.venv/bin/python scripts/paper_diagnostics.py --help
```

---

## Команды для установки нового service на сервере

После реализации подготовить команды, но выполнять аккуратно.

Пример:

```bash
cd /opt/hammertrade

sudo cp deploy/systemd/hammertrade-paper-maxhold5.example.service /etc/systemd/system/hammertrade-paper-maxhold5.service
sudo systemctl daemon-reload
sudo systemctl enable hammertrade-paper-maxhold5
sudo systemctl start hammertrade-paper-maxhold5
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
```

Если unit требует правки путей — сделать корректный unit под `/opt/hammertrade`.

Проверить baseline:

```bash
sudo systemctl status hammertrade-paper --no-pager
```

---

## Post-start checks

После запуска maxhold5:

```bash
cd /opt/hammertrade

ls -lah data/paper | grep maxhold
ls -lah runtime | grep maxhold
ls -lah out/paper | grep maxhold

cat runtime/paper_status_SiM6_SELL_maxhold5.json

journalctl -u hammertrade-paper-maxhold5 -n 80 --no-pager
journalctl -u hammertrade-paper -n 40 --no-pager
```

Запустить diagnostics для maxhold5:

```bash
.venv/bin/python scripts/paper_diagnostics.py \
  --state-db data/paper/paper_state_maxhold5.sqlite \
  --csv-fallback out/paper/paper_trades_SiM6_SELL_maxhold5.csv \
  --ticker SiM6 \
  --direction SELL \
  --experiment-name maxhold5
```

Запустить compare, если реализован:

```bash
.venv/bin/python scripts/compare_paper_experiments.py \
  --baseline-db data/paper/paper_state.sqlite \
  --experiment-db data/paper/paper_state_maxhold5.sqlite \
  --baseline-name baseline \
  --experiment-name maxhold5 \
  --output reports/paper_ab_compare_baseline_vs_maxhold5_latest.md
```

В первые часы/дни сделок может не быть — это нормально.

---

## Acceptance Criteria

MVP-2.1 считается готовым, если:

1. `max_hold_bars` добавлен как optional параметр.
2. Default `max_hold_bars=None` сохраняет старое поведение.
3. Baseline service `hammertrade-paper.service` не изменён по поведению и работает.
4. Создан отдельный maxhold5 service config/unit.
5. Запущен или подготовлен к запуску `hammertrade-paper-maxhold5.service`.
6. maxhold5 использует отдельную SQLite DB.
7. maxhold5 использует отдельный status file.
8. maxhold5 использует отдельный CSV/report namespace.
9. STOP/TAKE имеют приоритет над MAX_HOLD_EXIT.
10. `bars_held` считается по торговым свечам.
11. `paper_diagnostics.py` работает для maxhold5 DB.
12. Желательно: есть `compare_paper_experiments.py`.
13. Есть тесты или smoke checks.
14. Текущий baseline paper data не повреждён.
15. Systemd baseline не изменён.
16. В финальном ответе Claude Code указал:
    - созданные файлы;
    - изменённые файлы;
    - команды запуска;
    - статус baseline service;
    - статус maxhold5 service;
    - где лежит maxhold5 DB;
    - где status file;
    - как собирать diagnostics;
    - как сравнивать A/B;
    - что делать дальше.

---

## Что НЕ делать в MVP-2.1

Не включать real trading.

Не включать sandbox orders.

Не менять production baseline.

Не удалять baseline DB.

Не объединять baseline и maxhold5 в одну БД, если это усложняет сравнение.

Не делать `max_hold_bars=5` дефолтом.

Не делать автоматический выбор “лучшего” режима.

Не отключать baseline.

Не делать вывод “стратегия доказана”.

---

## Важная интерпретация результата

Правильная формулировка:

```text
max_hold_bars=5 запущен как параллельный paper experiment. Нужно собрать 2–4 недели данных и сравнить с baseline.
```

Неправильная формулировка:

```text
max_hold_bars=5 улучшает стратегию, можно переходить к live trading.
```

---

## Следующий процесс после MVP-2.1

После запуска двух сервисов:

```text
1. Дать им поработать минимум 1 неделю.
2. Лучше 2–4 недели.
3. Раз в несколько дней запускать:
   - diagnostics baseline;
   - diagnostics maxhold5;
   - A/B compare.
4. Смотреть:
   - net PnL;
   - PF;
   - max drawdown;
   - expectancy;
   - worst trade;
   - STOP/TAKE/MAX_HOLD_EXIT distribution;
   - days profitable;
   - open trades.
5. Если maxhold5 устойчиво лучше baseline на новых данных — оставить как основной paper candidate.
6. Если хуже — отключить maxhold5 service, baseline остаётся нетронутым.
```

---

## Финальный формат ответа Claude Code

После выполнения задачи ответить так:

```markdown
## MVP-2.1 Parallel Paper max_hold5 Experiment — готово

### Что сделано

### Созданные файлы

### Изменённые файлы

### Как запустить maxhold5 service

### Статус baseline service

### Статус maxhold5 service

### Где лежат данные maxhold5

### Как собрать diagnostics

### Как сравнить baseline vs maxhold5

### Exit priority

### Tests / smoke checks

### Что НЕ было изменено

### Warnings / limitations

### Что делать дальше
```
