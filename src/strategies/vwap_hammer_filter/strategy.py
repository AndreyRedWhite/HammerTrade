"""VWAP Hammer Filter — re-filter existing hammer backtest trades.

NOT a standalone strategy. Takes existing hammer backtest trades and
re-evaluates which ones would have been taken under VWAP filter.

Filters:
  A (price_above_vwap): SELL only if close > VWAP at signal_time
  B (high_above_vwap): SELL only if signal_high > VWAP at signal_time
  C (close_above_vwap_05atr): SELL only if close > VWAP + 0.5 * ATR

Compares: baseline, filtered_A, filtered_B, filtered_C.
"""
from __future__ import annotations

import pandas as pd

from src.research.metrics import compute_metrics
from src.research.vwap import compute_session_vwap, compute_atr


def _to_msk_str(ts_str: str) -> str:
    """Convert a timestamp string to MSK for display."""
    try:
        ts = pd.Timestamp(ts_str)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return str(ts.tz_convert("Europe/Moscow"))
    except Exception:
        return ts_str


def run_vwap_hammer_filter(
    hammer_trades_csv: str,
    candles_csv: str,
    scenario_filter: str = "baseline",
    atr_window: int = 14,
) -> tuple[list[dict], list[dict]]:
    """Re-filter hammer trades with VWAP conditions and compute metrics.

    Args:
        hammer_trades_csv: Path to existing hammer trades CSV.
        candles_csv: Path to candles CSV (used to compute VWAP/ATR).
        scenario_filter: Filter in hammer CSV to use as source (default 'baseline').
        atr_window: ATR window for filter C.

    Returns:
        (filter_results, enriched_trades) where:
          - filter_results: list of dicts, one per filter variant with metrics
          - enriched_trades: all hammer trades enriched with VWAP/ATR columns + filter flags
    """
    # Load hammer trades
    trades_df = pd.read_csv(hammer_trades_csv)
    if "scenario_name" in trades_df.columns:
        trades_df = trades_df[trades_df["scenario_name"] == scenario_filter].copy()

    if trades_df.empty:
        return [], []

    # Load candles
    candles = pd.read_csv(candles_csv)
    if not pd.api.types.is_datetime64_any_dtype(candles["timestamp"]):
        candles["timestamp"] = pd.to_datetime(candles["timestamp"], utc=True)
    elif candles["timestamp"].dt.tz is None:
        candles["timestamp"] = candles["timestamp"].dt.tz_localize("UTC")

    candles = candles.sort_values("timestamp").reset_index(drop=True)

    # Compute VWAP and ATR on candles
    candles["_vwap"] = compute_session_vwap(candles)
    candles["_atr"] = compute_atr(candles, window=atr_window)

    # Index by timestamp for fast lookup
    candles_indexed = candles.set_index("timestamp")

    # Parse signal_time in trades
    if "signal_time" not in trades_df.columns:
        return [], []

    trades_df["_signal_ts"] = pd.to_datetime(trades_df["signal_time"], utc=True)

    def lookup_vwap_atr(signal_ts: pd.Timestamp) -> tuple[float | None, float | None]:
        """Find VWAP and ATR at the signal timestamp."""
        # Find the candle at or just before signal_ts
        before = candles[candles["timestamp"] <= signal_ts]
        if before.empty:
            return None, None
        row = before.iloc[-1]
        v = row["_vwap"]
        a = row["_atr"]
        return (float(v) if not pd.isna(v) else None, float(a) if not pd.isna(a) else None)

    # Enrich trades with VWAP/ATR
    vwap_vals = []
    atr_vals = []
    for _, row in trades_df.iterrows():
        v, a = lookup_vwap_atr(row["_signal_ts"])
        vwap_vals.append(v)
        atr_vals.append(a)

    trades_df["vwap_at_signal"] = vwap_vals
    trades_df["atr_at_signal"] = atr_vals

    # Apply filters
    def _safe_float(val, default: float = 0.0) -> float:
        """Convert to float, returning default on NaN/None."""
        if val is None:
            return default
        try:
            f = float(val)
            return default if (f != f) else f  # NaN check: NaN != NaN
        except (ValueError, TypeError):
            return default

    def make_trade_dict(row: pd.Series, filter_name: str) -> dict | None:
        """Build a trade dict from a hammer trade row. Returns None for invalid rows."""
        pnl_raw = row.get("net_pnl_rub", 0)
        pnl = _safe_float(pnl_raw)
        # Skip rows with NaN prices (corrupt data)
        entry_p = _safe_float(row.get("entry_price"), default=None)
        if entry_p is None:
            return None

        exit_r = str(row.get("exit_reason", ""))
        bars_raw = row.get("bars_held", 0)
        bars = int(bars_raw) if bars_raw is not None and str(bars_raw) != "nan" else 0
        date_str = str(row.get("signal_time", ""))[:10]
        return {
            "scenario": filter_name,
            "date": date_str,
            "entry_msk": _to_msk_str(str(row.get("entry_time", ""))),
            "exit_msk": _to_msk_str(str(row.get("exit_time", ""))),
            "entry_price": entry_p,
            "stop_price": _safe_float(row.get("stop_price", 0)),
            "take_price": _safe_float(row.get("take_price", 0)),
            "exit_price": _safe_float(row.get("exit_price", 0)),
            "exit_reason": exit_r,
            "pnl_rub": pnl,
            "pnl_points": _safe_float(row.get("gross_points", 0)),
            "bars_held": bars,
            "direction": "SHORT",
            "vwap_at_signal": row.get("vwap_at_signal"),
            "atr_at_signal": row.get("atr_at_signal"),
            "or_window": "N/A",
        }

    filter_configs = {
        "baseline": None,  # all trades
        "price_above_vwap": lambda r: (
            r["vwap_at_signal"] is not None
            and float(r.get("signal_close", r.get("entry_price", 0))) > r["vwap_at_signal"]
        ),
        "high_above_vwap": lambda r: (
            r["vwap_at_signal"] is not None
            and float(r.get("signal_high", r.get("entry_price", 0))) > r["vwap_at_signal"]
        ),
        "close_above_vwap_05atr": lambda r: (
            r["vwap_at_signal"] is not None
            and r["atr_at_signal"] is not None
            and float(r.get("signal_close", r.get("entry_price", 0)))
            > r["vwap_at_signal"] + 0.5 * r["atr_at_signal"]
        ),
    }

    filter_results = []
    enriched_trades: list[dict] = []

    for filter_name, predicate in filter_configs.items():
        if predicate is None:
            filtered = trades_df
        else:
            filtered = trades_df[trades_df.apply(predicate, axis=1)]

        trade_dicts = [
            d for _, row in filtered.iterrows()
            if (d := make_trade_dict(row, filter_name)) is not None
        ]
        if filter_name == "baseline":
            enriched_trades = trade_dicts  # baseline enriched trades

        metrics = compute_metrics(trade_dicts)
        filter_results.append(
            {
                "filter": filter_name,
                "trades_kept": len(trade_dicts),
                "trades_total": len(trades_df),
                "pct_kept": round(len(trade_dicts) / max(len(trades_df), 1), 4),
                **metrics,
            }
        )

    return filter_results, enriched_trades
