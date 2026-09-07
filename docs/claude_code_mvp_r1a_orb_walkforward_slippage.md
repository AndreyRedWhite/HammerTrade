# Claude Code Prompt — MVP-R1a: ORB Walk-Forward + May Data + Slippage Audit

## Контекст проекта

Проект: `HammerTrade / MOEXF`.

Это исследовательская платформа для торговых стратегий на MOEX futures через T-Bank Invest API.

Текущий сервер:

```text
Server: 158.160.204.201
User: vorontsov
Project path: /opt/hammertrade
Virtualenv: /opt/hammertrade/.venv
```

Текущие paper-сервисы:

```text
Baseline hammer:
  service: hammertrade-paper.service
  ticker: SiM6
  direction: SELL
  max_hold_bars: None
  db: data/paper/paper_state.sqlite
  status: runtime/paper_status_SiM6_SELL.json

Maxhold5 hammer:
  service: hammertrade-paper-maxhold5.service
  ticker: SiM6
  direction: SELL
  max_hold_bars: 5
  db: data/paper/paper_state_maxhold5.sqlite
  status: runtime/paper_status_SiM6_SELL_maxhold5.json
```

Важно:

```text
Текущие paper-сервисы НЕ трогать.
Не менять systemd.
Не запускать новые paper-сервисы.
Не запускать sandbox.
Не запускать real orders.
```

Этот MVP — только offline research / validation для новой стратегии Opening Range Breakout.

---

## Что уже сделано

## Hammer ветка

По live paper отчёту за 3 недели:

```text
Baseline:
  period: 2026-05-04 — 2026-05-29
  trades: 86
  PF: 1.01
  Net PnL: +55.70 RUB

Maxhold5:
  period: 2026-05-13 — 2026-05-29
  trades: 57
  PF: 1.19
  Net PnL: +867.15 RUB
```

Сравнение на общем окне May 13–29:

```text
Baseline:
  trades: 56
  PF: 0.886
  Net PnL: -862.80 RUB
  MaxDD: 3 231 RUB

Maxhold5:
  trades: 57
  PF: 1.186
  Net PnL: +867.15 RUB
  MaxDD: 1 120 RUB
```

Decision:

```text
Hammer maxhold5 = OBSERVE_ONLY.
Не развивать активно, но продолжать наблюдение до 60–70 сделок.
```

## MVP-2.3 Hour 12 Targeted Audit

Result:

```text
exclude_hour_12 помогает baseline,
но не помогает maxhold5.
Candidate decision: Weak candidate / observe more.
Overfit risk: HIGH.
Не запускать maxhold5 + exclude12 сейчас.
```

## MVP-2.3a Trading Liveness Guard

Готово:

```text
trading_liveness_status: OK / DEGRADED / STALLED
consecutive_api_errors
last_successful_fetch_at
market_open_since grace period
check_paper_status.py exit codes
paper_error_report.py liveness summary
```

## Rollover SiM6 → SiU6 plan

Готово:

```text
docs/rollover_siu6_plan.md
```

Важно:

```text
SiM6 expiration_date: 2026-06-19
SiU6 expiration_date: 2026-09-18
SiU6 технически готов, но пока менее ликвиден.
С 2026-06-02 мониторить ликвидность.
Крайняя дата переключения: около 2026-06-10.
```

---

## MVP-R1 — Opening Range Breakout Research — готово

Создана Strategy Research Lab и первая альтернативная стратегия ORB.

Ключевые результаты ORB на Jan 15 – Apr 9 2026:

```text
Top scenario:
  Opening range: 10:00–11:00 MSK
  Direction: SHORT
  Take R: 2.0
  Trades: 41
  Winrate: 53.7%
  Net PnL: +36 727 RUB
  PF: 1.639

Other strong scenarios:
  10:00–11:00 SHORT 1.5R:
    trades 41, PF 1.560, net +32 222 RUB

  10:00–11:00 LONG 2R:
    trades 36, PF 1.517, net +25 058 RUB

  10:00–11:00 LONG 1R:
    trades 36, PF 1.472, net +21 408 RUB
```

