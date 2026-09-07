# Claude Code Prompt — MVP-R2: Multi-Strategy Research Pack + Paper Candidate Pipeline

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

Сейчас уже работают три paper-сервиса:

```text
1. hammer-baseline
   systemd: hammertrade-paper.service
   ticker: SiM6
   direction: SELL
   max_hold_bars: None
   db: data/paper/paper_state.sqlite
   status: runtime/paper_status_SiM6_SELL.json

2. hammer-maxhold5
   systemd: hammertrade-paper-maxhold5.service
   ticker: SiM6
   direction: SELL
   max_hold_bars: 5
   db: data/paper/paper_state_maxhold5.sqlite
   status: runtime/paper_status_SiM6_SELL_maxhold5.json

3. orb-paper
   systemd: hammertrade-paper-orb.service
   strategy: opening_range_breakout
   ticker: SiM6
   direction: SHORT
   opening range: 10:00–11:00 MSK
   take_r: 2.0
   orders_enabled: false
   db: data/paper/paper_state_orb.sqlite
   status: runtime/paper_status_SiM6_ORB.json
```

Важно:

```text
Текущие paper-сервисы НЕ ломать.
Не менять их параметры.
Не останавливать без необходимости.
Не запускать sandbox/real orders.
```

---

## Текущий статус стратегий

## Hammer baseline

```text
Status: control group
PF около 1.0
Используется как контроль против maxhold5
```

## Hammer maxhold5

Последний decision report:

```text
Decision: CONTINUE

May 13 – Jun 2:
  Trades: 61
  PF: 1.396
  Net: +1 877 RUB
  Baseline same window: +317 RUB
  MaxDD: 1 120 RUB vs baseline 3 231 RUB
```

Главный плюс:

```text
max_hold_bars=5 режет затяжные убыточные сделки.
```

Оставшаяся проблема:

```text
ONE_BAR_STOP:
  10 сделок
  WR 0%
  около -1 710 RUB
  max_hold не помогает, потому что стоп срабатывает до 5-го бара.
```

## ORB paper

ORB уже запущен как третий paper service.

Профиль:

```text
Opening Range Breakout
Ticker: SiM6
Direction: SHORT
Opening Range: 10:00–11:00 MSK
Take R: 2.0
Stop: opposite_range
Entry: breakout_level
Time exit: 18:40 MSK
Max trades/day: 1
Orders enabled: false
```

Первичная проверка первого торгового дня:

```text
State machine отработала корректно.
2026-06-01:
  OR high=72 231
  OR low=71 690
  range=541 pts
  breakout вниз не было
  0 trades
  DONE_FOR_DAY корректно
```

---

## Почему нужен MVP-R2

Мы не хотим искать “одну магическую стратегию”.

Цель проекта теперь шире:

```text
Построить multi-strategy research/paper platform,
где разные стратегии работают в разных режимах рынка.
```

Особенность РФ-рынка:

```text
Российский рынок сильно зависит от политических/геополитических и новостных факторов.
Чистый теханализ часто ломается.
Поэтому нужно не только тестировать стратегии,
но и понимать режим рынка:
  trend / range / high volatility / news shock proxy / low liquidity / expiration risk.
```

Текущая логика:

```text
1. Hammer maxhold5 — reversal candidate.
2. ORB — breakout/trend candidate.
3. Нужно исследовать другие режимы:
   - VWAP reversion / mean reversion;
   - VWAP filters;
   - momentum continuation;
   - opening range fade / false breakout;
   - volatility breakout / regime filters.
```

---

# Главная цель MVP-R2

Сделать Multi-Strategy Research Pack.

Нужно:

```text
1. Добавить несколько новых стратегий как offline research modules.
2. Прогнать их на доступных исторических данных SiM6:
   - Jan 15 – Apr 9 2026 train;
   - May 4 – May 29 2026 OOS;
   - full Jan–May.
3. Проверить slippage sensitivity.
4. Проверить regime breakdown.
5. Проверить concentration / robustness.
6. Сравнить результаты в едином формате.
7. Выдать список paper candidates:
   - READY_FOR_PAPER
   - NEEDS_MORE_DATA
   - REJECT
8. Подготовить pipeline, чтобы по итогам R2 можно было быстро запускать 1–3 лучшие стратегии в paper.
```

Этот MVP НЕ должен запускать новые paper services.

