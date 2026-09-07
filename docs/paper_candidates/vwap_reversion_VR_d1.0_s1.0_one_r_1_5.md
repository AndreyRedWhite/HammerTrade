# Paper Candidate: VWAP Reversion — VR_d1.0_s1.0_one_r_1_5

**Status**: NEEDS_MORE_DATA  
**Ticker**: SiM6  
**Direction**: SHORT only (price above VWAP → reversion down)  
**Date**: 2026-06-02  

---

## Parameters

| Parameter | Value |
|---|---|
| distance_mult | 1.0 (signal when close > VWAP + 1.0×ATR) |
| stop_mult | 1.0 (stop = entry + 1.0×ATR) |
| take_mode | one_r_1_5 (take = entry − 1.5×risk) |
| atr_window | 14 bars |
| direction | SHORT |
| max_trades_per_day | 3 |
| time_exit | 18:40 MSK |
| no_overnight | yes |

---

## Entry / Exit Logic

**Signal (SHORT)**:
- Session VWAP is computed fresh each day (anchored at session open)
- close > VWAP + 1.0 × ATR(14) → price stretched above VWAP

**Entry**: Close of the signal candle (SHORT)  
**Stop**: entry + 1.0 × ATR(14)  
**Take**: entry − 1.5 × risk  
**Commission**: 0.05 RUB per side, point value: 10 RUB/point

---

## Risk Parameters

- Risk per trade = 1.0 × ATR (dynamic, typically 15–30 points)
- Reward-to-risk ratio: 1.5
- Up to 3 trades per day (consecutive VWAP deviations)

---

## Time Windows

- Signal scan: all session candles (VWAP needs ~15 bars to stabilize)
- Entry: any time from 10:00 MSK (session open) to 18:40 MSK
- Force-close: 18:40 MSK
- No overnight positions

---

## Regime Filters

None applied currently. Strong candidates for filtering:
- Do NOT trade on NEWS_SHOCK_PROXY days (gap + first-hour shock)
- Caution on HIGH_VOL_TREND days (VWAP deviation may not revert)
- Best performance on NORMAL and LOW_VOL_RANGE days

---

## Performance Metrics (Train: 2026-01-15 to 2026-04-10)

| Metric | Value |
|---|---|
| Trades | 180 |
| Win Rate | 45.0% |
| Profit Factor | 1.294 |
| Net PnL | +10,271 ₽ |
| Slippage at 1pt | PF=1.181 (edge survives) |
| Slippage at 2pt | PF=1.079 (destroyed threshold) |

## Performance Metrics (OOS: 2026-05-01 to 2026-05-30)

| Metric | Value |
|---|---|
| Trades | 55 |
| Profit Factor | 1.475 |

---

## Walk-Forward (Monthly)

| Month | Trades | PF | Net₽ |
|---|---|---|---|
| 2026-01 | 36 | 1.330 | +2,531 |
| 2026-02 | 57 | 1.182 | +1,423 |
| 2026-03 | 66 | 1.020 | +331 |
| 2026-04 | 21 | 3.376 | +5,985 |

**Walk-forward note**: Most stable monthly performance of all strategies tested. All months profitable. April was exceptional (PF 3.4). Consistent but thin edge in Jan–Mar.

---

## Expected Trade Frequency

~3 trades per day (3 VWAP crossings), ~3 × 60 = 180 trades over 60 trading days. High frequency strategy.

---

## Why Selected

- Highest trade count (180) → most statistically robust
- Only strategy with ALL months profitable in walk-forward
- OOS PF 1.475 > train PF 1.294 — genuine generalization
- VWAP is a well-known market structure anchor

## Why Not Ready for Paper

1. **Slippage destroys edge at 2pts**: Si futures 1-min bars have 1pt bid/ask spread minimum. At realistic 2pt slippage, PF drops to 1.08 (marginal). Live execution requires sub-1pt slippage to be viable.
2. Mar 2026 PF was only 1.02 — thin edge in trending months
3. max_trades_per_day=3 means up to 3 simultaneous risk positions
4. Needs regime filter to exclude HIGH_VOL_TREND days

## Recommended Next Steps

1. Test with regime filter: exclude HIGH_VOL_TREND and NEWS_SHOCK_PROXY
2. Tighten entry: require close > VWAP + 1.5×ATR for better edge
3. Run with limit orders to reduce slippage (entry at VWAP + dist threshold)
4. Target: maintain PF > 1.2 at 2pt slippage before paper candidacy
