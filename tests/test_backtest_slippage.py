import pandas as pd

from src.backtest.engine import run_backtest


def _make_df(rows):
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


def _buy_take_df():
    # BUY: entry=close=100, stop=95, risk=5, take=105; row 1 hits take (high=106)
    return _make_df([
        {"is_signal": True, "fail_reason": "pass", "direction": "BUY",
         "open": 99, "high": 102, "low": 95, "close": 100},
        {"open": 102, "high": 106, "low": 100, "close": 105},
    ])


def _sell_take_df():
    # SELL: entry=close=100, stop=105, risk=5, take=95; row 1 hits take (low=94)
    return _make_df([
        {"is_signal": True, "fail_reason": "pass", "direction": "SELL",
         "open": 101, "high": 105, "low": 99, "close": 100},
        {"open": 100, "high": 100, "low": 94, "close": 97},
    ])


# --- 1. BUY slippage worsens result ---

def test_buy_slippage_worsens_result():
    df = _buy_take_df()
    no_slip = run_backtest(df, entry_mode="close", take_r=1.0, slippage_points=0)
    with_slip = run_backtest(df, entry_mode="close", take_r=1.0, slippage_points=1)
    pnl_no = no_slip.iloc[0]["net_pnl_rub"]
    pnl_slip = with_slip.iloc[0]["net_pnl_rub"]
    assert pnl_slip < pnl_no


# --- 2. SELL slippage worsens result ---

def test_sell_slippage_worsens_result():
    df = _sell_take_df()
    no_slip = run_backtest(df, entry_mode="close", take_r=1.0, slippage_points=0)
    with_slip = run_backtest(df, entry_mode="close", take_r=1.0, slippage_points=1)
    pnl_no = no_slip.iloc[0]["net_pnl_rub"]
    pnl_slip = with_slip.iloc[0]["net_pnl_rub"]
    assert pnl_slip < pnl_no


# --- 3. Slippage of 1 pt reduces PnL by exactly 20 RUB (2 * 1 * 10) ---

def test_buy_slippage_impact_20_rub():
    df = _buy_take_df()
    no_slip = run_backtest(df, entry_mode="close", take_r=1.0,
                           slippage_points=0, point_value_rub=10)
    with_slip = run_backtest(df, entry_mode="close", take_r=1.0,
                              slippage_points=1, point_value_rub=10)
    diff = no_slip.iloc[0]["net_pnl_rub"] - with_slip.iloc[0]["net_pnl_rub"]
    assert abs(diff - 20.0) < 1e-6


def test_sell_slippage_impact_20_rub():
    df = _sell_take_df()
    no_slip = run_backtest(df, entry_mode="close", take_r=1.0,
                           slippage_points=0, point_value_rub=10)
    with_slip = run_backtest(df, entry_mode="close", take_r=1.0,
                              slippage_points=1, point_value_rub=10)
    diff = no_slip.iloc[0]["net_pnl_rub"] - with_slip.iloc[0]["net_pnl_rub"]
    assert abs(diff - 20.0) < 1e-6


# --- 4. Raw and adjusted prices are stored correctly ---

def test_entry_exit_raw_stored():
    df = _buy_take_df()
    result = run_backtest(df, entry_mode="close", take_r=1.0, slippage_points=2)
    row = result.iloc[0]
    assert row["entry_price_raw"] == 100.0
    assert row["entry_price"] == 102.0          # raw + slippage
    assert row["exit_price_raw"] == 105.0       # take trigger
    assert row["exit_price"] == 103.0           # raw - slippage
    assert row["slippage_points"] == 2.0
