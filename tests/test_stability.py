import pandas as pd
import pytest

from src.backtest.stability import calculate_period_stability


def _df(pnl, buy_pnl=None, sell_pnl=None, drawdown=None):
    n = len(pnl)
    if buy_pnl is None:
        buy_pnl = [p / 2 for p in pnl]
    if sell_pnl is None:
        sell_pnl = [p / 2 for p in pnl]
    if drawdown is None:
        drawdown = [abs(p) * 0.3 if p < 0 else 0.0 for p in pnl]
    rows = []
    for i in range(n):
        rows.append({
            "period_key": f"2026-W{14 + i:02d}",
            "net_pnl_rub": pnl[i],
            "buy_net_pnl_rub": buy_pnl[i],
            "sell_net_pnl_rub": sell_pnl[i],
            "max_drawdown_rub": drawdown[i],
        })
    return pd.DataFrame(rows)


def test_profitable_losing_flat():
    df = _df([100, -50, 0, 200])
    m = calculate_period_stability(df)
    assert m["profitable_periods"] == 2
    assert m["losing_periods"] == 1
    assert m["flat_periods"] == 1


def test_profitable_periods_pct():
    df = _df([100, -50, 200, 80])
    m = calculate_period_stability(df)
    assert abs(m["profitable_periods_pct"] - 0.75) < 1e-9


def test_period_profit_factor_normal():
    # positive = 300, negative abs = 50 → pf = 6.0
    df = _df([100, -50, 200])
    m = calculate_period_stability(df)
    assert abs(m["period_profit_factor"] - 6.0) < 1e-6


def test_period_profit_factor_inf():
    df = _df([100, 50])
    m = calculate_period_stability(df)
    assert m["period_profit_factor"] == float("inf")


def test_period_profit_factor_zero():
    df = _df([0, 0])
    m = calculate_period_stability(df)
    assert m["period_profit_factor"] == 0.0


def test_total_net_pnl():
    df = _df([100, -30, 50])
    m = calculate_period_stability(df)
    assert abs(m["total_net_pnl_rub"] - 120.0) < 1e-6


def test_periods_total():
    df = _df([10, 20, 30, 40])
    m = calculate_period_stability(df)
    assert m["periods_total"] == 4


def test_buy_sell_profitable_periods():
    buy = [100, -20, 50]
    sell = [10, 30, -5]
    df = _df([110, 10, 45], buy_pnl=buy, sell_pnl=sell)
    m = calculate_period_stability(df)
    assert m["buy_profitable_periods"] == 2
    assert m["sell_profitable_periods"] == 2


def test_buy_sell_total_pnl():
    buy = [60, 40, -10]
    sell = [40, -30, 20]
    df = _df([100, 10, 10], buy_pnl=buy, sell_pnl=sell)
    m = calculate_period_stability(df)
    assert abs(m["buy_total_net_pnl_rub"] - 90.0) < 1e-6
    assert abs(m["sell_total_net_pnl_rub"] - 30.0) < 1e-6


def test_empty_df():
    df = pd.DataFrame(columns=["period_key", "net_pnl_rub",
                                "buy_net_pnl_rub", "sell_net_pnl_rub", "max_drawdown_rub"])
    m = calculate_period_stability(df)
    assert m["periods_total"] == 0
    assert m["profitable_periods"] == 0
    assert m["period_profit_factor"] == 0.0


def test_max_period_drawdown():
    df = _df([100, -50, 80], drawdown=[10.0, 60.0, 5.0])
    m = calculate_period_stability(df)
    assert abs(m["max_period_drawdown_rub"] - 60.0) < 1e-6
