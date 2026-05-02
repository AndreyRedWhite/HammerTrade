#!/usr/bin/env python3
"""Interactive research pipeline wizard — builds and optionally runs the full pipeline command."""
import sys
import subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

_SCRIPT = str(Path(__file__).resolve().parent / "run_full_research_pipeline.sh")

_DEFAULTS = {
    "ticker": "SiM6",
    "class_code": "SPBFUT",
    "start": "2026-03-01",
    "end": "2026-04-10",
    "timeframe": "1m",
    "profile": "balanced",
    "env": "prod",
    "load": True,
    "grid": True,
    "walkforward_grid": True,
    "archive": True,
    "point_value_rub": "auto",
    "fallback_point_value_rub": "10",
    "tick_size": "auto",
    "fallback_tick_size": "0.5",
    "slippage_points": "0",
    "take_r": "1.0",
    "max_hold_bars": "30",
    "direction_filter": "all",
}


def parse_args():
    p = argparse.ArgumentParser(
        description="Interactive research pipeline wizard"
    )
    p.add_argument("--dry-run", action="store_true",
                   help="Build and print the command, do not execute it")
    p.add_argument("--yes", action="store_true",
                   help="Use defaults without interactive prompts and skip final confirmation")
    return p.parse_args()


def _ask(prompt: str, default) -> str:
    default_str = str(default) if not isinstance(default, bool) else ("Y" if default else "n")
    response = input(f"{prompt} [{default_str}]: ").strip()
    if not response:
        return default_str
    return response


def _ask_bool(prompt: str, default: bool) -> bool:
    response = _ask(prompt, "Y" if default else "n")
    return response.strip().lower() not in ("n", "no", "false", "0")


def collect_params(use_defaults: bool) -> dict:
    if use_defaults:
        return dict(_DEFAULTS)

    print()
    print("Research Pipeline Wizard")
    print("========================")
    print("Press Enter to accept the default value shown in [brackets].")
    print()

    d = {}
    d["ticker"] = _ask("Ticker", _DEFAULTS["ticker"])
    d["class_code"] = _ask("Class code", _DEFAULTS["class_code"])
    d["start"] = _ask("From date", _DEFAULTS["start"])
    d["end"] = _ask("To date", _DEFAULTS["end"])
    d["timeframe"] = _ask("Timeframe", _DEFAULTS["timeframe"])
    d["profile"] = _ask("Profile", _DEFAULTS["profile"])
    d["env"] = _ask("Environment", _DEFAULTS["env"])
    d["point_value_rub"] = _ask("Point value RUB", _DEFAULTS["point_value_rub"])
    d["fallback_point_value_rub"] = _ask("Fallback point value RUB", _DEFAULTS["fallback_point_value_rub"])
    d["tick_size"] = _ask("Tick size", _DEFAULTS["tick_size"])
    d["fallback_tick_size"] = _ask("Fallback tick size", _DEFAULTS["fallback_tick_size"])
    d["slippage_points"] = _ask("Slippage points for baseline", _DEFAULTS["slippage_points"])
    d["take_r"] = _ask("Take R for baseline", _DEFAULTS["take_r"])
    d["max_hold_bars"] = _ask("Max hold bars", _DEFAULTS["max_hold_bars"])
    d["direction_filter"] = _ask("Direction filter (all/BUY/SELL)", _DEFAULTS["direction_filter"])
    d["load"] = _ask_bool("Load candles from T-Bank?", _DEFAULTS["load"])
    d["grid"] = _ask_bool("Run grid backtest?", _DEFAULTS["grid"])
    d["walkforward_grid"] = _ask_bool("Run walk-forward grid?", _DEFAULTS["walkforward_grid"])
    d["archive"] = _ask_bool("Create archive?", _DEFAULTS["archive"])
    return d


def build_command(params: dict) -> list:
    cmd = ["bash", _SCRIPT]
    cmd += ["--ticker", params["ticker"]]
    cmd += ["--class-code", params["class_code"]]
    cmd += ["--from", params["start"]]
    cmd += ["--to", params["end"]]
    cmd += ["--timeframe", params["timeframe"]]
    cmd += ["--profile", params["profile"]]
    cmd += ["--env", params["env"]]
    cmd += ["--point-value-rub", str(params["point_value_rub"])]
    cmd += ["--fallback-point-value-rub", str(params["fallback_point_value_rub"])]
    cmd += ["--tick-size", str(params["tick_size"])]
    cmd += ["--fallback-tick-size", str(params["fallback_tick_size"])]
    cmd += ["--slippage-points", str(params["slippage_points"])]
    cmd += ["--take-r", str(params["take_r"])]
    cmd += ["--max-hold-bars", str(params["max_hold_bars"])]
    cmd += ["--direction-filter", str(params["direction_filter"])]

    if not params.get("load", True):
        cmd.append("--skip-load")
    if not params.get("grid", True):
        cmd.append("--skip-grid")
    if not params.get("walkforward_grid", True):
        cmd.append("--skip-walkforward-grid")
    if not params.get("archive", True):
        cmd.append("--no-archive")

    return cmd


def main():
    args = parse_args()

    params = collect_params(use_defaults=args.yes)

    cmd = build_command(params)
    cmd_str = " \\\n  ".join(cmd)

    print()
    print("About to run:")
    print("=============")
    print()
    print(f"  Ticker:           {params['ticker']}")
    print(f"  Class code:       {params['class_code']}")
    print(f"  Period:           {params['start']} -> {params['end']}")
    print(f"  Timeframe:        {params['timeframe']}")
    print(f"  Profile:          {params['profile']}")
    print(f"  Point value RUB:  {params['point_value_rub']}")
    print(f"  Tick size:        {params['tick_size']}")
    print(f"  Direction filter: {params['direction_filter']}")
    print(f"  Load candles:     {params.get('load', True)}")
    print(f"  Grid:             {params.get('grid', True)}")
    print(f"  Walk-fwd grid:    {params.get('walkforward_grid', True)}")
    print(f"  Archive:          {params.get('archive', True)}")
    print()
    print("Command:")
    print()
    print(f"  {cmd_str}")
    print()

    if args.dry_run:
        print("(dry-run: not executing)")
        return

    if not args.yes:
        confirm = input("Run? [Y/n]: ").strip().lower()
        if confirm in ("n", "no"):
            print("Aborted.")
            return

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
