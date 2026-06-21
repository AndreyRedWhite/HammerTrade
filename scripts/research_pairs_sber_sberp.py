"""Stat-arb pairs backtest: SBER (ordinary) vs SBERP (preferred).

Market-neutral mean-reversion of the pref/ordinary spread.
Spread = log(SBERP) - log(SBER)  (= log of the pref/ord ratio).
Rolling z-score → enter on |z|>entry, exit on |z|<exit or |z|>stop or time-stop.

Both legs are the same issuer → structurally cointegrated (not spurious).
Train: Jan 15 – Apr 10 2026.  OOS: May 2026.

Diagnostics: spread mean/std, mean-reversion half-life (AR(1)).
PnL: dollar-neutral, fixed RUB notional per leg, commission + slippage on BOTH legs.

Outputs reports/research_pairs_sber_sberp_<ts>.md
"""
from __future__ import annotations

import sys
import itertools
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LEG_Y = "SBERP"   # dependent leg (we quote spread as logY - logX)
LEG_X = "SBER"

TRAIN = {
    "SBERP": "data/raw/tbank/SBERP_1m_2026-01-15_2026-04-10.csv",
    "SBER":  "data/raw/tbank/SBER_1m_2026-01-15_2026-04-10.csv",
}
OOS = {
    "SBERP": "data/raw/tbank/SBERP_1m_2026-05-01_2026-05-30.csv",
    "SBER":  "data/raw/tbank/SBER_1m_2026-05-01_2026-05-30.csv",
}

NOTIONAL_PER_LEG = 100_000.0   # RUB per leg
COMMISSION_BPS = 2.5           # per leg per side (entry+exit => ×2 per leg); ~0.025% T-Bank-ish
SLIPPAGE_BPS = 1.0            # per leg per side, bid/ask half-spread proxy

# Module-level cost knob (overridden by cost-sensitivity loop)
_COST_BPS_OVERRIDE = None      # if set, used instead of COMMISSION_BPS+SLIPPAGE_BPS


# ──────────────────────────────────────────────────────────────────────────────
# Data
# ──────────────────────────────────────────────────────────────────────────────

def _load_leg(path: str, timeframe: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").set_index("timestamp")
    if timeframe != "1min":
        df = df.resample(timeframe).agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}
        ).dropna(subset=["close"])
    return df


def build_pair(paths: dict, timeframe: str) -> pd.DataFrame:
    y = _load_leg(paths[LEG_Y], timeframe)[["open", "close"]].rename(
        columns={"open": "y_open", "close": "y_close"})
    x = _load_leg(paths[LEG_X], timeframe)[["open", "close"]].rename(
        columns={"open": "x_open", "close": "x_close"})
    pair = y.join(x, how="inner").dropna()
    pair["spread"] = np.log(pair["y_close"]) - np.log(pair["x_close"])
    return pair


# ──────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ──────────────────────────────────────────────────────────────────────────────

def half_life(spread: pd.Series) -> float:
    """AR(1) mean-reversion half-life in bars. inf if non-mean-reverting."""
    s = spread.dropna()
    s_lag = s.shift(1).dropna()
    s_ret = (s - s.shift(1)).dropna()
    s_lag = s_lag.loc[s_ret.index]
    if len(s_lag) < 10:
        return float("inf")
    beta = np.polyfit(s_lag.values, s_ret.values, 1)[0]  # Δs = a + beta·s_{-1}
    if beta >= 0:
        return float("inf")
    phi = 1 + beta
    if phi <= 0:
        return 0.0
    return float(-np.log(2) / np.log(phi))


# ──────────────────────────────────────────────────────────────────────────────
# Backtest
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PairParams:
    z_window: int
    entry_z: float
    exit_z: float
    stop_z: float
    max_hold_bars: int


