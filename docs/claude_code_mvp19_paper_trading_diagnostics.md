# Claude Code Prompt — MVP-1.9: Paper Trading Diagnostics

## Контекст проекта

Ты работаешь в проекте `HammerTrade`.

Это исследовательский trading/paper-trading бот для MOEX futures / MOEXF.

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

Проект уже развёрнут на сервере Yandex Cloud:

```text
Server: 158.160.204.201
Project path: /opt/hammertrade
Virtualenv: /opt/hammertrade/.venv
Systemd service: hammertrade-paper.service
User: vorontsov
CA bundle: /opt/hammertrade/certs/tbank-combined-ca.pem
```

Старый сервер `103.76.52.4` остановлен.

Текущий daemon уже работает через systemd:

```bash
cd /opt/hammertrade

sudo systemctl status hammertrade-paper
journalctl -u hammertrade-paper -n 100 --no-pager
```

Из предыдущих MVP уже сделано:

## MVP-1.7

Paper trading daemon for SiM6 SELL.

Ключевые файлы/сущности, которые должны уже существовать или быть близкими к этому:

```text
src/paper/models.py
src/paper/repository.py
src/paper/engine.py
src/paper/report.py
scripts/run_paper_trader.py
scripts/paper_report.py
deploy/systemd/hammertrade-paper.example.service
```

Основное состояние paper trading:

```text
data/paper/paper_state.sqlite
```

Основные таблицы:

```text
paper_state
paper_trades
paper_events
```

Ожидаемая структура `paper_trades` из MVP-1.7:

```sql
CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    class_code TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    profile TEXT NOT NULL,
    direction TEXT NOT NULL,
    signal_timestamp TEXT NOT NULL,
    entry_timestamp TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    take_price REAL NOT NULL,
    status TEXT NOT NULL,
    exit_timestamp TEXT,
    exit_price REAL,
    exit_reason TEXT,
    pnl_points REAL,
    pnl_rub REAL,
    bars_held INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

CSV export из MVP-1.7:

```text
out/paper/paper_trades_SiM6_SELL.csv
```

Daily paper report из MVP-1.7:

```bash
python scripts/paper_report.py \
  --state-db data/paper/paper_state.sqlite \
  --output reports/paper_report_SiM6_SELL.md
