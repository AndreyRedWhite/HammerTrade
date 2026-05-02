import os
import warnings

import pandas as pd

INSTRUMENTS_CSV = "data/instruments/moex_futures.csv"
INSTRUMENTS_COLUMNS = [
    "ticker", "class_code", "uid", "figi", "name",
    "lot", "min_price_increment", "expiration_date",
    "first_1min_candle_date", "first_1day_candle_date",
]


def resolve_instrument(
    client,
    ticker: str,
    class_code: str = "SPBFUT",
) -> dict:
    try:
        from t_tech.invest import InstrumentIdType
    except ImportError:
        from src.tbank.client import _SDK_INSTALL_HINT
        raise ImportError(_SDK_INSTALL_HINT)

    # Search by ticker
    try:
        resp = client.instruments.find_instrument(
            query=ticker,
            instrument_kind=None,
            api_trade_available_flag=None,
        )
        candidates = [
            i for i in resp.instruments
            if i.ticker.upper() == ticker.upper() and i.class_code.upper() == class_code.upper()
        ]
    except Exception as e:
        raise RuntimeError(f"Instrument search failed: {e}")

    if not candidates:
        # Try broader search to show hints
        try:
            resp2 = client.instruments.find_instrument(query=ticker)
            hints = [f"{i.ticker} ({i.class_code})" for i in resp2.instruments[:5]]
        except Exception:
            hints = []
        hint_str = ", ".join(hints) if hints else "none found"
        raise ValueError(
            f"Instrument not found: ticker='{ticker}', class_code='{class_code}'.\n"
            f"Similar instruments: {hint_str}"
        )

    instr = candidates[0]

    # Fetch full details for futures
    try:
        detail = client.instruments.future_by(
            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_UID,
            id=instr.uid,
        ).instrument
    except Exception:
        detail = instr

    def _safe_float(v):
        try:
            from src.tbank.money import quotation_to_float
            return quotation_to_float(v)
        except Exception:
            return None

    def _safe_date(v):
        if v is None:
            return None
        try:
            # v is already a datetime.datetime from t_tech SDK
            return v.date().isoformat()
        except Exception:
            try:
                return str(v)
            except Exception:
                return None

    record = {
        "ticker": ticker,
        "class_code": class_code,
        "uid": instr.uid,
        "figi": instr.figi,
        "name": instr.name,
        "lot": getattr(detail, "lot", None),
        "min_price_increment": _safe_float(getattr(detail, "min_price_increment", None)),
        "expiration_date": _safe_date(getattr(detail, "expiration_date", None)),
        "first_1min_candle_date": _safe_date(getattr(detail, "first_1min_candle_date", None)),
        "first_1day_candle_date": _safe_date(getattr(detail, "first_1day_candle_date", None)),
    }

    _save_to_catalog(record)
    return record


def _save_to_catalog(record: dict) -> None:
    os.makedirs(os.path.dirname(INSTRUMENTS_CSV), exist_ok=True)

    if os.path.exists(INSTRUMENTS_CSV):
        df = pd.read_csv(INSTRUMENTS_CSV)
    else:
        df = pd.DataFrame(columns=INSTRUMENTS_COLUMNS)

    mask = (df["ticker"] == record["ticker"]) & (df["class_code"] == record["class_code"])
    if mask.any():
        for col in INSTRUMENTS_COLUMNS:
            if col in record:
                df.loc[mask, col] = record[col]
    else:
        df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)

    df.to_csv(INSTRUMENTS_CSV, index=False)
