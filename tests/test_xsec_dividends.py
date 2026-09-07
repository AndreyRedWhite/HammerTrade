"""Проверка привязки дивидендов к ex-дате на РЕАЛЬНЫХ данных.

Это регрессионный тест на предположение, а не на код: конвенция MOEX уже один
раз менялась (до 2024 цена падала за торговый день до даты реестра, с 2024 — в
саму дату). Если она поедет снова, этот тест обязан упасть громко, а не молча
испортить все ряды доходностей.

Смысл проверки: на ex-дате крупной выплаты ЦЕНОВАЯ доходность резко
отрицательна, а доходность ПОЛНАЯ (с возвращённым дивидендом) — близка к нулю.
Если привязка сдвинута, картина ломается: появляется фиктивный плюс в один день
и настоящий минус в другой.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.xsec.panel import RAW, build_panel

MIN_YIELD = 0.04     # мелкие выплаты не видны в дневном шуме
MIN_SAMPLE = 8


@pytest.fixture(scope="module")
def panel():
    if not list((RAW / "eq").glob("*.csv")) or not list((RAW / "div").glob("*.csv")):
        pytest.skip("нет загруженных данных MOEX — сначала fetch_moex_daily_universe.py")
    return build_panel(use_cache=False)


def _large_dividend_events(panel) -> pd.DataFrame:
    price_ret = panel.close / panel.close.shift(1) - 1.0
    rows = []
    nz = panel.div.stack()
    nz = nz[nz != 0]
    for (dt, t), val in nz.items():
        px = panel.close.at[dt, t]
        if not np.isfinite(px) or px <= 0 or val / px < MIN_YIELD:
            continue
        pr, tr = price_ret.at[dt, t], panel.ret_cc.at[dt, t]
        if not (np.isfinite(pr) and np.isfinite(tr)):
            continue
        rows.append({"ticker": t, "date": dt, "yield": val / px,
                     "price_ret": pr, "total_ret": tr})
    return pd.DataFrame(rows)


def test_dividend_attachment_matches_price_drop(panel):
    """Полная доходность на ex-дате должна быть заметно ближе к нулю, чем ценовая."""
    ev = _large_dividend_events(panel)
    if len(ev) < MIN_SAMPLE:
        pytest.skip(f"слишком мало крупных выплат в выгрузке: {len(ev)}")

    mean_price = ev["price_ret"].abs().mean()
    mean_total = ev["total_ret"].abs().mean()
    assert mean_total < mean_price, (
        f"дивиденд не объясняет движение цены — привязка к ex-дате сдвинута: "
        f"|price| {mean_price:.2%} vs |total| {mean_total:.2%}")
    assert mean_total < 0.6 * mean_price, (
        f"дивиденд объясняет лишь {1 - mean_total / mean_price:.0%} движения — "
        f"похоже, конвенция ex-даты снова изменилась (n={len(ev)})")


def test_price_actually_falls_on_assumed_ex_date(panel):
    """На большинстве крупных выплат цена должна падать, а не расти."""
    ev = _large_dividend_events(panel)
    if len(ev) < MIN_SAMPLE:
        pytest.skip(f"слишком мало крупных выплат: {len(ev)}")
    share_down = float((ev["price_ret"] < 0).mean())
    assert share_down >= 0.7, (
        f"цена падает лишь в {share_down:.0%} крупных выплат — привязка неверна")


def test_no_absurd_dividend_driven_daily_return(panel):
    """Фильтр несогласованных записей не должен пропускать фиктивные +25% за день."""
    ev = _large_dividend_events(panel)
    if ev.empty:
        pytest.skip("нет крупных выплат")
    worst = ev.loc[ev["total_ret"].idxmax()]
    assert worst["total_ret"] < 0.25, (
        f"фиктивная дневная доходность от дивиденда: {worst['ticker']} "
        f"{worst['date'].date()} total_ret {worst['total_ret']:+.1%}")