```

## MVP-1.8

Operational Safety Layer v1 для paper trader.

Там были добавлены/ожидались:

```text
configs/market_hours/moex_futures.yaml
src/market/market_hours.py
scripts/check_paper_status.py
runtime/paper_status_SiM6_SELL.json
docs/paper_trader_operational.md
```

И новые параметры paper trader:

```text
--market-hours-config configs/market_hours/moex_futures.yaml
--ignore-market-hours
--api-timeout-sec 10
--status-file runtime/paper_status_SiM6_SELL.json
```

Важно: MVP-1.8 уже занят operational safety layer. Поэтому текущая задача называется MVP-1.9.

---

## Текущий live/paper результат

Paper trader был запущен непрерывно около 3.5 дней.

Период:

```text
04.05.2026 – 07.05.2026
```

Текущий результат:

```text
Total trades: 11
TAKE: 7
STOP: 4
Winrate: 63.6%
Gross profit: +1649.65 RUB
Gross loss: -1140.20 RUB
Net PnL: +509.45 RUB
Profit factor: 1.45
API errors / crashes: 0
```

Все сделки:

```text
04.05 09:39 SELL entry=76503 stop=76560 take=76448 exit=76561 STOP pnl=-580.05 bars=6
05.05 10:17 SELL entry=76517 stop=76537 take=76499 exit=76538 STOP pnl=-210.05 bars=2
05.05 15:14 SELL entry=76692 stop=76700 take=76686 exit=76687 TAKE pnl=+49.95 bars=1
05.05 17:37 SELL entry=76732 stop=76744 take=76722 exit=76723 TAKE pnl=+89.95 bars=9
05.05 18:30 SELL entry=76742 stop=76747 take=76739 exit=76748 STOP pnl=-60.05 bars=1
06.05 07:33 SELL entry=76699 stop=76746 take=76654 exit=76655 TAKE pnl=+439.95 bars=4
06.05 12:59 SELL entry=75477 stop=75491 take=75465 exit=75466 TAKE pnl=+109.95 bars=1
06.05 15:59 SELL entry=75372 stop=75395 take=75351 exit=75352 TAKE pnl=+199.95 bars=1
06.05 16:54 SELL entry=75229 stop=75238 take=75222 exit=75223 TAKE pnl=+59.95 bars=1
07.05 07:31 SELL entry=75502 stop=75575 take=75431 exit=75432 TAKE pnl=+699.95 bars=1
07.05 09:02 SELL entry=75416 stop=75444 take=75390 exit=75445 STOP pnl=-290.05 bars=1
```

Вывод по этим данным:

- технически daemon стабилен;
- стратегия пока в плюсе, но выборка маленькая;
- нельзя считать стратегию доказанно прибыльной;
- сейчас не нужно менять стратегию;
- нужно добавить диагностический слой по уже накопленным paper trades.

---

## Главная цель MVP-1.9

Добавить полноценную диагностику paper trading сделок.

Цель: получить отчёт, который помогает понять:

1. какие сделки дают прибыль;
2. какие сделки выглядят мусорными;
3. какие risk/reward/RR зоны опасны;
4. какие флаги стоит потом проверить в backtest/grid;
5. какие фильтры можно рассмотреть в следующем MVP.

Важно: это аналитический read-only MVP.

Текущую торговую логику менять нельзя.

---

## Жёсткие ограничения

Строго запрещено:

- real trading;
- sandbox orders;
- broker execution;
- postOrder;
- postSandboxOrder;
- изменение правил входа;
- изменение правил выхода;
- изменение расчёта stop/take;
- изменение HammerDetector;
- изменение backtest engine;
- изменение grid/walk-forward;
- изменение работающего systemd unit на сервере;
- остановка `hammertrade-paper.service` без явной необходимости;
- schema migration для `paper_trades`, если можно обойтись чтением;
- удаление текущих SQLite/CSV данных;
- перезапись текущего `out/paper/paper_trades_SiM6_SELL.csv`;
- печать токенов;
- коммит `.env`.

Разрешено:

- добавить новые аналитические модули;
- добавить новый CLI-скрипт;
- читать SQLite в read-only режиме;
- читать CSV как fallback;
- создавать новые CSV/Markdown отчёты;
- добавить tests/smoke checks;
- обновить README/docs;
- добавить Makefile target, если Makefile уже есть.

---

## Что нужно изучить перед реализацией

Перед кодингом обязательно проверить текущую кодовую базу:

1. Как сейчас устроен `src/paper/repository.py`.
2. Как устроен `scripts/paper_report.py`.
3. Что уже есть в `src/paper/report.py`.
4. Реальная схема таблицы `paper_trades` в `data/paper/paper_state.sqlite`.
5. Реальный формат `out/paper/paper_trades_SiM6_SELL.csv`.
6. Есть ли уже функции расчёта:
   - profit factor;
   - winrate;
   - drawdown;
   - bucket summary;
   - Markdown table rendering.
7. Есть ли уже timezone helpers.
8. Есть ли уже market timezone / MSK handling.
9. Есть ли уже tests для paper report.

Не плодить дублирующую архитектуру, если можно аккуратно расширить существующую.

---

## Основной источник данных

Основной источник:

```text
data/paper/paper_state.sqlite
```

Таблица:

```text
paper_trades
```

CSV fallback:

```text
out/paper/paper_trades_SiM6_SELL.csv
```

Новая диагностика должна по умолчанию читать SQLite.

Если SQLite отсутствует или таблица `paper_trades` отсутствует, можно попробовать CSV fallback.

Если нет ни SQLite, ни CSV — скрипт должен завершиться понятным сообщением, а не stack trace.

---

## Новые файлы

Желательная структура:

```text
src/paper/diagnostics.py
scripts/paper_diagnostics.py
tests/test_paper_diagnostics.py
```

Если по текущей архитектуре проекта правильнее расширить `src/paper/report.py`, можно так сделать, но лучше не превращать существующий short report в огромный модуль.

---

## CLI

Добавить скрипт:

```text
scripts/paper_diagnostics.py
```

Базовый запуск:

```bash
python scripts/paper_diagnostics.py
```

Он должен работать с дефолтами:

```text
--state-db data/paper/paper_state.sqlite
--csv-fallback out/paper/paper_trades_SiM6_SELL.csv
--ticker SiM6
--direction SELL
--reports-dir reports
--out-dir out/paper
```

Желательные аргументы:

```bash
python scripts/paper_diagnostics.py \
  --state-db data/paper/paper_state.sqlite \
  --ticker SiM6 \
  --direction SELL \
  --from 2026-05-04 \
  --to 2026-05-07 \
  --reports-dir reports \
  --out-dir out/paper
