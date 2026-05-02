import sys
from pathlib import Path
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_universe_research import build_command


class _FakeArgs:
    class_code = "SPBFUT"
    start = "2026-03-01"
    end = "2026-04-10"
    timeframe = "1m"
    profile = "balanced"
    env = "prod"
    direction_filter = "all"
    slippage_points = "0"
    grid_slippage_ticks_values = "0,1,2,5"
    take_r = "1.0"
    max_hold_bars = "30"
    skip_load = False
    skip_grid = False
    skip_walkforward_grid = False
    no_archive = False


def test_build_command_includes_tick_size():
    cmd = build_command("BRK6", 746.947, 0.01, _FakeArgs())
    assert "--tick-size" in cmd
    idx = cmd.index("--tick-size")
    assert cmd[idx + 1] == "0.01"


def test_build_command_includes_point_value_rub():
    cmd = build_command("BRK6", 746.947, 0.01, _FakeArgs())
    assert "--point-value-rub" in cmd
    idx = cmd.index("--point-value-rub")
    assert cmd[idx + 1] == "746.947"


def test_build_command_omits_tick_size_when_none():
    cmd = build_command("BRK6", 746.947, None, _FakeArgs())
    assert "--tick-size" not in cmd


def test_build_command_omits_tick_size_when_nan():
    cmd = build_command("BRK6", 746.947, float("nan"), _FakeArgs())
    assert "--tick-size" not in cmd


def test_build_command_omits_point_value_rub_when_none():
    cmd = build_command("SiM6", None, 0.5, _FakeArgs())
    assert "--point-value-rub" not in cmd


def test_build_command_ticker_present():
    cmd = build_command("SiM6", 10.0, 0.5, _FakeArgs())
    assert "--ticker" in cmd
    idx = cmd.index("--ticker")
    assert cmd[idx + 1] == "SiM6"


def test_build_command_skip_load_when_true():
    class Args(_FakeArgs):
        skip_load = True
    cmd = build_command("CRM6", 1000.0, 0.001, Args())
    assert "--skip-load" in cmd


def test_build_command_no_skip_load_when_false():
    cmd = build_command("CRM6", 1000.0, 0.001, _FakeArgs())
    assert "--skip-load" not in cmd


def test_build_command_skip_load_and_skip_walkforward_grid():
    class Args(_FakeArgs):
        skip_load = True
        skip_walkforward_grid = True
    cmd = build_command("CRM6", 1000.0, 0.001, Args())
    assert "--skip-load" in cmd
    assert "--skip-walkforward-grid" in cmd
