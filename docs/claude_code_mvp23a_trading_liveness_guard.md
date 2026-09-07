# Claude Code Prompt — MVP-2.3a: Trading Liveness / Consecutive Error Guard

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

Baseline status file: runtime/paper_status_SiM6_SELL.json
Maxhold5 status file: runtime/paper_status_SiM6_SELL_maxhold5.json
```

Сейчас работают два paper-сервиса:

```text
baseline: max_hold_bars=None
maxhold5: max_hold_bars=5
```

Важно: в этом MVP нельзя менять торговую стратегию, HammerDetector, stop/take/maxhold-логику, paper DB schema без необходимости или текущие параметры A/B эксперимента.

---

## Свежий инцидент

На 2026-05-27 был обнаружен critical operational incident.

Симптом:

```text
Оба paper-сервиса были active (running), но фактически не торговали примерно 2 дня.
Период простоя: примерно с 2026-05-25 до 2026-05-27.
Количество ошибок: около 790 API_ERROR подряд.
```

Причина:

```text
T-Bank API начал отдавать expiration_date='2026-06-19' для SiM6.
pandas читал соответствующую CSV-колонку как float64.
При записи строки с датой в float-колонку возникала ошибка.
```

Временный фикс уже сделан:

```text
pd.read_csv(..., dtype=object)
```

Файл:

```text
src/tbank/instruments.py
```

После фикса боты снова торгуют, в логах подтверждены:

```text
SIGNAL
ENTRY
CLOSE
```

Но проблема глубже:

```text
systemctl показывал active,
процессы были живые,
но фактически торговля была мёртвая.
```

Значит, текущий operational monitoring недостаточен.

---

## Текущий статус A/B после фикса

Накопленные результаты:

```text
baseline:
  closed trades: 75
  net PnL: +766 RUB
  Profit Factor: 1.098

maxhold5:
  closed trades: 46
  net PnL: +828 RUB
  Profit Factor: 1.262
```

Интерпретация:

```text
maxhold5 впервые вышел вперёд,
но для уверенного вывода нужно примерно 50–60 сделок у maxhold5.
Сейчас 46, осталось немного.
```

Важно:

```text
В данных есть operational gap около 2 дней.
Все будущие отчёты должны учитывать, что был период, когда services были active, но не торговали из-за повторяющихся API_ERROR.
```

---

## Зачем нужен MVP-2.3a

Нужно добавить защиту от ситуации:

```text
service active, но бот фактически не получает валидные свечи и не торгует.
```

Нужно, чтобы бот и диагностические скрипты явно показывали:

```text
- сервис живой, но торговля не живая;
- подряд идёт слишком много API_ERROR;
- последний успешный fetch был слишком давно;
- последний успешный cycle был слишком давно;
- во время открытого рынка бот не получает данные;
- текущий статус не OK, а DEGRADED / STALLED.
```

Это operational MVP, не trading MVP.

---

## Главная цель MVP-2.3a

Сделать Trading Liveness / Consecutive Error Guard.

Нужно:

1. Добавить liveness-поля в status JSON.
2. Добавить классификацию состояния торговли:
   - `OK`
   - `DEGRADED`
   - `STALLED`
3. Сделать так, чтобы `check_paper_status.py` не писал OK, если сервис active, но fetch давно неуспешен.
4. Сделать так, чтобы `paper_error_report.py` поднимал такие проблемы наверх.
5. Добавить guard по `consecutive_api_errors`.
6. Добавить guard по давности `last_successful_fetch_at`.
7. Добавить guard по давности `last_successful_cycle_at` во время открытого рынка.
8. Добавить тесты.
9. Не менять торговую стратегию.

---

## Жёсткие ограничения

Строго запрещено:

- менять HammerDetector;
- менять core candle pattern logic;
- менять entry rules;
- менять stop/take rules;
- менять `max_hold_bars=5`;
- менять текущие systemd units без необходимости;
- останавливать оба сервиса одновременно надолго;
- удалять DB/CSV/reports/logs;
- менять `.env`;
- печатать токены;
- запускать real trading;
- запускать sandbox orders;
- делать новые торговые фильтры;
- менять результаты backtest/paper;
- сбрасывать A/B experiment.

Разрешено:

- добавлять поля в status JSON backward-compatible;
- улучшать `check_paper_status.py`;
- улучшать `paper_error_report.py`;
- добавлять helper-модуль для liveness;
- добавлять logs;
- добавлять tests;
- добавлять docs;
- перезапустить сервисы по одному после изменений;
- читать systemd/journal/status files.

---

## Что изучить перед реализацией

Изучить:

```text
scripts/run_paper_trader.py
src/paper/status.py
scripts/check_paper_status.py
scripts/paper_error_report.py
src/market/market_hours.py
configs/market_hours/moex_futures.yaml
src/tbank/instruments.py
```

Найти текущие поля status JSON:

```bash
cat runtime/paper_status_SiM6_SELL.json
cat runtime/paper_status_SiM6_SELL_maxhold5.json
```

Понять:

```text
1. Какие поля уже есть:
   - last_fetch_status
   - last_fetch_at
   - last_successful_fetch_at
   - consecutive_api_errors
   - empty_response_count
   - consecutive_empty_responses
   - last_cycle_at
   - market_status
   - session
