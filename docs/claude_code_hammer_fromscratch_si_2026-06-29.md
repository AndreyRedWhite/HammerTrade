# Hammer reversals on SiM6 1m — from-scratch research (2026-06-29)

**Mandate:** the user distrusts the existing `HammerDetector`; rebuild the hammer
study from first principles. Find every hammer (up & down), label which were real
signals, find the common dependency, derive entry/exit params that are profitable
**net of real Si costs**.

**Data:** `data/processed/SiM6_1m_research_jan_may_2026.csv` — 61,555 1-minute bars,
80 trading days, 2026-01-15 → 2026-05-29 (gap Apr10→May01, no June). Built by
concatenating the two raw SiM6 files.

**Cost model (Si, verified from `data/instruments/futures_specs.csv`):** tick = 1,
point_value = 1 RUB. Round-trip commission per project audit (`scripts/true_cost_pnl.py`,
`REAL_RATE_PER_LEG = 0.00025`) ≈ 0.05% of notional ≈ **~40 pts at price 80,000**, plus
~2 pts slippage → **~42-point round-trip hurdle**.

**Train/test split:** TRAIN = Jan15–Mar31, TEST = Apr01–May29. Rules derived on TRAIN,
applied unchanged to TEST.

---

## 1. Candidate detection (loose, on purpose — "find ALL hammers")

- Bullish hammer: `lower_shadow ≥ 1.5·body AND lower_shadow ≥ 0.4·range AND range ≥ 10 AND lower_shadow ≥ upper_shadow`. → **6,570 candidates**.
- Bearish inverted hammer / shooting star: mirror with `upper_shadow`. → **6,769 candidates**.

## 2. Base rate — the naked hammer has NO edge

Enter next-bar open, stop at hammer extreme, fixed target, first-touch over 30 bars:

| Target | bull target-hit | bull mean net | bear target-hit | bear mean net |
|---|---|---|---|---|
| 40 | 34% | −41 | 34% | −41 |
| 80 | 20% | −40 | 21% | −40 |
| 120 | 13% | −41 | 14% | −40 |

Mean net ≈ −40 in **every** bucket ⇒ mean **gross** ≈ 0. A naked Si 1m hammer does
not predict direction; cost then makes it −40/trade.

Forward close-to-close displacement (signed, in trade direction), ALL candidates:

- **Bullish: NEGATIVE drift** (−5 pts @30 bars, 48% positive) — naked "hammer up" is
  an anti-signal on this market.
- Bearish: marginally positive (+2 pts @30 bars, 51%).

## 3. Feature mining — the descriptive pattern is real

Within candidates, the features that genuinely separate good from bad (consistent,
economically coherent, both directions):

