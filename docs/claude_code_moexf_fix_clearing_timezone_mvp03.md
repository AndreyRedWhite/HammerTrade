# Задача MVP-0.3: Fix clearing timezone + улучшение time handling

## Контекст

В проекте уже реализованы:

```text
MVP-0:
CSV candles -> candle geometry -> HammerDetector -> out/debug_simple_all.csv

MVP-0.1:
out/debug_simple_all.csv -> reports/debug_report.md

MVP-0.2:
T-Bank historical candles loader -> normalized CSV -> data quality report
```

После загрузки реальных свечей из T-Bank API по SiM6 1m за 2026-04-01 — 2026-04-10 обнаружена важная проблема.

T-Bank отдаёт timestamp в UTC:

```text
2026-04-01 10:55:00+00:00
```

А клиринговые окна в проекте заданы по московскому времени:

```text
13:55 Europe/Moscow
18:45 Europe/Moscow
```

Сейчас `clearing.py`, судя по поведению, сравнивает `dt.time()` напрямую с `13:55` и `18:45`. Если timestamp приходит в UTC, то время `10:55 UTC` не распознаётся как `13:55 MSK`.

Это критично: clearing-фильтр может пропускать сигналы около дневного и вечернего клиринга.

---

## Цель задачи

Исправить обработку timezone в clearing-фильтре.

Правильное поведение:

```text
любой timestamp -> привести к Europe/Moscow -> сравнить с clearing windows
```

То есть:

```text
2026-04-01 10:55:00+00:00
```

должен быть интерпретирован как:

```text
2026-04-01 13:55:00+03:00 Europe/Moscow
```

и попадать в clearing block.

---

## Что нельзя делать

Не делать:

- backtest;
- live trading;
- broker execution;
- sandbox orders;
- postOrder;
- изменение торговой логики детектора;
- изменение параметров стратегии;
- оптимизацию сигналов;
- работу с реальными заявками.

Эта задача только про корректную работу timezone/clearing.

---

# Что нужно исправить

## 1. Исправить `src/risk/clearing.py`

Найти текущую функцию, которая проверяет попадание timestamp в clearing block.

Сделать так, чтобы она:

1. принимала datetime;
2. если datetime timezone-aware — приводила его к `Europe/Moscow`;
3. если datetime naive — трактовала его как `Europe/Moscow`, либо использовала явно заданный timezone из конфига;
4. сравнивала уже московское время с клиринговыми окнами.

Пример ожидаемой логики:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

def to_moscow_time(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MOSCOW_TZ)
    return dt.astimezone(MOSCOW_TZ)
```

После этого checking logic должна использовать:

```python
dt_msk = to_moscow_time(dt)
current_time = dt_msk.time()
```

---

## 2. Поддержать параметры из env/config

Если в проекте уже есть параметр:

```env
TIMEZONE=Europe/Moscow
```

использовать его.

Если нет — дефолт:

```text
Europe/Moscow
```

Не хардкодить UTC.

---

## 3. Проверить оба клиринга

Клиринги:

```text
13:55 Moscow time
18:45 Moscow time
```

Окно блокировки из конфига:

```env
CLEARING_BLOCK_BEFORE_MIN=5
CLEARING_BLOCK_AFTER_MIN=5
```

При таких настройках должны блокироваться:

```text
13:50 — 14:00 MSK
18:40 — 18:50 MSK
```

Важно: границы должны быть включительными, если в текущей логике проекта нет другого явного решения.

---

# Тесты

Обновить или добавить тесты:

```text
tests/test_clearing.py
```

## Обязательные кейсы

### 1. UTC timestamp дневного клиринга

```python
datetime(2026, 4, 1, 10, 55, tzinfo=ZoneInfo("UTC"))
```

Это `13:55 Europe/Moscow`.

Ожидание:

```text
is_in_clearing_window == True
```

### 2. UTC timestamp за 5 минут до дневного клиринга

```python
datetime(2026, 4, 1, 10, 50, tzinfo=ZoneInfo("UTC"))
```

Это `13:50 Europe/Moscow`.

Ожидание:

```text
True
```

### 3. UTC timestamp через 5 минут после дневного клиринга

```python
datetime(2026, 4, 1, 11, 0, tzinfo=ZoneInfo("UTC"))
```

Это `14:00 Europe/Moscow`.

Ожидание:

```text
True
```

### 4. UTC timestamp вне окна дневного клиринга

```python
datetime(2026, 4, 1, 11, 1, tzinfo=ZoneInfo("UTC"))
```

Это `14:01 Europe/Moscow`.

Ожидание:

```text
False
```

### 5. UTC timestamp вечернего клиринга

```python
datetime(2026, 4, 1, 15, 45, tzinfo=ZoneInfo("UTC"))
```

Это `18:45 Europe/Moscow`.

Ожидание:

```text
True
```

### 6. Naive timestamp

```python
datetime(2026, 4, 1, 13, 55)
```

Ожидание:

```text
True
```

В рамках проекта naive datetime считаем московским временем, если иное явно не задано.

### 7. Timestamp already in Europe/Moscow

```python
datetime(2026, 4, 1, 13, 55, tzinfo=ZoneInfo("Europe/Moscow"))
```

Ожидание:

```text
True
```

---

# Проверка на реальном debug pipeline

После фикса нужно заново прогнать пайплайн на уже загруженном CSV:

```bash
python -m src.main \
  --input data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv \
  --output out/debug_simple_all.csv \
  --params configs/hammer_detector_balanced.env \
  --instrument SiM6 \
  --timeframe 1m \
  --profile balanced
```

Затем:

```bash
python -m src.analytics.debug_report \
  --input out/debug_simple_all.csv \
  --output reports/debug_report.md
```

Сравнить новый отчёт со старым.

Ожидаемый результат:

- количество `clearing` fail_reason должно стать более правдоподобным;
- сигналы около 10:50–11:00 UTC и 15:40–15:50 UTC должны блокироваться как клиринг;
- общее количество сигналов может немного уменьшиться.

---

# Дополнительная диагностика

Добавить в debug report или отдельный console summary необязательно, но желательно:

```text
Timestamps timezone: UTC / Europe/Moscow / naive
```

Если это сложно — не делать в этой задаче.

---

# Definition of Done

Задача выполнена, если:

1. `clearing.py` корректно приводит timestamp к `Europe/Moscow` перед сравнением.
2. UTC timestamp `10:55+00:00` распознаётся как дневной клиринг `13:55 MSK`.
3. UTC timestamp `15:45+00:00` распознаётся как вечерний клиринг `18:45 MSK`.
4. Naive datetime корректно обрабатываются как московское время.
5. Тесты проходят:

```bash
pytest
```

6. После повторного запуска детектора формируется новый `out/debug_simple_all.csv`.
7. После повторного запуска debug report формируется новый `reports/debug_report.md`.
8. В проекте не добавлены broker execution, sandbox orders, live trading или реальные заявки.

---

# Отчёт после выполнения

В конце работы напиши:

```text
Что исправлено:
...

Какие тесты добавлены/обновлены:
...

Как проверить на реальном CSV:
...

Что изменилось в новом debug_report:
...

Что пока не реализовано:
...
```

В блоке "Что пока не реализовано" обязательно укажи:

```text
- backtest пока не реализован;
- paper trading пока не реализован;
- sandbox orders не реализованы;
- live trading не реализован.
```