Исключение: если код удобно готовит unit examples/configs — можно создать examples, но не включать/не стартовать.

---

# Жёсткие ограничения

Строго запрещено:

- менять `hammertrade-paper.service`;
- менять `hammertrade-paper-maxhold5.service`;
- менять `hammertrade-paper-orb.service`;
- менять их systemd unit files;
- менять текущие paper DB/status/csv/log;
- сбрасывать state;
- менять HammerDetector;
- менять hammer strategy logic;
- менять ORB paper strategy params;
- запускать новые paper services;
- запускать sandbox orders;
- запускать real orders;
- менять `.env`;
- печатать токены;
- удалять SQLite/CSV/reports/logs;
- обещать прибыль;
- делать вывод “стратегия доказана”.

Разрешено:

- добавлять offline research strategies;
- добавлять configs;
- читать historical candles;
- загружать missing historical candles через T-Bank API read-only;
- добавлять reports/CSV;
- добавлять tests/docs;
- расширять Strategy Research Lab;
- добавлять paper candidate specs/examples без запуска.

---

# Existing Strategy Research Lab

Уже есть:

```text
src/strategies/base.py
src/strategies/registry.py
src/strategies/opening_range_breakout/
src/research/
scripts/research_strategy.py
scripts/research_orb_walkforward.py
```

Нужно переиспользовать и расширить, а не плодить полностью отдельные механизмы.

Если текущая архитектура недостаточна — аккуратно расширить.

---

# Данные

Использовать уже загруженные candles:

```text
Train:
  2026-01-15 — 2026-04-09
  около 43 765 строк
  60 trading days

OOS:
  2026-05-04 — 2026-05-29
  около 17 790 строк
  20 trading days

Full:
  2026-01-15 — 2026-05-29
```

Если exact file paths отличаются — найти их и указать в отчёте.

Если данных не хватает — загрузить read-only через T-Bank API.

Не печатать токены.

---

# Стратегии для MVP-R2

## Strategy 1 — VWAP Reversion

Mean reversion к VWAP.

```text
Если цена сильно отклонилась от VWAP,
и нет сильного трендового/новостного режима,
ожидаем возврат к VWAP.
```

Scenarios:

```text
SHORT:
  price above VWAP by threshold
  enter short
  take near VWAP / partial VWAP distance
  stop further away from VWAP

LONG:
  price below VWAP by threshold
  enter long
  take near VWAP / partial VWAP distance
  stop further away from VWAP
```

Thresholds:

```text
distance_to_vwap:
  0.5 ATR
  1.0 ATR
  1.5 ATR
  2.0 ATR
```

Take:

```text
take_to_vwap
take_50pct_to_vwap
take_75pct_to_vwap
```

Stop:

```text
stop = entry +/- 1.0 ATR
stop = entry +/- 1.5 ATR
```

Filters:

```text
avoid HIGH_VOL_TREND
avoid NEWS_SHOCK_PROXY
test with and without regime filter
```

---

## Strategy 2 — VWAP Filter for Hammer

Не новая standalone strategy, а фильтр к hammer signals.

Проверить:

```text
Улучшается ли hammer maxhold5, если брать SELL-сигналы только при определённом положении относительно VWAP?
```

Для текущей hammer SELL:

```text
A. SELL only if price > VWAP
B. SELL only if signal candle high is above VWAP
C. SELL only if close is above VWAP by >= 0.5 ATR
D. SELL only if price crossed back below VWAP after being above
E. No VWAP filter baseline
```

Если сложно реконструировать hammer signals — использовать существующий debug/backtest signal CSV. Не переписывать HammerDetector без необходимости.

---

## Strategy 3 — Momentum Continuation

Торговать продолжение сильного импульса.

For SHORT:

```text
large bearish candle
body >= X * ATR or candle_range >= X * ATR
close near low, e.g. close_position <= 20% of range
volume >= Y * rolling volume
optional: next candle does not fully reclaim impulse
```

For LONG:

```text
large bullish candle
close near high
volume spike
```

Scenarios:

```text
ATR multiplier:
  1.0
  1.5
  2.0

close_near_extreme:
  20%
  30%

volume multiplier:
  1.2
  1.5
  2.0
```

Entry:

```text
entry on close of impulse candle
or entry on break of impulse high/low
```

Exit:

```text
take_r:
  1.0
  1.5
  2.0

stop:
  opposite side of impulse candle
  or ATR stop

time_exit:
  18:40
```

