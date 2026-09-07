"""Пре-регистрированный набор сигналов (см. docs/claude_code_mvp_d1_daily_horizon_plan.md §5).

Только канонические, многократно задокументированные аномалии. Ничего
изобретённого: изобретённый сигнал на 11 годах данных подгоняется тривиально.

Контракт для всех функций: значение на дату T посчитано ПО ДАННЫМ ДО ЗАКРЫТИЯ T
ВКЛЮЧИТЕЛЬНО. Никаких центрированных окон, никаких shift(-1). Движок исполняет
такой сигнал по открытию T+1.

Больший скор = привлекательнее для лонга.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .panel import Panel

TRADING_DAYS_MONTH = 21
TRADING_DAYS_YEAR = 252


def total_return_index(panel: Panel) -> pd.DataFrame:
    """Индекс полной доходности по каждой бумаге (дивиденды реинвестированы).

    Именно по нему считаются моментум и волатильность — по «сырому» CLOSE они
    систематически смещены против высокодивидендных бумаг: на ex-дате цена
    падает, и это выглядит как отрицательная доходность.
    """
    return (1.0 + panel.ret_cc.fillna(0.0)).cumprod()


def momentum_12_1(panel: Panel, lookback: int = TRADING_DAYS_YEAR,
                  skip: int = TRADING_DAYS_MONTH) -> pd.DataFrame:
    """Кросс-секционный моментум: доходность за 12 мес с пропуском последнего.

    Пропуск последнего месяца — стандартная конструкция: он снимает
    краткосрочный разворот, который иначе загрязняет моментум-сигнал.
    """
    tri = total_return_index(panel)
    return tri.shift(skip) / tri.shift(lookback) - 1.0


def trend_ts(panel: Panel, window: int = 200) -> pd.DataFrame:
    """Time-series тренд: превышение цены над своей скользящей средней.

    Знак определяет участие (лонг только при положительном), величина —
    ранжирование.
    """
    tri = total_return_index(panel)
    return tri / tri.rolling(window, min_periods=window // 2).mean() - 1.0


def reversal_1w(panel: Panel, window: int = 5) -> pd.DataFrame:
    """Краткосрочный разворот: минус доходность за неделю.

    КОНТРОЛЬ, а не кандидат. По арифметике издержек (недельный ребаланс,
    высокий оборот) он обязан умереть. Если он «выживет» — значит в движке
    ошибка, а не открытие.
    """
    tri = total_return_index(panel)
    return -(tri / tri.shift(window) - 1.0)


def low_volatility(panel: Panel, window: int = 60) -> pd.DataFrame:
    """Low-vol: минус реализованная волатильность (низкая vol = высокий скор)."""
    return -panel.ret_cc.rolling(window, min_periods=window // 2).std()


def bench_regime(panel: Panel, window: int = 200, bench: str = "MCFTR") -> pd.Series:
    """Режимный фильтр: True, когда индекс выше своей скользящей средней.

    Используется как overlay поверх сигналов 1–2: вне режима портфель уходит
    в деньги.
    """
    if bench not in panel.bench.columns:
        bench = panel.bench.columns[0]
    b = panel.bench[bench].ffill()
    return b > b.rolling(window, min_periods=window // 2).mean()


def apply_regime(signal: pd.DataFrame, regime: pd.Series) -> pd.DataFrame:
    """Гасит сигнал в датах, где режим выключен (портфель уходит в кэш)."""
    return signal.where(regime.reindex(signal.index).fillna(False), other=np.nan)


#: Пре-регистрированный набор. Ключ -> (функция, kwargs). Расширять этот список
#: после того, как увидены результаты, — значит заниматься подгонкой.
REGISTRY = {
    "mom_12_1":       (momentum_12_1, {}),
    "mom_6_1":        (momentum_12_1, {"lookback": 126}),
    "trend_200":      (trend_ts, {"window": 200}),
    "trend_100":      (trend_ts, {"window": 100}),
    "lowvol_60":      (low_volatility, {"window": 60}),
    "lowvol_120":     (low_volatility, {"window": 120}),
    "reversal_1w":    (reversal_1w, {}),          # контроль — должен провалиться
}
