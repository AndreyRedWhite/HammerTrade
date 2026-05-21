# Claude Code Prompt — MVP-2.2: Backtest Exit/Time Filters v2

## Контекст проекта

Проект: `HammerTrade / MOEXF`.

Это исследовательский trading/paper-trading бот для MOEX futures.

Текущий основной инструмент:

```text
Ticker: SiM6
Class code: SPBFUT
Timeframe: 1m
Profile: balanced
Direction filter: SELL
Mode: paper only
Orders: disabled
```

Проект работает на сервере Yandex Cloud:

```text
Server: 158.160.204.201
User: vorontsov
Project path: /opt/hammertrade
Virtualenv: /opt/hammertrade/.venv
Baseline service: hammertrade-paper.service
Maxhold5 service: hammertrade-paper-maxhold5.service
Baseline DB: data/paper/paper_state.sqlite
Maxhold5 DB: data/paper/paper_state_maxhold5.sqlite
Baseline status: runtime/paper_status_SiM6_SELL.json
Maxhold5 status: runtime/paper_status_SiM6_SELL_maxhold5.json
```

Важно: сейчас идёт A/B paper experiment:

```text
baseline: max_hold_bars=None
maxhold5: max_hold_bars=5
```

Оба сервиса живые. В этом MVP нельзя менять работающие сервисы и нельзя включать новые фильтры в paper trader.

---

## Что уже сделано

## MVP-1.7 — Paper trading daemon

```text
scripts/run_paper_trader.py
src/paper/engine.py
src/paper/repository.py
src/paper/report.py
data/paper/paper_state.sqlite
out/paper/paper_trades_SiM6_SELL.csv
```

## MVP-1.8 — Operational Safety Layer

```text
configs/market_hours/moex_futures.yaml
src/market/market_hours.py
scripts/check_paper_status.py
runtime/paper_status_SiM6_SELL.json
docs/paper_trader_operational.md
```

## MVP-1.9 — Paper diagnostics

```text
src/paper/diagnostics.py
scripts/paper_diagnostics.py
tests/test_paper_diagnostics.py
docs/paper_trader_diagnostics.md
```

## MVP-2.0 — Backtest Diagnostic Filters

```text
src/backtest/diagnostic_filters.py
src/backtest/diagnostic_grid.py
scripts/backtest_diagnostic_filters.py
configs/backtest_diagnostic_filters_sim6_sell.yaml
tests/test_backtest_diagnostic_filters.py
docs/backtest_diagnostic_filters.md
```

MVP-2.0 showed:

```text
max_hold_3 and max_hold_5 looked very strong on Jan–Apr historical data.
```

## MVP-2.0a — Audit max_hold_bars

```text
src/backtest/max_hold_audit.py
scripts/audit_max_hold_bars.py
tests/test_max_hold_audit.py
docs/max_hold_bars_audit.md
```

Audit result:

```text
Look-ahead audit: PASS
Exit priority audit: PASS
Paper readiness: READY_WITH_WARNINGS
Verdict: PASS_WITH_WARNINGS
```

## MVP-2.1 — Parallel paper maxhold5 experiment

```text
hammertrade-paper.service
hammertrade-paper-maxhold5.service
scripts/compare_paper_experiments.py
tests/test_paper_max_hold.py
```

## MVP-2.1a — Empty candles handling

```text
scripts/run_paper_trader.py
src/paper/status.py
scripts/check_paper_status.py
scripts/paper_error_report.py
tests/test_empty_candles_handling.py
docs/paper_empty_candles_handling.md
```

`EMPTY_CANDLES_RESPONSE` now handled safely:

```text
does not create candle
does not create signal
does not increase bars_held
does not trigger MAX_HOLD_EXIT
does not close open trade
```

---

## Свежий live/paper diagnostic report на 2026-05-21

Baseline:

```text
Period: 2026-05-04 — 2026-05-21
Closed trades: 55
Net PnL: +2497 RUB
PF: 1.50
Winrate: 65.5%
Expectancy: +45.4 RUB/trade
Avg bars held: 4.1
Worst trade: -690 RUB
```

Maxhold5:

```text
Period: 2026-05-13 — 2026-05-21
Closed trades: 26
Net PnL: +1069 RUB
PF: 1.61
Winrate: 65.4%
Expectancy: +41.1 RUB/trade
Avg bars held: 2.9
Worst trade: -690 RUB
```

