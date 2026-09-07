import scripts.run_orb_sandbox_trader as orb
import pandas as pd


def test_fill_points_supports_non_si_futures():
    assert orb.fill_points(45510.0, 2, 10.0) == 2275.5
    assert orb.fill_points(152800.0, 2, 1.0) == 76400.0


def test_fill_points_invalid_input():
    assert orb.fill_points(None, 1, 1) is None
    assert orb.fill_points(10, 0, 1) is None


def test_close_confirmation_supports_long_and_short():
    long_bar = pd.DataFrame([{"ts": pd.Timestamp("2026-01-01", tz="UTC"),
                              "low": 99, "high": 111, "close": 106, "volume": 200}])
    assert orb.breakout_direction(long_bar, 100, 105, 100, "BOTH", "close", 1.5) == "LONG"
    short_bar = long_bar.assign(low=90, high=101, close=99)
    assert orb.breakout_direction(short_bar, 100, 105, 100, "BOTH", "close", 1.5) == "SHORT"


def test_ambiguous_touch_bar_is_skipped():
    bar = pd.DataFrame([{"ts": pd.Timestamp("2026-01-01", tz="UTC"),
                         "low": 90, "high": 110, "close": 102, "volume": 200}])
    assert orb.breakout_direction(bar, 100, 105, 100, "BOTH", "touch", 1.0) is None


def test_gross_pnl_respects_direction_and_point_value():
    assert orb.gross_pnl("LONG", 100, 110, 2, 10) == 200
    assert orb.gross_pnl("SHORT", 100, 90, 2, 10) == 200