```

Также нужен `--help`.

CLI должен печатать:

```text
HammerTrade Paper Diagnostics
Source       : SQLite data/paper/paper_state.sqlite
Ticker       : SiM6
Direction    : SELL
Loaded trades: 11
Closed trades: 11
Open trades  : 0
Enriched CSV : out/paper/paper_trades_diagnostics_SiM6_SELL_YYYYMMDD_HHMMSS.csv
Report       : reports/paper_diagnostics_SiM6_SELL_YYYYMMDD_HHMMSS.md
Warnings     : N
```

Если используется CSV fallback:

```text
Source       : CSV fallback out/paper/paper_trades_SiM6_SELL.csv
```

---

## Output files

Создавать новые файлы, не перезаписывать текущий export.

CSV:

```text
out/paper/paper_trades_diagnostics_SiM6_SELL_YYYYMMDD_HHMMSS.csv
```

Markdown:

```text
reports/paper_diagnostics_SiM6_SELL_YYYYMMDD_HHMMSS.md
```

Дополнительно можно обновлять latest-копии, если в проекте уже есть такой паттерн:

```text
out/paper/paper_trades_diagnostics_SiM6_SELL_latest.csv
reports/paper_diagnostics_SiM6_SELL_latest.md
```

Но только если это не конфликтует с существующим архивированием.

---

## Данные для enriched CSV

Для каждой сделки нужно сформировать enriched row.

### Базовые поля

```text
trade_id
ticker
class_code
timeframe
profile
direction
status
signal_timestamp_utc
signal_timestamp_msk
entry_timestamp_utc
entry_timestamp_msk
entry_date_msk
entry_hour_msk
day_of_week_msk
entry_price
stop_price
take_price
exit_timestamp_utc
exit_timestamp_msk
exit_price
exit_reason
pnl_points
pnl_rub
bars_held
created_at
updated_at
```

Если каких-то timestamp-полей нет или они naive:
- не падать;
- попытаться аккуратно распарсить;
- если timezone определить нельзя — оставить MSK-поле пустым;
- добавить warning.

### Risk / Reward для SELL

Для SELL:

```text
risk_points = stop_price - entry_price
reward_points = entry_price - take_price
actual_points = entry_price - exit_price
```

### Risk / Reward для BUY

Для BUY на будущее:

```text
risk_points = entry_price - stop_price
reward_points = take_price - entry_price
actual_points = exit_price - entry_price
```

### Direction fallback

Если `direction` отсутствует или неизвестен:
- попытаться определить направление по расположению stop/take:
  - если `stop > entry` и `take < entry` → SELL;
  - если `stop < entry` и `take > entry` → BUY;
- если не получается — оставить расчёты пустыми;
- добавить флаг `UNKNOWN_DIRECTION`.

### R/R

```text
rr = reward_points / risk_points
```

Если `risk_points <= 0`, не считать `rr`, добавить `INVALID_RISK`.

### PnL classification

```text
pnl_sign = WIN / LOSS / FLAT / UNKNOWN
abs_pnl_rub
```

Правила:

```text
WIN     если pnl_rub > 0
LOSS    если pnl_rub < 0
FLAT    если pnl_rub == 0
UNKNOWN если pnl_rub отсутствует
```

### Buckets

#### risk_bucket

```text
risk_points <= 10       -> RISK_000_010
risk_points <= 25       -> RISK_011_025
risk_points <= 50       -> RISK_026_050
risk_points > 50        -> RISK_051_PLUS
unknown/invalid         -> RISK_UNKNOWN
```

#### reward_bucket

```text
reward_points < 5       -> REWARD_LT_005
reward_points <= 10     -> REWARD_005_010
reward_points <= 25     -> REWARD_011_025
reward_points <= 50     -> REWARD_026_050
reward_points > 50      -> REWARD_051_PLUS
unknown/invalid         -> REWARD_UNKNOWN
```

#### rr_bucket

```text
rr < 0.8                -> RR_LT_0_8
rr < 1.0                -> RR_0_8_1_0
rr < 1.2                -> RR_1_0_1_2
rr >= 1.2               -> RR_GT_1_2
unknown/invalid         -> RR_UNKNOWN
```

#### bars_bucket

```text
bars_held <= 1          -> BARS_001
bars_held <= 3          -> BARS_002_003
bars_held <= 10         -> BARS_004_010
bars_held > 10          -> BARS_011_PLUS
unknown                 -> BARS_UNKNOWN
```

---

## Diagnostic flags

Добавить поле:

```text
diagnostic_flags
```

Формат:

```text
LOW_RR;TINY_TAKE;ONE_BAR_STOP
```

Правила:

```text
LOW_RR             если rr < 0.8
TINY_TAKE          если reward_points < 5
BIG_RISK           если risk_points > 40
ONE_BAR_STOP       если exit_reason == STOP и bars_held <= 1
ONE_BAR_TAKE       если exit_reason == TAKE и bars_held <= 1
INVALID_RISK       если risk_points <= 0
INVALID_REWARD     если reward_points <= 0
UNKNOWN_DIRECTION  если direction не удалось определить
MISSING_FIELDS     если не хватает важных полей
OPEN_TRADE         если status == OPEN
NO_EXIT_DATA       если status == CLOSED, но нет exit_price или exit_timestamp
```

Если уже реализована проверка market hours / clearing windows и её можно переиспользовать без дублирования — добавить флаг:

```text
NEAR_CLEARING
```

Но если для этого нужно тащить сложную новую логику — не делать в MVP-1.9.

---

## Markdown report

Markdown-отчёт должен быть на русском языке.

Файл:

```text
reports/paper_diagnostics_SiM6_SELL_YYYYMMDD_HHMMSS.md
```

Структура:

```markdown
# Paper Trading Diagnostics — SiM6 SELL

