"""Research: funding-carry на вечных фьючерсах MOEX (перп vs квартальник).

Конструкция: SHORT перп (собирает положительный фандинг) + LONG фронт-квартальник
(хедж; платит контанго-декей). Net carry = фандинг − implied-ставка квартальника.
Обратная конструкция симметрична при отрицательном фандинге.

Данные: MOEX ISS (публичные, дневные) — SWAPRATE (фандинг, в пунктах цены/день)
и SETTLEPRICE перпа; SETTLEPRICE квартальников для непрерывного фронта.
Знак фандинга MOEX: положительный → списывается у лонгов, начисляется шортам.

Издержки: комиссия T-Bank 0.025%/нога; полный цикл 2 ноги × (вход+выход) = 10 бп
+ спреды. Carry копится ежедневно, издержки амортизируются длиной холда.

Usage:
    python scripts/research_perp_funding.py                 # все 4 актива
    python scripts/research_perp_funding.py --assets CNY    # один
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

ISS = "https://iss.moex.com/iss/history/engines/futures/markets/forts/securities"
CACHE = Path("data/raw/moex_iss")
OUT = Path("out")
REPORTS = Path("reports")

# перп → (буква квартальной серии, годы контрактов)
ASSETS = {
    "CNY": {"perp": "CNYRUBF", "series": "CR", "years": range(2022, 2028)},
    "USD": {"perp": "USDRUBF", "series": "Si", "years": range(2022, 2028)},
    "GOLD": {"perp": "GLDRUBF", "series": "GL", "years": range(2023, 2028)},
    "IMOEX": {"perp": "IMOEXF", "series": "MM", "years": range(2024, 2028)},
}
MONTH_CODES = {"H": 3, "M": 6, "U": 9, "Z": 12}
COMMISSION_LEG = 0.00025  # T-Bank фьючерсы, низший тариф


def _fetch_history(secid: str, refresh: bool = False) -> pd.DataFrame:
    """Полная дневная история контракта с ISS (с пагинацией), с кэшем на диске."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE / f"{secid}_daily.csv"
    if cache_file.exists() and not refresh:
        return pd.read_csv(cache_file, parse_dates=["TRADEDATE"])
    rows, start = [], 0
    while True:
        url = (f"{ISS}/{secid}.json?iss.meta=off&start={start}"
               f"&history.columns=TRADEDATE,SECID,CLOSE,SETTLEPRICE,SWAPRATE,VOLUME,OPENPOSITION")
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.load(r)
        cols, data = d["history"]["columns"], d["history"]["data"]
        if not data:
            break
        rows.extend(data)
        start += len(data)
        time.sleep(0.15)
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
        df = df.drop_duplicates("TRADEDATE").sort_values("TRADEDATE")
    df.to_csv(cache_file, index=False)
    return df


def _quarterly_tickers(series: str, years) -> list[tuple[str, datetime]]:
    """Все тикеры серии с примерной датой экспирации (3-й четверг месяца)."""
    out = []
    for y in years:
        for code, month in MONTH_CODES.items():
            out.append((f"{series}{code}{y % 10}", datetime(y, month, 15)))
    return out


def build_front(series: str, years, min_days_to_exp: int = 7) -> pd.DataFrame:
    """Непрерывный ряд фронт-квартальника: на каждую дату — ближайший контракт
    с экспирацией > min_days_to_exp (без склейки цен — базис считается за день)."""
    frames = []
    for ticker, approx_exp in _quarterly_tickers(series, years):
        df = _fetch_history(ticker)
        if df.empty or "SETTLEPRICE" not in df:
            continue
        real_exp = df["TRADEDATE"].max()  # последний торговый день ≈ экспирация
        df = df.assign(EXPIRY=real_exp)
        frames.append(df[["TRADEDATE", "SECID", "SETTLEPRICE", "VOLUME", "EXPIRY"]])
    if not frames:
        return pd.DataFrame()
    allq = pd.concat(frames)
    allq["DTE"] = (allq["EXPIRY"] - allq["TRADEDATE"]).dt.days
    allq = allq[allq["DTE"] > min_days_to_exp]
    # фронт = минимальный DTE на дату
    front = allq.sort_values(["TRADEDATE", "DTE"]).groupby("TRADEDATE").first().reset_index()
    return front.rename(columns={"SETTLEPRICE": "Q_SETTLE", "SECID": "Q_SECID",
                                 "VOLUME": "Q_VOLUME"})


