# Быстрый фикс: понятная ротация архивов и latest/actual архив

## Контекст

В проекте есть full research pipeline:

```text
scripts/run_full_research_pipeline.sh
```

Он создаёт архивы вида:

```text
archives/research_<RUN_ID>.zip
```

Проблема: при повторных прогонах с тем же `RUN_ID` архив перезаписывается тем же именем. Из-за этого легко перепутать старый и новый архив, особенно когда пользователь загружает результаты в чат.

Пример:

```text
archives/research_CRM6_1m_2026-03-01_2026-04-10_balanced.zip
```

После доработок вроде `tick_size-aware detector` архив имеет то же имя, что и старый pre-fix архив. Визуально непонятно, какой архив актуальный.

Нужно сделать архивацию более явной.

---

## Цель фикса

Добавить в pipeline понятную систему архивов:

1. каждый новый архив должен иметь уникальную timestamp-метку;
2. рядом должен создаваться/обновляться `latest` / `actual` архив для быстрого поиска последнего результата;
3. старые архивы не должны мешаться в общей папке;
4. должна быть возможность быстро понять, какой архив свежий.

---

# Предлагаемая структура

Сейчас:

```text
archives/
  research_<RUN_ID>.zip
```

Сделать:

```text
archives/
  latest/
    Actual_<RUN_ID>.zip
    Actual_<RUN_ID>.manifest.txt

  old/
    research_<RUN_ID>_<YYYYMMDD_HHMMSS>.zip
    research_<RUN_ID>_<YYYYMMDD_HHMMSS>.manifest.txt
```

## Пример

Для `RUN_ID`:

```text
CRM6_1m_2026-03-01_2026-04-10_balanced
```

создавать:

```text
archives/latest/Actual_CRM6_1m_2026-03-01_2026-04-10_balanced.zip
archives/latest/Actual_CRM6_1m_2026-03-01_2026-04-10_balanced.manifest.txt
```

и timestamp-копию:

```text
archives/old/research_CRM6_1m_2026-03-01_2026-04-10_balanced_20260430_200130.zip
archives/old/research_CRM6_1m_2026-03-01_2026-04-10_balanced_20260430_200130.manifest.txt
```

---

# Что должно быть в manifest

Создавать manifest-файл рядом с архивом.

Пример:

```text
Run ID: CRM6_1m_2026-03-01_2026-04-10_balanced
Created at: 2026-04-30T20:01:30+03:00
Ticker: CRM6
Class code: SPBFUT
Timeframe: 1m
Period: 2026-03-01 -> 2026-04-10
Profile: balanced
Direction filter: all
Point value RUB: 1000.0
Tick size: 0.001
Tick size source: user
Skip load: true
Skip grid: false
Skip walkforward grid: true

Files included:
- data/raw/tbank/CRM6_1m_2026-03-01_2026-04-10_balanced.csv
- out/debug_simple_all_CRM6_1m_2026-03-01_2026-04-10_balanced.csv
- reports/debug_report_CRM6_1m_2026-03-01_2026-04-10_balanced.md
...
```

Важно: manifest не должен содержать токены и `.env`.

---

# Поведение архивации

Обновить `scripts/run_full_research_pipeline.sh`.

## 1. Создавать директории

```bash
mkdir -p archives/latest archives/old
```

## 2. Timestamp

Сформировать timestamp:

```bash
ARCHIVE_TS="$(date '+%Y%m%d_%H%M%S')"
```

## 3. Имена архивов

```bash
ACTUAL_ARCHIVE="archives/latest/Actual_${RUN_ID}.zip"
ACTUAL_MANIFEST="archives/latest/Actual_${RUN_ID}.manifest.txt"

OLD_ARCHIVE="archives/old/research_${RUN_ID}_${ARCHIVE_TS}.zip"
OLD_MANIFEST="archives/old/research_${RUN_ID}_${ARCHIVE_TS}.manifest.txt"
```

## 4. Архивировать в old

Основной zip собирать в:

```text
archives/old/research_<RUN_ID>_<TIMESTAMP>.zip
```

## 5. Копировать в latest

После успешного создания old-архива:

```bash
cp "${OLD_ARCHIVE}" "${ACTUAL_ARCHIVE}"
cp "${OLD_MANIFEST}" "${ACTUAL_MANIFEST}"
```

Так пользователь всегда может брать из:

```text
archives/latest/
```

