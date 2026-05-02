import pandas as pd


def calculate_period_stability(period_results_df: pd.DataFrame) -> dict:
    df = period_results_df
    n = len(df)

    if n == 0:
        return {
            "periods_total": 0, "profitable_periods": 0, "losing_periods": 0,
            "flat_periods": 0, "profitable_periods_pct": 0.0,
            "avg_period_net_pnl_rub": 0.0, "median_period_net_pnl_rub": 0.0,
            "best_period_net_pnl_rub": 0.0, "worst_period_net_pnl_rub": 0.0,
            "std_period_net_pnl_rub": 0.0, "total_net_pnl_rub": 0.0,
            "max_period_drawdown_rub": 0.0, "period_profit_factor": 0.0,
            "buy_total_net_pnl_rub": 0.0, "sell_total_net_pnl_rub": 0.0,
            "buy_profitable_periods": 0, "sell_profitable_periods": 0,
        }

    profitable = int((df["net_pnl_rub"] > 0).sum())
    losing = int((df["net_pnl_rub"] < 0).sum())
    flat = int((df["net_pnl_rub"] == 0).sum())

    pos_sum = float(df[df["net_pnl_rub"] > 0]["net_pnl_rub"].sum())
    neg_sum = float(df[df["net_pnl_rub"] < 0]["net_pnl_rub"].sum())

    if pos_sum > 0 and neg_sum == 0:
        period_pf = float("inf")
    elif pos_sum == 0 and neg_sum == 0:
        period_pf = 0.0
    else:
        period_pf = pos_sum / abs(neg_sum)

    buy_profitable = int((df["buy_net_pnl_rub"] > 0).sum()) if "buy_net_pnl_rub" in df.columns else 0
    sell_profitable = int((df["sell_net_pnl_rub"] > 0).sum()) if "sell_net_pnl_rub" in df.columns else 0

    return {
        "periods_total": n,
        "profitable_periods": profitable,
        "losing_periods": losing,
        "flat_periods": flat,
        "profitable_periods_pct": profitable / n,
        "avg_period_net_pnl_rub": float(df["net_pnl_rub"].mean()),
        "median_period_net_pnl_rub": float(df["net_pnl_rub"].median()),
        "best_period_net_pnl_rub": float(df["net_pnl_rub"].max()),
        "worst_period_net_pnl_rub": float(df["net_pnl_rub"].min()),
        "std_period_net_pnl_rub": float(df["net_pnl_rub"].std()) if n > 1 else 0.0,
        "total_net_pnl_rub": float(df["net_pnl_rub"].sum()),
        "max_period_drawdown_rub": float(df["max_drawdown_rub"].max()) if "max_drawdown_rub" in df.columns else 0.0,
        "period_profit_factor": period_pf,
        "buy_total_net_pnl_rub": float(df["buy_net_pnl_rub"].sum()) if "buy_net_pnl_rub" in df.columns else 0.0,
        "sell_total_net_pnl_rub": float(df["sell_net_pnl_rub"].sum()) if "sell_net_pnl_rub" in df.columns else 0.0,
        "buy_profitable_periods": buy_profitable,
        "sell_profitable_periods": sell_profitable,
    }


def calculate_profit_concentration(trades_df: pd.DataFrame, period_results_df: pd.DataFrame) -> dict:
    _zero = {
        "top_10pct_trades_profit_share": 0.0,
        "top_20pct_trades_profit_share": 0.0,
        "best_trade_profit_share": 0.0,
        "best_period_profit_share": 0.0,
        "top_2_periods_profit_share": 0.0,
    }

    # --- Trade concentration ---
    if len(trades_df) > 0 and "status" in trades_df.columns:
        closed = trades_df[trades_df["status"] == "closed"]
    else:
        closed = trades_df

    if len(closed) == 0 or "net_pnl_rub" not in closed.columns:
        return _zero

    profit_trades = (
        closed[closed["net_pnl_rub"] > 0]["net_pnl_rub"]
        .sort_values(ascending=False)
        .reset_index(drop=True)
    )
    total_trade_profit = float(profit_trades.sum())

    if total_trade_profit <= 0:
        result = dict(_zero)
    else:
        n = len(profit_trades)
        top10_n = max(1, round(n * 0.1))
        top20_n = max(1, round(n * 0.2))
        result = {
            "top_10pct_trades_profit_share": float(profit_trades.iloc[:top10_n].sum() / total_trade_profit),
            "top_20pct_trades_profit_share": float(profit_trades.iloc[:top20_n].sum() / total_trade_profit),
            "best_trade_profit_share": float(profit_trades.iloc[0] / total_trade_profit),
            "best_period_profit_share": 0.0,
            "top_2_periods_profit_share": 0.0,
        }

    # --- Period concentration ---
    if len(period_results_df) == 0 or "net_pnl_rub" not in period_results_df.columns:
        return result

    pos_periods = (
        period_results_df[period_results_df["net_pnl_rub"] > 0]["net_pnl_rub"]
        .sort_values(ascending=False)
        .reset_index(drop=True)
    )
    total_period_profit = float(pos_periods.sum())

    if total_period_profit > 0:
        result["best_period_profit_share"] = float(pos_periods.iloc[0] / total_period_profit)
        result["top_2_periods_profit_share"] = float(pos_periods.iloc[:2].sum() / total_period_profit)

    return result
