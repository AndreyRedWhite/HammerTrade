# MVP-2.2: Backtest Exit/Time Filters v2

## Цель

Historical backtest validation живых/paper гипотез на SiM6 SELL (balanced).

Проверяются:
1. `exclude_hour_12` — исключить сигналы в 12:xx MSK
2. Более мягкие `max_hold_bars`: 10 / 15 (вместо 5 в текущем maxhold5)
3. Условный `max_hold` — conditional exit на баре 5 при слабом прогрессе
4. Entry confirmation proxies для ONE_BAR_STOP
5. Комбинированные сценарии (time_filter × exit_rule)

**Важно:** Этот MVP только backtest validation. Paper сервисы не менялись.

---

## Новые файлы

```text
src/backtest/exit_time_filters_v2.py    — ядро: conditional max_hold, run_backtest_v2, run_scenario_v2
src/backtest/exit_time_grid_v2.py       — оркестрация Phase A/B, Markdown report
scripts/backtest_exit_time_filters_v2.py — CLI
configs/backtest_exit_time_filters_v2_sim6_sell.yaml — конфиг
tests/test_exit_time_filters_v2.py      — 21 тест
docs/backtest_exit_time_filters_v2.md   — этот файл
```

---

## Как запустить

```bash
# Локально
python scripts/backtest_exit_time_filters_v2.py \
  --config configs/backtest_exit_time_filters_v2_sim6_sell.yaml

# На сервере
cd /opt/hammertrade
.venv/bin/python scripts/backtest_exit_time_filters_v2.py \
  --config configs/backtest_exit_time_filters_v2_sim6_sell.yaml
```

Артефакты:
```text
out/backtest_exit_time_filters_v2_SiM6_SELL_latest.csv
out/backtest_exit_time_filters_v2_trades_SiM6_SELL_latest.csv
reports/backtest_exit_time_filters_v2_SiM6_SELL_latest.md
```

---

## Данные и период

- Файл: `out/debug_simple_all.csv` (SiM6, 1m, balanced)
- Период: 2026-01-15 — 2026-04-09
- SELL сигналов: 114
- Параметры: take_r=1.0, slippage=0, stop_buffer=0, allow_overlap=False
- max_hold=None → hard cap 200 bars (без принудительного выхода по времени)

---

## Baseline (V2)

| Метрика | Значение |
|---------|----------|
| Сделок | 113 |
| Winrate | 82.3% |
| Net PnL | +19 754 руб |
| Profit Factor | 3.391 |
| Max Drawdown | 1 250 руб |
| Avg bars held | 5.4 |
| TAKE / STOP | 93 / 20 |
| Прибыльных дней | 83% (44/53) |

_Примечание: V2 baseline без cap на bars_held даёт +19754 vs +21024 в MVP-2.0 (где default_max_hold_bars=30).
Разница ≈1270 руб — часть timeout-выходов на баре 30 была выгодной._

---

## Результаты Phase A

### A1. Time filters

| Сценарий | Сделки | Net PnL | PF | Max DD | Прибыль. дней |
|---|---:|---:|---:|---:|---:|
| baseline | 113 | +19 754 | 3.391 | 1250 | 83% |
| exclude_hour_12 | 102 | +20 345 | 4.368 | 800 | 86% |
| exclude_hours_12_19_21 | 95 | +18 285 | 4.120 | 620 | 86% |
| exclude_hours_12_13_19_21 | 88 | +15 906 | 3.714 | 620 | 84% |

**Выводы:**
- `exclude_hour_12` улучшает PF (+0.977), снижает DD на 450 руб, прибыльных дней 86% vs 83%.
- Но skip 10% (11 сигналов) — риск переобучения умеренный.
- Расширение фильтра (19, 21, 13) заметно снижает net PnL: −1469 до −3849 руб.
- Рекомендация: `exclude_hour_12` — слабый кандидат (улучшение умеренное, риск переобучения есть).

### A2. Фиксированный max_hold

| Сценарий | Сделки | Net PnL | PF | Max DD | Take/Stop/Hold | Прибыль. дней |
|---|---:|---:|---:|---:|---|---:|
| baseline | 113 | +19 754 | 3.391 | 1250 | 93/20/0 | 83% |
| max_hold_5 | 114 | +22 624 | 7.772 | 620 | 82/8/24 | 94% |
| max_hold_10 | 114 | +21 734 | 4.715 | 1250 | 87/14/13 | 87% |
| max_hold_15 | 114 | +21 234 | 4.217 | 1250 | 92/17/5 | 85% |

**Выводы:**
- Все три max_hold улучшают baseline по PF и net PnL.
- `max_hold_5` лучший по PF (7.772) и net (+22624), снижает DD вдвое.
- `max_hold_10` баланс: PF 4.715, DD без изменений, avg_bars 3.3.
- `max_hold_5` срезает 3/7 large winners, но спасает 10 лузеров (+6560 руб saved).
- Историческое подтверждение: max_hold=5 работает. Текущий paper experiment обоснован.

### A3. Conditional max_hold

| Сценарий | Сделки | Net PnL | PF | Cond. exits | Срезано LW | Прибыль. дней |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 113 | +19 754 | 3.391 | — | — | 83% |
| hold5_exit_if_progress_lt_25pct | 114 | +21 144 | 4.872 | 15 | — | 91% |
| hold5_exit_if_progress_lt_50pct | 114 | +20 714 | 5.201 | 18 | — | 92% |
| hold5_exit_if_pnl_le_0 | 113 | +19 364 | 3.613 | 8 | — | 85% |
| hold5_exit_if_pnl_lt_10pts | 114 | +21 144 | 4.872 | 15 | — | 91% |

