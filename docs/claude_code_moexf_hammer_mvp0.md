# Задача для Claude Code: MOEXF Hammer Bot — MVP-0 Explainable Detector

Ты работаешь как исполнитель реализации в Python-проекте `moexf_hammer_bot`.

## Контекст проекта

Проект посвящён исследованию торговой стратегии для фьючерсов MOEXF на Московской бирже.

Основная идея — находить разворотные свечные паттерны:

- BUY-молот;
- SELL-перевёрнутый молот;
- SELL-верхняя игла.

На текущем этапе запрещено делать live trading.

Нужно реализовать первый исследовательский MVP без брокерского API:

```text
CSV candles -> candle geometry -> hammer detector -> debug CSV
```

Главная цель MVP — не прибыль и не торговля, а возможность понять:

- какие свечи стали сигналами;
- какие свечи были отклонены;
- почему они были отклонены;
- какие фильтры режут хорошие визуальные зоны.

## Важные торговые условия

Заложи эти значения в конфиг, даже если не все будут использоваться сразу:

```text
POINT_VALUE_RUB=10
COMMISSION_PER_TRADE=0.025
COMMISSION_ROUND_TURN=0.05
CLEARING_1=13:55
CLEARING_2=18:45
TIMEZONE=Europe/Moscow
```

Клиринг:

```text
13:55 Moscow time
18:45 Moscow time
```

Для первого MVP нужно уметь отфильтровывать сигналы около клиринга, если включён параметр `S_CLEARING_ENABLE=1`.

Стартовое окно блокировки:

```text
CLEARING_BLOCK_BEFORE_MIN=5
CLEARING_BLOCK_AFTER_MIN=5
```

## Что нельзя делать

Не делай:

- подключение брокерского API;
- live trading;
- выставление реальных заявок;
- работу с API брокера;
- хранение брокерских ключей;
- автоподбор параметров под максимальную прибыль;
- удаление debug-логики;
- смешивание strategy и execution.

Если понадобится модуль execution, пока создай только заглушку или paper/backtest-ориентированную структуру без реальных заявок.

---

# Задача MVP-0

## 1. Создай структуру проекта

Создай такую структуру:

```text
moexf_hammer_bot/
├── configs/
│   ├── hammer_detector_balanced.env
│   ├── hammer_detector_strict.env
│   ├── hammer_detector_loose.env
│   └── hammer_detector_sell_upper_wick.env
├── data/
│   ├── raw/
│   └── processed/
├── docs/
├── logs/
├── out/
├── reports/
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── market_data/
│   │   ├── __init__.py
│   │   └── loader.py
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── candle_geometry.py
│   │   ├── hammer_detector.py
│   │   └── signal.py
│   ├── risk/
│   │   ├── __init__.py
│   │   └── clearing.py
│   ├── storage/
│   │   ├── __init__.py
│   │   └── debug_repository.py
│   └── analytics/
│       ├── __init__.py
│       └── summary.py
├── tests/
│   ├── test_candle_geometry.py
│   ├── test_hammer_detector.py
│   └── test_clearing.py
├── requirements.txt
└── README.md
```

## 2. Создай baseline config

Файл:

```text
configs/hammer_detector_balanced.env
```

Содержимое:

```env
S_BODY_MIN_FRAC=0.12
S_BODY_MAX_FRAC=0.33
S_WICK_MULT=2.3
S_OPP_WICK_MAX_FRAC=0.70
S_WICK_DOM_RATIO=2.0
S_EXT_WINDOW=5
S_EXT_EPS_TICKS=1.0
S_NEIGHBOR_MODE=left_or_right
S_NEIGHBOR_EPS_TICKS=1.0
S_MIN_RANGE_TICKS=2.0
S_MIN_WICK_TICKS=1.5
S_OPP_WICK_MAX_ABS_TICKS=2.0
S_CLOSE_POS_FRAC=0.60
S_SILHOUETTE_MIN_FRAC=0.45
S_MIN_EXCURSION_TICKS=2.0
S_EXCURSION_HORIZON=2
S_FALLBACK_TICK=0.5
S_CLEARING_ENABLE=1
S_CONFIRM_MODE=break
S_CONFIRM_HORIZON=1
S_COOLDOWN_BARS=3
POINT_VALUE_RUB=10
COMMISSION_PER_TRADE=0.025
COMMISSION_ROUND_TURN=0.05
CLEARING_BLOCK_BEFORE_MIN=5
CLEARING_BLOCK_AFTER_MIN=5
TIMEZONE=Europe/Moscow
```

Также создай остальные профили.

Файл:

