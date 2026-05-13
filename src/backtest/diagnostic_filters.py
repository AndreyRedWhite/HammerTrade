"""Diagnostic filter layer for backtest.

Pre-filters signals by MIN_REWARD, MIN_RR, time windows, and entry
confirmation. Wraps run_backtest() without modifying the engine.

Notes on MIN_RR:
  In breakout mode with no slippage, expected_rr = take_r for all signals
  (reward = risk * take_r, so rr = take_r always). Therefore min_rr <= take_r
  never filters any signal. This is a design property, not a bug — it equals
  take_r at the signal-geometry level. Slippage-adjusted rr would differ, but
  the backtest engine stores risk_points based on raw (un-slipped) prices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from src.backtest.engine import run_backtest
from src.backtest.metrics import calculate_backtest_metrics

_MSK = ZoneInfo("Europe/Moscow")


@dataclass
class FilterConfig:
    scenario_name: str = "baseline"
    direction: str = "SELL"
    min_reward_points: float = 0.0
    min_rr: float = 0.0
    time_filter_name: str = "all_hours"
    exclude_hours_msk: list = field(default_factory=list)
    include_hours_msk: Optional[list] = None  # None = all hours allowed
    max_hold_bars: Optional[int] = None        # None = use caller's default
    entry_confirmation: str = "baseline"       # baseline | next_candle_direction | breakout_confirmation
    min_trades_required: int = 30


@dataclass
class ScenarioResult:
    scenario_id: int
    scenario_name: str
    filter_config: FilterConfig
    # Signal counts
    n_original_signals: int = 0
    n_after_filters: int = 0
    n_filtered_signals: int = 0
    skip_rate_pct: float = 0.0
    # Backtest metrics
    trades: int = 0
    wins: int = 0
    losses: int = 0
    winrate_pct: float = 0.0
    gross_profit_rub: float = 0.0
    gross_loss_rub: float = 0.0
    net_pnl_rub: float = 0.0
    profit_factor: float = 0.0
    expectancy_rub: float = 0.0
    avg_trade_rub: float = 0.0
    median_trade_rub: float = 0.0
    best_trade_rub: float = 0.0
    worst_trade_rub: float = 0.0
    max_drawdown_rub: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_risk_points: float = 0.0
    avg_reward_points: float = 0.0
    avg_rr: float = 0.0
    avg_bars_held: float = 0.0
    take_count: int = 0
    stop_count: int = 0
    timeout_count: int = 0
    # Period stability (daily)
    periods_count: int = 0
    profitable_periods_count: int = 0
    profitable_periods_pct: float = 0.0
    worst_period_pnl: float = 0.0
    best_period_pnl: float = 0.0
    avg_period_pnl: float = 0.0
    # Flags
    is_low_sample: bool = False
    warnings: list = field(default_factory=list)
    risk_adjusted_score: float = 0.0

    def to_dict(self) -> dict:
        fc = self.filter_config
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "min_reward_points": fc.min_reward_points,
            "min_rr": fc.min_rr,
            "time_filter_name": fc.time_filter_name,
            "exclude_hours_msk": str(fc.exclude_hours_msk),
            "include_hours_msk": str(fc.include_hours_msk),
            "max_hold_bars": fc.max_hold_bars,
            "entry_confirmation": fc.entry_confirmation,
            "n_original_signals": self.n_original_signals,
            "n_after_filters": self.n_after_filters,
            "n_filtered_signals": self.n_filtered_signals,
            "skip_rate_pct": self.skip_rate_pct,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "winrate_pct": self.winrate_pct,
            "gross_profit_rub": self.gross_profit_rub,
            "gross_loss_rub": self.gross_loss_rub,
            "net_pnl_rub": self.net_pnl_rub,
            "profit_factor": self.profit_factor,
            "expectancy_rub": self.expectancy_rub,
            "avg_trade_rub": self.avg_trade_rub,
            "median_trade_rub": self.median_trade_rub,
            "best_trade_rub": self.best_trade_rub,
            "worst_trade_rub": self.worst_trade_rub,
            "max_drawdown_rub": self.max_drawdown_rub,
            "max_drawdown_pct": self.max_drawdown_pct,
            "avg_risk_points": self.avg_risk_points,
            "avg_reward_points": self.avg_reward_points,
            "avg_rr": self.avg_rr,
            "avg_bars_held": self.avg_bars_held,
            "take_count": self.take_count,
            "stop_count": self.stop_count,
            "timeout_count": self.timeout_count,
            "periods_count": self.periods_count,
            "profitable_periods_count": self.profitable_periods_count,
            "profitable_periods_pct": self.profitable_periods_pct,
            "worst_period_pnl": self.worst_period_pnl,
            "best_period_pnl": self.best_period_pnl,
            "avg_period_pnl": self.avg_period_pnl,
            "is_low_sample": self.is_low_sample,
            "risk_adjusted_score": self.risk_adjusted_score,
            "warnings": "; ".join(self.warnings),
        }


def get_msk_hour(timestamp) -> int:
    """Returns MSK (Europe/Moscow) hour of the given timestamp."""
    ts = pd.to_datetime(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.astimezone(_MSK).hour


def compute_signal_reward_risk(
    sig_row: pd.Series,
    stop_buffer_points: float,
    take_r: float,
) -> tuple[float, float, float]:
    """Returns (risk_points, reward_points, rr) from signal geometry.

    For SELL: entry_raw=low, stop=high+buffer → risk=stop-entry_raw.
    For BUY:  entry_raw=high, stop=low-buffer → risk=entry_raw-stop.
    reward = risk * take_r, rr = take_r (constant at pre-slippage level).
    """
    direction = str(sig_row.get("direction_candidate", "SELL")).upper()
    if direction == "BUY":
        entry_raw = float(sig_row["high"])
        stop = float(sig_row["low"]) - stop_buffer_points
        risk = entry_raw - stop
    else:
        entry_raw = float(sig_row["low"])
        stop = float(sig_row["high"]) + stop_buffer_points
        risk = stop - entry_raw

    if risk <= 0:
        return 0.0, 0.0, 0.0

    reward = risk * take_r
    rr = take_r
    return round(risk, 6), round(reward, 6), round(rr, 6)


def apply_signal_filters(
    debug_df: pd.DataFrame,
    filter_config: FilterConfig,
    stop_buffer_points: float,
    take_r: float,
) -> tuple[pd.DataFrame, int, int, int]:
    """Pre-filters signals in debug_df based on filter_config.

    Returns (modified_df, n_original_signals, n_after_filters, n_filtered).
    Filtered signals are masked by setting is_signal=False.
    """
    df = debug_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed", utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    direction_upper = filter_config.direction.upper()
    sig_mask = (
        df["is_signal"].astype(bool)
        & (df["fail_reason"].astype(str) == "pass")
        & (df["direction_candidate"].str.upper() == direction_upper)
    )
    original_indices = df.index[sig_mask].tolist()
    n_original = len(original_indices)

    to_filter: set[int] = set()

    for sig_idx in original_indices:
        sig_row = df.iloc[sig_idx]

        # MIN_REWARD filter
        if filter_config.min_reward_points > 0:
            _, reward, _ = compute_signal_reward_risk(sig_row, stop_buffer_points, take_r)
            if reward < filter_config.min_reward_points:
                to_filter.add(sig_idx)
                continue

        # MIN_RR filter (note: rr = take_r always at pre-slippage level)
        if filter_config.min_rr > 0:
            _, _, rr = compute_signal_reward_risk(sig_row, stop_buffer_points, take_r)
            if rr < filter_config.min_rr:
                to_filter.add(sig_idx)
                continue

        # Time filter
        hour_msk = get_msk_hour(sig_row["timestamp"])
        if filter_config.exclude_hours_msk and hour_msk in filter_config.exclude_hours_msk:
            to_filter.add(sig_idx)
            continue
        if filter_config.include_hours_msk is not None and hour_msk not in filter_config.include_hours_msk:
            to_filter.add(sig_idx)
            continue

        # Entry confirmation
        if filter_config.entry_confirmation == "next_candle_direction":
            next_idx = sig_idx + 1
            if next_idx >= len(df):
                to_filter.add(sig_idx)
                continue
            nxt = df.iloc[next_idx]
            direction = str(sig_row.get("direction_candidate", "SELL")).upper()
            if direction == "SELL":
                # Bearish confirmation: next candle must be red (close < open)
                if float(nxt["close"]) >= float(nxt["open"]):
                    to_filter.add(sig_idx)
                    continue
            else:  # BUY
                # Bullish confirmation: next candle must be green (close > open)
                if float(nxt["close"]) <= float(nxt["open"]):
                    to_filter.add(sig_idx)
                    continue
        # breakout_confirmation: equivalent to baseline (engine already uses breakout entry)

    if to_filter:
        df.loc[list(to_filter), "is_signal"] = False

    n_filtered = len(to_filter)
    n_after = n_original - n_filtered
    return df, n_original, n_after, n_filtered


def compute_period_stability(trades_df: pd.DataFrame) -> dict:
    """Computes daily period stability metrics from a trades DataFrame."""
    empty = {
        "periods_count": 0,
        "profitable_periods_count": 0,
        "profitable_periods_pct": 0.0,
        "worst_period_pnl": 0.0,
        "best_period_pnl": 0.0,
        "avg_period_pnl": 0.0,
    }
    if trades_df is None or len(trades_df) == 0:
        return empty

    closed = trades_df[trades_df["status"] == "closed"].copy()
    if len(closed) == 0:
        return empty

    closed["signal_time"] = pd.to_datetime(closed["signal_time"])
    closed["_day"] = closed["signal_time"].dt.date
    grouped = closed.groupby("_day")["net_pnl_rub"].sum()

    periods_count = len(grouped)
    profitable_count = int((grouped > 0).sum())

    return {
        "periods_count": periods_count,
        "profitable_periods_count": profitable_count,
        "profitable_periods_pct": round(100.0 * profitable_count / periods_count, 1) if periods_count > 0 else 0.0,
        "worst_period_pnl": round(float(grouped.min()), 2) if periods_count > 0 else 0.0,
        "best_period_pnl": round(float(grouped.max()), 2) if periods_count > 0 else 0.0,
        "avg_period_pnl": round(float(grouped.mean()), 2) if periods_count > 0 else 0.0,
    }


def run_scenario(
    debug_df: pd.DataFrame,
    filter_config: FilterConfig,
    scenario_id: int,
    stop_buffer_points: float = 0.0,
    take_r: float = 1.0,
    slippage_points: float = 0.0,
    slippage_ticks: Optional[float] = None,
    tick_size: Optional[float] = None,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
    entry_horizon_bars: int = 3,
    default_max_hold_bars: int = 30,
    allow_overlap: bool = False,
) -> tuple[ScenarioResult, pd.DataFrame]:
    """Runs a single filter scenario. Returns (ScenarioResult, trades_df)."""
    max_hold = filter_config.max_hold_bars if filter_config.max_hold_bars is not None else default_max_hold_bars

    filtered_df, n_original, n_after, n_filtered = apply_signal_filters(
        debug_df, filter_config, stop_buffer_points, take_r
    )
    skip_rate = round(100.0 * n_filtered / n_original, 1) if n_original > 0 else 0.0

    trades_df = run_backtest(
        debug_df=filtered_df,
        entry_mode="breakout",
        entry_horizon_bars=entry_horizon_bars,
        max_hold_bars=max_hold,
        take_r=take_r,
        stop_buffer_points=stop_buffer_points,
        point_value_rub=point_value_rub,
        commission_per_trade=commission_per_trade,
        contracts=contracts,
        allow_overlap=allow_overlap,
        slippage_points=slippage_points,
        slippage_ticks=slippage_ticks,
        tick_size=tick_size,
        direction_filter=filter_config.direction,
    )

    m = calculate_backtest_metrics(trades_df)

    closed = trades_df[trades_df["status"] == "closed"].copy() if len(trades_df) > 0 else pd.DataFrame()

    gross_profit_rub = 0.0
    gross_loss_rub = 0.0
    take_count = 0
    stop_count = 0
    timeout_count = 0
    avg_risk = 0.0
    avg_reward = 0.0
    avg_rr_val = 0.0
    median_pnl = 0.0

    if len(closed) > 0:
        wins_mask = closed["net_pnl_rub"] > 0
        losses_mask = closed["net_pnl_rub"] < 0
        gross_profit_rub = float(closed.loc[wins_mask, "net_pnl_rub"].sum())
        gross_loss_rub = float(closed.loc[losses_mask, "net_pnl_rub"].sum())

        take_count = int((closed["exit_reason"] == "take").sum())
        stop_count = int(closed["exit_reason"].isin(["stop", "stop_same_bar"]).sum())
        timeout_count = int(closed["exit_reason"].isin(["timeout", "end_of_data"]).sum())

        if "risk_points" in closed.columns and closed["risk_points"].notna().any():
            avg_risk = round(float(closed["risk_points"].mean()), 2)
            avg_reward = round(avg_risk * take_r, 2)
            avg_rr_val = round(take_r, 3)

        median_pnl = round(float(closed["net_pnl_rub"].median()), 2)

    stability = compute_period_stability(trades_df)

    net_pnl = round(m.get("net_pnl_rub", 0.0), 2)
    max_dd = m.get("max_drawdown_rub", 0.0)
    risk_adj_score = round(net_pnl - 0.5 * abs(max_dd), 2)

    n_closed = m.get("closed_trades", 0)
    expectancy = round(net_pnl / n_closed, 2) if n_closed > 0 else 0.0

    is_low_sample = n_closed < filter_config.min_trades_required
    warnings: list[str] = []
    if is_low_sample:
        warnings.append(f"LOW_SAMPLE: {n_closed} < min={filter_config.min_trades_required}")

    result = ScenarioResult(
        scenario_id=scenario_id,
        scenario_name=filter_config.scenario_name,
        filter_config=filter_config,
        n_original_signals=n_original,
        n_after_filters=n_after,
        n_filtered_signals=n_filtered,
        skip_rate_pct=skip_rate,
        trades=n_closed,
        wins=m.get("wins", 0),
        losses=m.get("losses", 0),
        winrate_pct=round(m.get("winrate", 0.0) * 100, 1),
        gross_profit_rub=round(gross_profit_rub, 2),
        gross_loss_rub=round(gross_loss_rub, 2),
        net_pnl_rub=net_pnl,
        profit_factor=round(m.get("profit_factor", 0.0), 3),
        expectancy_rub=expectancy,
        avg_trade_rub=round(m.get("avg_net_pnl_rub", 0.0), 2),
        median_trade_rub=median_pnl,
        best_trade_rub=round(m.get("max_win_rub", 0.0), 2),
        worst_trade_rub=round(m.get("max_loss_rub", 0.0), 2),
        max_drawdown_rub=round(max_dd, 2),
        max_drawdown_pct=round(m.get("max_drawdown_pct", 0.0) * 100, 1),
        avg_risk_points=avg_risk,
        avg_reward_points=avg_reward,
        avg_rr=avg_rr_val,
        avg_bars_held=round(m.get("avg_bars_held", 0.0), 1),
        take_count=take_count,
        stop_count=stop_count,
        timeout_count=timeout_count,
        periods_count=stability["periods_count"],
        profitable_periods_count=stability["profitable_periods_count"],
        profitable_periods_pct=stability["profitable_periods_pct"],
        worst_period_pnl=stability["worst_period_pnl"],
        best_period_pnl=stability["best_period_pnl"],
        avg_period_pnl=stability["avg_period_pnl"],
        is_low_sample=is_low_sample,
        warnings=warnings,
        risk_adjusted_score=risk_adj_score,
    )

    if len(trades_df) > 0:
        trades_df = trades_df.copy()
        trades_df["scenario_name"] = filter_config.scenario_name
        trades_df["scenario_id"] = scenario_id

    return result, trades_df
