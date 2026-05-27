"""Trading liveness guard — detects DEGRADED/STALLED state during open market."""
from datetime import datetime, timezone
from typing import Optional

DEGRADED_AFTER_CONSECUTIVE_ERRORS: int = 5
STALLED_AFTER_CONSECUTIVE_ERRORS: int = 20
DEGRADED_AFTER_FETCH_MINUTES: int = 15
STALLED_AFTER_FETCH_MINUTES: int = 30
DEGRADED_AFTER_EMPTY_RESPONSES: int = 3


def compute_liveness(
    *,
    is_market_open: bool,
    consecutive_api_errors: int,
    consecutive_empty_responses: int = 0,
    last_successful_fetch_at: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> tuple[str, Optional[str]]:
    """Compute trading liveness status.

    Returns (status, reason) where status is "OK", "DEGRADED", or "STALLED".
    When market is closed, always returns ("OK", None).
    When last_successful_fetch_at is None, time-based checks are skipped
    (only consecutive-error threshold applies).
    """
    if not is_market_open:
        return "OK", None

    if now_utc is None:
        now_utc = datetime.now(tz=timezone.utc)

    minutes_since_fetch: Optional[float] = None
    if last_successful_fetch_at:
        try:
            ts = datetime.fromisoformat(last_successful_fetch_at.replace("Z", "+00:00"))
            minutes_since_fetch = (now_utc - ts).total_seconds() / 60
        except (ValueError, TypeError):
            pass

    # STALLED (most severe — check first)
    if consecutive_api_errors >= STALLED_AFTER_CONSECUTIVE_ERRORS:
        return "STALLED", f"consecutive_api_errors={consecutive_api_errors}"
    if minutes_since_fetch is not None and minutes_since_fetch >= STALLED_AFTER_FETCH_MINUTES:
        return "STALLED", f"minutes_since_last_successful_fetch={minutes_since_fetch:.0f}"

    # DEGRADED
    if consecutive_api_errors >= DEGRADED_AFTER_CONSECUTIVE_ERRORS:
        return "DEGRADED", f"consecutive_api_errors={consecutive_api_errors}"
    if minutes_since_fetch is not None and minutes_since_fetch >= DEGRADED_AFTER_FETCH_MINUTES:
        return "DEGRADED", f"minutes_since_last_successful_fetch={minutes_since_fetch:.0f}"
    if consecutive_empty_responses >= DEGRADED_AFTER_EMPTY_RESPONSES:
        return "DEGRADED", f"consecutive_empty_responses={consecutive_empty_responses}"

    return "OK", None