```text
configs/hammer_detector_strict.env
```

```env
S_BODY_MIN_FRAC=0.15
S_BODY_MAX_FRAC=0.30
S_WICK_MULT=2.5
S_OPP_WICK_MAX_FRAC=0.60
S_WICK_DOM_RATIO=2.5
S_EXT_WINDOW=5
S_EXT_EPS_TICKS=1.0
S_NEIGHBOR_MODE=left_or_right
S_NEIGHBOR_EPS_TICKS=1.0
S_MIN_RANGE_TICKS=2.0
S_MIN_WICK_TICKS=1.5
S_OPP_WICK_MAX_ABS_TICKS=2.0
S_CLOSE_POS_FRAC=0.60
S_SILHOUETTE_MIN_FRAC=0.45
S_MIN_EXCURSION_TICKS=2.0
S_EXCURSION_HORIZON=2
S_FALLBACK_TICK=0.5
S_CLEARING_ENABLE=1
S_CONFIRM_MODE=break
S_CONFIRM_HORIZON=1
S_COOLDOWN_BARS=5
POINT_VALUE_RUB=10
COMMISSION_PER_TRADE=0.025
COMMISSION_ROUND_TURN=0.05
CLEARING_BLOCK_BEFORE_MIN=5
CLEARING_BLOCK_AFTER_MIN=5
TIMEZONE=Europe/Moscow
```

Файл:

```text
configs/hammer_detector_loose.env
```

```env
S_BODY_MIN_FRAC=0.12
S_BODY_MAX_FRAC=0.33
S_WICK_MULT=2.3
S_OPP_WICK_MAX_FRAC=0.70
S_WICK_DOM_RATIO=1.8
S_EXT_WINDOW=5
S_EXT_EPS_TICKS=1.0
S_NEIGHBOR_MODE=left_or_right
S_NEIGHBOR_EPS_TICKS=1.0
S_MIN_RANGE_TICKS=2.0
S_MIN_WICK_TICKS=1.5
S_OPP_WICK_MAX_ABS_TICKS=2.0
S_CLOSE_POS_FRAC=0.60
S_SILHOUETTE_MIN_FRAC=0.40
S_MIN_EXCURSION_TICKS=1.5
S_EXCURSION_HORIZON=2
S_FALLBACK_TICK=0.5
S_CLEARING_ENABLE=1
S_CONFIRM_MODE=break
S_CONFIRM_HORIZON=1
S_COOLDOWN_BARS=3
POINT_VALUE_RUB=10
COMMISSION_PER_TRADE=0.025
COMMISSION_ROUND_TURN=0.05
CLEARING_BLOCK_BEFORE_MIN=5
CLEARING_BLOCK_AFTER_MIN=5
TIMEZONE=Europe/Moscow
```

Файл:

```text
configs/hammer_detector_sell_upper_wick.env
```

```env
S_BODY_MIN_FRAC=0.12
S_BODY_MAX_FRAC=0.33
S_WICK_MULT=2.2
S_OPP_WICK_MAX_FRAC=0.85
S_WICK_DOM_RATIO=1.7
S_EXT_WINDOW=3
S_EXT_EPS_TICKS=1.5
S_NEIGHBOR_MODE=left_or_right
S_NEIGHBOR_EPS_TICKS=1.0
S_MIN_RANGE_TICKS=2.0
S_MIN_WICK_TICKS=1.5
S_OPP_WICK_MAX_ABS_TICKS=3.0
S_CLOSE_POS_FRAC=0.55
S_SILHOUETTE_MIN_FRAC=0.40
S_MIN_EXCURSION_TICKS=1.0
S_EXCURSION_HORIZON=2
S_FALLBACK_TICK=0.5
S_CLEARING_ENABLE=1
S_CONFIRM_MODE=break
S_CONFIRM_HORIZON=1
S_COOLDOWN_BARS=3
POINT_VALUE_RUB=10
COMMISSION_PER_TRADE=0.025
COMMISSION_ROUND_TURN=0.05
CLEARING_BLOCK_BEFORE_MIN=5
CLEARING_BLOCK_AFTER_MIN=5
TIMEZONE=Europe/Moscow
```

## 3. Реализуй загрузку свечей из CSV

Файл:

```text
src/market_data/loader.py
```

Ожидаемый входной CSV:

```text
timestamp,open,high,low,close,volume
```

Требования:

- читать CSV через pandas;
- парсить `timestamp` как datetime;
- сортировать свечи по времени;
- проверять наличие обязательных колонок;
- приводить `open/high/low/close/volume` к числам;
- при ошибке давать понятное исключение.

