"""Hammer SELL backtest on SBER, SBERP, GAZP, LKOH candle data.

Uses the same HammerDetector params as the SiM6 balanced config.
Point value for stocks = 1 rub/unit (stock trades in whole lots).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MSK = ZoneInfo("Europe/Moscow")

HAMMER_CONFIG = "configs/hammer_detector_balanced.env"
POINT_VALUE_RUB = 1.0       # stocks: 1 lot = 10 shares, but PnL in rub per point = 1
COMMISSION_PER_TRADE = 0.05  # ~0.05% round turn ≈ rough estimate

# (ticker, csv_path, tick_size)
# MOEX tick sizes: SBER/GAZP/SBERP = 0.01р, LKOH = 0.50р (price > 2000р)
TICKERS = [
    ("SBER",  "data/raw/tbank/SBER_1m_2026-01-15_2026-04-10.csv",  0.01),
    ("SBERP", "data/raw/tbank/SBERP_1m_2026-01-15_2026-04-10.csv", 0.01),
    ("GAZP",  "data/raw/tbank/GAZP_1m_2026-01-15_2026-04-10.csv",  0.01),
    ("LKOH",  "data/raw/tbank/LKOH_1m_2026-01-15_2026-04-10.csv",  0.50),
]


def _load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def run_hammer_backtest(df: pd.DataFrame, ticker: str, tick_size: float) -> dict:
    from src.config import load_params
    from src.strategy.hammer_detector import HammerDetector
    from src.backtest.engine import run_backtest
    import dataclasses

    params = load_params(HAMMER_CONFIG)
    params = dataclasses.replace(params, tick_size=tick_size)
    detector = HammerDetector(params)

    print(f"  [{ticker}] detect_all on {len(df)} candles...")
    debug_df = detector.detect_all(df, instrument=ticker, timeframe="1m", profile="balanced")

    signal_mask = debug_df["is_signal"].astype(bool) & (debug_df["fail_reason"].astype(str) == "pass")
    total_signals = signal_mask.sum()
    direction_counts = debug_df[signal_mask]["direction_candidate"].value_counts().to_dict()
    print(f"  [{ticker}] signals: {total_signals} {direction_counts}")

    results = {}
    for direction in ("SELL", "BUY", "all"):
        trades_df = run_backtest(
            debug_df,
            entry_mode="breakout",
            entry_horizon_bars=3,
            max_hold_bars=500,
            take_r=1.0,
            stop_buffer_points=0.0,
            point_value_rub=POINT_VALUE_RUB,
            commission_per_trade=COMMISSION_PER_TRADE,
            direction_filter=direction,
        )
        closed = trades_df[trades_df["status"] == "closed"]
        if closed.empty:
            results[direction] = {"trades": 0, "wr%": 0.0, "PF": 0.0, "net_rub": 0.0}
            continue
        pnl = closed["net_pnl_rub"]
        wins = (pnl > 0).sum()
        gw = pnl[pnl > 0].sum()
        gl = abs(pnl[pnl <= 0].sum())
        pf = round(gw / gl, 3) if gl > 0 else float("inf")
        results[direction] = {
            "trades": len(closed),
            "wr%": round(wins / len(closed) * 100, 1),
            "PF": pf,
            "net_rub": round(pnl.sum(), 2),
        }
    return results


def main():
    lines = [
        "# Research: Hammer SELL/BUY on SBER, SBERP, GAZP, LKOH",
        f"*Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        f"*Data: Jan 15 – Apr 10, 2026*",
        f"*Config: {HAMMER_CONFIG} (same as SiM6 baseline)*",
        f"*Note: PnL in rub assuming point_value=1 rub, commission={COMMISSION_PER_TRADE*2:.3f} rub/trade*",
        "",
    ]

    all_rows = []
    for ticker, csv_path, tick_size in TICKERS:
        print(f"\n{ticker} (tick={tick_size})...")
        try:
            df = _load(csv_path)
            days = df["timestamp"].apply(lambda t: t.astimezone(MSK).date()).nunique()
            print(f"  {len(df)} candles, {days} days")
            results = run_hammer_backtest(df, ticker, tick_size)
            for direction, r in results.items():
                all_rows.append({"ticker": ticker, "direction": direction, **r})
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback; traceback.print_exc()
            all_rows.append({"ticker": ticker, "direction": "ERROR", "trades": 0,
                             "wr%": 0, "PF": 0, "net_rub": str(e)})

    if all_rows:
        result_df = pd.DataFrame(all_rows)
        sell_df = result_df[result_df["direction"] == "SELL"]
        buy_df  = result_df[result_df["direction"] == "BUY"]
        all_df  = result_df[result_df["direction"] == "all"]

        lines.append("## SELL direction")
        lines.append(sell_df.drop(columns=["direction"]).to_markdown(index=False))
        lines.append("")
        lines.append("## BUY direction")
        lines.append(buy_df.drop(columns=["direction"]).to_markdown(index=False))
        lines.append("")
        lines.append("## Both directions combined")
        lines.append(all_df.drop(columns=["direction"]).to_markdown(index=False))
        lines.append("")

        lines.append("## Notes")
        lines.append("- PF = profit factor (gross wins / gross losses)")
        lines.append("- net_rub is approximate — point_value=1 rub/tick, which understates")
        lines.append("  actual rub PnL. For comparison, scale: SBER ~330rub/share,")
        lines.append("  LKOH ~7500 rub/share. Net_rub in this table = points × 1 rub.")
        lines.append("")

    Path("reports").mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"reports/research_hammer_stocks_{ts}.md"
    with open(out_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\nReport saved: {out_path}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
