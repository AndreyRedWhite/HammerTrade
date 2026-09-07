import pandas as pd
import pytest

from src.strategies.volatility_breakout import (
    VolatilityBreakoutConfig,
    prepare_breakout_frame,
)


def _candles(closes):
    ts = pd.date_range("2026-01-01", periods=len(closes), freq="h", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": closes,
        "high": [x + 0.5 for x in closes],
        "low": [x - 0.5 for x in closes],
        "close": closes,
        "volume": 1,
    })


def test_breakout_levels_are_shifted_and_no_lookahead():
    cfg = VolatilityBreakoutConfig(
        atr_window=2, channel_window=3, compression_lookback=4,
        compression_quantile=0.9, compression_recent_bars=3,
        exit_channel_window=2,
    )
    out = prepare_breakout_frame(_candles([100, 100, 100, 100, 100, 105]), cfg)
    last = out.iloc[-1]
    assert last.entry_high == pytest.approx(100.5)
    assert bool(last.long_signal)


def test_no_signal_without_prior_compression():
    cfg = VolatilityBreakoutConfig(
        atr_window=2, channel_window=3, compression_lookback=4,
        compression_quantile=0.1, compression_recent_bars=1,
        exit_channel_window=2,
    )
    out = prepare_breakout_frame(_candles([100, 102, 99, 103, 98, 110]), cfg)
    assert not bool(out.iloc[-1].long_signal)


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        prepare_breakout_frame(_candles([1, 2, 3]),
                               VolatilityBreakoutConfig(compression_quantile=1.0))
