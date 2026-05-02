# MVP-1.7: Paper trading daemon for SiM6 SELL

## Контекст

Проект HammerTrade уже:

- лежит в GitHub;
- развёрнут на сервере Yandex Cloud;
- находится на сервере в `/opt/hammertrade`;
- работает в virtualenv `/opt/hammertrade/.venv`;
- имеет isolated CA bundle для T-Bank API:
  - `/opt/hammertrade/certs/tbank-combined-ca.pem`;
- не устанавливает Russian Trusted Root CA глобально;
- не отключает TLS verification;
- не использует `verify=False` / `curl -k`.

Текущая проверка connectivity на сервере:

```text
DNS : PASS  invest-public-api.tbank.ru -> 178.130.128.33
TLS : PASS
SDK : SKIP  tinkoff-investments not installed, skipping SDK check.
Result: PASS
```

Важно: перед реализацией paper daemon нужно разобраться с SDK-зависимостью. Если для T-Bank API используется пакет `tinkoff-investments`, он должен быть явно указан в `requirements.txt`, а connectivity checker должен корректно проверять SDK.

---

## Главная цель MVP-1.7

Сделать **paper trading daemon** для стратегии:

```text
Instrument: SiM6
Class code: SPBFUT
Timeframe: 1m
Profile: balanced
Direction filter: SELL
Mode: paper only
Orders: disabled
```

Daemon должен:

1. регулярно получать свежие свечи через T-Bank API;
2. использовать только закрытые свечи;
3. прогонять HammerDetector;
4. открывать виртуальные paper-сделки по сигналу SELL;
5. сопровождать виртуальную сделку до stop/take/timeout;
6. писать сделки и состояние в SQLite;
7. быть устойчивым к рестартам;
8. быть готовым к запуску через systemd;
9. не делать никаких реальных или sandbox-заявок.

---

## Жёсткие ограничения

Строго запрещено:

- live trading;
- реальные заявки;
- sandbox orders;
- broker execution;
- postOrder;
- postSandboxOrder;
- отключать TLS verification;
- использовать verify=False;
- использовать curl -k;
- печатать токены;
- коммитить `.env`;
- хранить live/full-access token;
- использовать full-access token.

Разрешено:

- READONLY_TOKEN для market data;
- SANDBOX_TOKEN пока не использовать;
- isolated CA bundle через env:
  - `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH`;
  - `SSL_CERT_FILE`;
  - `REQUESTS_CA_BUNDLE`;
- SQLite;
- CSV/Markdown reports;
- logs.

---

# Часть 0. Исправить SDK dependency / connectivity

Перед paper daemon обязательно закрыть проблему:

```text
SDK : SKIP  tinkoff-investments not installed
```

## Что сделать

1. Проверить, какой пакет фактически нужен проекту для T-Bank API.
2. Если используется T-Invest Python SDK — добавить в `requirements.txt`:

```text
tinkoff-investments
```

или конкретную совместимую версию, если проект уже использует pinning.

3. Обновить `scripts/check_tbank_connectivity.py`, чтобы он:
   - корректно импортировал SDK;
   - делал безопасный readonly smoke test;
   - не печатал токен.

4. После установки зависимостей на сервере команда должна давать:

```text
DNS : PASS
TLS : PASS
SDK : PASS
Result: PASS
```

## Безопасный SDK smoke test

Можно проверить один из вариантов:

- найти инструмент `SiM6`;
- получить futures specs для `SiM6`;
- выполнить readonly-запрос instruments.

Не делать orders.

---

# Часть 1. Paper trading domain models

Создать модуль:

```text
src/paper/models.py
```

Добавить dataclass / enum:

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class PaperTradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"

class PaperExitReason(str, Enum):
    STOP = "STOP"
    TAKE = "TAKE"
    TIMEOUT = "TIMEOUT"
    MANUAL = "MANUAL"
    END_OF_DATA = "END_OF_DATA"