## 4. Реализуй расчёт геометрии свечи

Файл:

```text
src/strategy/candle_geometry.py
```

Для каждой свечи рассчитать:

```python
range_ = high - low
body = abs(close - open)
upper_shadow = high - max(open, close)
lower_shadow = min(open, close) - low
body_frac = body / range_
upper_frac = upper_shadow / range_
lower_frac = lower_shadow / range_
close_pos = (close - low) / range_
```

Если `range_ <= 0`, не падать, а корректно пометить такую свечу как невалидную.

## 5. Реализуй HammerDetector

Файл:

```text
src/strategy/hammer_detector.py
```

Нужен класс:

```python
class HammerDetector:
    def __init__(self, params):
        ...

    def detect_all(self, candles_df):
        ...
```

Он должен проверять две стороны:

```text
BUY hammer
SELL inverted hammer / upper wick
```

Для BUY:

- рабочий фитиль: `lower_shadow`;
- встречный фитиль: `upper_shadow`;
- свеча должна быть локальным минимумом;
- close должен быть ближе к верхней части свечи;
- подтверждение: в течение `S_CONFIRM_HORIZON` следующих свечей high пробивает high сигнальной свечи;
- экскурсия: в течение `S_EXCURSION_HORIZON` следующих свечей цена проходит минимум `S_MIN_EXCURSION_TICKS`.

Для SELL:

- рабочий фитиль: `upper_shadow`;
- встречный фитиль: `lower_shadow`;
- свеча должна быть локальным максимумом;
- close должен быть ближе к нижней части свечи;
- подтверждение: в течение `S_CONFIRM_HORIZON` следующих свечей low пробивает low сигнальной свечи;
- экскурсия: в течение `S_EXCURSION_HORIZON` следующих свечей цена проходит минимум `S_MIN_EXCURSION_TICKS`.

## 6. Обязательная explainable-debug логика

Главный результат MVP:

```text
out/debug_simple_all.csv
```

В этом файле должна быть строка для каждой свечи.

Обязательные колонки:

```text
timestamp
instrument
timeframe
open
high
low
close
volume
range
body
upper_shadow
lower_shadow
body_frac
upper_frac
lower_frac
close_pos
direction_candidate
is_signal
fail_reason
params_profile
```

Если данных `instrument` и `timeframe` нет во входном CSV, разреши передавать их через CLI-аргументы.

Например:

```bash
python -m src.main \
  --input data/raw/sample.csv \
  --output out/debug_simple_all.csv \
  --params configs/hammer_detector_balanced.env \
  --instrument SiM6 \
  --timeframe 1m \
  --profile balanced
```

## 7. Правила fail_reason

`fail_reason` должен быть заполнен всегда.

Если свеча стала сигналом:

```text
pass
```

Если свеча отклонена, указывай первый фильтр, на котором она отвалилась.

Минимальный список причин:

```text
range
doji
body_big
dom_fail
sil_fail
wick_abs
opp_abs
ext
neighbors
close_pos
excursion
confirm
clearing
no_candidate
invalid_range
cooldown
```

Дополнительно можно добавить колонку:

```text
fail_reasons
```

В ней можно хранить все причины через `|`, например:

```text
dom_fail|close_pos|confirm
```

Но колонка `fail_reason` обязательна.

## 8. Логика фильтров

Проверки должны идти примерно в таком порядке:

```text
invalid_range
range
doji
body_big
wick_abs
opp_abs
dom_fail
sil_fail
ext
neighbors
close_pos
excursion
confirm
clearing
cooldown
```

### range

Свеча слишком маленькая:

```text
range < S_MIN_RANGE_TICKS * tick_size
```

`tick_size` брать из `S_FALLBACK_TICK`.

### doji

Тело слишком маленькое:

```text
body_frac < S_BODY_MIN_FRAC
```

### body_big

Тело слишком большое:

```text
body_frac > S_BODY_MAX_FRAC
```

### wick_abs

Рабочий фитиль слишком маленький:

```text
working_wick < S_MIN_WICK_TICKS * tick_size
```

### opp_abs

Встречный фитиль слишком большой:

```text
opposite_wick > S_OPP_WICK_MAX_ABS_TICKS * tick_size
```

### dom_fail

Рабочий фитиль недостаточно доминирует:

```text
working_wick < body * S_WICK_MULT
```

или:

```text
working_wick / max(opposite_wick, tick_size) < S_WICK_DOM_RATIO
```

### sil_fail

Рабочий фитиль занимает слишком маленькую часть свечи:

```text
working_wick / range_ < S_SILHOUETTE_MIN_FRAC
```

