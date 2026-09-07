"""Hour-of-day targeted audit (MVP-2.3).

Analyses the effect of excluding a specific MSK hour from paper and historical
backtest trades. Produces per-source stats, counterfactuals, a per-hour
comparison and a candidate decision for the next paper experiment.
"""
from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

_MSK = ZoneInfo("Europe/Moscow")
_LOW_SAMPLE_THRESHOLD = 10
_LARGE_WINNER_RUB = 500.0
_LARGE_LOSER_RUB = -500.0
_BIG_RISK_PTS = 40.0   # mirrors src/paper/diagnostics.py


# ── Timestamp ─────────────────────────────────────────────────────────────────

def msk_hour_from_str(ts_str: str, tz: ZoneInfo = _MSK) -> Optional[int]:
    """Parse an ISO-8601 UTC timestamp and return the local hour."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(str(ts_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).hour
    except (ValueError, TypeError):
        return None


def _date_str_msk(ts_str: str, tz: ZoneInfo = _MSK) -> Optional[str]:
    """Return YYYY-MM-DD in local tz from an ISO-8601 string."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(str(ts_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


# ── Safe helpers ──────────────────────────────────────────────────────────────

def _f(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_pf(gross_profit: float, gross_loss: float) -> float:
    if gross_loss == 0:
        return math.inf if gross_profit > 0 else 0.0
    return round(gross_profit / gross_loss, 3)


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 2)


# ── Flag helpers ──────────────────────────────────────────────────────────────

def _is_big_risk(t: dict) -> bool:
    flags = t.get("diagnostic_flags") or ""
    if flags:
        return "BIG_RISK" in flags
    r = _f(t.get("risk_points"))
    return r is not None and r > _BIG_RISK_PTS


def _is_one_bar_stop(t: dict) -> bool:
    flags = t.get("diagnostic_flags") or ""
    if flags:
        return "ONE_BAR_STOP" in flags
    exit_r = (t.get("exit_reason") or "").lower()
    bars = _f(t.get("bars_held"))
    return exit_r == "stop" and bars is not None and bars <= 1


# ── HourStats ─────────────────────────────────────────────────────────────────

@dataclass
class HourStats:
    source: str = ""           # historical / live_baseline / live_maxhold5
    strategy: str = ""         # all_hours / hour_XX / without_hour_XX
    period: str = ""
    hour: str = "all"
    trades: int = 0
    wins: int = 0
    losses: int = 0
    winrate: float = 0.0
    net_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    max_drawdown: float = 0.0
    avg_bars_held: float = 0.0
    big_risk_count: int = 0
    big_risk_net: float = 0.0
    one_bar_stop_count: int = 0
    one_bar_stop_net: float = 0.0
    large_winner_count: int = 0
    large_winner_net: float = 0.0
    large_loser_count: int = 0
    large_loser_net: float = 0.0
    low_sample: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["profit_factor"] = "inf" if math.isinf(self.profit_factor) else self.profit_factor
        return d


