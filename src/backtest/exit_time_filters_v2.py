"""Backtest Exit/Time Filters v2 (MVP-2.2).

Extends MVP-2.0 diagnostic filters with:
- Conditional max_hold exit (progress-to-take % and PnL threshold at check_bar)
- Softer fixed max_hold (10, 15 bars)
- Hour-based time filters
- Large winner / cut winner / saved loser analysis support

The conditional exit logic:
  At check_bar (e.g. 5), if progress_to_take_pct < threshold → exit at current close.
  Stop/take priority always beats conditional exit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import pandas as pd

from src.backtest.diagnostic_filters import (
    FilterConfig,
    apply_signal_filters,
    compute_period_stability,
    get_msk_hour,
)
from src.backtest.metrics import calculate_backtest_metrics
from src.backtest.models import BacktestTrade

_HARD_CAP_BARS = 200  # safety cap when max_hold_bars=None


# ── ConditionalMaxHoldConfig ─────────────────────────────────────────────────

@dataclass
class ConditionalMaxHoldConfig:
    """Rules for conditional max_hold exit at a specific bar."""
    enabled: bool = False
    check_bar: int = 5
    min_progress_to_take_pct: Optional[float] = None  # exit if progress < threshold
    max_pnl_points: Optional[float] = None            # exit if pnl_points <= threshold

    @property
    def name(self) -> str:
        if not self.enabled:
            return "none"
        parts = []
        if self.min_progress_to_take_pct is not None:
            parts.append(f"progress_lt_{int(self.min_progress_to_take_pct)}pct")
        if self.max_pnl_points is not None:
            parts.append(f"pnl_le_{int(self.max_pnl_points)}pts")
        return f"hold{self.check_bar}_" + "_".join(parts) if parts else f"hold{self.check_bar}"


# ── FilterConfigV2 ────────────────────────────────────────────────────────────

@dataclass
class FilterConfigV2:
    scenario_name: str = "baseline_v2"
    direction: str = "SELL"
    exclude_hours_msk: list = field(default_factory=list)
    include_hours_msk: Optional[list] = None
    max_hold_bars: Optional[int] = None          # None = no fixed timeout (uses _HARD_CAP_BARS)
    conditional_max_hold: ConditionalMaxHoldConfig = field(default_factory=ConditionalMaxHoldConfig)
    entry_confirmation: str = "baseline"
    min_trades_required: int = 30
    time_filter_name: str = "all_hours"
    exit_rule_name: str = "no_max_hold"
    # Mark scenario as not safely simulatable without look-ahead
    is_unsupported: bool = False
    unsupported_reason: str = ""

    def to_filter_config(self) -> FilterConfig:
        """Convert to legacy FilterConfig for apply_signal_filters compatibility."""
        return FilterConfig(
            scenario_name=self.scenario_name,
            direction=self.direction,
            exclude_hours_msk=self.exclude_hours_msk,
            include_hours_msk=self.include_hours_msk,
            max_hold_bars=self.max_hold_bars,
            entry_confirmation=self.entry_confirmation,
            min_trades_required=self.min_trades_required,
            time_filter_name=self.time_filter_name,
        )


# ── ScenarioResultV2 ──────────────────────────────────────────────────────────

@dataclass
class ScenarioResultV2:
    scenario_id: int
    scenario_name: str
    filter_config: FilterConfigV2
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
    avg_risk_points: float = 0.0
    avg_bars_held: float = 0.0
    take_count: int = 0
    stop_count: int = 0
    max_hold_exit_count: int = 0               # fixed max_hold timeout exits
    conditional_max_hold_exit_count: int = 0   # conditional rule exits
    # Period stability (daily)
    periods_count: int = 0
    profitable_periods_count: int = 0
    profitable_periods_pct: float = 0.0
    worst_period_pnl: float = 0.0
    best_period_pnl: float = 0.0
    avg_period_pnl: float = 0.0
    # Large winner / cut winner analysis (populated after comparison vs baseline)
    large_winners_count: int = 0
    large_winners_cut_count: int = 0
    saved_losers_count: int = 0
    cut_winners_rub: float = 0.0
    saved_losers_rub: float = 0.0
    # Flags
    is_low_sample: bool = False
    warnings: list = field(default_factory=list)
    risk_adjusted_score: float = 0.0

    def to_dict(self) -> dict:
        fc = self.filter_config
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "time_filter_name": fc.time_filter_name,
            "exit_rule_name": fc.exit_rule_name,
            "entry_confirmation": fc.entry_confirmation,
            "exclude_hours_msk": str(fc.exclude_hours_msk),
            "max_hold_bars": fc.max_hold_bars,
            "conditional_enabled": fc.conditional_max_hold.enabled,
            "conditional_check_bar": fc.conditional_max_hold.check_bar if fc.conditional_max_hold.enabled else None,
            "conditional_progress_pct": fc.conditional_max_hold.min_progress_to_take_pct,
            "conditional_max_pnl": fc.conditional_max_hold.max_pnl_points,
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
            "avg_risk_points": self.avg_risk_points,
            "avg_bars_held": self.avg_bars_held,
            "take_count": self.take_count,
            "stop_count": self.stop_count,
            "max_hold_exit_count": self.max_hold_exit_count,
            "conditional_max_hold_exit_count": self.conditional_max_hold_exit_count,
            "periods_count": self.periods_count,
            "profitable_periods_count": self.profitable_periods_count,
            "profitable_periods_pct": self.profitable_periods_pct,
            "worst_period_pnl": self.worst_period_pnl,
            "best_period_pnl": self.best_period_pnl,
            "avg_period_pnl": self.avg_period_pnl,
            "large_winners_count": self.large_winners_count,
            "large_winners_cut_count": self.large_winners_cut_count,
            "saved_losers_count": self.saved_losers_count,
            "cut_winners_rub": self.cut_winners_rub,
            "saved_losers_rub": self.saved_losers_rub,
            "is_low_sample": self.is_low_sample,
            "risk_adjusted_score": self.risk_adjusted_score,
            "warnings": "; ".join(self.warnings),
        }


# ── Progress / conditional exit helpers ──────────────────────────────────────

def compute_progress_to_take_pct(
    entry_price: float,
    current_price: float,
    take_price: float,
    direction: str,
) -> float:
    """Percentage progress from entry toward take price.

    100% = at take price, 0% = at entry, negative = moved against signal.
    """
    if direction == "SELL":
        total_distance = entry_price - take_price
        progress = entry_price - current_price
    else:
        total_distance = take_price - entry_price
        progress = current_price - entry_price

    if total_distance <= 0:
        return 0.0
    return progress / total_distance * 100.0


def _should_conditional_exit(
    entry_price: float,
    current_close: float,
    take_price: float,
    direction: str,
    cond: ConditionalMaxHoldConfig,
) -> bool:
    if not cond.enabled:
        return False

    if cond.min_progress_to_take_pct is not None:
        progress = compute_progress_to_take_pct(entry_price, current_close, take_price, direction)
        if progress < cond.min_progress_to_take_pct:
            return True

    if cond.max_pnl_points is not None:
        if direction == "SELL":
            pnl_pts = entry_price - current_close
        else:
            pnl_pts = current_close - entry_price
        if pnl_pts <= cond.max_pnl_points:
            return True

    return False


# ── V2 backtest engine ────────────────────────────────────────────────────────

def _find_breakout_entry_v2(df, sig_idx, direction, entry_trigger, horizon):
    search_end = min(sig_idx + 1 + horizon, len(df))
    for idx in range(sig_idx + 1, search_end):
        row = df.iloc[idx]
        if direction == "BUY" and row["high"] >= entry_trigger:
            return idx, entry_trigger, row["timestamp"]
        if direction == "SELL" and row["low"] <= entry_trigger:
            return idx, entry_trigger, row["timestamp"]
    return None, None, None


def _find_exit_v2(
    df: pd.DataFrame,
    entry_bar_idx: int,
    direction: str,
    entry_price: float,
    stop_price: float,
    take_price: float,
    max_hold_bars: Optional[int],
    conditional: ConditionalMaxHoldConfig,
) -> tuple[int, float, str, int]:
    """Exit finder with optional conditional max_hold support.

    Returns (exit_bar_idx, exit_price_raw, exit_reason, bars_held).
    exit_reason: stop | stop_same_bar | take | timeout | conditional_max_hold_exit | end_of_data
    Stop/take priority always beats conditional or timeout exit.
    """
    limit = max_hold_bars if max_hold_bars is not None else _HARD_CAP_BARS
    start = entry_bar_idx + 1
    end = min(start + limit, len(df))
    last_idx = end - 1

    for idx in range(start, end):
        row = df.iloc[idx]
        bars_held = idx - entry_bar_idx

        if direction == "BUY":
            stop_hit = row["low"] <= stop_price
            take_hit = row["high"] >= take_price
        else:
            stop_hit = row["high"] >= stop_price
            take_hit = row["low"] <= take_price

        if stop_hit and take_hit:
            return idx, stop_price, "stop_same_bar", bars_held
        if stop_hit:
            return idx, stop_price, "stop", bars_held
        if take_hit:
            return idx, take_price, "take", bars_held

        # Conditional check at check_bar (after stop/take priority)
        if conditional.enabled and bars_held == conditional.check_bar:
            current_close = float(row["close"])
            if _should_conditional_exit(entry_price, current_close, take_price, direction, conditional):
                return idx, current_close, "conditional_max_hold_exit", bars_held

    actual_last = min(last_idx, len(df) - 1)
    exit_price = float(df.iloc[actual_last]["close"])
    reason = "end_of_data" if end > len(df) else "timeout"
    return actual_last, exit_price, reason, actual_last - entry_bar_idx


def run_backtest_v2(
    debug_df: pd.DataFrame,
    direction_filter: str = "SELL",
    entry_horizon_bars: int = 3,
    max_hold_bars: Optional[int] = None,
    conditional_max_hold: Optional[ConditionalMaxHoldConfig] = None,
    take_r: float = 1.0,
    stop_buffer_points: float = 0.0,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
    allow_overlap: bool = False,
    slippage_points: float = 0.0,
) -> pd.DataFrame:
    """Like run_backtest but supports conditional max_hold exit."""
    cond = conditional_max_hold or ConditionalMaxHoldConfig(enabled=False)

    df = debug_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    signals_mask = (df["is_signal"].astype(bool)) & (df["fail_reason"].astype(str) == "pass")
    if direction_filter != "all":
        signals_mask = signals_mask & (df["direction_candidate"].str.upper() == direction_filter.upper())
    signal_indices = df.index[signals_mask].tolist()

    trades = []
    commission_rub = commission_per_trade * 2 * contracts
    last_closed_exit_idx = -1
    trade_id = 0

    for sig_idx in signal_indices:
        trade_id += 1
        sig_row = df.iloc[sig_idx]
        direction = sig_row["direction_candidate"]

        if not allow_overlap and sig_idx <= last_closed_exit_idx:
            trades.append(_skipped_v2(trade_id, sig_row, "skipped_overlap"))
            continue

        if direction == "BUY":
            stop_price = sig_row["low"] - stop_buffer_points
        else:
            stop_price = sig_row["high"] + stop_buffer_points

        entry_trigger = float(sig_row["high"]) if direction == "BUY" else float(sig_row["low"])
        entry_bar_idx, entry_price_raw, entry_time = _find_breakout_entry_v2(
            df, sig_idx, direction, entry_trigger, entry_horizon_bars
        )
        if entry_bar_idx is None:
            trades.append(_skipped_v2(trade_id, sig_row, "skipped_no_entry"))
            continue

        if direction == "BUY":
            entry_price = entry_price_raw + slippage_points
        else:
            entry_price = entry_price_raw - slippage_points

        if direction == "BUY":
            risk_points = entry_price_raw - stop_price
        else:
            risk_points = stop_price - entry_price_raw

        if risk_points <= 0:
            trades.append(_skipped_v2(trade_id, sig_row, "skipped_invalid_risk"))
            continue

        if direction == "BUY":
            take_price = entry_price_raw + risk_points * take_r
        else:
            take_price = entry_price_raw - risk_points * take_r

        exit_bar_idx, exit_price_raw, exit_reason, bars_held = _find_exit_v2(
            df, entry_bar_idx, direction, entry_price,
            stop_price, take_price, max_hold_bars, cond
        )

        if direction == "BUY":
            exit_price = exit_price_raw - slippage_points
        else:
            exit_price = exit_price_raw + slippage_points

        if direction == "BUY":
            gross_points = exit_price - entry_price
        else:
            gross_points = entry_price - exit_price

        gross_pnl_rub = gross_points * point_value_rub * contracts
        net_pnl_rub = gross_pnl_rub - commission_rub

        exit_time = df.iloc[exit_bar_idx]["timestamp"] if exit_bar_idx < len(df) else entry_time

        trade = BacktestTrade(
            trade_id=trade_id,
            instrument=str(sig_row.get("instrument", "")),
            timeframe=str(sig_row.get("timeframe", "")),
            direction=direction,
            signal_time=sig_row["timestamp"],
            entry_time=entry_time,
            exit_time=exit_time,
            signal_open=float(sig_row["open"]),
            signal_high=float(sig_row["high"]),
            signal_low=float(sig_row["low"]),
            signal_close=float(sig_row["close"]),
            entry_price=entry_price,
            stop_price=stop_price,
            take_price=take_price,
            exit_price=exit_price,
            status="closed",
            exit_reason=exit_reason,
            risk_points=risk_points,
            gross_points=gross_points,
            gross_pnl_rub=gross_pnl_rub,
            commission_rub=commission_rub,
            net_pnl_rub=net_pnl_rub,
            bars_held=bars_held,
            entry_price_raw=entry_price_raw,
            exit_price_raw=exit_price_raw,
            slippage_points=slippage_points,
        )
        trades.append(trade)
        last_closed_exit_idx = exit_bar_idx

    if not trades:
        return pd.DataFrame(columns=list(BacktestTrade.__dataclass_fields__.keys()))

    return pd.DataFrame([asdict(t) for t in trades])


def _skipped_v2(trade_id, sig_row, status):
    return BacktestTrade(
        trade_id=trade_id,
        instrument=str(sig_row.get("instrument", "")),
        timeframe=str(sig_row.get("timeframe", "")),
        direction=str(sig_row.get("direction_candidate", "")),
        signal_time=sig_row["timestamp"],
        entry_time=None, exit_time=None,
        signal_open=float(sig_row["open"]),
        signal_high=float(sig_row["high"]),
        signal_low=float(sig_row["low"]),
        signal_close=float(sig_row["close"]),
        entry_price=None, stop_price=None, take_price=None, exit_price=None,
        status=status, exit_reason="none",
        risk_points=None, gross_points=None,
        gross_pnl_rub=None, commission_rub=None, net_pnl_rub=None, bars_held=None,
    )


# ── run_scenario_v2 ───────────────────────────────────────────────────────────

def run_scenario_v2(
    debug_df: pd.DataFrame,
    filter_config: FilterConfigV2,
    scenario_id: int,
    stop_buffer_points: float = 0.0,
    take_r: float = 1.0,
    slippage_points: float = 0.0,
    point_value_rub: float = 10.0,
    commission_per_trade: float = 0.025,
    contracts: int = 1,
    entry_horizon_bars: int = 3,
    allow_overlap: bool = False,
) -> tuple[ScenarioResultV2, pd.DataFrame]:
    """Runs a single V2 filter scenario. Returns (ScenarioResultV2, trades_df)."""
    legacy_fc = filter_config.to_filter_config()
    filtered_df, n_original, n_after, n_filtered = apply_signal_filters(
        debug_df, legacy_fc, stop_buffer_points, take_r
    )
    skip_rate = round(100.0 * n_filtered / n_original, 1) if n_original > 0 else 0.0

    trades_df = run_backtest_v2(
        debug_df=filtered_df,
        direction_filter=filter_config.direction,
        entry_horizon_bars=entry_horizon_bars,
        max_hold_bars=filter_config.max_hold_bars,
        conditional_max_hold=filter_config.conditional_max_hold,
        take_r=take_r,
        stop_buffer_points=stop_buffer_points,
        point_value_rub=point_value_rub,
        commission_per_trade=commission_per_trade,
        contracts=contracts,
        allow_overlap=allow_overlap,
        slippage_points=slippage_points,
    )

    m = calculate_backtest_metrics(trades_df)
    closed = trades_df[trades_df["status"] == "closed"].copy() if len(trades_df) > 0 else pd.DataFrame()

    gross_profit_rub = 0.0
    gross_loss_rub = 0.0
    take_count = 0
    stop_count = 0
    max_hold_exit_count = 0
    conditional_max_hold_exit_count = 0
    avg_risk = 0.0
    median_pnl = 0.0

    if len(closed) > 0:
        wins_mask = closed["net_pnl_rub"] > 0
        losses_mask = closed["net_pnl_rub"] < 0
        gross_profit_rub = float(closed.loc[wins_mask, "net_pnl_rub"].sum())
        gross_loss_rub = float(closed.loc[losses_mask, "net_pnl_rub"].sum())

        take_count = int((closed["exit_reason"] == "take").sum())
        stop_count = int(closed["exit_reason"].isin(["stop", "stop_same_bar"]).sum())
        max_hold_exit_count = int(closed["exit_reason"].isin(["timeout", "end_of_data"]).sum())
        conditional_max_hold_exit_count = int((closed["exit_reason"] == "conditional_max_hold_exit").sum())

        if "risk_points" in closed.columns and closed["risk_points"].notna().any():
            avg_risk = round(float(closed["risk_points"].mean()), 2)

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
    if filter_config.is_unsupported:
        warnings.append(f"UNSUPPORTED: {filter_config.unsupported_reason}")

    result = ScenarioResultV2(
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
        avg_risk_points=avg_risk,
        avg_bars_held=round(m.get("avg_bars_held", 0.0), 1),
        take_count=take_count,
        stop_count=stop_count,
        max_hold_exit_count=max_hold_exit_count,
        conditional_max_hold_exit_count=conditional_max_hold_exit_count,
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


# ── Large winner / cut winner analysis ───────────────────────────────────────

def compute_winner_loser_analysis(
    baseline_trades: pd.DataFrame,
    scenario_trades: pd.DataFrame,
    large_winner_threshold: float = 500.0,
    cut_winner_threshold: float = 300.0,
    saved_loser_threshold: float = -300.0,
) -> dict:
    """Compare scenario trades vs baseline to find cut winners and saved losers.

    Returns dict with counts and RUB deltas.
    """
    empty = {
        "large_winners_count": 0,
        "large_winners_cut_count": 0,
        "saved_losers_count": 0,
        "cut_winners_rub": 0.0,
        "saved_losers_rub": 0.0,
    }

    if baseline_trades is None or len(baseline_trades) == 0:
        return empty
    if scenario_trades is None or len(scenario_trades) == 0:
        return empty

    base_closed = baseline_trades[baseline_trades["status"] == "closed"].copy()
    scen_closed = scenario_trades[scenario_trades["status"] == "closed"].copy()

    if len(base_closed) == 0 or len(scen_closed) == 0:
        return empty

    # Match by signal_time — same signal, compare outcomes
    base_closed["signal_time"] = pd.to_datetime(base_closed["signal_time"])
    scen_closed["signal_time"] = pd.to_datetime(scen_closed["signal_time"])

    merged = base_closed[["signal_time", "net_pnl_rub"]].merge(
        scen_closed[["signal_time", "net_pnl_rub"]],
        on="signal_time",
        suffixes=("_base", "_scen"),
        how="inner",
    )

    large_winners_count = int((merged["net_pnl_rub_base"] >= large_winner_threshold).sum())
    large_winners_cut = merged[
        (merged["net_pnl_rub_base"] >= large_winner_threshold)
        & (merged["net_pnl_rub_scen"] < merged["net_pnl_rub_base"])
    ]
    large_winners_cut_count = len(large_winners_cut)

    cut_winners = merged[
        (merged["net_pnl_rub_base"] >= cut_winner_threshold)
        & (merged["net_pnl_rub_scen"] < merged["net_pnl_rub_base"])
    ]
    cut_winners_rub = float((cut_winners["net_pnl_rub_scen"] - cut_winners["net_pnl_rub_base"]).sum())

    saved_losers = merged[
        (merged["net_pnl_rub_base"] <= saved_loser_threshold)
        & (merged["net_pnl_rub_scen"] > merged["net_pnl_rub_base"])
    ]
    saved_losers_count = len(saved_losers)
    saved_losers_rub = float((saved_losers["net_pnl_rub_scen"] - saved_losers["net_pnl_rub_base"]).sum())

    return {
        "large_winners_count": large_winners_count,
        "large_winners_cut_count": large_winners_cut_count,
        "saved_losers_count": saved_losers_count,
        "cut_winners_rub": round(cut_winners_rub, 2),
        "saved_losers_rub": round(saved_losers_rub, 2),
    }
