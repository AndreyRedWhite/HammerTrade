def build_run_id(
    ticker: str,
    timeframe: str,
    start: str,
    end: str,
    profile: str,
    direction_filter: str = "all",
) -> str:
    base = f"{ticker}_{timeframe}_{start}_{end}_{profile}"
    if direction_filter and direction_filter != "all":
        return f"{base}_{direction_filter}"
    return base
