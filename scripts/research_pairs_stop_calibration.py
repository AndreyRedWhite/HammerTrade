"""Calibrate --stop-loss-bps for the live pairs core (TATN+RTKM @1h).

The live PnL-space stop (commit a56746a) is provisionally 300 bps of one leg's
notional. That level was a guess: exit-only journal data can't show trades that
dipped past a stop and RECOVERED, so it needs a bar-by-bar backtest — this script.

Method (matches the live engine's exit semantics):
  * mark each open trade to bar CLOSE, net of the full round-trip cost, each bar;
  * a trade's MAE = its worst such mark, in bps of one leg's notional;
  * the stop fires when the mark <= -stop_bps (checked before EXIT_MEAN), filling
    at the next bar open (same convention as the rest of the backtest).

Two questions answered:
  1. MAE distribution of winners vs losers → where do healthy trades bottom out,
     and do losers blow through that? (the stop wants to sit just past winners.)
  2. Stop grid → pooled net / PF / #stopped, train vs OOS. net_with_stop minus
     net_no_stop = the stop's real contribution (loss-saved minus recovery-killed).

Only TATN+RTKM (SBER/SNGS were dropped). Train Jan15–Apr10, OOS May 2026.
Outputs reports/research_pairs_stop_calibration_<ts>.md
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.research_pairs_basket import build_pair, PairParams, TRAIN_SUFFIX, OOS_SUFFIX

# The live working core only.
PAIRS = {
    "TATN": ("TATNP", "TATN"),
    "RTKM": ("RTKMP", "RTKM"),
}

NOTIONAL_PER_LEG = 100_000.0
COST_BPS = 5.0   # per leg per side — the confirmed live commission (round-turn pair = 4x)
TF = "60min"

# Live primary config (hammertrade-*-pairs-*): zw50, entry2.0, exit0.5, stop_z4, max_hold 45.
PRIMARY = PairParams(z_window=50, entry_z=2.0, exit_z=0.5, stop_z=4.0, max_hold_bars=45)

STOP_GRID_BPS = [None, 400, 300, 250, 200, 150, 125, 100, 75, 50]


def backtest_with_mae(pair: pd.DataFrame, p: PairParams, pair_name: str,
                      cost_bps: float = COST_BPS, stop_loss_bps=None) -> pd.DataFrame:
    """Bar-by-bar backtest that records each trade's MAE and honours a PnL-space stop."""
    df = pair.copy()
    df["mu"] = df["spread"].rolling(p.z_window).mean()
    df["sd"] = df["spread"].rolling(p.z_window).std()
    df["z"] = (df["spread"] - df["mu"]) / df["sd"]

    idx = df.index
    n = len(df)
    costs = 4 * (cost_bps / 1e4) * NOTIONAL_PER_LEG
    stop_rub = abs(stop_loss_bps) / 1e4 * NOTIONAL_PER_LEG if stop_loss_bps is not None else None

    pos = 0
    entry_i = entry_y = entry_x = None
    mae = 0.0
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
                mae = 0.0
        else:
            held = nxt - entry_i
            # mark to THIS bar's close, net of the round-trip cost (as the live engine does)
            yc, xc = df["y_close"].iloc[i], df["x_close"].iloc[i]
            unreal = ((yc / entry_y - 1.0) * pos + (xc / entry_x - 1.0) * (-pos)) * NOTIONAL_PER_LEG - costs
            mae = min(mae, unreal)

            reason = None
            if stop_rub is not None and unreal <= -stop_rub:
                reason = "STOP_LOSS"
            elif abs(z) <= p.exit_z:
                reason = "EXIT_MEAN"
            elif abs(z) >= p.stop_z:
                reason = "STOP_DIVERGE"
            elif held >= p.max_hold_bars:
                reason = "TIME"

            if reason:
                exit_y, exit_x = df["y_open"].iloc[nxt], df["x_open"].iloc[nxt]
                gross = ((exit_y / entry_y - 1.0) * pos + (exit_x / entry_x - 1.0) * (-pos)) * NOTIONAL_PER_LEG
                trades.append({
                    "pair": pair_name, "entry_ts": idx[entry_i], "exit_ts": idx[nxt],
                    "direction": "LONG_SPREAD" if pos == 1 else "SHORT_SPREAD",
                    "held_bars": held, "net_rub": gross - costs, "reason": reason,
                    "mae_bps": round(mae / NOTIONAL_PER_LEG * 1e4, 1),
                })
                pos = 0
                entry_i = entry_y = entry_x = None
    return pd.DataFrame(trades)


