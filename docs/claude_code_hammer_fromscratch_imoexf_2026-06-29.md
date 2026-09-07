# Hammer reversals on IMOEXF — from-scratch research, 18 months (2026-06-29)

Follow-up to the Si study (`docs/claude_code_hammer_fromscratch_si_2026-06-29.md`).
User asked to switch to IMOEXF and run "point 1" (longer history + higher timeframes).
Same from-scratch methodology, NO reuse of the production detector.

## Data (fetched fresh from T-Bank prod, read-only)
- `data/raw/tbank/IMOEXF_1m_2025-01-01_2026-01-01.csv` — 231,960 1m bars.
- `data/raw/tbank/IMOEXF_1m_2026-01-01_2026-06-29.csv` — 118,620 1m bars.
- Combined `data/processed/IMOEXF_1m_2025_2026.csv` — **350,580 1m bars, 446 trading days**.
- (Local CA bundle had to be rebuilt: `/tmp/russian_ca.pem` = system CA + Russian Trusted
  Root CA, via `scripts/build_tbank_ca_bundle.sh`; set GRPC_DEFAULT_SSL_ROOTS_FILE_PATH /
  SSL_CERT_FILE / REQUESTS_CA_BUNDLE to it.)

Regime: index fell both years — **2025: 2907→2776 (−4.5%), 2026: 2756→2296 (−16.7%)**.

## Cost model (IMOEXF, from `futures_specs.csv`)
point_value = 10 RUB/pt, tick = 0.5. Commission 0.025%/leg of notional (= index×10).
Round-trip ≈ 0.0005·price·... = **~1.2 pts commission + ~1 pt slippage ≈ 2.4 pts**.
Much cheaper than Si (~42 pts) — but IMOEXF intraday moves are also tiny
(median ATR: 5m = 2.9 pt, 15m = 5.1 pt, 60m = 10.2 pt), so cost/ATR is still unfavorable.

## Pipeline
Loose hammer geometry (long working shadow ≥1.5·body, ≥0.4·range), honest break-entry
(stop order at hammer extreme — no look-ahead), filter "near day extreme" + core hours
(avoid 13–15 MSK midday), stop 0.6·ATR, target 2R, max-hold 40 bars. Net of the cost model.

## Decisive test — regime split (TRAIN = full 2025 / TEST = 2026)

| TF | dir | 2025 GROSS | 2025 pf | 2026 GROSS | 2026 net |
|---|---|---|---|---|---|
| 5m | long | −1.4 | 0.17 | −1.2 | −3.5 |
| 5m | **short** | **−0.7** | 0.27 | +0.9 | −1.4 |
| 15m | long | −1.5 | 0.27 | −1.5 | −3.9 |
| 15m | short | −2.0 | 0.21 | +0.1 | −2.3 |
| 60m | long | −3.8 | 0.28 | −3.5 | −5.8 |
| 60m | short | −2.9 | 0.38 | −1.2 | −3.6 |

## Conclusion — NO tradeable edge

1. **In 2025, every variant is negative even GROSS** (before costs), both directions, all
   timeframes (pf 0.17–0.38). The hammer pattern has no predictive power there.
2. The only thing that looks mildly positive — **2026 short side (gross +0.1…+0.9)** — appears
   **only in the strong-downtrend year and vanishes in 2025**. It is therefore a
   **downtrend/momentum regime artifact, not a hammer edge**: in a falling market "sell the
   bounce" on any trigger looks okay, but the inverted-hammer shape adds nothing (it is
   net-negative in 2025).
3. Even that 2026 short "edge" (+0.9 gross) does **not clear the ~2.4-pt cost** (net −1.4).

**Bottom line: hammer / inverted-hammer reversals are not a robust, cost-survivable edge on
IMOEXF across 1m–60m and across 2025–2026.** This matches the Si result and the project's
prior audit (only ORB + pairs survive real costs).

## Hammer as a trend-continuation trigger — also fails

Tested taking hammers ONLY in the direction of the EMA-100 regime (bull hammer in
uptrend / inverted hammer in downtrend) vs against-trend vs no filter. "With-trend" is
the least-bad but still **gross-negative on both train and test, all timeframes**
(5m: gross −0.3 train / −0.4 test). The hammer adds nothing in any orientation.

## What the data DOES support — momentum, not reversal

Replacing the hammer trigger with a plain **with-trend breakout** (enter on break of the
N-bar extreme when price is on the trend side of the EMA) — same exits, same cost — flips
the sign:

| TF | strategy | 2025 GROSS | 2026 GROSS | test pf |
|---|---|---|---|---|
| 15m | with-trend breakout | +1.0 | +0.4 | 0.54 |
| 60m | with-trend breakout | +2.2 | +0.9 | 0.77 |

This is the **only configuration with a regime-robust positive gross edge in BOTH years**.
The hammer was actively hurting — remove it and an edge appears.

⚠️ **Overfitting caveat:** optimizing the breakout grid on TRAIN-2025 produces gorgeous
in-sample numbers (60m: net +6.5/trade, pf 1.5) that **collapse out-of-sample** (test net
−1.8, pf 0.82). The trustworthy signal is the *un-optimized* gross edge (~+1–2 pts, both
years), NOT the train-best net. Even that gross edge does not reliably clear IMOEXF's
~2.4-pt cost intraday.

**Recommendation:** drop hammer reversals entirely. If pursuing IMOEXF, build on
**trend/momentum breakout with a regime filter** (which the project's ORB already embodies
— and ORB is one of the audited cost-survivors). The edge is thin vs cost, so favour
higher timeframe / cheaper execution, and validate strictly out-of-sample (the in-sample
optimum lies).

Artifacts: `data/processed/IMOEXF_1m_2025_2026.csv`, analysis modules in session scratchpad
(`analyze_hammer.py`, `trend.py`).