Comparable period since 2026-05-13:

```text
baseline: 25 trades, +1580 RUB
maxhold5: 26 trades, +1069 RUB
```

Conclusion:

```text
Baseline currently beats maxhold5 on comparable live/paper sample.
maxhold5 is not clearly better anymore.
```

---

## Key live/paper observations

## 1. `max_hold_bars=5` is too aggressive

Maxhold5 `MAX_HOLD_EXIT` summary:

```text
MAX_HOLD_EXIT:
  trades: 9
  winrate: 44%
  net: -60 RUB
  PF: 0.88
```

Important examples:

```text
2026-05-19 09:03
baseline: TAKE +800, 10 bars
maxhold5: MAX_HOLD_EXIT +20, 5 bars
delta maxhold5 vs baseline: -780

2026-05-20 13:40
baseline: TAKE +820, 17 bars
maxhold5: MAX_HOLD_EXIT -150, 5 bars
delta maxhold5 vs baseline: -970

2026-05-20 14:49
baseline: STOP -640, 11 bars
maxhold5: MAX_HOLD_EXIT -180, 5 bars
delta maxhold5 vs baseline: +460
```

Conclusion:

```text
max_hold_bars=5 sometimes saves losers,
but cuts large winners too early.
Need to backtest softer exits:
- max_hold_bars = 10
- max_hold_bars = 15
- conditional max_hold
```

---

## 2. `hour 12 MSK` looks toxic

Baseline by hour:

```text
12:xx MSK:
  trades: 3
  winrate: 0%
  net: -1340 RUB
  PF: 0.00
```

This pattern has appeared repeatedly in previous reports.

Conclusion:

```text
exclude_hour_12 is now a strong candidate for backtest validation.
```

But risk:

```text
Time filters can overfit strongly.
Need historical validation and period stability.
```

---

## 3. `ONE_BAR_STOP` remains main entry-quality problem

Baseline diagnostic flags:

```text
ONE_BAR_STOP:
  trades: 7
  net: -1150 RUB
  PF: 0.00
```

Conclusion:

```text
Need to backtest confirmation/entry-quality filters that could reduce one-bar stops.
But ONE_BAR_STOP is post-factum, so we must test observable pre-entry proxies.
```

---

## 4. `BIG_RISK` changed interpretation

Baseline diagnostic flags:

```text
BIG_RISK:
  trades: 10
  net: +1690 RUB
  PF: 1.71
```

Important:

```text
Top-5 best baseline trades are all BIG_RISK.
Large candle patterns with wider stops are now a major source of profit.
```

Conclusion:

```text
Do NOT treat BIG_RISK as a bad filter.
Do NOT add max_risk_points as primary risk filter.
Do NOT cut large hammers just because stop is wide.
```

This is important because the original strategy is built around strong candle reversal patterns.

---

## 5. Core strategy must stay unchanged

Core strategy:

```text
Hammer / inverted hammer / upper wick reversal pattern on MOEX futures.
Small body + long shadow / wick.
Candle geometry based reversal signal.
Current paper mode focuses on SiM6 SELL side.
```

Current MVP must not change:

```text
HammerDetector
core candle pattern logic
entry signal source
stop/take geometry
direction filter
```

This MVP works only with:

```text
historical validation
exit rules
time filters
entry confirmation proxies
diagnostics
```

---

## Главная цель MVP-2.2

Сделать historical backtest validation новых live/paper гипотез:

1. `exclude_hour_12`
2. softer `max_hold_bars`: 10 / 15
3. conditional `max_hold` instead of fixed `5`
4. entry confirmation proxies for `ONE_BAR_STOP`
5. combined scenarios that do not destroy large winners / BIG_RISK patterns

Это НЕ внедрение в paper trader.

Это НЕ изменение работающих сервисов.

---

## Жёсткие ограничения

Строго запрещено:

- менять `hammertrade-paper.service`;
- менять `hammertrade-paper-maxhold5.service`;
- перезапускать сервисы без необходимости;
- менять текущий A/B experiment;
- менять `max_hold_bars=5` в maxhold5 service;
- включать новые фильтры в paper trader;
- менять HammerDetector;
- менять core candle pattern logic;
- менять entry signal source;
- менять stop/take geometry;
- менять `.env`;
- печатать токены;
- удалять SQLite/CSV/reports;
- запускать real trading;
- запускать sandbox orders;
- делать вывод “стратегия доказана”.

