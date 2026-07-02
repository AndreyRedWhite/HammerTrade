"""Telegram alerting for fleet health.

Used by scripts/check_all_paper_status.py (--telegram): when the fleet check
finds problems (inactive unit / halted trading / stale status), it sends one
Telegram message and then stays quiet until the problem set CHANGES or
``resend_after_sec`` elapses (anti-spam for a 10-minute timer). When the fleet
recovers, a single "recovered" message is sent and the state file is cleared.

Configuration (env): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. Both unset = alerting
silently disabled (safe default for local runs).
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TELEGRAM_API = "https://api.telegram.org"


def is_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN")) and bool(os.environ.get("TELEGRAM_CHAT_ID"))


def send_telegram(text: str, *, timeout: float = 10.0) -> bool:
    """Send a plain-text message; returns True on HTTP 200 with ok=true."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text[:4000],  # Telegram hard limit 4096
        "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(url, data=payload, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return bool(body.get("ok"))
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _fingerprint(problems: list[str]) -> str:
    return hashlib.sha1("\n".join(sorted(problems)).encode()).hexdigest()


def _load_state(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def alert_on_problems(
    problems: list[str],
    state_path: Path,
    *,
    resend_after_sec: float = 4 * 3600,
    header: str = "HammerTrade fleet",
    now: datetime | None = None,
    send=send_telegram,
) -> str:
    """Dedup-gated alert. Returns the action taken:

    "sent" / "suppressed" (same problems, too soon) / "recovered" /
    "none" (healthy, nothing pending) / "send_failed" / "not_configured".
    """
    if not is_configured():
        return "not_configured"
    now = now or datetime.now(tz=timezone.utc)
    state = _load_state(state_path)

    if not problems:
        if state.get("fingerprint"):
            ok = send(f"✅ {header}: recovered — all services OK "
                      f"(was: {len(state.get('problems', []))} problem(s))")
            if ok:
                state_path.unlink(missing_ok=True)
                return "recovered"
            return "send_failed"
        return "none"

    fp = _fingerprint(problems)
    if state.get("fingerprint") == fp:
        try:
            alerted_at = datetime.fromisoformat(state["alerted_at"])
        except (KeyError, ValueError):
            alerted_at = None
        if alerted_at and (now - alerted_at).total_seconds() < resend_after_sec:
            return "suppressed"

    lines = "\n".join(f"• {p}" for p in problems[:30])
    more = f"\n… and {len(problems) - 30} more" if len(problems) > 30 else ""
    ok = send(f"🚨 {header}: {len(problems)} problem(s)\n{lines}{more}")
    if not ok:
        return "send_failed"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "fingerprint": fp,
        "alerted_at": now.isoformat(),
        "problems": problems,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return "sent"
