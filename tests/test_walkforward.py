import pandas as pd
import pytest

from src.backtest.walkforward import run_period_backtests

REQUIRED_PERIOD_COLS = {
    "period_key", "period_start", "period_end", "rows", "signals",
    "closed_trades", "skipped_trades", "wins", "losses", "timeouts", "winrate",
    "gross_pnl_rub", "net_pnl_rub", "avg_net_pnl_rub", "median_net_pnl_rub",
    "profit_factor", "max_drawdown_rub", "max_drawdown_pct", "ending_equity_rub",
    "avg_bars_held", "buy_trades", "sell_trades", "buy_net_pnl_rub", "sell_net_pnl_rub",
}


def _make_multiweek_df():
    """Signal candles in weeks 14 and 15 of 2026 (UTC midday = same MSK day)."""
    rows = []
    # Week 14: April 1-5 UTC midday
    # Week 15: April 6-10 UTC midday
    for day_offset in range(10):
        base = pd.Timestamp(f"2026-04-{1 + day_offset:02d} 10:00:00+00:00")
        # Signal bar
        rows.append({
            "timestamp": base,
            "instrument": "SiM6", "timeframe": "1m",
            "open": 100.0, "high": 102.0, "low": 95.0, "close": 100.0,
            "volume": 100,
            "is_signal": True, "fail_reason": "pass", "direction_candidate": "BUY",
        })
        # Non-signal bars in the same day (including one that hits take)
        for j in range(1, 6):
            rows.append({
                "timestamp": base + pd.Timedelta(minutes=j),
                "instrument": "SiM6", "timeframe": "1m",
                "open": 100.0,
                "high": 106.0 if j == 2 else 101.0,
                "low": 99.0, "close": 105.0,
                "volume": 100,
                "is_signal": False, "fail_reason": "range", "direction_candidate": "BUY",
            })
    return pd.DataFrame(rows)


# --- 1. Data is split into multiple periods ---

def test_period_count_week():
    df = _make_multiweek_df()
    period_results, _ = run_period_backtests(df, period="week")
    # April 1-5 = week 14, April 6-10 = week 15
    assert len(period_results) == 2


def test_period_count_day():
    df = _make_multiweek_df()
    period_results, _ = run_period_backtests(df, period="day")
    # 10 distinct days
    assert len(period_results) == 10


# --- 2. Required columns in period_results ---

def test_period_results_required_columns():
    df = _make_multiweek_df()
    period_results, _ = run_period_backtests(df, period="week")
    missing = REQUIRED_PERIOD_COLS - set(period_results.columns)
    assert not missing, f"Missing columns: {missing}"


# --- 3. all_period_trades has period_key ---

def test_all_trades_has_period_key():
    df = _make_multiweek_df()
    _, all_trades = run_period_backtests(df, period="week")
    assert "period_key" in all_trades.columns


def test_all_trades_period_keys_match():
    df = _make_multiweek_df()
    period_results, all_trades = run_period_backtests(df, period="week")
    trade_keys = set(all_trades["period_key"].unique())
    result_keys = set(period_results["period_key"])
    assert trade_keys.issubset(result_keys)


# --- 4. Period without signals doesn't crash ---

def test_period_no_signals_ok():
    # Week 14 has signals, week 15 has none
    rows = []
    for day_offset in range(5):
        base = pd.Timestamp(f"2026-04-{1 + day_offset:02d} 10:00:00+00:00")
        rows.append({
            "timestamp": base,
            "instrument": "SiM6", "timeframe": "1m",
            "open": 100.0, "high": 102.0, "low": 95.0, "close": 100.0,
            "volume": 100,
            "is_signal": day_offset == 0,  # signal only on first day (week 14)
            "fail_reason": "pass" if day_offset == 0 else "range",
            "direction_candidate": "BUY",
        })
        rows.append({
            "timestamp": base + pd.Timedelta(minutes=2),
            "instrument": "SiM6", "timeframe": "1m",
            "open": 100.0, "high": 106.0, "low": 99.0, "close": 105.0,
            "volume": 100,
            "is_signal": False, "fail_reason": "range", "direction_candidate": "BUY",
        })
    for day_offset in range(5, 10):
        base = pd.Timestamp(f"2026-04-{1 + day_offset:02d} 10:00:00+00:00")
        rows.append({
            "timestamp": base,
            "instrument": "SiM6", "timeframe": "1m",
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
            "volume": 100,
            "is_signal": False, "fail_reason": "range", "direction_candidate": "BUY",
        })
    df = pd.DataFrame(rows)
    period_results, _ = run_period_backtests(df, period="week")
    assert len(period_results) == 2
    # Week 15 has no signals
    w15 = period_results[period_results["period_key"] == "2026-W15"]
    assert w15["signals"].iloc[0] == 0
    assert w15["closed_trades"].iloc[0] == 0


# --- 5. Trades don't cross period boundary ---

def test_trades_not_crossing_period_boundary():
    # Signal at end of week 14; the exit would normally be in week 15,
    # but since the period slice only has week 14 data, it's end_of_data or timeout.
    rows = []
    # One signal on Friday April 4, 15:00 UTC
    base = pd.Timestamp("2026-04-04 15:00:00+00:00")
    rows.append({
        "timestamp": base,
        "instrument": "SiM6", "timeframe": "1m",
        "open": 100.0, "high": 102.0, "low": 95.0, "close": 100.0,
        "volume": 100,
        "is_signal": True, "fail_reason": "pass", "direction_candidate": "BUY",
    })
    # Next bar still in same minute (won't hit take for small take_r)
    rows.append({
        "timestamp": base + pd.Timedelta(minutes=1),
        "instrument": "SiM6", "timeframe": "1m",
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        "volume": 100,
        "is_signal": False, "fail_reason": "range", "direction_candidate": "BUY",
    })
    # Week 15 bar (would be the take bar if not isolated)
    rows.append({
        "timestamp": pd.Timestamp("2026-04-06 10:00:00+00:00"),
        "instrument": "SiM6", "timeframe": "1m",
        "open": 100.0, "high": 106.0, "low": 99.0, "close": 105.0,
        "volume": 100,
        "is_signal": False, "fail_reason": "range", "direction_candidate": "BUY",
    })
    df = pd.DataFrame(rows)
    period_results, all_trades = run_period_backtests(df, period="week", take_r=1.0, max_hold_bars=30)

    w14_trades = all_trades[all_trades["period_key"] == "2026-W14"]
    if len(w14_trades) > 0:
        closed = w14_trades[w14_trades["status"] == "closed"]
        # Exit must be timeout or end_of_data, NOT take (take bar was in week 15)
        assert not (closed["exit_reason"] == "take").any(), \
            "Trade crossed period boundary — should be end_of_data or timeout"