Разрешено:

- добавлять backtest-only experimental modules;
- добавлять configs для backtest experiments;
- читать historical candles/debug CSV;
- читать existing diagnostic artifacts;
- создавать CSV/Markdown reports;
- добавлять tests;
- добавлять docs;
- переиспользовать MVP-2.0 diagnostic grid;
- добавлять new scenario types in backtest layer only.

---

## Что изучить перед реализацией

Изучи:

```text
src/backtest/diagnostic_filters.py
src/backtest/diagnostic_grid.py
scripts/backtest_diagnostic_filters.py
configs/backtest_diagnostic_filters_sim6_sell.yaml
src/backtest/max_hold_audit.py
scripts/audit_max_hold_bars.py
src/paper/diagnostics.py
out/debug_simple_all.csv
out/backtest_diagnostic_filters_SiM6_SELL_latest.csv
out/backtest_diagnostic_trades_SiM6_SELL_latest.csv
reports/backtest_diagnostic_filters_SiM6_SELL_latest.md
reports/max_hold_bars_audit_SiM6_SELL_latest.md
```

Нужно понять:

1. Как сейчас реализован `max_hold_bars` в backtest.
2. Как считается `bars_held`.
3. Как определяется `exit_reason`.
4. Какие поля есть в `out/debug_simple_all.csv`.
5. Есть ли signal candle OHLC:
   - signal open
   - signal high
   - signal low
   - signal close
   - body size
   - upper/lower wick
   - range
   - entry price
   - stop
   - take
6. Можно ли реализовать conditional max_hold на основе доступных данных.
7. Можно ли реализовать confirmation proxies without look-ahead.
8. Есть ли MSK hour conversion already.
9. Есть ли period stability helpers.

---

## Предпочтительная структура новых файлов

Можно расширить MVP-2.0 или создать v2.

Желательная структура:

```text
src/backtest/exit_time_filters_v2.py
src/backtest/exit_time_grid_v2.py
scripts/backtest_exit_time_filters_v2.py
configs/backtest_exit_time_filters_v2_sim6_sell.yaml
tests/test_exit_time_filters_v2.py
docs/backtest_exit_time_filters_v2.md
```

Если лучше расширить существующие `diagnostic_filters.py` / `diagnostic_grid.py`, можно, но не ломать MVP-2.0 reports.

---

## Config

Создать конфиг:

```text
configs/backtest_exit_time_filters_v2_sim6_sell.yaml
```

Пример:

```yaml
experiment:
  name: "mvp22_exit_time_filters_v2_sim6_sell"
  ticker: "SiM6"
  class_code: "SPBFUT"
  timeframe: "1m"
  profile: "balanced"
  direction: "SELL"

data:
  signals_csv: "out/debug_simple_all.csv"
  trades_csv: "out/backtest_diagnostic_trades_SiM6_SELL_latest.csv"

date_range:
  from: "2026-01-15"
  to: "2026-05-21"

baseline:
  scenario_name: "baseline"

filters:
  time_filters:
    - name: "all_hours"
      exclude_hours_msk: []
    - name: "exclude_hour_12"
      exclude_hours_msk: [12]
    - name: "exclude_hours_12_19_21"
      exclude_hours_msk: [12, 19, 21]
    - name: "exclude_hours_12_13_19_21"
      exclude_hours_msk: [12, 13, 19, 21]

  max_hold:
    - name: "no_max_hold"
      max_hold_bars: null
    - name: "max_hold_5"
      max_hold_bars: 5
    - name: "max_hold_10"
      max_hold_bars: 10
    - name: "max_hold_15"
      max_hold_bars: 15

  conditional_max_hold:
    - name: "none"
      enabled: false
    - name: "hold5_exit_if_progress_lt_25pct"
      enabled: true
      check_bar: 5
      min_progress_to_take_pct: 25
    - name: "hold5_exit_if_progress_lt_50pct"
      enabled: true
      check_bar: 5
      min_progress_to_take_pct: 50
    - name: "hold5_exit_if_pnl_le_0"
      enabled: true
      check_bar: 5
      max_pnl_points: 0
    - name: "hold5_exit_if_pnl_lt_10pts"
      enabled: true
      check_bar: 5
      max_pnl_points: 10

  entry_confirmation:
    - name: "baseline"
    - name: "next_candle_direction"
    - name: "breakout_confirmation"
    - name: "skip_if_next_candle_against_signal"

reporting:
  min_trades_required: 30
  top_n: 20
```