## Период

## Источник данных

## Общая статистика

## Статистика по дням

## Статистика по часам входа

## Статистика по exit_reason

## Risk buckets

## Reward buckets

## R/R buckets

## Bars held buckets

## Diagnostic flags

## Подозрительные сделки

## Лучшие сделки

## Худшие сделки

## Открытые сделки

## Предварительные гипотезы фильтров

## Warnings
```

---

## Общая статистика

Считать только закрытые сделки для PnL-метрик.

Отдельно показывать:

```text
total_trades
closed_trades
open_trades
wins
losses
flats
winrate_pct
gross_profit_rub
gross_loss_rub
net_pnl_rub
profit_factor
avg_pnl_rub
median_pnl_rub
best_trade_rub
worst_trade_rub
avg_win_rub
avg_loss_rub
expectancy_rub
avg_risk_points
avg_reward_points
avg_rr
avg_bars_held
```

Формулы:

```text
gross_profit_rub = сумма pnl_rub по прибыльным закрытым сделкам
gross_loss_rub = модуль суммы pnl_rub по убыточным закрытым сделкам
net_pnl_rub = сумма pnl_rub по всем закрытым сделкам
profit_factor = gross_profit_rub / gross_loss_rub
expectancy_rub = net_pnl_rub / closed_trades
```

Если `gross_loss_rub == 0`, profit factor вывести как `N/A` или `inf`.

---

## Группировки

Для каждой группировки выводить таблицу:

```text
group
trades
wins
losses
flats
winrate_pct
gross_profit_rub
gross_loss_rub
net_pnl_rub
profit_factor
avg_pnl_rub
```

Группировки:

```text
entry_date_msk
entry_hour_msk
exit_reason
risk_bucket
reward_bucket
rr_bucket
bars_bucket
diagnostic_flags
```

Для `diagnostic_flags` одна сделка может попадать в несколько групп.

---

## Подозрительные сделки

Вывести сделки, где `diagnostic_flags` не пустой.

Колонки:

```text
entry_timestamp_msk
direction
entry_price
stop_price
take_price
exit_price
exit_reason
pnl_rub
risk_points
reward_points
rr
bars_held
diagnostic_flags
```

Если сделок много — показать первые 50 худших по `pnl_rub`, а в тексте указать общее количество.

---

## Лучшие и худшие сделки

Показать:

```text
Top 5 best closed trades by pnl_rub
Top 5 worst closed trades by pnl_rub
```

Колонки:

```text
entry_timestamp_msk
exit_reason
pnl_rub
risk_points
reward_points
rr
bars_held
diagnostic_flags
```

---

## Открытые сделки

Если есть `status == OPEN`, вывести отдельную таблицу:

```text
trade_id
entry_timestamp_msk
direction
entry_price
stop_price
take_price
bars_held
diagnostic_flags
```

Если открытых сделок нет:

```text
Открытых сделок нет.
```

---

## Предварительные гипотезы фильтров

Это очень важный блок.

Нужно автоматически формировать осторожные гипотезы, не правила.

Пример:

```text
Выборка мала, выводы предварительные. Использовать эти гипотезы только для последующего backtest/grid-теста, не как готовое правило live-торговли.
```

Далее:

### TINY_TAKE

Если сделки с `TINY_TAKE` имеют отрицательный net PnL:

```text
Гипотеза: проверить фильтр MIN_REWARD_POINTS, так как сделки с reward_points < 5 показали отрицательный net PnL.
```

### BIG_RISK

Если сделки с `BIG_RISK` имеют отрицательный net PnL или дают worst trade:

```text
Гипотеза: проверить ограничение MAX_RISK_POINTS или отдельный режим обработки больших стопов.
```

Важно: не предлагать сразу `MAX_RISK_POINTS=40` как готовое правило, потому что в текущем live/paper срезе большая прибыльная сделка 07.05 07:31 имела risk около 73 points и дала +699.95 RUB. Поэтому формулировка должна быть осторожной.

### LOW_RR

Если сделки с `LOW_RR` имеют отрицательный net PnL:

```text
Гипотеза: проверить минимальный R/R перед входом.
```

### ONE_BAR_STOP

Если есть `ONE_BAR_STOP`:

```text
Гипотеза: проверить дополнительное подтверждение входа, так как часть стопов происходит уже на первом баре.
```

### Profit concentration

Если top 1 или top 2 сделки дают большую часть net PnL, добавить:

```text
Гипотеза: проверить концентрацию прибыли — результат может сильно зависеть от нескольких импульсных сделок.
```

Правило для MVP-1.9:

```text
Если сумма top 2 pnl_rub > 70% от gross_profit_rub или net_pnl_rub, добавить предупреждение о concentration risk.
```

---

## Warnings

Блок `Warnings` должен включать:

- отсутствующие поля;
- невалидный risk;
- невалидный reward;
- неизвестное направление;
- нераспарсенные timestamps;
- naive timestamps;
- невозможность рассчитать MSK-время;
- отсутствие SQLite и использование CSV fallback;
- пустой набор сделок;
- открытые сделки без exit data;
- любые пропущенные расчёты.

---

## Tests / smoke checks

Если в проекте уже используется pytest — добавить тесты:

```text
tests/test_paper_diagnostics.py
```

Минимальные проверки:

1. SELL risk/reward:

```text
entry=100
stop=110
take=90
exit=90
direction=SELL

