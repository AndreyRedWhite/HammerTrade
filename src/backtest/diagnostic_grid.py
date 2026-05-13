"""Phase A / Phase B grid orchestration for diagnostic filter experiments.

Generates scenarios, runs backtests, ranks results, and builds the Markdown
report comparing each filter scenario against the baseline.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from src.backtest.diagnostic_filters import (
    FilterConfig,
    ScenarioResult,
    run_scenario,
)


@dataclass
class BacktestParams:
    stop_buffer_points: float = 0.0
    take_r: float = 1.0
    slippage_points: float = 0.0
    slippage_ticks: Optional[float] = None
    tick_size: Optional[float] = None
    point_value_rub: float = 10.0
    commission_per_trade: float = 0.025
    contracts: int = 1
    entry_horizon_bars: int = 3
    default_max_hold_bars: int = 30
    allow_overlap: bool = False
    min_trades_required: int = 30
    direction: str = "SELL"


def _make_baseline_config(params: BacktestParams) -> FilterConfig:
    return FilterConfig(
        scenario_name="baseline",
        direction=params.direction,
        min_trades_required=params.min_trades_required,
    )


def _time_filter_configs(time_filters: list[dict], params: BacktestParams) -> list[FilterConfig]:
    configs = []
    for tf in time_filters:
        name = tf.get("name", "")
        if name == "all_hours":
            continue  # all_hours is the baseline — skip here
        configs.append(FilterConfig(
            scenario_name=f"time_{name}",
            direction=params.direction,
            time_filter_name=name,
            exclude_hours_msk=tf.get("exclude_hours_msk", []) or [],
            include_hours_msk=tf.get("include_hours_msk") or None,
            min_trades_required=params.min_trades_required,
        ))
    return configs


def make_phase_a_configs(cfg: dict, params: BacktestParams) -> list[FilterConfig]:
    """Generates single-factor Phase A filter configs (excluding baseline)."""
    f = cfg.get("filters", {})
    configs: list[FilterConfig] = []

    # MIN_REWARD_POINTS
    for mrp in f.get("min_reward_points", []):
        if mrp == 0:
            continue
        configs.append(FilterConfig(
            scenario_name=f"min_reward_{mrp}",
            direction=params.direction,
            min_reward_points=float(mrp),
            min_trades_required=params.min_trades_required,
        ))

    # MIN_RR
    for mrr in f.get("min_rr", []):
        if mrr == 0.0:
            continue
        configs.append(FilterConfig(
            scenario_name=f"min_rr_{str(mrr).replace('.', '_')}",
            direction=params.direction,
            min_rr=float(mrr),
            min_trades_required=params.min_trades_required,
        ))

    # Time filters
    configs.extend(_time_filter_configs(f.get("time_filter", []), params))

    # MAX_HOLD_BARS
    for mhb in f.get("max_hold_bars", []):
        if mhb is None:
            continue
        configs.append(FilterConfig(
            scenario_name=f"max_hold_{mhb}",
            direction=params.direction,
            max_hold_bars=int(mhb),
            min_trades_required=params.min_trades_required,
        ))

    # ENTRY_CONFIRMATION
    for ec in f.get("entry_confirmation", []):
        if ec == "baseline":
            continue
        configs.append(FilterConfig(
            scenario_name=f"confirm_{ec}",
            direction=params.direction,
            entry_confirmation=ec,
            min_trades_required=params.min_trades_required,
        ))

    return configs


def make_phase_b_configs(cfg: dict, params: BacktestParams) -> list[FilterConfig]:
    """Generates combined Phase B filter configs."""
    pb = cfg.get("phase_b", {})
    f = cfg.get("filters", {})

    reward_values = [float(x) for x in pb.get("min_reward_points", [0, 5, 6])]
    rr_values = [float(x) for x in pb.get("min_rr", [0.0, 0.8])]
    tf_names = pb.get("time_filter", ["all_hours", "exclude_bad_paper_hours"])

    # Build time_filter lookup
    tf_map: dict[str, dict] = {"all_hours": {"name": "all_hours", "exclude_hours_msk": [], "include_hours_msk": None}}
    for tf in f.get("time_filter", []):
        tf_map[tf["name"]] = tf

    configs: list[FilterConfig] = []
    for mrp in reward_values:
        for mrr in rr_values:
            for tf_name in tf_names:
                tf_spec = tf_map.get(tf_name, {})
                name = f"B_rwd{int(mrp)}_rr{str(mrr).replace('.', '')}_tf_{tf_name}"
                configs.append(FilterConfig(
                    scenario_name=name,
                    direction=params.direction,
                    min_reward_points=mrp,
                    min_rr=mrr,
                    time_filter_name=tf_name,
                    exclude_hours_msk=tf_spec.get("exclude_hours_msk", []) or [],
                    include_hours_msk=tf_spec.get("include_hours_msk") or None,
                    min_trades_required=params.min_trades_required,
                ))
    return configs


def run_all_scenarios(
    debug_df: pd.DataFrame,
    params: BacktestParams,
    cfg: dict,
) -> tuple[ScenarioResult, list[ScenarioResult], list[ScenarioResult], dict[str, pd.DataFrame]]:
    """Runs baseline + Phase A + Phase B. Returns (baseline, phase_a, phase_b, trades_map)."""
    def _run(fc: FilterConfig, sid: int):
        return run_scenario(
            debug_df=debug_df,
            filter_config=fc,
            scenario_id=sid,
            stop_buffer_points=params.stop_buffer_points,
            take_r=params.take_r,
            slippage_points=params.slippage_points,
            slippage_ticks=params.slippage_ticks,
            tick_size=params.tick_size,
            point_value_rub=params.point_value_rub,
            commission_per_trade=params.commission_per_trade,
            contracts=params.contracts,
            entry_horizon_bars=params.entry_horizon_bars,
            default_max_hold_bars=params.default_max_hold_bars,
            allow_overlap=params.allow_overlap,
        )

    sid = 0
    trades_map: dict[str, pd.DataFrame] = {}

    sid += 1
    baseline_result, baseline_trades = _run(_make_baseline_config(params), sid)
    trades_map[baseline_result.scenario_name] = baseline_trades

    phase_a_configs = make_phase_a_configs(cfg, params)
    phase_a: list[ScenarioResult] = []
    for fc in phase_a_configs:
        sid += 1
        r, t = _run(fc, sid)
        phase_a.append(r)
        trades_map[r.scenario_name] = t

    phase_b_configs = make_phase_b_configs(cfg, params)
    phase_b: list[ScenarioResult] = []
    for fc in phase_b_configs:
        sid += 1
        r, t = _run(fc, sid)
        phase_b.append(r)
        trades_map[r.scenario_name] = t

    return baseline_result, phase_a, phase_b, trades_map


def rank_scenarios(
    baseline: ScenarioResult,
    all_results: list[ScenarioResult],
    top_n: int = 10,
) -> dict[str, list[ScenarioResult]]:
    """Returns rankings by net_pnl, profit_factor, and risk_adjusted_score."""
    eligible = [r for r in all_results if not r.is_low_sample]
    all_inc_baseline = [baseline] + all_results

    by_pnl = sorted(all_inc_baseline, key=lambda r: r.net_pnl_rub, reverse=True)[:top_n]
    by_pf = sorted(eligible + [baseline], key=lambda r: r.profit_factor, reverse=True)[:top_n]
    by_score = sorted(all_inc_baseline, key=lambda r: r.risk_adjusted_score, reverse=True)[:top_n]
    by_robustness = [
        r for r in eligible + [baseline]
        if (r.profit_factor >= baseline.profit_factor
            and r.trades >= int(baseline.trades * 0.7)
            and r.profitable_periods_pct >= baseline.profitable_periods_pct)
    ]
    by_robustness.sort(key=lambda r: r.profit_factor, reverse=True)

    return {
        "by_net_pnl": by_pnl,
        "by_profit_factor": by_pf,
        "by_risk_adjusted": by_score,
        "robust": by_robustness[:top_n],
    }


# ─────────────────────────── Markdown report ──────────────────────────────

def _arrow(delta: float, threshold: float = 0.001) -> str:
    if delta > threshold:
        return "▲"
    if delta < -threshold:
        return "▼"
    return "="


def _pct_str(v: float) -> str:
    return f"{v:+.1f}%" if v != 0 else "0.0%"


def _row_vs_baseline(r: ScenarioResult, baseline: ScenarioResult) -> str:
    dpf = r.profit_factor - baseline.profit_factor
    dpnl = r.net_pnl_rub - baseline.net_pnl_rub
    ddd = r.max_drawdown_rub - baseline.max_drawdown_rub  # lower is better, negative = improved
    sample_flag = " ⚠️ LOW_SAMPLE" if r.is_low_sample else ""
    return (
        f"PF {_arrow(dpf)} {dpf:+.3f}; "
        f"PnL {_arrow(dpnl)} {dpnl:+.0f} руб; "
        f"DD {_arrow(-ddd)} {ddd:+.0f} руб"
        f"{sample_flag}"
    )


def _scenario_table_row(r: ScenarioResult, baseline: ScenarioResult) -> str:
    vs = _row_vs_baseline(r, baseline)
    return (
        f"| {r.scenario_name} "
        f"| {r.trades} "
        f"| {r.skip_rate_pct:.0f}% "
        f"| {r.winrate_pct:.1f}% "
        f"| {r.net_pnl_rub:+.0f} "
        f"| {r.profit_factor:.3f} "
        f"| {r.max_drawdown_rub:.0f} "
        f"| {r.profitable_periods_pct:.0f}% ({r.profitable_periods_count}/{r.periods_count}) "
        f"| {vs} |"
    )


_TABLE_HEADER = (
    "| Сценарий | Сделки | Skip% | Winrate | Net PnL | PF | Max DD | Дн. стаб. | vs baseline |\n"
    "|---|---:|---:|---:|---:|---:|---:|---|---|"
)


def build_markdown_report(
    baseline: ScenarioResult,
    phase_a: list[ScenarioResult],
    phase_b: list[ScenarioResult],
    rankings: dict[str, list[ScenarioResult]],
    ticker: str,
    direction: str,
    period_from: str,
    period_to: str,
    params: BacktestParams,
    cfg: dict,
) -> str:
    lines: list[str] = []
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append(f"# Backtest Diagnostic Filters — {ticker} {direction}")
    lines.append("")
    lines.append(f"_Сгенерировано: {ts}_")
    lines.append("")

    # Context
    lines.append("## Контекст")
    lines.append("")
    lines.append(f"- Ticker: {ticker}")
    lines.append(f"- Direction: {direction}")
    lines.append(f"- Период данных: {period_from} — {period_to}")
    lines.append(f"- take_r: {params.take_r}")
    lines.append(f"- stop_buffer_points: {params.stop_buffer_points}")
    lines.append(f"- slippage_points: {params.slippage_points}")
    lines.append(f"- default_max_hold_bars: {params.default_max_hold_bars}")
    lines.append(f"- min_trades_required: {params.min_trades_required}")
    lines.append("")

    # Источник данных
    lines.append("## Источник данных")
    lines.append("")
    signals_csv = cfg.get("data", {}).get("signals_csv", "out/debug_simple_all.csv")
    lines.append(f"- Файл сигналов: `{signals_csv}`")
    lines.append(f"- Сигналов ({direction}) в периоде: {baseline.n_original_signals}")
    lines.append("")

    # Baseline
    lines.append("## Baseline")
    lines.append("")
    lines.append("Запуск без каких-либо фильтров.")
    lines.append("")
    lines.append("| Метрика | Значение |")
    lines.append("|---------|----------|")
    lines.append(f"| Сигналов ({direction}) | {baseline.n_original_signals} |")
    lines.append(f"| Сделок | {baseline.trades} |")
    lines.append(f"| WIN | {baseline.wins} |")
    lines.append(f"| LOSS | {baseline.losses} |")
    lines.append(f"| Winrate | {baseline.winrate_pct:.1f}% |")
    lines.append(f"| Gross profit | +{baseline.gross_profit_rub:.0f} руб |")
    lines.append(f"| Gross loss | {baseline.gross_loss_rub:.0f} руб |")
    lines.append(f"| Net PnL | {baseline.net_pnl_rub:+.0f} руб |")
    lines.append(f"| Profit Factor | {baseline.profit_factor:.3f} |")
    lines.append(f"| Expectancy | {baseline.expectancy_rub:+.2f} руб/сделка |")
    lines.append(f"| Best trade | +{baseline.best_trade_rub:.0f} руб |")
    lines.append(f"| Worst trade | {baseline.worst_trade_rub:.0f} руб |")
    lines.append(f"| Max Drawdown | {baseline.max_drawdown_rub:.0f} руб ({baseline.max_drawdown_pct:.1f}%) |")
    lines.append(f"| Avg risk points | {baseline.avg_risk_points:.1f} |")
    lines.append(f"| Avg bars held | {baseline.avg_bars_held:.1f} |")
    lines.append(f"| Дней торговых | {baseline.periods_count} |")
    lines.append(f"| Прибыльных дней | {baseline.profitable_periods_count} ({baseline.profitable_periods_pct:.0f}%) |")
    if baseline.is_low_sample:
        lines.append(f"| ⚠️ LOW_SAMPLE | {baseline.trades} < min={params.min_trades_required} |")
    lines.append("")

    # Phase A
    lines.append("## Phase A — Однофакторный анализ")
    lines.append("")
    lines.append("Каждый фильтр проверяется отдельно против baseline.")
    lines.append("")

    def _phase_a_section(title: str, note: str, subset: list[ScenarioResult]) -> None:
        lines.append(f"### {title}")
        lines.append("")
        if note:
            lines.append(f"_{note}_")
            lines.append("")
        lines.append(_TABLE_HEADER)
        lines.append(_scenario_table_row(baseline, baseline).replace("| vs baseline |", "| baseline |"))
        for r in subset:
            lines.append(_scenario_table_row(r, baseline))
        lines.append("")

    # MIN_REWARD
    reward_scenarios = [r for r in phase_a if r.filter_config.min_reward_points > 0
                        and r.filter_config.min_rr == 0
                        and not r.filter_config.exclude_hours_msk
                        and r.filter_config.include_hours_msk is None
                        and r.filter_config.max_hold_bars is None
                        and r.filter_config.entry_confirmation == "baseline"]
    _phase_a_section(
        "1. MIN_REWARD_POINTS",
        "Сигналы с reward_points < порога пропускаются. "
        "reward_points = (sig_high − sig_low + stop_buffer) × take_r.",
        reward_scenarios,
    )

    # MIN_RR
    rr_scenarios = [r for r in phase_a if r.filter_config.min_rr > 0
                    and r.filter_config.min_reward_points == 0
                    and not r.filter_config.exclude_hours_msk
                    and r.filter_config.include_hours_msk is None
                    and r.filter_config.max_hold_bars is None
                    and r.filter_config.entry_confirmation == "baseline"]
    rr_note = (
        "⚠️ Ограничение модели: в breakout-режиме без slippage rr = take_r для всех сигналов. "
        f"При take_r={params.take_r} фильтр min_rr ≤ {params.take_r} не исключает ни одного сигнала. "
        "Это не ошибка — результаты идентичны baseline."
    )
    _phase_a_section("2. MIN_RR", rr_note, rr_scenarios)

    # Time filters
    time_scenarios = [r for r in phase_a if r.filter_config.time_filter_name != "all_hours"
                      and r.filter_config.min_reward_points == 0
                      and r.filter_config.min_rr == 0
                      and r.filter_config.max_hold_bars is None
                      and r.filter_config.entry_confirmation == "baseline"]
    _phase_a_section(
        "3. Time filters",
        "⚠️ Осторожно с переобучением: time filter выбирает часы по paper trading данным (~30 сделок). "
        "Historical backtest может подтвердить или опровергнуть гипотезу, но не доказать её.",
        time_scenarios,
    )

    # Max hold bars
    hold_scenarios = [r for r in phase_a if r.filter_config.max_hold_bars is not None
                      and r.filter_config.min_reward_points == 0
                      and r.filter_config.min_rr == 0
                      and r.filter_config.time_filter_name == "all_hours"
                      and r.filter_config.entry_confirmation == "baseline"]
    _phase_a_section("4. Max hold bars", "", hold_scenarios)

    # Entry confirmation
    confirm_scenarios = [r for r in phase_a if r.filter_config.entry_confirmation != "baseline"
                         and r.filter_config.min_reward_points == 0
                         and r.filter_config.min_rr == 0
                         and r.filter_config.time_filter_name == "all_hours"
                         and r.filter_config.max_hold_bars is None]
    _phase_a_section(
        "5. Entry confirmation",
        "breakout_confirmation эквивалентен baseline: движок уже использует breakout entry. "
        "next_candle_direction требует, чтобы свеча после сигнала была медвежьей (close < open) для SELL.",
        confirm_scenarios,
    )

    # Phase B
    lines.append("## Phase B — Комбинированные сценарии")
    lines.append("")
    lines.append("Сетка лучших кандидатов из Phase A: min_reward × min_rr × time_filter.")
    lines.append("")
    if phase_b:
        lines.append(_TABLE_HEADER)
        for r in phase_b:
            lines.append(_scenario_table_row(r, baseline))
        lines.append("")
    else:
        lines.append("_Phase B не содержит сценариев._")
        lines.append("")

    # Rankings
    def _ranking_table(title: str, results: list[ScenarioResult]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if not results:
            lines.append("_Нет подходящих сценариев._")
            lines.append("")
            return
        lines.append(_TABLE_HEADER)
        for r in results:
            lines.append(_scenario_table_row(r, baseline))
        lines.append("")

    _ranking_table("Top scenarios by Net PnL", rankings.get("by_net_pnl", []))
    _ranking_table("Top scenarios by Profit Factor", rankings.get("by_profit_factor", []))
    _ranking_table("Top scenarios by risk-adjusted score", rankings.get("by_risk_adjusted", []))
    _ranking_table("Robustness (PF≥baseline, trades≥70% baseline, days≥baseline)", rankings.get("robust", []))

    # Period stability
    lines.append("## Robustness / period stability")
    lines.append("")
    lines.append("Дневная устойчивость по топ-5 сценариям (по risk-adjusted score):")
    lines.append("")
    lines.append("| Сценарий | Дней | Прибыльных | % | Лучший день | Худший день | Avg/день |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    top5 = ([baseline] + rankings.get("by_risk_adjusted", []))[:6]
    seen_ids: set[int] = set()
    for r in top5:
        if r.scenario_id in seen_ids:
            continue
        seen_ids.add(r.scenario_id)
        lines.append(
            f"| {r.scenario_name} "
            f"| {r.periods_count} "
            f"| {r.profitable_periods_count} "
            f"| {r.profitable_periods_pct:.0f}% "
            f"| +{r.best_period_pnl:.0f} "
            f"| {r.worst_period_pnl:.0f} "
            f"| {r.avg_period_pnl:+.0f} |"
        )
    lines.append("")

    # Paper trading comparison
    lines.append("## Comparison with paper trading hypotheses")
    lines.append("")
    lines.append("| Гипотеза paper trading | Бэктест | Подтвердилась? |")
    lines.append("|---|---|---|")

    reward5 = next((r for r in phase_a if "min_reward_5" in r.scenario_name), None)
    if reward5:
        confirmed = "✅ Да" if reward5.profit_factor > baseline.profit_factor else "❌ Нет"
        lines.append(
            f"| TINY_TAKE: reward<5 → плохие сделки (paper: PF=0.15) "
            f"| min_reward=5: PF={reward5.profit_factor:.3f} vs baseline {baseline.profit_factor:.3f} "
            f"| {confirmed} |"
        )
    lines.append(
        f"| LOW_RR: rr<0.8 → убыточные (paper: net -50 RUб, PF=0.83) "
        f"| Не применимо: rr=take_r=1.0 всегда в backtest "
        f"| ⚠️ N/A — ограничение модели |"
    )

    conf_ncd = next((r for r in phase_a if "next_candle" in r.scenario_name), None)
    if conf_ncd:
        skip_pct = conf_ncd.skip_rate_pct
        dpf = conf_ncd.profit_factor - baseline.profit_factor
        confirmed = "✅ Частично" if dpf > 0 else "❌ Нет"
        lines.append(
            f"| ONE_BAR_STOP: ранние стопы можно срезать подтверждением "
            f"| next_candle_direction: PF={conf_ncd.profit_factor:.3f}, skip={skip_pct:.0f}% "
            f"| {confirmed} |"
        )
    lines.append(
        "| BARS_001 сильнее BARS_002_003 / BARS_004_010 "
        "| Проверяется через max_hold_bars сценарии "
        "| — |"
    )
    lines.append("")

    # Candidate filters
    lines.append("## Candidate filters for next paper trading config")
    lines.append("")
    all_results_combined = [baseline] + phase_a + phase_b
    candidates = [
        r for r in all_results_combined
        if r.scenario_id != baseline.scenario_id
        and not r.is_low_sample
        and r.profit_factor > baseline.profit_factor
        and r.trades >= int(baseline.trades * 0.7)
    ]
    candidates.sort(key=lambda r: r.profit_factor, reverse=True)

    if candidates:
        lines.append("### Вариант A — Есть кандидаты")
        lines.append("")
        lines.append("Сценарии, где PF > baseline и trades ≥ 70% baseline:")
        lines.append("")
        for c in candidates[:3]:
            fc = c.filter_config
            lines.append(f"**{c.scenario_name}**")
            lines.append(f"- PF: {c.profit_factor:.3f} (baseline: {baseline.profit_factor:.3f}, Δ={c.profit_factor-baseline.profit_factor:+.3f})")
            lines.append(f"- Net PnL: {c.net_pnl_rub:+.0f} руб (baseline: {baseline.net_pnl_rub:+.0f})")
            lines.append(f"- Max DD: {c.max_drawdown_rub:.0f} руб (baseline: {baseline.max_drawdown_rub:.0f})")
            lines.append(f"- Trades: {c.trades} ({c.skip_rate_pct:.0f}% skip)")
            if fc.min_reward_points > 0:
                lines.append(f"- min_reward_points = {fc.min_reward_points}")
            if fc.min_rr > 0:
                lines.append(f"- min_rr = {fc.min_rr}")
            if fc.time_filter_name != "all_hours":
                lines.append(f"- time_filter = {fc.time_filter_name}")
            if fc.max_hold_bars is not None:
                lines.append(f"- max_hold_bars = {fc.max_hold_bars}")
            if fc.entry_confirmation != "baseline":
                lines.append(f"- entry_confirmation = {fc.entry_confirmation}")
            lines.append("")
        lines.append(
            "> Рекомендуется проверить эти параметры в paper trading перед любыми выводами о live trading."
        )
    else:
        lines.append("### Вариант B — Кандидаты слабые")
        lines.append("")
        lines.append(
            "Ни один сценарий не показал PF > baseline при trades ≥ 70% baseline. "
            "Рекомендуется продолжить сбор paper trading данных и/или расширить исторический тест."
        )
    lines.append("")

    # Rejected scenarios
    lines.append("## Scenarios rejected")
    lines.append("")
    rejected = [r for r in phase_a + phase_b if r.is_low_sample or r.profit_factor < baseline.profit_factor]
    if rejected:
        lines.append("| Сценарий | Причина |")
        lines.append("|---|---|")
        for r in rejected[:10]:
            reasons = []
            if r.is_low_sample:
                reasons.append(f"LOW_SAMPLE ({r.trades} trades)")
            if r.profit_factor < baseline.profit_factor:
                reasons.append(f"PF ниже baseline ({r.profit_factor:.3f} < {baseline.profit_factor:.3f})")
            lines.append(f"| {r.scenario_name} | {'; '.join(reasons)} |")
    else:
        lines.append("_Нет отклонённых сценариев._")
    lines.append("")

    # Warnings
    lines.append("## Warnings and limitations")
    lines.append("")
    lines.append(f"1. Выборка мала: {baseline.n_original_signals} {direction} сигналов за весь период.")
    lines.append(f"2. MIN_RR filter при take_r={params.take_r} не исключает ни одного сигнала (rr=take_r=const).")
    lines.append("3. Time filters выбраны на основе paper trading (~30 сделок) — риск переобучения.")
    lines.append("4. Backtest без slippage и market impact — реальное исполнение будет хуже.")
    lines.append("5. Исторические данные SiM6 Jan–Apr 2026 могут не представлять будущую волатильность.")
    lines.append("6. breakout_confirmation эквивалентен baseline (уже используется в движке).")
    lines.append("")

    # Recommendation
    lines.append("## Recommendation")
    lines.append("")
    if candidates:
        best = candidates[0]
        fc = best.filter_config
        filter_parts = []
        if fc.min_reward_points > 0:
            filter_parts.append(f"min_reward_points={fc.min_reward_points}")
        if fc.time_filter_name != "all_hours":
            filter_parts.append(f"time_filter={fc.time_filter_name}")
        if fc.max_hold_bars is not None:
            filter_parts.append(f"max_hold_bars={fc.max_hold_bars}")
        if fc.entry_confirmation != "baseline":
            filter_parts.append(f"entry_confirmation={fc.entry_confirmation}")
        filter_str = ", ".join(filter_parts) if filter_parts else "(нет изменений)"
        lines.append(
            f"**Scenario `{best.scenario_name}`** показал лучший PF ({best.profit_factor:.3f} vs {baseline.profit_factor:.3f}) "
            f"при разумном количестве сделок ({best.trades})."
        )
        lines.append("")
        lines.append(f"Предлагаемые параметры для MVP-2.1: {filter_str}")
        lines.append("")
        lines.append(
            "> Paper trading показывает положительную динамику, но выборка всё ещё мала. "
            "Бэктест подтвердил гипотезы на истории, но не является основанием для live trading."
        )
    else:
        lines.append("Диагностические фильтры не показали стабильного улучшения baseline на историческом срезе.")
        lines.append("Рекомендуется продолжить paper trading без изменений стратегии.")
    lines.append("")

    # Next MVP
    lines.append("## Next MVP")
    lines.append("")
    if candidates:
        lines.append(
            "**MVP-2.1 — Paper trading с фильтрами.** "
            "Добавить в конфиг paper trader один фильтр-кандидат из Phase A/B и собрать "
            "2–4 недели новых данных для сравнения с baseline. "
            "Параллельно расширить исторический датасет (SiM6 / другие инструменты)."
        )
    else:
        lines.append(
            "**Накопить ещё 2–4 недели paper trading данных**, затем повторить diagnostic filters "
            "на расширенной выборке. Рассмотреть загрузку дополнительных исторических данных."
        )
    lines.append("")

    return "\n".join(lines)


def save_results(
    baseline: ScenarioResult,
    phase_a: list[ScenarioResult],
    phase_b: list[ScenarioResult],
    trades_map: dict[str, pd.DataFrame],
    out_dir: str,
    reports_dir: str,
    ticker: str,
    direction: str,
    report_md: str,
) -> dict[str, str]:
    """Saves CSV and Markdown artifacts. Returns dict of {label: path}."""
    import os
    from pathlib import Path

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(reports_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = f"{ticker}_{direction}_{ts}"
    latest_tag = f"{ticker}_{direction}"

    all_results = [baseline] + phase_a + phase_b

    # Scenario summary CSV
    summary_rows = [r.to_dict() for r in all_results]
    summary_df = pd.DataFrame(summary_rows)
    summary_csv = str(Path(out_dir) / f"backtest_diagnostic_filters_{tag}.csv")
    summary_latest = str(Path(out_dir) / f"backtest_diagnostic_filters_{latest_tag}_latest.csv")
    summary_df.to_csv(summary_csv, index=False)
    summary_df.to_csv(summary_latest, index=False)

    # Combined trades CSV
    trade_dfs = []
    for r in all_results:
        t = trades_map.get(r.scenario_name, pd.DataFrame())
        if len(t) > 0:
            trade_dfs.append(t)
    if trade_dfs:
        all_trades_df = pd.concat(trade_dfs, ignore_index=True)
    else:
        all_trades_df = pd.DataFrame()
    trades_csv = str(Path(out_dir) / f"backtest_diagnostic_trades_{tag}.csv")
    trades_latest = str(Path(out_dir) / f"backtest_diagnostic_trades_{latest_tag}_latest.csv")
    all_trades_df.to_csv(trades_csv, index=False)
    all_trades_df.to_csv(trades_latest, index=False)

    # Markdown report
    report_md_path = str(Path(reports_dir) / f"backtest_diagnostic_filters_{tag}.md")
    report_latest = str(Path(reports_dir) / f"backtest_diagnostic_filters_{latest_tag}_latest.md")
    Path(report_md_path).write_text(report_md, encoding="utf-8")
    Path(report_latest).write_text(report_md, encoding="utf-8")

    return {
        "summary_csv": summary_csv,
        "summary_latest": summary_latest,
        "trades_csv": trades_csv,
        "trades_latest": trades_latest,
        "report_md": report_md_path,
        "report_latest": report_latest,
    }
