"""Liquid futures universe scanner — research tool, not a trading module."""
import warnings
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd


def fetch_available_futures(
    client,
    class_code: str = "SPBFUT",
) -> pd.DataFrame:
    """Return DataFrame of all futures for given class_code from T-Bank."""
    try:
        from t_tech.invest import InstrumentStatus
    except ImportError:
        from src.tbank.client import _SDK_INSTALL_HINT
        raise ImportError(_SDK_INSTALL_HINT)

    from src.tbank.money import quotation_to_float

    try:
        resp = client.instruments.futures(instrument_status=InstrumentStatus.INSTRUMENT_STATUS_ALL)
        futures = resp.instruments
    except Exception as e:
        raise RuntimeError(f"Failed to fetch futures list: {e}")

    rows = []
    for f in futures:
        if f.class_code.upper() != class_code.upper():
            continue

        def _sq(v):
            try:
                return quotation_to_float(v)
            except Exception:
                return None

        def _sm(v):
            try:
                from src.tbank.money import money_value_to_float
                return money_value_to_float(v)
            except Exception:
                return None

        def _date(v):
            if v is None:
                return None
            try:
                if hasattr(v, "ToDatetime"):
                    return v.ToDatetime().replace(tzinfo=timezone.utc)
                if hasattr(v, "tzinfo"):
                    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
                return v
            except Exception:
                return None

        mpi = _sq(getattr(f, "min_price_increment", None))
        mpia = _sm(getattr(f, "min_price_increment_amount", None))
        point_value_rub = None
        if mpi and mpia and mpi > 0:
            point_value_rub = mpia / mpi

        rows.append({
            "ticker": f.ticker,
            "class_code": f.class_code,
            "uid": f.uid,
            "name": f.name,
            "expiration_date": _date(getattr(f, "expiration_date", None)),
            "first_trade_date": _date(getattr(f, "first_trade_date", None)),
            "last_trade_date": _date(getattr(f, "last_trade_date", None)),
            "first_1min_candle_date": _date(getattr(f, "first_1min_candle_date", None)),
            "first_1day_candle_date": _date(getattr(f, "first_1day_candle_date", None)),
            "min_price_increment": mpi,
            "min_price_increment_amount": mpia,
            "point_value_rub": point_value_rub,
            "api_trade_available_flag": getattr(f, "api_trade_available_flag", None),
            "buy_available_flag": getattr(f, "buy_available_flag", None),
            "sell_available_flag": getattr(f, "sell_available_flag", None),
        })

    return pd.DataFrame(rows)


