# Paper Candidate — Momentum Continuation MC_atr2.0_vol2.0_r2.0

Создан: 2026-06-02  
Источник: MVP-R2 `reports/research_multistrategy_r2_latest.md`  
Статус: **NEEDS_MORE_DATA → первый кандидат после SiU6 rollover**

---

## Why this candidate

Из всех R2-стратегий Momentum показал **лучший OOS PF (2.883 на 20 May-сделках)** и наиболее
устойчивую slippage sensitivity (PF ≥ 1.15 даже при 10pt слиппаже). Execution-логика проще
VWAP-reversion: нет VWAP-compute в реальном времени, вход — по Close импульсной свечи.

---

## Research result summary

| Метрика | Train (Jan–Apr) | OOS (May) |
|---------|----------------|-----------|
| Trades | 60 | 20 |
| Winrate | 38.3% | — |
| Net PnL | +18 687 RUB | — |
| PF | **1.519** | **2.883** |
| MaxDD (train) | — | — |
| Concentration | ⚠ CONCENTRATION_HIGH (top-3 = 79% net) | — |

Monthly walk-forward (train):

| Месяц | Trades | PF | Net₽ |
|-------|--------|-----|------|
| 2026-01 | 12 | 0.498 | **−4 661** |
| 2026-02 | 19 | 1.101 | +1 179 |
| 2026-03 | 22 | 2.776 | +19 219 |
| 2026-04 | 7 | 1.701 | +2 950 |

**Январь убыточный** — режим низкой волатильности. Март = основная прибыль.

Slippage (train):

| Slip pts | PF | Net₽ | Edge destroyed? |
|----------|----|------|----------------|
| 0 | 1.519 | +18 687 | No |
| 2 | 1.434 | +16 287 | No |
| 5 | 1.319 | +12 687 | No |
| 10 | 1.154 | +6 687 | No |

Слиппаж не убивает стратегию — **edge сохраняется при 10pt**.

---

## Exact signal logic

Стратегия: **SHORT only**, direction = SELL.

Сигнал срабатывает на свече, если одновременно:
1. `candle.range >= 2.0 × ATR_14`, где `range = high − low`
2. `(close − low) / range <= 0.25` (close в нижних 25% диапазона свечи)
3. `volume >= 2.0 × rolling_mean(volume, window=20)`
4. `ATR` вычисляется как rolling(14) средней True Range по предыдущим барам — **нет look-ahead**

Все три условия — строгие AND.

---

## Entry logic

- Entry price = `close` сигнальной свечи (вход по цене закрытия импульса)
- Entry direction = SHORT (продажа)
- Момент входа = следующая свеча (исполнение по открытию следующего бара)

---

## Stop logic

- `stop_price = high` сигнальной свечи
- Риск: `risk_points = stop_price − entry_price`

Стоп выше максимума импульсной свечи — разворот свечи означает, что импульс исчерпан.

---

## Take / exit logic

- `take_price = entry_price − risk_points × 2.0`  (take_r = 2.0)
- `take_r = 2.0` — фиксированный коэффициент из best scenario
- STOP: last bar `high >= stop_price` → exit at stop_price
- TAKE: last bar `low <= take_price` → exit at take_price
- TIME_EXIT: свеча с MSK-временем >= 18:40 → exit at candle open

Приоритет: TIME_EXIT > STOP > TAKE (STOP в той же свече бьёт прежде TAKE).

---

## Time/session rules

- Торговая сессия: основная MOEX (10:00–18:45 МСК)
- Поиск сигналов: с первой свечи дня, когда ATR накоплен (≥ 14 баров данных)
- Max trades/day: **1** (первый сигнал за день)
- Time exit: **18:40 МСК**
- No overnight: открытые позиции принудительно закрываются по TIME_EXIT

---

## Regime dependency

| Режим | Trades | PF | Net₽ |
|-------|--------|-----|------|
| NORMAL | 55 | 1.349 | +11 907 |
| HIGH_VOL_TREND | 2 | 1.512 | +210 |
| LOW_VOL_RANGE | 1 | 0.000 | −1 470 |
| NEWS_SHOCK_PROXY | 2 | ∞ | +8 040 |

