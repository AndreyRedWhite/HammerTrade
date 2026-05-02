import pandas as pd
import pytest

from src.backtest.stability import calculate_profit_concentration


def _trades(pnl_list):
    rows = []
    for i, pnl in enumerate(pnl_list):
        rows.append({
            "trade_id": i + 1,
            "status": "closed",
            "net_pnl_rub": pnl,
            "direction": "BUY",
            "exit_reason": "take" if pnl > 0 else "stop",
        })
    return pd.DataFrame(rows)


def _periods(pnl_list):
    rows = []
    for i, pnl in enumerate(pnl_list):
        rows.append({"period_key": f"W{i}", "net_pnl_rub": pnl})
    return pd.DataFrame(rows)


# --- Top 10% trades profit share ---

def test_top_10pct_trades_profit_share():
    # 10 profit trades: one big winner (100), rest small (10 each)
    pnl = [100] + [10] * 9  # total = 190
    t = _trades(pnl)
    p = _periods([190])
    m = calculate_profit_concentration(t, p)
    # top 10% = 1 trade = 100/190
    assert abs(m["top_10pct_trades_profit_share"] - 100 / 190) < 1e-6


def test_top_20pct_trades_profit_share():
    # 5 trades: 100, 50, 10, 10, 10 → total = 180
    pnl = [100, 50, 10, 10, 10]
    t = _trades(pnl)
    p = _periods([180])
    m = calculate_profit_concentration(t, p)
    # top 20% = 1 trade (round(5*0.2)=1) = 100/180
    assert abs(m["top_20pct_trades_profit_share"] - 100 / 180) < 1e-6


# --- Best trade profit share ---

def test_best_trade_profit_share():
    pnl = [100, 50, 25]
    t = _trades(pnl)
    p = _periods([175])
    m = calculate_profit_concentration(t, p)
    assert abs(m["best_trade_profit_share"] - 100 / 175) < 1e-6


# --- Period shares ---

def test_best_period_profit_share():
    t = _trades([100, 50])
    p = _periods([300, 100, 200])  # total positive = 600; best = 300
    m = calculate_profit_concentration(t, p)
    assert abs(m["best_period_profit_share"] - 300 / 600) < 1e-6


def test_top_2_periods_profit_share():
    t = _trades([100])
    p = _periods([300, 200, 100])  # total = 600; top 2 = 500
    m = calculate_profit_concentration(t, p)
    assert abs(m["top_2_periods_profit_share"] - 500 / 600) < 1e-6


# --- Zero profit edge case ---

def test_zero_profit_all_shares_zero():
    t = _trades([-10, -20, -5])
    p = _periods([-35])
    m = calculate_profit_concentration(t, p)
    assert m["top_10pct_trades_profit_share"] == 0.0
    assert m["top_20pct_trades_profit_share"] == 0.0
    assert m["best_trade_profit_share"] == 0.0
    assert m["best_period_profit_share"] == 0.0
    assert m["top_2_periods_profit_share"] == 0.0


def test_negative_period_excluded_from_concentration():
    t = _trades([100, 50])
    p = _periods([300, -100, 200])  # positive total = 500
    m = calculate_profit_concentration(t, p)
    assert abs(m["best_period_profit_share"] - 300 / 500) < 1e-6


# --- Mixed positive and negative trades ---

def test_only_profit_trades_counted():
    pnl = [100, -50, 200, -30]  # profit = [200, 100], total = 300
    t = _trades(pnl)
    p = _periods([220])
    m = calculate_profit_concentration(t, p)
    assert abs(m["best_trade_profit_share"] - 200 / 300) < 1e-6