2. Где обновляется status file.
3. Где ловятся API_ERROR.
4. Где сбрасываются counters после успешного fetch.
5. Как определяется MARKET_CLOSED.
6. Как отличить open session от closed session.
7. Как сейчас check_paper_status.py определяет OK/WARNING/ERROR.
```

---

## Новые/уточнённые поля status JSON

Добавить или уточнить backward-compatible поля:

```json
{
  "trading_liveness_status": "OK",
  "trading_liveness_reason": null,
  "last_successful_fetch_at": "2026-05-27T...",
  "last_successful_cycle_at": "2026-05-27T...",
  "last_signal_check_at": "2026-05-27T...",
  "last_trade_event_at": "2026-05-27T...",
  "last_api_error_at": null,
  "last_api_error_message": null,
  "total_api_errors": 0,
  "consecutive_api_errors": 0,
  "minutes_since_last_successful_fetch": 0,
  "minutes_since_last_successful_cycle": 0,
  "is_market_open": true,
  "liveness_checked_at": "2026-05-27T..."
}
```

Если некоторые поля уже есть — не дублировать, а использовать/обновить.

Важно:

```text
- старые поля не удалять;
- status schema backward-compatible;
- baseline и maxhold5 должны иметь одинаковую структуру;
- check_paper_status.py должен работать со старыми status files без новых полей.
```

---

## Liveness rules

Ввести функцию/модуль, который определяет liveness.

Желательная структура:

```text
src/paper/liveness.py
```

Если лучше разместить в `src/paper/status.py`, можно, но отдельный модуль предпочтительнее.

Пример правил:

## OK

```text
market closed:
  service active + status file updated recently => OK / MARKET_CLOSED

market open:
  last_successful_fetch_at <= 10 minutes ago
  consecutive_api_errors < 5
  last_fetch_status in [OK, MARKET_CLOSED, EMPTY_CANDLES_RESPONSE, STALE_CANDLES? depending context]
```

## DEGRADED

```text
market open and:
  consecutive_api_errors >= 5
  or minutes_since_last_successful_fetch > 15
  or consecutive_empty_responses >= 3
```

## STALLED

```text
market open and:
  consecutive_api_errors >= 20
  or minutes_since_last_successful_fetch > 30
  or last_successful_cycle_at > 30 minutes ago
```

Thresholds should be configurable constants:

```text
DEGRADED_AFTER_CONSECUTIVE_ERRORS = 5
STALLED_AFTER_CONSECUTIVE_ERRORS = 20
DEGRADED_AFTER_FETCH_MINUTES = 15
STALLED_AFTER_FETCH_MINUTES = 30
```

Important:

```text
MARKET_CLOSED should not be STALLED just because no candles are fetched.
Weekend/holiday/night session should not trigger false alarms if market_hours says closed.
```

---

## API error handling

When generic API error happens:

```text
1. consecutive_api_errors += 1
2. total_api_errors += 1
3. last_api_error_at = now
4. last_api_error_message = normalized message
5. status is updated immediately
6. liveness is recalculated
```

When successful fetch happens:

```text
1. consecutive_api_errors = 0
2. last_successful_fetch_at = now
3. last_successful_cycle_at = now
4. last_fetch_status = OK
5. liveness = OK
```

When empty response happens:

```text
EMPTY_CANDLES_RESPONSE handling from MVP-2.1a remains intact.
consecutive_empty_responses is tracked separately.
```

---

## check_paper_status.py changes

`check_paper_status.py` must display:

```text
service/status file:
  last_fetch_status
  trading_liveness_status
  trading_liveness_reason
  consecutive_api_errors
  total_api_errors
  last_api_error_at
  last_successful_fetch_at
  minutes_since_last_successful_fetch
  empty_response_count
  consecutive_empty_responses
