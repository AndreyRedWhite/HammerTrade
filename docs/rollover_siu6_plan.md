# SiM6 → SiU6 Rollover Plan

Составлен: 2026-05-27. Диагностика выполнена через T-Bank API (вечерняя сессия ~20:40 MSK).

---

## 1. Сравнение SiM6 vs SiU6

### Инструментальные параметры

| Параметр | SiM6 | SiU6 |
|---|---|---|
| Полное имя | Si-6.26 Курс Доллар – Рубль | Si-9.26 Курс Доллар – Рубль |
| UID | b4df2961-035a-4dcd-8372-9af0db10d2c9 | 574d37d8-9de4-423a-9e33-b936002d8bda |
| FIGI | FUTSI0626000 | FUTSI0926000 |
| class_code | SPBFUT | SPBFUT |
| lot | 1 | 1 |
| min_price_increment | **1.0** | **1.0** |
| expiration_date | **2026-06-19** | **2026-09-18** |
| first 1m candle date | 2024-06-25 | 2024-09-18 |

Параметры стратегии менять не нужно: `min_price_increment` и `lot` одинаковы.

### Ликвидность (2026-05-27, 2-дневные данные)

| Метрика | SiM6 | SiU6 | Отношение |
|---|---:|---:|---:|
| 1m свечей за 2 дня | 1778 | 1612 | — |
| Avg volume/bar (2d) | 1689.8 | 187.8 | **9:1** |
| Avg vol (последние 10 баров) | 97.3 | 34.0 | **2.9:1** |
| Spread (вечерняя сессия) | 5 pts | 7 pts | +40% |
| Top-5 глубина стакана (B+A) | 197 | 80 | −59% |
| Top-10 глубина стакана (B+A) | 691 | 103 | **−85%** |
| Последняя цена | 71 814 | 72 857 | — |

SiU6 стакан — тонкий, с провалами (72 849 → 72 843 → 72 822). Характерно для контракта за 4 недели до начала активного роллирования OI.

---

## 2. Текущий вывод: SiU6 технически готов, но пока недостаточно ликвиден

- ✅ SiU6 торгуется, 1m свечи доступны.
- ✅ Параметры стратегии идентичны — менять ничего не нужно.
- ✅ Код поддерживает произвольный тикер через `--ticker`.
- ⚠️ Объём в 9 раз ниже SiM6 — слипидж и риск проскальзывания неприемлемы.
- ⚠️ Стакан тонкий — стопы могут исполняться по худшим ценам.

**Торговля на SiU6 до достижения критериев ликвидности недопустима.**

---

## 3. Мониторинг с 2 июня

Начиная с **2026-06-02** запускать проверку ликвидности раз в день в основную сессию (желательно 12:00–14:00 MSK):

```bash
cd /opt/hammertrade
.venv/bin/python scripts/check_rollover_siu6.py
```

Смотреть на:
- `avg vol last 10` для SiU6 во время основной сессии — должно расти
- Spread SiU6 — должен приближаться к 5 pts (как у SiM6)
- Top-5 глубина SiU6 — должна приближаться к 100+

Записывать значения вручную или сохранять вывод скрипта для сравнения.

---

## 4. Критерии переключения

Переключаться при **первом** из двух условий:

### Условие ликвидности (предпочтительное)

```
SiU6 avg volume/bar за последние 60 минут основной сессии (10:00–19:00 MSK) >= 500 контрактов/мин
```

Это соответствует ~30% от текущего объёма SiM6 и является достаточным для надёжного исполнения стопов и тейков при 1 контракте.

Проверить:
```bash
cd /opt/hammertrade
.venv/bin/python scripts/check_rollover_siu6.py
# смотреть avg vol last 10 во время основной сессии
```

### Крайняя дата (жёсткий дедлайн)

**2026-06-10 (среда)** — 9 рабочих дней до экспирации SiM6 (2026-06-19).

Независимо от ликвидности SiU6, к этой дате нужно переключиться, потому что:
- SiM6 к этому моменту начинает терять ликвидность из-за ухода OI
- Торговля на умирающем контракте даёт ложные сигналы и широкие спреды

---

## 5. Runbook переключения

### Подготовка (за день до переключения)

1. Убедиться, что оба сервиса работают нормально:
   ```bash
   cd /opt/hammertrade
   .venv/bin/python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json
   .venv/bin/python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL_maxhold5.json
   ```
2. Запустить итоговый A/B отчёт и сохранить:
   ```bash
   .venv/bin/python scripts/compare_paper_experiments.py \
     --baseline-db data/paper/paper_state.sqlite \
     --experiment-db data/paper/paper_state_maxhold5.sqlite
   ```
