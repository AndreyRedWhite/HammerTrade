"""Read-only fleet dashboard (Flask) over the same report engine.

Security:
  - HTTP Basic Auth, credentials from env DASHBOARD_USER / DASHBOARD_PASS.
    Fail-closed: refuses to authenticate if not set.
  - Intended to bind 127.0.0.1 only; TLS + public exposure handled by nginx.
  - Strictly read-only: reads SQLite trade DBs + status JSON. No order paths,
    no writes, no mutating routes.

UI: one sortable table (click any header; sort persists via localStorage),
summary cards, status badges, candidates section. Lifetime metrics + 24h/7d
PnL columns.
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

_STATUS = {
    "PROMOTE": ("#1a7f37", "#dafbe1"),
    "ACTIVE":  ("#0969da", "#ddf4ff"),
    "WATCH":   ("#9a6700", "#fff8c5"),
    "FREEZE":  ("#cf222e", "#ffebe9"),
}
_STATUS_RANK = {"FREEZE": 0, "WATCH": 1, "ACTIVE": 2, "PROMOTE": 3}


def _check_auth(user: str, pw: str) -> bool:
    exp_user = os.environ.get("DASHBOARD_USER", "")
    exp_pw = os.environ.get("DASHBOARD_PASS", "")
    if not exp_user or not exp_pw:
        return False
    return (hmac.compare_digest(user or "", exp_user)
            and hmac.compare_digest(pw or "", exp_pw))


def requires_auth(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        a = request.authorization
        if not a or not _check_auth(a.username, a.password):
            return Response("Authentication required", 401,
                            {"WWW-Authenticate": 'Basic realm="HammerTrade Dashboard"'})
        return f(*args, **kwargs)
    return wrapped


def _fmt(v, nd=0):
    if v is None:
        return "—"
    if isinstance(v, float) and v == float("inf"):
        return "∞"
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    return str(v)


def _num(v) -> str:
    """data-sort value: numeric or '' (treated as always-last in JS)."""
    if v is None:
        return ""
    if isinstance(v, float) and v == float("inf"):
        return "999999999"
    return str(v)


def _esc(v) -> str:
    return html.escape(str(v))


def _pnl_cell(v) -> str:
    color = "#1a7f37" if (isinstance(v, (int, float)) and v > 0) else \
            ("#cf222e" if (isinstance(v, (int, float)) and v < 0) else "#57606a")
    return f"<td data-sort='{_num(v)}' style='color:{color};font-weight:600'>{_fmt(v)}</td>"


_CSS = """
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;
 margin:0;background:#f6f8fa;color:#1f2328}