def compute_stats(
    trades: list[dict],
    source: str,
    strategy: str,
    period: str,
    hour: str,
    pnl_key: str = "pnl_rub",
) -> HourStats:
    """Compute HourStats from a (pre-filtered) list of trade dicts."""
    closed = [t for t in trades if _f(t.get(pnl_key)) is not None]
    n = len(closed)
    if n == 0:
        return HourStats(source=source, strategy=strategy, period=period,
                         hour=hour, low_sample=True)

    pnls = [_f(t[pnl_key]) for t in closed]
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    net = round(sum(pnls), 2)

    bars_vals = [_f(t.get("bars_held")) for t in closed]
    valid_bars = [b for b in bars_vals if b is not None]
    avg_bars = round(sum(valid_bars) / len(valid_bars), 2) if valid_bars else 0.0

    br = [t for t in closed if _is_big_risk(t)]
    obs = [t for t in closed if _is_one_bar_stop(t)]
    lw = [t for t in closed if (_f(t.get(pnl_key)) or 0) >= _LARGE_WINNER_RUB]
    ll = [t for t in closed if (_f(t.get(pnl_key)) or 0) <= _LARGE_LOSER_RUB]

    return HourStats(
        source=source, strategy=strategy, period=period, hour=hour,
        trades=n, wins=wins, losses=losses,
        winrate=round(wins / n * 100, 1) if n > 0 else 0.0,
        net_pnl=net,
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
        profit_factor=_safe_pf(gross_profit, gross_loss),
        expectancy=round(net / n, 2) if n > 0 else 0.0,
        best_trade=round(max(pnls), 2),
        worst_trade=round(min(pnls), 2),
        max_drawdown=_max_drawdown(pnls),
        avg_bars_held=avg_bars,
        big_risk_count=len(br),
        big_risk_net=round(sum(_f(t.get(pnl_key)) for t in br), 2),
        one_bar_stop_count=len(obs),
        one_bar_stop_net=round(sum(_f(t.get(pnl_key)) for t in obs), 2),
        large_winner_count=len(lw),
        large_winner_net=round(sum(_f(t.get(pnl_key)) for t in lw), 2),
        large_loser_count=len(ll),
        large_loser_net=round(sum(_f(t.get(pnl_key)) for t in ll), 2),
        low_sample=n < _LOW_SAMPLE_THRESHOLD,
    )


# ── Data loading ──────────────────────────────────────────────────────────────

def load_historical_trades(
    csv_path: str,
    scenario: str = "baseline",
    tz: ZoneInfo = _MSK,
) -> list[dict]:
    """Load backtest trades CSV and normalise to a common schema.

    Adds ``entry_hour_msk``, normalises ``pnl_rub`` (from ``net_pnl_rub``),
    ``exit_reason`` (title-case), and computes ``diagnostic_flags``.
    """
    path = Path(csv_path)
    if not path.exists():
        return []

    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("scenario_name") != scenario:
                continue

            ts = row.get("signal_time") or row.get("entry_time") or ""
            hour = msk_hour_from_str(ts, tz)
            date = _date_str_msk(ts, tz)

            pnl = _f(row.get("net_pnl_rub")) or _f(row.get("pnl_rub"))
            exit_r = (row.get("exit_reason") or "").upper()
            risk = _f(row.get("risk_points"))
            bars = _f(row.get("bars_held"))

            flags: list[str] = []
            if risk is not None and risk > _BIG_RISK_PTS:
                flags.append("BIG_RISK")
            if exit_r == "STOP" and bars is not None and bars <= 1:
                flags.append("ONE_BAR_STOP")
            if exit_r == "TAKE" and bars is not None and bars <= 1:
                flags.append("ONE_BAR_TAKE")

            rows.append({
                "entry_hour_msk": hour,
                "entry_date_msk": date,
                "pnl_rub": pnl,
                "exit_reason": exit_r,
                "risk_points": risk,
                "bars_held": bars,
                "diagnostic_flags": ";".join(flags),
                "source_scenario": scenario,
                "_raw": row,
            })
    return rows


def load_paper_trades(
    db_path: str,
    ticker: str = "SiM6",
    direction: str = "SELL",
) -> list[dict]:
    """Load paper trades from SQLite and enrich using paper diagnostics."""
    from src.paper.diagnostics import enrich_trade, load_from_sqlite
    rows, _warnings, _label = load_from_sqlite(db_path, ticker=ticker,
                                                direction=direction)
    enriched = []
    for row in rows:
        e, _w = enrich_trade(row)
        enriched.append(e)
    return enriched


def _period_str(trades: list[dict], date_key: str = "entry_date_msk") -> str:
    dates = [t.get(date_key) for t in trades if t.get(date_key)]
    if not dates:
        return "unknown"
    return f"{min(dates)} – {max(dates)}"


# ── AuditResult ───────────────────────────────────────────────────────────────

