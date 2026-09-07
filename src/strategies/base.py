from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import pandas as pd


@dataclass
class StrategySignal:
    strategy_name: str
    ticker: str
    direction: str  # "LONG" or "SHORT"
    timestamp: datetime
    entry_price: float
    stop_price: Optional[float]
    take_price: Optional[float]
    reason: str
    metadata: dict = field(default_factory=dict)


@dataclass
class StrategyResult:
    strategy_name: str
    ticker: str
    direction: str
    timeframe: str
    scenario: str
    period: str
    trades: int
    wins: int
    losses: int
    winrate: float
    net_pnl: float
    profit_factor: float
    expectancy: float
    max_drawdown: float
    best_trade: float
    worst_trade: float
    avg_bars_held: float
    median_bars_held: float
    profitable_days_pct: float
    profitable_weeks_pct: float
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "ticker": self.ticker,
            "direction": self.direction,
            "timeframe": self.timeframe,
            "scenario": self.scenario,
            "period": self.period,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "winrate": self.winrate,
            "net_pnl": self.net_pnl,
            "profit_factor": self.profit_factor,
            "expectancy": self.expectancy,
            "max_drawdown": self.max_drawdown,
            "best_trade": self.best_trade,
            "worst_trade": self.worst_trade,
            "avg_bars_held": self.avg_bars_held,
            "median_bars_held": self.median_bars_held,
            "profitable_days_pct": self.profitable_days_pct,
            "profitable_weeks_pct": self.profitable_weeks_pct,
            "warnings": self.warnings,
        }


class Strategy(ABC):
    name: str

    @abstractmethod
    def generate_signals(self, candles: pd.DataFrame, context: dict) -> list[StrategySignal]:
        """Generate signals from candle data.

        Args:
            candles: DataFrame with columns: timestamp, open, high, low, close, volume
            context: Additional context (regime info, rolling stats, etc.)

        Returns:
            List of StrategySignal objects
        """
        ...

    @abstractmethod
    def required_columns(self) -> list[str]:
        """Return list of required DataFrame columns."""
        ...