@dataclass
class PaperTrade:
    trade_id: str
    ticker: str
    class_code: str
    timeframe: str
    profile: str
    direction: str
    signal_timestamp: datetime
    entry_timestamp: datetime
    entry_price: float
    stop_price: float
    take_price: float
    status: PaperTradeStatus
    exit_timestamp: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[PaperExitReason] = None
    pnl_points: Optional[float] = None
    pnl_rub: Optional[float] = None
    bars_held: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

Можно адаптировать под существующие модели backtest, но не смешивать paper-trades с historical backtest trades.

---

# Часть 2. SQLite repository

Создать:

```text
src/paper/repository.py
```

SQLite DB:

```text
data/paper/paper_state.sqlite
```

Таблицы:

## `paper_state`

```sql
CREATE TABLE IF NOT EXISTS paper_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Ключи:

```text
last_processed_candle_ts:<ticker>:<timeframe>:<profile>:<direction>
```

## `paper_trades`

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

## `paper_events`

```sql
CREATE TABLE IF NOT EXISTS paper_events (
    event_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT
);
```

Repository должен уметь:

```python
init_db()
get_state(key)
set_state(key, value)
get_open_trade(ticker, timeframe, profile, direction)
insert_trade(trade)
update_trade(trade)
insert_event(...)
list_recent_trades(...)
```

---

# Часть 3. Paper execution engine

Создать:

```text
src/paper/engine.py
```

Цель: использовать уже существующую backtest/execution логику, но в online-style режиме.

## Вход

- последние свечи DataFrame;
- последняя закрытая свеча;
- текущая open paper trade, если есть;
- detector signal;
- params:
  - entry_mode;
  - take_r;
  - max_hold_bars;
  - stop_buffer_points;
  - slippage_ticks;
  - tick_size;
  - point_value_rub.

## Для первой версии

Рекомендуемые параметры:

```text
entry_mode = breakout
take_r = 1.0
max_hold_bars = 30
stop_buffer_points = 0
slippage_ticks = 1
contracts = 1
```

## SELL trade logic

Для SELL:

- signal candle имеет верхнюю иглу / upper wick;
- entry по breakout/trigger как в backtest;
- stop выше high сигнальной свечи + buffer;
- take по R;
- timeout через max_hold_bars.

Нужно использовать те же правила, что и в backtest v1, насколько возможно. Если есть готовая логика в backtest engine — переиспользовать или вынести общие функции, чтобы не разъехалась логика.

## Важно

Paper engine не должен открывать больше одной сделки одновременно по одному:

```text
ticker + timeframe + profile + direction
```

Если сделка уже открыта — новые сигналы игнорировать/логировать.

---

# Часть 4. Market data polling

Создать:

```text
src/paper/market_data.py
```

или использовать существующий T-Bank candles loader.

Нужно уметь получить свежие candles:

```python
fetch_recent_candles(
    ticker: str,
    class_code: str,
    timeframe: str,
    lookback_minutes: int,
    env: str,
) -> pandas.DataFrame
```

Для 1m можно брать последние 200–500 минут, чтобы detector имел контекст.

Важно:

- использовать только закрытые свечи;
- не обрабатывать текущую незакрытую минуту;
- timestamps хранить в UTC;
- для клиринга detector уже умеет timezone conversion;
- при API ошибке не падать навсегда, а логировать и retry на следующем цикле.

---

# Часть 5. Daemon script

Создать CLI:

```text
scripts/run_paper_trader.py
```

Пример запуска:

```bash
python scripts/run_paper_trader.py   --ticker SiM6   --class-code SPBFUT   --timeframe 1m   --profile balanced   --params configs/hammer_detector_balanced.env   --direction-filter SELL   --entry-mode breakout   --take-r 1.0   --max-hold-bars 30   --stop-buffer-points 0   --slippage-ticks 1   --contracts 1   --poll-interval-seconds 20   --lookback-candles 300   --state-db data/paper/paper_state.sqlite   --trades-output out/paper/paper_trades_SiM6_SELL.csv   --log-file logs/paper_SiM6_SELL.log   --env prod
```

## Флаги

Обязательные/дефолтные:

```text
--ticker default SiM6
--class-code default SPBFUT
--timeframe default 1m
--profile default balanced
--params default configs/hammer_detector_balanced.env
--direction-filter default SELL
--entry-mode default breakout
--take-r default 1.0
--max-hold-bars default 30
--stop-buffer-points default 0
--slippage-ticks default 1
--contracts default 1
--poll-interval-seconds default 20
--lookback-candles default 300
--state-db default data/paper/paper_state.sqlite
--trades-output default out/paper/paper_trades_SiM6_SELL.csv
--log-file default logs/paper_SiM6_SELL.log
--env default prod
--once
--dry-run
```

## `--once`

Один цикл:

1. получить свежие свечи;
2. обработать последнюю закрытую свечу;
3. обновить state/trades;
4. завершиться.

Это нужно для smoke-test и cron-like debugging.

## `--dry-run`

Не писать в SQLite, не создавать сделку. Только:

- получить candles;
- показать последнюю закрытую свечу;
- показать detector summary;
- показать, был бы сигнал или нет.

---

# Часть 6. Idempotency

Daemon должен хранить:

```text
last_processed_candle_ts
```

Если последняя закрытая свеча уже обработана:

```text
No new closed candle. Waiting...
```

и не создавать дублей.

Trade ID можно формировать так:

```text
paper:<ticker>:<timeframe>:<profile>:<direction>:<signal_timestamp>
```

Если такой trade_id уже есть — не создавать повторно.

---

# Часть 7. Logging

Использовать стандартный `logging`.

Писать:

```text
logs/paper_SiM6_SELL.log
```

В логах:

```text
startup params
connectivity info
last closed candle timestamp
new signal / no signal
open trade
exit trade
API errors
retry
shutdown
```

Не печатать токены.

---

# Часть 8. CSV export

Помимо SQLite, обновлять CSV:

```text
out/paper/paper_trades_SiM6_SELL.csv
```

Колонки:

```text
trade_id
ticker
class_code
timeframe
profile
direction
signal_timestamp
entry_timestamp
entry_price
stop_price
take_price
status
exit_timestamp
exit_price
exit_reason
pnl_points
pnl_rub
bars_held
created_at
updated_at
```

CSV можно перегенерировать из SQLite после каждого изменения или append/update простым способом.

---

# Часть 9. Daily summary report

Создать:

```text
src/paper/report.py
```

и CLI:

```text
scripts/paper_report.py
```

Пример:

```bash
python scripts/paper_report.py   --state-db data/paper/paper_state.sqlite   --output reports/paper_report_SiM6_SELL.md
```

Report:

```markdown
# Paper Trading Report

