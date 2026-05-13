# Backtest Diagnostic Filters (MVP-2.0)

## Назначение

Historical validation диагностических фильтров, выявленных в paper trading.

Проверяет на исторических данных, улучшают ли backtest следующие фильтры:
- `MIN_REWARD_POINTS` — минимальный ожидаемый reward
- `MIN_RR` — минимальный R/R ratio (= take_r в текущей архитектуре)
- Time filters — фильтрация по часу входа в MSK
- Max hold bars — ограничение времени удержания позиции
- Entry confirmation — подтверждение направления через следующую свечу

**Важно:** Этот модуль не меняет paper trader, не включает фильтры в live execution.

## Как запустить

```bash
# Базовый запуск с дефолтами
python scripts/backtest_diagnostic_filters.py

# С явным конфигом
python scripts/backtest_diagnostic_filters.py \
  --config configs/backtest_diagnostic_filters_sim6_sell.yaml

# С переопределением периода
python scripts/backtest_diagnostic_filters.py \
  --config configs/backtest_diagnostic_filters_sim6_sell.yaml \
  --from 2026-03-01 \
  --to 2026-04-09 \
  --ticker SiM6 \
  --direction SELL
```

## Созданные артефакты

| Файл | Описание |
|------|----------|
| `out/backtest_diagnostic_filters_SiM6_SELL_YYYYMMDD_HHMMSS.csv` | Сводная таблица по всем сценариям |
| `out/backtest_diagnostic_filters_SiM6_SELL_latest.csv` | Последний результат (перезаписывается) |
| `out/backtest_diagnostic_trades_SiM6_SELL_YYYYMMDD_HHMMSS.csv` | Все сделки по всем сценариям |
| `out/backtest_diagnostic_trades_SiM6_SELL_latest.csv` | Последний trades CSV |
| `reports/backtest_diagnostic_filters_SiM6_SELL_YYYYMMDD_HHMMSS.md` | Полный Markdown отчёт |
| `reports/backtest_diagnostic_filters_SiM6_SELL_latest.md` | Последний отчёт |

## Структура Phase A / Phase B

### Phase A — однофакторный анализ

Каждый фильтр тестируется отдельно против baseline:
- baseline (без фильтров)
- min_reward_points = 5, 6, 8
- min_rr = 0.8, 0.9 (при take_r=1.0 не фильтрует — см. ограничение ниже)
- time_filter: exclude_bad_paper_hours, only_good_paper_hours
- max_hold_bars = 3, 5, 10
- entry_confirmation: next_candle_direction, breakout_confirmation

### Phase B — комбинированные сценарии

Сетка: `min_reward × min_rr × time_filter`.

## Ограничение MIN_RR

В текущей архитектуре backtest (breakout entry, без slippage):

```
expected_rr = take_r  (для всех сигналов)
```

Потому что:
- `entry_price_raw = signal_low` (для SELL)
- `stop_price = signal_high + stop_buffer`
- `risk_points = stop_price - entry_price_raw`
- `reward_points = risk_points × take_r`
- `rr = reward / risk = take_r`

При `take_r=1.0`, `rr=1.0` для всех сигналов.  
Поэтому `min_rr <= 1.0` никогда не фильтрует ни одну сделку.

Это корректное поведение модели, а не ошибка.

## Диагностические флаги в Phase A

| Флаг paper trading | Гипотеза | Как проверяется в backtest |
|--------------------|---------|---------------------------|
| `TINY_TAKE` | reward < 5 pt → плохие сделки | `min_reward_points >= 5` |
| `LOW_RR` | rr < 0.8 → убыточные | `min_rr >= 0.8` (N/A при take_r=1.0) |
| `ONE_BAR_STOP` | ранние стопы → потери | `entry_confirmation=next_candle_direction` |
| `BARS_001 > BARS_002_003` | удержание >1 бара ухудшает | `max_hold_bars = 1, 3, 5` |

## Метрики в summary CSV

```
scenario_id, scenario_name,
min_reward_points, min_rr, time_filter_name, exclude_hours_msk, include_hours_msk,
max_hold_bars, entry_confirmation,
n_original_signals, n_after_filters, n_filtered_signals, skip_rate_pct,
trades, wins, losses, winrate_pct,
gross_profit_rub, gross_loss_rub, net_pnl_rub,
profit_factor, expectancy_rub, avg_trade_rub, median_trade_rub,
best_trade_rub, worst_trade_rub,
max_drawdown_rub, max_drawdown_pct,
avg_risk_points, avg_reward_points, avg_rr, avg_bars_held,
take_count, stop_count, timeout_count,
periods_count, profitable_periods_count, profitable_periods_pct,
worst_period_pnl, best_period_pnl, avg_period_pnl,
is_low_sample, risk_adjusted_score, warnings
```

## Важное ограничение

MVP-2.0 — исторический validation, не доказательство прибыльности.

Корректная формулировка:

> Scenario X улучшил исторический backtest относительно baseline и может быть кандидатом для следующего paper trading MVP. Перед live trading необходима проверка в paper режиме на новых данных.
