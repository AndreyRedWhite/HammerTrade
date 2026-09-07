"""Кросс-секционный портфельный бэктест (дневной/недельный горизонт).

Форма задачи принципиально иная, чем у интрадейного событийного движка
(`src/backtest/engine.py`): здесь на каждую дату ребаланса ранжируется весь
универс, формируется портфель и держится до следующего ребаланса.

Жёсткие правила вшиты в движок, а не оставлены на дисциплину вызывающего кода:

* **Никакого lookahead.** Сигнал считается по данным до закрытия дня R
  включительно и исполняется по цене ОТКРЫТИЯ дня R+delay (по умолчанию +1).
  Веса `W[i]` — это то, с чем выходишь из открытия дня i; доходность они
  зарабатывают начиная со следующего интервала.
* **Издержки на оборот**, а не на сделку: `turnover × bps`. Дрейф весов между
  ребалансами учитывается, иначе оборот завышается.
* **Нельзя продать то, что не торгуется.** Если удерживаемая бумага в день
  ребаланса не торгуется, позиция переносится, а не закрывается по
  несуществующей цене — иначе через чёрный ход возвращается survivorship bias.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .panel import Panel, liquidity_mask


@dataclass
class Config:
    rebalance: str = "ME"              # 'ME' месяц, 'W-FRI' неделя
    long_q: float = 0.2                # верхний квинтиль в лонг
    short_q: float | None = None       # нижний квинтиль в шорт; None => long-only
    cost_bps_per_side: float = 10.0    # 5 комиссия (замерена) + 5 проскальзывание
    borrow_bps_per_year: float = 0.0   # стоимость займа под шорт
    exec_delay: int = 1                # дней от сигнала до исполнения (≥1)
    min_names: int = 10                # меньше — ребаланс пропускается
    liq_lookback: int = 20
    liq_min_value: float = 50_000_000.0


@dataclass
class Result:
    equity: pd.Series
    ret: pd.Series
    gross_ret: pd.Series
    cost: pd.Series
    turnover: pd.Series
    weights: pd.DataFrame
    n_long: pd.Series
    n_short: pd.Series
    config: Config
    contrib: pd.DataFrame = field(default_factory=pd.DataFrame)


def _rebalance_dates(dates: pd.DatetimeIndex, freq: str) -> list[int]:
    """Индексы последних торговых дней каждого периода."""
    s = pd.Series(np.arange(len(dates)), index=dates)
    return sorted(s.resample(freq).last().dropna().astype(int).tolist())


def _target_weights(scores: pd.Series, eligible: pd.Series,
                    cfg: Config) -> pd.Series | None:
    """Ранжирование → веса. Возвращает None, если бумаг слишком мало."""
    s = scores.where(eligible).dropna()
    if len(s) < cfg.min_names:
        return None

    w = pd.Series(0.0, index=scores.index)
    n_long = max(1, int(round(len(s) * cfg.long_q)))
    longs = s.nlargest(n_long).index
    w.loc[longs] = 1.0 / n_long

    if cfg.short_q:
        n_short = max(1, int(round(len(s) * cfg.short_q)))
        shorts = s.nsmallest(n_short).index
        # бумага не может быть одновременно в обеих ногах
        shorts = shorts.difference(longs)
        if len(shorts):
            w.loc[shorts] = -1.0 / len(shorts)
    return w


def run(panel: Panel, signal: pd.DataFrame, cfg: Config) -> Result:
    """signal: матрица (даты × тикеры). Значение на дату R должно быть посчитано
    по данным ДО закрытия R включительно — за это отвечает функция сигнала."""
    if cfg.exec_delay < 1:
        raise ValueError("exec_delay должен быть ≥1: исполнение по открытию "
                         "следующего дня, иначе это lookahead")

    dates = panel.dates
    tickers = panel.tickers
    n, m = len(dates), len(tickers)

    liq = liquidity_mask(panel, cfg.liq_lookback, cfg.liq_min_value)
    signal = signal.reindex(index=dates, columns=tickers)
    ret = panel.ret_oo.reindex(index=dates, columns=tickers).fillna(0.0).to_numpy()
    tradable = panel.tradable.reindex(index=dates, columns=tickers).fillna(False).to_numpy()

    # день ребаланса -> день исполнения
    exec_of = {}
    for r in _rebalance_dates(dates, cfg.rebalance):
        e = r + cfg.exec_delay
        if e < n:
            exec_of[e] = r

    W = np.zeros((n, m))
    port_ret = np.zeros(n)
    gross = np.zeros(n)
    cost = np.zeros(n)
    turn = np.zeros(n)
    n_long = np.zeros(n, dtype=int)
    n_short = np.zeros(n, dtype=int)
    contrib = np.zeros((n, m))

    borrow_daily = cfg.borrow_bps_per_year / 1e4 / 252.0

    for i in range(1, n):
        w_prev = W[i - 1]
        r_i = ret[i]

        pnl_i = w_prev * r_i
        g = pnl_i.sum()
        # заём под шорт: платим за валовую короткую экспозицию
        short_expo = -w_prev[w_prev < 0].sum()
        g -= short_expo * borrow_daily

        gross[i] = g
        contrib[i] = pnl_i

        # дрейф весов за прошедший интервал
        denom = 1.0 + g
        w_drift = w_prev * (1.0 + r_i) / (denom if abs(denom) > 1e-9 else 1.0)

        if i in exec_of:
            r_idx = exec_of[i]
            eligible = pd.Series(liq.to_numpy()[r_idx], index=tickers)
            tgt = _target_weights(pd.Series(signal.to_numpy()[r_idx], index=tickers),
                                  eligible, cfg)
            if tgt is None:
                W[i] = w_drift
            else:
                w_new = tgt.to_numpy().copy()
                # нельзя выйти из бумаги, которой сегодня не торгуют — переносим
                stuck = (~tradable[i]) & (np.abs(w_drift) > 1e-12)
                w_new[stuck] = w_drift[stuck]
                t = np.abs(w_new - w_drift).sum()
                turn[i] = t
                cost[i] = t * cfg.cost_bps_per_side / 1e4
                W[i] = w_new
                n_long[i] = int((w_new > 0).sum())
                n_short[i] = int((w_new < 0).sum())
        else:
            W[i] = w_drift
            n_long[i] = n_long[i - 1]
            n_short[i] = n_short[i - 1]

        port_ret[i] = gross[i] - cost[i]

    idx = dates
    return Result(
        equity=pd.Series((1.0 + pd.Series(port_ret, index=idx)).cumprod(), index=idx),
        ret=pd.Series(port_ret, index=idx),
        gross_ret=pd.Series(gross, index=idx),
        cost=pd.Series(cost, index=idx),
        turnover=pd.Series(turn, index=idx),
        weights=pd.DataFrame(W, index=idx, columns=tickers),
        n_long=pd.Series(n_long, index=idx),
        n_short=pd.Series(n_short, index=idx),
        config=cfg,
        contrib=pd.DataFrame(contrib, index=idx, columns=tickers),
    )
