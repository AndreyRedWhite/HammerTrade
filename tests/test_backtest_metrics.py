import pandas as pd
import pytest

from src.backtest.metrics import calculate_backtest_metrics


def _trades(*rows):
    cols = [
        "trade_id", "instrument", "timeframe", "direction",
        "signal_time", "entry_time", "exit_time",
        "signal_open", "signal_high", "signal_low", "signal_close",
        "entry_price", "stop_price", "take_price", "exit_price",
        "status", "exit_reason",
        "risk_points", "gross_points", "gross_pnl_rub", "commission_rub",
        "net_pnl_rub", "bars_held",
    ]
    return pd.DataFrame(rows, columns=cols)


def _closed(trade_id, direction, net_pnl_rub, exit_reason="take", bars_held=5):
    gross = net_pnl_rub + 0.05
    return {
        "trade_id": trade_id, "instrument": "SiM6", "timeframe": "1m",
        "direction": direction,
        "signal_time": pd.Timestamp("2026-04-01 10:00:00"),
        "entry_time": pd.Timestamp("2026-04-01 10:01:00"),
        "exit_time": pd.Timestamp("2026-04-01 10:06:00"),
        "signal_open": 100, "signal_high": 101, "signal_low": 95, "signal_close": 100,
        "entry_price": 100, "stop_price": 95, "take_price": 105, "exit_price": 105,
        "status": "closed", "exit_reason": exit_reason,
        "risk_points": 5, "gross_points": gross / 10, "gross_pnl_rub": gross,
        "commission_rub": 0.05, "net_pnl_rub": net_pnl_rub, "bars_held": bars_held,
    }


def _skipped(trade_id, status="skipped_no_entry"):
    return {
        "trade_id": trade_id, "instrument": "SiM6", "timeframe": "1m",
        "direction": "BUY",
        "signal_time": pd.Timestamp("2026-04-01 10:00:00"),
        "entry_time": None, "exit_time": None,
        "signal_open": 100, "signal_high": 101, "signal_low": 95, "signal_close": 100,
        "entry_price": None, "stop_price": None, "take_price": None, "exit_price": None,
        "status": status, "exit_reason": "none",
        "risk_points": None, "gross_points": None, "gross_pnl_rub": None,
        "commission_rub": None, "net_pnl_rub": None, "bars_held": None,
    }


def test_total_signals():
    df = _trades(_closed(1, "BUY", 10), _closed(2, "SELL", -5), _skipped(3))
    m = calculate_backtest_metrics(df)
    assert m["total_signals"] == 3


def test_closed_trades():
    df = _trades(_closed(1, "BUY", 10), _skipped(2))
    m = calculate_backtest_metrics(df)
    assert m["closed_trades"] == 1


def test_skipped_trades():
    df = _trades(_closed(1, "BUY", 10), _skipped(2), _skipped(3))
    m = calculate_backtest_metrics(df)
    assert m["skipped_trades"] == 2


def test_wins_losses():
    df = _trades(_closed(1, "BUY", 50), _closed(2, "BUY", -20), _closed(3, "SELL", 30))
    m = calculate_backtest_metrics(df)
    assert m["wins"] == 2
    assert m["losses"] == 1


def test_winrate():
    df = _trades(_closed(1, "BUY", 50), _closed(2, "BUY", -20))
    m = calculate_backtest_metrics(df)
    assert abs(m["winrate"] - 0.5) < 1e-9


def test_net_pnl_rub():
    df = _trades(_closed(1, "BUY", 50), _closed(2, "SELL", -20))
    m = calculate_backtest_metrics(df)
    assert abs(m["net_pnl_rub"] - 30.0) < 1e-6


def test_profit_factor_normal():
    df = _trades(_closed(1, "BUY", 50), _closed(2, "BUY", -20))
    m = calculate_backtest_metrics(df)
    assert abs(m["profit_factor"] - 50.0 / 20.0) < 1e-6


def test_profit_factor_inf():
    df = _trades(_closed(1, "BUY", 50))
    m = calculate_backtest_metrics(df)
    assert m["profit_factor"] == float("inf")


def test_profit_factor_zero_when_no_trades():
    df = _trades(_skipped(1))
    m = calculate_backtest_metrics(df)
    assert m["profit_factor"] == 0.0


def test_buy_sell_breakdown():
    df = _trades(
        _closed(1, "BUY", 40),
        _closed(2, "BUY", 10),
        _closed(3, "SELL", -15),
    )
    m = calculate_backtest_metrics(df)
    assert m["buy_trades"] == 2
    assert m["sell_trades"] == 1
    assert abs(m["buy_net_pnl_rub"] - 50.0) < 1e-6
    assert abs(m["sell_net_pnl_rub"] - (-15.0)) < 1e-6


def test_skipped_not_in_pnl():
    df = _trades(_closed(1, "BUY", 100), _skipped(2), _skipped(3))
    m = calculate_backtest_metrics(df)
    assert abs(m["net_pnl_rub"] - 100.0) < 1e-6
    assert m["skipped_trades"] == 2