.wrap{max-width:1280px;margin:0 auto;padding:18px}
h1{font-size:20px;margin:0 0 2px}
.meta{color:#6e7781;font-size:12px;margin-bottom:14px}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}
.card{background:#fff;border:1px solid #d0d7de;border-radius:10px;padding:12px 16px;
 min-width:120px;box-shadow:0 1px 2px rgba(27,31,36,.04)}
.card .k{font-size:11px;color:#6e7781;text-transform:uppercase;letter-spacing:.04em}
.card .v{font-size:22px;font-weight:700;margin-top:2px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}
.chip{font-size:12px;font-weight:600;padding:2px 9px;border-radius:999px}
.pos{color:#1a7f37}.neg{color:#cf222e}
h2{font-size:14px;margin:20px 0 8px}
.cand{display:flex;flex-direction:column;gap:6px}
.candcard{background:#fff;border:1px solid #d0d7de;border-left:4px solid #1a7f37;
 border-radius:8px;padding:9px 12px;font-size:13px}
.tablewrap{background:#fff;border:1px solid #d0d7de;border-radius:10px;overflow:auto;
 box-shadow:0 1px 2px rgba(27,31,36,.04)}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:7px 10px;text-align:right;border-bottom:1px solid #eaeef2;white-space:nowrap}
th{background:#f6f8fa;font-weight:600;position:sticky;top:0;cursor:pointer;user-select:none}
th:hover{background:#eef1f4}
th .ar{color:#0969da;font-size:10px}
td.l,th.l{text-align:left}
tbody tr:hover td{background:#f6f8fa}
.badge{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}
.hint{color:#6e7781;font-size:11px;margin:6px 2px 0}
"""

_JS = """
function val(td){var d=td.getAttribute('data-sort');if(d===null)d=td.textContent.trim();
 if(d===''){return null;} var n=parseFloat(d.replace(/,/g,'')); return isNaN(n)?d.toLowerCase():n;}
function sortBy(idx){
 var t=document.getElementById('fleet'),tb=t.tBodies[0];
 var rows=Array.prototype.slice.call(tb.rows);
 var cur=t.getAttribute('data-col'), asc=t.getAttribute('data-asc')==='1';
 if(cur==idx){asc=!asc;}else{asc=false;} // new column -> desc first
 rows.sort(function(a,b){
   var x=val(a.cells[idx]),y=val(b.cells[idx]);
   if(x===null&&y===null)return 0; if(x===null)return 1; if(y===null)return -1; // nulls last
   if(x<y)return asc?-1:1; if(x>y)return asc?1:-1; return 0;});
 rows.forEach(function(r){tb.appendChild(r);});
 t.setAttribute('data-col',idx);t.setAttribute('data-asc',asc?'1':'0');
 var ths=t.tHead.rows[0].cells;
 for(var i=0;i<ths.length;i++){var s=ths[i].querySelector('.ar');if(s)s.textContent='';}
 var s=ths[idx].querySelector('.ar');if(s)s.textContent=asc?'\\u25B2':'\\u25BC';
 try{localStorage.setItem('fleetSort',idx+','+(asc?1:0));}catch(e){}
}
window.addEventListener('DOMContentLoaded',function(){
 var ths=document.querySelectorAll('#fleet th');
 ths.forEach(function(th,i){th.addEventListener('click',function(){sortBy(i);});});
 var saved=null;try{saved=localStorage.getItem('fleetSort');}catch(e){}
 if(saved){var p=saved.split(',');var t=document.getElementById('fleet');
   t.setAttribute('data-col','x');t.setAttribute('data-asc',p[1]==='1'?'0':'1');sortBy(parseInt(p[0]));}
 else{var t=document.getElementById('fleet');t.setAttribute('data-col','x');
   t.setAttribute('data-asc','1');sortBy(6);} // default: lifetime PnL desc
});
"""


def _badge(status: str) -> str:
    fg, bg = _STATUS.get(status, ("#57606a", "#eaeef2"))
    return f"<span class='badge' style='color:{fg};background:{bg}'>{_esc(status)}</span>"


def _build_rows(base: Path, now: datetime):
    d1 = {r.svc.unit: r for r in build_reports(base, now, 1)}
    weekly = build_reports(base, now, 7)
    rows = []
    for r in weekly:
        m = r.lifetime
        pnl24 = d1[r.svc.unit].window.pnl_rub if r.svc.unit in d1 else 0.0
        rows.append({
            "status": r.status_class, "unit": r.svc.unit.replace("hammertrade-", "").replace(".service", ""),
            "family": r.svc.family, "instr": r.svc.instrument, "dir": r.svc.direction or "—",
            "trades": m.trades, "pnl": m.pnl_rub, "pf": m.pf, "wr": m.wr,
            "maxdd": m.max_dd_rub, "avgw": m.avg_win, "avgl": m.avg_loss,
            "pnl24": pnl24, "pnl7": r.window.pnl_rub, "open": r.open_positions,
            "live": r.liveness, "apierr": r.api_errors,
            "active": r.svc.active, "cand": r.sandbox_capable,
        })
    return rows


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    @app.route("/")
    @requires_auth
    def index():
        now = datetime.now(tz=timezone.utc)
        rows = _build_rows(BASE_DIR, now)

        by_class: dict[str, int] = {}
        for r in rows:
            by_class[r["status"]] = by_class.get(r["status"], 0) + 1
        life_pnl = sum(r["pnl"] for r in rows)
        pnl24 = sum(r["pnl24"] for r in rows)
        active = sum(1 for r in rows if r["active"] == "active")
        degraded = sum(1 for r in rows if r["live"] != "OK")

        # summary cards
        chips = "".join(
            f"<span class='chip' style='color:{_STATUS[k][0]};background:{_STATUS[k][1]}'>"
            f"{k} {by_class.get(k,0)}</span>"
            for k in ("PROMOTE", "ACTIVE", "WATCH", "FREEZE"))
        pnl_cls = "pos" if life_pnl >= 0 else "neg"
        pnl24_cls = "pos" if pnl24 >= 0 else "neg"
        cards = (
            "<div class='cards'>"
            f"<div class='card'><div class='k'>Services</div><div class='v'>{len(rows)}</div></div>"
            f"<div class='card'><div class='k'>Lifetime PnL</div><div class='v {pnl_cls}'>{life_pnl:+,.0f}₽</div></div>"
            f"<div class='card'><div class='k'>Last 24h PnL</div><div class='v {pnl24_cls}'>{pnl24:+,.0f}₽</div></div>"
            f"<div class='card'><div class='k'>Health</div><div class='v'>{active}/{len(rows)}"
            f"<span style='font-size:12px;color:#6e7781'> active · {degraded} degr</span></div></div>"
            f"<div class='card' style='flex:1'><div class='k'>Status mix</div><div class='chips'>{chips}</div></div>"
            "</div>")

        # candidates
        cands = [r for r in rows if r["cand"]]
        cand_html = "<div class='cand'>"
        if cands:
            for r in cands:
                tag = "SANDBOX (running)" if r["family"] == "sandbox" else "PROMOTE candidate"
                cand_html += (f"<div class='candcard'><b>{_esc(r['unit'])}</b> · {_esc(tag)} · "
                              f"{_esc(r['family'])} {_esc(r['instr'])} {_esc(r['dir'])} · "
                              f"{r['trades']} tr · PF {_fmt(r['pf'],2)} · WR {_fmt(r['wr'],0)}% · "
                              f"PnL {_fmt(r['pnl'])}₽</div>")
        else:
            cand_html += "<div class='candcard' style='border-left-color:#9a6700'>Пока нет PROMOTE-кандидатов (выборка набирается); sandbox-сервис показан если запущен.</div>"
        cand_html += "</div>"

        # table
        cols = [("status", "STATUS", "l"), ("unit", "service", "l"), ("family", "fam", "l"),
                ("instr", "instr", "l"), ("dir", "dir", "l"), ("trades", "trades", ""),
                ("pnl", "PnL ₽", ""), ("pf", "PF", ""), ("wr", "WR%", ""), ("maxdd", "MaxDD", ""),
                ("avgw", "avgW", ""), ("avgl", "avgL", ""), ("pnl24", "24h ₽", ""),
                ("pnl7", "7d ₽", ""), ("open", "open", ""), ("live", "live", ""),
                ("apierr", "apiErr", "")]
        head = "".join(f"<th class='{c[2]}'>{_esc(c[1])} <span class='ar'></span></th>" for c in cols)

        body = ""
        for r in rows:
            live_color = "#1a7f37" if r["live"] == "OK" else "#cf222e"
            warn = "" if r["active"] == "active" else " ⛔"
            body += (
                "<tr>"
                f"<td class='l' data-sort='{_STATUS_RANK.get(r['status'],9)}'>{_badge(r['status'])}</td>"
                f"<td class='l'>{_esc(r['unit'])}{warn}</td>"
                f"<td class='l'>{_esc(r['family'])}</td>"
                f"<td class='l'>{_esc(r['instr'])}</td>"
                f"<td class='l'>{_esc(r['dir'])}</td>"
                f"<td data-sort='{_num(r['trades'])}'>{r['trades']}</td>"
                + _pnl_cell(r["pnl"])
                + f"<td data-sort='{_num(r['pf'])}'>{_fmt(r['pf'],2)}</td>"
                f"<td data-sort='{_num(r['wr'])}'>{_fmt(r['wr'],0)}</td>"
                f"<td data-sort='{_num(r['maxdd'])}'>{_fmt(r['maxdd'])}</td>"
                f"<td data-sort='{_num(r['avgw'])}'>{_fmt(r['avgw'])}</td>"
                f"<td data-sort='{_num(r['avgl'])}'>{_fmt(r['avgl'])}</td>"
                + _pnl_cell(r["pnl24"]) + _pnl_cell(r["pnl7"])
                + f"<td data-sort='{_num(r['open'])}'>{r['open']}</td>"
                f"<td data-sort='{'0' if r['live']=='OK' else '1'}' style='color:{live_color}'>{_esc(r['live'])}</td>"
                f"<td data-sort='{_num(r['apierr'])}'>{r['apierr']}</td>"
                "</tr>")

        page = (
            "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta http-equiv='refresh' content='120'>"
            "<title>HammerTrade Fleet</title>"
            f"<style>{_CSS}</style></head><body><div class='wrap'>"
            "<h1>HammerTrade — Fleet Dashboard</h1>"
            f"<div class='meta'>Обновлено {now.strftime('%Y-%m-%d %H:%M UTC')} · автообновление 120с · "
            "PF/WR/MaxDD/avg — за всё время · только чтение</div>"
            + cards
            + "<h2>Sandbox / live-capable кандидаты</h2>" + cand_html
            + "<h2>Все сервисы</h2>"
            "<div class='tablewrap'><table id='fleet'>"
            f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
            "<div class='hint'>Клик по заголовку колонки — сортировка (повторный клик меняет направление). "
            "Выбор сортировки запоминается. По умолчанию — по PnL за всё время.</div>"
            f"<script>{_JS}</script>"
            "</div></body></html>"
        )
        return Response(page, mimetype="text/html")

    return app
