from itertools import product
from typing import Optional

import pandas as pd

from src.backtest.engine import run_backtest
from src.backtest.metrics import calculate_backtest_metrics
from src.backtest.periods import assign_period

_METRICS_KEYS = [
    "closed_trades", "skipped_trades", "wins", "losses", "timeouts", "winrate",
    "gross_pnl_rub", "net_pnl_rub", "avg_net_pnl_rub", "median_net_pnl_rub",
    "profit_factor", "max_drawdown_rub", "max_drawdown_pct", "ending_equity_rub",
    "avg_bars_held", "buy_trades", "sell_trades", "buy_net_pnl_rub", "sell_net_pnl_rub",
]


def run_period_backtests(
    debug_df: pd.DataFrame,
    period: str = "week",
    entry_mode: str = "breakout",
    entry_horizon_bars: int = 3,
    max_hold_bars: int = 30,
    take_r: float = 1.0,
    stop_buffer_points: float = 0.0,
    slippage_points: float = 0.0,
    slippage_ticks: Optional[float] = None,
    tick_size: Optional[float] = None,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
    allow_overlap: bool = False,
    direction_filter: str = "all",
) -> tuple:
    df_with_periods = assign_period(debug_df, period)
    period_keys = sorted(df_with_periods["period_key"].unique())

    period_results = []
    all_trades = []

    for pk in period_keys:
        period_df = df_with_periods[df_with_periods["period_key"] == pk].copy()
        period_start = period_df["period_start"].iloc[0]
        period_end = period_df["period_end"].iloc[0]
        rows = len(period_df)
        signals = int(
            (period_df["is_signal"].astype(bool) &
             (period_df["fail_reason"].astype(str) == "pass")).sum()
        )

        trades_df = run_backtest(
            debug_df=period_df,
            entry_mode=entry_mode,
            entry_horizon_bars=entry_horizon_bars,
            max_hold_bars=max_hold_bars,
            take_r=take_r,
            stop_buffer_points=stop_buffer_points,
            point_value_rub=point_value_rub,
            commission_per_trade=commission_per_trade,
            contracts=contracts,
            allow_overlap=allow_overlap,
            slippage_points=slippage_points,
            slippage_ticks=slippage_ticks,
            tick_size=tick_size,
            direction_filter=direction_filter,
        )
        m = calculate_backtest_metrics(trades_df)

        if len(trades_df) > 0:
            t = trades_df.copy()
            t["period_key"] = pk
            all_trades.append(t)

        period_results.append({
            "period_key": pk,
            "period_start": period_start,
            "period_end": period_end,
            "rows": rows,
            "signals": signals,
            **{k: m[k] for k in _METRICS_KEYS},
        })

    period_results_df = pd.DataFrame(period_results)
    all_period_trades_df = (
        pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    )
    return period_results_df, all_period_trades_df


def run_period_grid_backtests(
    debug_df: pd.DataFrame,
    period: str,
    entry_modes: list,
    take_r_values: list,
    max_hold_bars_values: list,
    stop_buffer_points_values: list,
    slippage_points_values: list,
    slippage_ticks_values: Optional[list] = None,
    tick_size: Optional[float] = None,
    entry_horizon_bars: int = 3,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
    direction_filter: str = "all",
) -> pd.DataFrame:
    use_ticks = slippage_ticks_values is not None
    slip_values = slippage_ticks_values if use_ticks else slippage_points_values

    df_with_periods = assign_period(debug_df, period)
    period_keys = sorted(df_with_periods["period_key"].unique())

    # Pre-slice once
    period_slices = {
        pk: df_with_periods[df_with_periods["period_key"] == pk].copy()
        for pk in period_keys
    }

    rows = []
    scenario_id = 0

    for entry_mode, take_r, max_hold, stop_buf, slip in product(
        entry_modes, take_r_values, max_hold_bars_values,
        stop_buffer_points_values, slip_values,
    ):
        scenario_id += 1

        for pk, period_df in period_slices.items():
            period_start = period_df["period_start"].iloc[0]
            period_end = period_df["period_end"].iloc[0]
            period_rows = len(period_df)
            signals = int(
                (period_df["is_signal"].astype(bool) &
                 (period_df["fail_reason"].astype(str) == "pass")).sum()
            )

            if use_ticks:
                trades_df = run_backtest(
                    debug_df=period_df,
                    entry_mode=entry_mode,
                    entry_horizon_bars=entry_horizon_bars,
                    max_hold_bars=max_hold,
                    take_r=take_r,
                    stop_buffer_points=stop_buf,
                    point_value_rub=point_value_rub,
                    commission_per_trade=commission_per_trade,
                    contracts=contracts,
                    slippage_ticks=slip,
                    tick_size=tick_size,
                    direction_filter=direction_filter,
                )
                eff_slip = slip * tick_size if tick_size else 0.0
                slip_row = {
                    "slippage_points": 0.0,
                    "slippage_ticks": slip,
                    "effective_slippage_points": eff_slip,
                    "tick_size": tick_size,
                }
            else:
                trades_df = run_backtest(
                    debug_df=period_df,
                    entry_mode=entry_mode,
                    entry_horizon_bars=entry_horizon_bars,
                    max_hold_bars=max_hold,
                    take_r=take_r,
                    stop_buffer_points=stop_buf,
                    point_value_rub=point_value_rub,
                    commission_per_trade=commission_per_trade,
                    contracts=contracts,
                    slippage_points=slip,
                    direction_filter=direction_filter,
                )
                slip_row = {
                    "slippage_points": slip,
                    "slippage_ticks": None,
                    "effective_slippage_points": slip,
                    "tick_size": tick_size,
                }

            m = calculate_backtest_metrics(trades_df)

            rows.append({
                "period_key": pk,
                "period_start": period_start,
                "period_end": period_end,
                "scenario_id": scenario_id,
                "entry_mode": entry_mode,
                "entry_horizon_bars": entry_horizon_bars,
                "take_r": take_r,
                "max_hold_bars": max_hold,
                "stop_buffer_points": stop_buf,
                **slip_row,
                "contracts": contracts,
                "rows": period_rows,
                "total_signals": signals,
                **{k: m[k] for k in _METRICS_KEYS},
            })

    return pd.DataFrame(rows)