```

Exit code behavior:

```text
OK => exit 0
DEGRADED => exit 1
STALLED => exit 2
missing/broken status file => exit 2
```

If current scripts rely on exit codes differently, preserve compatibility where possible and document.

Console output should make it obvious:

```text
[OK] baseline trading_liveness=OK fetch=OK last_successful_fetch=...
[DEGRADED] maxhold5 consecutive_api_errors=7 last_successful_fetch=18m ago
[STALLED] baseline consecutive_api_errors=790 last_successful_fetch=2d ago
```

---

## paper_error_report.py changes

`paper_error_report.py` should put liveness summary at the top:

```text
Paper Error Report

baseline:
  trading_liveness_status: OK / DEGRADED / STALLED
  reason:
  consecutive_api_errors:
  total_api_errors:
  last_api_error_at:
  last_successful_fetch_at:
  minutes_since_last_successful_fetch:

maxhold5:
  ...
```

If any status is `STALLED`, report should clearly say:

```text
CRITICAL: service is active but trading liveness is STALLED
```

---

## Logging

On transition to DEGRADED/STALLED, log warning/error.

Example:

```text
[baseline] TRADING_LIVENESS_DEGRADED consecutive_api_errors=5 last_successful_fetch=16m ago reason="api errors threshold"
[baseline] TRADING_LIVENESS_STALLED consecutive_api_errors=20 last_successful_fetch=35m ago reason="fetch stalled during open market"
```

Avoid log spam:

```text
- log transition when status changes;
- then maybe repeat every N cycles;
- do not print full traceback for known repeated API errors every cycle unless debug mode.
```

---

## Incident annotation

Add a simple place in docs or report to note known incident:

```text
2026-05-25 — 2026-05-27:
  both paper services active but not trading;
  root cause: T-Bank instruments expiration_date dtype issue;
  fix: pd.read_csv(..., dtype=object) in src/tbank/instruments.py.
```

This can be in:

```text
docs/trading_liveness_guard.md
```

---

## Documentation

Create:

```text
docs/trading_liveness_guard.md
```

Content:

```markdown
# Trading Liveness Guard

## Problem

## Incident 2026-05-25 — 2026-05-27

## Status fields

## Liveness statuses

## Thresholds

## How check_paper_status.py interprets status

## How paper_error_report.py reports problems

## How to react to DEGRADED

## How to react to STALLED

## What this guard does NOT do
```

Important:

```text
This guard does not auto-restart services and does not place orders.
It only detects and reports stalled trading.
```

No auto-restart in this MVP.

---

## Tests

Add tests:

```text
tests/test_trading_liveness.py
```

Minimum tests:

1. Liveness OK when market open and last_successful_fetch is recent.
2. Liveness DEGRADED when consecutive_api_errors >= 5.
3. Liveness STALLED when consecutive_api_errors >= 20.
4. Liveness DEGRADED when last_successful_fetch older than threshold.
5. Liveness STALLED when last_successful_fetch older than stalled threshold.
6. Market closed does not trigger STALLED because of old fetch.
7. Successful fetch resets consecutive_api_errors.
8. API error increments consecutive and total counters.
9. Status JSON remains backward-compatible if new fields missing.
10. check_paper_status returns expected exit code for OK.
11. check_paper_status returns expected exit code for DEGRADED.
12. check_paper_status returns expected exit code for STALLED.
13. paper_error_report highlights STALLED.
14. Existing EMPTY_CANDLES_RESPONSE fields remain intact.

If direct CLI exit code testing is inconvenient, test underlying functions.

---

## Backward compatibility

Run:

```bash
.venv/bin/python -m pytest tests/test_trading_liveness.py
```

Also:

```bash
.venv/bin/python -m pytest \
  tests/test_trading_liveness.py \
  tests/test_empty_candles_handling.py \
  tests/test_paper_max_hold.py \
  tests/test_paper_engine.py