## Summary

| Metric | Value |
|---|---:|
| Trades total | ... |
| Open trades | ... |
| Closed trades | ... |
| Net PnL RUB | ... |
| Winrate | ... |
| Profit Factor | ... |

## Open Trades

...

## Recent Closed Trades

...
```

---

# Часть 10. systemd service

Обновить:

```text
deploy/systemd/hammertrade-paper.example.service
```

Актуализировать ExecStart:

```ini
ExecStart=/opt/hammertrade/.venv/bin/python scripts/run_paper_trader.py --ticker SiM6 --class-code SPBFUT --timeframe 1m --profile balanced --direction-filter SELL --env prod
```

Добавить инструкции в:

```text
docs/deploy_yandex_server.md
```

Пример установки:

```bash
sudo cp deploy/systemd/hammertrade-paper.example.service /etc/systemd/system/hammertrade-paper.service
sudo systemctl daemon-reload
sudo systemctl enable hammertrade-paper
sudo systemctl start hammertrade-paper
sudo systemctl status hammertrade-paper
journalctl -u hammertrade-paper -f
```

Важно: запускать systemd service только после успешного:

```bash
python scripts/check_tbank_connectivity.py --ca-bundle /opt/hammertrade/certs/tbank-combined-ca.pem
```

---

# Часть 11. Smoke tests на сервере

После реализации и deploy на сервер:

```bash
cd /opt/hammertrade
git pull
source .venv/bin/activate
pip install -r requirements.txt
set -a
source .env
set +a
python scripts/check_tbank_connectivity.py --ca-bundle /opt/hammertrade/certs/tbank-combined-ca.pem
python scripts/run_paper_trader.py --once --dry-run
python scripts/run_paper_trader.py --once
python scripts/paper_report.py --state-db data/paper/paper_state.sqlite --output reports/paper_report_SiM6_SELL.md
```

Если всё ок — можно запускать systemd.

---

# Часть 12. Tests

Добавить тесты без реального T-Bank API.

## tests/test_paper_repository.py

Проверить:

- init_db;
- set/get state;
- insert/open/close trade;
- no duplicate trade_id;
- events insert.

## tests/test_paper_engine.py

Synthetic candles:

- SELL signal opens paper trade;
- no duplicate trade if open trade exists;
- stop closes trade;
- take closes trade;
- timeout closes trade;
- pnl_rub считается через point_value_rub;
- slippage_ticks учитывается.

## tests/test_paper_daemon_cli.py

- `--help`;
- `--dry-run` не пишет state;
- `--once` вызывает один цикл;
- ошибки API mock не валят процесс.

## tests/test_paper_report.py

- report создаётся;
- summary метрики считаются;
- open/closed trades отображаются.

Не делать реальных T-Bank API вызовов в tests.

---

# Часть 13. README

Добавить раздел:

```markdown
## Paper trading
```

Описать:

- это не live trading;
- orders disabled;
- используется READONLY_TOKEN;
- состояние в SQLite;
- запуск once/dry-run;
- запуск systemd;
- где смотреть логи и отчёты.

---

# Definition of Done

Задача выполнена, если:

1. `requirements.txt` содержит нужный T-Bank SDK dependency.
2. `scripts/check_tbank_connectivity.py` после установки SDK может делать SDK smoke test.
3. Есть:
   - `src/paper/models.py`;
   - `src/paper/repository.py`;
   - `src/paper/engine.py`;
   - `src/paper/report.py`;
   - `scripts/run_paper_trader.py`;
   - `scripts/paper_report.py`.
4. Paper trader поддерживает:
   - `--once`;
   - `--dry-run`;
   - SQLite state;
   - CSV export;
   - logs;
   - SELL-only стартовую конфигурацию.
5. Paper trader не делает никаких orders.
6. systemd example обновлён.
7. docs deploy обновлены.
8. README обновлён.
9. Tests проходят:

```bash
pytest
```

10. На сервере smoke-test проходит:
   - connectivity;
   - `run_paper_trader.py --once --dry-run`;
   - `run_paper_trader.py --once`;
   - `paper_report.py`.

---

# Отчёт после выполнения

После реализации напиши:

```text
Что добавлено:
...

Как проверена SDK-зависимость:
...

Как запустить paper trader dry-run:
...

Как запустить один реальный paper-cycle:
...

Где хранится SQLite state:
...

Где лежит CSV trades:
...

Где лежат logs:
...

Как создать paper report:
...

Как запустить через systemd:
...

Что проверено локально:
...

Что проверено на сервере:
...

Что НЕ делалось:
...
```

В блоке "Что НЕ делалось" обязательно указать:

```text
- live trading не добавлялся;
- sandbox orders не добавлялись;
- broker execution не добавлялся;
- реальные заявки не выполнялись;
- TLS verification не отключалась;
- Russian Trusted Root CA не устанавливался глобально;
- токены не печатались и не коммитились.
```
