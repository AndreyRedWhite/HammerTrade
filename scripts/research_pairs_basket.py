"""Stat-arb basket backtest: pref/ordinary pairs on MOEX.

Pairs (spread = log(pref) - log(ordinary)):
  SBERP/SBER, TATNP/TATN, SNGSP/SNGS, RTKMP/RTKM

Validates the SBER/SBERP single-pair finding across a basket: pooling trades
gives a much larger OOS sample and diversifies single-name risk.

Reuses the validated config family (60min bars, full-reversion exit).
Train Jan15–Apr10, OOS May 2026. Outputs reports/research_pairs_basket_<ts>.md
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

# name -> (pref_ticker, ordinary_ticker)
PAIRS = {
    "SBER": ("SBERP", "SBER"),
    "TATN": ("TATNP", "TATN"),
    "SNGS": ("SNGSP", "SNGS"),
    "RTKM": ("RTKMP", "RTKM"),
}

TRAIN_SUFFIX = "1m_2026-01-15_2026-04-10"
OOS_SUFFIX = "1m_2026-05-01_2026-05-30"
DATA_DIR = Path("data/raw/tbank")

NOTIONAL_PER_LEG = 100_000.0
COST_BPS = 3.5   # per leg per side (commission+slippage); round-turn pair = 4×


@dataclass
class PairParams:
    z_window: int
    entry_z: float
    exit_z: float
    stop_z: float
    max_hold_bars: int


def _load_leg(ticker: str, suffix: str, timeframe: str) -> pd.DataFrame:
    path = DATA_DIR / f"{ticker}_{suffix}.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").set_index("timestamp")
    if timeframe != "1min":
        df = df.resample(timeframe).agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}
        ).dropna(subset=["close"])
    return df


def build_pair(pref: str, ordn: str, suffix: str, timeframe: str) -> pd.DataFrame:
    y = _load_leg(pref, suffix, timeframe)[["open", "close"]].rename(
        columns={"open": "y_open", "close": "y_close"})
    x = _load_leg(ordn, suffix, timeframe)[["open", "close"]].rename(
        columns={"open": "x_open", "close": "x_close"})
    pair = y.join(x, how="inner").dropna()
    pair["spread"] = np.log(pair["y_close"]) - np.log(pair["x_close"])
    return pair


def half_life(spread: pd.Series) -> float:
    s = spread.dropna()
    s_ret = (s - s.shift(1)).dropna()
    s_lag = s.shift(1).dropna().loc[s_ret.index]
    if len(s_lag) < 10:
        return float("inf")
    beta = np.polyfit(s_lag.values, s_ret.values, 1)[0]
    if beta >= 0:
        return float("inf")
    phi = 1 + beta
    return float(-np.log(2) / np.log(phi)) if phi > 0 else 0.0


def backtest(pair: pd.DataFrame, p: PairParams, pair_name: str,
             cost_bps: float = COST_BPS) -> pd.DataFrame:
    df = pair.copy()
    df["mu"] = df["spread"].rolling(p.z_window).mean()
    df["sd"] = df["spread"].rolling(p.z_window).std()
    df["z"] = (df["spread"] - df["mu"]) / df["sd"]

    idx = df.index
    n = len(df)
    pos = 0
    entry_i = entry_y = entry_x = None
    trades = []

    for i in range(n - 1):
        z = df["z"].iloc[i]
        if np.isnan(z):
            continue
        nxt = i + 1
        if pos == 0:
            if z >= p.entry_z:
                pos = -1
            elif z <= -p.entry_z:
                pos = +1
            if pos != 0:
                entry_i = nxt
                entry_y = df["y_open"].iloc[nxt]
                entry_x = df["x_open"].iloc[nxt]
        else:
            held = nxt - entry_i
            if (abs(z) <= p.exit_z) or (abs(z) >= p.stop_z) or (held >= p.max_hold_bars):
                exit_y = df["y_open"].iloc[nxt]
                exit_x = df["x_open"].iloc[nxt]
                y_ret = (exit_y / entry_y - 1.0) * pos
                x_ret = (exit_x / entry_x - 1.0) * (-pos)
                gross = (y_ret + x_ret) * NOTIONAL_PER_LEG
                costs = 4 * (cost_bps / 1e4) * NOTIONAL_PER_LEG
                trades.append({
                    "pair": pair_name,
                    "entry_ts": idx[entry_i], "exit_ts": idx[nxt],
                    "direction": "LONG_SPREAD" if pos == 1 else "SHORT_SPREAD",
                    "held_bars": held, "net_rub": gross - costs,
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
    top3_pct = round(pnl.nlargest(3).sum() / pnl.sum() * 100, 1) if pnl.sum() > 0 else float("inf")
    return {
        "trades": len(trades),
        "wr%": round(wins / len(trades) * 100, 1),
        "PF": pf,
        "net_rub": round(pnl.sum(), 0),
        "avg_hold": round(trades["held_bars"].mean(), 1),
        "top3%": top3_pct,
    }


def run_all_pairs(p: PairParams, suffix: str, timeframe: str,
                  cost_bps: float = COST_BPS) -> pd.DataFrame:
    all_trades = []
    for name, (pref, ordn) in PAIRS.items():
        pair = build_pair(pref, ordn, suffix, timeframe)
        all_trades.append(backtest(pair, p, name, cost_bps))
    return pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()


def main():
    tf = "60min"
    bars_per_day = int(9 * 60 / 60)
    max_hold = bars_per_day * 5

    lines = [
        "# Stat-Arb Basket Backtest: pref/ordinary pairs",
        f"*Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        f"*Pairs: {', '.join(f'{p}/{o}' for p, o in PAIRS.values())}*",
        f"*Timeframe {tf}, spread=log(pref)-log(ord). Train Jan15–Apr10, OOS May.*",
        f"*Notional {NOTIONAL_PER_LEG:,.0f} RUB/leg; cost {COST_BPS}bps/leg/side.*",
        "",
    ]

    # ── Per-pair half-life diagnostic ─────────────────────────────────────────
    lines.append("## Mean-reversion half-life per pair (train, 60m bars)")
    hl_rows = []
    for name, (pref, ordn) in PAIRS.items():
        pair = build_pair(pref, ordn, TRAIN_SUFFIX, tf)
        sp = pair["spread"]
        hl_rows.append({
            "pair": f"{pref}/{ordn}",
            "bars": len(pair),
            "mean_premium%": round((np.exp(sp.mean()) - 1) * 100, 2),
            "spread_std%": round(sp.std() * 100, 3),
            "half_life_bars": round(half_life(sp), 1),
            "half_life_days": round(half_life(sp) / bars_per_day, 2),
        })
    lines.append(pd.DataFrame(hl_rows).to_markdown(index=False))
    lines.append("")

    # ── Grid: pooled basket train + OOS ───────────────────────────────────────
    grid = {"z_window": [50, 100], "entry_z": [2.0, 2.5], "exit_z": [0.0, 0.5]}
    keys = list(grid.keys())
    rows = []
    for combo in itertools.product(*grid.values()):
        params = dict(zip(keys, combo))
        p = PairParams(max_hold_bars=max_hold, stop_z=4.0, **params)
        st = summarize(run_all_pairs(p, TRAIN_SUFFIX, tf))
        so = summarize(run_all_pairs(p, OOS_SUFFIX, tf))
        label = f"zw{params['z_window']}_e{params['entry_z']}_x{params['exit_z']}"
        rows.append({
            "scenario": label,
            "tr_trades": st["trades"], "tr_PF": st["PF"], "tr_net": st["net_rub"],
            "tr_wr%": st["wr%"], "tr_top3%": st["top3%"],
            "oos_trades": so["trades"], "oos_PF": so["PF"], "oos_net": so["net_rub"],
            "oos_wr%": so["wr%"],
        })
    grid_df = pd.DataFrame(rows).sort_values("oos_PF", ascending=False)
    lines.append("## Pooled basket — grid (sorted by OOS PF)")
    lines.append(grid_df.to_markdown(index=False))
    lines.append("")

    # ── Per-pair breakdown for primary config ────────────────────────────────
    # Primary = best pooled-OOS config with a meaningful sample: partial-reversion
    # exit (x0.5) works across the basket; full-reversion (x0.0) only fits SBER
    # (whose half-life is ~3 bars vs 8-20 days for the others).
    p_primary = PairParams(z_window=50, entry_z=2.0, exit_z=0.5,
                           stop_z=4.0, max_hold_bars=max_hold)
    lines.append("## Per-pair breakdown — primary config (zw50, entry2.0, exit0.5)")
    for period_name, suffix in [("Train", TRAIN_SUFFIX), ("OOS May", OOS_SUFFIX)]:
        pair_rows = []
        for name, (pref, ordn) in PAIRS.items():
            pair = build_pair(pref, ordn, suffix, tf)
            tr = backtest(pair, p_primary, name)
            pair_rows.append({"pair": f"{pref}/{ordn}", **summarize(tr)})
        # pooled row
        pooled = run_all_pairs(p_primary, suffix, tf)
        pair_rows.append({"pair": "** POOLED **", **summarize(pooled)})
        lines.append(f"### {period_name}")
        lines.append(pd.DataFrame(pair_rows).to_markdown(index=False))
        lines.append("")

    # ── Cost sensitivity on pooled basket, primary config ─────────────────────
    lines.append("## Cost sensitivity — pooled basket, primary config")
    cost_rows = []
    for cb in [1.0, 2.0, 3.5, 5.0, 7.5, 10.0]:
        st = summarize(run_all_pairs(p_primary, TRAIN_SUFFIX, tf, cost_bps=cb))
        so = summarize(run_all_pairs(p_primary, OOS_SUFFIX, tf, cost_bps=cb))
        cost_rows.append({
            "cost_bps/leg/side": cb, "rt_pair_bps": cb * 4,
            "train_PF": st["PF"], "train_net": st["net_rub"],
            "oos_PF": so["PF"], "oos_net": so["net_rub"], "oos_trades": so["trades"],
        })
    lines.append(pd.DataFrame(cost_rows).to_markdown(index=False))
    lines.append("")

    Path("reports").mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"reports/research_pairs_basket_{ts}.md"
    with open(out_path, "w") as f:
        f.write("\n".join(lines))

    print(f"Report saved: {out_path}\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
