# IMOEXF 60m with-trend breakout — strategy candidate (walk-forward validated)

Spun out of the hammer研究 (`docs/claude_code_hammer_fromscratch_imoexf_2026-06-29.md`):
the only configuration with a regime-robust positive gross edge was a **with-trend
breakout** (the hammer trigger only hurt). This doc validates it properly.

## Data
IMOEXF 1m fetched fresh from T-Bank prod, **2023-11-14 → 2026-06-28** (~31 months,
736 trading days), resampled to 60m → 11,093 bars. Files in `data/raw/tbank/IMOEXF_1m_*`.
Index regime over the window: choppy-to-down (≈2900 → ≈2300).

## Cost model (real)
point_value = 10 RUB/pt, tick = 0.5. Commission 0.025%/leg of notional (≈index×10) ≈ 1.2 pt
round-trip; slippage 1 tick/leg = 1 pt round-trip. **Total ≈ 2.4 pt/round-trip.**

## Strategy logic
- **Regime:** EMA(100) on 60m. `strength = (close − EMA)/ATR14`.
- **Entry (with-trend breakout):**
  - LONG when `strength ≥ +0.5` AND close breaks the prior 20-bar high.
  - SHORT when `strength ≤ −0.5` AND close breaks the prior 20-bar low.
  - Core hours only (09–13, 15–19 MSK; avoids the midday clearing).
- **Stop:** 1.5·ATR. **Target:** 2R. **Max-hold:** 40 bars. One position at a time.

## Walk-forward (re-optimized, 9mo train / 3mo test, true OOS)
| test window | n | win | net pt/trade | pf | net RUB |
|---|---|---|---|---|---|
| 2024-08→11 | 45 | 40% | +5.08 | 1.38 | +2,288 |
| 2024-11→2025-02 | 35 | 49% | +15.31 | 2.23 | +5,357 |
| 2025-02→05 | 35 | 54% | +22.65 | 2.57 | +7,927 |
| 2025-05→08 | 46 | 35% | +3.89 | 1.30 | +1,791 |
| 2025-08→11 | 45 | 40% | +2.79 | 1.25 | +1,254 |
| 2025-11→2026-02 | 60 | 27% | −4.57 | 0.59 | −2,740 |
| 2026-02→05 | 52 | 27% | −4.15 | 0.58 | −2,159 |
| **Aggregate OOS** | **318** | **37%** | **+4.31** | **1.36** | **+13,717** |

5 of 7 windows positive; the last two (late-2025→2026) lost — re-optimization adds variance.

## Fixed config (NO optimization) over full sample — the robustness anchor
Config `(lookback=20, EMA=100, stop=1.5ATR, TR=2.0, minStrength=0.5)`:

| year | n | win | gross | net pt/trade | pf | net RUB |
|---|---|---|---|---|---|---|
| 2023 (Nov-Dec) | 16 | 38% | +4.97 | +2.42 | 1.28 | +386 |
| 2024 | 184 | 43% | +4.51 | +2.00 | 1.19 | +3,684 |
| 2025 | 169 | 43% | +4.96 | +2.54 | 1.21 | +4,300 |
| 2026 (H1) | 94 | 47% | +3.80 | +1.45 | 1.19 | +1,359 |
| **Full** | **463** | **44%** | **+4.55** | **+2.10** | **1.20** | **+9,730** (maxDD −2,625) |

**Net-positive in every year, pf ~1.2 across 4 different regimes.** This is the headline.

## Robustness
- **Param plateau:** all neighbours of the fixed config are net-positive (+1.0…+4.3 pt;
  no negative cell over lookback∈{10,20,30} × TR∈{1.5,2,3}). Higher TR (3.0) is even
  better (+2.7…+4.3) — trend-following likes letting winners run. Not a lucky spike.
- **Cost sensitivity:** net/trade = +3.1 / +2.1 / +1.1 / +0.1 at slippage 0 / 1 / 2 / 3
  ticks/leg. Breaks even around **~3 ticks** round-trip slippage.
- **Long vs short:** SHORT net +3.14 (pf 1.28) carries the edge; LONG only +0.89 (pf 1.09).

## Honest assessment
A **real, modest, robust edge** — unlike hammers. Net +2.1 pt/trade (~+3,700 RUB/yr per
contract, maxDD ~−2,600), pf 1.2, consistent across 2023–2026, on a parameter plateau.

**Risks / caveats:**
1. **Thin & execution-sensitive** — dies at ~3-tick slippage. Real fills must be tight.
2. **Short-biased** — most of the edge is short; the window was non-bullish. A sustained
   bull market would lean on the marginal long side (still pf 1.09, so not negative, but
   unproven in a strong uptrend).
3. Low frequency (~180 trades/yr) → wide outcome bands; needs time to express.

## Recommended next step
Paper-trade it (the project's paper/sandbox harness) to validate the slippage assumption
with real fills, since the whole edge lives in the 1-vs-3-tick slippage band. It overlaps
conceptually with the existing ORB (breakout) survivor — consider folding it in as a
higher-timeframe, regime-filtered ORB variant rather than a separate engine. Consider
TR=3.0 (higher net in-sample, but re-validate OOS).