Adapt structure to existing config style if needed.

---

## Scenarios to test

## Phase A — single-factor analysis

Test each family separately vs baseline.

### A1. Time filters

Scenarios:

```text
baseline all hours
exclude_hour_12
exclude_hours_12_19_21
exclude_hours_12_13_19_21
```

Need answer:

```text
Does excluding 12 MSK improve historical backtest?
Is effect stable by month/week?
Does it remove too many trades?
Is it overfit?
```

Important:

```text
12 MSK is a strong live/paper candidate,
but time filters are high-overfit-risk.
```

---

### A2. Fixed max_hold bars

Scenarios:

```text
no max hold
max_hold_5
max_hold_10
max_hold_15
```

Need answer:

```text
Is 5 too aggressive historically too?
Do 10/15 preserve large winners better?
Which value improves PF/drawdown without cutting net PnL?
```

Important metrics:

```text
MAX_HOLD_EXIT count
MAX_HOLD_EXIT net
number of cut winners
number of saved losers
delta vs baseline
large winners cut count
```

---

### A3. Conditional max_hold

This is key.

Test softer logic:

## Progress-to-take logic

For SELL:

```text
progress_to_take_pct = (entry_price - current_close) / (entry_price - take_price) * 100
```

At `check_bar = 5`:

```text
if progress_to_take_pct < threshold:
    exit by CONDITIONAL_MAX_HOLD_EXIT at current close
else:
    keep original trade alive
```

Thresholds:

```text
25%
50%
```

For BUY, mirror logic if BUY supported.

Goal:

```text
Do not cut trades that are already moving strongly toward take.
Cut only stale/weak trades.
```

## PnL threshold logic

At `check_bar = 5`:

```text
if current_pnl_points <= 0:
    exit

if current_pnl_points < 10:
    exit
```

Goal:

```text
Exit weak trades, keep winners alive.
```

Need answer:

```text
Does conditional max_hold beat fixed max_hold_5?
Does it preserve big winners from 19/20 May-like cases?
Does it still reduce stops?
```

---

### A4. Entry confirmation proxies for ONE_BAR_STOP

ONE_BAR_STOP is post-factum. Need test observable proxies.

Scenarios:

```text
baseline
next_candle_direction
breakout_confirmation
skip_if_next_candle_against_signal
```

Definitions:

## next_candle_direction

For SELL:

```text
allow entry only if confirmation candle is bearish:
next_close < next_open
```

Alternative if project already uses different definition:

```text
next_close < signal_close
```

Use one clear definition and document it.

## breakout_confirmation

For SELL:

```text
allow entry only if price breaks below signal low / breakout level
```

If current baseline already uses breakout entry, scenario may equal baseline. If so, document.

## skip_if_next_candle_against_signal

For SELL:

```text
skip if next candle closes above its open
```

or equivalent.

Important:

```text
Do not introduce look-ahead incorrectly.
If scenario waits for next candle, entry must shift to next actionable bar.
Do not pretend entry happened at old price after seeing next candle.
```

If correct simulation requires entry delay, implement with delayed entry or mark unsupported.

Need answer:

```text
Can confirmation reduce one-bar stops without killing winners?
```

---

## Phase B — combined scenarios

After Phase A, run small combined grid.

Suggested combinations:

```text
time_filter:
  all_hours
  exclude_hour_12

exit:
  no_max_hold
  max_hold_10
  max_hold_15
  conditional_hold5_progress_lt_25pct
  conditional_hold5_progress_lt_50pct
  conditional_hold5_pnl_le_0
  conditional_hold5_pnl_lt_10pts

entry_confirmation:
  baseline
  best_supported_confirmation
```

Keep grid small and readable.

Do not include too many time filters in Phase B to avoid overfitting.

---

## Metrics for each scenario

For each scenario calculate:

```text
scenario_id
scenario_name
filters_json
trades
wins
losses
winrate_pct
gross_profit_rub
gross_loss_rub
net_pnl_rub
profit_factor
expectancy_rub
avg_trade_rub
median_trade_rub
best_trade_rub
worst_trade_rub
max_drawdown_rub
avg_risk_points
avg_reward_points
avg_rr
avg_bars_held
take_count
stop_count
max_hold_exit_count
conditional_max_hold_exit_count
timeout_count
skipped_signals
skip_rate_pct
large_winners_count
large_winners_cut_count
saved_losers_count
cut_winners_rub
saved_losers_rub
```

