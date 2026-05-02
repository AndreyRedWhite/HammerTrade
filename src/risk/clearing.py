from datetime import time, datetime
from zoneinfo import ZoneInfo

import pandas as pd

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
CLEARING_TIMES = [time(13, 55), time(18, 45)]


def to_moscow_time(dt) -> datetime:
    """Convert any timestamp to Europe/Moscow. Naive datetimes are assumed Moscow."""
    if isinstance(dt, pd.Timestamp):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=MOSCOW_TZ).to_pydatetime()
        return dt.tz_convert(MOSCOW_TZ).to_pydatetime()
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=MOSCOW_TZ)
        return dt.astimezone(MOSCOW_TZ)
    raise TypeError(f"Unsupported timestamp type: {type(dt)}")


def is_near_clearing(
    ts,
    block_before_min: int = 5,
    block_after_min: int = 5,
) -> bool:
    dt_msk = to_moscow_time(ts)
    t = dt_msk.time()
    t_minutes = t.hour * 60 + t.minute

    for clearing in CLEARING_TIMES:
        c_minutes = clearing.hour * 60 + clearing.minute
        if (c_minutes - block_before_min) <= t_minutes <= (c_minutes + block_after_min):
            return True
    return False
