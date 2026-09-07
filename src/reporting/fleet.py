"""Fleet report assembly: discover services, read trades, build daily/weekly report.

Discovery is driven by the live systemd units (source of truth), so new
services appear automatically. Runs on the server (needs systemctl + the
SQLite DBs); --no-systemd falls back to scanning data/paper for DBs.
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.reporting.metrics import (
    Metrics,
    Trade,
    classify,
    compute_metrics,
    cumulative_curve,
    filter_window,
)

# script basename -> (family, table, pnl_col, exit_ts_col)
SCRIPT_FAMILY = {
    "run_paper_trader.py":            ("hammer", "paper_trades", "pnl_rub", "exit_timestamp"),
    "run_momentum_paper_trader.py":   ("momentum", "momentum_paper_trades", "pnl_rub", "exit_timestamp"),
    "run_orb_paper_trader.py":        ("orb", "orb_paper_trades", "pnl_rub", "exit_timestamp"),
    "run_orf_paper_trader.py":        ("orf", "orf_paper_trades", "pnl_rub", "exit_timestamp"),
    "run_vwap_reversion_paper_trader.py": ("vwap", "vwap_paper_trades", "pnl_rub", "exit_timestamp"),
    # Three PnL columns exist for pairs; the funnel must read the strongest.
    #   pnl_rub           entry AND exit at the signal bar close — both untradeable
    #   pnl_rub_market    entry at next open, exit STILL at the signal close
    #   pnl_rub_realistic entry AND exit at the next bar's open
    # Only the last one prices both ends at something a live trader could get.
    # Measured 2026-09: the gap between pnl_rub and pnl_rub_realistic is
    # 4.5-22.2 bps/trade and flips three of four tested pairs configurations from
    # positive to negative — so reading the wrong column here does not shade a
    # verdict, it inverts it. COALESCE only falls back for pre-migration rows.
    "run_pairs_paper_trader.py":      ("pairs", "pairs_trades",
                                       "COALESCE(pnl_rub_realistic, pnl_rub_market, pnl_rub)",
                                       "exit_timestamp"),
    "run_hammer_maxhold5_sandbox.py": ("sandbox", "sandbox_trades", "net_pnl_rub", "exit_time"),
    "run_pairs_sandbox_trader.py":    ("sandbox", "pair_trades", "net_pnl_rub", "exit_ts"),
    "run_orb_sandbox_trader.py":      ("sandbox", "orb_trades", "net_pnl_rub", "exit_ts"),
    "run_carry_sandbox_trader.py":    ("sandbox", "carry_trades", "net_pnl_rub", "exit_ts"),
    "run_volatility_breakout_sandbox_trader.py":
        ("sandbox", "volatility_breakout_trades", "net_pnl_rub", "exit_ts"),
    "run_xsec_momentum_sandbox_trader.py":
        ("sandbox", "xsec_trades", "net_pnl_rub", "exit_ts"),
}


@dataclass
class Service:
    unit: str
    family: str
    table: str
    pnl_col: str
    exit_ts_col: str
    db_path: Optional[str] = None
    status_path: Optional[str] = None
    instrument: str = "?"
    direction: str = ""
    active: str = "?"
    restarts: str = "?"


@dataclass
class ServiceReport:
    svc: Service
    window: Metrics
    lifetime: Metrics
    open_positions: int
    liveness: str
    api_errors: int
    status_class: str
    sandbox_capable: bool = False
    curve: list[float] = field(default_factory=list)  # lifetime cumulative PnL
    first_trade_ts: Optional[datetime] = None
    last_trade_ts: Optional[datetime] = None
    restarts: int = 0
    trades: list = field(default_factory=list)  # closed Trade objects (portfolio analytics)


# ── discovery ─────────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 15) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


def _exec_tokens(unit: str) -> list[str]:
    """Tokenize the ExecStart command (joining backslash continuations)."""
    text = _run(["systemctl", "cat", unit])
    joined, buf, in_exec = [], "", False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("ExecStart="):
            in_exec = True
            buf = s[len("ExecStart="):]
        elif in_exec:
            buf += " " + s
        if in_exec:
            if s.endswith("\\"):
                buf = buf.rstrip("\\")
            else:
                joined = buf.replace("\\", " ").split()
                break
    return joined


def _arg(tokens: list[str], name: str) -> Optional[str]:
    """Value of --name X or --name=X."""
    for i, t in enumerate(tokens):
        if t == name and i + 1 < len(tokens):
            return tokens[i + 1]
        if t.startswith(name + "="):
            return t.split("=", 1)[1]
    return None


def _walk_yaml_paths(node, out: dict):
    """Recursively collect first .sqlite/.json and ticker/direction from a config."""
    if isinstance(node, dict):
        for k, v in node.items():
            kl = str(k).lower()
            if isinstance(v, str):
                if v.endswith(".sqlite") and "db" not in out:
                    out["db"] = v
                elif v.endswith(".json") and "status" not in out:
                    out["status"] = v
                elif kl == "ticker" and "ticker" not in out:
                    out["ticker"] = v
                elif kl == "direction" and "direction" not in out:
                    out["direction"] = v
            else:
                _walk_yaml_paths(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_yaml_paths(v, out)


def _from_config(cfg_path: str, base: Path) -> dict:
    try:
        import yaml
        with (base / cfg_path).open() as f:
            data = yaml.safe_load(f)
    except Exception:
        return {}
    out: dict = {}
    _walk_yaml_paths(data, out)
    return out


def discover_services(base: Path) -> list[Service]:
    units_raw = _run(["systemctl", "list-units", "hammertrade-*.service",
                      "--type=service", "--all", "--no-legend", "--no-pager"])
    services: list[Service] = []
    for line in units_raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0].lstrip("●").strip()
        if not unit.endswith(".service"):
            continue
        tokens = _exec_tokens(unit)
        script = next((t for t in tokens if t.startswith("scripts/")), "")
        script_base = script.split("/")[-1]
        fam = SCRIPT_FAMILY.get(script_base)
        if fam is None:
            # sandbox service uses a different script name — detect by config dir
            cfg = _arg(tokens, "--config") or ""
            if "sandbox" in cfg:
                fam = SCRIPT_FAMILY["run_hammer_maxhold5_sandbox.py"]
            else:
                continue
        family, table, pnl_col, exit_col = fam

        db = _arg(tokens, "--state-db")
        status = _arg(tokens, "--status-file")
        ticker = direction = None
        cfg = _arg(tokens, "--config")
        if (db is None or status is None) and cfg:
            info = _from_config(cfg, base)
            db = db or info.get("db")
            status = status or info.get("status")
            ticker = info.get("ticker")
            direction = info.get("direction")

        svc = Service(unit=unit, family=family, table=table, pnl_col=pnl_col,
                      exit_ts_col=exit_col, db_path=db, status_path=status,
                      instrument=ticker or "?", direction=direction or "")
        active = _run(["systemctl", "is-active", unit]).strip() or "?"
        restarts = _run(["systemctl", "show", unit, "-p", "NRestarts", "--value"]).strip() or "?"
        svc.active, svc.restarts = active, restarts
        services.append(svc)
    return sorted(services, key=lambda s: (s.family, s.unit))


# ── trade + status IO ─────────────────────────────────────────────────────────

def _parse_ts(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def load_trades(svc: Service, base: Path) -> tuple[list[Trade], int]:
    """Return (closed_trades, open_count). Closed = exit_ts AND pnl present."""
    if not svc.db_path:
        return [], 0
    p = base / svc.db_path
    if not p.exists():
        return [], 0
    try:
        conn = sqlite3.connect(str(p))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT direction, {svc.pnl_col} AS pnl, {svc.exit_ts_col} AS ets, status "
            f"FROM {svc.table}"
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return [], 0
    closed, open_n = [], 0
    for r in rows:
        ets = _parse_ts(r["ets"])
        pnl = r["pnl"]
        if ets is not None and pnl is not None:
            closed.append(Trade(exit_ts=ets, pnl_rub=float(pnl), direction=r["direction"] or ""))
        else:
            open_n += 1
    return closed, open_n


def read_status(svc: Service, base: Path) -> dict:
    if not svc.status_path:
        return {}
    p = base / svc.status_path
    try:
        with p.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _liveness_of(status: dict) -> str:
    live = status.get("trading_liveness_status")
    if live:
        return live
    fetch = status.get("fetch_status") or status.get("last_fetch_status") or ""
    if status.get("market_open", True) and fetch in ("API_ERROR", "API_TIMEOUT", "NO_CANDLES"):
        return fetch
    return "OK"


def _api_errors_of(status: dict) -> int:
    for k in ("total_api_errors", "consecutive_api_errors", "api_errors"):
        if isinstance(status.get(k), int):
            return status[k]
    return 0


# ── assembly ──────────────────────────────────────────────────────────────────

def build_reports(base: Path, now: datetime, window_days: int) -> list[ServiceReport]:
    reports = []
    for svc in discover_services(base):
        closed, open_n = load_trades(svc, base)
        status = read_status(svc, base)
        # enrich instrument/direction from status if unknown
        if svc.family == "pairs":
            svc.instrument = "BASKET"
            svc.direction = svc.direction or "NEUTRAL"
        if svc.instrument == "?":
            svc.instrument = str(status.get("ticker") or status.get("pairs") or "?")[:16]
        if not svc.direction:
            svc.direction = str(status.get("direction") or "")
        lifetime = compute_metrics(closed)
        window = compute_metrics(filter_window(closed, now, window_days))
        liveness = _liveness_of(status)
        status_class = classify(svc.family, lifetime, liveness)
        exits = sorted(t.exit_ts for t in closed) if closed else []
        try:
            restarts = int(svc.restarts)
        except (ValueError, TypeError):
            restarts = 0
        reports.append(ServiceReport(
            svc=svc, window=window, lifetime=lifetime, open_positions=open_n,
            liveness=liveness, api_errors=_api_errors_of(status),
            status_class=status_class,
            sandbox_capable=(svc.family == "sandbox" or status_class == "PROMOTE"),
            curve=cumulative_curve(closed),
            first_trade_ts=exits[0] if exits else None,
            last_trade_ts=exits[-1] if exits else None,
            restarts=restarts,
            trades=closed,
        ))
    return reports


# ── formatting ────────────────────────────────────────────────────────────────

def _fmt(v, nd=0):
    if v is None:
        return "—"
    if isinstance(v, float) and v == float("inf"):
        return "∞"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def render_markdown(reports: list[ServiceReport], now: datetime,
                    period_label: str, window_days: int) -> str:
    L = []
    L.append(f"# Fleet Report — {period_label}")
    L.append(f"*Generated {now.strftime('%Y-%m-%d %H:%M UTC')} · window = last {window_days}d · "
             f"PF/WR/MaxDD/avg are LIFETIME*")
    L.append("")

    # summary
    by_class: dict[str, int] = {}
    for r in reports:
        by_class[r.status_class] = by_class.get(r.status_class, 0) + 1
    win_pnl = sum(r.window.pnl_rub for r in reports)
    life_pnl = sum(r.lifetime.pnl_rub for r in reports)
    degraded = [r for r in reports if r.liveness != "OK"]
    inactive = [r for r in reports if r.svc.active != "active"]
    L.append(f"**{len(reports)} services** · "
             + " · ".join(f"{k}={v}" for k, v in sorted(by_class.items())))
    L.append(f"**PnL** window={win_pnl:+.0f}₽ · lifetime={life_pnl:+.0f}₽")
    L.append(f"**Health**: {len(reports)-len(inactive)}/{len(reports)} units active, "
             f"{len(degraded)} degraded liveness")
    L.append("")

    # main table
    hdr = ("| service | fam | instr | dir | w.tr | w.pnl | tr | PnL | PF | WR% | "
           "MaxDD | avgW | avgL | open | live | apiErr | STATUS |")
    sep = "|" + "---|" * 17
    L.append(hdr)
    L.append(sep)
    for r in sorted(reports, key=lambda x: (x.status_class, x.svc.family, x.svc.unit)):
        m, w = r.lifetime, r.window
        short = r.svc.unit.replace("hammertrade-", "").replace(".service", "")
        L.append("| " + " | ".join([
            short, r.svc.family, r.svc.instrument, r.svc.direction or "—",
            str(w.trades), _fmt(w.pnl_rub), str(m.trades), _fmt(m.pnl_rub),
            _fmt(m.pf, 2), _fmt(m.wr, 0), _fmt(m.max_dd_rub), _fmt(m.avg_win),
            _fmt(m.avg_loss), str(r.open_positions), r.liveness, str(r.api_errors),
            r.status_class,
        ]) + " |")
    L.append("")

    # sandbox / live-capable candidates
    cands = [r for r in reports if r.sandbox_capable]
    L.append("## Sandbox / live-capable candidates")
    if cands:
        for r in cands:
            tag = "SANDBOX (running)" if r.svc.family == "sandbox" else "PROMOTE candidate"
            L.append(f"- **{r.svc.unit.replace('hammertrade-','').replace('.service','')}** "
                     f"[{tag}] — {r.svc.family} {r.svc.instrument} {r.svc.direction}: "
                     f"lifetime {r.lifetime.trades} tr, PF {_fmt(r.lifetime.pf,2)}, "
                     f"WR {_fmt(r.lifetime.wr,0)}%, PnL {_fmt(r.lifetime.pnl_rub)}₽")
    else:
        L.append("- none (no PROMOTE-classified strategies; sandbox service not found)")
    L.append("")

    # attention
    attn = [r for r in reports if r.status_class == "FREEZE" or r.liveness != "OK"
            or r.svc.active != "active"]
    if attn:
        L.append("## ⚠️ Needs attention")
        for r in attn:
            issues = []
            if r.svc.active != "active":
                issues.append(f"unit {r.svc.active}")
            if r.liveness != "OK":
                issues.append(f"liveness {r.liveness}")
            if r.status_class == "FREEZE":
                issues.append(f"FREEZE (PF {_fmt(r.lifetime.pf,2)} @ {r.lifetime.trades}tr)")
            L.append(f"- {r.svc.unit.replace('hammertrade-','').replace('.service','')}: "
                     + ", ".join(issues))
        L.append("")

    return "\n".join(L)