Observations:

```text
- Лучшее OR окно: 10:00–11:00.
- 15-минутный диапазон убыточен, median PF около 0.96.
- HIGH_VOL_TREND regime = очень сильный результат.
- ORB выглядит сильнее hammer maxhold5, но пока только offline / in-sample.
```

Ограничения MVP-R1:

```text
1. ORB обучен и протестирован на одном периоде Jan–Apr 2026.
2. Нет walk-forward.
3. May-данные не включены.
4. Slippage при breakout не учтён.
5. 36–41 сделок на сценарий — выборка тонкая.
```

Артефакты MVP-R1:

```text
reports/research_opening_range_breakout_SiM6_latest.md
out/research_opening_range_breakout_SiM6_latest.csv
out/research_opening_range_breakout_trades_SiM6_latest.csv
reports/hammer_decision_report_20260530_190737.md
```

---

# Главная цель MVP-R1a

Проверить, является ли ORB реальным кандидатом для будущего paper-эксперимента.

Нужно сделать:

```text
1. Загрузить / собрать May 2026 1m candles по SiM6.
2. Прогнать ORB на Jan–Apr как train/in-sample и May как out-of-sample.
3. Сделать walk-forward по месяцам и неделям.
4. Проверить slippage sensitivity.
5. Проверить regime breakdown.
6. Проверить, не держится ли результат на 1–2 днях.
7. Дать решение:
   - PAPER_CANDIDATE
   - NEEDS_MORE_DATA
   - REJECT
```

Этот MVP НЕ должен запускать ORB в paper/live.

---

# Жёсткие ограничения

Строго запрещено:

- менять `hammertrade-paper.service`;
- менять `hammertrade-paper-maxhold5.service`;
- менять current systemd units;
- менять current paper DB;
- сбрасывать state;
- удалять SQLite/CSV/reports/logs;
- менять HammerDetector;
- менять текущую hammer strategy logic;
- менять `max_hold_bars=5`;
- запускать ORB paper service;
- запускать sandbox orders;
- запускать real orders;
- менять `.env`;
- печатать токены;
- делать вывод “стратегия доказана”;
- обещать прибыль.

Разрешено:

- читать T-Bank API для historical candles;
- использовать токены из `.env`;
- добавлять read-only research modules;
- добавлять offline backtest scripts;
- создавать новые configs;
- читать existing paper DB/reports;
- создавать Markdown/CSV reports;
- добавлять tests;
- добавлять docs.

---

# Что изучить перед реализацией

Изучи существующие файлы MVP-R1:

```text
src/strategies/base.py
src/strategies/registry.py
src/strategies/opening_range_breakout/
src/research/
scripts/research_strategy.py
configs/research/opening_range_breakout_sim6.yaml
reports/research_opening_range_breakout_SiM6_latest.md
out/research_opening_range_breakout_SiM6_latest.csv
out/research_opening_range_breakout_trades_SiM6_latest.csv
```

Также проверь historical data loaders:

```text
src/tbank/
scripts/
data/raw/tbank/
```

Нужно понять:

```text
1. Где лежат Jan–Apr candles.
2. Есть ли May candles.
3. Как сейчас ORB получает candles.
4. Как считаются metrics.
5. Где лучше добавить walk-forward.
6. Как добавить slippage без ломки MVP-R1.
```

---

# Часть A — May 2026 data

## Цель

Получить 1m candles по SiM6 за период:

```text
2026-05-01 — 2026-05-30
```

или максимально доступный период May 2026.

Если есть gaps — явно указать.

## Требования

Добавить или использовать existing loader:

```text
scripts/load_research_candles.py
```

или расширить existing loader.

Желательные outputs:

