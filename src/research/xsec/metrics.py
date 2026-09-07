"""Метрики и применение пре-зафиксированных критериев отсечения.

Пороги взяты из docs/claude_code_mvp_d1_daily_horizon_plan.md §7 и намеренно
захардкожены здесь: если критерий живёт в коде, его смягчение постфактум видно
в диффе. Именно этого не хватало прошлым итерациям проекта.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .engine import Result

TRADING_DAYS_YEAR = 252


@dataclass
class Criteria:
    """Пороги из §7 плана. Не смягчать по факту результата."""
    min_sharpe: float = 0.5
    min_cagr: float = 0.05
    max_drawdown: float = 0.25
    max_bench_corr: float = 0.30
    max_cost_drag: float = 0.25
    min_positive_years: float = 0.60
    max_top1_name_share: float = 0.25
    max_top1_year_share: float = 0.50
    # тесты на устойчивость
    stress_min_sharpe: float = 0.30


def max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1.0).min())


def summarize(res: Result, bench: pd.Series | None = None) -> dict:
    r = res.ret
    live = r.loc[r.ne(0).idxmax():] if r.ne(0).any() else r
    years = len(live) / TRADING_DAYS_YEAR
    eq = (1.0 + live).cumprod()

    total = float(eq.iloc[-1]) if len(eq) else 1.0
    cagr = total ** (1 / years) - 1.0 if years > 0 and total > 0 else float("nan")
    vol = float(live.std() * np.sqrt(TRADING_DAYS_YEAR))
    sharpe = float(live.mean() / live.std() * np.sqrt(TRADING_DAYS_YEAR)) if live.std() > 0 else float("nan")

    gross_total = float(res.gross_ret.loc[live.index].sum())
    cost_total = float(res.cost.loc[live.index].sum())
    cost_drag = cost_total / abs(gross_total) if gross_total else float("inf")

    by_year = live.groupby(live.index.year).apply(lambda s: float((1 + s).prod() - 1))
    pos_years = float((by_year > 0).mean()) if len(by_year) else float("nan")

    pnl_by_name = res.contrib.loc[live.index].sum()
    tot_pnl = float(pnl_by_name.sum())
    top1_name = float(pnl_by_name.max() / tot_pnl) if tot_pnl > 0 else float("nan")

    yr_pos = by_year[by_year > 0]
    top1_year = float(yr_pos.max() / yr_pos.sum()) if len(yr_pos) and yr_pos.sum() > 0 else float("nan")

    out = {
        "years": years,
        "total_return": total - 1.0,
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "max_dd": max_drawdown(eq),
        "gross_return_sum": gross_total,
        "cost_sum": cost_total,
        "cost_drag": cost_drag,
        "turnover_per_year": float(res.turnover.loc[live.index].sum() / years) if years else float("nan"),
        "positive_years": pos_years,
        "by_year": by_year.to_dict(),
        "top1_name_share": top1_name,
        "top1_year_share": top1_year,
        "n_long_avg": float(res.n_long.loc[live.index].mean()),
        "n_short_avg": float(res.n_short.loc[live.index].mean()),
    }

    if bench is not None:
        b = bench.reindex(live.index).pct_change().fillna(0.0)
        out["bench_corr"] = float(live.corr(b)) if b.std() > 0 else float("nan")
        bt = float((1 + b).prod())
        out["bench_cagr"] = bt ** (1 / years) - 1.0 if years > 0 and bt > 0 else float("nan")
        out["bench_max_dd"] = max_drawdown((1 + b).cumprod())
    return out


def check(summary: dict, market_neutral: bool, crit: Criteria = Criteria()) -> dict:
    """Применяет критерии §7. Возвращает {критерий: (значение, порог, прошёл)}."""
    c: dict[str, tuple] = {}

    def add(name, val, ok, target):
        c[name] = (val, target, bool(ok))

    s = summary
    add("sharpe", s["sharpe"], s["sharpe"] >= crit.min_sharpe, f"≥{crit.min_sharpe}")
    add("max_dd", s["max_dd"], s["max_dd"] >= -crit.max_drawdown, f"≥−{crit.max_drawdown:.0%}")
    add("cost_drag", s["cost_drag"], s["cost_drag"] <= crit.max_cost_drag, f"≤{crit.max_cost_drag:.0%}")
    add("positive_years", s["positive_years"], s["positive_years"] >= crit.min_positive_years,
        f"≥{crit.min_positive_years:.0%}")
    add("top1_name_share", s["top1_name_share"],
        not (s["top1_name_share"] > crit.max_top1_name_share), f"≤{crit.max_top1_name_share:.0%}")
    add("top1_year_share", s["top1_year_share"],
        not (s["top1_year_share"] > crit.max_top1_year_share), f"≤{crit.max_top1_year_share:.0%}")

    if market_neutral:
        add("cagr", s["cagr"], s["cagr"] >= crit.min_cagr, f"≥{crit.min_cagr:.0%}")
        bc = s.get("bench_corr", float("nan"))
        add("bench_corr", bc, abs(bc) <= crit.max_bench_corr if bc == bc else False,
            f"|corr|≤{crit.max_bench_corr}")
    else:
        bcagr = s.get("bench_cagr", float("nan"))
        add("cagr_vs_bench", s["cagr"], s["cagr"] > bcagr if bcagr == bcagr else False,
            f">бенчмарк {bcagr:.1%}" if bcagr == bcagr else ">бенчмарк")
        bdd = s.get("bench_max_dd", float("nan"))
        add("dd_vs_bench", s["max_dd"], s["max_dd"] >= bdd if bdd == bdd else False,
            f"≥бенчмарк {bdd:.1%}" if bdd == bdd else "≥бенчмарк")

    c["__passed__"] = (sum(v[2] for v in c.values()), len(c), all(v[2] for v in c.values()))
    return c


def format_table(name: str, summary: dict, checks: dict) -> str:
    lines = [f"### {name}", ""]
    s = summary
    lines.append(f"*{s['years']:.1f} лет · CAGR {s['cagr']:.2%} · vol {s['vol']:.2%} · "
                 f"Sharpe {s['sharpe']:.2f} · maxDD {s['max_dd']:.1%} · "
                 f"оборот {s['turnover_per_year']:.1f}×/год · cost drag {s['cost_drag']:.1%}*")
    lines += ["", "| критерий | значение | порог | ok |", "|---|---|---|---|"]
    for k, (val, target, ok) in checks.items():
        if k.startswith("__"):
            continue
        v = f"{val:.2%}" if k in ("cagr", "max_dd", "cost_drag", "positive_years",
                                  "top1_name_share", "top1_year_share", "cagr_vs_bench",
                                  "dd_vs_bench") else f"{val:.2f}"
        lines.append(f"| {k} | {v} | {target} | {'✅' if ok else '❌'} |")
    n_ok, n_tot, passed = checks["__passed__"]
    lines += ["", f"**{n_ok}/{n_tot} критериев · {'ПРОШЁЛ' if passed else 'НЕ ПРОШЁЛ'}**", ""]
    if s.get("by_year"):
        yr = " · ".join(f"{y}: {v:+.1%}" for y, v in sorted(s["by_year"].items()))
        lines += [f"по годам: {yr}", ""]
    return "\n".join(lines)