```

If feasible:

```bash
.venv/bin/python -m pytest
```

Current expected total was around 427 tests after previous MVPs. Do not break existing suite.

---

## Safe rollout

If daemon code changed, restart services one by one.

Recommended:

```bash
cd /opt/hammertrade

sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager

# restart maxhold5 first
sudo systemctl restart hammertrade-paper-maxhold5
sleep 10
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
.venv/bin/python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL_maxhold5.json

# then baseline
sudo systemctl restart hammertrade-paper
sleep 10
sudo systemctl status hammertrade-paper --no-pager
.venv/bin/python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json
```

Do not delete DB. Do not reset state.

---

## Post-rollout checks

Run:

```bash
cd /opt/hammertrade

.venv/bin/python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json
.venv/bin/python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL_maxhold5.json

.venv/bin/python scripts/paper_error_report.py

journalctl -u hammertrade-paper -n 80 --no-pager
journalctl -u hammertrade-paper-maxhold5 -n 80 --no-pager
```

Need to confirm:

```text
baseline:
  service active
  trading_liveness_status = OK
  max_hold_bars = None

maxhold5:
  service active
  trading_liveness_status = OK
  max_hold_bars = 5

Both:
  consecutive_api_errors not growing
  last_successful_fetch_at recent during market open
  check_paper_status clearly shows liveness
```

---

## Acceptance Criteria

MVP-2.3a is ready if:

1. Status JSON includes trading liveness fields.
2. Consecutive API errors are tracked.
3. Total API errors are tracked.
4. Last API error time/message are tracked.
5. Last successful fetch time is tracked.
6. Minutes since last successful fetch are reported.
7. Liveness status is calculated:
   - OK
   - DEGRADED
   - STALLED
8. Market closed does not falsely trigger STALLED.
9. During open market, stale successful fetch / many API errors triggers DEGRADED/STALLED.
10. `check_paper_status.py` displays liveness clearly.
11. `paper_error_report.py` highlights DEGRADED/STALLED.
12. Tests pass.
13. Docs added.
14. Baseline service still runs.
15. Maxhold5 service still runs.
16. Baseline remains `max_hold_bars=None`.
17. Maxhold5 remains `max_hold_bars=5`.
18. A/B experiment not reset.
19. Claude final response includes:
    - files changed;
    - fields added;
    - thresholds;
    - status of both services;
    - tests run;
    - what to do if STALLED appears.

---

## Что НЕ делать в MVP-2.3a

Do not auto-restart services.

Do not send Telegram notifications.

Do not add cron/systemd timers.

Do not change strategy.

Do not change maxhold5.

Do not start exclude_hour_12 experiment.

Do not start sandbox.

Do not start real trading.

Do not change HammerDetector.

Do not change DB schema unless absolutely necessary.

Do not delete state.

Do not hide API errors.

---

## Future improvements, NOT in this MVP

Potential future steps:

```text
MVP-2.3b: Telegram/Email alert on STALLED
MVP-2.4: Futures rollover SiM6 -> SiU6
MVP-2.5: Shared candle fetch/cache for baseline and experiments
MVP-3.0: Sandbox execution layer
```

But this MVP only detects and reports liveness problems.

---

## Финальный формат ответа Claude Code

```markdown
## MVP-2.3a Trading Liveness Guard — готово

### Что было причиной инцидента

### Что сделано

### Созданные файлы

### Изменённые файлы

### Новые status fields

### Liveness statuses and thresholds

### Поведение при API_ERROR

### Поведение при successful fetch

### check_paper_status.py

### paper_error_report.py

### Статус baseline service

### Статус maxhold5 service

### Что НЕ было изменено

### Tests / smoke checks

### Документация

### Warnings / limitations

### Что делать при DEGRADED/STALLED

### Рекомендация
```
