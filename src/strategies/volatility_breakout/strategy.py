"""Pure indicator math for a low-turnover volatility breakout.

The strategy deliberately works on closed 1h/4h bars.  It waits for ATR
compression and then requires a close outside the prior Donchian channel.
All rolling levels are shifted, so the signal cannot see the current bar.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class VolatilityBreakoutConfig:
    atr_window: int = 14
    channel_window: int = 20
    compression_lookback: int = 100
    compression_quantile: float = 0.25
    compression_recent_bars: int = 5
    exit_channel_window: int = 10
    stop_atr: float = 2.0
    take_r: float = 3.0

    def validate(self) -> None:
        if min(self.atr_window, self.channel_window, self.compression_lookback,
               self.compression_recent_bars, self.exit_channel_window) < 1:
            raise ValueError("all strategy windows must be positive")
        if not 0 < self.compression_quantile < 1:
            raise ValueError("compression_quantile must be between 0 and 1")
        if self.stop_atr <= 0 or self.take_r <= 0:
            raise ValueError("stop_atr and take_r must be positive")


def prepare_breakout_frame(
    candles: pd.DataFrame,
    cfg: VolatilityBreakoutConfig,
) -> pd.DataFrame:
    """Return candles with causal indicators and LONG/SHORT entry flags."""
    cfg.validate()
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required.difference(candles.columns)
    if missing:
        raise ValueError(f"candles missing columns: {sorted(missing)}")

    out = candles.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out = out.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)

    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.rolling(cfg.atr_window, min_periods=cfg.atr_window).mean()

    # Entry levels use only bars strictly before the signal bar.
    out["entry_high"] = out["high"].shift(1).rolling(
        cfg.channel_window, min_periods=cfg.channel_window
    ).max()
    out["entry_low"] = out["low"].shift(1).rolling(
        cfg.channel_window, min_periods=cfg.channel_window
    ).min()
    out["exit_high"] = out["high"].shift(1).rolling(
        cfg.exit_channel_window, min_periods=cfg.exit_channel_window
    ).max()
    out["exit_low"] = out["low"].shift(1).rolling(
        cfg.exit_channel_window, min_periods=cfg.exit_channel_window
    ).min()

    # Compression must have happened before the breakout bar.  Looking for it
    # in a short recent window avoids requiring the breakout bar itself to have
    # an artificially small range.
    atr_cutoff = out["atr"].shift(1).rolling(
        cfg.compression_lookback,
        min_periods=max(cfg.atr_window, cfg.compression_lookback // 2),
    ).quantile(cfg.compression_quantile)
    compressed_bar = out["atr"].shift(1) <= atr_cutoff
    out["compression_ready"] = compressed_bar.rolling(
        cfg.compression_recent_bars, min_periods=1
    ).max().fillna(False).astype(bool)

    out["long_signal"] = (
        out["compression_ready"]
        & out["entry_high"].notna()
        & (out["close"] > out["entry_high"])
    )
    out["short_signal"] = (
        out["compression_ready"]
        & out["entry_low"].notna()
        & (out["close"] < out["entry_low"])
    )
    return out