```text
data/raw/tbank/SiM6_1m_20260501_20260530.csv
data/raw/tbank/SiM6_1m_20260115_20260409.csv
data/raw/tbank/SiM6_1m_20260115_20260530.csv
```

Если уже есть общий historical CSV — можно не дублировать, но отчёт должен явно указать source file.

## Data quality

Сделать lightweight data quality check:

```text
rows
first_timestamp
last_timestamp
trading_days
missing_day_count
duplicate_timestamp_count
zero_range_candles
OHLC validity
large gaps
```

Output:

```text
reports/research_data_quality_SiM6_1m_202605_latest.md
```

Если уже есть data quality tooling, переиспользовать.

---

# Часть B — ORB Walk-Forward

## Scenarios to validate

Не надо гонять бесконечный grid. Сфокусироваться на сценариях из MVP-R1:

```text
1. OR 10:00–11:00 SHORT take_2R
2. OR 10:00–11:00 SHORT take_1.5R
3. OR 10:00–11:00 LONG take_2R
4. OR 10:00–11:00 LONG take_1.0R
5. OR 10:00–11:00 BOTH take_2R if supported
```

Также include baseline variants:

```text
6. OR 10:00–10:30 SHORT take_2R
7. OR 10:00–11:00 SHORT take_1R
```

Но report должен держать фокус на top candidates.

## Period splits

Сделать:

```text
Train / in-sample:
  2026-01-15 — 2026-04-09

OOS / May:
  2026-05-01 — 2026-05-30

Full:
  2026-01-15 — 2026-05-30
```

Если Jan–Apr source differs from May source, нормализовать columns.

## Walk-forward by month

Периоды:

```text
Jan partial
Feb
Mar
Apr partial
May
```

For each:

```text
trades
net_pnl
PF
winrate
max_drawdown
best_trade
worst_trade
profitable_days_pct
```

## Walk-forward by week

Weekly breakdown:

```text
week_start
week_end
trades
net_pnl
PF
winrate
max_drawdown
```

Need answer:

```text
ORB works across periods or only one month/week?
May confirms or rejects Jan-Apr?
```

---

# Часть C — Slippage sensitivity

Breakout strategies are sensitive to execution.

Add slippage scenarios:

```text
0 pt
1 pt
2 pt
5 pt
10 pt
```

For long:

```text
entry worse by +slippage
exit worse:
  take/timeout sell worse by -slippage
  stop sell worse by -slippage
```

For short:

```text
entry worse by -slippage
exit buy worse:
  take/timeout buy worse by +slippage
  stop buy worse by +slippage
```

If current backtest has slippage model, reuse it.

Metrics per scenario and slippage:

```text
trades
net_pnl
PF
expectancy
maxDD
best/worst
slippage_destroyed_edge flag
```

Define:

```text
slippage_destroyed_edge = PF drops below 1.1 or net <= 0 at slippage <= 2 pt
```

Need answer:

```text
Does ORB survive 1–2 pt slippage?
Does it survive 5 pt slippage?
```

---

# Часть D — Regime validation

Use existing regime proxy from MVP-R1.

Regimes:

```text
LOW_VOL_RANGE
NORMAL
HIGH_VOL_TREND
NEWS_SHOCK_PROXY
```

For each candidate scenario, report:

```text
regime
trades
net_pnl
PF
winrate
avg_trade
maxDD
```

Need answer:

```text
Is ORB primarily a HIGH_VOL_TREND strategy?
Does it fail in LOW_VOL_RANGE?
Should ORB be enabled only under certain regime?
```

If regime classification is too rough, document limitations.

---

# Часть E — Concentration / robustness

For top scenarios:

```text
top 1 day contribution
top 3 days contribution
top 5 trades contribution
worst 3 trades
net without best day
net without best 3 trades
net without worst day
```

Need answer:

```text
Does result depend on one or two outlier days?
```

Flag:

```text
CONCENTRATION_HIGH
```

if:

```text
top 3 trades > 50% of total net
or best day > 40% of total net
```