risk_points=10
reward_points=10
actual_points=10
rr=1.0
```

2. BUY risk/reward:

```text
entry=100
stop=90
take=110
exit=110
direction=BUY

risk_points=10
reward_points=10
actual_points=10
rr=1.0
```

3. `LOW_RR` ставится при `rr < 0.8`.
4. `TINY_TAKE` ставится при `reward_points < 5`.
5. `BIG_RISK` ставится при `risk_points > 40`.
6. `ONE_BAR_STOP` ставится при `exit_reason=STOP` и `bars_held <= 1`.
7. Отчёт не падает на пустом наборе сделок.
8. Отчёт не падает при отсутствующих необязательных полях.
9. SQLite reader корректно читает временную тестовую БД с таблицей `paper_trades`.
10. CSV fallback работает на временном CSV.

---

## Makefile

Если в проекте уже есть Makefile, добавить цель:

```makefile
paper-diagnostics:
	python scripts/paper_diagnostics.py
```

Если Makefile нет — не создавать только ради этой цели.

---

## Документация

Обновить README или отдельный документ, если уже есть docs по paper trader.

Предпочтительно:

```text
docs/paper_trader_diagnostics.md
```

Содержание:

```markdown
# Paper trader diagnostics

## Назначение

## Источник данных

## Как запустить

