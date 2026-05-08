"""Tests for src/paper/diagnostics.py — MVP-1.9."""
import csv
import sqlite3
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.paper.diagnostics import (
    _bars_bucket,
    _reward_bucket,
    _risk_bucket,
    _rr_bucket,
    build_markdown_report,
    compute_summary,
    enrich_trade,
    load_from_csv,
    load_from_sqlite,
    run_diagnostics,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

_TS = "2026-05-04T09:39:00+00:00"

def _trade(
    trade_id="t1",
    direction="SELL",
    entry=100.0,
    stop=110.0,
    take=90.0,
    exit_price=90.0,
    exit_reason="TAKE",
    status="CLOSED",
    pnl_rub=100.0,
    bars_held=3,
    pnl_points=10.0,
) -> dict:
    return {
        "trade_id": trade_id,
        "ticker": "SiM6",
        "class_code": "SPBFUT",
        "timeframe": "1m",
        "profile": "balanced",
        "direction": direction,
        "signal_timestamp": _TS,
        "entry_timestamp": _TS,
        "entry_price": entry,
        "stop_price": stop,
        "take_price": take,
        "status": status,
        "exit_timestamp": _TS,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pnl_points": pnl_points,
        "pnl_rub": pnl_rub,
        "bars_held": bars_held,
        "created_at": _TS,
        "updated_at": _TS,
    }


def _sqlite_db(tmp_path: Path, trades: list[dict]) -> Path:
    db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE paper_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT, class_code TEXT, timeframe TEXT, profile TEXT,
            direction TEXT, signal_timestamp TEXT, entry_timestamp TEXT,
            entry_price REAL, stop_price REAL, take_price REAL,
            status TEXT, exit_timestamp TEXT, exit_price REAL,
            exit_reason TEXT, pnl_points REAL, pnl_rub REAL,
            bars_held INTEGER, created_at TEXT, updated_at TEXT
        )
    """)
    for t in trades:
        conn.execute(
            "INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                t["trade_id"], t["ticker"], t["class_code"], t["timeframe"], t["profile"],
                t["direction"], t["signal_timestamp"], t["entry_timestamp"],
                t["entry_price"], t["stop_price"], t["take_price"],
                t["status"], t.get("exit_timestamp"), t.get("exit_price"),
                t.get("exit_reason"), t.get("pnl_points"), t.get("pnl_rub"),
                t.get("bars_held", 0), t["created_at"], t["updated_at"],
            ),
        )
    conn.commit()
    conn.close()
    return db


def _csv_file(tmp_path: Path, trades: list[dict]) -> Path:
    path = tmp_path / "trades.csv"
    if not trades:
        path.write_text("trade_id\n")
        return path
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
        writer.writeheader()
        writer.writerows(trades)
    return path


# ── 1. SELL risk/reward ────────────────────────────────────────────────────────

def test_sell_rr():
    # entry=100, stop=110, take=90, exit=90 → risk=10, reward=10, actual=10, rr=1.0
    e, w = enrich_trade(_trade(direction="SELL", entry=100, stop=110, take=90, exit_price=90))
    assert e["risk_points"] == pytest.approx(10.0)
    assert e["reward_points"] == pytest.approx(10.0)
    assert e["actual_points"] == pytest.approx(10.0)
    assert e["rr"] == pytest.approx(1.0)


# ── 2. BUY risk/reward ─────────────────────────────────────────────────────────

def test_buy_rr():
    # entry=100, stop=90, take=110, exit=110 → risk=10, reward=10, actual=10, rr=1.0
    e, w = enrich_trade(_trade(direction="BUY", entry=100, stop=90, take=110, exit_price=110,
                                exit_reason="TAKE", pnl_rub=100))
    assert e["risk_points"] == pytest.approx(10.0)
    assert e["reward_points"] == pytest.approx(10.0)
    assert e["actual_points"] == pytest.approx(10.0)
    assert e["rr"] == pytest.approx(1.0)


# ── 3. LOW_RR flag ────────────────────────────────────────────────────────────

def test_low_rr_flag():
    # reward=5, risk=10 → rr=0.5 < 0.8 → LOW_RR
    e, _ = enrich_trade(_trade(direction="SELL", entry=100, stop=110, take=95, exit_price=95))
    assert "LOW_RR" in e["diagnostic_flags"]


def test_no_low_rr_when_rr_ok():
    # rr=1.0 → no LOW_RR
    e, _ = enrich_trade(_trade(direction="SELL", entry=100, stop=110, take=90, exit_price=90))
    assert "LOW_RR" not in e["diagnostic_flags"]


# ── 4. TINY_TAKE flag ─────────────────────────────────────────────────────────

def test_tiny_take_flag():
    # reward=3 < 5 → TINY_TAKE
    e, _ = enrich_trade(_trade(direction="SELL", entry=100, stop=110, take=97, exit_price=97))
    assert "TINY_TAKE" in e["diagnostic_flags"]


def test_no_tiny_take_when_reward_ok():
    e, _ = enrich_trade(_trade(direction="SELL", entry=100, stop=110, take=90, exit_price=90))
    assert "TINY_TAKE" not in e["diagnostic_flags"]


# ── 5. BIG_RISK flag ──────────────────────────────────────────────────────────

def test_big_risk_flag():
    # risk=50 > 40 → BIG_RISK
    e, _ = enrich_trade(_trade(direction="SELL", entry=100, stop=150, take=90, exit_price=90))
    assert "BIG_RISK" in e["diagnostic_flags"]


def test_no_big_risk_when_risk_ok():
    e, _ = enrich_trade(_trade(direction="SELL", entry=100, stop=110, take=90, exit_price=90))
    assert "BIG_RISK" not in e["diagnostic_flags"]


# ── 6. ONE_BAR_STOP flag ──────────────────────────────────────────────────────

def test_one_bar_stop_flag():
    e, _ = enrich_trade(_trade(exit_reason="STOP", bars_held=1, pnl_rub=-100))
    assert "ONE_BAR_STOP" in e["diagnostic_flags"]


def test_no_one_bar_stop_when_multi_bar():
    e, _ = enrich_trade(_trade(exit_reason="STOP", bars_held=5, pnl_rub=-100))
    assert "ONE_BAR_STOP" not in e["diagnostic_flags"]


# ── 7. Report doesn't crash on empty trades ───────────────────────────────────

def test_report_empty_trades():
    result = DiagnosticsResultFromEmpty()
    md = build_markdown_report(
        enriched=[], summary=result["summary"], groups=result["groups"],
        hypotheses=[], warnings=[], source_label="test",
        ticker="SiM6", direction="SELL",
        generated_at="2026-01-01T00:00:00Z",
    )
    assert "Paper Trading Diagnostics" in md
    assert "Нет данных" in md


def DiagnosticsResultFromEmpty():
    from src.paper.diagnostics import compute_group_stats, compute_summary
    enriched: list = []
    summary = compute_summary(enriched)
    groups = {k: compute_group_stats(enriched, k) for k in
              ["entry_date_msk", "entry_hour_msk", "exit_reason",
               "risk_bucket", "reward_bucket", "rr_bucket", "bars_bucket", "diagnostic_flags"]}
    return {"summary": summary, "groups": groups}


# ── 8. Report doesn't crash on missing optional fields ────────────────────────

def test_enrich_missing_optional_fields():
    row = {
        "trade_id": "t_min",
        "ticker": "SiM6",
        "class_code": "SPBFUT",
        "timeframe": "1m",
        "profile": "balanced",
        "direction": "SELL",
        "signal_timestamp": None,
        "entry_timestamp": _TS,
        "entry_price": 100.0,
        "stop_price": 110.0,
        "take_price": 90.0,
        "status": "OPEN",
        "exit_timestamp": None,
        "exit_price": None,
        "exit_reason": None,
        "pnl_points": None,
        "pnl_rub": None,
        "bars_held": 0,
        "created_at": _TS,
        "updated_at": _TS,
    }
    e, w = enrich_trade(row)
    assert e["pnl_sign"] == "UNKNOWN"
    assert e["rr_bucket"] in ("RR_UNKNOWN", "RR_LT_0_8", "RR_0_8_1_0", "RR_1_0_1_2", "RR_GT_1_2")
    assert "OPEN_TRADE" in e["diagnostic_flags"]


# ── 9. SQLite reader ──────────────────────────────────────────────────────────

def test_sqlite_reader(tmp_path):
    db = _sqlite_db(tmp_path, [_trade("t1"), _trade("t2")])
    rows, warnings, source = load_from_sqlite(str(db))
    assert len(rows) == 2
    assert not warnings
    assert "SQLite" in source


def test_sqlite_missing_file(tmp_path):
    rows, warnings, source = load_from_sqlite(str(tmp_path / "nope.sqlite"))
    assert rows == []
    assert warnings
    assert source == ""


# ── 10. CSV fallback ──────────────────────────────────────────────────────────

def test_csv_fallback(tmp_path):
    f = _csv_file(tmp_path, [_trade("t1"), _trade("t2")])
    rows, warnings, source = load_from_csv(str(f))
    assert len(rows) == 2
    assert "CSV fallback" in source


def test_csv_missing_file(tmp_path):
    rows, warnings, source = load_from_csv(str(tmp_path / "nope.csv"))
    assert rows == []
    assert warnings
    assert source == ""


# ── Buckets ───────────────────────────────────────────────────────────────────

def test_risk_buckets():
    assert _risk_bucket(5) == "RISK_000_010"
    assert _risk_bucket(10) == "RISK_000_010"
    assert _risk_bucket(11) == "RISK_011_025"
    assert _risk_bucket(25) == "RISK_011_025"
    assert _risk_bucket(26) == "RISK_026_050"
    assert _risk_bucket(51) == "RISK_051_PLUS"
    assert _risk_bucket(None) == "RISK_UNKNOWN"


def test_reward_buckets():
    assert _reward_bucket(3) == "REWARD_LT_005"
    assert _reward_bucket(5) == "REWARD_005_010"
    assert _reward_bucket(10) == "REWARD_005_010"
    assert _reward_bucket(11) == "REWARD_011_025"
    assert _reward_bucket(51) == "REWARD_051_PLUS"
    assert _reward_bucket(None) == "REWARD_UNKNOWN"


def test_rr_buckets():
    assert _rr_bucket(0.5) == "RR_LT_0_8"
    assert _rr_bucket(0.8) == "RR_0_8_1_0"
    assert _rr_bucket(0.95) == "RR_0_8_1_0"
    assert _rr_bucket(1.0) == "RR_1_0_1_2"
    assert _rr_bucket(1.2) == "RR_GT_1_2"
    assert _rr_bucket(None) == "RR_UNKNOWN"


def test_bars_buckets():
    assert _bars_bucket(1) == "BARS_001"
    assert _bars_bucket(2) == "BARS_002_003"
    assert _bars_bucket(3) == "BARS_002_003"
    assert _bars_bucket(4) == "BARS_004_010"
    assert _bars_bucket(10) == "BARS_004_010"
    assert _bars_bucket(11) == "BARS_011_PLUS"
    assert _bars_bucket(None) == "BARS_UNKNOWN"


# ── run_diagnostics integration ───────────────────────────────────────────────

def test_run_diagnostics_sqlite(tmp_path):
    db = _sqlite_db(tmp_path, [_trade("t1", pnl_rub=500), _trade("t2", pnl_rub=-200)])
    result = run_diagnostics(db_path=str(db), csv_fallback="no.csv")
    assert result.summary["total_trades"] == 2
    assert result.summary["net_pnl_rub"] == pytest.approx(300.0)
    assert len(result.enriched) == 2
    for e in result.enriched:
        assert "risk_points" in e
        assert "diagnostic_flags" in e


def test_run_diagnostics_csv_fallback(tmp_path):
    csv_f = _csv_file(tmp_path, [_trade("t1", pnl_rub=100)])
    result = run_diagnostics(db_path="no.sqlite", csv_fallback=str(csv_f))
    assert result.summary["total_trades"] == 1
    assert "CSV fallback" in result.source_label


def test_run_diagnostics_no_data(tmp_path):
    result = run_diagnostics(db_path="no.sqlite", csv_fallback="no.csv")
    assert result.summary["total_trades"] == 0
    assert result.warnings
