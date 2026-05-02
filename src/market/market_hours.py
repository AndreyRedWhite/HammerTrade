"""Market hours / session schedule for MOEX futures."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class MarketSession:
    name: str
    start: time
    end: time


@dataclass(frozen=True)
class MarketHoursConfig:
    timezone: str
    weekday_sessions: tuple[MarketSession, ...]
    weekend_sessions: tuple[MarketSession, ...]
    stale_candle_grace_minutes: int


def load_market_hours_config(path: Path) -> MarketHoursConfig:
    import yaml

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Market hours config not found: {path}")

    with path.open() as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Market hours config must be a YAML mapping: {path}")

    tz = raw.get("timezone")
    if not tz:
        raise ValueError("Market hours config missing 'timezone'")

    def _parse_sessions(key: str) -> tuple[MarketSession, ...]:
        items = raw.get(key, [])
        sessions = []
        for item in items:
            name = item["name"]
            start = _parse_time(item["start"], key, name)
            end = _parse_time(item["end"], key, name)
            sessions.append(MarketSession(name=name, start=start, end=end))
        return tuple(sessions)

    return MarketHoursConfig(
        timezone=tz,
        weekday_sessions=_parse_sessions("weekday_sessions"),
        weekend_sessions=_parse_sessions("weekend_sessions"),
        stale_candle_grace_minutes=int(raw.get("stale_candle_grace_minutes", 3)),
    )


def _parse_time(value: str, section: str, name: str) -> time:
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except Exception:
        raise ValueError(f"Invalid time '{value}' in {section}/{name}, expected HH:MM")


def to_market_timezone(ts: datetime, config: MarketHoursConfig) -> datetime:
    if ts.tzinfo is None:
        raise ValueError(
            f"timezone-aware datetime is required, got naive: {ts!r}"
        )
    return ts.astimezone(ZoneInfo(config.timezone))


def is_session_open(ts: datetime, config: MarketHoursConfig) -> bool:
    market_ts = to_market_timezone(ts, config)
    weekday = market_ts.weekday()  # 0=Monday … 6=Sunday
    t = market_ts.time()
    sessions = config.weekend_sessions if weekday >= 5 else config.weekday_sessions
    return any(s.start <= t < s.end for s in sessions)


def get_session_name(ts: datetime, config: MarketHoursConfig) -> str:
    market_ts = to_market_timezone(ts, config)
    weekday = market_ts.weekday()
    t = market_ts.time()
    sessions = config.weekend_sessions if weekday >= 5 else config.weekday_sessions
    for s in sessions:
        if s.start <= t < s.end:
            return s.name
    return "closed"
