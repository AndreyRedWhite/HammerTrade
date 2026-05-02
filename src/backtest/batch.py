from itertools import product
from typing import Optional

import pandas as pd

from src.backtest.engine import run_backtest
from src.backtest.metrics import calculate_backtest_metrics


def run_batch(
    debug_df: pd.DataFrame,
    entry_modes=("breakout",),
    take_r_values=(1.0,),
    max_hold_bars_values=(30,),
    stop_buffer_points_values=(0.0,),
    slippage_points_values=(0.0,),
    slippage_ticks_values: Optional[list] = None,
    tick_size: Optional[float] = None,
    entry_horizon_bars: int = 3,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
    allow_overlap: bool = False,
    direction_filter: str = "all",
) -> pd.DataFrame:
    use_ticks = slippage_ticks_values is not None
    slip_values = slippage_ticks_values if use_ticks else slippage_points_values

    rows = []
    scenario_id = 0

    for entry_mode, take_r, max_hold, stop_buf, slip in product(
        entry_modes,
        take_r_values,
        max_hold_bars_values,
        stop_buffer_points_values,
        slip_values,
    ):
        scenario_id += 1

        if use_ticks:
            trades_df = run_backtest(
                debug_df=debug_df,
                entry_mode=entry_mode,
                entry_horizon_bars=entry_horizon_bars,
                max_hold_bars=max_hold,
                take_r=take_r,
                stop_buffer_points=stop_buf,
                point_value_rub=point_value_rub,
                commission_per_trade=commission_per_trade,
                contracts=contracts,
                allow_overlap=allow_overlap,
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
                debug_df=debug_df,
                entry_mode=entry_mode,
                entry_horizon_bars=entry_horizon_bars,
                max_hold_bars=max_hold,
                take_r=take_r,
                stop_buffer_points=stop_buf,
                point_value_rub=point_value_rub,
                commission_per_trade=commission_per_trade,
                contracts=contracts,
                allow_overlap=allow_overlap,
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
            "scenario_id": scenario_id,
            "entry_mode": entry_mode,
            "entry_horizon_bars": entry_horizon_bars,
            "take_r": take_r,
            "max_hold_bars": max_hold,
            "stop_buffer_points": stop_buf,
            **slip_row,
            "contracts": contracts,
            **m,
        })

    return pd.DataFrame(rows)