@dataclass
class SourceAudit:
    source: str
    all_hours: HourStats
    audit_hour: HourStats
    without_audit_hour: HourStats
    by_hour: dict[int, HourStats] = field(default_factory=dict)
    period_breakdown: list[dict] = field(default_factory=list)  # monthly for hist, weekly for paper
    detail_trades_hour: list[dict] = field(default_factory=list)


@dataclass
class AuditResult:
    audit_hour: int
    tz_name: str
    historical: Optional[SourceAudit]
    live_baseline: Optional[SourceAudit]
    live_maxhold5: Optional[SourceAudit]
    overfit_risk: str = "MEDIUM"
    candidate_decision: str = "B"
    candidate_reason: str = ""
    recommendation: str = ""


# ── Run audit ─────────────────────────────────────────────────────────────────

def _per_hour_stats(
    trades: list[dict], source: str, period: str,
    pnl_key: str = "pnl_rub",
    min_trades: int = 1,
) -> dict[int, HourStats]:
    by_hour: dict[int, list] = {}
    for t in trades:
        h = t.get("entry_hour_msk")
        if h is None:
            continue
        try:
            h = int(h)
        except (TypeError, ValueError):
            continue
        by_hour.setdefault(h, []).append(t)

    result = {}
    for h, ts in sorted(by_hour.items()):
        if len(ts) < min_trades:
            continue
        result[h] = compute_stats(ts, source=source,
                                   strategy=f"hour_{h:02d}",
                                   period=period, hour=str(h),
                                   pnl_key=pnl_key)
    return result


def _period_breakdown(trades: list[dict], source: str, audit_h: int,
                       pnl_key: str = "pnl_rub") -> list[dict]:
    """Break down audit-hour trades by month (or week for live data)."""
    # For historical: monthly. For live: weekly (shorter period).
    n_days = _date_range_days(trades)
    use_week = n_days <= 60

    buckets: dict[str, list] = {}
    for t in trades:
        if t.get("entry_hour_msk") != audit_h:
            continue
        date = t.get("entry_date_msk") or ""
        if not date:
            continue
        try:
            dt = datetime.fromisoformat(date)
        except ValueError:
            continue
        if use_week:
            # ISO week
            iso = dt.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        else:
            key = date[:7]  # YYYY-MM
        buckets.setdefault(key, []).append(t)

    result = []
    for period_key in sorted(buckets):
        ts = buckets[period_key]
        s = compute_stats(ts, source=source, strategy="hour_audit_period",
                          period=period_key, hour=str(audit_h), pnl_key=pnl_key)
        row = s.to_dict()
        row["period_label"] = period_key
        row["granularity"] = "week" if use_week else "month"
        result.append(row)
    return result


def _date_range_days(trades: list[dict]) -> int:
    dates = [t.get("entry_date_msk") for t in trades if t.get("entry_date_msk")]
    if len(dates) < 2:
        return 0
    try:
        d1 = datetime.fromisoformat(min(dates))
        d2 = datetime.fromisoformat(max(dates))
        return (d2 - d1).days
    except ValueError:
        return 0