---

## Strategy 4 — Opening Range Fade / False Breakout

ORB ловит продолжение пробоя. OR Fade ловит ложный пробой.

For SHORT fade:

```text
price breaks above OR high
then returns back inside opening range within N bars
enter short on re-entry
stop above breakout extreme
take = OR midpoint or OR low
```

For LONG fade:

```text
price breaks below OR low
then returns back inside opening range within N bars
enter long on re-entry
stop below breakout extreme
take = OR midpoint or OR high
```

Opening ranges:

```text
10:00–10:30
10:00–11:00
```

Re-entry window:

```text
3 bars
5 bars
10 bars
```

Take:

```text
midpoint
opposite side of OR
1R
```

Filters:

```text
works likely better in LOW_VOL_RANGE / NORMAL
avoid HIGH_VOL_TREND / NEWS_SHOCK_PROXY
test with and without regime filter
```

---

## Strategy 5 — Volatility Breakout / Range Expansion

Optional if MVP becomes too large.

Signal:

```text
before signal: low volatility compression
then range expansion breakout
```

Compression:

```text
rolling ATR / median ATR below threshold
last N bars range below threshold
```

Breakout:

```text
price breaks last N bar high/low
with range/volume expansion
```

Scenarios:

```text
compression_window: 30, 60, 120 minutes
breakout_window: 15, 30, 60 minutes
direction: long/short/both
take_r: 1.0, 1.5, 2.0
```

If needed, defer and explain.

---

# Regime Classification

Use existing regime classifier, but make sure every strategy report includes regime breakdown.

Regimes:

```text
LOW_VOL_RANGE
NORMAL
HIGH_VOL_TREND
NEWS_SHOCK_PROXY
```

If needed, add/adjust features:

```text
daily_range
opening_gap
first_hour_range
ATR_30m
ATR_60m
volume_vs_average
large_candle_count
trendiness / close location in daily range
```

Important:

```text
Regime classifier is a proxy, not real news understanding.
Document limitations.
```

---

# Slippage

Every standalone strategy must be tested with:

```text
0 pt
1 pt
2 pt
5 pt
10 pt
```

Define:

```text
edge_destroyed = PF < 1.1 or net <= 0 at slippage <= 2 pt
```

---

# Robustness / Concentration

For every candidate scenario calculate:

```text
top_1_day_contribution
top_3_day_contribution
top_5_trades_contribution
net_without_best_day
net_without_best_3_trades
worst_3_trades
max_drawdown
```

Flags:

```text
CONCENTRATION_HIGH:
  best day > 40% of net
  or top 3 trades > 50% of net
```

If net <= 0, concentration flags should be handled carefully.

---

# Walk-forward

For every strategy/scenario:

```text
Train: Jan 15 – Apr 9
OOS: May 4 – May 29
Full: Jan 15 – May 29
Monthly breakdown
Weekly breakdown
```

Need to answer:

```text
Does strategy survive May OOS?
Does it work only in one month/week?
Does it depend on regime?
```

---

# Unified Candidate Decision

For each strategy/scenario output:

```text
READY_FOR_PAPER
NEEDS_MORE_DATA
REJECT
```

## READY_FOR_PAPER

Only if:

```text
OOS May PF >= 1.25
OOS May net > 0
slippage 1–2 pt still PF > 1.1
not concentration-high
logical regime story
at least 10 OOS trades, preferably 20+
```

## NEEDS_MORE_DATA

If:

```text
train good, OOS too few trades
or OOS positive but concentration high
or slippage weakens but does not kill
or regime dependency plausible but sample small
```

## REJECT

If:

```text
OOS PF < 1.0
or OOS net <= 0
or slippage <=2 destroys edge
or result only from one outlier
or logic appears inconsistent
```

---

# Paper Candidate Specs

For every scenario with `READY_FOR_PAPER` or strong `NEEDS_MORE_DATA`, create:

```text
docs/paper_candidates/<strategy_name>_<scenario_name>.md
```

Each spec must include:

```text
strategy name
scenario params
ticker
direction
entry logic
exit logic
risk logic
time windows
regime filters
expected trade frequency
artifacts names if launched
stop conditions
why candidate was selected
why not ready for live/sandbox
```

Do NOT start services.

---

# Reports

Create main report:

```text
reports/research_multistrategy_r2_YYYYMMDD_HHMMSS.md
reports/research_multistrategy_r2_latest.md
```

