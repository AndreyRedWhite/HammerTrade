"""Read-only fleet dashboard (Flask) over the same report engine.

Security:
  - HTTP Basic Auth, credentials from env DASHBOARD_USER / DASHBOARD_PASS.
    Fail-closed: refuses to start if not set.
  - Intended to bind 127.0.0.1 only; TLS + public exposure handled by nginx.
  - Strictly read-only: reads SQLite trade DBs + status JSON. No order paths,
    no writes, no mutating routes.
"""
from __future__ import annotations

import hmac
import html
import os
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, Response, request

from src.reporting.fleet import build_reports

BASE_DIR = Path(os.environ.get("HAMMERTRADE_BASE", ".")).resolve()

_STATUS_COLORS = {
    "PROMOTE": "#1a7f37", "ACTIVE": "#0969da",
    "WATCH": "#6e7781", "FREEZE": "#cf222e",
}


def _check_auth(user: str, pw: str) -> bool:
    exp_user = os.environ.get("DASHBOARD_USER", "")
    exp_pw = os.environ.get("DASHBOARD_PASS", "")
    if not exp_user or not exp_pw:
        return False  # fail-closed
    return (hmac.compare_digest(user or "", exp_user)
            and hmac.compare_digest(pw or "", exp_pw))


def requires_auth(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        a = request.authorization
        if not a or not _check_auth(a.username, a.password):
            return Response(
                "Authentication required", 401,
                {"WWW-Authenticate": 'Basic realm="HammerTrade Dashboard"'},
            )
        return f(*args, **kwargs)
    return wrapped


def _fmt(v, nd=0):
    if v is None:
        return "—"
    if isinstance(v, float) and v == float("inf"):
        return "∞"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _esc(v) -> str:
    return html.escape(str(v))


def _rows_html(reports) -> str:
    out = []
    for r in sorted(reports, key=lambda x: (x.status_class, x.svc.family, x.svc.unit)):
        m, w = r.lifetime, r.window
        short = r.svc.unit.replace("hammertrade-", "").replace(".service", "")
        color = _STATUS_COLORS.get(r.status_class, "#6e7781")
        live_color = "#1a7f37" if r.liveness == "OK" else "#cf222e"
        unit_warn = "" if r.svc.active == "active" else " ⛔"
        pnl_color = "#1a7f37" if m.pnl_rub > 0 else ("#cf222e" if m.pnl_rub < 0 else "#6e7781")
        out.append(
            "<tr>"
            f"<td class='l'>{_esc(short)}{unit_warn}</td>"
            f"<td>{_esc(r.svc.family)}</td>"
            f"<td>{_esc(r.svc.instrument)}</td>"
            f"<td>{_esc(r.svc.direction or '—')}</td>"
            f"<td>{w.trades}</td><td>{_fmt(w.pnl_rub)}</td>"
            f"<td>{m.trades}</td>"
            f"<td style='color:{pnl_color}'>{_fmt(m.pnl_rub)}</td>"
            f"<td>{_fmt(m.pf, 2)}</td><td>{_fmt(m.wr, 0)}</td>"
            f"<td>{_fmt(m.max_dd_rub)}</td><td>{_fmt(m.avg_win)}</td><td>{_fmt(m.avg_loss)}</td>"
            f"<td>{r.open_positions}</td>"
            f"<td style='color:{live_color}'>{_esc(r.liveness)}</td>"
            f"<td>{r.api_errors}</td>"
            f"<td style='color:{color};font-weight:600'>{_esc(r.status_class)}</td>"
            "</tr>"
        )
    return "".join(out)


def _section(title: str, reports, now, window_days) -> str:
    by_class: dict[str, int] = {}
    for r in reports:
        by_class[r.status_class] = by_class.get(r.status_class, 0) + 1
    win_pnl = sum(r.window.pnl_rub for r in reports)
    life_pnl = sum(r.lifetime.pnl_rub for r in reports)
    inactive = sum(1 for r in reports if r.svc.active != "active")
    degraded = sum(1 for r in reports if r.liveness != "OK")
    summary = (f"{len(reports)} services · "
               + " · ".join(f"{k}={v}" for k, v in sorted(by_class.items()))
               + f" · window PnL {win_pnl:+.0f}₽ · lifetime {life_pnl:+.0f}₽ · "
               f"{len(reports)-inactive}/{len(reports)} active, {degraded} degraded")
    head = ("<tr><th>service</th><th>fam</th><th>instr</th><th>dir</th>"
            "<th>w.tr</th><th>w.pnl</th><th>tr</th><th>PnL</th><th>PF</th><th>WR%</th>"
            "<th>MaxDD</th><th>avgW</th><th>avgL</th><th>open</th><th>live</th>"
            "<th>apiErr</th><th>STATUS</th></tr>")
    return (f"<h2>{_esc(title)}</h2><p class='sum'>{_esc(summary)}</p>"
            f"<table>{head}{_rows_html(reports)}</table>")


_CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:18px;background:#f6f8fa;color:#1f2328}
h1{font-size:20px;margin:0 0 4px} h2{font-size:15px;margin:20px 0 6px}
.meta{color:#6e7781;font-size:12px;margin-bottom:8px}
.sum{font-size:12px;color:#424a53;margin:2px 0 8px}
table{border-collapse:collapse;width:100%;background:#fff;font-size:12px;
 box-shadow:0 1px 2px rgba(0,0,0,.06);border-radius:6px;overflow:hidden}
th,td{padding:5px 8px;text-align:right;border-bottom:1px solid #eaeef2;white-space:nowrap}
th{background:#f0f3f6;font-weight:600;text-align:right;position:sticky;top:0}
td.l,th:first-child{text-align:left}
tr:hover td{background:#f6f8fa}
.cand{background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:10px;margin-top:8px;font-size:13px}
"""


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    @app.route("/")
    @requires_auth
    def index():
        now = datetime.now(tz=timezone.utc)
        daily = build_reports(BASE_DIR, now, 1)
        weekly = build_reports(BASE_DIR, now, 7)

        cands = [r for r in weekly if r.sandbox_capable]
        cand_html = "<div class='cand'>"
        if cands:
            for r in cands:
                tag = "SANDBOX (running)" if r.svc.family == "sandbox" else "PROMOTE candidate"
                cand_html += (f"• <b>{_esc(r.svc.unit.replace('hammertrade-','').replace('.service',''))}</b> "
                              f"[{tag}] — {_esc(r.svc.family)} {_esc(r.svc.instrument)} "
                              f"{_esc(r.svc.direction)}: {r.lifetime.trades} tr, "
                              f"PF {_fmt(r.lifetime.pf,2)}, WR {_fmt(r.lifetime.wr,0)}%, "
                              f"PnL {_fmt(r.lifetime.pnl_rub)}₽<br>")
        else:
            cand_html += "none (no PROMOTE strategies; sandbox not found)"
        cand_html += "</div>"

        page = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta http-equiv='refresh' content='60'>"
            "<title>HammerTrade Fleet</title>"
            f"<style>{_CSS}</style></head><body>"
            "<h1>HammerTrade — Fleet Dashboard</h1>"
            f"<div class='meta'>Generated {now.strftime('%Y-%m-%d %H:%M UTC')} · "
            "auto-refresh 60s · PF/WR/MaxDD/avg are LIFETIME · read-only</div>"
            "<h2>Sandbox / live-capable candidates</h2>" + cand_html
            + _section("Daily (last 24h)", daily, now, 1)
            + _section("Weekly (last 7d)", weekly, now, 7)
            + "</body></html>"
        )
        return Response(page, mimetype="text/html")

    return app
