"""Grid orchestration for MVP-2.2 Exit/Time Filters v2 backtest experiments.

Generates Phase A (single-factor) and Phase B (combined) configs,
runs all scenarios, and builds the Markdown report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from src.backtest.exit_time_filters_v2 import (
    ConditionalMaxHoldConfig,
    FilterConfigV2,
    ScenarioResultV2,
    compute_winner_loser_analysis,
    run_scenario_v2,
)


# ── BacktestParamsV2 ──────────────────────────────────────────────────────────

@dataclass
class BacktestParamsV2:
    stop_buffer_points: float = 0.0
    take_r: float = 1.0
    slippage_points: float = 0.0
    point_value_rub: float = 10.0
    commission_per_trade: float = 0.025
    contracts: int = 1
    entry_horizon_bars: int = 3
    allow_overlap: bool = False
    min_trades_required: int = 30
    direction: str = "SELL"


# ── Config factory helpers ────────────────────────────────────────────────────

def make_baseline_config_v2(params: BacktestParamsV2) -> FilterConfigV2:
    return FilterConfigV2(
        scenario_name="baseline",
        direction=params.direction,
        time_filter_name="all_hours",
        exit_rule_name="no_max_hold",
        min_trades_required=params.min_trades_required,
    )


def make_phase_a_time_configs(cfg: dict, params: BacktestParamsV2) -> list[FilterConfigV2]:
    """Phase A1: time filter scenarios."""
    configs = []
    for tf in cfg.get("filters", {}).get("time_filters", []):
        name = tf.get("name", "")
        if name == "all_hours":
            continue
        configs.append(FilterConfigV2(
            scenario_name=f"time_{name}",
            direction=params.direction,
            time_filter_name=name,
            exit_rule_name="no_max_hold",
            exclude_hours_msk=tf.get("exclude_hours_msk", []) or [],
            min_trades_required=params.min_trades_required,
        ))
    return configs


def make_phase_a_maxhold_configs(cfg: dict, params: BacktestParamsV2) -> list[FilterConfigV2]:
    """Phase A2: fixed max_hold bar scenarios."""
    configs = []
    for mh in cfg.get("filters", {}).get("max_hold", []):
        name = mh.get("name", "")
        bars = mh.get("max_hold_bars")
        if name == "no_max_hold":
            continue  # baseline already covers this
        if bars is None:
            continue
        configs.append(FilterConfigV2(
            scenario_name=name,
            direction=params.direction,
            time_filter_name="all_hours",
            exit_rule_name=name,
            max_hold_bars=int(bars),
            min_trades_required=params.min_trades_required,
        ))
    return configs


def make_phase_a_conditional_configs(cfg: dict, params: BacktestParamsV2) -> list[FilterConfigV2]:
    """Phase A3: conditional max_hold scenarios."""
    configs = []
    for cm in cfg.get("filters", {}).get("conditional_max_hold", []):
        name = cm.get("name", "")
        if not cm.get("enabled", False):
            continue
        check_bar = int(cm.get("check_bar", 5))
        progress_pct = cm.get("min_progress_to_take_pct")
        max_pnl = cm.get("max_pnl_points")
        cond = ConditionalMaxHoldConfig(
            enabled=True,
            check_bar=check_bar,
            min_progress_to_take_pct=float(progress_pct) if progress_pct is not None else None,
            max_pnl_points=float(max_pnl) if max_pnl is not None else None,
        )
        configs.append(FilterConfigV2(
            scenario_name=name,
            direction=params.direction,
            time_filter_name="all_hours",
            exit_rule_name=name,
            conditional_max_hold=cond,
            min_trades_required=params.min_trades_required,
        ))
    return configs


def make_phase_a_confirmation_configs(cfg: dict, params: BacktestParamsV2) -> list[FilterConfigV2]:
    """Phase A4: entry confirmation proxy scenarios."""
    configs = []
    for ec in cfg.get("filters", {}).get("entry_confirmation", []):
        name = ec.get("name", "") if isinstance(ec, dict) else str(ec)
        if name == "baseline":
            continue
        # breakout_confirmation is equivalent to baseline — mark unsupported
        is_unsupported = name == "breakout_confirmation"
        unsupported_reason = (
            "Equivalent to baseline: engine already uses breakout entry" if is_unsupported else ""
        )
        # next_candle_direction has look-ahead risk: confirmation candle may be the entry candle
        look_ahead_warning = name in ("next_candle_direction", "skip_if_next_candle_against_signal")
        fc = FilterConfigV2(
            scenario_name=f"confirm_{name}",
            direction=params.direction,
            time_filter_name="all_hours",
            exit_rule_name="no_max_hold",
            entry_confirmation=name if not is_unsupported else "baseline",
            min_trades_required=params.min_trades_required,
            is_unsupported=is_unsupported,
            unsupported_reason=unsupported_reason,
        )
        if look_ahead_warning:
            # Still run it but add warning about potential look-ahead
            fc.unsupported_reason = (
                "LOOK_AHEAD_RISK: confirmation uses next candle direction — "
                "if that candle IS the breakout bar, decision is post-hoc"
            )
        configs.append(fc)
    return configs


def _tf_config_lookup(cfg: dict) -> dict[str, dict]:
    lookup = {"all_hours": {"name": "all_hours", "exclude_hours_msk": []}}
    for tf in cfg.get("filters", {}).get("time_filters", []):
        lookup[tf["name"]] = tf
    return lookup


def _cond_config_lookup(cfg: dict) -> dict[str, ConditionalMaxHoldConfig]:
    lookup: dict[str, ConditionalMaxHoldConfig] = {"none": ConditionalMaxHoldConfig(enabled=False)}
    for cm in cfg.get("filters", {}).get("conditional_max_hold", []):
        name = cm.get("name", "")
        if not cm.get("enabled", False):
            continue
        lookup[name] = ConditionalMaxHoldConfig(
            enabled=True,
            check_bar=int(cm.get("check_bar", 5)),
            min_progress_to_take_pct=(
                float(cm["min_progress_to_take_pct"]) if cm.get("min_progress_to_take_pct") is not None else None
            ),
            max_pnl_points=(
                float(cm["max_pnl_points"]) if cm.get("max_pnl_points") is not None else None
            ),
        )
    return lookup


def make_phase_b_configs_v2(cfg: dict, params: BacktestParamsV2) -> list[FilterConfigV2]:
    """Phase B: combined time_filter × exit_rule × confirmation grid."""
    pb = cfg.get("phase_b", {})
    tf_lookup = _tf_config_lookup(cfg)
    cond_lookup = _cond_config_lookup(cfg)

    tf_names = pb.get("time_filters", ["all_hours", "exclude_hour_12"])
    exit_names = pb.get("exit_rules", [
        "no_max_hold", "max_hold_10", "max_hold_15",
        "hold5_exit_if_progress_lt_25pct",
        "hold5_exit_if_pnl_le_0",
    ])
    confirm_names = pb.get("entry_confirmation", ["baseline"])

    # Build max_hold lookup from config
    mh_lookup: dict[str, Optional[int]] = {"no_max_hold": None}
    for mh in cfg.get("filters", {}).get("max_hold", []):
        mh_name = mh.get("name", "")
        bars = mh.get("max_hold_bars")
        mh_lookup[mh_name] = int(bars) if bars is not None else None

    configs = []
    for tf_name in tf_names:
        tf_spec = tf_lookup.get(tf_name, {})
        for exit_name in exit_names:
            for confirm_name in confirm_names:
                if confirm_name == "breakout_confirmation":
                    continue  # equivalent to baseline, skip in Phase B
                scen_name = f"B_{tf_name}_{exit_name}"
                if confirm_name != "baseline":
                    scen_name += f"_{confirm_name}"

                # Resolve exit rule
                if exit_name in mh_lookup:
                    max_hold = mh_lookup[exit_name]
                    cond = ConditionalMaxHoldConfig(enabled=False)
                elif exit_name in cond_lookup:
                    max_hold = None
                    cond = cond_lookup[exit_name]
                else:
                    continue

                configs.append(FilterConfigV2(
                    scenario_name=scen_name,
                    direction=params.direction,
                    time_filter_name=tf_name,
                    exit_rule_name=exit_name,
                    exclude_hours_msk=tf_spec.get("exclude_hours_msk", []) or [],
                    max_hold_bars=max_hold,
                    conditional_max_hold=cond,
                    entry_confirmation=confirm_name if confirm_name != "baseline" else "baseline",
                    min_trades_required=params.min_trades_required,
                ))
    return configs


# ── Run all ───────────────────────────────────────────────────────────────────

def _run(debug_df, fc, sid, params):
    return run_scenario_v2(
        debug_df=debug_df,
        filter_config=fc,
        scenario_id=sid,
        stop_buffer_points=params.stop_buffer_points,
        take_r=params.take_r,
        slippage_points=params.slippage_points,
        point_value_rub=params.point_value_rub,
        commission_per_trade=params.commission_per_trade,
        contracts=params.contracts,
        entry_horizon_bars=params.entry_horizon_bars,
        allow_overlap=params.allow_overlap,
    )


def run_all_scenarios_v2(
    debug_df: pd.DataFrame,
    params: BacktestParamsV2,
    cfg: dict,
) -> tuple[
    ScenarioResultV2,
    list[ScenarioResultV2],
    list[ScenarioResultV2],
    list[ScenarioResultV2],
    list[ScenarioResultV2],
    dict[str, pd.DataFrame],
]:
    """Runs baseline + Phase A (4 families) + Phase B. Returns results + trades_map."""
    sid = 0
    trades_map: dict[str, pd.DataFrame] = {}

    sid += 1
    baseline_result, baseline_trades = _run(debug_df, make_baseline_config_v2(params), sid, params)
    trades_map[baseline_result.scenario_name] = baseline_trades

    phase_a1: list[ScenarioResultV2] = []
    for fc in make_phase_a_time_configs(cfg, params):
        sid += 1
        r, t = _run(debug_df, fc, sid, params)
        phase_a1.append(r)
        trades_map[r.scenario_name] = t

    phase_a2: list[ScenarioResultV2] = []
    for fc in make_phase_a_maxhold_configs(cfg, params):
        sid += 1
        r, t = _run(debug_df, fc, sid, params)
        phase_a2.append(r)
        trades_map[r.scenario_name] = t

    phase_a3: list[ScenarioResultV2] = []
    for fc in make_phase_a_conditional_configs(cfg, params):
        sid += 1
        r, t = _run(debug_df, fc, sid, params)
        phase_a3.append(r)
        trades_map[r.scenario_name] = t

    phase_a4: list[ScenarioResultV2] = []
    for fc in make_phase_a_confirmation_configs(cfg, params):
        sid += 1
        r, t = _run(debug_df, fc, sid, params)
        phase_a4.append(r)
        trades_map[r.scenario_name] = t

    phase_b: list[ScenarioResultV2] = []
    for fc in make_phase_b_configs_v2(cfg, params):
        sid += 1
        r, t = _run(debug_df, fc, sid, params)
        phase_b.append(r)
        trades_map[r.scenario_name] = t

    # Enrich scenario results with cut winner / saved loser analysis vs baseline
    all_non_baseline = phase_a1 + phase_a2 + phase_a3 + phase_a4 + phase_b
    for r in all_non_baseline:
        scen_t = trades_map.get(r.scenario_name, pd.DataFrame())
        analysis = compute_winner_loser_analysis(baseline_trades, scen_t)
        r.large_winners_count = analysis["large_winners_count"]
        r.large_winners_cut_count = analysis["large_winners_cut_count"]
        r.saved_losers_count = analysis["saved_losers_count"]
        r.cut_winners_rub = analysis["cut_winners_rub"]
        r.saved_losers_rub = analysis["saved_losers_rub"]

    return baseline_result, phase_a1, phase_a2, phase_a3, phase_a4, phase_b, trades_map


# ── Rankings ──────────────────────────────────────────────────────────────────

def rank_scenarios_v2(
    baseline: ScenarioResultV2,
    all_results: list[ScenarioResultV2],
    top_n: int = 10,
) -> dict[str, list[ScenarioResultV2]]:
    eligible = [r for r in all_results if not r.is_low_sample]
    all_inc = [baseline] + all_results

    by_pnl = sorted(all_inc, key=lambda r: r.net_pnl_rub, reverse=True)[:top_n]
    by_pf = sorted(eligible + [baseline], key=lambda r: r.profit_factor, reverse=True)[:top_n]
    by_score = sorted(all_inc, key=lambda r: r.risk_adjusted_score, reverse=True)[:top_n]
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


# ── Markdown report ───────────────────────────────────────────────────────────

def _arrow(delta: float) -> str:
    if delta > 0.001:
        return "▲"
    if delta < -0.001:
        return "▼"
    return "="


def _row_v2(r: ScenarioResultV2, baseline: ScenarioResultV2) -> str:
    dpf = r.profit_factor - baseline.profit_factor
    dpnl = r.net_pnl_rub - baseline.net_pnl_rub
    ddd = r.max_drawdown_rub - baseline.max_drawdown_rub
    sample_flag = " ⚠️LOW" if r.is_low_sample else ""
    return (
        f"| {r.scenario_name} "
        f"| {r.trades} "
        f"| {r.skip_rate_pct:.0f}% "
        f"| {r.winrate_pct:.1f}% "
        f"| {r.net_pnl_rub:+.0f} "
        f"| {r.profit_factor:.3f} "
        f"| {r.max_drawdown_rub:.0f} "
        f"| {r.avg_bars_held:.1f} "
        f"| {r.take_count}/{r.stop_count}/{r.max_hold_exit_count+r.conditional_max_hold_exit_count} "
        f"| {r.profitable_periods_pct:.0f}% ({r.profitable_periods_count}/{r.periods_count}) "
        f"| PF {_arrow(dpf)} {dpf:+.3f}; PnL {_arrow(dpnl)} {dpnl:+.0f}; DD {_arrow(-ddd)} {ddd:+.0f}{sample_flag} |"
    )


_TABLE_HEADER_V2 = (
    "| Сценарий | Сд | Skip% | Win% | Net PnL | PF | Max DD | Avg bars | Take/Stop/Hold | Дн.стаб. | vs baseline |\n"
    "|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|"
)


def build_markdown_report_v2(
    baseline: ScenarioResultV2,
    phase_a1: list[ScenarioResultV2],
    phase_a2: list[ScenarioResultV2],
    phase_a3: list[ScenarioResultV2],
    phase_a4: list[ScenarioResultV2],
    phase_b: list[ScenarioResultV2],
    rankings: dict[str, list[ScenarioResultV2]],
    ticker: str,
    direction: str,
    period_from: str,
    period_to: str,
    params: BacktestParamsV2,
    cfg: dict,
) -> str:
    lines: list[str] = []
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append(f"# Backtest Exit/Time Filters v2 — {ticker} {direction}")
    lines.append("")
    lines.append(f"_Сгенерировано: {ts}_")
    lines.append("")

    # Цель
    lines.append("## Цель")
    lines.append("")
    lines.append("Historical backtest validation живых/paper гипотез:")
    lines.append("")
    lines.append("1. `exclude_hour_12` — исключить сигналы в 12:xx MSK")
    lines.append("2. Более мягкие `max_hold_bars`: 10 / 15 (вместо 5 в текущем maxhold5)")
    lines.append("3. Условный `max_hold` вместо фиксированного 5 (conditional exit на баре 5 при слабом прогрессе)")
    lines.append("4. Прокси для entry confirmation (ONE_BAR_STOP)")
    lines.append("5. Комбинированные сценарии без уничтожения больших победителей / BIG_RISK")
    lines.append("")
    lines.append("> **Важно:** Этот отчёт — только historical validation. Никаких изменений в live/paper сервисах.")
    lines.append("")

    # Источник данных
    lines.append("## Источник данных")
    lines.append("")
    lines.append(f"- Ticker: **{ticker}**")
    lines.append(f"- Direction: **{direction}**")
    lines.append(f"- Период данных: **{period_from} — {period_to}**")
    lines.append(f"- Файл сигналов: `{cfg.get('data', {}).get('signals_csv', 'out/debug_simple_all.csv')}`")
    lines.append(f"- SELL сигналов в периоде: **{baseline.n_original_signals}**")
    lines.append(f"- take_r: {params.take_r}, stop_buffer: {params.stop_buffer_points}, slippage: {params.slippage_points}")
    lines.append(f"- max_hold=None → hard cap {200} bars")
    lines.append("")

    # Baseline
    lines.append("## Baseline")
    lines.append("")
    lines.append("Без фильтров. Без max_hold (hard cap 200 bars).")
    lines.append("")
    lines.append("| Метрика | Значение |")
    lines.append("|---------|----------|")
    lines.append(f"| Сделок | {baseline.trades} |")
    lines.append(f"| WIN / LOSS | {baseline.wins} / {baseline.losses} |")
    lines.append(f"| Winrate | {baseline.winrate_pct:.1f}% |")
    lines.append(f"| Net PnL | {baseline.net_pnl_rub:+.0f} руб |")
    lines.append(f"| Profit Factor | {baseline.profit_factor:.3f} |")
    lines.append(f"| Expectancy | {baseline.expectancy_rub:+.2f} руб/сд |")
    lines.append(f"| Best / Worst | +{baseline.best_trade_rub:.0f} / {baseline.worst_trade_rub:.0f} руб |")
    lines.append(f"| Max Drawdown | {baseline.max_drawdown_rub:.0f} руб |")
    lines.append(f"| Avg bars held | {baseline.avg_bars_held:.1f} |")
    lines.append(f"| TAKE / STOP | {baseline.take_count} / {baseline.stop_count} |")
    lines.append(f"| Дней торговых | {baseline.periods_count} |")
    lines.append(f"| Прибыльных дней | {baseline.profitable_periods_count} ({baseline.profitable_periods_pct:.0f}%) |")
    lines.append(f"| Худший / лучший день | {baseline.worst_period_pnl:.0f} / +{baseline.best_period_pnl:.0f} руб |")
    lines.append(f"| Risk-adjusted score | {baseline.risk_adjusted_score:.0f} |")
    lines.append("")

    # Live/paper observations
    lines.append("## Live/paper наблюдения, проверяемые в этом MVP")
    lines.append("")
    lines.append("| Наблюдение | Бэктест-гипотеза |")
    lines.append("|---|---|")
    lines.append("| max_hold_bars=5 иногда срезает большие победители | Проверить max_hold=10/15 и conditional |")
    lines.append("| Час 12 MSK: 3 сделки, PF=0.00, −1340 руб в live/paper | Проверить exclude_hour_12 на истории |")
    lines.append("| ONE_BAR_STOP: 7 сделок, −1150 руб, PF=0.00 | Проверить entry confirmation proxies |")
    lines.append("| BIG_RISK: 10 сделок, +1690 руб, PF=1.71 — источник прибыли | Убедиться что сценарии его не уничтожают |")
    lines.append("")

    def _section(title: str, note: str, results: list[ScenarioResultV2]) -> None:
        lines.append(f"### {title}")
        lines.append("")
        if note:
            lines.append(f"> {note}")
            lines.append("")
        lines.append(_TABLE_HEADER_V2)
        lines.append(
            _row_v2(baseline, baseline).replace("| vs baseline |", "| **baseline** |")
        )
        for r in results:
            lines.append(_row_v2(r, baseline))
        lines.append("")

    # Phase A1 — Time filters
    lines.append("## Phase A — Однофакторный анализ")
    lines.append("")
    lines.append("Каждая группа фильтров проверяется отдельно против baseline.")
    lines.append("")

    _section(
        "A1. Time filters",
        "⚠️ Высокий риск переобучения: time filter выбран по ~30 live/paper сделкам. "
        "Backtest не доказывает, а проверяет гипотезу.",
        phase_a1,
    )

    _section(
        "A2. Фиксированный max_hold bars",
        "Сравнение max_hold_5/10/15 vs baseline (no max_hold). "
        "Колонка Take/Stop/Hold: take | stop | max_hold exits.",
        phase_a2,
    )

    _section(
        "A3. Conditional max_hold",
        "Выход на баре 5 только если прогресс к тейку < порога ИЛИ PnL ≤ порога. "
        "Сильные сделки (в движении к тейку) остаются открытыми.",
        phase_a3,
    )

    # Confirmation analysis
    lines.append("### A4. Entry confirmation proxies")
    lines.append("")
    lines.append("> ⚠️ Риск look-ahead: next_candle_direction проверяет свечу T+1, "
                 "которая может быть той же свечой, где произошёл breakout entry. "
                 "breakout_confirmation эквивалентен baseline (уже используется в движке).")
    lines.append("")
    lines.append(_TABLE_HEADER_V2)
    lines.append(
        _row_v2(baseline, baseline).replace("| vs baseline |", "| **baseline** |")
    )
    for r in phase_a4:
        row = _row_v2(r, baseline)
        if r.filter_config.unsupported_reason:
            row = row.rstrip(" |") + f" ⚠️ |"
        lines.append(row)
    lines.append("")
    for r in phase_a4:
        if r.filter_config.unsupported_reason:
            lines.append(f"- **{r.scenario_name}**: {r.filter_config.unsupported_reason}")
    lines.append("")

    # Phase B
    lines.append("## Phase B — Комбинированные сценарии")
    lines.append("")
    lines.append("Сетка: time_filter × exit_rule × entry_confirmation.")
    lines.append("")
    if phase_b:
        lines.append(_TABLE_HEADER_V2)
        for r in phase_b:
            lines.append(_row_v2(r, baseline))
        lines.append("")
    else:
        lines.append("_Phase B не содержит сценариев._")
        lines.append("")

    # Rankings
    def _rank_table(title: str, results: list[ScenarioResultV2]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if not results:
            lines.append("_Нет подходящих сценариев._")
            lines.append("")
            return
        lines.append(_TABLE_HEADER_V2)
        for r in results:
            lines.append(_row_v2(r, baseline))
        lines.append("")

    _rank_table("Top scenarios by Net PnL", rankings.get("by_net_pnl", []))
    _rank_table("Top scenarios by Profit Factor", rankings.get("by_profit_factor", []))
    _rank_table("Top scenarios by risk-adjusted score", rankings.get("by_risk_adjusted", []))
    _rank_table("Robust scenarios (PF≥baseline, trades≥70%, days≥baseline)", rankings.get("robust", []))

    # Large winners / cut winners
    lines.append("## Large winners / cut winners analysis")
    lines.append("")
    lines.append("Large winner = baseline net_pnl ≥ 500 руб. Cut winner = baseline ≥ 300, scenario < baseline.")
    lines.append("")
    all_non_base = phase_a1 + phase_a2 + phase_a3 + phase_a4 + phase_b
    lw_rows = [r for r in all_non_base if not r.is_low_sample]
    if lw_rows:
        lines.append("| Сценарий | Больших победителей (baseline) | Срезано | Срезано % | Потери от срезания |")
        lines.append("|---|---:|---:|---:|---:|")
        for r in lw_rows:
            cut_pct = (
                f"{100.0 * r.large_winners_cut_count / r.large_winners_count:.0f}%"
                if r.large_winners_count > 0 else "—"
            )
            lines.append(
                f"| {r.scenario_name} "
                f"| {r.large_winners_count} "
                f"| {r.large_winners_cut_count} "
                f"| {cut_pct} "
                f"| {r.cut_winners_rub:.0f} руб |"
            )
    else:
        lines.append("_Нет подходящих сценариев._")
    lines.append("")

    # Saved losers
    lines.append("## Saved losers analysis")
    lines.append("")
    lines.append("Saved loser = baseline ≤ −300 руб, scenario лучше baseline.")
    lines.append("")
    if lw_rows:
        lines.append("| Сценарий | Сохранено лузеров | Выигрыш от сохранения |")
        lines.append("|---|---:|---:|")
        for r in lw_rows:
            lines.append(
                f"| {r.scenario_name} "
                f"| {r.saved_losers_count} "
                f"| +{r.saved_losers_rub:.0f} руб |"
            )
    lines.append("")

    # Period stability
    lines.append("## Period stability — топ сценарии")
    lines.append("")
    lines.append("| Сценарий | Дней | Прибыльных | % | Лучший | Худший | Avg/день |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    top6 = ([baseline] + rankings.get("by_risk_adjusted", []))[:7]
    seen_ids: set[int] = set()
    for r in top6:
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

    # Comparison with live A/B
    lines.append("## Сравнение с текущим live/paper A/B экспериментом")
    lines.append("")
    lines.append("| Параметр | baseline (no hold) | maxhold5 (live) | Backtest max_hold_5 |")
    lines.append("|---|---|---|---|")
    mh5_r = next((r for r in phase_a2 if "max_hold_5" in r.scenario_name), None)
    mh5_pf = f"{mh5_r.profit_factor:.3f}" if mh5_r else "—"
    mh5_net = f"{mh5_r.net_pnl_rub:+.0f}" if mh5_r else "—"
    mh5_dd = f"{mh5_r.max_drawdown_rub:.0f}" if mh5_r else "—"
    mh5_he = f"{mh5_r.max_hold_exit_count}" if mh5_r else "—"
    lines.append(f"| Net PnL | {baseline.net_pnl_rub:+.0f} | N/A (live) | {mh5_net} |")
    lines.append(f"| Profit Factor | {baseline.profit_factor:.3f} | 1.61 (live) | {mh5_pf} |")
    lines.append(f"| Max Drawdown | {baseline.max_drawdown_rub:.0f} | N/A | {mh5_dd} |")
    lines.append(f"| MAX_HOLD_EXIT | 0 | 9 (live) | {mh5_he} |")
    lines.append("")

    # Candidate recommendation
    lines.append("## Candidate for next paper experiment")
    lines.append("")
    all_scored = [r for r in all_non_base if not r.is_low_sample and not r.filter_config.is_unsupported]
    strong_candidates = [
        r for r in all_scored
        if (r.profit_factor > baseline.profit_factor
            and r.trades >= int(baseline.trades * 0.7)
            and r.profitable_periods_pct >= baseline.profitable_periods_pct
            and r.large_winners_cut_count <= r.large_winners_count * 0.5)
    ]
    strong_candidates.sort(key=lambda r: (r.profit_factor, r.net_pnl_rub), reverse=True)

    if strong_candidates:
        lines.append("### Сильные кандидаты (PF > baseline, trades ≥ 70%, stable, не рубят победителей)")
        lines.append("")
        for c in strong_candidates[:3]:
            fc = c.filter_config
            lines.append(f"**`{c.scenario_name}`**")
            lines.append(f"- PF: {c.profit_factor:.3f} (Δ {c.profit_factor-baseline.profit_factor:+.3f})")
            lines.append(f"- Net PnL: {c.net_pnl_rub:+.0f} руб (Δ {c.net_pnl_rub-baseline.net_pnl_rub:+.0f})")
            lines.append(f"- Max DD: {c.max_drawdown_rub:.0f} руб (Δ {c.max_drawdown_rub-baseline.max_drawdown_rub:+.0f})")
            lines.append(f"- Trades: {c.trades} ({c.skip_rate_pct:.0f}% skip)")
            lines.append(f"- Large winners срезано: {c.large_winners_cut_count}/{c.large_winners_count}")
            lines.append(f"- Saved losers: {c.saved_losers_count} (+{c.saved_losers_rub:.0f} руб)")
            if fc.time_filter_name != "all_hours":
                lines.append(f"- time_filter: `{fc.time_filter_name}`")
            if fc.max_hold_bars is not None:
                lines.append(f"- max_hold_bars: {fc.max_hold_bars}")
            if fc.conditional_max_hold.enabled:
                lines.append(f"- conditional_max_hold: {fc.conditional_max_hold.name}")
            lines.append("")
    else:
        lines.append("### Кандидатов нет")
        lines.append("")
        lines.append(
            "Ни один сценарий не выполнил все критерии strong candidate "
            "(PF > baseline, trades ≥ 70%, period stability, ≤50% large winners cut)."
        )
        lines.append("")
        # Show weak candidates
        weak = [r for r in all_scored if r.profit_factor > baseline.profit_factor and r.trades >= 20]
        weak.sort(key=lambda r: r.profit_factor, reverse=True)
        if weak:
            lines.append("Weak candidates (PF улучшается, но есть оговорки):")
            lines.append("")
            for c in weak[:3]:
                lines.append(f"- **`{c.scenario_name}`**: PF={c.profit_factor:.3f}, "
                              f"net={c.net_pnl_rub:+.0f}, "
                              f"срезано победителей {c.large_winners_cut_count}/{c.large_winners_count}")
            lines.append("")
    lines.append(
        "> Любой кандидат — это **только кандидат для следующего paper experiment**, "
        "а не основание для изменения стратегии."
    )
    lines.append("")

    # Rejected
    lines.append("## Rejected scenarios")
    lines.append("")
    rejected = [r for r in all_non_base if r.is_low_sample or r.profit_factor < baseline.profit_factor]
    if rejected:
        lines.append("| Сценарий | Причина |")
        lines.append("|---|---|")
        for r in rejected[:15]:
            reasons = []
            if r.is_low_sample:
                reasons.append(f"LOW_SAMPLE ({r.trades} сделок)")
            if r.profit_factor < baseline.profit_factor:
                reasons.append(f"PF {r.profit_factor:.3f} < baseline {baseline.profit_factor:.3f}")
            lines.append(f"| {r.scenario_name} | {'; '.join(reasons)} |")
    else:
        lines.append("_Нет отклонённых сценариев._")
    lines.append("")

    # Answers to spec questions
    lines.append("## Ответы на вопросы MVP-2.2")
    lines.append("")

    def _q(n, q, a):
        lines.append(f"**{n}. {q}**")
        lines.append(f"→ {a}")
        lines.append("")

    h12_r = next((r for r in phase_a1 if "hour_12" in r.scenario_name and "13" not in r.scenario_name), None)
    h12_ans = (
        f"PF {h12_r.profit_factor:.3f} vs {baseline.profit_factor:.3f} "
        f"(Δ{h12_r.profit_factor-baseline.profit_factor:+.3f}), "
        f"net {h12_r.net_pnl_rub:+.0f} руб, {h12_r.trades} сделок"
        if h12_r else "Нет данных"
    )
    _q(1, "Улучшает ли exclude_hour_12 исторический результат?", h12_ans)

    h12_stab = (
        f"Дней прибыльных: {h12_r.profitable_periods_pct:.0f}% vs baseline {baseline.profitable_periods_pct:.0f}%"
        if h12_r else "—"
    )
    _q(2, "Устойчив ли exclude_hour_12 по месяцам/неделям?", h12_stab)

    h12_skip = (
        f"Skip rate: {h12_r.skip_rate_pct:.0f}%, {h12_r.n_filtered_signals} сигналов отфильтровано"
        if h12_r else "—"
    )
    _q(3, "Не похоже ли exclude_hour_12 на переобучение?", h12_skip)

    mh5_ans = (
        f"Backtest max_hold_5: PF={mh5_r.profit_factor:.3f}, net={mh5_r.net_pnl_rub:+.0f}, "
        f"MAX_HOLD exits={mh5_r.max_hold_exit_count}, "
        f"срезано победителей {mh5_r.large_winners_cut_count}/{mh5_r.large_winners_count}"
        if mh5_r else "—"
    )
    _q(4, "Слишком ли агрессивен max_hold=5 исторически?", mh5_ans)

    mh10_r = next((r for r in phase_a2 if "max_hold_10" in r.scenario_name), None)
    mh15_r = next((r for r in phase_a2 if "max_hold_15" in r.scenario_name), None)
    mh_comp = (
        f"max_hold_10: PF={mh10_r.profit_factor:.3f}, net={mh10_r.net_pnl_rub:+.0f}; "
        f"max_hold_15: PF={mh15_r.profit_factor:.3f}, net={mh15_r.net_pnl_rub:+.0f}"
        if mh10_r and mh15_r else "—"
    )
    _q(5, "Лучше ли max_hold=10 или 15 чем max_hold=5?", mh_comp)

    best_cond = max(phase_a3, key=lambda r: r.profit_factor) if phase_a3 else None
    cond_ans = (
        f"Лучший conditional: {best_cond.scenario_name} "
        f"PF={best_cond.profit_factor:.3f}, "
        f"conditional exits={best_cond.conditional_max_hold_exit_count}, "
        f"срезано победителей {best_cond.large_winners_cut_count}/{best_cond.large_winners_count}"
        if best_cond else "—"
    )
    _q(6, "Preserves ли conditional max_hold большие победители лучше fixed=5?", cond_ans)

    _q(7, "Какое conditional правило лучший trade-off?", cond_ans)

    conf_r = next((r for r in phase_a4 if "next_candle" in r.scenario_name), None)
    conf_ans = (
        f"next_candle_direction: PF={conf_r.profit_factor:.3f} vs {baseline.profit_factor:.3f}, "
        f"skip={conf_r.skip_rate_pct:.0f}% (⚠️ look-ahead risk)"
        if conf_r else "—"
    )
    _q(8, "Снижает ли entry confirmation ONE_BAR_STOP без уничтожения победителей?", conf_ans)

    _q(9, "Уничтожает ли confirmation слишком много победителей?",
       f"Срезано: {conf_r.large_winners_cut_count}/{conf_r.large_winners_count}" if conf_r else "—")

    best_dd = min(all_non_base, key=lambda r: r.max_drawdown_rub) if all_non_base else None
    _q(10, "Какой сценарий снижает worst trade / maxDD?",
       f"{best_dd.scenario_name}: DD={best_dd.max_drawdown_rub:.0f} vs baseline {baseline.max_drawdown_rub:.0f}" if best_dd else "—")

    best_pf_eligible = rankings.get("by_profit_factor", [])
    _q(11, "Какой сценарий лучший PF при достаточном числе сделок?",
       f"{best_pf_eligible[0].scenario_name}: PF={best_pf_eligible[0].profit_factor:.3f}, trades={best_pf_eligible[0].trades}" if best_pf_eligible else "—")

    big_risk_ok = [r for r in all_non_base if r.large_winners_cut_count == 0 and not r.is_low_sample]
    _q(12, "Какой сценарий preserves BIG_RISK winners?",
       f"{len(big_risk_ok)} сценариев не срезают ни одного large winner")

    _q(13, "Какой сценарий тестировать следующим в paper?",
       f"{strong_candidates[0].scenario_name}" if strong_candidates else "Нет сильного кандидата — продолжать baseline")

    _q(14, "Что делать с текущим maxhold5?",
       "Смотреть на основе: исторически max_hold_5 " +
       (f"{'улучшает' if mh5_r and mh5_r.profit_factor > baseline.profit_factor else 'не улучшает'}" if mh5_r else "неизвестно") +
       " PF. Live/paper данных пока недостаточно для выводов.")

    # Warnings
    lines.append("## Warnings and limitations")
    lines.append("")
    lines.append(f"1. Малая выборка: {baseline.n_original_signals} {direction} сигналов за {period_from}–{period_to}.")
    lines.append("2. next_candle_direction имеет риск look-ahead (если breakout = подтверждающая свеча).")
    lines.append("3. Time filters выбраны по ~30 live/paper сделкам — высокий риск переобучения.")
    lines.append("4. Backtest без slippage и market impact — реальное исполнение будет хуже.")
    lines.append("5. breakout_confirmation эквивалентен baseline — результаты идентичны.")
    lines.append("6. Conditional max_hold симулирован с полным знанием bar 5 close — нет look-ahead.")
    lines.append("7. Данные только Jan–Apr 2026 (локальный CSV). Расширенный тест на май — на сервере.")
    lines.append("")

    # Recommendation
    lines.append("## Рекомендация")
    lines.append("")
    if strong_candidates:
        best = strong_candidates[0]
        fc = best.filter_config
        lines.append(f"**Candidate for next paper experiment: `{best.scenario_name}`**")
        lines.append("")
        lines.append(f"- PF: {best.profit_factor:.3f} (vs baseline {baseline.profit_factor:.3f})")
        lines.append(f"- Net PnL: {best.net_pnl_rub:+.0f} руб")
        lines.append(f"- Max DD: {best.max_drawdown_rub:.0f} руб")
        lines.append(f"- Trades: {best.trades} ({100.0*best.trades/baseline.trades:.0f}% от baseline)")
        lines.append(f"- Large winners срезано: {best.large_winners_cut_count}/{best.large_winners_count}")
        if fc.time_filter_name != "all_hours":
            lines.append(f"- time_filter: `{fc.time_filter_name}`")
        if fc.max_hold_bars is not None:
            lines.append(f"- max_hold_bars: {fc.max_hold_bars}")
        if fc.conditional_max_hold.enabled:
            lines.append(f"- conditional_max_hold: {fc.conditional_max_hold.name}")
    else:
        lines.append("**Нет сильного кандидата для следующего paper experiment.**")
        lines.append("")
        lines.append("Рекомендуется:")
        lines.append("- Продолжить текущий A/B эксперимент (baseline vs maxhold5)")
        lines.append("- Накопить ≥ 4 недели данных maxhold5 (нужно ~50+ сделок)")
        lines.append("- Повторить MVP-2.2 анализ на расширенных данных (на сервере)")
    lines.append("")
    lines.append(
        "> ⚠️ Текущие paper сервисы (`hammertrade-paper` и `hammertrade-paper-maxhold5`) "
        "не изменены этим MVP. Любые изменения — только после подтверждения в paper trading."
    )
    lines.append("")

    return "\n".join(lines)


# ── Save results ──────────────────────────────────────────────────────────────

def save_results_v2(
    baseline: ScenarioResultV2,
    phase_a1: list[ScenarioResultV2],
    phase_a2: list[ScenarioResultV2],
    phase_a3: list[ScenarioResultV2],
    phase_a4: list[ScenarioResultV2],
    phase_b: list[ScenarioResultV2],
    trades_map: dict[str, pd.DataFrame],
    out_dir: str,
    reports_dir: str,
    ticker: str,
    direction: str,
    report_md: str,
) -> dict[str, str]:
    import os
    from pathlib import Path

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(reports_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = f"{ticker}_{direction}_{ts}"
    latest_tag = f"{ticker}_{direction}"

    all_results = [baseline] + phase_a1 + phase_a2 + phase_a3 + phase_a4 + phase_b
    summary_rows = [r.to_dict() for r in all_results]
    summary_df = pd.DataFrame(summary_rows)

    prefix = "backtest_exit_time_filters_v2"
    summary_csv = str(Path(out_dir) / f"{prefix}_{tag}.csv")
    summary_latest = str(Path(out_dir) / f"{prefix}_{latest_tag}_latest.csv")
    summary_df.to_csv(summary_csv, index=False)
    summary_df.to_csv(summary_latest, index=False)

    trade_dfs = []
    for r in all_results:
        t = trades_map.get(r.scenario_name, pd.DataFrame())
        if len(t) > 0:
            trade_dfs.append(t)
    all_trades_df = pd.concat(trade_dfs, ignore_index=True) if trade_dfs else pd.DataFrame()

    trades_csv = str(Path(out_dir) / f"{prefix}_trades_{tag}.csv")
    trades_latest = str(Path(out_dir) / f"{prefix}_trades_{latest_tag}_latest.csv")
    all_trades_df.to_csv(trades_csv, index=False)
    all_trades_df.to_csv(trades_latest, index=False)

    report_path = str(Path(reports_dir) / f"{prefix}_{tag}.md")
    report_latest = str(Path(reports_dir) / f"{prefix}_{latest_tag}_latest.md")
    Path(report_path).write_text(report_md, encoding="utf-8")
    Path(report_latest).write_text(report_md, encoding="utf-8")

    return {
        "summary_csv": summary_csv,
        "summary_latest": summary_latest,
        "trades_csv": trades_csv,
        "trades_latest": trades_latest,
        "report_md": report_path,
        "report_latest": report_latest,
    }
