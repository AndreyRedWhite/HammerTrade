"""Построение выровненной панели дневных данных MOEX для кросс-секционных тестов.

Панель — это набор матриц (даты × тикеры): open, close, value, плюс маски
торгуемости. Из неё считаются сигналы и доходности.

Три вещи, каждая из которых способна в одиночку сфабриковать ложный край, и
поэтому решаются здесь, а не оставляются на дисциплину вызывающего кода:

1. **Point-in-time состав.** Бумага участвует только в те даты, когда она реально
   торговалась. Делистингованные остаются в истории до своего последнего дня.
2. **Total return.** Дивиденды возвращаются в доходность, иначе ранжирование
   систематически наказывает высокодивидендные бумаги (на MOEX это 8–10%/год).
3. **Разрыв 2022.** Биржа стояла 28.02–24.03.2022: ISS отдаёт строки с CLOSE=None.
   Такие даты выкидываются из индекса, и доходность через разрыв становится одним
   честным «дневным» наблюдением, а не месяцем нулей.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("data/raw/moex_daily")
CACHE = Path("data/processed/xsec_panel.pkl")

# Дивиденды ISS датированы датой ЗАКРЫТИЯ РЕЕСТРА, а цена падает на ex-дате.
# Смещение определено эмпирически (см. tests/test_xsec_dividends.py): до 2024
# провал цены приходится на 1 торговый день ДО даты реестра, с 2024 — на саму
# дату. Соответствует переходу MOEX на более короткий расчётный цикл.
#
# ВАЖНО: соблазнительный вариант «искать день с самой отрицательной доходностью
# в окне ±5 дней» применять НЕЛЬЗЯ. Он подмешивает дивиденд именно к худшим дням
# и тем самым систематически глушит реальные просадки — то есть фабрикует
# оптимизм ровно того сорта, который этот проект уже четыре раза находил у себя
# постфактум. Конвенция должна быть внешней по отношению к данным.
EX_SHIFT_ERAS = ((pd.Timestamp("2024-01-01"), 0), (pd.Timestamp.min, 1))


def _ex_shift_bdays(rec: pd.Timestamp) -> int:
    for since, shift in EX_SHIFT_ERAS:
        if rec >= since:
            return shift
    return 1


@dataclass
class Panel:
    open: pd.DataFrame          # цена открытия
    close: pd.DataFrame         # цена закрытия
    value: pd.DataFrame         # оборот, ₽
    tradable: pd.DataFrame      # bool: в этот день бумагой реально торговали
    div: pd.DataFrame           # дивиденд на акцию, отнесённый к ex-дате
    ret_cc: pd.DataFrame        # total-return close→close
    ret_oo: pd.DataFrame        # total-return open→open (для исполнения на открытии)
    bench: pd.DataFrame         # IMOEX / MCFTR

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.close.index

    @property
    def tickers(self) -> list[str]:
        return list(self.close.columns)

    def describe(self) -> str:
        n_gap = int((~self.tradable).sum().sum())
        return (f"Panel: {len(self.dates)} торговых дней "
                f"{self.dates[0].date()} → {self.dates[-1].date()}, "
                f"{len(self.tickers)} бумаг, "
                f"{self.tradable.sum(axis=1).mean():.0f} торгуемых в среднем за день, "
                f"{n_gap:,} пропусков (бумага не торговалась)")


def _load_equity_frames() -> tuple[pd.DataFrame, ...]:
    files = sorted(RAW.glob("eq/*.csv"))
    if not files:
        raise FileNotFoundError(f"нет данных в {RAW/'eq'} — сначала fetch_moex_daily_universe.py")
    o, c, v = {}, {}, {}
    for f in files:
        df = pd.read_csv(f, parse_dates=["TRADEDATE"])
        if df.empty:
            continue
        df = df.set_index("TRADEDATE").sort_index()
        for col in ("OPEN", "CLOSE", "VALUE"):
            df[col] = pd.to_numeric(df.get(col), errors="coerce")
        t = f.stem
        o[t], c[t], v[t] = df["OPEN"], df["CLOSE"], df["VALUE"]
    return (pd.DataFrame(o).sort_index(),
            pd.DataFrame(c).sort_index(),
            pd.DataFrame(v).sort_index())


def _load_dividends(dates: pd.DatetimeIndex, tickers: list[str]) -> pd.DataFrame:
    """Дивиденды на акцию, отнесённые к оценочной ex-дате (реестр − 2 торговых дня)."""
    div = pd.DataFrame(0.0, index=dates, columns=tickers)
    for f in sorted(RAW.glob("div/*.csv")):
        t = f.stem
        if t not in div.columns:
            continue
        df = pd.read_csv(f)
        if df.empty or "registryclosedate" not in df.columns:
            continue
        df = df[df.get("currencyid", "RUB").astype(str) == "RUB"]
        col = div.columns.get_loc(t)
        for _, row in df.iterrows():
            try:
                rec = pd.Timestamp(row["registryclosedate"])
                val = float(row["value"])
            except (ValueError, TypeError):
                continue
            if val <= 0:
                continue
            # позиция даты реестра в календаре торгов, затем шаг назад на нужное
            # число ТОРГОВЫХ дней (не календарных — иначе выходные съедают сдвиг)
            pos = dates.searchsorted(rec, side="left")
            pos -= _ex_shift_bdays(rec)
            if 0 <= pos < len(dates):
                div.iloc[pos, col] += val
    return div


#: Крупная выплата обязана быть видна в цене. Если дивиденд ≥ этого порога, а
#: цена на ex-дате не упала хотя бы на половину его величины — запись
#: несогласованна (в 2022 санкционные отмены дивидендов остались в ISS как
#: объявленные) и отбрасывается.
SUSPECT_YIELD = 0.08
SUSPECT_MIN_DROP_FRACTION = 0.5


def _drop_inconsistent_dividends(div: pd.DataFrame, close: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Отбрасывает крупные дивиденды, не подтверждённые падением цены.

    Обоснование направления: проверка может только УБРАТЬ начисление, то есть
    занизить доходность. Это безопасная сторона. Обратный ход — подбирать дату
    так, чтобы дивиденд «подошёл» к цене, — запрещён: он подгоняет данные под
    желаемый результат (см. комментарий к EX_SHIFT_ERAS).

    Порог по доходности нужен, чтобы не срабатывать на мелких выплатах, где
    дневной шум заведомо больше дивиденда.
    """
    div = div.copy()
    price_ret = close / close.shift(1) - 1.0
    dropped: list[str] = []
    nz = div.stack()
    nz = nz[nz != 0]
    for (dt, t), val in nz.items():
        px = close.at[dt, t]
        if not np.isfinite(px) or px <= 0:
            continue
        if val / px < SUSPECT_YIELD:
            continue
        r = price_ret.at[dt, t]
        if not np.isfinite(r):
            continue
        if r > -SUSPECT_MIN_DROP_FRACTION * (val / px):
            div.at[dt, t] = 0.0
            dropped.append(f"{t} {dt.date()} div={val:.2f} ({val/px:.1%}) "
                           f"но цена {r:+.2%} — падения нет")
    return div, dropped