---

# Часть F — Comparison with Hammer

Compare carefully:

```text
Hammer maxhold5 live paper:
  May 13–29
  trades 57
  PF 1.19
  net +867 RUB

ORB:
  historical Jan–Apr
  May OOS
  full Jan–May
```

Do NOT say ORB is better based only on historical.

Report should say:

```text
ORB is offline/historical.
Hammer is live paper.
Not apples-to-apples.
Next step, if ORB survives OOS/slippage, is paper experiment.
```

---

# Часть G — Output files

Create timestamped and latest outputs:

```text
reports/research_orb_walkforward_SiM6_YYYYMMDD_HHMMSS.md
reports/research_orb_walkforward_SiM6_latest.md

out/research_orb_walkforward_summary_SiM6_YYYYMMDD_HHMMSS.csv
out/research_orb_walkforward_summary_SiM6_latest.csv

out/research_orb_walkforward_trades_SiM6_YYYYMMDD_HHMMSS.csv
out/research_orb_walkforward_trades_SiM6_latest.csv

reports/research_data_quality_SiM6_1m_202605_latest.md
```

---

# Часть H — CLI

Add script:

```text
scripts/research_orb_walkforward.py
```

Example run:

```bash
python scripts/research_orb_walkforward.py \
  --config configs/research/opening_range_breakout_sim6_walkforward.yaml
```

Config:

```text
configs/research/opening_range_breakout_sim6_walkforward.yaml
```

Example config:

```yaml
experiment:
  name: opening_range_breakout_sim6_walkforward
  ticker: SiM6
  class_code: SPBFUT
  timeframe: 1m
  timezone: Europe/Moscow

data:
  train_csv: data/raw/tbank/SiM6_1m_20260115_20260409.csv
  oos_csv: data/raw/tbank/SiM6_1m_20260501_20260530.csv
  full_csv: data/raw/tbank/SiM6_1m_20260115_20260530.csv
  allow_api_load_if_missing: true

periods:
  train:
    from: "2026-01-15"
    to: "2026-04-09"
  oos:
    from: "2026-05-01"
    to: "2026-05-30"
  full:
    from: "2026-01-15"
    to: "2026-05-30"

scenarios:
  - name: or_60_short_2r
    opening_range: ["10:00", "11:00"]
    direction: short
    take_r: 2.0
  - name: or_60_short_1_5r
    opening_range: ["10:00", "11:00"]
    direction: short
    take_r: 1.5
  - name: or_60_long_2r
    opening_range: ["10:00", "11:00"]
    direction: long
    take_r: 2.0
  - name: or_60_long_1r
    opening_range: ["10:00", "11:00"]
    direction: long
    take_r: 1.0
  - name: or_60_both_2r
    opening_range: ["10:00", "11:00"]
    direction: both
    take_r: 2.0
  - name: or_30_short_2r
    opening_range: ["10:00", "10:30"]
    direction: short
    take_r: 2.0
  - name: or_60_short_1r
    opening_range: ["10:00", "11:00"]
    direction: short
    take_r: 1.0

slippage_points:
  - 0
  - 1
  - 2
  - 5
  - 10

exit:
  time_exit: "18:40"
  max_trades_per_day: 1
  no_overnight: true
```

---

# Часть I — Report structure

Markdown report in Russian:

```markdown
# ORB Walk-Forward + May OOS + Slippage Audit — SiM6

## Цель

## Краткий вывод

## Источники данных и data quality

## Сценарии

## Train Jan–Apr results

## May OOS results

## Full Jan–May results

## Walk-forward by month

## Walk-forward by week

## Slippage sensitivity

## Regime breakdown

## Concentration / robustness

## Comparison with Hammer maxhold5

## Candidate decision

## Warnings and limitations

## Recommendation

## Next MVP
```

---

# Candidate decision rules

Output one of:

```text
PAPER_CANDIDATE
NEEDS_MORE_DATA
REJECT
```

