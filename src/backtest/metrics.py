import pandas as pd


def calculate_backtest_metrics(trades_df: pd.DataFrame) -> dict:
    closed = trades_df[trades_df["status"] == "closed"].copy()
    skipped = trades_df[trades_df["status"] != "closed"]

    wins = closed[closed["net_pnl_rub"] > 0]
    losses = closed[closed["net_pnl_rub"] < 0]
    timeouts = closed[closed["exit_reason"] == "timeout"]

    gross_profit = wins["net_pnl_rub"].sum() if len(wins) else 0.0
    gross_loss = losses["net_pnl_rub"].sum() if len(losses) else 0.0

    if gross_profit > 0 and gross_loss == 0:
        profit_factor = float("inf")
    elif gross_profit == 0 and gross_loss == 0:
        profit_factor = 0.0
    else:
        profit_factor = gross_profit / abs(gross_loss)

    buy_closed = closed[closed["direction"] == "BUY"]
    sell_closed = closed[closed["direction"] == "SELL"]

    max_dd_rub, max_dd_pct, ending_equity, min_equity, max_equity = _calc_drawdown(closed)

    return {
        "total_signals": len(trades_df),
        "closed_trades": len(closed),
        "skipped_trades": len(skipped),
        "wins": len(wins),
        "losses": len(losses),
        "timeouts": len(timeouts),
        "winrate": len(wins) / len(closed) if len(closed) > 0 else 0.0,
        "gross_pnl_rub": closed["gross_pnl_rub"].sum() if len(closed) else 0.0,
        "net_pnl_rub": closed["net_pnl_rub"].sum() if len(closed) else 0.0,
        "avg_net_pnl_rub": closed["net_pnl_rub"].mean() if len(closed) else 0.0,
        "median_net_pnl_rub": closed["net_pnl_rub"].median() if len(closed) else 0.0,
        "profit_factor": profit_factor,
        "max_win_rub": wins["net_pnl_rub"].max() if len(wins) else 0.0,
        "max_loss_rub": losses["net_pnl_rub"].min() if len(losses) else 0.0,
        "avg_bars_held": closed["bars_held"].mean() if len(closed) else 0.0,
        "buy_trades": len(buy_closed),
        "sell_trades": len(sell_closed),
        "buy_net_pnl_rub": buy_closed["net_pnl_rub"].sum() if len(buy_closed) else 0.0,
        "sell_net_pnl_rub": sell_closed["net_pnl_rub"].sum() if len(sell_closed) else 0.0,
        "max_drawdown_rub": max_dd_rub,
        "max_drawdown_pct": max_dd_pct,
        "ending_equity_rub": ending_equity,
        "min_equity_rub": min_equity,
        "max_equity_rub": max_equity,
    }


def _calc_drawdown(closed_df: pd.DataFrame):
    if len(closed_df) == 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    equity = closed_df["net_pnl_rub"].reset_index(drop=True).cumsum()
    peak = equity.cummax()
    drawdown = peak - equity

    max_dd_rub = float(drawdown.max())
    dd_idx = int(drawdown.idxmax())
    peak_at_max_dd = float(peak.iloc[dd_idx])
    max_dd_pct = (max_dd_rub / peak_at_max_dd) if peak_at_max_dd > 0 else 0.0

    return (
        max_dd_rub,
        max_dd_pct,
        float(equity.iloc[-1]),
        float(equity.min()),
        float(equity.max()),
    )