**Основная прибыль в NORMAL режиме** (55 сделок). NEWS_SHOCK даёт 2 выброса с огромной прибылью —
источник концентрации. Стратегия **работает в любом режиме кроме LOW_VOL_RANGE**.

---

## Slippage sensitivity

Стратегия устойчива к slippage: при 10pt PF = 1.154. Причина — большие take-расстояния (take_r=2.0)
амортизируют slippage. **Маркет-ордера приемлемы**.

---

## Robustness / concentration

⚠ **CONCENTRATION_HIGH**: топ-3 сделки = 79% прибыли.  
Январь убыточен (PF 0.498).

**Импликация**: стратегия зависит от нескольких крупных импульсных дней (NEWS_SHOCK_PROXY +
высоко-волатильные дни). В боковом/тихом рынке прибыли мало. Ожидаемое поведение для momentum-стратегии.

---

## Expected trade frequency

- Train (60 дней): 60 сделок → **~1 сделка в день**
- May OOS (20 дней): 20 сделок → ~1 сделка в день
- При высоких фильтрах (atr×2.0, vol×2.0) сигнал генерируется не каждый день

---

## Paper artifact names (SiU6 post-rollover)

| Artifact | Path |
|----------|------|
| SQLite DB | `data/paper/paper_state_siu6_momentum.sqlite` |
| Status JSON | `runtime/paper_status_SiU6_MOMENTUM.json` |
| Trades CSV | `out/paper/paper_trades_SiU6_MOMENTUM.csv` |
| Log | `logs/paper_SiU6_MOMENTUM.log` |
| Experiment name | `momentum_mc_atr2_vol2_r2` |
| Systemd unit | `hammertrade-paper-momentum.service` |

---

## Liveness / monitoring

- Использовать тот же `compute_liveness()` из `src/paper/liveness.py`
- Status JSON с полями: liveness, consecutive_api_errors, last_successful_fetch_at
- Включить в `check_all_paper_status.py` после запуска

---

## Stop conditions

```
CONTINUE research if:
  PF >= 1.25 after >= 30 trades
  AND not result from 1–2 outlier days
  AND liveness OK

OBSERVE_ONLY if:
  1.1 <= PF < 1.25 after >= 30 trades

FREEZE if:
  PF < 1.1 after >= 30 trades
  OR concentration: 1 day > 60% of net
  OR liveness unstable > 3 days
```

---

## Risks

1. **Концентрация**: результат зависит от 2–3 NEWS_SHOCK/HIGH_VOL дней. В затяжном боковике месяц может быть убыточным.
2. **Январский риск**: если SiU6 стартует в периоде низкой волатильности — первые недели могут быть отрицательными.
3. **Параметры не оптимизировались под SiU6**: спред, ликвидность, тик-размер у SiU6 немного отличаются.
4. **Slippage при гэп-открытии**: вход по Close предыдущей свечи. Если следующая открывается с гэпом — реальный слиппаж может быть выше модельного.

---

## Why not live/sandbox yet

1. Только 20 OOS сделок — статистически недостаточно.
2. Концентрация слишком высокая (79% в 3 сделках) — нет уверенности в устойчивости.
3. Не протестировано на SiU6 (другой контракт, возможна другая волатильность).
4. Нет paper-engine для Momentum: требуется реализация `run_momentum_paper_trader.py`.

---

## Launch checklist after rollover

- [ ] SiU6 avg vol/bar >= 500 (ликвидность достаточна)
- [ ] `run_momentum_paper_trader.py` реализован и протестирован
- [ ] Smoke test (--once) прошёл успешно
- [ ] Status file корректно создаётся
- [ ] orders_enabled=False проверен
- [ ] Systemd unit установлен и сервис активен
- [ ] `check_all_paper_status.py` показывает OK
- [ ] Начало наблюдения задокументировано
