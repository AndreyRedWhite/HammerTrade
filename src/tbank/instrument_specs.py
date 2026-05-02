import os
import warnings
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

_SPECS_CSV = "data/instruments/futures_specs.csv"

_CSV_COLUMNS = [
    "ticker", "class_code", "uid", "figi", "name", "lot", "currency",
    "min_price_increment", "min_price_increment_amount", "point_value_rub",
    "initial_margin_on_buy", "initial_margin_on_sell",
    "expiration_date", "first_trade_date", "last_trade_date",
    "first_1min_candle_date", "first_1day_candle_date",
    "api_trade_available_flag", "buy_available_flag", "sell_available_flag",
    "updated_at",
]


@dataclass(frozen=True)
class FutureInstrumentSpec:
    ticker: str
    class_code: str
    uid: str
    figi: Optional[str]
    name: str
    lot: int
    currency: str
    min_price_increment: float
    min_price_increment_amount: Optional[float]
    point_value_rub: Optional[float]
    initial_margin_on_buy: Optional[float]
    initial_margin_on_sell: Optional[float]
    expiration_date: Optional[datetime]
    first_trade_date: Optional[datetime]
    last_trade_date: Optional[datetime]
    first_1min_candle_date: Optional[datetime]
    first_1day_candle_date: Optional[datetime]
    api_trade_available_flag: Optional[bool]
    buy_available_flag: Optional[bool]
    sell_available_flag: Optional[bool]


def _compute_point_value_rub(
    min_price_increment: Optional[float],
    min_price_increment_amount: Optional[float],
) -> Optional[float]:
    if min_price_increment_amount is None or min_price_increment is None:
        return None
    if min_price_increment == 0:
        return None
    return min_price_increment_amount / min_price_increment


def fetch_future_spec(
    client,
    ticker: str,
    class_code: str = "SPBFUT",
) -> FutureInstrumentSpec:
    try:
        from t_tech.invest import InstrumentIdType
    except ImportError:
        from src.tbank.client import _SDK_INSTALL_HINT
        raise ImportError(_SDK_INSTALL_HINT)

    from src.tbank.money import quotation_to_float, money_value_to_float

    # --- Find instrument ---
    try:
        resp = client.instruments.find_instrument(
            query=ticker,
            instrument_kind=None,
            api_trade_available_flag=None,
        )
        candidates = [
            i for i in resp.instruments
            if i.ticker.upper() == ticker.upper()
            and i.class_code.upper() == class_code.upper()
        ]
    except Exception as e:
        raise RuntimeError(f"Instrument search failed for '{ticker}': {e}")

    if not candidates:
        try:
            resp2 = client.instruments.find_instrument(query=ticker)
            hints = [f"{i.ticker} ({i.class_code})" for i in resp2.instruments[:5]]
        except Exception:
            hints = []
        hint_str = ", ".join(hints) if hints else "none found"
        raise ValueError(
            f"Instrument not found: ticker='{ticker}', class_code='{class_code}'.\n"
            f"Check ticker and class_code. Similar: {hint_str}"
        )

    instr = candidates[0]

    # --- Full futures details ---
    try:
        detail = client.instruments.future_by(
            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_UID,
            id=instr.uid,
        ).instrument
    except Exception:
        detail = instr

    def _sq(v):
        try:
            return quotation_to_float(v)
        except Exception:
            return None

    def _sm(v):
        try:
            return money_value_to_float(v)
        except Exception:
            return None

    def _date(v):
        if v is None:
            return None
        try:
            if hasattr(v, "ToDatetime"):
                return v.ToDatetime()
            return v
        except Exception:
            return None

    def _bool(v):
        if v is None:
            return None
        return bool(v)

    min_price_increment = _sq(getattr(detail, "min_price_increment", None))
    lot = getattr(detail, "lot", None) or getattr(instr, "lot", 1)
    currency = getattr(detail, "currency", None) or getattr(instr, "currency", "")

    # --- Futures margin for min_price_increment_amount + margins ---
    min_price_increment_amount = None
    initial_margin_on_buy = None
    initial_margin_on_sell = None

    figi = getattr(detail, "figi", None) or getattr(instr, "figi", None)
    uid = getattr(detail, "uid", None) or instr.uid

    try:
        margin = client.instruments.get_futures_margin(figi=figi)
        min_price_increment_amount = _sm(getattr(margin, "min_price_increment_amount", None))
        if min_price_increment_amount is None:
            min_price_increment_amount = _sq(getattr(margin, "min_price_increment_amount", None))
        initial_margin_on_buy = _sm(getattr(margin, "initial_margin_on_buy", None))
        initial_margin_on_sell = _sm(getattr(margin, "initial_margin_on_sell", None))
    except Exception as e:
        warnings.warn(
            f"Could not fetch futures margin for '{ticker}': {e}. "
            "point_value_rub will be None."
        )

    point_value_rub = _compute_point_value_rub(min_price_increment, min_price_increment_amount)
    if point_value_rub is None:
        warnings.warn(
            f"point_value_rub could not be computed for '{ticker}'. "
            "min_price_increment_amount may be unavailable. Use --fallback-point-value-rub."
        )

    return FutureInstrumentSpec(
        ticker=ticker,
        class_code=class_code,
        uid=uid,
        figi=figi,
        name=getattr(detail, "name", None) or getattr(instr, "name", ""),
        lot=int(lot) if lot is not None else 1,
        currency=str(currency) if currency else "",
        min_price_increment=min_price_increment or 0.0,
        min_price_increment_amount=min_price_increment_amount,
        point_value_rub=point_value_rub,
        initial_margin_on_buy=initial_margin_on_buy,
        initial_margin_on_sell=initial_margin_on_sell,
        expiration_date=_date(getattr(detail, "expiration_date", None)),
        first_trade_date=_date(getattr(detail, "first_trade_date", None)),
        last_trade_date=_date(getattr(detail, "last_trade_date", None)),
        first_1min_candle_date=_date(getattr(detail, "first_1min_candle_date", None)),
        first_1day_candle_date=_date(getattr(detail, "first_1day_candle_date", None)),
        api_trade_available_flag=_bool(getattr(detail, "api_trade_available_flag", None)),
        buy_available_flag=_bool(getattr(detail, "buy_available_flag", None)),
        sell_available_flag=_bool(getattr(detail, "sell_available_flag", None)),
    )