## Где лежат отчёты

## Как читать diagnostic_flags

## Важное ограничение

Диагностика не меняет стратегию и не доказывает прибыльность. Она помогает выбрать гипотезы для последующего backtest/grid.
```

---

## Команды проверки на сервере

После реализации дать пользователю команды:

```bash
cd /opt/hammertrade
source .venv/bin/activate

python scripts/paper_diagnostics.py

ls -lah reports | grep paper_diagnostics | tail
ls -lah out/paper | grep paper_trades_diagnostics | tail
```

Если есть Makefile:

```bash
make paper-diagnostics
```

Проверить, что сервис продолжает работать:

```bash
sudo systemctl status hammertrade-paper --no-pager
python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json
```

Если `check_paper_status.py` ещё не существует в конкретной ветке — не ломать задачу, просто указать это в отчёте.

---

## Acceptance Criteria

MVP-1.9 считается готовым, если:

1. Появился CLI:

```text
scripts/paper_diagnostics.py
```

2. Базовая команда работает:

```bash
python scripts/paper_diagnostics.py
```

3. Скрипт по умолчанию читает:

```text
data/paper/paper_state.sqlite
```

4. Если SQLite недоступен, есть понятный fallback или понятная ошибка.
5. Генерируется enriched CSV:

```text
out/paper/paper_trades_diagnostics_SiM6_SELL_YYYYMMDD_HHMMSS.csv
```

6. Генерируется Markdown report:

```text
reports/paper_diagnostics_SiM6_SELL_YYYYMMDD_HHMMSS.md
```

7. В enriched CSV есть поля:

```text
risk_points
reward_points
actual_points
rr
pnl_sign
abs_pnl_rub
risk_bucket
reward_bucket
rr_bucket
bars_bucket
diagnostic_flags
```

8. Markdown report содержит:

```text
Период
Источник данных
Общая статистика
Статистика по дням
Статистика по часам входа
Статистика по exit_reason
Risk buckets
Reward buckets
R/R buckets
Bars held buckets
Diagnostic flags
Подозрительные сделки
Лучшие сделки
Худшие сделки
Открытые сделки
Предварительные гипотезы фильтров
Warnings
```

9. Скрипт не падает на:
   - пустом наборе сделок;
   - открытой сделке;
   - отсутствующих необязательных полях;
   - неизвестном направлении;
   - невалидном risk/reward.
10. Текущий paper trader не изменён по торговой логике.
11. Systemd unit не изменён без необходимости.
12. Тесты или smoke checks выполнены.
13. Claude Code в финальном ответе перечисляет:
   - созданные файлы;
   - изменённые файлы;
   - как запускать;
   - где смотреть отчёты;
   - результат тестов;
   - важные ограничения.

---

## Что НЕ делать в этом MVP

Не реализовывать фильтры:

```text
MIN_REWARD_POINTS
MAX_RISK_POINTS
MIN_RR
```

Не подключать эти фильтры к paper trader.

Не менять стратегию.

Не менять detector.

Не менять backtest.

Не менять walk-forward.

Не менять grid search.

Не добавлять Telegram-уведомления.

Не добавлять live/sandbox execution.

Не менять systemd unit на сервере.

Это MVP только для диагностики.

---

## Финальный формат ответа Claude Code

После выполнения задачи ответить так:

```markdown
## MVP-1.9 Paper Trading Diagnostics — готово

### Что сделано

### Созданные файлы

### Изменённые файлы

### Как запустить

### Где смотреть результаты

### Пример вывода CLI

### Пример структуры отчёта

### Тесты / smoke checks

### Важные замечания

### Что предлагаю сделать в MVP-2.0
```
