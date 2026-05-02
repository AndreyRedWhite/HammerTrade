# Быстрый фикс: `--skip-load` для `run_universe_research.py`

## Контекст

В проекте уже есть:

```text
scripts/run_full_research_pipeline.sh
scripts/run_universe_research.py
```

`run_full_research_pipeline.sh` уже поддерживает флаг:

```bash
--skip-load
```

Он нужен, чтобы не обращаться к T-Bank API и использовать уже скачанный CSV:

```text
data/raw/tbank/<RUN_ID>.csv
```

Сейчас проблема в том, что `run_universe_research.py` запускает несколько pipeline-команд по universe CSV, но не пробрасывает `--skip-load` внутрь каждой команды.

Из-за этого при запуске universe research скрипт снова пытается ходить в T-Bank API.

На текущей сети T-Bank API отдаёт TLS-цепочку через `Russian Trusted Root CA`, что приводит к ошибке:

```text
CERTIFICATE_VERIFY_FAILED: self signed certificate in certificate chain
```

Пользователь не будет добавлять этот root CA в trust store и не будет отключать TLS verification.

Нужно дать возможность пересчитать уже загруженные CSV без сетевых вызовов.

---

## Цель фикса

Добавить в:

```text
scripts/run_universe_research.py
```

поддержку флага:

```bash
--skip-load
```

Чтобы можно было запускать:

```bash
python scripts/run_universe_research.py \
  --universe data/instruments/liquid_futures_2026-03-01_2026-04-10.csv \
  --top 5 \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --timeframe 1m \
  --profile balanced \
  --env prod \
  --skip-load \
  --skip-walkforward-grid
```

И чтобы каждая команда внутри batch запускалась примерно так:

```bash
bash scripts/run_full_research_pipeline.sh \
  --ticker CRM6 \
  --class-code SPBFUT \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --timeframe 1m \
  --profile balanced \
  --env prod \
  --direction-filter all \
  --slippage-points 0 \
  --take-r 1.0 \
  --max-hold-bars 30 \
  --point-value-rub 1000.0 \
  --tick-size 0.001 \
  --skip-load \
  --skip-walkforward-grid
```

---

## Важно

Не делать:

- отключение TLS verification;
- установку Russian Trusted Root CA;
- `curl -k`;
- изменение T-Bank client;
- изменение сертификатов;
- изменение токенов;
- live trading;
- sandbox orders;
- broker execution;
- сетевые вызовы из Claude Code.

Этот фикс только про проброс `--skip-load`.

---

# Что нужно изменить

## 1. CLI argparse

В `scripts/run_universe_research.py` добавить аргумент:

```python
parser.add_argument(
    "--skip-load",
    action="store_true",
    help="Do not call T-Bank API inside each pipeline; use existing raw CSV files.",
)
```

---

## 2. Command builder

Найти функцию, которая строит команды для каждого тикера.

Если `args.skip_load == True`, добавить в команду:

```text
--skip-load
```

Важно: флаг должен попасть именно в команду `run_full_research_pipeline.sh`.

---

## 3. Dry-run / preview output

Если скрипт показывает команды перед запуском, в preview тоже должен быть виден:

```text
--skip-load
```

Например:

```text
Command: bash ... run_full_research_pipeline.sh ... --skip-load --skip-walkforward-grid
```

---

## 4. User-facing text

В выводе `Universe Research Batch Runner` добавить строку:

```text
Skip load: yes/no
```

Пример:

```text
Universe Research Batch Runner
==============================

Universe file: ...
Top N: ...
Period: ...
Timeframe: ...
Profile: ...
Skip load: yes
```

---

## 5. README

Обновить README в разделе universe research.

Добавить пример:

```bash
python scripts/run_universe_research.py \
  --universe data/instruments/liquid_futures_2026-03-01_2026-04-10.csv \
  --top 5 \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --timeframe 1m \
  --profile balanced \
  --env prod \
  --skip-load \
  --skip-walkforward-grid
```

И пояснение:

```text
Use --skip-load when raw candle CSV files already exist and you do not want to call T-Bank API again.
This is useful when network/TLS restrictions prevent connecting to T-Bank API.
```

---

# Тесты

Добавить/обновить тесты.

Если уже есть:

```text
tests/test_universe_research_tick_size.py
```

или тесты command builder — расширить их.

## Обязательные проверки

1. Когда `skip_load=True`, command содержит:

```text
--skip-load
```

2. Когда `skip_load=False`, command не содержит:

```text
--skip-load
```

3. Если одновременно указаны:

```text
--skip-load
--skip-walkforward-grid
```

команда содержит оба флага.

4. Preview/dry-run не запускает subprocess.

---

# Проверка вручную

Разрешено запускать только локальные проверки, не делающие T-Bank API-запросы:

```bash
python scripts/run_universe_research.py --help
```

```bash
pytest
```

Можно также проверить dry-run/preview, если он не запускает pipeline.

Не запускать реальный universe research из Claude Code.

---

# Definition of Done

Фикс готов, если:

1. `scripts/run_universe_research.py` принимает `--skip-load`.
2. `--skip-load` пробрасывается в каждую команду `run_full_research_pipeline.sh`.
3. Preview команд показывает `--skip-load`.
4. В summary выводится `Skip load: yes/no`.
5. README обновлён.
6. Тесты проходят:

```bash
pytest
```

7. Никакие T-Bank API вызовы не выполнялись из Claude Code.

---

# Отчёт после выполнения

После реализации напиши:

```text
Что изменено:
...

Как теперь запускать universe research без T-Bank API:
...

Что проверено:
...

Что НЕ запускалось и почему:
...
```

В блоке "Что НЕ запускалось и почему" обязательно указать:

```text
T-Bank API и полный universe research не запускались из Claude Code. Пользователь сам запустит команду локально, когда нужно. Фикс нужен, чтобы можно было использовать уже скачанные CSV через --skip-load.
```