### close_pos

BUY:

```text
close_pos < S_CLOSE_POS_FRAC
```

SELL:

```text
close_pos > 1 - S_CLOSE_POS_FRAC
```

### ext

BUY:

```text
low должен быть локальным минимумом в окне S_EXT_WINDOW с допуском S_EXT_EPS_TICKS
```

SELL:

```text
high должен быть локальным максимумом в окне S_EXT_WINDOW с допуском S_EXT_EPS_TICKS
```

### confirm

BUY:

```text
в течение S_CONFIRM_HORIZON следующих свечей должен быть пробой high сигнальной свечи
```

SELL:

```text
в течение S_CONFIRM_HORIZON следующих свечей должен быть пробой low сигнальной свечи
```

### excursion

BUY:

```text
max(high следующих S_EXCURSION_HORIZON свечей) - signal_close >= S_MIN_EXCURSION_TICKS * tick_size
```

SELL:

```text
signal_close - min(low следующих S_EXCURSION_HORIZON свечей) >= S_MIN_EXCURSION_TICKS * tick_size
```

### clearing

Если `S_CLEARING_ENABLE=1`, сигнал не должен попадать в окно:

```text
13:55 ± CLEARING_BLOCK_BEFORE_MIN/CLEARING_BLOCK_AFTER_MIN
18:45 ± CLEARING_BLOCK_BEFORE_MIN/CLEARING_BLOCK_AFTER_MIN
```

## 9. Реализуй CLI

Файл:

```text
src/main.py
```

Команда запуска:

```bash
python -m src.main \
  --input data/raw/sample.csv \
  --output out/debug_simple_all.csv \
  --params configs/hammer_detector_balanced.env \
  --instrument SiM6 \
  --timeframe 1m \
  --profile balanced
```

После запуска нужно вывести краткий summary:

```text
Rows processed: N
Signals found: X
BUY signals: B
SELL signals: S
Output written: out/debug_simple_all.csv
Top fail reasons:
- close_pos: ...
- dom_fail: ...
- ext: ...
```

## 10. Requirements

Создай `requirements.txt`:

```text
pandas
python-dotenv
pytest
```

## 11. Тесты

Нужно написать минимальные тесты.

### tests/test_candle_geometry.py

Проверь, что для свечи:

```text
open=100
high=110
low=90
close=105
```

получается:

```text
range=20
body=5
upper_shadow=5
lower_shadow=10
body_frac=0.25
upper_frac=0.25
lower_frac=0.5
close_pos=0.75
```

### tests/test_hammer_detector.py

Сделай маленький synthetic dataframe, где есть очевидный BUY-молот:

```text
до сигнала цена снижается
сигнальная свеча имеет длинную нижнюю тень
close находится в верхней части range
следующая свеча пробивает high сигнальной свечи
```

Проверь:

```text
is_signal == True
direction_candidate == BUY
fail_reason == pass
```

Сделай второй synthetic dataframe, где свеча похожа на доджи:

```text
body_frac < S_BODY_MIN_FRAC
```

Проверь:

```text
is_signal == False
fail_reason == doji
```

### tests/test_clearing.py

Проверь, что время около:

```text
13:55
18:45
```

попадает в clearing block, а обычное время не попадает.

## 12. README

В `README.md` опиши:

- что это research-проект;
- что live trading пока запрещён;
- какой CSV нужен на вход;
- как запустить;
- какой файл появляется на выходе;
- что означает `fail_reason`;
- что будет следующим этапом.

## 13. Definition of Done

Задача считается выполненной, если:

1. Проект запускается командой:

```bash
python -m src.main \
  --input data/raw/sample.csv \
  --output out/debug_simple_all.csv \
  --params configs/hammer_detector_balanced.env \
  --instrument SiM6 \
  --timeframe 1m \
  --profile balanced
```

2. Создаётся файл:

```text
out/debug_simple_all.csv
```

3. В debug-файле есть строка для каждой входной свечи.

4. В debug-файле есть колонка:

```text
fail_reason
```

5. Для сигналов:

```text
fail_reason=pass
is_signal=True
```

6. Для отклонённых свечей `fail_reason` содержит понятную причину.

7. Тесты проходят:

```bash
pytest
```

8. В проекте нет broker API, live trading и реальных заявок.

## 14. В конце работы дай отчёт

После реализации напиши краткий отчёт:

```text
Созданные файлы:
...

Как запустить:
...

Формат входного CSV:
...

Формат выходного debug CSV:
...

Какие тесты добавлены:
...

Что пока не реализовано:
...
```
