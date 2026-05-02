import pytest
import pandas as pd
from src.strategy.candle_geometry import compute_geometry, get_geometry_for_candle


def test_geometry_values():
    g = get_geometry_for_candle(open_=100, high=110, low=90, close=105)

    assert g["range"] == 20
    assert g["body"] == 5
    assert g["upper_shadow"] == 5
    assert g["lower_shadow"] == 10
    assert abs(g["body_frac"] - 0.25) < 1e-9
    assert abs(g["upper_frac"] - 0.25) < 1e-9
    assert abs(g["lower_frac"] - 0.50) < 1e-9
    assert abs(g["close_pos"] - 0.75) < 1e-9
    assert g["valid_candle"] is True


def test_geometry_invalid_range():
    g = get_geometry_for_candle(open_=100, high=100, low=100, close=100)
    assert g["valid_candle"] is False
    assert g["body_frac"] is None


def test_compute_geometry_dataframe():
    df = pd.DataFrame([
        {"timestamp": "2024-01-01 10:00", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 100},
        {"timestamp": "2024-01-01 10:01", "open": 105, "high": 105, "low": 105, "close": 105, "volume": 10},
    ])
    result = compute_geometry(df)

    row0 = result.iloc[0]
    assert row0["range"] == 20
    assert row0["valid_candle"]
    assert abs(row0["close_pos"] - 0.75) < 1e-9

    row1 = result.iloc[1]
    assert not row1["valid_candle"]