def _audit_source(
    trades: list[dict],
    source: str,
    audit_h: int,
    pnl_key: str = "pnl_rub",
) -> SourceAudit:
    period = _period_str(trades)

    # Filter to closed only (have pnl)
    closed = [t for t in trades if _f(t.get(pnl_key)) is not None
              and (t.get("status") in ("CLOSED", None, "")
                   or source == "historical")]

    hour_trades = [t for t in closed if t.get("entry_hour_msk") == audit_h]
    without_trades = [t for t in closed if t.get("entry_hour_msk") != audit_h]

    all_stats = compute_stats(closed, source, "all_hours", period, "all", pnl_key)
    hour_stats = compute_stats(hour_trades, source, f"hour_{audit_h:02d}",
                                period, str(audit_h), pnl_key)
    without_stats = compute_stats(without_trades, source, f"without_hour_{audit_h:02d}",
                                   period, f"without_{audit_h}", pnl_key)

    by_hour = _per_hour_stats(closed, source, period, pnl_key)
    period_bd = _period_breakdown(closed, source, audit_h, pnl_key)

    # Trade detail for audit hour
    detail = []
    for t in hour_trades:
        d: dict = {
            "entry_date": t.get("entry_date_msk", ""),
            "entry_msk": t.get("entry_timestamp_msk") or t.get("entry_date_msk", ""),
            "exit_reason": t.get("exit_reason", ""),
            "entry_price": t.get("entry_price", ""),
            "stop_price": t.get("stop_price", ""),
            "take_price": t.get("take_price", ""),
            "exit_price": t.get("exit_price", ""),
            "pnl_rub": t.get(pnl_key, ""),
            "risk_points": t.get("risk_points", ""),
            "bars_held": t.get("bars_held", ""),
            "flags": t.get("diagnostic_flags", ""),
        }
        detail.append(d)

    return SourceAudit(
        source=source,
        all_hours=all_stats,
        audit_hour=hour_stats,
        without_audit_hour=without_stats,
        by_hour=by_hour,
        period_breakdown=period_bd,
        detail_trades_hour=detail,
    )


def _assess_overfit(
    hist: Optional[SourceAudit],
    baseline: Optional[SourceAudit],
    maxhold5: Optional[SourceAudit],
    audit_h: int,
) -> tuple[str, str, str, str]:
    """Return (overfit_risk, candidate_decision, candidate_reason, recommendation)."""

    pros: list[str] = []
    cons: list[str] = []

    # Historical evidence
    hist_improves = False
    if hist and not hist.audit_hour.low_sample:
        h12 = hist.audit_hour
        wo = hist.without_audit_hour
        all_ = hist.all_hours
        if wo.profit_factor > all_.profit_factor and wo.net_pnl > all_.net_pnl:
            hist_improves = True
            pros.append("Historical PF improves without hour 12")
        else:
            cons.append("Historical PF does not improve when hour 12 excluded")
    elif hist and hist.audit_hour.low_sample:
        cons.append(f"Historical hour {audit_h} LOW_SAMPLE ({hist.audit_hour.trades} trades)")

    # Does hour 12 remove key winners historically?
    hist_cuts_winners = False
    if hist and hist.audit_hour.large_winner_count > 0:
        hist_cuts_winners = True
        cons.append(f"Historical hour {audit_h} contains {hist.audit_hour.large_winner_count} large winner(s)")

    # Live baseline evidence
    baseline_improves = False
    if baseline and not baseline.audit_hour.low_sample:
        wo = baseline.without_audit_hour
        all_ = baseline.all_hours
        if wo.net_pnl > all_.net_pnl and wo.profit_factor > all_.profit_factor:
            baseline_improves = True
            pros.append("Live baseline improves without hour 12")
        else:
            cons.append("Live baseline does not improve when hour 12 excluded")
        # ONE_BAR_STOP impact
        if baseline.audit_hour.one_bar_stop_count > 0:
            pros.append(f"Hour {audit_h} contains {baseline.audit_hour.one_bar_stop_count} ONE_BAR_STOP trade(s) in baseline")
    elif baseline and baseline.audit_hour.low_sample:
        cons.append(f"Live baseline hour {audit_h} LOW_SAMPLE ({baseline.audit_hour.trades} trades)")

    if baseline and baseline.audit_hour.large_winner_count > 0:
        cons.append(f"Live baseline hour {audit_h} contains {baseline.audit_hour.large_winner_count} large winner(s)")
    else:
        if baseline and baseline.audit_hour.trades > 0:
            pros.append(f"Hour {audit_h} does not contain large winners in live baseline")

    # maxhold5 evidence
    if maxhold5 and not maxhold5.audit_hour.low_sample:
        wo = maxhold5.without_audit_hour
        all_ = maxhold5.all_hours
        if wo.net_pnl > all_.net_pnl:
            pros.append("Live maxhold5 also improves without hour 12")
        else:
            cons.append("Live maxhold5 does not clearly improve without hour 12")
    elif maxhold5 and maxhold5.audit_hour.low_sample:
        cons.append(f"Live maxhold5 hour {audit_h} LOW_SAMPLE ({maxhold5.audit_hour.trades} trades)")

    # Is effect concentrated in one trade?
    if baseline:
        h12 = baseline.audit_hour
        if h12.trades > 0 and h12.large_loser_count == h12.trades:
            cons.append("Hour 12 effect may be driven by large losers only (concentration risk)")
        elif h12.trades <= 2:
            cons.append("Very few trades in hour 12 (high single-trade concentration risk)")
        else:
            pros.append(f"Hour {audit_h} effect spread across {h12.trades} trades (not single-trade driven)")

    # Time filters always carry overfit risk
    cons.append("Time-of-day filters have inherently HIGH overfit risk (session, regime, seasonality)")

    # Score
    n_pros = len(pros)
    n_cons = len(cons)
    if n_pros >= 4 and n_cons <= 2 and hist_improves and baseline_improves and not hist_cuts_winners:
        overfit = "MEDIUM"
        decision = "A"
        reason = "Historical and live baseline both confirm; no key winners removed; effect distributed."
        rec = (f"Proceed to MVP-2.4: maxhold5 + exclude_hour_{audit_h} controlled paper experiment. "
               f"Stop condition: PF < 1.25 after 60+ closed trades or 4 weeks.")
    elif n_pros >= 2 and baseline_improves:
        overfit = "MEDIUM"
        decision = "B"
        reason = "Live baseline improves but historical or maxhold5 evidence is weaker."
        rec = ("Consider the experiment with caution. Validate in a backtest grid before launch. "
               "If backtest confirms PF improvement ≥0.3 on walkforward, proceed to MVP-2.4.")
    elif hist_cuts_winners or not hist_improves:
        overfit = "HIGH"
        decision = "C"
        reason = "Historical data does not confirm the filter benefit, or large winners are cut."
        rec = "Do not proceed. Continue observing live paper with current parameters."
    else:
        overfit = "HIGH"
        decision = "B"
        reason = "Insufficient evidence or small sample. Too early to decide."
        rec = "Collect more live trades, then re-run audit."

    pro_lines = "\n".join(f"  + {p}" for p in pros)
    con_lines = "\n".join(f"  - {c}" for c in cons)
    full_reason = f"Pros:\n{pro_lines}\n\nCons:\n{con_lines}"

    return overfit, decision, full_reason, rec


