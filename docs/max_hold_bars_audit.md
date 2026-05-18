# max_hold_bars Audit — документация (MVP-2.0a)

## Что это

Аудит результата `max_hold_bars=3,5` из MVP-2.0 Backtest Diagnostic Filters.

MVP-2.0 показал PF=14.8 (max_hold_3) и PF=7.8 (max_hold_5) vs PF=4.0 (baseline).
Перед включением в paper trader нужно убедиться, что результат корректен.

## Файлы

| Файл | Назначение |
|------|-----------|
| `src/backtest/max_hold_audit.py` | Модуль: loaders, matching, static audits, report builder |
| `scripts/audit_max_hold_bars.py` | CLI: запуск аудита, сохранение артефактов |
| `tests/test_max_hold_audit.py` | 23 теста |
| `docs/max_hold_bars_audit.md` | Этот файл |

## Быстрый запуск

```bash
# из директории проекта, с debug CSV (для OOS и slippage sensitivity):
.venv/bin/python scripts/audit_max_hold_bars.py \
  --summary-csv out/backtest_diagnostic_filters_SiM6_SELL_latest.csv \
  --trades-csv  out/backtest_diagnostic_trades_SiM6_SELL_latest.csv \
  --debug-csv   out/debug_simple_all.csv

# только на артефактах MVP-2.0 (без OOS и slippage re-run):
.venv/bin/python scripts/audit_max_hold_bars.py \
  --summary-csv out/backtest_diagnostic_filters_SiM6_SELL_latest.csv \
  --trades-csv  out/backtest_diagnostic_trades_SiM6_SELL_latest.csv \
  --skip-oos --skip-slippage
```

## Аргументы CLI

| Аргумент | По умолчанию | Описание |
|----------|-------------|----------|
| `--summary-csv` | `out/backtest_diagnostic_filters_SiM6_SELL_latest.csv` | Сводная таблица сценариев |
| `--trades-csv` | `out/backtest_diagnostic_trades_SiM6_SELL_latest.csv` | Trade-level данные |
| `--debug-csv` | `out/debug_simple_all.csv` | Сигналы для OOS и slippage |
| `--baseline-scenario` | `baseline` | Имя baseline сценария |
| `--scenario-a` | `max_hold_3` | Первый сценарий для сравнения |
| `--scenario-b` | `max_hold_5` | Второй сценарий для сравнения |
| `--group-by` | `month` | Период для статистики (`month` / `week`) |
| `--top-n` | `10` | Топ-N improvements/degradations |
| `--skip-oos` | — | Пропустить OOS re-run |
| `--skip-slippage` | — | Пропустить slippage sensitivity |

## Артефакты

```text
reports/max_hold_bars_audit_SiM6_SELL_YYYYMMDD_HHMMSS.md  ← детальный отчёт
reports/max_hold_bars_audit_SiM6_SELL_latest.md            ← latest copy
out/max_hold_bars_audit_trades_SiM6_SELL_YYYYMMDD_HHMMSS.csv
out/max_hold_bars_audit_trades_SiM6_SELL_latest.csv
out/max_hold_bars_audit_deltas_SiM6_SELL_YYYYMMDD_HHMMSS.csv
out/max_hold_bars_audit_deltas_SiM6_SELL_latest.csv
```

## Что проверяет аудит

### 1. Scenario consistency
Сравнение baseline / max_hold_3 / max_hold_5: trades, PF, max DD, winrate.
Объяснение разницы 113 vs 114 сделок.

### 2. Exit reason distribution
По каждому сценарию: take / stop / timeout — counts, net PnL, avg PnL, winrate.

### 3. Trade-level matching
Сопоставление сделок по `signal_time`. Для каждой пары — delta PnL и классификация:

| Классификация | Описание |
|--------------|---------|
| `SAME_RESULT` | Сделка не изменилась |
| `MAX_HOLD_SAVED_STOP` | Baseline=stop → max_hold=timeout, max_hold лучше |
| `MAX_HOLD_CUT_WINNER` | Baseline=take → max_hold=timeout, max_hold хуже |
| `MAX_HOLD_SMALLER_WIN` | Оба прибыльны, max_hold меньше |
| `MAX_HOLD_SMALLER_LOSS` | Оба убыточны, max_hold меньше |
| `MAX_HOLD_LARGER_LOSS` | Оба убыточны, max_hold хуже |
| `MAX_HOLD_CHANGED_EXIT` | Другой случай |
| `UNLOCKED_SIGNAL` | Сигнал был skipped в baseline, стал сделкой в max_hold |
| `UNMATCHED_BASELINE` | Сделка из baseline не найдена в max_hold |

### 4. Look-ahead bias
Статический анализ кода backtest engine.
- Выход по timeout: `df.iloc[actual_last]['close']` — close текущего бара, не будущего.
- `max_hold_bars` ограничивает диапазон поиска: все бары в диапазоне — прошлые/текущие.
- **Verdict: PASS**

### 5. Exit priority
- Priority 1: stop + take на одном баре → stop_same_bar (консервативно)
- Priority 2: только stop → stop
- Priority 3: только take → take
- Priority 4: нет stop/take в окне → timeout на close последнего бара
- max_hold не перетирает stop/take внутри своего окна.
- **Verdict: PASS**

### 6. Period stability
Monthly breakdown: Jan / Feb / Mar / Apr 2026.
Проверка: улучшает ли max_hold все месяцы или только один.

### 7. Out-of-sample check
Train: 2026-01-15 – 2026-03-31, Test: 2026-04-01 – 2026-04-09.
Требуется debug CSV (`out/debug_simple_all.csv`).
Предупреждение: test период ~21 сделка — LOW_SAMPLE.

### 8. Slippage sensitivity
baseline vs max_hold_5 при slippage_points = 0 / 1 / 2 / 5.
Требуется debug CSV.

### 9. Paper vs backtest equivalence
Анализ реализуемости max_hold_bars в paper trader:
- `bars_held` уже есть в SQLite state.
- Нужен новый config-параметр `max_hold_bars` (int | None, default None).
- Учесть market hours gap (clearing, overnight).
- **Verdict: READY_WITH_WARNINGS**

## Verdict

```text
PASS              — все проверки пройдены, нет критичных предупреждений
PASS_WITH_WARNINGS — корректно, но есть ограничения (малый OOS, market hours)
FAIL              — найден look-ahead, некорректный exit priority, или необъяснённое расхождение
```

## Главные находки (SiM6 SELL, 2026-01-15 – 2026-04-09)

- **113 vs 114 объяснено**: сигнал `2026-04-08 15:31:00` был заблокирован `allow_overlap=False`;
  при max_hold_3 предыдущая сделка (09:09) завершается на 3-м баре (15:13) вместо 30-го (15:40).
- **Механизм улучшения**: max_hold_3 конвертирует 14 stop-выходов в timeout (+7010 RUB),
  ценой обрезки 16 take-выходов (-5640 RUB). Net ≈ +1660 RUB.
- **Period stability**: max_hold улучшает PF в каждом месяце (Jan–Apr). Эффект не из одного периода.
- **OOS (April)**: ~21 сделка — LOW_SAMPLE. Направление верное, но не статистически значимо.
- **Look-ahead**: не обнаружен.
- **Exit priority**: корректен.

## Рекомендация для MVP-2.1

При verdict PASS или PASS_WITH_WARNINGS: **рекомендуемый кандидат — `max_hold_bars=5`**.

Почему 5, а не 3:
- max_hold_3 (PF=14.8) подозрительно агрессивен.
- max_hold_5 (PF=7.8) более консервативен и устойчив при slippage.

Реализация в MVP-2.1:
- Добавить `max_hold_bars: 5` как optional параметр paper trader config.
- Default: `null` (текущее поведение).
- Собрать 2–4 недели бумажных данных, затем сравнить.

> Правильная формулировка: max_hold_bars=5 можно проверить в следующем paper trading MVP
> как контролируемый эксперимент. Это не доказательство прибыльности и не основание для live trading.