**Выводы:**
- Conditional max_hold лучше baseline по PF и net.
- `hold5_exit_if_progress_lt_50pct` лучший PF среди conditional (5.201).
- Значительно лучше сохраняют прибыльные дни: 91-92% vs 83% baseline.
- PnL ниже чем fixed max_hold_5, но потенциально меньше срезают large winners.
- `hold5_exit_if_pnl_le_0` слабейший: чуть хуже baseline по net PnL.

### A4. Entry confirmation proxies

| Сценарий | Сделки | Net PnL | PF | Max DD | Skip% |
|---|---:|---:|---:|---:|---:|
| baseline | 113 | +19 754 | 3.391 | 1250 | 0% |
| confirm_next_candle_direction | 83 | +17 566 | 4.253 | 1630 | 27% |
| confirm_breakout_confirmation | 113 | +19 754 | 3.391 | 1250 | 0% |

**Выводы:**
- `breakout_confirmation` идентичен baseline (движок уже использует breakout entry).
- `next_candle_direction`: PF улучшается, но net PnL −2188 и DD вырастает до 1630.
- Skip 27% (31 сигнал) — очень агрессивная фильтрация.
- ⚠️ Look-ahead risk: подтверждающая свеча (T+1) может быть той же свечой, где произошёл breakout entry.
- Вывод: entry confirmation в текущей реализации — не кандидат для paper.

---

## Результаты Phase B (лучшие)

Сетка all_hours/exclude_hour_12 × все exit rules:

| Сценарий | PF | Net PnL | Max DD |
|---|---:|---:|---:|
| B_exclude_hour_12_hold5_exit_if_progress_lt_50pct | 6.761 | +20685 | 1250 |
| B_exclude_hour_12_max_hold_10 | 6.302 | +21955 | 1250 |
| B_exclude_hour_12_max_hold_15 | 5.614 | +21255 | 1250 |
| B_all_hours_hold5_exit_if_progress_lt_50pct | 5.201 | +20714 | 1250 |
| B_all_hours_max_hold_10 | 4.715 | +21734 | 1250 |

---

## Что подтвердилось

1. **max_hold_bars=5 работает исторически**: PF 7.772, net +22624, DD снижен вдвое.
   Текущий paper experiment с maxhold5 обоснован исторически.

2. **max_hold_10 тоже хорош**: PF 4.715, net +21734, без потерь DD.
   Более консервативная альтернатива max_hold_5.

3. **exclude_hour_12 работает**: PF +0.977, DD −450 руб. Умеренное улучшение.

4. **Conditional max_hold работает**: Лучше baseline по PF и стабильности.
   `hold5_exit_if_progress_lt_50pct` — лучший conditional (PF 5.201).

5. **BIG_RISK сохранён**: max_hold сценарии не уничтожают large winners полностью.

---

## Что не подтвердилось

1. **Entry confirmation не улучшает**: next_candle_direction снижает net PnL и растит DD.
   Кроме того, есть look-ahead риск.

2. **Исключение 19, 21 часов не помогает**: net PnL снижается на 1469–3849 руб.

3. **max_hold_5 НЕ слишком агрессивен исторически**: Он действительно срезает 3/7 large winners,
   но суммарный эффект положительный (saved losers +6560 vs cut winners −2870).

---

## Large winners / cut winners

- Baseline large winners (≥500 руб): 7
- max_hold_5 срезает 3/7 (43%), но спасает 10 лузеров (+6560 руб)
- Conditional hold5_progress_lt_50pct срезает 2/7 (29%) — лучше по этому критерию
- max_hold_10 — промежуточный результат

---

## Conditional max_hold vs fixed max_hold_5

| Критерий | fixed max_hold_5 | conditional_progress_50pct |
|---|---|---|
| PF | **7.772** | 5.201 |
| Net PnL | **+22624** | +20714 |
| DD снижение | **−630 руб** | 0 |
| Large winners срезано | 3/7 | 2/7 |
| Прибыльных дней | **94%** | 92% |

**Вывод:** fixed max_hold_5 лучше по всем метрикам кроме "срезания победителей".
Conditional более осторожный выход, но хуже по net PnL и DD.

---

## Candidate for next paper experiment

### Сильные кандидаты

**`max_hold_5`** (уже запущен в maxhold5 service!)
- PF: 7.772 (исторически), live 1.61
- Backtest подтверждает правильность выбора
- Продолжать текущий A/B эксперимент

**`B_exclude_hour_12_hold5_exit_if_progress_lt_50pct`** (если maxhold5 покажет слабость)
- PF: 6.761, net: +20685, срезает 2/7 large winners
- Комбинация двух рабочих фильтров
- Требует отдельного paper experiment после закрытия текущего A/B

---

## Что НЕ было изменено

- `hammertrade-paper.service` — не тронут
- `hammertrade-paper-maxhold5.service` — не тронут
- HammerDetector, core candle logic, stop/take geometry
- Никаких real/sandbox orders

---

## Backward compatibility

Все 427 тестов проходят (`venv/bin/python -m pytest --tb=no -q`).
MVP-2.0 отчёты не затронуты.

---

## Conditional max_hold — реализация

```python
# At check_bar=5 (after stop/take priority):
progress_to_take_pct = (entry_price - current_close) / (entry_price - take_price) * 100
if progress_to_take_pct < min_progress_to_take_pct:
    exit at current_close, reason="conditional_max_hold_exit"

# PnL threshold:
pnl_points = entry_price - current_close  # for SELL
if pnl_points <= max_pnl_points:
    exit at current_close, reason="conditional_max_hold_exit"
```

Stop/take priority всегда выше conditional или timeout exit.
