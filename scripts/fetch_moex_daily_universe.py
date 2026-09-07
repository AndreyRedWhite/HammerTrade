"""MVP-D1: загрузка дневной истории акций MOEX с point-in-time составом универса.

Ключевое отличие от прошлых загрузчиков: состав универса берётся ПО ДАТЕ
(эндпоинт списка бумаг на конкретный торговый день), а не сегодняшний список
TQBR. Это включает делистингованные и остановленные бумаги в те периоды, когда
они торговались, и тем самым убирает survivorship bias — без этого любой
лонговый кросс-секционный сигнал покажет фантомную доходность.

Этапы (каждый резюмируемый — уже скачанное не перекачивается):
  1. Помесячные срезы состава TQBR      -> universe_monthly.csv
  2. Дневная история по каждой бумаге    -> eq/{SECID}.csv
  3. Дивиденды (доступны с ~2019)        -> div/{SECID}.csv
  4. Индексы IMOEX (price) и MCFTR (TR)  -> idx/{SECID}.csv

Usage:
    python scripts/fetch_moex_daily_universe.py                 # всё, с 2015
    python scripts/fetch_moex_daily_universe.py --from 2019-01-01
    python scripts/fetch_moex_daily_universe.py --stage universe # только этап 1
"""
from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

ISS = "https://iss.moex.com/iss"
BOARD = "history/engines/stock/markets/shares/boards/TQBR/securities"
IDX = "history/engines/stock/markets/index/securities"

OUT = Path("data/raw/moex_daily")
EQ_DIR = OUT / "eq"
DIV_DIR = OUT / "div"
IDX_DIR = OUT / "idx"

EQ_COLS = "TRADEDATE,SECID,OPEN,LOW,HIGH,CLOSE,VOLUME,VALUE,NUMTRADES"
SLEEP = 0.12
RETRIES = 4

# Бумага попадает в загрузку, если её месячный оборот хоть раз превышал порог.
# Порог намеренно низкий: отсекаем только заведомо неторгуемое, чтобы не создать
# отбор по успешности. Фильтр ликвидности на момент ребаланса применяется позже,
# в движке, по скользящему окну.
MIN_MONTHLY_VALUE_RUB = 10_000_000.0


