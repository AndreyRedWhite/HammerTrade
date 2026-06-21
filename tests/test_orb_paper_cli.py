"""Tests for ORB paper trader CLI argument parsing."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse_args(argv=None):
    """Import and call _parse_args from run_orb_paper_trader with given argv."""
    import importlib
    import sys as _sys
    old_argv = _sys.argv
    try:
        _sys.argv = ["run_orb_paper_trader.py"] + (argv or [])
        # Import fresh each time to avoid cached args
        import scripts.run_orb_paper_trader as module
        importlib.reload(module)
        return module._parse_args()
    finally:
        _sys.argv = old_argv


# ─────────────────────────────── 1 ────────────────────────────────────────────
def test_default_orders_enabled_false():
    """Default --orders-enabled should be False."""
    args = _parse_args([])
    assert args.orders_enabled is False


# ─────────────────────────────── 2 ────────────────────────────────────────────
def test_default_direction_short():
    """Default --direction should be SHORT."""
    args = _parse_args([])
    assert args.direction == "SHORT"


# ─────────────────────────────── 3 ────────────────────────────────────────────
def test_required_args_parse():
    """A valid args list with overrides parses without error."""
    args = _parse_args([
        "--ticker", "SiU6",
        "--direction", "SHORT",
        "--opening-range-start", "10:00",
        "--opening-range-end", "11:00",
        "--take-r", "2.5",
        "--state-db", "/tmp/orb.sqlite",
        "--experiment-name", "orb_test",
        "--once",
        "--ignore-market-hours",
    ])
    assert args.ticker == "SiU6"
    assert args.direction == "SHORT"
    assert args.take_r == 2.5
    assert args.state_db == "/tmp/orb.sqlite"
    assert args.experiment_name == "orb_test"
    assert args.once is True
    assert args.ignore_market_hours is True
    assert args.orders_enabled is False  # MUST always be False by default
