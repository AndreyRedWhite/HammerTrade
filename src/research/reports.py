"""Research report builders for ORB and other strategies."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional


def build_orb_markdown_report(
    scenario_results: list[dict],
    all_trades: list[dict],
    config: dict,
) -> str:
    """Build a Markdown research report for ORB backtest results.

    Sections: Цель, Источник данных, Top scenarios, Results by opening range,
    Results by take_r, Results by direction, Results by regime, Worst scenarios,
    Trade examples, Comparison with hammer maxhold5, Limitations, Recommendation.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ticker = config.get("experiment", {}).get("ticker", "SiM6")
    timeframe = config.get("experiment", {}).get("timeframe", "1m")
    candles_csv = config.get("data", {}).get("candles_csv", "N/A")

    period = scenario_results[0].get("period", "N/A") if scenario_results else "N/A"
    total_scenarios = len(scenario_results)
    total_trades = len(all_trades)

    lines = []
    lines.append(f"# ORB Research Report — {ticker} {timeframe}")
    lines.append(f"\nСгенерировано: {now}\n")

    # Цель
    lines.append("## Цель\n")
    lines.append(
        "Исследование стратегии Opening Range Breakout (ORB) на фьючерсах Si (MOEX) "
        "на 1-минутных барах. Цель — оценить потенциал ORB как дополнительной стратегии "
        "к действующей Hammer Reversal, изучить зависимость результатов от параметров "
        "открывающего диапазона, соотношения риск/прибыль и рыночного режима.\n"
    )

    # Источник данных
    lines.append("## Источник данных\n")
    lines.append(f"- Файл: `{candles_csv}`")
    lines.append(f"- Период: {period}")
    lines.append(f"- Тикер: {ticker}, таймфрейм: {timeframe}")
    lines.append(f"- Всего сценариев: {total_scenarios}, всего сделок: {total_trades}")
    lines.append(
        "\n> **Ограничение**: данные охватывают только Jan–Apr 2026. "
        "Майские и поздние апрельские данные (с 10 апреля) отсутствуют в локальном датасете.\n"
    )

    if not scenario_results:
        lines.append("\n_Нет результатов для отображения._\n")
        return "\n".join(lines)

    # Sort by PF desc
    sorted_by_pf = sorted(scenario_results, key=lambda x: x.get("profit_factor", 0), reverse=True)

    # Top scenarios
    lines.append("## Топ-10 сценариев по Profit Factor\n")
    lines.append("| # | OR окно | Направление | Take R | Сделок | Побед | Winrate | Net PnL (руб) | PF | Expectancy |")
    lines.append("|---|---------|-------------|--------|--------|-------|---------|---------------|-----|------------|")
    for i, r in enumerate(sorted_by_pf[:10], 1):
        lines.append(
            f"| {i} | {r.get('or_window')} | {r.get('direction')} | "
            f"{r.get('take_r')} | {r.get('trades')} | {r.get('wins')} | "
            f"{r.get('winrate', 0):.1%} | {r.get('net_pnl', 0):.2f} | "
            f"{r.get('profit_factor', 0):.3f} | {r.get('expectancy', 0):.2f} |"
        )
    lines.append("")

    # Results by opening range
    lines.append("## Результаты по ширине открывающего диапазона\n")
    or_windows = sorted(set(r["or_window"] for r in scenario_results))
    lines.append("| OR окно | Сценариев | Медиана PF | Медиана Net PnL | Медиана Winrate |")
    lines.append("|---------|-----------|------------|-----------------|-----------------|")
    for or_w in or_windows:
        group = [r for r in scenario_results if r["or_window"] == or_w]
        pfs = [r.get("profit_factor", 0) for r in group]
        pnls = [r.get("net_pnl", 0) for r in group]
        wrs = [r.get("winrate", 0) for r in group]
        lines.append(
            f"| {or_w} | {len(group)} | {_median(pfs):.3f} | "
            f"{_median(pnls):.2f} | {_median(wrs):.1%} |"
        )
    lines.append("")

    # Results by take_r
    lines.append("## Результаты по Take R\n")
    take_rs = sorted(set(r["take_r"] for r in scenario_results))
    lines.append("| Take R | Сценариев | Медиана PF | Медиана Net PnL | Медиана Winrate |")
    lines.append("|--------|-----------|------------|-----------------|-----------------|")
    for tr in take_rs:
        group = [r for r in scenario_results if r["take_r"] == tr]
        pfs = [r.get("profit_factor", 0) for r in group]
        pnls = [r.get("net_pnl", 0) for r in group]
        wrs = [r.get("winrate", 0) for r in group]
        lines.append(
            f"| {tr} | {len(group)} | {_median(pfs):.3f} | "
            f"{_median(pnls):.2f} | {_median(wrs):.1%} |"
        )
    lines.append("")

    # Results by direction
    lines.append("## Результаты по направлению\n")
    directions = sorted(set(r["direction"] for r in scenario_results))
    lines.append("| Направление | Сценариев | Медиана PF | Медиана Net PnL | Медиана Winrate |")
    lines.append("|-------------|-----------|------------|-----------------|-----------------|")
    for d in directions:
        group = [r for r in scenario_results if r["direction"] == d]
        pfs = [r.get("profit_factor", 0) for r in group]
        pnls = [r.get("net_pnl", 0) for r in group]
        wrs = [r.get("winrate", 0) for r in group]
        lines.append(
            f"| {d} | {len(group)} | {_median(pfs):.3f} | "
            f"{_median(pnls):.2f} | {_median(wrs):.1%} |"
        )
    lines.append("")

    # Results by regime (if available)
    has_regime = any("regime_breakdown" in r for r in scenario_results)
    if has_regime:
        lines.append("## Результаты по рыночному режиму\n")
        regime_stats: dict = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        for t in all_trades:
            regime = t.get("regime", "NORMAL")
            regime_stats[regime]["trades"] += 1
            pnl = float(t.get("pnl_rub", 0))
            regime_stats[regime]["pnl"] += pnl
            if pnl > 0:
                regime_stats[regime]["wins"] += 1

        lines.append("| Режим | Сделок | Побед | Winrate | Net PnL (руб) |")
        lines.append("|-------|--------|-------|---------|---------------|")
        for regime, stats in sorted(regime_stats.items()):
            t_count = stats["trades"]
            wr = stats["wins"] / t_count if t_count else 0
            lines.append(
                f"| {regime} | {t_count} | {stats['wins']} | "
                f"{wr:.1%} | {stats['pnl']:.2f} |"
            )
        lines.append("")

    # Worst scenarios
    lines.append("## Худшие сценарии (по Profit Factor)\n")
    worst = sorted(scenario_results, key=lambda x: x.get("profit_factor", 0))[:5]
    lines.append("| OR окно | Направление | Take R | Сделок | Net PnL | PF |")
    lines.append("|---------|-------------|--------|--------|---------|-----|")
    for r in worst:
        lines.append(
            f"| {r.get('or_window')} | {r.get('direction')} | "
            f"{r.get('take_r')} | {r.get('trades')} | "
            f"{r.get('net_pnl', 0):.2f} | {r.get('profit_factor', 0):.3f} |"
        )
    lines.append("")

    # Trade examples
    lines.append("## Примеры сделок\n")

    if all_trades:
        sorted_trades = sorted(all_trades, key=lambda t: float(t.get("pnl_rub", 0)), reverse=True)
        top5 = sorted_trades[:5]
        bot5 = sorted_trades[-5:]

        lines.append("### Топ-5 прибыльных сделок\n")
        lines.append("| Дата | Тикер | Dir | OR окно | Take R | Entry | Exit | PnL руб | Exit reason |")
        lines.append("|------|-------|-----|---------|--------|-------|------|---------|-------------|")
        for t in top5:
            lines.append(
                f"| {t.get('date', '')} | {t.get('ticker', '')} | "
                f"{t.get('direction', '')} | {t.get('or_window', '')} | "
                f"{t.get('take_r', '')} | {t.get('entry_price', '')} | "
                f"{t.get('exit_price', '')} | {t.get('pnl_rub', 0):.2f} | "
                f"{t.get('exit_reason', '')} |"
            )
        lines.append("")

        lines.append("### Топ-5 убыточных сделок\n")
        lines.append("| Дата | Тикер | Dir | OR окно | Take R | Entry | Exit | PnL руб | Exit reason |")
        lines.append("|------|-------|-----|---------|--------|-------|------|---------|-------------|")
        for t in bot5:
            lines.append(
                f"| {t.get('date', '')} | {t.get('ticker', '')} | "
                f"{t.get('direction', '')} | {t.get('or_window', '')} | "
                f"{t.get('take_r', '')} | {t.get('entry_price', '')} | "
                f"{t.get('exit_price', '')} | {t.get('pnl_rub', 0):.2f} | "
                f"{t.get('exit_reason', '')} |"
            )
        lines.append("")

    # Comparison with Hammer maxhold5
    lines.append("## Сравнение с Hammer Reversal (maxhold5)\n")
    lines.append(
        "Данные для сравнения Hammer maxhold5 (май 2026) недоступны в backtesting-формате "
        "за тот же период (Jan–Apr 2026). Прямое сравнение невозможно из-за разных периодов.\n"
    )
    lines.append(
        "| Метрика | ORB best scenario | Hammer maxhold5 (paper) |\n"
        "|---------|-------------------|------------------------|\n"
    )
    if sorted_by_pf:
        best = sorted_by_pf[0]
        lines.append(
            f"| Trades | {best.get('trades', 'N/A')} | ~57 (live май) |\n"
            f"| PF | {best.get('profit_factor', 0):.3f} | 1.163 (A/B май) |\n"
            f"| Winrate | {best.get('winrate', 0):.1%} | ~52% (est) |\n"
            f"| Net PnL | {best.get('net_pnl', 0):.2f} RUB | see paper report |\n"
        )

    # Limitations
    lines.append("## Ограничения\n")
    lines.append(
        "1. **Период данных**: только Jan 15 – Apr 9, 2026. Майские данные отсутствуют локально "
        "(бот работает на сервере, raw candles не сохраняются).\n"
        "2. **Исполнение**: backtest использует limit-order симуляцию на уровне OR high/low. "
        "В реальности возможно проскальзывание при гэпах на открытии.\n"
        "3. **Комиссия**: учтена фиксированная комиссия 0.05 руб/сделку (одна сторона). "
        "Реальные сборы брокера могут отличаться.\n"
        "4. **Один контракт**: расчёт ведётся на 1 контракт Si.\n"
        "5. **Нет overnight**: стратегия закрывает позиции до 18:40 MSK.\n"
        "6. **False breakout filter**: первые 2 бара после OR окна пропускаются. "
        "Этот параметр не оптимизировался.\n"
        "7. **Overfit risk**: результаты получены на одном in-sample периоде без walk-forward.\n"
    )

    # Recommendation
    lines.append("## Рекомендация\n")
    if sorted_by_pf and sorted_by_pf[0].get("profit_factor", 0) >= 1.3:
        rec = "ПЕРСПЕКТИВНО — лучший сценарий показывает PF ≥ 1.3."
        advice = (
            "Рекомендуется провести walk-forward тест и расширить датасет (SiU6) "
            "перед рассмотрением бумажного трейдинга."
        )
    elif sorted_by_pf and sorted_by_pf[0].get("profit_factor", 0) >= 1.1:
        rec = "ТРЕБУЕТ ДОПОЛНИТЕЛЬНОГО ИССЛЕДОВАНИЯ — PF в диапазоне 1.1–1.3."
        advice = (
            "Оптимизировать параметры на расширенном датасете. "
            "Проверить устойчивость на out-of-sample периоде."
        )
    else:
        rec = "НЕ РЕКОМЕНДУЕТСЯ — PF < 1.1 даже в лучших сценариях."
        advice = "Стратегия не показывает статистического преимущества на данном датасете."

    lines.append(f"**{rec}**\n\n{advice}\n")

    return "\n".join(lines)


def build_orb_csv(scenario_results: list[dict]) -> list[dict]:
    """Return scenario results as list of flat dicts suitable for CSV export."""
    rows = []
    for r in scenario_results:
        row = {k: v for k, v in r.items() if k not in ("exit_reason_breakdown", "regime_breakdown")}
        # Flatten exit reason breakdown
        if "exit_reason_breakdown" in r:
            for reason, count in r["exit_reason_breakdown"].items():
                row[f"exit_{reason.lower()}"] = count
        rows.append(row)
    return rows


def build_trades_csv(all_trades: list[dict]) -> list[dict]:
    """Return all trades as list of dicts for CSV export."""
    return [dict(t) for t in all_trades]


def _median(values: list) -> float:
    """Compute median of a list of numbers."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return float(s[n // 2])
    return float((s[n // 2 - 1] + s[n // 2]) / 2)