## PAPER_CANDIDATE

Only if:

```text
May OOS PF >= 1.25
May OOS net > 0
slippage 1–2 pt still PF > 1.1
result not concentrated in 1–2 trades/days
regime story makes sense
```

## NEEDS_MORE_DATA

If:

```text
Jan-Apr strong but May weak/too few trades
or slippage weakens but not destroys
or regime dependency is strong but plausible
```

## REJECT

If:

```text
May OOS net <= 0
or May OOS PF < 1.0
or slippage 1–2 pt destroys edge
or result depends on one outlier day
```

Important:

```text
Even PAPER_CANDIDATE does NOT mean start live/sandbox.
It means: consider future controlled paper service after rollover.
```

---

# Tests

Add tests:

```text
tests/test_orb_walkforward.py
tests/test_orb_slippage.py
tests/test_orb_robustness.py
```

Minimum tests:

## Walk-forward

```text
1. Month split works.
2. Week split works.
3. Train/OOS split works.
4. Missing May CSV triggers loader or clear error.
5. Summary rows include period label.
```

## Slippage

```text
1. Long entry worsens with positive slippage.
2. Short entry worsens with positive slippage.
3. Long exit worsens correctly.
4. Short exit worsens correctly.
5. Slippage can turn PF below threshold.
```

## Robustness

```text
1. Top trades contribution calculated correctly.
2. Best day contribution calculated correctly.
3. Concentration flag works.
4. Empty trades does not crash.
```

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_orb_walkforward.py \
  tests/test_orb_slippage.py \
  tests/test_orb_robustness.py
```

If feasible:

```bash
.venv/bin/python -m pytest
```

---

# Service safety checks

After implementation, verify:

```bash
sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager

.venv/bin/python scripts/check_paper_status.py \
  --status-file runtime/paper_status_SiM6_SELL.json

.venv/bin/python scripts/check_paper_status.py \
  --status-file runtime/paper_status_SiM6_SELL_maxhold5.json
```

Expected:

```text
baseline: active, liveness OK, max_hold_bars=None
maxhold5: active, liveness OK, max_hold_bars=5
```

---

# Acceptance Criteria

MVP-R1a is done if:

1. May 2026 SiM6 1m candles loaded or clear limitation reported.
2. Data quality report created.
3. ORB top scenarios from MVP-R1 re-tested on Jan–Apr train.
4. ORB tested on May OOS.
5. ORB tested on full Jan–May.
6. Walk-forward monthly stats produced.
7. Walk-forward weekly stats produced.
8. Slippage sensitivity 0/1/2/5/10 pt produced.
9. Regime breakdown produced.
10. Concentration/robustness analysis produced.
11. Comparison with hammer maxhold5 included.
12. Candidate decision produced.
13. No current paper service changed.
14. Tests pass.
15. Claude final answer includes:
    - files created/changed;
    - data source;
    - train result;
    - May OOS result;
    - slippage result;
    - candidate decision;
    - service status.

---

# What NOT to do

Do not start ORB paper service.

Do not start sandbox.

Do not start real trading.

Do not auto-select ORB as winner.

Do not modify current systemd units.

Do not alter hammer services.

Do not change `.env`.

Do not print tokens.

Do not claim profitability.

Do not implement news NLP.

Do not implement Telegram notifications.

---

# Финальный формат ответа Claude Code

```markdown
## MVP-R1a ORB Walk-Forward + Slippage Audit — готово

### Что сделано

### Созданные файлы

### Изменённые файлы

### Data source / May candles

### Data quality

### Train Jan–Apr results

### May OOS results

### Full Jan–May results

### Walk-forward by month

### Walk-forward by week

### Slippage sensitivity

### Regime breakdown

### Concentration / robustness

### Comparison with Hammer maxhold5

### Candidate decision

### Что НЕ было изменено

### Tests / smoke checks

### Service status

### Артефакты

### Warnings / limitations

### Рекомендация
```
