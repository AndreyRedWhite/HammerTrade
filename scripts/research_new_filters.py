"""Research script: ORB range cap, ORB volume filter, Hammer regime filter.

Runs on existing SiM6 1m candle data (train Jan15–Apr10, OOS May 2026).
Outputs markdown report to reports/research_new_filters_<ts>.md
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MSK = ZoneInfo("Europe/Moscow")

TRAIN_CSV = "data/raw/tbank/SiM6_1m_2026-01-15_2026-04-10_balanced.csv"
OOS_CSV   = "data/raw/tbank/SiM6_1m_20260501_20260530.csv"
HAMMER_CONFIG = "configs/hammer_detector_balanced.env"
POINT_VALUE_RUB = 10.0
COMMISSION_PER_TRADE = 0.025

OR_START = time(10, 0)
OR_END   = time(11, 0)
TIME_EXIT = time(18, 40)
MIN_OR_CANDLES = 5
TAKE_R = 2.0


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["msk_dt"] = df["timestamp"].apply(lambda t: t.astimezone(MSK))
    df["msk_date"] = df["msk_dt"].dt.date
    return df


def _compute_or(day_df: pd.DataFrame):
    """Returns (or_high, or_low, or_range, or_vol_avg) or None."""
    or_mask = day_df["msk_dt"].apply(lambda t: OR_START <= t.time() < OR_END)
    or_candles = day_df[or_mask]
    if len(or_candles) < MIN_OR_CANDLES:
        return None
    or_high = float(or_candles["high"].max())
    or_low  = float(or_candles["low"].min())
    or_range = or_high - or_low
    or_vol_avg = float(or_candles["volume"].mean())
    return or_high, or_low, or_range, or_vol_avg


def _simulate_orb_short(entry_price, stop_price, take_price, post_df) -> dict:
    exit_price = exit_reason = None
    for _, c in post_df.iterrows():
        if c["msk_dt"].time() >= TIME_EXIT:
            exit_price = float(c["open"]); exit_reason = "TIME_EXIT"; break
        if float(c["high"]) >= stop_price:
            exit_price = stop_price; exit_reason = "STOP"; break
        if float(c["low"]) <= take_price:
            exit_price = take_price; exit_reason = "TAKE"; break
    if exit_price is None:
        exit_price = float(post_df.iloc[-1]["close"]) if len(post_df) else entry_price
        exit_reason = "TIME_EXIT"
    pnl_pts = entry_price - exit_price
    return {"exit_reason": exit_reason, "pnl_pts": pnl_pts,
            "pnl_rub": pnl_pts * POINT_VALUE_RUB - COMMISSION_PER_TRADE * 2}


def _orb_summary(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for val, g in df.groupby(group_col):
        pnl = g["pnl_rub"]
        wins = (pnl > 0).sum()
        gw = pnl[pnl > 0].sum()
        gl = abs(pnl[pnl <= 0].sum())
        pf = round(gw / gl, 3) if gl > 0 else float("inf")
        rows.append({
            group_col: val,
            "trades": len(g),
            "wr%": round(wins / len(g) * 100, 1),
            "PF": pf,
            "net_rub": round(pnl.sum(), 2),
            "avg_or_range": round(g["or_range"].mean(), 0),
        })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────────
# 1. ORB range cap
# ──────────────────────────────────────────────────────────────────────────────

def run_orb_range_cap(df: pd.DataFrame, caps: list) -> pd.DataFrame:
    rows = []
    for date, day_df in df.groupby("msk_date"):
        day_df = day_df.sort_values("timestamp").reset_index(drop=True)
        or_result = _compute_or(day_df)
        if or_result is None:
            continue
        or_high, or_low, or_range, _ = or_result

        post_or = day_df[day_df["msk_dt"].apply(lambda t: t.time() >= OR_END)].reset_index(drop=True)
        if post_or.empty:
            continue

        entry_row = None
        for _, c in post_or.iterrows():
            if c["msk_dt"].time() >= TIME_EXIT:
                break
            if float(c["low"]) < or_low:
                entry_row = c
                break
        if entry_row is None:
            continue

        entry_price = or_low
        stop_price  = or_high
        take_price  = entry_price - or_range * TAKE_R
        sig_ts = entry_row["timestamp"]
        post_trade = df[df["timestamp"] > sig_ts].reset_index(drop=True)
        trade = _simulate_orb_short(entry_price, stop_price, take_price, post_trade)

        for cap in caps:
            if cap is not None and or_range > cap:
                continue
            rows.append({
                "cap": str(cap) if cap is not None else "no_cap",
                "date": str(date),
                "or_range": or_range,
                **trade,
            })

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────────
# 2. ORB volume filter
# ──────────────────────────────────────────────────────────────────────────────

def run_orb_volume_filter(df: pd.DataFrame, vol_mults: list) -> pd.DataFrame:
    df = df.copy()
    df["vol_avg20"] = df["volume"].rolling(20, min_periods=1).mean()

    rows = []
    for date, day_df in df.groupby("msk_date"):
        day_df = day_df.sort_values("timestamp").reset_index(drop=True)
        or_result = _compute_or(day_df)
        if or_result is None:
            continue
        or_high, or_low, or_range, _ = or_result

        post_or = day_df[day_df["msk_dt"].apply(lambda t: t.time() >= OR_END)].reset_index(drop=True)
        if post_or.empty:
            continue

        for _, c in post_or.iterrows():
            if c["msk_dt"].time() >= TIME_EXIT:
                break
            if float(c["low"]) < or_low:
                entry_price = or_low
                stop_price  = or_high
                take_price  = entry_price - or_range * TAKE_R
                breakout_vol = float(c["volume"])
                vol_avg = float(c["vol_avg20"])

                sig_ts = c["timestamp"]
                post_trade = df[df["timestamp"] > sig_ts].reset_index(drop=True)
                trade = _simulate_orb_short(entry_price, stop_price, take_price, post_trade)

                for vm in vol_mults:
                    if vm > 0 and vol_avg > 0 and breakout_vol < vm * vol_avg:
                        continue
                    rows.append({
                        "vol_mult": f"{vm:.1f}x" if vm > 0 else "no_filter",
                        "date": str(date),
                        "or_range": or_range,
                        "vol_ratio": round(breakout_vol / vol_avg, 2) if vol_avg > 0 else None,
                        **trade,
                    })
                break

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Hammer + regime filter
# ──────────────────────────────────────────────────────────────────────────────

def run_hammer_regime_filter(df: pd.DataFrame, label: str = "") -> dict:
    from src.config import load_params
    from src.strategy.hammer_detector import HammerDetector
    from src.backtest.engine import run_backtest
    from src.research.regime import compute_regime_context

    print(f"  [{label}] Loading HammerParams...")
    params = load_params(HAMMER_CONFIG)
    detector = HammerDetector(params)

    print(f"  [{label}] Running HammerDetector.detect_all()...")
    debug_df = detector.detect_all(df, instrument="SiM6", timeframe="1m", profile="balanced")
    debug_df["timestamp"] = pd.to_datetime(debug_df["timestamp"], utc=True)
    debug_df["msk_date"] = debug_df["timestamp"].apply(
        lambda t: t.astimezone(MSK).date().isoformat()
    )

    print(f"  [{label}] Computing regime context...")
    regime_df = compute_regime_context(df)
    regime_map = {str(row["date"]): row["regime"] for _, row in regime_df.iterrows()}
    debug_df["regime"] = debug_df["msk_date"].map(regime_map).fillna("UNKNOWN")

    signal_mask = debug_df["is_signal"].astype(bool) & (debug_df["fail_reason"].astype(str) == "pass")
    signal_debug = debug_df[signal_mask]
    print(f"  [{label}] Signals: {signal_mask.sum()}, "
          f"regime dist: {signal_debug['regime'].value_counts().to_dict()}")

    regime_scenarios = [
        ("all_regimes",          set()),
        ("excl_HIGH_VOL_TREND",  {"HIGH_VOL_TREND"}),
        ("excl_NEWS_SHOCK",      {"NEWS_SHOCK_PROXY"}),
        ("only_NORMAL",          {"HIGH_VOL_TREND", "NEWS_SHOCK_PROXY", "LOW_VOL_RANGE"}),
        ("NORMAL+LOW_VOL",       {"HIGH_VOL_TREND", "NEWS_SHOCK_PROXY"}),
    ]

    results = {}
    regime_counts = regime_df["regime"].value_counts().to_dict() if not regime_df.empty else {}

    for name, excl_set in regime_scenarios:
        if excl_set:
            filtered = debug_df[~debug_df["regime"].isin(excl_set)]
        else:
            filtered = debug_df
        trades_df = run_backtest(
            filtered,
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
        if closed.empty:
            results[name] = {"trades": 0, "wr%": 0.0, "PF": 0.0, "net_rub": 0.0}
            continue
        pnl = closed["net_pnl_rub"]
        wins = (pnl > 0).sum()
        gw = pnl[pnl > 0].sum()
        gl = abs(pnl[pnl <= 0].sum())
        pf = round(gw / gl, 3) if gl > 0 else float("inf")
        results[name] = {
            "trades": len(closed),
            "wr%": round(wins / len(closed) * 100, 1),
            "PF": pf,
            "net_rub": round(pnl.sum(), 2),
        }

    results["_regime_counts"] = regime_counts
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print("Loading candle data...")
    train = _load(TRAIN_CSV)
    oos   = _load(OOS_CSV)

    print(f"Train: {len(train)} candles, {train['msk_date'].nunique()} days")
    print(f"OOS:   {len(oos)} candles, {oos['msk_date'].nunique()} days")

    lines = [
        "# Research: ORB Range Cap + Volume Filter + Hammer Regime Filter",
        f"*Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        f"*Train: {TRAIN_CSV}*",
        f"*OOS:   {OOS_CSV}*",
        "",
    ]

    # ── 1. ORB range cap ──────────────────────────────────────────────────────
    print("\n1. ORB range cap...")
    caps = [400, 500, 600, 700, 800, None]
    train_cap = run_orb_range_cap(train, caps)
    oos_cap   = run_orb_range_cap(oos, caps)

    lines += ["## 1. ORB Range Cap (SHORT, OR 10:00–11:00, take_r=2.0)", ""]
    if not train_cap.empty:
        no_cap = train_cap[train_cap["cap"] == "no_cap"]
        if not no_cap.empty:
            pct = no_cap["or_range"].quantile([0.25, 0.5, 0.75, 0.9, 0.95]).round(0)
            lines.append(
                f"OR range percentiles (train): "
                f"p25={pct[0.25]:.0f}  p50={pct[0.5]:.0f}  "
                f"p75={pct[0.75]:.0f}  p90={pct[0.9]:.0f}  p95={pct[0.95]:.0f}"
            )
            lines.append("")

        lines.append("### Train (Jan 15 – Apr 10)")
        lines.append(_orb_summary(train_cap, "cap").to_markdown(index=False))
        lines.append("")
        if not oos_cap.empty:
            lines.append("### OOS (May 2026)")
            lines.append(_orb_summary(oos_cap, "cap").to_markdown(index=False))
            lines.append("")

    # ── 2. ORB volume filter ──────────────────────────────────────────────────
    print("\n2. ORB volume filter...")
    vol_mults = [0, 1.0, 1.5, 2.0, 2.5]
    train_vol = run_orb_volume_filter(train, vol_mults)
    oos_vol   = run_orb_volume_filter(oos, vol_mults)

    lines += ["## 2. ORB Volume Filter on Breakout Candle", ""]
    if not train_vol.empty:
        no_filt = train_vol[train_vol["vol_mult"] == "no_filter"]
        if not no_filt.empty and "vol_ratio" in no_filt.columns:
            pct = no_filt["vol_ratio"].dropna().quantile([0.25, 0.5, 0.75, 0.9]).round(2)
            lines.append(
                f"Breakout vol/avg20 percentiles (train): "
                f"p25={pct[0.25]}  p50={pct[0.5]}  p75={pct[0.75]}  p90={pct[0.9]}"
            )
            lines.append("")

        lines.append("### Train (Jan 15 – Apr 10)")
        lines.append(_orb_summary(train_vol, "vol_mult").to_markdown(index=False))
        lines.append("")
        if not oos_vol.empty:
            lines.append("### OOS (May 2026)")
            lines.append(_orb_summary(oos_vol, "vol_mult").to_markdown(index=False))
            lines.append("")

    # ── 3. Hammer regime filter ───────────────────────────────────────────────
    print("\n3. Hammer SELL + regime filter (train)...")
    try:
        regime_res_train = run_hammer_regime_filter(train, "train")
        train_regime_ok = True
    except Exception as e:
        regime_res_train = {"_error": str(e)}
        train_regime_ok = False
        import traceback; traceback.print_exc()

    print("\n3b. Hammer SELL + regime filter (OOS)...")
    try:
        regime_res_oos = run_hammer_regime_filter(oos, "OOS")
        oos_regime_ok = True
    except Exception as e:
        regime_res_oos = {"_error": str(e)}
        oos_regime_ok = False
        print(f"  OOS ERROR: {e}")

    lines += ["## 3. Hammer SELL — Regime Filter (SELL only, take_r=1.0, no max_hold)", ""]

    if "_error" in regime_res_train:
        lines.append(f"Error: `{regime_res_train['_error']}`")
        lines.append("")
    else:
        regime_counts = regime_res_train.pop("_regime_counts", {})
        lines.append("**Regime distribution (trading days, train):**")
        for reg, cnt in sorted(regime_counts.items()):
            lines.append(f"- {reg}: {cnt} days")
        lines.append("")

        rows_train = [{"filter": k, **v} for k, v in regime_res_train.items()]
        lines.append("### Train (Jan 15 – Apr 10)")
        lines.append(pd.DataFrame(rows_train).to_markdown(index=False))
        lines.append("")

    if oos_regime_ok and "_error" not in regime_res_oos:
        regime_res_oos.pop("_regime_counts", {})
        rows_oos = [{"filter": k, **v} for k, v in regime_res_oos.items()]
        lines.append("### OOS (May 2026)")
        lines.append(pd.DataFrame(rows_oos).to_markdown(index=False))
        lines.append("")
    elif "_error" in regime_res_oos:
        lines.append(f"OOS error: `{regime_res_oos['_error']}`")
        lines.append("")

    # ── Save ──────────────────────────────────────────────────────────────────
    Path("reports").mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"reports/research_new_filters_{ts}.md"
    with open(out_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\n{'='*60}")
    print(f"Report saved: {out_path}")
    print("=" * 60)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