Create summary CSV:

```text
out/research_multistrategy_r2_summary_YYYYMMDD_HHMMSS.csv
out/research_multistrategy_r2_summary_latest.csv
```

Create trades CSVs if feasible:

```text
out/research_multistrategy_r2_trades_<strategy>_latest.csv
```

## Main Markdown structure

```markdown
# MVP-R2 Multi-Strategy Research Pack

## Цель

## Краткий вывод

## Источники данных

## Data quality

## Strategy candidates overview

## VWAP Reversion

## VWAP Filter for Hammer

## Momentum Continuation

## Opening Range Fade

## Volatility Breakout

## Regime breakdown

## Slippage sensitivity

## Robustness / concentration

## Comparison with current paper services

## READY_FOR_PAPER candidates

## NEEDS_MORE_DATA candidates

## REJECTED candidates

## Paper candidate specs

## Limitations

## Recommendation

## Next steps
```

---

# Comparison with current paper services

Include current paper summary:

```text
hammer-baseline
hammer-maxhold5
orb-paper
```

But clearly state:

```text
Paper services are live paper.
R2 strategies are offline research.
Do not compare directly without caution.
```

---

# CLI

Add:

```text
scripts/research_multistrategy_r2.py
```

Run:

```bash
python scripts/research_multistrategy_r2.py \
  --config configs/research/multistrategy_r2_sim6.yaml
```

Config:

```text
configs/research/multistrategy_r2_sim6.yaml
```

If this is too much for one implementation, prioritize:

```text
1. VWAP Reversion
2. Momentum Continuation
3. Opening Range Fade
4. VWAP Hammer Filter
5. Volatility Breakout optional
```

Final answer must clearly say what was included and what was deferred.

---

# Tests

Add tests as needed:

```text
tests/test_vwap_reversion.py
tests/test_momentum_continuation.py
tests/test_opening_range_fade.py
tests/test_volatility_breakout.py
tests/test_multistrategy_r2_runner.py
tests/test_candidate_decision.py
```

Run relevant tests and, if feasible:

```bash
.venv/bin/python -m pytest
```

Do not break existing 536 tests.

---

# Service Safety Check

After implementation, verify current services:

```bash
sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
sudo systemctl status hammertrade-paper-orb --no-pager

.venv/bin/python scripts/check_all_paper_status.py
```

Expected:

```text
hammer-baseline: active OK
hammer-maxhold5: active OK
orb-paper: active OK
```

---

# Acceptance Criteria

MVP-R2 is done if:

1. Multi-strategy research CLI exists.
2. VWAP Reversion implemented or explicitly deferred with reason.
3. Momentum Continuation implemented or explicitly deferred with reason.
4. Opening Range Fade implemented or explicitly deferred with reason.
5. VWAP Hammer Filter implemented or explicitly deferred with reason.
6. Volatility Breakout implemented or explicitly deferred with reason.
7. Train/OOS/Full results produced.
8. Monthly/weekly walk-forward produced.
9. Regime breakdown produced.
10. Slippage sensitivity produced.
11. Concentration/robustness produced.
12. Unified candidate decisions produced.
13. Candidate specs generated for strong candidates.
14. Main Markdown report created.
15. Summary CSV created.
16. Current paper services not changed.
17. Tests pass.
18. Claude final answer includes:
    - strategies tested;
    - top candidates;
    - rejected candidates;
    - service status;
    - next recommendation.

---

# What NOT to do

Do not start new paper services.

Do not change existing paper services.

Do not execute sandbox/real orders.

Do not perform rollover.

Do not implement news NLP.

Do not add Telegram notifications.

Do not over-optimize after seeing results.

Do not claim profitability.

---

# Финальный формат ответа Claude Code

```markdown
## MVP-R2 Multi-Strategy Research Pack — готово

### Что сделано

### Созданные файлы

### Изменённые файлы

### Data source

### Strategies tested

### Top results

### READY_FOR_PAPER candidates

### NEEDS_MORE_DATA candidates

### REJECTED candidates

### VWAP Reversion

### VWAP Hammer Filter

### Momentum Continuation

### Opening Range Fade

### Volatility Breakout

### Slippage sensitivity

### Regime breakdown

### Robustness / concentration

### Paper candidate specs

### Current paper service status

### Tests / smoke checks

### Артефакты

### Warnings / limitations

### Рекомендация
```