Definitions:

```text
large_winner = baseline pnl_rub >= 500
large_loser = baseline pnl_rub <= -500
saved_loser = baseline <= -300 and scenario pnl > baseline pnl
cut_winner = baseline >= +300 and scenario pnl < baseline pnl
```

These thresholds can be adjusted if project already has conventions.

---

## Stability checks

Do not only rank by total PnL.

Add:

```text
monthly stats
weekly stats
profitable_days_pct
profitable_weeks_pct
worst_day_pnl
best_day_pnl
avg_day_pnl
periods_count
LOW_SAMPLE flag
```

Need to answer:

```text
Does scenario improve all months or only one?
Does exclude_hour_12 help across months?
Does conditional max_hold avoid overfitting?
```

---

## Ranking

Rank scenarios by:

1. Net PnL
2. Profit Factor with minimum trade count
3. Max drawdown reduction
4. Risk-adjusted score

Use transparent score:

```text
score = net_pnl_rub - 0.5 * abs(max_drawdown_rub)
```

or existing project score if available.

Also compute:

```text
trades_retained_pct vs baseline
```

Reject/flag scenarios where:

```text
trades < min_trades_required
trades_retained_pct < 60%
```

unless explicitly discussed.

---

## Output files

Create timestamped artifacts:

```text
out/backtest_exit_time_filters_v2_SiM6_SELL_YYYYMMDD_HHMMSS.csv
out/backtest_exit_time_filters_v2_trades_SiM6_SELL_YYYYMMDD_HHMMSS.csv
reports/backtest_exit_time_filters_v2_SiM6_SELL_YYYYMMDD_HHMMSS.md
```

Also latest copies:

```text
out/backtest_exit_time_filters_v2_SiM6_SELL_latest.csv
out/backtest_exit_time_filters_v2_trades_SiM6_SELL_latest.csv
reports/backtest_exit_time_filters_v2_SiM6_SELL_latest.md
```

---

## Markdown report structure

Report language: Russian.

Structure:

```markdown
# Backtest Exit/Time Filters v2 — SiM6 SELL

## Цель

## Источник данных

## Baseline

## Live/paper observations being tested

## Phase A — Time filters

## Phase A — Fixed max_hold

## Phase A — Conditional max_hold

## Phase A — Entry confirmation proxies

## Phase B — Combined scenarios

## Top scenarios by Net PnL

## Top scenarios by Profit Factor

## Top scenarios by Drawdown reduction

## Large winners / cut winners analysis

## Saved losers analysis

## Period stability

## Comparison with current live/paper A/B

## Rejected scenarios

## Candidate for next paper experiment

## Warnings and limitations

## Recommendation
```

---

## Required report answers

Report must answer:

1. Does `exclude_hour_12` improve historical result?
2. Is `exclude_hour_12` stable by month/week?
3. Does `exclude_hour_12` look overfit?
4. Is fixed `max_hold_5` too aggressive historically?
5. Are `max_hold_10` or `max_hold_15` better than `5`?
6. Does conditional max_hold preserve large winners better?
7. Which conditional rule has best trade-off?
8. Can entry confirmation reduce ONE_BAR_STOP-like losses?
9. Does confirmation destroy too many winners?
10. Which scenario reduces worst trade / maxDD?
11. Which scenario has best PF with enough trades?
12. Which scenario preserves BIG_RISK winners?
13. Which scenario should be tested next in paper, if any?
14. Should current maxhold5 service continue, be stopped, or be replaced by another experimental service later?

Important:

```text
Do not recommend changing baseline immediately.
Any recommendation should be “candidate for next paper experiment”.
```

---

## Candidate decision rules

## Strong candidate

A scenario can be recommended for future paper experiment only if:

```text
PF > baseline PF
Net PnL >= baseline Net PnL or MaxDD much lower
Worst trade better than baseline
Trades retained >= 70%
Does not cut most large winners
Stable in at least 3/4 months or majority of weeks
No obvious look-ahead
```

## Weak candidate

If:

```text
PF improves but Net PnL falls hard
or trades retained < 60%
or improvement comes from one month only
or large winners are cut heavily
```

then mark as:

```text
Not ready for paper
```

## Time filter warning

For time filters:

```text
Even if exclude_hour_12 works, mark as high overfit risk unless stable historically.
```

