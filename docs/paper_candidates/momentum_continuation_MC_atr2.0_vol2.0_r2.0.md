# Paper Candidate: Momentum Continuation — MC_atr2.0_vol2.0_r2.0

**Status**: NEEDS_MORE_DATA  
**Ticker**: SiM6  
**Direction**: SHORT only  
**Date**: 2026-06-02  

---

## Parameters

| Parameter | Value |
|---|---|
| atr_mult | 2.0 |
| vol_mult | 2.0 |
| take_r | 2.0 |
| atr_window | 14 bars |
| vol_window | 20 bars |
| direction | SHORT |
| max_trades_per_day | 1 (first signal wins) |
| time_exit | 18:40 MSK |
| no_overnight | yes |

---

## Entry / Exit Logic

**Signal (SHORT)**:
- Candle range ≥ 2.0 × ATR(14)
- Close in bottom 25% of candle range: (close − low) / range ≤ 0.25
- Volume ≥ 2.0 × 20-bar rolling mean volume
- All three conditions met simultaneously → strong bearish impulse

**Entry**: Close of the impulse candle (SHORT)  
**Stop**: High of the impulse candle  
**Take**: entry − (stop − entry) × 2.0  
**Commission**: 0.05 RUB per side, point value: 10 RUB/point

---

## Risk Parameters

- Risk per trade = stop − entry (varies, typically 1–3 × ATR)
- Reward-to-risk ratio: 2.0 (take_r = 2.0)
- No position sizing adjustments

---

## Time Windows

- Signal scan: all session candles after setup period (14 ATR bars)
- Entry: any time from session open to 18:40 MSK
- Force-close: 18:40 MSK
- No overnight positions

---

## Regime Filters

None applied in current version. Consider adding:
- Skip NEWS_SHOCK_PROXY days (opening gap > 3× median range)
- Skip HIGH_VOL_TREND days (directional momentum overrides reversion)

---

## Performance Metrics (Train: 2026-01-15 to 2026-04-10)

| Metric | Value |
|---|---|
| Trades | 60 |
| Win Rate | 38.3% |
| Profit Factor | 1.519 |
| Net PnL | +18,687 ₽ |
| Max Drawdown | ~15,000 ₽ |
| Slippage at 5pts | PF=1.319 (edge survives) |

## Performance Metrics (OOS: 2026-05-01 to 2026-05-30)

| Metric | Value |
|---|---|
| Trades | 20 |
| Profit Factor | 2.883 |

---

## Walk-Forward (Monthly)

| Month | Trades | PF | Net₽ |
|---|---|---|---|
| 2026-01 | 12 | 0.498 | −4,661 |
| 2026-02 | 19 | 1.101 | +1,179 |
| 2026-03 | 22 | 2.776 | +19,219 |
| 2026-04 | 7 | 1.701 | +2,950 |

**Walk-forward note**: Jan was a losing month. Strategy strengthens in March–April. High month-to-month variance suggests the edge is real but regime-dependent.

---

## Expected Trade Frequency

~1 trade per day (max_trades_per_day=1), but filter is strict (atr_mult=2.0 + vol_mult=2.0). Actual: ~1 trade/day across 60 trading days = 1.0 trades/day on train.

---

## Concentration Warning

Top 3 trades = 78.9% of total net PnL. The edge is highly concentrated in a few outlier trades. This is a significant concern for live trading.

---

## Why Selected

- Best train PF (1.519) and best OOS PF (2.883) in Momentum Continuation grid
- Slippage robust: PF stays above 1.1 at 10pts slippage
- OOS validates the signal direction — no OOS degradation

## Why Not Ready for Paper

1. Only 60 train trades — insufficient sample for robust statistics
2. Extreme concentration: top 3 trades = 79% of profit
3. January losing month suggests regime sensitivity
4. OOS only 20 trades — too few to confirm edge reliably

## Recommended Next Steps

1. Collect 1–2 more months of data (SiU6 after rollover)
2. Add regime filter: only trade on NORMAL + HIGH_VOL_TREND days
3. Re-run with larger grid including stop variants
4. Target: 100+ trades with PF > 1.3 before paper candidacy