def run_audit(
    audit_hour: int,
    historical_trades: list[dict],
    paper_baseline: list[dict],
    paper_maxhold5: list[dict],
    tz: ZoneInfo = _MSK,
) -> AuditResult:
    tz_name = str(tz)

    hist_audit = _audit_source(historical_trades, "historical", audit_hour)
    base_audit = _audit_source(paper_baseline, "live_baseline", audit_hour)
    mh5_audit = _audit_source(paper_maxhold5, "live_maxhold5", audit_hour)

    overfit, decision, reason, rec = _assess_overfit(hist_audit, base_audit, mh5_audit, audit_hour)

    return AuditResult(
        audit_hour=audit_hour,
        tz_name=tz_name,
        historical=hist_audit,
        live_baseline=base_audit,
        live_maxhold5=mh5_audit,
        overfit_risk=overfit,
        candidate_decision=decision,
        candidate_reason=reason,
        recommendation=rec,
    )


# ── Report builders ───────────────────────────────────────────────────────────

def _pf_str(v: float) -> str:
    if math.isinf(v):
        return "∞"
    return f"{v:.3f}"


def _stats_row(label: str, s: HourStats) -> str:
    ls = " ⚠ LOW_SAMPLE" if s.low_sample else ""
    pf = _pf_str(s.profit_factor)
    return (f"| {label} | {s.trades} | {s.wins} | {s.losses} | {s.winrate}% | "
            f"{s.net_pnl:+.2f} | {pf} | {s.max_drawdown:.2f} |{ls}")