def _get(url: str) -> dict:
    """Запрос к ISS с ретраями.

    Ловим широко: ISS на длинных прогонах роняет соединение
    (`RemoteDisconnected`, `ConnectionReset`), и это НЕ подклассы `URLError` —
    узкий except обрывал многочасовую загрузку на случайном месте.
    """
    last = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                return json.load(r)
        except (urllib.error.URLError, http.client.HTTPException, OSError,
                TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(min(30.0, 2.0 * (2 ** attempt)))  # 2,4,8,16,30…
    raise RuntimeError(f"ISS failed after {RETRIES} tries: {url}") from last


def _paged(url_base: str, block: str = "history") -> tuple[list[list], list[str] | None]:
    """ISS отдаёт по 100 строк; тянем до пустой страницы."""
    rows, cols, start = [], None, 0
    while True:
        d = _get(f"{url_base}&start={start}")
        blk = d.get(block, {})
        data = blk.get("data", [])
        if cols is None:
            cols = blk.get("columns")
        if not data:
            break
        rows.extend(data)
        start += len(data)
        time.sleep(SLEEP)
    return rows, cols


def _write_atomic(df: pd.DataFrame, path: Path) -> None:
    """Пишем через temp+rename: падение посреди записи иначе оставит обрезанный
    файл, который логика резюмирования примет за успешно скачанный."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(path)


def _month_ends(from_d: date, to_d: date) -> list[date]:
    """Последний календарный день каждого месяца в диапазоне."""
    out, cur = [], date(from_d.year, from_d.month, 1)
    while cur <= to_d:
        nxt = date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)
        out.append(min(nxt - timedelta(days=1), to_d))
        cur = nxt
    return out


def stage_universe(from_d: date, to_d: date, refresh: bool = False) -> pd.DataFrame:
    """Этап 1: помесячные срезы состава торгуемых бумаг (point-in-time)."""
    path = OUT / "universe_monthly.csv"
    if path.exists() and not refresh:
        print(f"[universe] cached: {path}")
        return pd.read_csv(path, parse_dates=["TRADEDATE"])

    frames = []
    for me in _month_ends(from_d, to_d):
        # Отступаем назад до дня с РЕАЛЬНЫМИ торгами: последний день месяца бывает
        # выходным, а в 2022 биржа стояла почти месяц (строки отдаются, но с
        # CLOSE=None и VALUE=0 — такой срез бесполезен для оценки ликвидности).
        got = None
        for back in range(0, 32):
            d = me - timedelta(days=back)
            rows, cols = _paged(
                f"{ISS}/{BOARD}.json?iss.meta=off&date={d.isoformat()}"
                f"&history.columns=TRADEDATE,SECID,CLOSE,VALUE,VOLUME")
            if not rows:
                continue
            cand = pd.DataFrame(rows, columns=cols)
            if pd.to_numeric(cand["VALUE"], errors="coerce").fillna(0).gt(0).any():
                got = cand
                break
        if got is None or got.empty:
            print(f"[universe] {me} — торгов не найдено в пределах 32 дней")
            continue
        frames.append(got)
        print(f"[universe] {me} -> {len(got)} бумаг", flush=True)

    df = pd.concat(frames, ignore_index=True)
    df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
    OUT.mkdir(parents=True, exist_ok=True)
    _write_atomic(df, path)
    print(f"[universe] сохранено {len(df)} строк, {df.SECID.nunique()} уникальных бумаг -> {path}")
    return df


def pick_tickers(universe: pd.DataFrame) -> list[str]:
    """Бумаги, когда-либо показавшие осмысленный месячный оборот."""
    u = universe.copy()
    u["VALUE"] = pd.to_numeric(u["VALUE"], errors="coerce").fillna(0.0)
    peak = u.groupby("SECID")["VALUE"].max()
    keep = sorted(peak[peak >= MIN_MONTHLY_VALUE_RUB].index.tolist())
    print(f"[pick] {len(keep)} из {u.SECID.nunique()} бумаг прошли порог "
          f"оборота {MIN_MONTHLY_VALUE_RUB:,.0f}₽")
    return keep


def stage_history(tickers: list[str], from_d: date, to_d: date) -> None:
    """Этап 2: полная дневная история по каждой бумаге."""
    EQ_DIR.mkdir(parents=True, exist_ok=True)
    todo = [t for t in tickers if not (EQ_DIR / f"{t}.csv").exists()]
    print(f"[history] к загрузке {len(todo)} из {len(tickers)} (остальные в кэше)")
    for i, t in enumerate(todo, 1):
        rows, cols = _paged(
            f"{ISS}/{BOARD}/{t}.json?iss.meta=off"
            f"&from={from_d.isoformat()}&till={to_d.isoformat()}"
            f"&history.columns={EQ_COLS}")
        df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=EQ_COLS.split(","))
        if not df.empty:
            df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
            df = df.drop_duplicates("TRADEDATE").sort_values("TRADEDATE")
        _write_atomic(df, EQ_DIR / f"{t}.csv")
        print(f"[history] {i}/{len(todo)} {t}: {len(df)} дней", flush=True)


def stage_dividends(tickers: list[str], refresh: bool = False,
                    max_age_days: int = 30) -> None:
    """Этап 3: дивиденды. ISS отдаёт примерно с 2019 — раньше данных нет.

    Дивидендный календарь — ЖИВОЙ ряд, а не снимок: компании объявляют новые
    выплаты постоянно. Раньше файл скачивался только если его нет
    (`if not ...exists()`), поэтому календарь навсегда застревал на дате первой
    загрузки. Локально это дало цены до июля 2026 против дивидендов до 2025 г. —
    то есть «total return» за 2026 фактически был price return, а любая проверка
    ex-date опиралась на календарь, в котором нужных дат просто нет.

    Теперь файл перекачивается, если он старше `max_age_days`, а `refresh`
    заставляет перекачать всё.
    """
    DIV_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cutoff = max_age_days * 86400

    def _stale(t: str) -> bool:
        p = DIV_DIR / f"{t}.csv"
        if not p.exists():
            return True
        if refresh:
            return True
        return (now - p.stat().st_mtime) > cutoff

    todo = [t for t in tickers if _stale(t)]
    fresh = len(tickers) - len(todo)
    print(f"[div] к загрузке {len(todo)} из {len(tickers)} "
          f"(свежих не старше {max_age_days} дн.: {fresh})")
    for i, t in enumerate(todo, 1):
        d = _get(f"{ISS}/securities/{t}/dividends.json?iss.meta=off")
        blk = d.get("dividends", {})
        df = pd.DataFrame(blk.get("data", []), columns=blk.get("columns"))
        _write_atomic(df, DIV_DIR / f"{t}.csv")
        if i % 25 == 0 or len(df):
            print(f"[div] {i}/{len(todo)} {t}: {len(df)} выплат", flush=True)
        time.sleep(SLEEP)


def stage_indices(from_d: date, to_d: date) -> None:
    """Этап 4: IMOEX (ценовой) и MCFTR (полной доходности) — бенчмарки."""
    IDX_DIR.mkdir(parents=True, exist_ok=True)
    for sec in ("IMOEX", "MCFTR"):
        p = IDX_DIR / f"{sec}.csv"
        if p.exists():
            print(f"[idx] cached: {sec}")
            continue
        rows, cols = _paged(
            f"{ISS}/{IDX}/{sec}.json?iss.meta=off"
            f"&from={from_d.isoformat()}&till={to_d.isoformat()}"
            f"&history.columns=TRADEDATE,SECID,OPEN,CLOSE")
        df = pd.DataFrame(rows, columns=cols)
        if not df.empty:
            df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
            df = df.drop_duplicates("TRADEDATE").sort_values("TRADEDATE")
        _write_atomic(df, p)
        print(f"[idx] {sec}: {len(df)} дней")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_date", default="2015-01-01")
    ap.add_argument("--to", dest="to_date", default=date.today().isoformat())
    ap.add_argument("--stage", default="all",
                    choices=["all", "universe", "history", "dividends", "indices"])
    ap.add_argument("--refresh-universe", action="store_true")
    ap.add_argument("--refresh-dividends", action="store_true",
                    help="Перекачать дивидендный календарь целиком, игнорируя возраст файлов")
    ap.add_argument("--dividend-max-age-days", type=int, default=30,
                    help="Файл дивидендов старше этого перекачивается автоматически")
    a = ap.parse_args()

    from_d = datetime.strptime(a.from_date, "%Y-%m-%d").date()
    to_d = datetime.strptime(a.to_date, "%Y-%m-%d").date()
    print(f"MOEX daily fetch {from_d} → {to_d}, stage={a.stage}")

    universe = stage_universe(from_d, to_d, a.refresh_universe)
    if a.stage == "universe":
        return
    tickers = pick_tickers(universe)
    (OUT / "tickers.txt").write_text("\n".join(tickers))

    if a.stage in ("all", "indices"):
        stage_indices(from_d, to_d)
    if a.stage in ("all", "history"):
        stage_history(tickers, from_d, to_d)
    if a.stage in ("all", "dividends"):
        stage_dividends(tickers, refresh=a.refresh_dividends,
                        max_age_days=a.dividend_max_age_days)
    print("\nГотово.")


if __name__ == "__main__":
    main()
