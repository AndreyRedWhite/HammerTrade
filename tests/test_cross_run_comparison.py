import zipfile
from pathlib import Path

import pandas as pd
import pytest

from src.analytics.cross_run_comparison import (
    parse_manifest, build_comparison_row, build_comparison_df,
    generate_comparison_report,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_manifest(run_id="CRM6_1m_2026-03-01_2026-04-10_balanced",
                   ticker="CRM6", files=None) -> str:
    if files is None:
        files = [
            f"out/debug_simple_all_{run_id}.csv",
            f"out/backtest_trades_{run_id}.csv",
        ]
    lines = [
        f"Run ID: {run_id}",
        "Created at: 2026-04-30T20:01:30+0300",
        f"Ticker: {ticker}",
        "Class code: SPBFUT",
        "Timeframe: 1m",
        "Period: 2026-03-01 -> 2026-04-10",
        "Profile: balanced",
        "Direction filter: all",
        "Point value RUB: 1000.0",
        "Tick size: 0.001",
        "Tick size source: specs",
        "Skip load: true",
        "Skip grid: false",
        "Skip walkforward grid: true",
        "",
        "Files included:",
    ] + [f"- {f}" for f in files]
    return "\n".join(lines)


def _make_debug_csv(n_signals=3) -> str:
    rows = []
    for i in range(10):
        is_sig = i < n_signals
        rows.append({
            "timestamp": f"2026-03-01 10:{i:02d}:00",
            "instrument": "CRM6",
            "timeframe": "1m",
            "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0,
            "volume": 100,
            "is_signal": is_sig,
            "fail_reason": "pass" if is_sig else "range",
            "direction_candidate": "BUY",
        })
    return pd.DataFrame(rows).to_csv(index=False)


def _make_trades_csv() -> str:
    rows = [
        {"trade_id": 1, "direction": "BUY", "status": "closed",
         "net_pnl_rub": 200.0, "exit_reason": "take"},
        {"trade_id": 2, "direction": "BUY", "status": "closed",
         "net_pnl_rub": -100.0, "exit_reason": "stop"},
        {"trade_id": 3, "direction": "BUY", "status": "skipped_no_entry",
         "net_pnl_rub": None, "exit_reason": "none"},
    ]
    return pd.DataFrame(rows).to_csv(index=False)


def _make_grid_csv() -> str:
    rows = []
    for slip in [0, 1, 2]:
        rows.append({
            "scenario_id": slip + 1, "entry_mode": "close",
            "slippage_ticks": float(slip), "effective_slippage_points": slip * 0.001,
            "net_pnl_rub": 200.0 - slip * 50,
        })
    return pd.DataFrame(rows).to_csv(index=False)


def _make_wf_csv() -> str:
    rows = [
        {"period_key": "2026-W10", "net_pnl_rub": 150.0},
        {"period_key": "2026-W11", "net_pnl_rub": -50.0},
        {"period_key": "2026-W12", "net_pnl_rub": 80.0},
    ]
    return pd.DataFrame(rows).to_csv(index=False)


def _make_zip(tmp_path: Path, run_id: str, ticker: str,
              include_walkforward: bool = True) -> tuple:
    manifest_text = _make_manifest(run_id=run_id, ticker=ticker)
    zip_path = tmp_path / f"Actual_{run_id}.zip"
    manifest_path = tmp_path / f"Actual_{run_id}.manifest.txt"

    manifest_path.write_text(manifest_text)

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"out/debug_simple_all_{run_id}.csv", _make_debug_csv())
        zf.writestr(f"out/backtest_trades_{run_id}.csv", _make_trades_csv())
        zf.writestr(f"out/backtest_grid_results_{run_id}.csv", _make_grid_csv())
        if include_walkforward:
            zf.writestr(f"out/walkforward_period_results_{run_id}_week.csv", _make_wf_csv())

    return str(zip_path), str(manifest_path)


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_parse_manifest():
    text = _make_manifest()
    m = parse_manifest(text)
    assert m["Ticker"] == "CRM6"
    assert m["Tick size"] == "0.001"
    assert any("debug_simple_all" in f for f in m["files"])


def test_build_comparison_row(tmp_path):
    zip_path, manifest_path = _make_zip(tmp_path, "CRM6_1m_balanced", "CRM6")
    row = build_comparison_row(zip_path, manifest_path)
    assert row["ticker"] == "CRM6"
    assert row["signals"] == 3
    assert row["closed_trades"] == 2
    assert row["net_pnl_rub"] == pytest.approx(100.0)
    assert row["grid_scenarios"] == 3


def test_comparison_row_no_walkforward(tmp_path):
    zip_path, manifest_path = _make_zip(
        tmp_path, "BRK6_1m_balanced", "BRK6", include_walkforward=False
    )
    row = build_comparison_row(zip_path, manifest_path)
    assert row["periods_total"] is None
    assert row["profitable_periods"] is None


def test_build_comparison_df(tmp_path):
    zp1, mp1 = _make_zip(tmp_path, "CRM6_1m_balanced", "CRM6")
    zp2, mp2 = _make_zip(tmp_path, "BRK6_1m_balanced", "BRK6")
    df = build_comparison_df([zp1, zp2])
    assert len(df) == 2
    assert set(df["ticker"]) == {"CRM6", "BRK6"}


def test_comparison_csv_created(tmp_path):
    zp, mp = _make_zip(tmp_path, "CRM6_1m_balanced", "CRM6")
    df = build_comparison_df([zp])
    output = tmp_path / "comparison.csv"
    df.to_csv(output, index=False)
    assert output.exists()
    loaded = pd.read_csv(output)
    assert "ticker" in loaded.columns


def test_comparison_report_created(tmp_path):
    zp, mp = _make_zip(tmp_path, "CRM6_1m_balanced", "CRM6")
    df = build_comparison_df([zp])
    report = str(tmp_path / "comparison.md")
    generate_comparison_report(df, report, created_at="2026-05-01")
    assert Path(report).exists()
    content = Path(report).read_text()
    assert "# Cross-run Research Comparison" in content
    assert "CRM6" in content


def test_slippage_ticks_robustness_in_report(tmp_path):
    zp, mp = _make_zip(tmp_path, "CRM6_1m_balanced", "CRM6")
    df = build_comparison_df([zp])
    report = str(tmp_path / "comparison.md")
    generate_comparison_report(df, report)
    content = Path(report).read_text()
    assert "Slippage ticks robustness" in content