def _hour_table(by_hour: dict[int, HourStats], good_hours: list[int], bad_hours: list[int]) -> str:
    lines = ["| Час (МСК) | Сделок | W | L | WR% | Net RUB | PF | MaxDD | ⚠ |",
             "|-----------|--------|---|---|-----|---------|----|----|---|"]
    for h in sorted(by_hour):
        s = by_hour[h]
        mark = ""
        if h in good_hours:
            mark = "✓ лучший"
        elif h in bad_hours:
            mark = "✗ худший"
        ls = "LOW_SAMPLE" if s.low_sample else ""
        lines.append(f"| {h:02d}:xx | {s.trades} | {s.wins} | {s.losses} | "
                     f"{s.winrate}% | {s.net_pnl:+.2f} | {_pf_str(s.profit_factor)} | "
                     f"{s.max_drawdown:.2f} | {ls}{mark} |")
    return "\n".join(lines)


def _detail_table(rows: list[dict]) -> str:
    if not rows:
        return "_Сделок нет._"
    header = ("| Дата МСК | Причина | PnL RUB | Risk | Bars | Flags |")
    sep = "|----------|---------|---------|------|------|-------|"
    lines = [header, sep]
    for r in rows:
        lines.append(f"| {r['entry_date']} | {r['exit_reason']} | "
                     f"{r['pnl_rub']} | {r['risk_points']} | "
                     f"{r['bars_held']} | {r['flags']} |")
    return "\n".join(lines)


def _period_bd_table(rows: list[dict]) -> str:
    if not rows:
        return "_Нет данных._"
    lines = ["| Период | Сделок | W | L | WR% | Net RUB | PF | ⚠ |",
             "|--------|--------|---|---|-----|---------|----|----|"]
    for r in rows:
        ls = "LOW_SAMPLE" if r.get("low_sample") else ""
        pf = "∞" if r.get("profit_factor") == "inf" or r.get("profit_factor") == math.inf \
            else f"{float(r.get('profit_factor', 0)):.3f}"
        lines.append(f"| {r['period_label']} | {r['trades']} | {r['wins']} | "
                     f"{r['losses']} | {r['winrate']}% | {r['net_pnl']:+.2f} | {pf} | {ls} |")
    return "\n".join(lines)


def _counterfactual_section(
    source_label: str, actual: HourStats, without: HourStats, audit_h: int
) -> str:
    delta_net = round(without.net_pnl - actual.net_pnl, 2)
    sign = "+" if delta_net >= 0 else ""
    return (
        f"| | Фактически | Без часа {audit_h} | Δ |\n"
        f"|--|------------|----------------|---|\n"
        f"| Net PnL RUB | {actual.net_pnl:+.2f} | {without.net_pnl:+.2f} | {sign}{delta_net:.2f} |\n"
        f"| PF | {_pf_str(actual.profit_factor)} | {_pf_str(without.profit_factor)} | — |\n"
        f"| Сделок | {actual.trades} | {without.trades} | — |\n"
        f"| WR% | {actual.winrate}% | {without.winrate}% | — |\n"
        f"| MaxDD | {actual.max_drawdown:.2f} | {without.max_drawdown:.2f} | — |\n"
        f"\n> ⚠ Counterfactual on observed paper trades, not live execution proof.\n"
    )