1. **Confirmation bar** (next bar breaks the hammer's extreme) — the single biggest
   split. ⚠️ **But see §4: this split is largely a look-ahead artifact.**
2. **Location at a day extreme** — bullish hammers near the **day LOW** (support,
   `dist_daylow < 1.5·ATR`: +19…+23 pts); bearish near the **day HIGH** (resistance,
   `dist_dayhigh < 1.5·ATR`: +21…+45 pts). Reversals need something to reverse against.
3. **Avoid the midday clearing chop (13:00–15:00 MSK)** — consistently the worst window
   (bearish −11 @30 bars there vs +19…+23 in 09–11 / 15–19).
4. Volume/range expansion on the bar (`vol_z > 1.5`, `range/ATR > 1`) adds a few pts.

**Common dependency (the answer to the question):** a hammer is tradeable only as
**(1) a confirmed reversal (2) at a significant day extreme — support/resistance —
(3) outside the midday clearing window.** A hammer "in open space" is noise.

## 4. The look-ahead trap (directly addresses distrust of the old detector)

Selecting on "confirmation" (known only at the close of bar i+1) while entering at the
**open** of bar i+1 leaks the future. Done honestly — entry as a **stop order at the
break of the hammer's extreme** (fills intrabar at the break level, no look-ahead) —
the confirmation edge **collapses**.

> ⚠️ The production `src/strategy/hammer_detector.py` has the same class of problem:
> filter #11 `excursion` gates `is_signal` on **future** bars (`df.iloc[i+1:i+1+horizon]`).
> That is look-ahead baked into the signal definition and would inflate any backtest
> built on it. This is concrete support for the user's instinct to rebuild from scratch.

## 5. Honest backtest, no look-ahead, net of cost

Best honest configs (break-entry, stop = 1·ATR, target = 3R, max-hold 60, core hours,
near day extreme < 1.5 ATR, vol/range filter):

| Direction | split | n | win% | GROSS pts/trade | net @42pt cost |
|---|---|---|---|---|---|
| Bearish (short @ day high) | TRAIN | 68 | 26.5% | **+9.0** | −33 |
| Bearish | TEST | 20 | 25.0% | **+0.5** | −41 |
| Bullish (long @ day low) | TRAIN | 55 | 29.1% | **+16.0** | −26 |
| Bullish | TEST | 56 | 25.0% | **−4.6** | −47 |

Commission sensitivity (net pts/trade vs round-trip cost), ALL data:

| round-trip cost | 2 | 5 | 10 | 20 | 30 | 42 (real Si) |
|---|---|---|---|---|---|---|
| Bearish net | +5 | +2 | −3 | −13 | −23 | −35 |
| Bullish net | +4 | +1 | −4 | −14 | −24 | −36 |

## 6. Conclusion

**On SiM6 1-minute data, hammer/inverted-hammer reversals do NOT have a reliable,
cost-survivable edge.**

- The descriptive pattern (confirm + day extreme + avoid midday) is **real** but the
  in-sample gross edge is only **+9…+16 pts/trade**, it **does not persist out-of-sample**
  (bearish → +0.5, bullish → −4.6), and it is an order of magnitude below Si's **~42-pt
  round-trip cost barrier**.
- Break-even commission is roughly **5–8 pts round-trip**; Si's real cost is ~42. The
  edge would need a venue/tariff ~6–8× cheaper, OR much bigger moves per trade.
- This is consistent with the project's prior audit (only ORB + pairs survive real costs;
  hammer dies).

**Why this doesn't contradict manual experience:** a discretionary edge on hammers most
likely lives on **higher timeframes** (15m/1h, where targets are 100s of pts and the
fixed % cost is negligible) and with discretionary context — not 1-minute Si scalps where
a 42-pt cost dominates ~15-pt moves.

## 7. Higher-timeframe check (15m / 30m / 60m) — does NOT rescue it

Same honest pipeline (loose hammer + break-entry + day-extreme + core hours, stop 1·ATR,
target 3R, max-hold 20 bars), resampled from 1m:

| TF | dir | TRAIN gross | TEST gross | n (train/test) |
|---|---|---|---|---|
| 15m | long | −92.7 | +54.5 | 50 / 29 |
| 15m | short | −12.9 | +11.4 | 58 / 14 |
| 30m | long | −95.2 | −45.0 | 31 / 22 |
| 60m | long | −91.7 | +64.4 | 23 / 12 |
| 60m | short | −18.5 | −5.5 | 21 / 11 |

Gross is mostly negative; where a split is positive it is tiny-n (11–29 trades) and the
sign **flips between train and test** — pure small-sample noise. 80 trading days simply
does not contain enough hammers-at-day-extremes to support 30m/60m trading. Higher
timeframes do **not** produce a robust edge here.

## 8. Bottom line & next step

No robust, cost-survivable hammer edge exists on SiM6 across 1m–60m in this sample. The
pattern logic (confirm + day extreme + avoid midday) is sound and worth keeping as a
filter, but Si's ~42-pt cost barrier plus a sub-20-pt gross edge that doesn't persist OOS
kill it.

**To genuinely pursue the user's manual intuition, the productive next experiments are:**
1. A **longer history** (12+ months, multiple Si contracts) to get enough 15m/1h samples
   for a real out-of-sample test — current 80 days is underpowered above 1m.
2. **Lower-cost instruments** (the gross edge is fixed in points; break-even needs
   round-trip cost ≲ 8 pts vs Si's ~42).

Artifacts: `out/hammer_fromscratch_{bullish,bearish}_candidates.csv` (every candidate +
features + forward MFE/MAE + outcome).