def load_specs_cache(path: str = _SPECS_CSV) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=_CSV_COLUMNS)
    try:
        return pd.read_csv(path, dtype=str)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=_CSV_COLUMNS)


def upsert_future_spec(
    spec: FutureInstrumentSpec,
    path: str = _SPECS_CSV,
) -> None:
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)

    df = load_specs_cache(path)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    record = {
        "ticker": spec.ticker,
        "class_code": spec.class_code,
        "uid": spec.uid,
        "figi": spec.figi,
        "name": spec.name,
        "lot": spec.lot,
        "currency": spec.currency,
        "min_price_increment": spec.min_price_increment,
        "min_price_increment_amount": spec.min_price_increment_amount,
        "point_value_rub": spec.point_value_rub,
        "initial_margin_on_buy": spec.initial_margin_on_buy,
        "initial_margin_on_sell": spec.initial_margin_on_sell,
        "expiration_date": str(spec.expiration_date) if spec.expiration_date else None,
        "first_trade_date": str(spec.first_trade_date) if spec.first_trade_date else None,
        "last_trade_date": str(spec.last_trade_date) if spec.last_trade_date else None,
        "first_1min_candle_date": str(spec.first_1min_candle_date) if spec.first_1min_candle_date else None,
        "first_1day_candle_date": str(spec.first_1day_candle_date) if spec.first_1day_candle_date else None,
        "api_trade_available_flag": spec.api_trade_available_flag,
        "buy_available_flag": spec.buy_available_flag,
        "sell_available_flag": spec.sell_available_flag,
        "updated_at": now_str,
    }

    mask = (df["ticker"] == str(spec.ticker)) & (df["class_code"] == str(spec.class_code))
    if mask.any():
        for col in _CSV_COLUMNS:
            if col in record:
                df.loc[mask, col] = str(record[col]) if record[col] is not None else ""
    else:
        new_row = {col: (str(record.get(col, "")) if record.get(col) is not None else "") for col in _CSV_COLUMNS}
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    df.to_csv(path, index=False)


def get_cached_future_spec(
    ticker: str,
    class_code: str = "SPBFUT",
    path: str = _SPECS_CSV,
) -> Optional[FutureInstrumentSpec]:
    df = load_specs_cache(path)
    if df.empty:
        return None

    mask = (df["ticker"].str.upper() == ticker.upper()) & (df["class_code"].str.upper() == class_code.upper())
    matches = df[mask]
    if matches.empty:
        return None

    row = matches.iloc[0]

    def _opt_float(v) -> Optional[float]:
        try:
            s = str(v).strip()
            if not s or s.lower() in ("nan", "none", ""):
                return None
            return float(s)
        except Exception:
            return None

    def _opt_bool(v) -> Optional[bool]:
        s = str(v).strip().lower()
        if s in ("true", "1"):
            return True
        if s in ("false", "0"):
            return False
        return None

    def _opt_str(v) -> Optional[str]:
        s = str(v).strip()
        return s if s and s.lower() not in ("nan", "none") else None

    min_price_increment = _opt_float(row.get("min_price_increment"))
    min_price_increment_amount = _opt_float(row.get("min_price_increment_amount"))
    point_value_rub = _opt_float(row.get("point_value_rub"))

    return FutureInstrumentSpec(
        ticker=str(row["ticker"]),
        class_code=str(row["class_code"]),
        uid=str(row.get("uid", "")),
        figi=_opt_str(row.get("figi")),
        name=str(row.get("name", "")),
        lot=int(float(row.get("lot", 1) or 1)),
        currency=str(row.get("currency", "")),
        min_price_increment=min_price_increment or 0.0,
        min_price_increment_amount=min_price_increment_amount,
        point_value_rub=point_value_rub,
        initial_margin_on_buy=_opt_float(row.get("initial_margin_on_buy")),
        initial_margin_on_sell=_opt_float(row.get("initial_margin_on_sell")),
        expiration_date=None,
        first_trade_date=None,
        last_trade_date=None,
        first_1min_candle_date=None,
        first_1day_candle_date=None,
        api_trade_available_flag=_opt_bool(row.get("api_trade_available_flag")),
        buy_available_flag=_opt_bool(row.get("buy_available_flag")),
        sell_available_flag=_opt_bool(row.get("sell_available_flag")),
    )
