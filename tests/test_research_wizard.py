import subprocess
import sys
from pathlib import Path
import pytest

# Import wizard module directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_research_wizard import build_command, collect_params, _DEFAULTS


def test_defaults_are_complete():
    required = ["ticker", "class_code", "start", "end", "timeframe", "profile", "env"]
    for key in required:
        assert key in _DEFAULTS, f"Missing default: {key}"


def test_build_command_basic():
    params = dict(_DEFAULTS)
    params["ticker"] = "SiM6"
    cmd = build_command(params)
    assert "bash" in cmd[0]
    assert "--ticker" in cmd
    assert "SiM6" in cmd
    assert "--from" in cmd
    assert "--to" in cmd


def test_build_command_skip_load():
    params = dict(_DEFAULTS)
    params["ticker"] = "SiM6"
    params["load"] = False
    cmd = build_command(params)
    assert "--skip-load" in cmd


def test_build_command_skip_grid():
    params = dict(_DEFAULTS)
    params["ticker"] = "SiM6"
    params["grid"] = False
    cmd = build_command(params)
    assert "--skip-grid" in cmd


def test_build_command_direction_filter():
    params = dict(_DEFAULTS)
    params["ticker"] = "SiM6"
    params["direction_filter"] = "SELL"
    cmd = build_command(params)
    assert "--direction-filter" in cmd
    idx = cmd.index("--direction-filter")
    assert cmd[idx + 1] == "SELL"


def test_build_command_no_archive():
    params = dict(_DEFAULTS)
    params["ticker"] = "SiM6"
    params["archive"] = False
    cmd = build_command(params)
    assert "--no-archive" in cmd


def test_collect_params_uses_defaults_when_yes():
    params = collect_params(use_defaults=True)
    assert params["ticker"] == _DEFAULTS["ticker"]
    assert params["profile"] == _DEFAULTS["profile"]


def test_dry_run_does_not_call_subprocess():
    """dry-run flag should print command but not execute the pipeline."""
    result = subprocess.run(
        [sys.executable, "scripts/run_research_wizard.py", "--dry-run", "--yes"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent)
    )
    assert result.returncode == 0
    assert "dry-run" in result.stdout.lower() or "not executing" in result.stdout.lower()


def test_yes_flag_uses_defaults():
    result = subprocess.run(
        [sys.executable, "scripts/run_research_wizard.py", "--yes", "--dry-run"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent)
    )
    assert result.returncode == 0
    assert _DEFAULTS["ticker"] in result.stdout