def filter_active_futures(
    futures_df: pd.DataFrame,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Keep only futures that overlap the research period and have 1m candle history."""
    if futures_df.empty:
        return futures_df

    df = futures_df.copy()
    now = datetime.now(timezone.utc)
    start_utc = _ensure_utc(start)
    end_utc = _ensure_utc(end)

    def _is_active(row) -> bool:
        exp = row.get("expiration_date") or row.get("last_trade_date")
        if exp is not None:
            exp = _ensure_utc(exp)
            if exp < start_utc:
                return False
        first_candle = row.get("first_1min_candle_date")
        if first_candle is not None:
            first_candle = _ensure_utc(first_candle)
            if first_candle > end_utc:
                return False
        return True

    mask = df.apply(_is_active, axis=1)
    return df[mask].reset_index(drop=True)


def estimate_futures_liquidity(
    client,
    futures_df: pd.DataFrame,
    start: datetime,
    end: datetime,
    timeframe: str = "1m",
    sample_days: int = 5,
) -> pd.DataFrame:
    """
    Estimate liquidity of each future by downloading a sample of candles.
    Returns futures_df with appended liquidity columns + activity_score.
    """
    from src.tbank.candles import fetch_historical_candles

    start_utc = _ensure_utc(start)
    end_utc = _ensure_utc(end)

    # Sample window: last sample_days before end (or whatever is available)
    sample_end = end_utc
    sample_start = max(start_utc, sample_end - timedelta(days=sample_days))

    total = len(futures_df)
    rows = []
    for i, (_, row) in enumerate(futures_df.iterrows(), 1):
        ticker = row["ticker"]
        uid = row.get("uid", "")
        liquidity = _empty_liquidity()
        print(f"  [{i}/{total}] {ticker}", end="\r", flush=True)
        try:
            candles_df = fetch_historical_candles(
                client=client,
                instrument_uid=uid,
                start=sample_start,
                end=sample_end,
                timeframe=timeframe,
            )
            if candles_df is not None and len(candles_df) > 0:
                liquidity = _calc_liquidity(candles_df)
        except Exception as e:
            warnings.warn(f"Could not load candles for {ticker}: {e}")

        rows.append({**row.to_dict(), **liquidity})
    print(f"  Done: {total} instruments scanned.    ")

    result = pd.DataFrame(rows)
    if "activity_score" in result.columns:
        result = result.sort_values("activity_score", ascending=False).reset_index(drop=True)
        result.insert(0, "rank", range(1, len(result) + 1))
    return result


def _calc_liquidity(candles_df: pd.DataFrame) -> dict:
    n = len(candles_df)
    non_zero_vol = int((candles_df["volume"] > 0).sum()) if "volume" in candles_df.columns else 0
    zero_range = int(((candles_df["high"] - candles_df["low"]) == 0).sum()) if "high" in candles_df.columns else 0
    total_vol = float(candles_df["volume"].sum()) if "volume" in candles_df.columns else 0.0
    avg_vol = float(candles_df["volume"].mean()) if "volume" in candles_df.columns else 0.0
    median_vol = float(candles_df["volume"].median()) if "volume" in candles_df.columns else 0.0
    avg_range = float((candles_df["high"] - candles_df["low"]).mean()) if "high" in candles_df.columns else 0.0
    median_range = float((candles_df["high"] - candles_df["low"]).median()) if "high" in candles_df.columns else 0.0
    activity_score = non_zero_vol * median_vol
    return {
        "candles_count": n,
        "non_zero_volume_candles": non_zero_vol,
        "zero_range_candles": zero_range,
        "total_volume": total_vol,
        "avg_volume_per_candle": round(avg_vol, 2),
        "median_volume_per_candle": round(median_vol, 2),
        "avg_range": round(avg_range, 4),
        "median_range": round(median_range, 4),
        "activity_score": round(activity_score, 2),
    }


def _empty_liquidity() -> dict:
    return {
        "candles_count": 0,
        "non_zero_volume_candles": 0,
        "zero_range_candles": 0,
        "total_volume": 0.0,
        "avg_volume_per_candle": 0.0,
        "median_volume_per_candle": 0.0,
        "avg_range": 0.0,
        "median_range": 0.0,
        "activity_score": 0.0,
    }


def generate_universe_report(
    df: pd.DataFrame,
    output_path: str,
    params: dict,
) -> None:
    from pathlib import Path

    lines = []
    lines.append("# Liquid Futures Universe Report")
    lines.append("")
    lines.append("## Parameters")
    lines.append("")
    lines.append("| Parameter | Value |")
    lines.append("|---|---|")
    for k, v in params.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    if df.empty:
        lines.append("No futures found.")
    else:
        display_cols = [
            "rank", "ticker", "name", "expiration_date", "point_value_rub",
            "candles_count", "total_volume", "median_volume_per_candle",
            "zero_range_candles", "activity_score",
        ]
        existing = [c for c in display_cols if c in df.columns]
        lines.append("## Top futures by activity_score")
        lines.append("")
        header = "| " + " | ".join(existing) + " |"
        separator = "| " + " | ".join(["---:" if c not in ("ticker", "name") else "---" for c in existing]) + " |"
        lines.append(header)
        lines.append(separator)
        for _, row in df.iterrows():
            values = []
            for c in existing:
                v = row.get(c, "")
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    values.append("")
                else:
                    values.append(str(v))
            lines.append("| " + " | ".join(values) + " |")
        lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("This is a rough liquidity scan based on historical candles.")
    lines.append("It does not guarantee live order book liquidity.")
    lines.append("")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")


def _ensure_utc(dt) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if hasattr(dt, "tzinfo") and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