самую свежую актуальную версию конкретного `RUN_ID`.

---

# Важное замечание

Не нужно создавать один общий `Actual.tar.gz` для всех прогонов, потому что если подряд запустить 5 инструментов, один общий `Actual.tar.gz` будет постоянно перетираться и будет непонятно, к какому инструменту он относится.

Лучше:

```text
Actual_<RUN_ID>.zip
```

Так будет понятно:

```text
Actual_CRM6_...
Actual_BRK6_...
Actual_SiM6_...
```

---

# Что вывести в конце pipeline

В конце вместо старого:

```text
Archive created: archives/research_<RUN_ID>.zip
```

вывести:

```text
Archive created:
  Latest: archives/latest/Actual_<RUN_ID>.zip
  Timestamped: archives/old/research_<RUN_ID>_<YYYYMMDD_HHMMSS>.zip

Manifest:
  Latest: archives/latest/Actual_<RUN_ID>.manifest.txt
  Timestamped: archives/old/research_<RUN_ID>_<YYYYMMDD_HHMMSS>.manifest.txt
```

И в списке recommended files добавить `Latest archive`.

---

# Что делать со старыми архивами

Не нужно автоматически переносить все уже существующие старые архивы, чтобы не усложнять задачу.

Но если в `archives/` уже есть старый файл:

```text
archives/research_<RUN_ID>.zip
```

можно:

1. оставить как есть;
2. либо при следующем запуске не трогать;
3. новый формат будет использовать `archives/latest/` и `archives/old/`.

Если хочешь добавить миграцию — только простую и безопасную:

```text
если archives/research_<RUN_ID>.zip существует, не удалять его автоматически
```

---

# Флаг совместимости

Оставить `--no-archive` как есть.

Если `--no-archive` передан:

- не создавать old archive;
- не создавать latest archive;
- не создавать manifest.

---

# README

Обновить README.

Добавить раздел:

```markdown
## Research archives
```

Описать:

1. Где искать актуальные архивы:

```text
archives/latest/Actual_<RUN_ID>.zip
```

2. Где хранятся timestamp-копии:

```text
archives/old/research_<RUN_ID>_<YYYYMMDD_HHMMSS>.zip
```

3. Что такое manifest:

```text
archives/latest/Actual_<RUN_ID>.manifest.txt
```

4. Что `.env` и токены не попадают в архив.

5. Как быстро найти свежие архивы:

```bash
ls -lt archives/latest/
ls -lt archives/old/ | head
```

---

# Тесты / проверки

Это bash-фикс, поэтому достаточно лёгких проверок.

Если есть тесты для pipeline — обновить их.

Если нет, сделать минимальные локальные проверки без T-Bank API:

1. `./scripts/run_full_research_pipeline.sh --help` работает.
2. `--no-archive` не создаёт архив.
3. При archive enabled формируются правильные пути переменных.
4. Manifest generation-функция, если вынесена в helper, создаёт файл без `.env`.

Не запускать T-Bank API из Claude Code.

---

# Definition of Done

Фикс готов, если:

1. Новый архив создаётся в:

```text
archives/old/research_<RUN_ID>_<TIMESTAMP>.zip
```

2. Latest-копия создаётся в:

```text
archives/latest/Actual_<RUN_ID>.zip
```

3. Создаются manifest-файлы:

```text
archives/old/research_<RUN_ID>_<TIMESTAMP>.manifest.txt
archives/latest/Actual_<RUN_ID>.manifest.txt
```

4. Manifest содержит:
   - RUN_ID;
   - created_at;
   - ticker;
   - period;
   - timeframe;
   - profile;
   - direction_filter;
   - point_value_rub;
   - tick_size;
   - tick_size_source;
   - список файлов.
5. Manifest не содержит `.env` и токены.
6. `--no-archive` отключает создание архивов и manifest.
7. README обновлён.
8. T-Bank API не запускался из Claude Code.

---

# Отчёт после выполнения

После реализации напиши:

```text
Что изменено:
...

Где теперь лежит актуальный архив:
...

Где лежат timestamp-копии:
...

Что такое manifest:
...

Как проверить свежий архив:
...

Что проверено:
...

Что НЕ запускалось и почему:
...
```

В блоке "Что НЕ запускалось и почему" указать:

```text
T-Bank API и полный research pipeline не запускались из Claude Code. Изменения касаются только структуры архивации.
```