def build_markdown_report(result: AuditResult, generated_at: str = "") -> str:
    h = result.audit_hour
    lines: list[str] = []

    lines.append(f"# Hour {h} Targeted Audit — SiM6 SELL\n")
    if generated_at:
        lines.append(f"Сгенерировано: {generated_at}\n")

    # ── Краткий вывод ──────────────────────────────────────────────────────────
    lines.append("## Краткий вывод\n")
    dec_map = {
        "A": "**A — Strong candidate for paper experiment** ✓",
        "B": "**B — Weak candidate / observe more** ⚠",
        "C": "**C — Reject** ✗",
    }
    lines.append(f"Candidate decision: {dec_map.get(result.candidate_decision, result.candidate_decision)}\n")
    lines.append(f"Overfit risk: **{result.overfit_risk}**\n")
    lines.append(f"Recommendation: {result.recommendation}\n")

    # ── Источники данных ───────────────────────────────────────────────────────
    lines.append("## Источники данных\n")
    if result.historical:
        lines.append(f"- Historical backtest: {result.historical.all_hours.period}")
    if result.live_baseline:
        lines.append(f"- Live baseline SQLite: {result.live_baseline.all_hours.period}")
    if result.live_maxhold5:
        lines.append(f"- Live maxhold5 SQLite: {result.live_maxhold5.all_hours.period}")
    lines.append("")

    # ── Helper: source section ─────────────────────────────────────────────────
    def _source_section(title: str, sa: SourceAudit, pnl_label: str = "pnl_rub") -> list[str]:
        out = [f"## {title}\n",
               "### Общая сводка\n",
               "| Сценарий | Сделок | W | L | WR% | Net RUB | PF | MaxDD |",
               "|----------|--------|---|---|-----|---------|----|----|"]
        out.append(_stats_row("Все часы", sa.all_hours))
        ls_flag = " ⚠ LOW_SAMPLE" if sa.audit_hour.low_sample else ""
        out.append(_stats_row(f"Час {h} только{ls_flag}", sa.audit_hour))
        out.append(_stats_row(f"Без часа {h}", sa.without_audit_hour))
        out.append("")
        out.append(f"### Детальные сделки в час {h}\n")
        out.append(_detail_table(sa.detail_trades_hour))
        out.append("")
        out.append(f"### Период-стабильность (разбивка по {sa.period_breakdown[0]['granularity'] if sa.period_breakdown else 'периодам'})\n")
        out.append(_period_bd_table(sa.period_breakdown))
        out.append("")
        out.append(f"### BIG_RISK / ONE_BAR_STOP в час {h}\n")
        ah = sa.audit_hour
        out.append(f"- BIG_RISK: {ah.big_risk_count} сделок, net {ah.big_risk_net:+.2f} RUB")
        out.append(f"- ONE_BAR_STOP: {ah.one_bar_stop_count} сделок, net {ah.one_bar_stop_net:+.2f} RUB")
        out.append(f"- Large winners (≥500 RUB): {ah.large_winner_count} шт, net {ah.large_winner_net:+.2f} RUB")
        out.append(f"- Large losers (≤−500 RUB): {ah.large_loser_count} шт, net {ah.large_loser_net:+.2f} RUB")
        out.append("")
        return out

    # ── Historical ─────────────────────────────────────────────────────────────
    if result.historical:
        lines.extend(_source_section("Historical backtest: час 12", result.historical))

    # ── Live baseline ──────────────────────────────────────────────────────────
    if result.live_baseline:
        lines.extend(_source_section("Live/paper baseline: час 12", result.live_baseline))

    # ── Live maxhold5 ──────────────────────────────────────────────────────────
    if result.live_maxhold5:
        lines.extend(_source_section("Live/paper maxhold5: час 12", result.live_maxhold5))

    # ── Counterfactual ─────────────────────────────────────────────────────────
    lines.append("## Counterfactual — без часа 12\n")
    if result.live_baseline:
        lines.append("### Live baseline\n")
        lines.append(_counterfactual_section("baseline", result.live_baseline.all_hours,
                                              result.live_baseline.without_audit_hour, h))
    if result.live_maxhold5:
        lines.append("### Live maxhold5\n")
        lines.append(_counterfactual_section("maxhold5", result.live_maxhold5.all_hours,
                                              result.live_maxhold5.without_audit_hour, h))

    # ── Big winners/losers impact ──────────────────────────────────────────────
    lines.append("## Big winners / big losers impact\n")
    lines.append(f"Threshold: large winner ≥ {_LARGE_WINNER_RUB:.0f} RUB, large loser ≤ {_LARGE_LOSER_RUB:.0f} RUB\n")
    lines.append("| Источник | Ч. {h} large winners | Ч. {h} large losers | Ч. {h} BIG_RISK | Ч. {h} ONE_BAR_STOP |".format(h=h))
    lines.append("|----------|----------------------|---------------------|-----------------|---------------------|")
    for sa in [result.historical, result.live_baseline, result.live_maxhold5]:
        if sa is None:
            continue
        ah = sa.audit_hour
        lines.append(f"| {sa.source} | {ah.large_winner_count} ({ah.large_winner_net:+.2f}) | "
                     f"{ah.large_loser_count} ({ah.large_loser_net:+.2f}) | "
                     f"{ah.big_risk_count} ({ah.big_risk_net:+.2f}) | "
                     f"{ah.one_bar_stop_count} ({ah.one_bar_stop_net:+.2f}) |")
    lines.append("")

    # ── Comparison with other hours ────────────────────────────────────────────
    lines.append("## Сравнение с другими часами\n")
    good_hours = [9, 10, 15, 22, 23]
    bad_hours = [11, 12, 13, 18, 19, 20, 21]

    for sa in [result.historical, result.live_baseline, result.live_maxhold5]:
        if sa is None or not sa.by_hour:
            continue
        lines.append(f"### {sa.source}\n")
        lines.append(_hour_table(sa.by_hour, good_hours, bad_hours))
        lines.append("")

    # ── Overfit risk ───────────────────────────────────────────────────────────
    lines.append("## Overfit risk assessment\n")
    lines.append(result.candidate_reason)
    lines.append(f"\n**Итоговая оценка: {result.overfit_risk}**\n")

    # ── Candidate decision ─────────────────────────────────────────────────────
    lines.append("## Candidate decision\n")
    lines.append(dec_map.get(result.candidate_decision, result.candidate_decision))
    lines.append(f"\n{result.recommendation}\n")

    # ── Следующий MVP ──────────────────────────────────────────────────────────
    lines.append("## Next MVP\n")
    if result.candidate_decision == "A":
        lines.append("**MVP-2.4 — Parallel Paper maxhold5 + exclude_hour_12 Experiment**")
        lines.append("")
        lines.append("Stop condition: PF < 1.25 after минимум 60 closed trades или 4 недели.")
    elif result.candidate_decision == "B":
        lines.append("Дополнительное наблюдение. Повторный аудит после набора ≥ 20 trades в час 12.")
    else:
        lines.append("Заморозить активную оптимизацию. Продолжить live paper с текущими параметрами.")

    return "\n".join(lines) + "\n"


# ── CSV output ────────────────────────────────────────────────────────────────

_CSV_FIELDS = [
    "source", "strategy", "period", "hour",
    "trades", "wins", "losses", "winrate",
    "net_pnl", "gross_profit", "gross_loss", "profit_factor",
    "expectancy", "best_trade", "worst_trade", "max_drawdown",
    "avg_bars_held",
    "big_risk_count", "big_risk_net",
    "one_bar_stop_count", "one_bar_stop_net",
    "large_winner_count", "large_winner_net",
    "large_loser_count", "large_loser_net",
    "low_sample",
]


def build_csv_rows(result: AuditResult) -> list[dict]:
    rows: list[dict] = []
    for sa in [result.historical, result.live_baseline, result.live_maxhold5]:
        if sa is None:
            continue
        for stats in [sa.all_hours, sa.audit_hour, sa.without_audit_hour]:
            rows.append(stats.to_dict())
        for _h, s in sorted(sa.by_hour.items()):
            rows.append(s.to_dict())
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