def backtest(pair: pd.DataFrame, p: PairParams) -> pd.DataFrame:
    """One open pair-position at a time. Execute at NEXT bar open (no lookahead)."""
    df = pair.copy()
    df["mu"] = df["spread"].rolling(p.z_window).mean()
    df["sd"] = df["spread"].rolling(p.z_window).std()
    df["z"] = (df["spread"] - df["mu"]) / df["sd"]

    idx = df.index
    n = len(df)
    pos = 0            # +1 = long spread (long Y short X), -1 = short spread, 0 flat
    entry_i = None
    entry_y = entry_x = None
    trades = []

    cost_bps = _COST_BPS_OVERRIDE if _COST_BPS_OVERRIDE is not None \
        else (COMMISSION_BPS + SLIPPAGE_BPS)  # per leg per side

    for i in range(n - 1):
        z = df["z"].iloc[i]
        if np.isnan(z):
            continue
        nxt = i + 1  # execution bar

        if pos == 0:
            if z >= p.entry_z:
                pos = -1  # spread too high → short Y, long X
            elif z <= -p.entry_z:
                pos = +1  # spread too low → long Y, short X
            if pos != 0:
                entry_i = nxt
                entry_y = df["y_open"].iloc[nxt]
                entry_x = df["x_open"].iloc[nxt]
        else:
            held = nxt - entry_i
            exit_now = (abs(z) <= p.exit_z) or (abs(z) >= p.stop_z) or (held >= p.max_hold_bars)
            if exit_now:
                exit_y = df["y_open"].iloc[nxt]
                exit_x = df["x_open"].iloc[nxt]
                # leg returns (signed by position): long spread = +Y -X
                y_ret = (exit_y / entry_y - 1.0) * pos
                x_ret = (exit_x / entry_x - 1.0) * (-pos)
                gross = (y_ret + x_ret) * NOTIONAL_PER_LEG
                # costs: 2 legs × entry+exit = 4 sides
                costs = 4 * (cost_bps / 1e4) * NOTIONAL_PER_LEG
                net = gross - costs
                reason = ("EXIT_MEAN" if abs(z) <= p.exit_z
                          else "STOP_DIVERGE" if abs(z) >= p.stop_z
                          else "TIME")
                trades.append({
                    "entry_ts": idx[entry_i], "exit_ts": idx[nxt],
                    "direction": "LONG_SPREAD" if pos == 1 else "SHORT_SPREAD",
                    "held_bars": held, "gross_rub": gross, "net_rub": net,
                    "reason": reason,
                })
                pos = 0
                entry_i = entry_y = entry_x = None

    return pd.DataFrame(trades)