def _load_bench(dates: pd.DatetimeIndex) -> pd.DataFrame:
    out = {}
    for sec in ("IMOEX", "MCFTR"):
        p = RAW / "idx" / f"{sec}.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p, parse_dates=["TRADEDATE"]).set_index("TRADEDATE").sort_index()
        out[sec] = pd.to_numeric(df["CLOSE"], errors="coerce")
    return pd.DataFrame(out).reindex(dates)


def build_panel(min_names_per_day: int = 20, use_cache: bool = True) -> Panel:
    if use_cache and CACHE.exists():
        return pd.read_pickle(CACHE)

    o, c, v = _load_equity_frames()

    # Только даты, когда торговалась хотя бы часть рынка. Это выкидывает
    # закрытие биржи 2022 и выходные, попавшие в выгрузку.
    traded_per_day = c.notna().sum(axis=1)
    good_dates = traded_per_day[traded_per_day >= min_names_per_day].index
    o, c, v = o.loc[good_dates], c.loc[good_dates], v.loc[good_dates]

    tradable = c.notna() & v.fillna(0).gt(0)
    div = _load_dividends(c.index, list(c.columns))
    div, dropped = _drop_inconsistent_dividends(div, c)
    if dropped:
        print(f"[panel] отброшено {len(dropped)} несогласованных дивидендов:")
        for d in dropped[:15]:
            print(f"        {d}")
        if len(dropped) > 15:
            print(f"        … ещё {len(dropped) - 15}")

    # Total return: на ex-дате цена падает на дивиденд, возвращаем его обратно.
    prev_c = c.shift(1)
    ret_cc = (c + div) / prev_c - 1.0
    # open→open: дивиденд относим к тому же дню, что и в close-версии
    prev_o = o.shift(1)
    ret_oo = (o + div) / prev_o - 1.0

    # Доходность бессмысленна там, где нет обеих цен
    ret_cc = ret_cc.where(c.notna() & prev_c.notna())
    ret_oo = ret_oo.where(o.notna() & prev_o.notna())

    panel = Panel(open=o, close=c, value=v, tradable=tradable, div=div,
                  ret_cc=ret_cc, ret_oo=ret_oo, bench=_load_bench(c.index))

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(panel, CACHE)
    return panel


def liquidity_mask(panel: Panel, lookback: int = 20,
                   min_median_value: float = 50_000_000.0) -> pd.DataFrame:
    """Маска ликвидности на КАЖДУЮ дату, посчитанная только по прошлым данным.

    Используется скользящая медиана оборота за `lookback` дней, сдвинутая на 1 день
    вперёд: на дату T доступна информация по T-1 включительно. Сдвиг обязателен —
    без него в отбор просачивается оборот сегодняшнего дня.
    """
    med = panel.value.rolling(lookback, min_periods=max(5, lookback // 2)).median()
    return (med.shift(1) >= min_median_value) & panel.tradable