3. Запустить полную диагностику обоих экспериментов и сохранить:
   ```bash
   .venv/bin/python scripts/paper_diagnostics.py \
     --state-db data/paper/paper_state.sqlite --direction SELL
   .venv/bin/python scripts/paper_diagnostics.py \
     --state-db data/paper/paper_state_maxhold5.sqlite \
     --direction SELL --experiment-name maxhold5
   ```

---

### Шаг 1 — Переключение maxhold5

#### 1.1 Проверить open_trades ОБЯЗАТЕЛЬНО перед остановкой

```bash
.venv/bin/python scripts/check_paper_status.py \
  --status-file runtime/paper_status_SiM6_SELL_maxhold5.json
```

Если `open_trades: 1` — ждать закрытия позиции (стоп/тейк/MAX_HOLD_EXIT).
Не останавливать сервис с открытой позицией.

#### 1.2 Остановить сервис

```bash
sudo systemctl stop hammertrade-paper-maxhold5.service
```

#### 1.3 Архивировать старые данные

```bash
DATE=$(date +%Y%m%d)
cp data/paper/paper_state_maxhold5.sqlite \
   data/paper/paper_state_maxhold5_SiM6_ARCHIVED_${DATE}.sqlite
cp runtime/paper_status_SiM6_SELL_maxhold5.json \
   runtime/paper_status_SiM6_SELL_maxhold5_ARCHIVED_${DATE}.json
```

Старые файлы НЕ удалять.

#### 1.4 Обновить systemd unit-файл для maxhold5

Изменить только следующие параметры (остальное — без изменений):

```
--ticker SiU6
--state-db data/paper/paper_state_siu6_maxhold5.sqlite
--status-file runtime/paper_status_SiU6_SELL_maxhold5.json
--trades-output out/paper/paper_trades_SiU6_SELL_maxhold5.csv
--log-file logs/paper_SiU6_SELL_maxhold5.log
```

```bash
sudo systemctl daemon-reload
```

#### 1.5 Запустить и проверить

```bash
sudo systemctl start hammertrade-paper-maxhold5.service
sleep 15
.venv/bin/python scripts/check_paper_status.py \
  --status-file runtime/paper_status_SiU6_SELL_maxhold5.json
```

Ожидаемый результат:
```
[OK]  SiU6 SELL  pid=...
  liveness   : OK  fetch=OK
```

Подождать 5 минут, убедиться что `trading_liveness_status = OK` и `consecutive_api_errors = 0`.

---

### Шаг 2 — Переключение baseline (через 15–30 минут после шага 1)

Повторить те же шаги для baseline:

#### 2.1 Проверить open_trades

```bash
.venv/bin/python scripts/check_paper_status.py \
  --status-file runtime/paper_status_SiM6_SELL.json
```

Если `open_trades: 1` — ждать закрытия.

#### 2.2 Остановить сервис

```bash
sudo systemctl stop hammertrade-paper.service
```

#### 2.3 Архивировать

```bash
DATE=$(date +%Y%m%d)
cp data/paper/paper_state.sqlite \
   data/paper/paper_state_SiM6_ARCHIVED_${DATE}.sqlite
cp runtime/paper_status_SiM6_SELL.json \
   runtime/paper_status_SiM6_SELL_ARCHIVED_${DATE}.json
```

#### 2.4 Обновить unit-файл baseline

```
--ticker SiU6
--state-db data/paper/paper_state_siu6.sqlite
--status-file runtime/paper_status_SiU6_SELL.json
--trades-output out/paper/paper_trades_SiU6_SELL.csv
--log-file logs/paper_SiU6_SELL.log
```

```bash
sudo systemctl daemon-reload
```

#### 2.5 Запустить и проверить

```bash
sudo systemctl start hammertrade-paper.service
sleep 15
.venv/bin/python scripts/check_paper_status.py \
  --status-file runtime/paper_status_SiU6_SELL.json
```

---

### Шаг 3 — Финальная проверка

```bash
.venv/bin/python scripts/paper_error_report.py \
  --status-files runtime/paper_status_SiU6_SELL.json \
                 runtime/paper_status_SiU6_SELL_maxhold5.json

journalctl -u hammertrade-paper -n 50 --no-pager
journalctl -u hammertrade-paper-maxhold5 -n 50 --no-pager
```

Убедиться:
- Оба сервиса `active (running)`
- `trading_liveness_status = OK`
- `ticker = SiU6` в status JSON
- `max_hold_bars = None` у baseline
- `max_hold_bars = 5` у maxhold5
- `consecutive_api_errors` не растёт

