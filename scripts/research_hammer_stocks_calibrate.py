"""Grid search for Hammer SELL params on SBER and GAZP.

Baseline params (balanced) give WR=22% on SBER/GAZP — need calibration.
Key issue: these stocks have very tight 1m candle geometry (range ~0.04-0.06 rub),
so body/wick ratios differ from Si futures.

Grid over:
  - body_min_frac: 0.10, 0.12, 0.15
  - body_max_frac: 0.33, 0.45, 0.55
  - wick_mult: 1.8, 2.3, 3.0
  - min_excursion_ticks: 1.0, 2.0, 3.0

Fixed: tick_size per instrument, take_r=1.0, max_hold_bars=500
"""
from __future__ import annotations

import sys
import dataclasses
import itertools
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_params, HammerParams
from src.strategy.hammer_detector import HammerDetector
from src.backtest.engine import run_backtest

HAMMER_CONFIG = "configs/hammer_detector_balanced.env"
POINT_VALUE_RUB = 1.0
COMMISSION_PER_TRADE = 0.05

TICKERS = [
    ("SBER",  "data/raw/tbank/SBER_1m_2026-01-15_2026-04-10.csv",  0.01),
    ("GAZP",  "data/raw/tbank/GAZP_1m_2026-01-15_2026-04-10.csv",  0.01),
]

GRID = {
    "body_min_frac":      [0.10, 0.12, 0.15],
    "body_max_frac":      [0.33, 0.45, 0.55],
    "wick_mult":          [1.8, 2.3, 3.0],
    "min_excursion_ticks":[1.0, 2.0, 3.0],
}

MIN_TRADES = 30  # ignore scenarios with too few trades


def _load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def run_scenario(df: pd.DataFrame, params: HammerParams, ticker: str, tick_size: float) -> dict:
    params = dataclasses.replace(params, tick_size=tick_size)
    detector = HammerDetector(params)
    debug_df = detector.detect_all(df, instrument=ticker, timeframe="1m", profile="grid")
    trades_df = run_backtest(
        debug_df,
        entry_mode="breakout",
        entry_horizon_bars=3,
        max_hold_bars=500,
        take_r=1.0,
        stop_buffer_points=0.0,
        point_value_rub=POINT_VALUE_RUB,
        commission_per_trade=COMMISSION_PER_TRADE,
        direction_filter="SELL",
    )
    closed = trades_df[trades_df["status"] == "closed"]
    if len(closed) < MIN_TRADES:
        return None
    pnl = closed["net_pnl_rub"]
    wins = (pnl > 0).sum()
    gw = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = round(gw / gl, 3) if gl > 0 else float("inf")
    return {
        "trades": len(closed),
        "wr%": round(wins / len(closed) * 100, 1),
        "PF": pf,
        "net_rub": round(pnl.sum(), 2),
    }


def main():
    base_params = load_params(HAMMER_CONFIG)

    keys = list(GRID.keys())
    values = list(GRID.values())
    combos = list(itertools.product(*values))
    total = len(combos)
    print(f"Grid size: {total} combinations")

    lines = [
        "# Hammer SELL Calibration: SBER and GAZP",
        f"*Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        f"*Grid: {total} combinations × 2 tickers*",
        f"*Min trades filter: {MIN_TRADES}*",
        "",
    ]

    for ticker, csv_path, tick_size in TICKERS:
        print(f"\n=== {ticker} (tick={tick_size}) ===")
        df = _load(csv_path)
        days = df["timestamp"].apply(lambda t: t.tz_convert("Europe/Moscow").date()).nunique()
        print(f"  {len(df)} candles, {days} days")

        results = []
        for i, combo in enumerate(combos):
            if i % 50 == 0:
                print(f"  combo {i}/{total}...", flush=True)
            params = dataclasses.replace(
                base_params,
                **dict(zip(keys, combo))
            )
            res = run_scenario(df, params, ticker, tick_size)
            if res is not None:
                results.append({**dict(zip(keys, combo)), **res})

        if not results:
            lines.append(f"## {ticker}: no scenarios with ≥{MIN_TRADES} trades")
            lines.append("")
            continue

        res_df = pd.DataFrame(results)
        best = res_df.sort_values("PF", ascending=False).head(10)

        print(f"  {len(results)} valid scenarios, best PF={best.iloc[0]['PF']}")
        lines.append(f"## {ticker} — Top 10 by Profit Factor")
        lines.append(f"*{len(results)} valid scenarios (≥{MIN_TRADES} trades)*")
        lines.append("")
        lines.append(best.to_markdown(index=False))
        lines.append("")

        # also show best by WR
        best_wr = res_df.sort_values("wr%", ascending=False).head(5)
        lines.append(f"### {ticker} — Top 5 by Win Rate")
        lines.append(best_wr.to_markdown(index=False))
        lines.append("")

    Path("reports").mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"reports/research_hammer_stocks_calibrate_{ts}.md"
    with open(out_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\nReport saved: {out_path}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
