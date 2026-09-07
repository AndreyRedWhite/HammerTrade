#!/usr/bin/env python
"""MVP-R1a: ORB Walk-Forward + May OOS + Slippage Audit.

Usage:
    venv/bin/python scripts/research_orb_walkforward.py \
        --config configs/research/opening_range_breakout_sim6_walkforward.yaml
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, time

import pandas as pd
import yaml

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategies.opening_range_breakout.backtest import run_orb_backtest
from src.strategies.opening_range_breakout.strategy import _to_msk
from src.research.metrics import compute_metrics
from src.research.walkforward import walkforward_table
from src.research.slippage import slippage_sensitivity, slippage_destroyed_edge
from src.research.robustness import (
    top_trades_contribution,
    best_day_contribution,
    worst_day_contribution,
    net_without_best_day,
    concentration_flag,
)
from src.research.regime import compute_regime_context


# ---------------------------------------------------------------------------
# Data quality check
# ---------------------------------------------------------------------------

def data_quality_report(csv_path: str, label: str) -> dict:
    """Run lightweight data quality checks on a candles CSV.

    Returns a dict with quality summary fields.
    """
    df = pd.read_csv(csv_path)
    row_count = len(df)

    if row_count == 0:
        return {"label": label, "csv_path": csv_path, "row_count": 0, "issues": ["EMPTY FILE"]}

    # Parse timestamps
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["msk_dt"] = df["timestamp"].apply(_to_msk)
    df["msk_date"] = df["msk_dt"].dt.date

    first_ts = str(df["timestamp"].iloc[0])
    last_ts = str(df["timestamp"].iloc[-1])

    trading_days = df["msk_date"].nunique()

    # Duplicate timestamps
    dup_count = int(df["timestamp"].duplicated().sum())

    # Zero-range candles (high == low)
    zero_range = int((df["high"] == df["low"]).sum())
    zero_range_pct = round(zero_range / row_count * 100, 2)

    # Missing days check (weekdays with no data between first and last)
    all_dates = pd.bdate_range(
        start=df["msk_date"].min(), end=df["msk_date"].max(), freq="B"
    )
    observed_dates = set(str(d.date()) for d in df["msk_dt"])
    expected_dates = set(str(d.date()) for d in all_dates)
    # Russia has extra public holidays — just flag large gaps
    missing_days = sorted(expected_dates - observed_dates)

    issues = []
    if dup_count > 0:
        issues.append(f"DUPLICATE_TIMESTAMPS: {dup_count}")
    if zero_range_pct > 5:
        issues.append(f"HIGH_ZERO_RANGE_CANDLES: {zero_range_pct}%")
    if len(missing_days) > 20:
        issues.append(f"MANY_MISSING_BDAYS: {len(missing_days)} (incl. RU holidays)")

    return {
        "label": label,
        "csv_path": csv_path,
        "row_count": row_count,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "trading_days": trading_days,
        "duplicate_timestamps": dup_count,
        "zero_range_candles": zero_range,
        "zero_range_pct": zero_range_pct,
        "missing_bdays_raw": len(missing_days),
        "issues": issues,
    }


def build_data_quality_markdown(train_dq: dict, oos_dq: dict) -> str:
    lines = []
    lines.append("# Data Quality Report — SiM6 1m 2026\n")
    lines.append(f"Сгенерировано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    for dq in [train_dq, oos_dq]:
        lines.append(f"## {dq['label']}\n")
        lines.append(f"- Файл: `{dq['csv_path']}`")
        lines.append(f"- Строк: {dq['row_count']}")
        lines.append(f"- Первый timestamp: {dq['first_timestamp']}")
        lines.append(f"- Последний timestamp: {dq['last_timestamp']}")
        lines.append(f"- Торговых дней: {dq['trading_days']}")
        lines.append(f"- Дублей timestamps: {dq['duplicate_timestamps']}")
        lines.append(f"- Свечей с нулевым диапазоном: {dq['zero_range_candles']} ({dq['zero_range_pct']}%)")
        lines.append(f"- Отсутствующих рабочих дней (raw, вкл. праздники РФ): {dq['missing_bdays_raw']}")
        if dq['issues']:
            lines.append(f"- **Проблемы**: {'; '.join(dq['issues'])}")
        else:
            lines.append("- Проблем не обнаружено")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Regime breakdown helper
# ---------------------------------------------------------------------------

def regime_breakdown(trades: list[dict], candles: pd.DataFrame) -> list[dict]:
    """Compute trade metrics broken down by day regime."""
    if not trades:
        return []

    regime_ctx = compute_regime_context(candles)
    regime_map = {}
    if not regime_ctx.empty:
        for _, row in regime_ctx.iterrows():
            regime_map[str(row["date"])] = row["regime"]

    # Attach regime to trades
    for t in trades:
        date_str = str(t.get("date", ""))[:10]
        t["_regime_resolved"] = regime_map.get(date_str, "NORMAL")

    rows = []
    by_regime: dict[str, list] = defaultdict(list)
    for t in trades:
        by_regime[t["_regime_resolved"]].append(t)

    for regime, r_trades in sorted(by_regime.items()):
        m = compute_metrics(r_trades)
        rows.append({
            "regime": regime,
            **m,
        })
    return rows


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_walkforward_report(
    config: dict,
    train_dq: dict,
    oos_dq: dict,
    train_results: list[dict],
    oos_results: list[dict],
    full_results: list[dict],
    best_scenario: dict,
    best_train_trades: list[dict],
    best_oos_trades: list[dict],
    wf_month_train: list[dict],
    wf_week_train: list[dict],
    wf_month_oos: list[dict],
    slip_train: list[dict],
    slip_oos: list[dict],
    regime_train: list[dict],
    regime_oos: list[dict],
    rob_train: dict,
    rob_oos: dict,
    candidate_decision: str,
    candidate_reason: str,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ticker = config.get("experiment", {}).get("ticker", "SiM6")

    lines = []
    lines.append(f"# ORB Walk-Forward Research Report — {ticker} 1m")
    lines.append(f"\nСгенерировано: {now}\n")

    # --- Краткий вывод ---
    lines.append("## Краткий вывод\n")
    lines.append(f"**Решение: {candidate_decision}**\n")
    lines.append(f"*Обоснование:* {candidate_reason}\n")
    best_name = best_scenario.get("scenario_name", best_scenario.get("scenario", "N/A"))
    lines.append(f"Лучший сценарий (по train PF): **{best_name}**\n")
    lines.append(
        "**Риск оверфита**: Walk-forward по месяцам и slip-тест показывают степень "
        "устойчивости стратегии за пределами in-sample периода.\n"
    )

    # --- Источники данных и data quality ---
    lines.append("## Источники данных и Data Quality\n")
    for dq in [train_dq, oos_dq]:
        lines.append(f"### {dq['label']}")
        lines.append(f"- Файл: `{dq['csv_path']}`")
        lines.append(f"- Строк: {dq['row_count']}, торговых дней: {dq['trading_days']}")
        lines.append(f"- Период: {dq['first_timestamp'][:10]} → {dq['last_timestamp'][:10]}")
        lines.append(f"- Дублей: {dq['duplicate_timestamps']}, нулевые свечи: {dq['zero_range_candles']} ({dq['zero_range_pct']}%)")
        if dq["issues"]:
            lines.append(f"- **Проблемы**: {'; '.join(dq['issues'])}")
        else:
            lines.append("- Проблем не обнаружено")
        lines.append("")

    # --- Сценарии ---
    lines.append("## Сценарии\n")
    scenarios = config.get("scenarios", [])
    lines.append("| Сценарий | OR Start | OR End | Direction | Take R |")
    lines.append("|----------|----------|--------|-----------|--------|")
    for s in scenarios:
        lines.append(
            f"| {s['name']} | {s['or_start_msk']} | {s['or_end_msk']} "
            f"| {s['direction']} | {s['take_r']} |"
        )
    lines.append("")

    def _scenario_table(results: list[dict], title: str) -> list[str]:
        out = [f"## {title}\n"]
        out.append("| Сценарий | OR окно | Dir | TakeR | Сделок | WR | Net PnL | PF | MaxDD |")
        out.append("|----------|---------|-----|-------|--------|-----|---------|-----|-------|")
        for r in sorted(results, key=lambda x: x.get("profit_factor", 0), reverse=True):
            name = r.get("scenario_name", r.get("scenario", ""))
            out.append(
                f"| {name} | {r.get('or_window','')} | {r.get('direction','')} "
                f"| {r.get('take_r','')} | {r.get('trades',0)} "
                f"| {r.get('winrate',0):.1%} | {r.get('net_pnl',0):.2f} "
                f"| {r.get('profit_factor',0):.3f} | {r.get('max_drawdown',0):.2f} |"
            )
        out.append("")
        return out

    lines.extend(_scenario_table(train_results, "Train Jan–Apr 2026"))
    lines.extend(_scenario_table(oos_results, "May OOS 2026"))
    lines.extend(_scenario_table(full_results, "Full Jan–May 2026"))

    # --- Walk-forward по месяцам ---
    lines.append("## Walk-Forward по месяцам (лучший сценарий, Train)\n")
    if wf_month_train:
        lines.append("| Месяц | Торг.дней | Сделок | WR | Net PnL | PF | MaxDD | Приб.дней |")
        lines.append("|-------|-----------|--------|-----|---------|-----|-------|-----------|")
        for row in wf_month_train:
            pf = row.get("profit_factor", 0)
            pf_str = f"{pf:.3f}" if pf < 9999 else "∞"
            lines.append(
                f"| {row['period_label']} | {row['trading_days']} "
                f"| {row['trades']} | {row.get('winrate',0):.1%} "
                f"| {row.get('net_pnl',0):.2f} | {pf_str} "
                f"| {row.get('max_drawdown',0):.2f} | {row['profitable_days']} |"
            )
        lines.append("")
    else:
        lines.append("_Нет данных_\n")

    lines.append("## Walk-Forward по месяцам (лучший сценарий, OOS May)\n")
    if wf_month_oos:
        lines.append("| Месяц | Торг.дней | Сделок | WR | Net PnL | PF | MaxDD | Приб.дней |")
        lines.append("|-------|-----------|--------|-----|---------|-----|-------|-----------|")
        for row in wf_month_oos:
            pf = row.get("profit_factor", 0)
            pf_str = f"{pf:.3f}" if pf < 9999 else "∞"
            lines.append(
                f"| {row['period_label']} | {row['trading_days']} "
                f"| {row['trades']} | {row.get('winrate',0):.1%} "
                f"| {row.get('net_pnl',0):.2f} | {pf_str} "
                f"| {row.get('max_drawdown',0):.2f} | {row['profitable_days']} |"
            )
        lines.append("")
    else:
        lines.append("_Нет данных_\n")

    lines.append("## Walk-Forward по неделям (лучший сценарий, Train)\n")
    if wf_week_train:
        lines.append("| Неделя | Торг.дней | Сделок | WR | Net PnL | PF |")
        lines.append("|--------|-----------|--------|-----|---------|-----|")
        for row in wf_week_train:
            pf = row.get("profit_factor", 0)
            pf_str = f"{pf:.3f}" if pf < 9999 else "∞"
            lines.append(
                f"| {row['period_label']} | {row['trading_days']} "
                f"| {row['trades']} | {row.get('winrate',0):.1%} "
                f"| {row.get('net_pnl',0):.2f} | {pf_str} |"
            )
        lines.append("")
    else:
        lines.append("_Нет данных_\n")

    # --- Slippage sensitivity ---
    def _slip_table(slip_rows: list[dict], title: str) -> list[str]:
        out = [f"## Slippage Sensitivity — {title}\n"]
        out.append("| Slip pts | Сделок | WR | Net PnL | PF | Edge уничтожен? |")
        out.append("|----------|--------|-----|---------|-----|----------------|")
        for row in slip_rows:
            destroyed = "ДА" if row.get("destroyed_edge") else "нет"
            out.append(
                f"| {row['slip_pts']} | {row.get('trades',0)} "
                f"| {row.get('winrate',0):.1%} "
                f"| {row.get('net_pnl',0):.2f} "
                f"| {row.get('profit_factor',0):.3f} | {destroyed} |"
            )
        out.append("")
        return out

    lines.extend(_slip_table(slip_train, "Train"))
    lines.extend(_slip_table(slip_oos, "OOS May"))

    # --- Regime breakdown ---
    def _regime_table(regime_rows: list[dict], title: str) -> list[str]:
        out = [f"## Режимы — {title}\n"]
        if not regime_rows:
            out.append("_Нет данных_\n")
            return out
        out.append("| Режим | Сделок | WR | Net PnL | PF |")
        out.append("|-------|--------|-----|---------|-----|")
        for row in regime_rows:
            pf = row.get("profit_factor", 0)
            pf_str = f"{pf:.3f}" if pf < 9999 else "∞"
            out.append(
                f"| {row['regime']} | {row.get('trades',0)} "
                f"| {row.get('winrate',0):.1%} "
                f"| {row.get('net_pnl',0):.2f} | {pf_str} |"
            )
        out.append("")
        return out

    lines.extend(_regime_table(regime_train, "Train"))
    lines.extend(_regime_table(regime_oos, "OOS May"))

    # --- Concentration / Robustness ---
    lines.append("## Концентрация и устойчивость (лучший сценарий)\n")
    for label, rob in [("Train", rob_train), ("OOS May", rob_oos)]:
        lines.append(f"### {label}")
        lines.append(f"- Топ-3 сделки: {rob.get('top3_pct',0):.1%} от суммарного PnL")
        lines.append(f"- Лучший день: {rob.get('best_day_pct',0):.1%} от суммарного PnL ({rob.get('best_date','N/A')})")
        lines.append(f"- Net без лучшего дня: {rob.get('net_without_best_day',0):.2f} руб")
        lines.append(f"- Концентрация высокая: **{'ДА' if rob.get('concentrated') else 'нет'}**")
        if rob.get("concentration_reason"):
            lines.append(f"  - {rob['concentration_reason']}")
        lines.append("")

    # --- Comparison with Hammer maxhold5 ---
    lines.append("## Сравнение с Hammer maxhold5\n")
    lines.append(
        "> **Внимание**: прямое сравнение невозможно (разные стратегии, разные периоды).\n"
    )
    best_oos = next((r for r in oos_results if r.get("scenario_name") == best_name), None)
    lines.append("| Метрика | ORB best OOS | Hammer maxhold5 (A/B май 2026) |")
    lines.append("|---------|-------------|-------------------------------|")
    if best_oos:
        lines.append(f"| Сделок | {best_oos.get('trades','N/A')} | ~57 (live paper) |")
        lines.append(f"| PF | {best_oos.get('profit_factor',0):.3f} | 1.163 |")
        lines.append(f"| WR | {best_oos.get('winrate',0):.1%} | ~52% (est) |")
        lines.append(f"| Net PnL | {best_oos.get('net_pnl',0):.2f} руб | см. paper report |")
    lines.append("")

    # --- Candidate decision ---
    lines.append("## Candidate Decision\n")
    lines.append(f"### {candidate_decision}\n")
    lines.append(f"{candidate_reason}\n")

    # --- Limitations ---
    lines.append("## Ограничения\n")
    lines.append(
        "1. **Короткий OOS**: май 2026 — только ~20 торговых дней; статистическая мощность низкая.\n"
        "2. **Единый контракт**: расчёт на 1 лот SiM6; реальный слиппедж при объёме может быть выше.\n"
        "3. **Нет overnight и event-risk**: стратегия закрывается до 18:40 MSK; геополитические "
        "ночные гэпы не моделируются.\n"
    )

    # --- Рекомендация / Next MVP ---
    lines.append("## Рекомендация / Next MVP\n")
    if candidate_decision == "PAPER_CANDIDATE":
        lines.append(
            "Запустить ORB как бумажную стратегию на SiU6 параллельно с Hammer maxhold5. "
            "Накопить 60+ сделок OOS перед принятием решения о реальной торговле.\n"
            "**Next MVP**: MVP-R1b — ORB на SiU6 (июнь–сентябрь 2026) с расширенной OOS выборкой.\n"
        )
    elif candidate_decision == "NEEDS_MORE_DATA":
        lines.append(
            "Дождаться июньских данных SiU6. Повторить анализ с 60+ OOS сделками. "
            "Рассмотреть расширение OR окна и дополнительные фильтры (объём, режим).\n"
            "**Next MVP**: MVP-R1b — ORB на SiU6 с OOS после ролловера.\n"
        )
    else:
        lines.append(
            "Стратегия не показывает достаточного преимущества. "
            "Рассмотреть другие подходы или существенную доработку фильтров.\n"
            "**Next MVP**: MVP-R2 — Mean Reversion Intraday или объёмные стратегии.\n"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Candidate decision
# ---------------------------------------------------------------------------

def make_candidate_decision(
    config: dict,
    oos_metrics: dict,
    slip_oos: list[dict],
    concentrated: bool,
) -> tuple[str, str]:
    """Determine PAPER_CANDIDATE / NEEDS_MORE_DATA / REJECT."""
    cand = config.get("candidate", {})
    min_oos_pf = float(cand.get("paper_candidate_min_oos_pf", 1.25))
    min_oos_net = float(cand.get("paper_candidate_min_oos_net", 0.0))
    max_slip_pts = float(cand.get("paper_candidate_max_slip_pts", 2))
    slip_thresh_pf = float(cand.get("paper_candidate_slip_threshold_pf", 1.1))
    reject_max_pf = float(cand.get("reject_max_oos_pf", 1.0))

    oos_pf = float(oos_metrics.get("profit_factor", 0))
    oos_net = float(oos_metrics.get("net_pnl", 0))

    # Check reject first
    if oos_net <= 0 or oos_pf < reject_max_pf:
        return ("REJECT", f"OOS net={oos_net:.2f} руб, PF={oos_pf:.3f} < {reject_max_pf}")

    # Check slippage at max_slip_pts
    slip_at_threshold = None
    for row in slip_oos:
        if float(row["slip_pts"]) == max_slip_pts:
            slip_at_threshold = row
            break
    slip_destroys = slip_at_threshold and slippage_destroyed_edge(
        slip_at_threshold, threshold_pf=slip_thresh_pf
    )

    # PAPER_CANDIDATE
    if (
        oos_pf >= min_oos_pf
        and oos_net > min_oos_net
        and not slip_destroys
        and not concentrated
    ):
        return (
            "PAPER_CANDIDATE",
            f"OOS PF={oos_pf:.3f} >= {min_oos_pf}, net={oos_net:.2f} > 0, "
            f"slippage@{max_slip_pts}pt не уничтожает edge, концентрация в норме",
        )

    # NEEDS_MORE_DATA
    reasons = []
    if oos_pf < min_oos_pf:
        reasons.append(f"OOS PF {oos_pf:.3f} < {min_oos_pf}")
    if slip_destroys:
        reasons.append(f"slippage@{max_slip_pts}pt уничтожает edge")
    if concentrated:
        reasons.append("высокая концентрация результатов")
    return ("NEEDS_MORE_DATA", "; ".join(reasons) if reasons else "недостаточно OOS данных")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ORB Walk-Forward + OOS + Slippage Audit")
    parser.add_argument("--config", required=True, help="Path to walkforward YAML config")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    train_csv = config["data"]["train_csv"]
    oos_csv = config["data"]["oos_csv"]
    ticker = config.get("experiment", {}).get("ticker", "SiM6")

    print(f"[ORB WF] Loading train data: {train_csv}")
    print(f"[ORB WF] Loading OOS data:   {oos_csv}")

    # --- Data quality ---
    print("[ORB WF] Running data quality checks...")
    train_dq = data_quality_report(train_csv, f"Train — {train_csv}")
    oos_dq = data_quality_report(oos_csv, f"OOS May — {oos_csv}")
    dq_md = build_data_quality_markdown(train_dq, oos_dq)

    dq_path = "reports/research_data_quality_SiM6_1m_202605_latest.md"
    os.makedirs("reports", exist_ok=True)
    with open(dq_path, "w") as f:
        f.write(dq_md)
    print(f"[ORB WF] Data quality: {dq_path}")

    # --- Build scenario config for run_orb_backtest ---
    # run_orb_backtest uses opening_ranges, directions, take.r
    backtest_config = {
        "experiment": config.get("experiment", {}),
        "opening_ranges": config.get("opening_ranges", [["10:00", "10:15"]]),
        "directions": config.get("directions", ["long", "short"]),
        "take": config.get("take", {"r": [1.5, 2.0]}),
        "entry": config.get("entry", {}),
        "stop": config.get("stop", {}),
        "exit": config.get("exit", {}),
        "commission": config.get("commission", {}),
    }

    # --- Run backtests ---
    print("[ORB WF] Running TRAIN backtest...")
    train_results, train_trades = run_orb_backtest(train_csv, backtest_config)
    print(f"[ORB WF] Train: {len(train_results)} scenarios, {len(train_trades)} trades")

    print("[ORB WF] Running OOS backtest...")
    oos_results, oos_trades = run_orb_backtest(oos_csv, backtest_config)
    print(f"[ORB WF] OOS: {len(oos_results)} scenarios, {len(oos_trades)} trades")

    print("[ORB WF] Running FULL (train+OOS) backtest...")
    # Concatenate CSVs for full run
    train_df = pd.read_csv(train_csv)
    oos_df = pd.read_csv(oos_csv)
    full_df = pd.concat([train_df, oos_df], ignore_index=True)
    full_results, full_trades = run_orb_backtest(full_df, backtest_config)
    print(f"[ORB WF] Full: {len(full_results)} scenarios, {len(full_trades)} trades")

    # Attach scenario name from config scenarios list where possible
    scenario_name_map = {}
    for s in config.get("scenarios", []):
        key = (
            f"{s['or_start_msk']}-{s['or_end_msk']}",
            s["direction"].upper(),
            float(s["take_r"]),
        )
        scenario_name_map[key] = s["name"]

    def _attach_names(results: list[dict]) -> list[dict]:
        for r in results:
            key = (r.get("or_window", ""), r.get("direction", ""), float(r.get("take_r", 0)))
            r["scenario_name"] = scenario_name_map.get(key, r.get("scenario", ""))
        return results

    train_results = _attach_names(train_results)
    oos_results = _attach_names(oos_results)
    full_results = _attach_names(full_results)

    # --- Find best scenario by train PF ---
    if not train_results:
        print("[ORB WF] ERROR: no train results generated.")
        sys.exit(1)

    best_train = max(train_results, key=lambda r: r.get("profit_factor", 0))
    best_key = (
        best_train.get("or_window", ""),
        best_train.get("direction", ""),
        float(best_train.get("take_r", 0)),
    )
    print(
        f"[ORB WF] Best scenario (train PF): {best_train.get('scenario_name','')} | "
        f"PF={best_train.get('profit_factor',0):.3f} | "
        f"net={best_train.get('net_pnl',0):.2f} | "
        f"trades={best_train.get('trades',0)}"
    )

    # Isolate trades for best scenario
    def _filter_trades(trades: list[dict], key: tuple) -> list[dict]:
        or_window, direction, take_r = key
        return [
            t for t in trades
            if t.get("or_window") == or_window
            and t.get("direction") == direction
            and float(t.get("take_r", 0)) == take_r
        ]

    best_train_trades = _filter_trades(train_trades, best_key)
    best_oos_trades = _filter_trades(oos_trades, best_key)

    best_oos = next(
        (r for r in oos_results if
         r.get("or_window") == best_key[0]
         and r.get("direction") == best_key[1]
         and float(r.get("take_r", 0)) == best_key[2]),
        {"profit_factor": 0, "net_pnl": 0, "trades": 0, "winrate": 0},
    )
    print(
        f"[ORB WF] Best scenario OOS: PF={best_oos.get('profit_factor',0):.3f} | "
        f"net={best_oos.get('net_pnl',0):.2f} | trades={best_oos.get('trades',0)}"
    )

    # --- Walk-forward ---
    print("[ORB WF] Building walk-forward tables...")
    wf_month_train = walkforward_table(best_train_trades, period="month")
    wf_week_train = walkforward_table(best_train_trades, period="week")
    wf_month_oos = walkforward_table(best_oos_trades, period="month")

    # --- Slippage ---
    slip_pts = config.get("slippage", {}).get("test_pts", [0, 1, 2, 5, 10])
    print(f"[ORB WF] Slippage sensitivity: {slip_pts}")
    # Costs come from the config, exactly as the trade simulation does — the two
    # must not be allowed to disagree (they used to: this call re-priced every
    # trade at point_value 10.0 / commission 0.05 regardless of the config).
    _commission_cfg = config.get("commission", {}) or {}
    if "rub_per_trade" not in _commission_cfg or "point_value_rub" not in _commission_cfg:
        raise SystemExit(
            "config must set commission.rub_per_trade and commission.point_value_rub"
        )
    commission_rub = float(_commission_cfg["rub_per_trade"])
    point_value_rub = float(_commission_cfg["point_value_rub"])
    slip_train = slippage_sensitivity(
        best_train_trades, slip_pts,
        point_value_rub=point_value_rub, commission_rub=commission_rub)
    slip_oos = slippage_sensitivity(
        best_oos_trades, slip_pts,
        point_value_rub=point_value_rub, commission_rub=commission_rub)

    # --- Robustness ---
    print("[ORB WF] Robustness analysis...")

    def _build_rob(trades: list[dict]) -> dict:
        top3 = top_trades_contribution(trades, 3)
        bd = best_day_contribution(trades)
        conc, conc_reason = concentration_flag(trades)
        return {
            "top3_pct": top3["pct_of_total"],
            "best_date": bd["best_date"],
            "best_day_pct": bd["pct_of_total"],
            "net_without_best_day": net_without_best_day(trades),
            "concentrated": conc,
            "concentration_reason": conc_reason,
        }

    rob_train = _build_rob(best_train_trades)
    rob_oos = _build_rob(best_oos_trades)

    # --- Regime breakdown ---
    print("[ORB WF] Regime breakdown...")
    train_candles = pd.read_csv(train_csv)
    oos_candles = pd.read_csv(oos_csv)
    regime_train_rows = regime_breakdown(best_train_trades, train_candles)
    regime_oos_rows = regime_breakdown(best_oos_trades, oos_candles)

    # --- Candidate decision ---
    oos_metrics_best = compute_metrics(best_oos_trades)
    candidate, candidate_reason = make_candidate_decision(
        config, oos_metrics_best, slip_oos, rob_oos["concentrated"]
    )
    print(f"[ORB WF] Candidate decision: {candidate} — {candidate_reason}")

    # --- Build report ---
    print("[ORB WF] Building report...")
    report_md = build_walkforward_report(
        config=config,
        train_dq=train_dq,
        oos_dq=oos_dq,
        train_results=train_results,
        oos_results=oos_results,
        full_results=full_results,
        best_scenario=best_train,
        best_train_trades=best_train_trades,
        best_oos_trades=best_oos_trades,
        wf_month_train=wf_month_train,
        wf_week_train=wf_week_train,
        wf_month_oos=wf_month_oos,
        slip_train=slip_train,
        slip_oos=slip_oos,
        regime_train=regime_train_rows,
        regime_oos=regime_oos_rows,
        rob_train=rob_train,
        rob_oos=rob_oos,
        candidate_decision=candidate,
        candidate_reason=candidate_reason,
    )

    # --- Write outputs ---
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("reports", exist_ok=True)
    os.makedirs("out", exist_ok=True)

    report_path = f"reports/research_orb_walkforward_{ticker}_{ts}.md"
    report_latest = f"reports/research_orb_walkforward_{ticker}_latest.md"
    for path in [report_path, report_latest]:
        with open(path, "w") as f:
            f.write(report_md)

    # Summary CSV — all scenarios on train + oos
    summary_rows = []
    for period_label, results in [("train", train_results), ("oos", oos_results), ("full", full_results)]:
        for r in results:
            row = {"period": period_label, **{k: v for k, v in r.items() if k != "exit_reason_breakdown"}}
            if "exit_reason_breakdown" in r:
                for reason, cnt in r["exit_reason_breakdown"].items():
                    row[f"exit_{reason.lower()}"] = cnt
            summary_rows.append(row)

    summary_csv = f"out/research_orb_walkforward_summary_{ticker}_{ts}.csv"
    summary_csv_latest = f"out/research_orb_walkforward_summary_{ticker}_latest.csv"
    if summary_rows:
        fieldnames = list(summary_rows[0].keys())
        for path in [summary_csv, summary_csv_latest]:
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(summary_rows)

    # Trades CSV — best scenario only (train + oos)
    all_best_trades = [
        {"period": "train", **t} for t in best_train_trades
    ] + [
        {"period": "oos", **t} for t in best_oos_trades
    ]
    trades_csv = f"out/research_orb_walkforward_trades_{ticker}_{ts}.csv"
    trades_csv_latest = f"out/research_orb_walkforward_trades_{ticker}_latest.csv"
    if all_best_trades:
        fieldnames = list(all_best_trades[0].keys())
        for path in [trades_csv, trades_csv_latest]:
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_best_trades)

    # --- Print summary to stdout ---
    print("\n" + "=" * 70)
    print(f"ORB WALK-FORWARD SUMMARY — {ticker}")
    print("=" * 70)
    print(f"\nTop 3 scenarios by TRAIN PF:")
    for i, r in enumerate(sorted(train_results, key=lambda x: x.get("profit_factor", 0), reverse=True)[:3], 1):
        print(
            f"  {i}. {r.get('scenario_name',''):<20} | OR={r.get('or_window','')} "
            f"dir={r.get('direction','')} R={r.get('take_r','')} "
            f"| PF={r.get('profit_factor',0):.3f} net={r.get('net_pnl',0):.2f} "
            f"trades={r.get('trades',0)}"
        )

    print(f"\nTop 3 scenarios by OOS PF:")
    for i, r in enumerate(sorted(oos_results, key=lambda x: x.get("profit_factor", 0), reverse=True)[:3], 1):
        print(
            f"  {i}. {r.get('scenario_name',''):<20} | OR={r.get('or_window','')} "
            f"dir={r.get('direction','')} R={r.get('take_r','')} "
            f"| PF={r.get('profit_factor',0):.3f} net={r.get('net_pnl',0):.2f} "
            f"trades={r.get('trades',0)}"
        )

    print(f"\nBest scenario ({best_train.get('scenario_name','')}) Slippage OOS:")
    for row in slip_oos:
        print(
            f"  slip={row['slip_pts']:>4} pt | PF={row.get('profit_factor',0):.3f} "
            f"net={row.get('net_pnl',0):>8.2f} | destroyed={row.get('destroyed_edge')}"
        )

    print(f"\n{'=' * 70}")
    print(f"CANDIDATE DECISION: {candidate}")
    print(f"Reason: {candidate_reason}")
    print(f"{'=' * 70}")

    print(f"\nOutputs:")
    print(f"  Report:  {report_path}")
    print(f"  Summary: {summary_csv}")
    print(f"  Trades:  {trades_csv}")
    print(f"  DQ:      {dq_path}")


if __name__ == "__main__":
    main()
