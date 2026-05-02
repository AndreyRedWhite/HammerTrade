import calendar

import pandas as pd

_MSK = "Europe/Moscow"


def add_moscow_timestamp(df: pd.DataFrame, timestamp_col: str = "timestamp") -> pd.DataFrame:
    df = df.copy()
    ts = pd.to_datetime(df[timestamp_col])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(_MSK)
    else:
        ts = ts.dt.tz_convert(_MSK)
    df["timestamp_msk"] = ts
    return df


def assign_period(df: pd.DataFrame, period: str = "week", timezone: str = _MSK) -> pd.DataFrame:
    df = df.copy()
    if "timestamp_msk" not in df.columns:
        df = add_moscow_timestamp(df)
    ts = df["timestamp_msk"]
    if ts.dt.tz is not None and str(ts.dt.tz) != timezone:
        ts = ts.dt.tz_convert(timezone)
        df["timestamp_msk"] = ts

    if period == "day":
        df["period_key"] = ts.dt.strftime("%Y-%m-%d")
        df["period_start"] = ts.apply(lambda x: x.replace(hour=0, minute=0, second=0, microsecond=0))
        df["period_end"] = ts.apply(lambda x: x.replace(hour=23, minute=59, second=59, microsecond=999999))

    elif period == "week":
        df["period_key"] = ts.apply(
            lambda x: f"{x.isocalendar()[0]}-W{x.isocalendar()[1]:02d}"
        )

        def _monday(x):
            return (x - pd.Timedelta(days=x.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        def _sunday(x):
            return _monday(x) + pd.Timedelta(
                days=6, hours=23, minutes=59, seconds=59, microseconds=999999
            )

        df["period_start"] = ts.apply(_monday)
        df["period_end"] = ts.apply(_sunday)

    elif period == "month":
        df["period_key"] = ts.dt.strftime("%Y-%m")

        def _month_start(x):
            return x.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        def _month_end(x):
            last = calendar.monthrange(x.year, x.month)[1]
            return x.replace(day=last, hour=23, minute=59, second=59, microsecond=999999)

        df["period_start"] = ts.apply(_month_start)
        df["period_end"] = ts.apply(_month_end)

    else:
        raise ValueError(f"Unknown period: {period!r}. Expected 'day', 'week', 'month'.")

    return df
