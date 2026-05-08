# Paper Trader Diagnostics

## Назначение

Аналитический инструмент для диагностики закрытых paper-trades.
Помогает выявить подозрительные сделки, оценить risk/reward по бакетам
и сформировать предварительные гипотезы для последующего backtest/grid.

Не меняет стратегию. Не влияет на работающий daemon.

## Источник данных

По умолчанию: `data/paper/paper_state.sqlite` (таблица `paper_trades`).

Если SQLite недоступен — CSV fallback: `out/paper/paper_trades_SiM6_SELL.csv`.

## Как запустить

```bash
# Базовый запуск с дефолтами
python scripts/paper_diagnostics.py

# С явными параметрами
python scripts/paper_diagnostics.py \
  --state-db data/paper/paper_state.sqlite \
  --ticker SiM6 \
  --direction SELL \
  --from 2026-05-04 \
  --to 2026-05-07 \
  --reports-dir reports \
  --out-dir out/paper
```

## Где лежат отчёты

| Файл | Описание |
|------|----------|
| `reports/paper_diagnostics_SiM6_SELL_YYYYMMDD_HHMMSS.md` | Markdown-отчёт с полной диагностикой |
| `reports/paper_diagnostics_SiM6_SELL_latest.md` | Последний отчёт (перезаписывается) |
| `out/paper/paper_trades_diagnostics_SiM6_SELL_YYYYMMDD_HHMMSS.csv` | Enriched CSV со всеми вычисленными полями |
| `out/paper/paper_trades_diagnostics_SiM6_SELL_latest.csv` | Последний enriched CSV (перезаписывается) |

## Как читать diagnostic_flags

Поле `diagnostic_flags` в enriched CSV и в отчёте — строка с флагами через `;`.

| Флаг | Условие |
|------|---------|
| `LOW_RR` | R/R < 0.8 |
| `TINY_TAKE` | reward_points < 5 |
| `BIG_RISK` | risk_points > 40 |
| `ONE_BAR_STOP` | exit_reason=STOP и bars_held ≤ 1 |
| `ONE_BAR_TAKE` | exit_reason=TAKE и bars_held ≤ 1 |
| `INVALID_RISK` | risk_points ≤ 0 |
| `INVALID_REWARD` | reward_points ≤ 0 |
| `UNKNOWN_DIRECTION` | direction не удалось определить |
| `MISSING_FIELDS` | отсутствуют обязательные поля |
| `OPEN_TRADE` | status = OPEN |
| `NO_EXIT_DATA` | status = CLOSED, но нет exit_price или exit_timestamp |

## Важное ограничение

Диагностика не меняет стратегию и не доказывает прибыльность.
Она помогает выбрать гипотезы для последующего backtest/grid.
Выборка мала — выводы предварительные.
