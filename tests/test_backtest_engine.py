import pandas as pd
import pytest

from src.backtest.engine import run_backtest


def _make_df(rows):
    """Build a minimal debug DataFrame with required columns."""
    records = []
    for i, r in enumerate(rows):
        records.append({
            "timestamp": pd.Timestamp(f"2026-04-01 10:{i:02d}:00"),
            "instrument": "SiM6",
            "timeframe": "1m",
            "open": r.get("open", 100.0),
            "high": r.get("high", 101.0),
            "low": r.get("low", 99.0),
            "close": r.get("close", 100.0),
            "volume": 100,
            "is_signal": r.get("is_signal", False),
            "fail_reason": r.get("fail_reason", "filter"),
            "direction_candidate": r.get("direction", "BUY"),
        })
    return pd.DataFrame(records)


# --- 1. BUY take-profit ---

def test_buy_take_profit():
    df = _make_df([
        # signal bar: BUY, close=100, low=95 (stop), high used for breakout ignored in close mode
        {"is_signal": True, "fail_reason": "pass", "direction": "BUY",
         "open": 99, "high": 101, "low": 95, "close": 100},
        # entry bar (close mode entry_price=100, stop=95, risk=5, take=105)
        # next bar hits take: high=106
        {"open": 100, "high": 106, "low": 99, "close": 102},
    ])
    result = run_backtest(df, entry_mode="close", take_r=1.0)
    trade = result[result["status"] == "closed"].iloc[0]
    assert trade["exit_reason"] == "take"
    assert trade["net_pnl_rub"] > 0


# --- 2. BUY stop-loss ---

def test_buy_stop_loss():
    df = _make_df([
        {"is_signal": True, "fail_reason": "pass", "direction": "BUY",
         "open": 99, "high": 101, "low": 95, "close": 100},
        # next bar hits stop: low=94
        {"open": 100, "high": 100, "low": 94, "close": 96},
    ])
    result = run_backtest(df, entry_mode="close", take_r=1.0)
    trade = result[result["status"] == "closed"].iloc[0]
    assert trade["exit_reason"] == "stop"
    assert trade["net_pnl_rub"] < 0


# --- 3. SELL take-profit ---

def test_sell_take_profit():
    df = _make_df([
        # SELL: entry_price=close=100, stop=high+buffer=105, risk=5, take=95
        {"is_signal": True, "fail_reason": "pass", "direction": "SELL",
         "open": 101, "high": 105, "low": 99, "close": 100},
        # next bar hits take: low=94
        {"open": 100, "high": 100, "low": 94, "close": 97},
    ])
    result = run_backtest(df, entry_mode="close", take_r=1.0)
    trade = result[result["status"] == "closed"].iloc[0]
    assert trade["exit_reason"] == "take"
    assert trade["net_pnl_rub"] > 0


# --- 4. SELL stop-loss ---

def test_sell_stop_loss():
    df = _make_df([
        {"is_signal": True, "fail_reason": "pass", "direction": "SELL",
         "open": 101, "high": 105, "low": 99, "close": 100},
        # next bar hits stop: high=106
        {"open": 100, "high": 106, "low": 100, "close": 104},
    ])
    result = run_backtest(df, entry_mode="close", take_r=1.0)
    trade = result[result["status"] == "closed"].iloc[0]
    assert trade["exit_reason"] == "stop"
    assert trade["net_pnl_rub"] < 0


# --- 5. Same-bar stop and take (conservative = stop) ---

def test_same_bar_stop_and_take():
    df = _make_df([
        # BUY: entry=close=100, stop=95, take=105
        {"is_signal": True, "fail_reason": "pass", "direction": "BUY",
         "open": 99, "high": 101, "low": 95, "close": 100},
        # both stop (low=94) and take (high=106) hit in same bar
        {"open": 100, "high": 106, "low": 94, "close": 100},
    ])
    result = run_backtest(df, entry_mode="close", take_r=1.0)
    trade = result[result["status"] == "closed"].iloc[0]
    assert trade["exit_reason"] == "stop_same_bar"
    assert trade["net_pnl_rub"] < 0


# --- 6. Breakout no entry ---

def test_breakout_no_entry():
    # entry_trigger = signal high = 101; next bars never reach 101
    df = _make_df([
        {"is_signal": True, "fail_reason": "pass", "direction": "BUY",
         "open": 99, "high": 101, "low": 95, "close": 100},
        {"open": 98, "high": 100, "low": 97, "close": 99},
        {"open": 98, "high": 100, "low": 97, "close": 99},
        {"open": 98, "high": 100, "low": 97, "close": 99},
    ])
    result = run_backtest(df, entry_mode="breakout", entry_horizon_bars=3)
    row = result.iloc[0]
    assert row["status"] == "skipped_no_entry"


# --- 7. Invalid risk ---

def test_invalid_risk():
    # BUY: entry_price=close=100, stop = low = 101 (above entry) -> risk <= 0
    df = _make_df([
        {"is_signal": True, "fail_reason": "pass", "direction": "BUY",
         "open": 100, "high": 102, "low": 101, "close": 100},
        {"open": 100, "high": 101, "low": 99, "close": 100},
    ])
    result = run_backtest(df, entry_mode="close", take_r=1.0)
    row = result.iloc[0]
    assert row["status"] == "skipped_invalid_risk"


# --- 8. No overlap ---

def test_no_overlap():
    # Two BUY signals close together; second signal bar falls inside first trade's hold window
    df = _make_df([
        # signal 1 at index 0: entry=close=100, stop=95, take=105
        {"is_signal": True, "fail_reason": "pass", "direction": "BUY",
         "open": 99, "high": 101, "low": 95, "close": 100},
        # signal 2 at index 1 — still inside trade 1's window
        {"is_signal": True, "fail_reason": "pass", "direction": "BUY",
         "open": 100, "high": 102, "low": 98, "close": 101},
        # trade 1 exits here via take: high=106
        {"open": 101, "high": 106, "low": 100, "close": 104},
        {"open": 104, "high": 107, "low": 103, "close": 106},
    ])
    result = run_backtest(df, entry_mode="close", take_r=1.0, allow_overlap=False)
    statuses = result["status"].tolist()
    assert "closed" in statuses
    assert "skipped_overlap" in statuses
