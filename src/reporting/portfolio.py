"""Portfolio / exposure analytics across all strategies.

Answers "how do they work TOGETHER", not just individually:
  - combined PnL / equity curve / portfolio vol & drawdown
  - correlation between strategies' daily PnL (redundant vs diversifying)
  - exposure by instrument / direction / asset-class (market)
  - overload flags (too much risk on one market / one direction)
  - each strategy's contribution to total RETURN and total RISK (variance,
    correlation-aware)

Common unit = realized PnL in RUB (all engines report RUB; instruments with
different point values are comparable on realized PnL). Notional exposure is
NOT tracked for paper strategies (all 1 lot) — exposure here is by
realized-risk and by count/PnL grouping.

Daily PnL is bucketed by MSK trading date. Correlation/risk use the union of
all trading dates, zero-filled (a strategy made 0 on a day it didn't trade).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np

MSK = ZoneInfo("Europe/Moscow")

ASSET_CLASS = {
    "SiU6": "FX/RUB", "EuU6": "FX/RUB",
    "MXU6": "Equity-index", "BRQ6": "Oil", "GDU6": "Gold",
    "LKOH": "Equity", "BASKET": "Equity",
}


def asset_class(instr: str) -> str:
    if instr in ASSET_CLASS:
        return ASSET_CLASS[instr]
    if instr and (instr.startswith("SBER") or instr.startswith("GAZP")):
        return "Equity"
    return "Other"


def norm_direction(d: str) -> str:
    d = (d or "").upper()
    if d in ("SELL", "SHORT", "SHORT_SPREAD"):
        return "SHORT"
    if d in ("BUY", "LONG", "LONG_SPREAD"):
        return "LONG"
    return "NEUTRAL"


@dataclass
class StrategyContribution:
    unit: str
    instrument: str
    direction: str
    asset_class: str
    total_pnl: float
    trade_days: int
    daily_vol: float
    return_pct: float          # share of portfolio total PnL
    risk_pct: Optional[float]  # share of portfolio variance (corr-aware); None if excluded


@dataclass
class PortfolioReport:
    n_strategies: int
    n_dates: int
    total_pnl: float
    daily_mean: float
    daily_vol: float
    sharpe_annual: Optional[float]
    max_dd: float
    equity_curve: list[float]
    contributions: list[StrategyContribution]
    corr_pairs: list[tuple]            # (unitA, unitB, corr) notable pairs
    by_instrument: dict
    by_direction: dict
    by_asset_class: dict
    overload_flags: list[str]
    excluded_low_data: list[str]


def _short(unit: str) -> str:
    return unit.replace("hammertrade-", "").replace(".service", "")


def daily_matrix(reports):
    """Return (sorted_dates, {unit: {date: pnl}})."""
    mat: dict[str, dict[date, float]] = {}
    all_dates: set[date] = set()
    for r in reports:
        unit = _short(r.svc.unit)
        series: dict[date, float] = {}
        for t in r.trades:
            ets = t.exit_ts
            if ets is None:
                continue
            d = ets.astimezone(MSK).date()
            series[d] = series.get(d, 0.0) + float(t.pnl_rub)
            all_dates.add(d)
        if series:
            mat[unit] = series
    return sorted(all_dates), mat


def _vector(series: dict, dates: list) -> np.ndarray:
    return np.array([series.get(d, 0.0) for d in dates], dtype=float)


def analyze(reports, *, min_trade_days: int = 4, corr_threshold: float = 0.5) -> PortfolioReport:
    dates, mat = daily_matrix(reports)
    units = list(mat.keys())
    meta = {_short(r.svc.unit): r for r in reports}

    # portfolio equity curve (all strategies, all dates)
    daily_total = _vector({}, dates)  # zeros
    for u in units:
        daily_total = daily_total + _vector(mat[u], dates)
    equity = list(np.cumsum(daily_total)) if len(dates) else []
    total_pnl = float(daily_total.sum())
    daily_mean = float(daily_total.mean()) if len(dates) else 0.0
    daily_vol = float(daily_total.std(ddof=1)) if len(dates) > 1 else 0.0
    sharpe = (daily_mean / daily_vol * np.sqrt(252)) if daily_vol > 0 else None
    # max drawdown of equity
    max_dd = 0.0
    peak = 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)

    # strategies with enough trade-days for corr/risk
    incl = [u for u in units if len(mat[u]) >= min_trade_days]
    excluded = [u for u in units if u not in incl]

    risk_pct: dict[str, Optional[float]] = {u: None for u in units}
    corr_pairs = []
    if len(incl) >= 2 and len(dates) >= 3:
        M = np.column_stack([_vector(mat[u], dates) for u in incl])  # dates × incl
        cov = np.cov(M, rowvar=False)
        port_var = float(cov.sum())
        if port_var > 0:
            col_sums = cov.sum(axis=1)
            for i, u in enumerate(incl):
                risk_pct[u] = float(col_sums[i] / port_var * 100.0)
        # correlations
        with np.errstate(invalid="ignore", divide="ignore"):
            corr = np.corrcoef(M, rowvar=False)
        for i in range(len(incl)):
            for j in range(i + 1, len(incl)):
                c = corr[i, j]
                if np.isfinite(c) and abs(c) >= corr_threshold:
                    corr_pairs.append((incl[i], incl[j], round(float(c), 2)))
        corr_pairs.sort(key=lambda x: -abs(x[2]))

    # per-strategy contributions
    contribs = []
    for u in units:
        series = mat[u]
        vec = _vector(series, dates)
        pnl = float(vec.sum())
        r = meta[u]
        contribs.append(StrategyContribution(
            unit=u, instrument=r.svc.instrument,
            direction=norm_direction(r.svc.direction),
            asset_class=asset_class(r.svc.instrument),
            total_pnl=round(pnl, 1), trade_days=len(series),
            daily_vol=round(float(vec.std(ddof=1)) if len(dates) > 1 else 0.0, 1),
            return_pct=round(pnl / total_pnl * 100, 1) if total_pnl != 0 else 0.0,
            risk_pct=round(risk_pct[u], 1) if risk_pct[u] is not None else None,
        ))
    contribs.sort(key=lambda c: -c.total_pnl)

    # exposures
    def _group(keyfn):
        g: dict[str, dict] = {}
        for c in contribs:
            k = keyfn(c)
            e = g.setdefault(k, {"n": 0, "pnl": 0.0, "risk_pct": 0.0})
            e["n"] += 1
            e["pnl"] += c.total_pnl
            if c.risk_pct is not None:
                e["risk_pct"] += c.risk_pct
        for e in g.values():
            e["pnl"] = round(e["pnl"], 1)
            e["risk_pct"] = round(e["risk_pct"], 1)
        return dict(sorted(g.items(), key=lambda kv: -kv[1]["pnl"]))

    by_instrument = _group(lambda c: c.instrument)
    by_direction = _group(lambda c: c.direction)
    by_asset = _group(lambda c: c.asset_class)

    # overload flags
    flags = []
    n = len(contribs)
    for cls, e in by_asset.items():
        if n and e["n"] / n > 0.5:
            flags.append(f"⚠ {e['n']}/{n} strategies ({e['n']/n*100:.0f}%) on one market: {cls}")
        if e["risk_pct"] > 50:
            flags.append(f"⚠ {e['risk_pct']:.0f}% of portfolio risk concentrated in {cls}")
    short_risk = sum(e["risk_pct"] for d, e in by_direction.items() if d == "SHORT")
    long_risk = sum(e["risk_pct"] for d, e in by_direction.items() if d == "LONG")
    if short_risk - long_risk > 50:
        flags.append(f"⚠ directional tilt: SHORT risk {short_risk:.0f}% vs LONG {long_risk:.0f}% — "
                     "book is net-SHORT; little hedge if the market rallies")

    return PortfolioReport(
        n_strategies=len(units), n_dates=len(dates), total_pnl=round(total_pnl, 1),
        daily_mean=round(daily_mean, 1), daily_vol=round(daily_vol, 1),
        sharpe_annual=round(sharpe, 2) if sharpe is not None else None,
        max_dd=round(max_dd, 1), equity_curve=[round(x, 1) for x in equity],
        contributions=contribs, corr_pairs=corr_pairs,
        by_instrument=by_instrument, by_direction=by_direction, by_asset_class=by_asset,
        overload_flags=flags, excluded_low_data=excluded,
    )