def analyze(asset: str, cfg: dict) -> dict:
    perp = _fetch_history(cfg["perp"])
    if perp.empty:
        return {"asset": asset, "error": "no perp data"}
    perp = perp.rename(columns={"SETTLEPRICE": "P_SETTLE", "SWAPRATE": "FUNDING"})
    front = build_front(cfg["series"], cfg["years"])
    m = perp[["TRADEDATE", "P_SETTLE", "FUNDING", "VOLUME"]].merge(
        front[["TRADEDATE", "Q_SECID", "Q_SETTLE", "DTE"]], on="TRADEDATE", how="inner")
    m = m.dropna(subset=["P_SETTLE", "Q_SETTLE", "FUNDING"])
    if m.empty:
        return {"asset": asset, "error": "no overlap"}

    # масштаб котировки: Si за 1000 USD vs USDRUBF за 1 USD → нормализуем Q
    # к единицам перпа по медианному отношению, округлённому до степени 10
    import math
    ratio = (m["Q_SETTLE"] / m["P_SETTLE"]).median()
    scale = 10 ** round(math.log10(ratio))
    if scale != 1:
        m["Q_SETTLE"] = m["Q_SETTLE"] / scale

    # фандинг в бп/день от цены перпа; short perp ПОЛУЧАЕТ положительный фандинг
    m["funding_bp"] = m["FUNDING"] / m["P_SETTLE"] * 1e4
    # implied-ставка квартальника (годовых) из базиса к перпу (перп ≈ спот)
    m["basis_bp"] = (m["Q_SETTLE"] / m["P_SETTLE"] - 1) * 1e4
    m["q_rate_ann"] = (m["Q_SETTLE"] / m["P_SETTLE"] - 1) * 365 / m["DTE"]
    # дневной carry конструкции short-perp+long-Q, бп/день:
    # + funding_bp (получаем)  − базис-декей (basis_bp / DTE, платим)
    m["carry_bp_day"] = m["funding_bp"] - m["basis_bp"] / m["DTE"]

    yearly = m.set_index("TRADEDATE")["carry_bp_day"].resample("YE").agg(["mean", "count"])
    return {
        "asset": asset, "perp": cfg["perp"], "n_days": len(m),
        "period": f"{m['TRADEDATE'].min().date()} → {m['TRADEDATE'].max().date()}",
        "funding_bp_mean": m["funding_bp"].mean(),
        "funding_bp_std": m["funding_bp"].std(),
        "funding_pos_share": (m["funding_bp"] > 0).mean(),
        "funding_ann_pct": m["funding_bp"].mean() * 365 / 100,
        "q_rate_ann_pct": m["q_rate_ann"].mean() * 100,
        "carry_bp_day_mean": m["carry_bp_day"].mean(),
        "carry_ann_pct": m["carry_bp_day"].mean() * 365 / 100,
        "carry_pos_share": (m["carry_bp_day"] > 0).mean(),
        "carry_bp_day_std": m["carry_bp_day"].std(),
        "scale": scale,
        "breakeven_days": round(4 * COMMISSION_LEG * 1e4 / m["carry_bp_day"].mean(), 1)
                          if m["carry_bp_day"].mean() > 0 else None,
        "yearly": {str(i.year): (round(float(r["mean"]), 2), int(r["count"]))
                   for i, r in yearly.iterrows()},
        "df": m,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--assets", nargs="*", default=list(ASSETS),
                   help=f"подмножество из {list(ASSETS)}")
    args = p.parse_args()

    OUT.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    lines = [f"# Perp funding-carry research — {stamp}",
             "",
             "Конструкция: SHORT перп + LONG фронт-квартальник. "
             "carry_bp_day = funding − basis/DTE (бп/день, до издержек). "
             f"Полный цикл издержек ≈ {4 * COMMISSION_LEG * 1e4:.0f} бп комиссии + спреды.",
             ""]
    for asset in args.assets:
        r = analyze(asset, ASSETS[asset])
        if "error" in r:
            lines.append(f"## {asset}: ERROR {r['error']}")
            continue
        df = r.pop("df")
        df.to_csv(OUT / f"research_perp_funding_{asset}_{stamp}.csv", index=False)
        lines += [
            f"## {asset} ({r['perp']}) — {r['period']}, {r['n_days']} дней",
            "",
            f"- Фандинг: **{r['funding_bp_mean']:+.2f} бп/день** "
            f"(σ {r['funding_bp_std']:.2f}, >0 в {r['funding_pos_share']:.0%} дней) "
            f"≈ **{r['funding_ann_pct']:+.1f}% годовых** собирает шорт перпа",
            f"- Implied-ставка квартальника: {r['q_rate_ann_pct']:+.1f}% годовых",
            f"- **Net carry (short perp + long Q): {r['carry_bp_day_mean']:+.2f} бп/день "
            f"≈ {r['carry_ann_pct']:+.1f}% годовых** (>0 в {r['carry_pos_share']:.0%} дней, "
            f"σ {r['carry_bp_day_std']:.2f} бп/день)",
            f"- Окупаемость полного цикла комиссий (10 бп): "
            f"{r['breakeven_days']} дн. холда" if r["breakeven_days"] else
            "- Carry ≤ 0 — издержки не окупаются",
            f"- По годам (бп/день, n): {r['yearly']} (scale Q/P = {r['scale']})",
            "",
        ]
        print(lines[-6])
        print(lines[-4])
    report = REPORTS / f"research_perp_funding_{stamp}.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nreport: {report}")


if __name__ == "__main__":
    main()
