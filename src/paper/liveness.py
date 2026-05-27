"""Trading liveness guard — detects DEGRADED/STALLED state during open market."""
from datetime import datetime, timezone
from typing import Optional

DEGRADED_AFTER_CONSECUTIVE_ERRORS: int = 5
STALLED_AFTER_CONSECUTIVE_ERRORS: int = 20
DEGRADED_AFTER_FETCH_MINUTES: int = 15
STALLED_AFTER_FETCH_MINUTES: int = 30
DEGRADED_AFTER_EMPTY_RESPONSES: int = 3

# Grace period after market open: time-based checks are skipped during this window
# even if last_successful_fetch_at is still None. After the grace period expires,
# minutes-since-market-open is used as a proxy for stale fetch.
OPEN_MARKET_GRACE_MINUTES: int = 5


def _parse_ts(ts_str: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def compute_liveness(
    *,
    is_market_open: bool,
    consecutive_api_errors: int,
    consecutive_empty_responses: int = 0,
    last_successful_fetch_at: Optional[str] = None,
    market_open_since: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> tuple[str, Optional[str]]:
    """Compute trading liveness status.

    Returns (status, reason) where status is "OK", "DEGRADED", or "STALLED".

    When market is closed, always returns ("OK", None).

    When last_successful_fetch_at is not None:
      - time-based thresholds apply normally.

    When last_successful_fetch_at is None (no successful fetch yet this session):
      - If market_open_since is None: only error-counter thresholds apply.
      - If market_open_since is set:
          - For the first OPEN_MARKET_GRACE_MINUTES after market open: time checks skip.
          - After the grace period: minutes-since-open is used as a stale-fetch proxy,
            so DEGRADED/STALLED fire if the market has been open long enough without
            a successful fetch even when error counters are low.
    """
    if not is_market_open:
        return "OK", None

    if now_utc is None:
        now_utc = datetime.now(tz=timezone.utc)

    # ── Determine effective minutes of fetch staleness ───────────────────────
    minutes_stale: Optional[float] = None

    if last_successful_fetch_at:
        ts = _parse_ts(last_successful_fetch_at)
        if ts:
            minutes_stale = (now_utc - ts).total_seconds() / 60
    elif market_open_since:
        # No successful fetch yet this session.  After grace period, use
        # minutes-since-open as a backstop so time-based thresholds still fire.
        open_ts = _parse_ts(market_open_since)
        if open_ts:
            minutes_since_open = (now_utc - open_ts).total_seconds() / 60
            if minutes_since_open > OPEN_MARKET_GRACE_MINUTES:
                minutes_stale = minutes_since_open
    # If both are None: time-based checks are skipped; only error counters apply.

    # ── STALLED (most severe — check first) ──────────────────────────────────
    if consecutive_api_errors >= STALLED_AFTER_CONSECUTIVE_ERRORS:
        return "STALLED", f"consecutive_api_errors={consecutive_api_errors}"
    if minutes_stale is not None and minutes_stale >= STALLED_AFTER_FETCH_MINUTES:
        label = (
            "minutes_since_last_successful_fetch"
            if last_successful_fetch_at
            else "minutes_since_market_open_no_fetch"
        )
        return "STALLED", f"{label}={minutes_stale:.0f}"

    # ── DEGRADED ─────────────────────────────────────────────────────────────
    if consecutive_api_errors >= DEGRADED_AFTER_CONSECUTIVE_ERRORS:
        return "DEGRADED", f"consecutive_api_errors={consecutive_api_errors}"
    if minutes_stale is not None and minutes_stale >= DEGRADED_AFTER_FETCH_MINUTES:
        label = (
            "minutes_since_last_successful_fetch"
            if last_successful_fetch_at
            else "minutes_since_market_open_no_fetch"
        )
        return "DEGRADED", f"{label}={minutes_stale:.0f}"
    if consecutive_empty_responses >= DEGRADED_AFTER_EMPTY_RESPONSES:
        return "DEGRADED", f"consecutive_empty_responses={consecutive_empty_responses}"

    return "OK", None
