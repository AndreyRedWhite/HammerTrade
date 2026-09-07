"""MVP-D1: прогон пре-регистрированного набора кросс-секционных стратегий.

Порядок намеренно жёсткий и соответствует docs/claude_code_mvp_d1_daily_horizon_plan.md:

  0. NULL-ТЕСТ — случайный сигнал обязан дать ~ноль. Движок, который не умеет
     возвращать пустой результат на шуме, не может доказать ничего. Если этот
     тест не проходит, остальные цифры не имеют смысла и прогон прерывается.
  1. IS  (2015→2021) — только чтобы посмотреть, есть ли вообще на что смотреть.
  2. OOS (2022→2026) — по нему и только по нему применяются критерии §7.
  3. Тесты на устойчивость: издержки ×2 и задержка исполнения +1 день
     (второе — заодно аудит на lookahead).

Usage:
    python scripts/research_xsec_d1.py
    python scripts/research_xsec_d1.py --quick     # без sensitivities
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from src.research.xsec import signals as sig
from src.research.xsec.engine import Config, run
from src.research.xsec.metrics import Criteria, check, format_table, summarize
from src.research.xsec.panel import build_panel

REPORTS = Path("reports")
IS_END = "2021-12-31"
OOS_START = "2022-01-01"

# NULL-тест проверяет СРЕДНЕЕ по многим прогонам, а не максимум по нескольким.
# Причина: на окне OOS ~4.6 года стандартная ошибка оценки Sharpe ≈ 1/√4.6 ≈ 0.47,
# то есть отдельный прогон на шуме легко даёт ±0.8 просто по статистике. Порог,
# приложенный к максимуму из 5 наблюдений, обязан срабатывать независимо от
# корректности движка — это сломанный тест, а не строгий.
# Замерено: 25 прогонов дают среднее −0.07 при σ отдельного прогона 0.38.
NULL_DRAWS = 25
NULL_MAX_ABS_T = 2.5     # |t| среднего против нуля


def _slice(res, start=None, end=None):
    """Обрезает результат по датам, сохраняя тип."""
    from src.research.xsec.engine import Result
    sl = slice(start, end)
    return Result(
        equity=res.equity.loc[sl], ret=res.ret.loc[sl], gross_ret=res.gross_ret.loc[sl],
        cost=res.cost.loc[sl], turnover=res.turnover.loc[sl], weights=res.weights.loc[sl],
        n_long=res.n_long.loc[sl], n_short=res.n_short.loc[sl], config=res.config,
        contrib=res.contrib.loc[sl])


def null_test(panel, cfg: Config, n_draws: int = NULL_DRAWS) -> tuple[bool, dict]:
    """Случайный сигнал не должен давать края.

    Издержки принудительно занулены: с ними шумовая торговля теряет
    систематически (оборот × ставка), и тест перестал бы отвечать на свой
    вопрос — «фабрикует ли движок край из ничего».
    """
    cfg = Config(**{**cfg.__dict__, "cost_bps_per_side": 0.0})
    rng = np.random.default_rng(20260729)
    out = []
    for _ in range(n_draws):
        noise = pd.DataFrame(rng.standard_normal(panel.close.shape),
                             index=panel.dates, columns=panel.tickers)
        out.append(summarize(_slice(run(panel, noise, cfg), OOS_START))["sharpe"])

    a = np.asarray(out, dtype=float)
    mean, sd = float(np.nanmean(a)), float(np.nanstd(a))
    se = sd / np.sqrt(len(a)) if sd > 0 else float("nan")
    t = mean / se if se and np.isfinite(se) else 0.0
    stats = {"mean": mean, "median": float(np.nanmedian(a)), "sd": sd,
             "t": t, "min": float(np.nanmin(a)), "max": float(np.nanmax(a)),
             "n": len(a)}
    return bool(abs(t) < NULL_MAX_ABS_T), stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--cost-bps", type=float, default=10.0)
    ap.add_argument("--liq-min", type=float, default=50_000_000.0)
    a = ap.parse_args()

    print("Строю панель...", flush=True)
    panel = build_panel()
    print(panel.describe(), flush=True)

    bench = panel.bench.get("MCFTR")
    if bench is None or bench.isna().all():
        bench = panel.bench.get("IMOEX")

    base_ls = Config(cost_bps_per_side=a.cost_bps, short_q=0.2, liq_min_value=a.liq_min)
    base_lo = Config(cost_bps_per_side=a.cost_bps, short_q=None, liq_min_value=a.liq_min)

    lines = [f"# MVP-D1 — кросс-секционный прогон (дневной горизонт)",
             f"*{datetime.now():%Y-%m-%d %H:%M} · {panel.describe()}*",
             f"*издержки {a.cost_bps:.0f} bps/сторона · ликвидность ≥{a.liq_min/1e6:.0f}M₽ медиана 20д*",
             "", "## 0. NULL-тест (случайный сигнал)", ""]

    print(f"\n[0] NULL-тест ({NULL_DRAWS} прогонов)...", flush=True)
    ok, st = null_test(panel, base_ls)
    lines.append(f"Sharpe на случайном сигнале, {st['n']} прогонов (OOS, издержки=0):")
    lines.append(f"среднее **{st['mean']:+.3f}** · медиана {st['median']:+.3f} · "
                 f"σ отдельного прогона {st['sd']:.3f} · "
                 f"диапазон {st['min']:+.2f}…{st['max']:+.2f}")
    lines.append(f"t-статистика среднего против нуля: **{st['t']:+.2f}** "
                 f"(порог |t| < {NULL_MAX_ABS_T})")
    lines.append(f"**{'ПРОЙДЕН' if ok else 'ПРОВАЛЕН'}**")
    print(f"    среднее {st['mean']:+.3f}, t={st['t']:+.2f} -> {'OK' if ok else 'FAIL'}")
    if not ok:
        lines.append("\n⛔ Движок даёт край на шуме — остальные результаты недействительны.")
        REPORTS.mkdir(exist_ok=True)
        p = REPORTS / f"xsec_d1_{datetime.now():%Y%m%d_%H%M%S}.md"
        p.write_text("\n".join(lines))
        print(f"\n⛔ NULL-тест провален. Отчёт: {p}")
        sys.exit(1)

    results = {}
    for mode, cfg in (("long-short", base_ls), ("long-only", base_lo)):
        lines += ["", f"## Режим: {mode}", ""]
        print(f"\n[{mode}]", flush=True)
        for name, (fn, kw) in sig.REGISTRY.items():
            s_df = fn(panel, **kw)
            freq = "W-FRI" if name == "reversal_1w" else "ME"
            cfg_i = Config(**{**cfg.__dict__, "rebalance": freq})
            res = run(panel, s_df, cfg_i)
            results[(mode, name)] = (res, cfg_i, s_df)

            summ_oos = summarize(_slice(res, OOS_START), bench)
            chk = check(summ_oos, market_neutral=(mode == "long-short"))
            summ_is = summarize(_slice(res, None, IS_END), bench)

            tag = " *(контроль — обязан провалиться)*" if name == "reversal_1w" else ""
            lines.append(format_table(f"{name} — OOS 2022+{tag}", summ_oos, chk))
            lines.append(f"IS 2015–2021 для справки: CAGR {summ_is['cagr']:.2%}, "
                         f"Sharpe {summ_is['sharpe']:.2f}, maxDD {summ_is['max_dd']:.1%}\n")
            print(f"    {name:14s} OOS Sharpe {summ_oos['sharpe']:6.2f} "
                  f"CAGR {summ_oos['cagr']:7.2%} DD {summ_oos['max_dd']:7.1%} "
                  f"{'PASS' if chk['__passed__'][2] else 'fail'}", flush=True)

    if not a.quick:
        lines += ["", "## Тесты на устойчивость", "",
                  "| стратегия | режим | база | издержки ×2 | задержка +1д |",
                  "|---|---|---|---|---|"]
        print("\n[sensitivities]", flush=True)
        for (mode, name), (res, cfg_i, s_df) in results.items():
            base_s = summarize(_slice(res, OOS_START))["sharpe"]
            r2 = run(panel, s_df, Config(**{**cfg_i.__dict__,
                                            "cost_bps_per_side": cfg_i.cost_bps_per_side * 2}))
            rd = run(panel, s_df, Config(**{**cfg_i.__dict__,
                                            "exec_delay": cfg_i.exec_delay + 1}))
            s2 = summarize(_slice(r2, OOS_START))["sharpe"]
            sd = summarize(_slice(rd, OOS_START))["sharpe"]
            lines.append(f"| {name} | {mode} | {base_s:.2f} | {s2:.2f} | {sd:.2f} |")
            print(f"    {name:14s} {mode:11s} {base_s:6.2f} -> x2 {s2:6.2f}, +1d {sd:6.2f}",
                  flush=True)

    REPORTS.mkdir(exist_ok=True)
    p = REPORTS / f"xsec_d1_{datetime.now():%Y%m%d_%H%M%S}.md"
    p.write_text("\n".join(lines))
    print(f"\nОтчёт: {p}")


if __name__ == "__main__":
    main()