---

## Tests

Add tests:

```text
tests/test_exit_time_filters_v2.py
```

Minimum tests:

1. `exclude_hour_12` skips only MSK hour 12.
2. Time filter does not skip other hours.
3. Fixed `max_hold_10` exits at bar 10, not 5.
4. Stop/take priority beats max_hold.
5. Conditional progress-to-take for SELL calculates correctly.
6. Conditional progress rule exits weak trade.
7. Conditional progress rule keeps strong trade alive.
8. Conditional pnl rule exits losing/flat trade.
9. Conditional pnl rule keeps strong winner.
10. Cut winner classification works.
11. Saved loser classification works.
12. Scenario with zero trades does not crash.
13. Entry confirmation scenario marked unsupported if cannot be simulated safely.
14. Report generation works.

If existing tests/helpers can be reused, do so.

---

## Backward compatibility

Run:

```bash
.venv/bin/python -m pytest tests/test_exit_time_filters_v2.py
```

Then preferably:

```bash
.venv/bin/python -m pytest \
  tests/test_exit_time_filters_v2.py \
  tests/test_backtest_diagnostic_filters.py \
  tests/test_max_hold_audit.py
```

If feasible:

```bash
.venv/bin/python -m pytest
```

Do not break existing 406 tests.

---

## CLI

Add script:

```text
scripts/backtest_exit_time_filters_v2.py
```

Run:

```bash
.venv/bin/python scripts/backtest_exit_time_filters_v2.py \
  --config configs/backtest_exit_time_filters_v2_sim6_sell.yaml
```

CLI output:

```text
HammerTrade Backtest Exit/Time Filters v2
Ticker      : SiM6
Direction   : SELL
Period      : ...
Baseline    : trades=N, net=..., PF=..., maxDD=...
Scenarios   : N
Best net    : ...
Best PF     : ...
Report      : reports/backtest_exit_time_filters_v2_SiM6_SELL_YYYYMMDD_HHMMSS.md
Warnings    : N
```

---

## Commands to run on server

```bash
cd /opt/hammertrade
source .venv/bin/activate

python scripts/backtest_exit_time_filters_v2.py \
  --config configs/backtest_exit_time_filters_v2_sim6_sell.yaml

ls -lah reports | grep backtest_exit_time_filters_v2 | tail
ls -lah out | grep backtest_exit_time_filters_v2 | tail
```

Check services still alive:

```bash
sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json
python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL_maxhold5.json
```

---

## Acceptance Criteria

MVP-2.2 is done if:

1. New CLI exists:
   - `scripts/backtest_exit_time_filters_v2.py`
2. New config exists:
   - `configs/backtest_exit_time_filters_v2_sim6_sell.yaml`
3. Baseline scenario is included.
4. `exclude_hour_12` is tested.
5. `exclude_hours_12_19_21` is tested.
6. `max_hold_5`, `max_hold_10`, `max_hold_15` are tested.
7. At least two conditional max_hold rules are tested.
8. Entry confirmation proxies are tested or explicitly marked unsupported with reason.
9. Report includes large winners / cut winners analysis.
10. Report includes saved losers analysis.
11. Report includes period stability.
12. Report gives candidate recommendation for next paper experiment.
13. Current paper services are not changed.
14. Current paper services remain active.
15. Tests/smoke checks pass.
16. Claude final answer includes:
    - files created/changed;
    - how to run;
    - baseline result;
    - best scenarios;
    - what confirmed / did not confirm;
    - recommendation;
    - warnings.

---

## What NOT to do in MVP-2.2

Do not change live/paper services.

Do not add new systemd service.

Do not stop maxhold5.

Do not switch maxhold5 to 10/15.

Do not implement filter in paper trader.

Do not change HammerDetector.

Do not change core candle pattern logic.

Do not change stop/take geometry.

Do not change `.env`.

Do not claim strategy is proven.

---

## Final Claude Code response format

```markdown
## MVP-2.2 Backtest Exit/Time Filters v2 — готово

### Что сделано

### Созданные файлы

### Изменённые файлы

### Как запустить

### Источник данных и период

### Baseline

### Phase A results

### Phase B results

### Что подтвердилось

### Что не подтвердилось

### Large winners / cut winners

### Saved losers

### Candidate for next paper experiment

### Что НЕ было изменено

### Tests / smoke checks

### Артефакты

### Warnings / limitations

### Рекомендация
```
