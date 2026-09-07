#!/usr/bin/env python3
"""Event-driven cashflow replay of the perp-carry construction, WITH IndexDiv.

WHAT THIS REPLACES
==================
``scripts/research_perp_funding.py`` averaged a daily SNAPSHOT of
``funding_ma - basis/DTE`` and reported the mean as an edge (+4.76 bp/day on
IMOEX). That is not a realised return: it holds no position, pays no costs,
rolls nothing, and — decisively — omits a contractual cashflow.

THE OMITTED CASHFLOW
====================
A perpetual on a PRICE index has THREE variation-margin components: mark-to-
market, ``SwapRate``, and a dividend adjustment (``IndexDiv``) that is credited
to longs and DEBITED from shorts. This construction is short the perpetual, so
the adjustment is an obligation. The ISS history endpoint the project reads
exposes ``SWAPRATE`` only, so the daemon never saw it.

That IMOEXF tracks the PRICE index is verifiable: over 2024-01..2026-09 the
perp/index ratio is 100.001 (sd 0.049) and the perp returned -28.0% against
IMOEX -28.0%, while the total-return index MCFTRR returned -11.7%. A short that
kept the dividend-driven part of that fall while also receiving funding would be
collecting dividends for free.

THE ARITHMETIC BEING TESTED
===========================
The quarterly basis is ``rT - qT`` (financing minus expected dividends), so
``funding - basis/DTE`` evaluates to ``f - r + q`` while the construction earns
``f - r``. The gap is the dividend yield ``q``. Prediction: subtracting the
realised dividend accrual removes most of the reported edge, and turns the 2026
regime negative.

IndexDiv is proxied by the daily return difference between the total-return
index (MCFTRR) and the price index (IMOEX) — which is what the dividend
adjustment compensates for, by construction.

Usage:
    venv/bin/python scripts/research_carry_cashflow_replay.py
    venv/bin/python scripts/research_carry_cashflow_replay.py --asset GLDRUBF
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.carry import expected_carry_bp, front_selection_is_consistent
from src.costs import FUTURES_COMMISSION_BPS_PER_SIDE, required_daily_carry_bps, roundtrip_bps

ISS = "https://iss.moex.com/iss"
MONTH = {"H": 3, "M": 6, "U": 9, "Z": 12}


def _paged(url: str, block: str = "history") -> pd.DataFrame:
    rows, cols, start = [], None, 0
    while True:
        with urllib.request.urlopen(f"{url}&start={start}", timeout=45) as r:
            d = json.load(r)[block]
        if cols is None:
            cols = d["columns"]
        if not d["data"]:
            break
        rows += d["data"]
        start += len(d["data"])
        if len(d["data"]) < 100:
            break
    return pd.DataFrame(rows, columns=cols)


def futures_history(secid: str, frm: str) -> pd.DataFrame:
    df = _paged(f"{ISS}/history/engines/futures/markets/forts/securities/{secid}.json"
                f"?iss.meta=off&from={frm}"
                f"&history.columns=TRADEDATE,SETTLEPRICE,CLOSE,SWAPRATE,VOLUME")
    if df.empty:
        return df
    df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
    df["px"] = pd.to_numeric(df["SETTLEPRICE"], errors="coerce").fillna(
        pd.to_numeric(df["CLOSE"], errors="coerce"))
    df["swap"] = pd.to_numeric(df.get("SWAPRATE"), errors="coerce")
    df["vol"] = pd.to_numeric(df.get("VOLUME"), errors="coerce").fillna(0)
    return df.set_index("TRADEDATE").sort_index()[["px", "swap", "vol"]]


def index_history(secid: str, frm: str) -> pd.Series:
    df = _paged(f"{ISS}/history/engines/stock/markets/index/securities/{secid}.json"
                f"?iss.meta=off&from={frm}&history.columns=TRADEDATE,CLOSE")
    if df.empty:
        return pd.Series(dtype=float)
    df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
    return df.set_index("TRADEDATE").sort_index()["CLOSE"].astype(float)


def daily_dividend_accrual_bps(price_idx: pd.Series, total_return_idx: pd.Series) -> pd.Series:
    """Dividend accrual per day, in bps, from the TR-vs-price index gap.

    This is exactly what an index dividend adjustment compensates: the total
    return index keeps the dividend, the price index drops it.
    """
    j = pd.DataFrame({"p": price_idx, "t": total_return_idx}).dropna()
    r_price = j["p"].pct_change()
    r_total = j["t"].pct_change()
    return ((r_total - r_price) * 1e4).dropna()


def quarterly_series(prefix: str, frm: str) -> dict:
    """{ticker: history} for a quarterly series, keeping only commensurate scales."""
    out = {}
    for yr in range(3, 8):
        for m in "HMUZ":
            t = f"{prefix}{m}{yr}"
            try:
                h = futures_history(t, frm)
            except Exception:
                continue
            if not h.empty and len(h) > 20:
                out[t] = h
    return out


def replay(asset: str, q_prefix: str, frm: str, args) -> dict:
    perp = futures_history(asset, frm)
    if perp.empty:
        raise SystemExit(f"no perp history for {asset}")

    quarterlies = quarterly_series(q_prefix, frm)
    # Reject any series quoted on a different scale than the perp — the executor
    # picks its series from an unvalidated CLI prefix, and MIX vs MXI differ 100x.
    med_perp = perp["px"].median()
    quarterlies = {t: h for t, h in quarterlies.items()
                   if abs(h["px"].median() / med_perp - 1) < 0.25}
    if not quarterlies:
        raise SystemExit(f"no commensurate quarterlies for prefix {q_prefix}")

    expiries = {t: pd.Timestamp(year=2020 + int(t[-1]), month=MONTH[t[-2]], day=18)
                for t in quarterlies}

    div_bps = args.div_bps  # a pd.Series indexed by date, or None

    cost_rt = roundtrip_bps(n_legs=2, cost_bps_per_side=FUTURES_COMMISSION_BPS_PER_SIDE)
    gate = required_daily_carry_bps(
        roundtrip_cost_bps=cost_rt,
        expected_hold_days=args.expected_hold_days,
        cover_multiple=args.cover_multiple,
    )

    rows = []
    held = None          # {"ticker", "entry_perp", "entry_q", "entry_date"}
    trades = []
    dates = perp.index

    for i, d in enumerate(dates):
        if i == 0:
            continue
        p_now, p_prev = perp["px"].iloc[i], perp["px"].iloc[i - 1]
        if not np.isfinite(p_now) or not np.isfinite(p_prev) or p_prev <= 0:
            continue

        # 20-day funding MA in bps of perp price, using only past data.
        window = perp["swap"].iloc[max(0, i - args.funding_ma_days):i]
        fma = (window.mean() / p_prev * 1e4) if window.notna().sum() >= 3 else np.nan

        # Front selection under the EXECUTOR's rule.
        live = [(t, (expiries[t] - d).days) for t in quarterlies
                if d in quarterlies[t].index and (expiries[t] - d).days > args.min_front_dte]
        front = min(live, key=lambda x: x[1]) if live else None

        # --- accruals on a held position -------------------------------------
        day = {"date": d, "funding_bps": 0.0, "indexdiv_bps": 0.0,
               "price_bps": 0.0, "cost_bps": 0.0, "held": held["ticker"] if held else None}

        if held is not None:
            h = quarterlies[held["ticker"]]
            # Funding: a SHORT perp receives SWAPRATE.
            sw = perp["swap"].iloc[i]
            if np.isfinite(sw):
                day["funding_bps"] = sw / p_prev * 1e4
            # IndexDiv: DEBITED from the short. This is the omitted term.
            if div_bps is not None and d in div_bps.index:
                day["indexdiv_bps"] = -float(div_bps.loc[d])
            # Price PnL: short perp + long quarterly, in bps of leg notional.
            if d in h.index and i > 0:
                prev_dates = h.index[h.index < d]
                if len(prev_dates):
                    q_now = h["px"].loc[d]
                    q_prev = h["px"].loc[prev_dates[-1]]
                    if np.isfinite(q_now) and np.isfinite(q_prev) and q_prev > 0:
                        day["price_bps"] = (-(p_now / p_prev - 1) + (q_now / q_prev - 1)) * 1e4

        # --- decisions --------------------------------------------------------
        if held is None:
            if front is not None and np.isfinite(fma):
                t, dte = front
                q_px = quarterlies[t]["px"].loc[d]
                if np.isfinite(q_px):
                    carry = expected_carry_bp(fma, p_now, q_px, dte)
                    if carry >= max(args.entry_carry_bp, gate):
                        held = {"ticker": t, "entry_date": d, "entry_carry": carry}
                        day["cost_bps"] = cost_rt / 2.0   # entry half of the round trip
                        trades.append({"entry": d, "ticker": t, "entry_carry": carry})
        else:
            t = held["ticker"]
            dte_held = (expiries[t] - d).days
            q_px = quarterlies[t]["px"].loc[d] if d in quarterlies[t].index else np.nan
            reason = None
            if dte_held < args.roll_dte:
                reason = "ROLL"
            elif np.isfinite(fma) and np.isfinite(q_px):
                # Exit decision on the HELD contract, not on the current front.
                if expected_carry_bp(fma, p_now, q_px, max(dte_held, 1)) <= args.exit_carry_bp:
                    reason = "CARRY_FLIP"
            if reason:
                day["cost_bps"] += cost_rt / 2.0          # exit half
                trades[-1].update(exit=d, reason=reason)
                held = None

        rows.append(day)

    df = pd.DataFrame(rows).set_index("date")
    df["naive_bps"] = df["price_bps"] + df["funding_bps"]                    # what the daemon books
    df["full_bps"] = df["naive_bps"] + df["indexdiv_bps"] - df["cost_bps"]   # with the obligation
    return {"daily": df, "trades": trades, "gate": gate, "cost_rt": cost_rt}


def summarise(df: pd.DataFrame, label: str) -> str:
    inpos = df[df["held"].notna()]
    n = len(inpos)
    if n == 0:
        return f"{label}: never in position\n"
    out = [f"{label}: {n} days in position of {len(df)} ({n/len(df):.0%})"]
    for col, name in [("naive_bps", "naive  (price + funding)      "),
                      ("full_bps", "full   (- IndexDiv - costs)   ")]:
        mean = inpos[col].mean()
        out.append(f"   {name} {mean:+7.3f} bp/day   total {inpos[col].sum():+9.1f} bp")
    out.append(f"   omitted IndexDiv               {inpos['indexdiv_bps'].mean():+7.3f} bp/day")
    out.append(f"   costs                          {-inpos['cost_bps'].mean():+7.3f} bp/day")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asset", default="IMOEXF")
    ap.add_argument("--q-prefix", default="MM")
    ap.add_argument("--from", dest="frm", default="2023-01-01")
    ap.add_argument("--funding-ma-days", type=int, default=20)
    ap.add_argument("--entry-carry-bp", type=float, default=1.0)
    ap.add_argument("--exit-carry-bp", type=float, default=0.0)
    ap.add_argument("--expected-hold-days", type=float, default=10.0)
    ap.add_argument("--cover-multiple", type=float, default=2.0)
    ap.add_argument("--roll-dte", type=int, default=7)
    ap.add_argument("--min-front-dte", type=int, default=10)
    ap.add_argument("--price-index", default="IMOEX")
    ap.add_argument("--total-return-index", default="MCFTRR")
    ap.add_argument("--no-dividend-adjustment", action="store_true",
                    help="For assets with no index dividend (e.g. GOLD)")
    ap.add_argument("--out", default="reports/carry_cashflow_replay.md")
    args = ap.parse_args()

    ok, detail = front_selection_is_consistent(
        min_front_dte=args.min_front_dte, roll_dte=args.roll_dte,
        expected_hold_days=args.expected_hold_days)
    print(f"[horizon] {'OK' if ok else 'INCONSISTENT'}: {detail}\n")

    args.div_bps = None
    if not args.no_dividend_adjustment:
        print(f"[data] {args.price_index} / {args.total_return_index} ...")
        p = index_history(args.price_index, args.frm)
        t = index_history(args.total_return_index, args.frm)
        args.div_bps = daily_dividend_accrual_bps(p, t)
        print(f"[data] dividend accrual: {len(args.div_bps)} days, "
              f"mean {args.div_bps.mean():.2f} bp/day\n")

    print(f"[replay] {args.asset} vs {args.q_prefix} quarterlies from {args.frm} ...")
    res = replay(args.asset, args.q_prefix, args.frm, args)
    df, trades = res["daily"], res["trades"]

    lines = [f"# Carry cashflow replay — {args.asset}", "",
             f"Round trip {res['cost_rt']:.1f} bp, entry gate {res['gate']:.2f} bp/day, "
             f"horizon check: {detail}", "",
             f"Trades: {len(trades)}", "", "```"]
    lines.append(summarise(df, "ALL"))
    for year in sorted({d.year for d in df.index}):
        lines.append(summarise(df[df.index.year == year], str(year)))
    lines.append("```")

    print("\n".join(lines[6:]))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[out] {args.out}")


if __name__ == "__main__":
    main()
