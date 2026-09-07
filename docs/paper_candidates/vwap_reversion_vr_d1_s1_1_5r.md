# Paper Candidate — VWAP Reversion VR_d1.0_s1.0_1.5R

Создан: 2026-06-02  
Источник: MVP-R2 `reports/research_multistrategy_r2_latest.md`  
Статус: **NEEDS_MORE_DATA → второй кандидат, требует limit-fill модели**

---

## Why this candidate

VWAP Reversion — наиболее статистически устойчивая стратегия R2: **180 train trades, 55 OOS trades,
все 4 месяца train прибыльны**. PF 1.475 на May OOS подтверждает out-of-sample. Однако стратегия
**критически чувствительна к slippage**: при 2pt PF уже ≈ 1.08 (на границе). Требует
limit-order или dual-fill tracking в paper engine — сложнее Momentum.

---

## Research result summary

| Метрика | Train (Jan–Apr) | OOS (May) |
|---------|----------------|-----------|
| Trades | 180 | 55 |
| Winrate | 45.0% | — |
| Net PnL | +10 271 RUB | — |
| PF | **1.294** | **1.475** |
| Концентрация | без CONCENTRATION_HIGH | — |

Monthly walk-forward (train):

| Месяц | Trades | WR | PF | Net₽ |
|-------|--------|-----|-----|------|
| 2026-01 | 36 | 44.4% | 1.330 | +2 531 |
| 2026-02 | 57 | 47.4% | 1.182 | +1 423 |
| 2026-03 | 66 | 36.4% | 1.020 | +331 |
| 2026-04 | 21 | 66.7% | 3.376 | +5 985 |

**Все месяцы прибыльны** — хорошая временна́я стабильность.

Slippage (train):

| Slip pts | PF | Net₽ | Edge destroyed? |
|----------|----|------|----------------|
| 0 | 1.294 | +10 271 | No |
| 1 | 1.181 | +6 671 | No |
| 2 | 1.079 | +3 071 | **Yes** (PF < 1.1) |
| 5 | 0.828 | −7 729 | Yes |
| 10 | 0.531 | −25 729 | Yes |

⚠ **Edge destroyed at 2pt slippage.** Маркет-ордера неприемлемы.

---

## Exact signal logic

Стратегия: **SHORT only** (price above VWAP → mean reversion down).

Сигнал срабатывает на свече, если:
1. `close > session_VWAP + 1.0 × ATR_14`
2. `close > session_VWAP` (price is above VWAP)

Все условия — строгие AND. Нет look-ahead: VWAP вычислен только по свечам до и включая текущую.

---

## Anchored VWAP calculation

```
session_VWAP = cumsum(typical_price × volume) / cumsum(volume)
typical_price = (high + low + close) / 3

Anchor: reset at each MSK trading day start.
First candle: VWAP = typical_price (no history needed).
```

В реальном времени VWAP должен обновляться нарастающим итогом в рамках торгового дня. Реализован в `src/research/vwap.compute_session_vwap()`.

ATR = rolling(14) mean(True Range). True Range = max(high−low, |high−prev_close|, |low−prev_close|).

---

## Entry logic

- Entry price = `close` сигнальной свечи (немедленный вход по текущей цене)
- Entry direction = SHORT
- Момент входа = свеча, закрывшаяся выше `VWAP + 1.0 × ATR`

---

## Stop logic

- `stop_price = entry_price + 1.0 × ATR_at_signal`
- ATR зафиксирован на момент входа, не обновляется

---

## Take / exit logic

- Режим: `one_r_1_5` → `take_price = entry_price − risk_points × 1.5`
- `risk_points = stop_price − entry_price = 1.0 × ATR`
- Альтернативный режим `to_vwap`: take динамически = текущий VWAP (обновляется каждый бар)
- STOP: `candle.high >= stop_price`
- TAKE: `candle.low <= take_price`
- TIME_EXIT: MSK time >= 18:40 → exit at candle open

---

## Time/session rules

- Торговая сессия: основная MOEX (10:00–18:45 МСК)
- Max trades/day: **3** (VWAP reversion может давать несколько сигналов в день)
- Time exit: **18:40 МСК**
- No overnight

---

## Regime dependency

| Режим | Trades | PF | Net₽ |
|-------|--------|-----|------|
| NORMAL | 165 | 1.142 | +4 802 |
| HIGH_VOL_TREND | 6 | 2.941 | +655 |
| LOW_VOL_RANGE | 3 | ∞ | +1 543 |
| NEWS_SHOCK_PROXY | 6 | 4.798 | +3 272 |

Работает во всех режимах. **NORMAL (165 trades) — основной** режим с умеренным PF 1.14.
High volatility и NEWS_SHOCK дают outlier-profits (малый sample).

---

## Slippage sensitivity — CRITICAL