---

## 6. Новые имена артефактов

| Артефакт | Baseline (SiU6) | Maxhold5 (SiU6) |
|---|---|---|
| SQLite DB | `data/paper/paper_state_siu6.sqlite` | `data/paper/paper_state_siu6_maxhold5.sqlite` |
| Status file | `runtime/paper_status_SiU6_SELL.json` | `runtime/paper_status_SiU6_SELL_maxhold5.json` |
| Trades CSV | `out/paper/paper_trades_SiU6_SELL.csv` | `out/paper/paper_trades_SiU6_SELL_maxhold5.csv` |
| Log file | `logs/paper_SiU6_SELL.log` | `logs/paper_SiU6_SELL_maxhold5.log` |

Архивные данные SiM6 остаются нетронутыми:

| Архив | Путь |
|---|---|
| Baseline DB | `data/paper/paper_state_SiM6_ARCHIVED_YYYYMMDD.sqlite` |
| Maxhold5 DB | `data/paper/paper_state_maxhold5_SiM6_ARCHIVED_YYYYMMDD.sqlite` |

---

## 7. Rollback plan

Если после переключения SiU6 показывает проблемы (STALLED, тонкий рынок, аномальные сигналы):

```bash
# Остановить проблемный сервис
sudo systemctl stop hammertrade-paper-maxhold5.service

# Восстановить unit-файл на SiM6 параметры
# (--ticker SiM6, старые пути к DB и status)
sudo systemctl daemon-reload

# Восстановить последний рабочий status файл (если нужно для мониторинга)
cp runtime/paper_status_SiM6_SELL_maxhold5_ARCHIVED_YYYYMMDD.json \
   runtime/paper_status_SiM6_SELL_maxhold5.json

# Запустить обратно
sudo systemctl start hammertrade-paper-maxhold5.service
sleep 15
.venv/bin/python scripts/check_paper_status.py \
  --status-file runtime/paper_status_SiM6_SELL_maxhold5.json
```

Старые DB не удалялись — просто вернуть путь в unit-файле.

**Rollback возможен** пока SiM6 торгуется с нормальной ликвидностью, то есть до примерно 2026-06-15. После этого возврат на SiM6 теряет смысл.

---

## 8. Что НЕ менять при роллировании

Следующие параметры остаются **идентичными** для SiU6 и не пересматриваются в рамках этого MVP:

| Параметр | Значение | Причина |
|---|---|---|
| HammerDetector | без изменений | паттерн инструментно-независимый |
| Параметры детектора | `configs/hammer_detector_balanced.env` | без изменений |
| `--direction-filter` | `SELL` | без изменений |
| `--entry-mode` | `breakout` | без изменений |
| `--take-r` | `1.0` | без изменений |
| `--stop-buffer-points` | `0.0` | без изменений |
| `--slippage-ticks` | `1.0` | без изменений |
| `--contracts` | `1` | без изменений |
| `--max-hold-bars` baseline | `None` | без изменений |
| `--max-hold-bars` maxhold5 | `5` | без изменений |
| `--poll-interval-seconds` | `20` | без изменений |
| `--lookback-candles` | `300` | без изменений |
| `--market-hours-config` | `configs/market_hours/moex_futures.yaml` | без изменений |
| `--api-timeout-sec` | `10` | без изменений |
| `--env` | `prod` | без изменений |
| `.env` | без изменений | READONLY_TOKEN |

Единственные изменения: `--ticker SiU6` и новые пути к DB/status/csv/log.

---

## 9. Контрольный лист дня роллирования

```
[ ] 1. Ликвидность SiU6 >= 500 avg vol/bar (осн. сессия) ИЛИ дата >= 2026-06-10
[ ] 2. A/B эксперимент maxhold5 завершён (>= 50 сделок, вывод сделан)
[ ] 3. Сохранён итоговый A/B отчёт (compare_paper_experiments.py)
[ ] 4. Сохранена полная диагностика baseline и maxhold5 на SiM6
[ ] 5. open_trades = 0 у maxhold5 перед остановкой
[ ] 6. maxhold5 архивирован и запущен на SiU6 → liveness OK
[ ] 7. open_trades = 0 у baseline перед остановкой
[ ] 8. baseline архивирован и запущен на SiU6 → liveness OK
[ ] 9. paper_error_report.py показывает оба сервиса OK
[ ] 10. Тикер SiU6 в status JSON обоих сервисов подтверждён
```