def summarize(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0, "wr%": 0.0, "PF": 0.0, "net_rub": 0.0,
                "avg_hold": 0.0, "top3%": 0.0}
    pnl = trades["net_rub"]
    wins = (pnl > 0).sum()
    gw = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = round(gw / gl, 3) if gl > 0 else float("inf")
    top3 = pnl.nlargest(3).sum()
    top3_pct = round(top3 / pnl.sum() * 100, 1) if pnl.sum() > 0 else float("inf")
    return {
        "trades": len(trades),
        "wr%": round(wins / len(trades) * 100, 1),
        "PF": pf,
        "net_rub": round(pnl.sum(), 0),
        "avg_hold": round(trades["held_bars"].mean(), 1),
        "top3%": top3_pct,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    timeframes = ["15min", "60min"]
    grid = {
        "z_window": [50, 100],
        "entry_z": [2.0, 2.5],
        "exit_z": [0.0, 0.5],
    }
    STOP_Z = 4.0
    # max_hold in bars ≈ a few trading days; set per-timeframe below

    lines = [
        "# Stat-Arb Pairs Backtest: SBER / SBERP",
        f"*Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        f"*Spread = log(SBERP) − log(SBER). Train Jan15–Apr10, OOS May 2026.*",
        f"*Notional {NOTIONAL_PER_LEG:,.0f} RUB/leg; cost {COMMISSION_BPS}+{SLIPPAGE_BPS}bps/leg/side.*",
        "",
    ]

    for tf in timeframes:
        print(f"\n=== timeframe {tf} ===")
        pair_train = build_pair(TRAIN, tf)
        pair_oos = build_pair(OOS, tf)
        print(f"  train bars: {len(pair_train)}, oos bars: {len(pair_oos)}")

        # bars per trading day ~ (9h session)/tf
        bars_per_day = int(9 * 60 / int(tf.replace("min", "")))
        max_hold = bars_per_day * 5  # ~5 trading days

        # diagnostics on train
        sp = pair_train["spread"]
        hl = half_life(sp)
        disc_mean = (np.exp(sp.mean()) - 1) * 100  # mean pref/ord premium in %
        disc_std = sp.std() * 100
        lines.append(f"## Timeframe {tf}")
        lines.append(
            f"- Train spread: mean pref/ord ratio premium = {disc_mean:.2f}%, "
            f"log-spread std = {disc_std:.3f}%, **half-life = {hl:.1f} bars "
            f"(~{hl/bars_per_day:.1f} trading days)**"
        )
        lines.append(f"- max_hold_bars = {max_hold} (~5 trading days), stop_z = {STOP_Z}")
        lines.append("")

        keys = list(grid.keys())
        combos = list(itertools.product(*grid.values()))
        rows_train, rows_oos = [], []
        for combo in combos:
            params = dict(zip(keys, combo))
            p = PairParams(max_hold_bars=max_hold, stop_z=STOP_Z, **params)
            tr_train = backtest(pair_train, p)
            tr_oos = backtest(pair_oos, p)
            st = summarize(tr_train)
            so = summarize(tr_oos)
            label = f"zw{params['z_window']}_e{params['entry_z']}_x{params['exit_z']}"
            rows_train.append({"scenario": label, **st})
            rows_oos.append({"scenario": label, **so})

        tdf = pd.DataFrame(rows_train).sort_values("PF", ascending=False)
        odf = pd.DataFrame(rows_oos).set_index("scenario")

        # attach OOS columns next to train for the same scenario
        merged = tdf.copy()
        merged["oos_trades"] = merged["scenario"].map(odf["trades"])
        merged["oos_PF"] = merged["scenario"].map(odf["PF"])
        merged["oos_net"] = merged["scenario"].map(odf["net_rub"])
        merged["oos_wr%"] = merged["scenario"].map(odf["wr%"])

        lines.append("### Train (sorted by PF) with OOS side-by-side")
        lines.append(merged.to_markdown(index=False))
        lines.append("")

    # ── Cost sensitivity on best 60m config (zw50, e2.0, x0.0) ────────────────
    global _COST_BPS_OVERRIDE
    lines.append("## Cost sensitivity — best 60min config (zw50, entry2.0, exit0.0)")
    lines.append("*Edge must survive realistic costs. cost_bps = per leg per side; "
                 "round-turn pair cost = 4 × cost_bps.*")
    lines.append("")
    pair_train_60 = build_pair(TRAIN, "60min")
    pair_oos_60 = build_pair(OOS, "60min")
    bp_day_60 = int(9 * 60 / 60)
    p_best = PairParams(z_window=50, entry_z=2.0, exit_z=0.0,
                        stop_z=4.0, max_hold_bars=bp_day_60 * 5)
    cost_rows = []
    for cb in [1.0, 2.0, 3.5, 5.0, 7.5, 10.0]:
        _COST_BPS_OVERRIDE = cb
        st = summarize(backtest(pair_train_60, p_best))
        so = summarize(backtest(pair_oos_60, p_best))
        cost_rows.append({
            "cost_bps/leg/side": cb,
            "rt_pair_bps": cb * 4,
            "train_PF": st["PF"], "train_net": st["net_rub"],
            "oos_PF": so["PF"], "oos_net": so["net_rub"],
        })
    _COST_BPS_OVERRIDE = None
    lines.append(pd.DataFrame(cost_rows).to_markdown(index=False))
    lines.append("")

    Path("reports").mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"reports/research_pairs_sber_sberp_{ts}.md"
    with open(out_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\nReport saved: {out_path}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