def run_pairs(suffix: str, stop_loss_bps=None) -> pd.DataFrame:
    out = []
    for name, (pref, ordn) in PAIRS.items():
        pair = build_pair(pref, ordn, suffix, TF)
        out.append(backtest_with_mae(pair, PRIMARY, name, stop_loss_bps=stop_loss_bps))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def summarize(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0, "wr%": 0.0, "PF": 0.0, "net_rub": 0.0, "stopped": 0}
    pnl = trades["net_rub"]
    gw, gl = pnl[pnl > 0].sum(), abs(pnl[pnl <= 0].sum())
    return {
        "trades": len(trades),
        "wr%": round((pnl > 0).mean() * 100, 1),
        "PF": round(gw / gl, 2) if gl > 0 else float("inf"),
        "net_rub": round(pnl.sum(), 0),
        "stopped": int((trades["reason"] == "STOP_LOSS").sum()),
    }


def mae_table(trades: pd.DataFrame) -> pd.DataFrame:
    """MAE percentiles for winners vs losers (under natural, no-stop exits)."""
    rows = []
    for label, mask in [("winners", trades["net_rub"] > 0), ("losers", trades["net_rub"] <= 0)]:
        m = trades.loc[mask, "mae_bps"]
        if m.empty:
            rows.append({"group": label, "n": 0})
            continue
        rows.append({
            "group": label, "n": len(m),
            "mae_p50": round(m.median(), 0), "mae_p25": round(m.quantile(0.25), 0),
            "mae_p10": round(m.quantile(0.10), 0), "mae_min": round(m.min(), 0),
        })
    return pd.DataFrame(rows)


def main():
    lines = [
        "# Pairs stop-loss calibration — TATN+RTKM @1h",
        f"*Generated {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        f"*Config: zw{PRIMARY.z_window} entry{PRIMARY.entry_z} exit{PRIMARY.exit_z} "
        f"stop_z{PRIMARY.stop_z} max_hold{PRIMARY.max_hold_bars}; "
        f"{NOTIONAL_PER_LEG:,.0f}/leg; cost {COST_BPS}bps/leg/side. Train Jan15–Apr10, OOS May.*",
        "*MAE = worst mark-to-close during a trade, in bps of one leg's notional (negative=loss).*",
        "",
    ]

    # ── MAE distribution (natural exits, no stop) ─────────────────────────────
    lines.append("## MAE of winners vs losers (no stop) — where should the stop sit?")
    for period, suffix in [("Train", TRAIN_SUFFIX), ("OOS May", OOS_SUFFIX)]:
        nat = run_pairs(suffix, stop_loss_bps=None)
        lines.append(f"### {period}")
        lines.append(mae_table(nat).to_markdown(index=False))
        lines.append("")

    # ── Stop grid, pooled TATN+RTKM ───────────────────────────────────────────
    lines.append("## Stop-loss grid — pooled TATN+RTKM (net_rub is pooled across both)")
    base_tr = summarize(run_pairs(TRAIN_SUFFIX, None))["net_rub"]
    base_oos = summarize(run_pairs(OOS_SUFFIX, None))["net_rub"]
    rows = []
    for stop in STOP_GRID_BPS:
        st = summarize(run_pairs(TRAIN_SUFFIX, stop))
        so = summarize(run_pairs(OOS_SUFFIX, stop))
        rows.append({
            "stop_bps": "none" if stop is None else stop,
            "tr_net": st["net_rub"], "tr_PF": st["PF"], "tr_stopped": st["stopped"],
            "tr_vs_base": round(st["net_rub"] - base_tr, 0),
            "oos_net": so["net_rub"], "oos_PF": so["PF"], "oos_stopped": so["stopped"],
            "oos_vs_base": round(so["net_rub"] - base_oos, 0),
        })
    lines.append(pd.DataFrame(rows).to_markdown(index=False))
    lines.append("")
    lines.append("*`vs_base` = net minus the no-stop net: positive ⇒ the stop adds money "
                 "(loss cut > recovery killed); negative ⇒ it destroys recovering trades.*")

    Path("reports").mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"reports/research_pairs_stop_calibration_{ts}.md"
    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Report saved: {out_path}\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