⚠ **PF destroyed at slippage >= 2pt.** Это главный риск стратегии.

Причина: малые R/R ratios в реверсионной стратегии. При take_r=1.5 и небольшом ATR (10–20pt),
2pt слиппаж (вход+выход) отнимает существенную долю прибыли.

**Требование**: вход должен быть по лимитным ордерам или с гарантированным спредом ≤ 1pt.

---

## Execution risk analysis

### Проблема маркет-ордеров

В бэктесте вход = Close сигнальной свечи. На реальном рынке:
- Маркет-ордер исполнится **в следующей свече** (задержка на 1 бар)
- Слиппаж может достигать 2–5pt в нормальных условиях
- Это уничтожает edge (PF 1.08 при 2pt)

### Подход для paper engine

```
Dual-fill accounting:
  theoretical_pnl:   вход по Close сигнальной свечи (бэктест-модель)
  market_fill_pnl:   вход по Open следующей свечи (реалистичная маркет-оценка)
  limit_fill_sim:    вход при price >= Close + N ticks (симуляция лимитного ордера)
  
Metrics должны показывать все три варианта.
```

### Почему не лимитные ордера напрямую

T-Bank READONLY_TOKEN позволяет только читать данные. Для лимитных ордеров нужен TRADING_TOKEN
(которого намеренно нет в проекте). **Paper engine с VWAP reversion = теоретический PnL**.

### Рекомендация по paper tracking

Для paper VWAP: записывать и theoretical fill (close), и market fill (open следующей), чтобы
видеть расхождение в реальных условиях. Когда разрыв between_both_fills > 1pt систематически →
стратегия нежизнеспособна без лимитных ордеров.

---

## Expected trade frequency

- Train (60 дней): 180 сделок → **~3 сделки в день** (max_trades=3)
- May OOS (20 дней): 55 сделок → ~2.75 сделки в день
- Больше сигналов → больше комиссии → важнее slippage

---

## Paper artifact names (SiU6 post-rollover)

| Artifact | Path |
|----------|------|
| SQLite DB | `data/paper/paper_state_siu6_vwap_reversion.sqlite` |
| Status JSON | `runtime/paper_status_SiU6_VWAP_REVERSION.json` |
| Trades CSV | `out/paper/paper_trades_SiU6_VWAP_REVERSION.csv` |
| Log | `logs/paper_SiU6_VWAP_REVERSION.log` |
| Experiment name | `vwap_reversion_vr_d1_s1_1_5r` |
| Systemd unit | `hammertrade-paper-vwap-reversion.service` |

---

## Liveness / monitoring

- Стандартный liveness guard из `src/paper/liveness.py`
- Дополнительно в status: `last_vwap_computed`, `vwap_at_last_signal`, `trades_today`
- В `compare_all_paper_experiments.py` включить dual-fill comparison columns

---

## Stop conditions

```
CONTINUE research if:
  PF >= 1.2 after >= 40 trades
  AND theoretical PF - market_fill PF < 0.2 (исполнение близко к теоретическому)
  AND liveness OK

OBSERVE_ONLY if:
  PF 1.1–1.2 after >= 40 trades

FREEZE if:
  PF < 1.1 after >= 40 trades
  OR market_fill_pnl <= 0 (execution too costly)
  OR liveness unstable
```

---

## Risks

1. **Execution fragility**: edge destroyed at 2pt slippage. Главный риск.
2. **Маркет-открытие**: если вход по Close даёт значительное отличие от реального Fill — данные misleading.
3. **VWAP в реальном времени**: нужна корректная инкрементальная VWAP-compute в daemon без look-ahead.
4. **Март почти breakeven** (PF 1.02, +331 RUB на 66 сделках) — режимная чувствительность.
5. **3 сделки в день × комиссия**: 3 × 0.05 = 0.15 RUB/день negligible, но при реальном broker это может быть 10× больше.

---

## Why not live/sandbox yet

1. **Edge too slippage-sensitive**: 2pt destroys PF. Нужен лимитный ордер или подтверждение что слиппаж < 1pt.
2. **Нет dual-fill paper engine**: только после реализации.
3. **Momentum имеет приоритет**: более простая execution, более сильный OOS PF.
4. **Не тестировалась на SiU6**: другой контракт.

---

## Launch checklist after rollover

- [ ] SiU6 avg vol/bar >= 500
- [ ] `run_vwap_reversion_paper_trader.py` реализован с dual-fill accounting
- [ ] Dual-fill comparison columns добавлены в diagnostics
- [ ] Smoke test прошёл, theoretical vs market fill сравнены
- [ ] Typical market fill slippage < 1.5pt (проверить на первых 20 сделках)
- [ ] orders_enabled=False проверен
- [ ] Systemd unit установлен
- [ ] `check_all_paper_status.py` показывает OK
- [ ] Momentum уже работает и стабилен >= 2 недели
