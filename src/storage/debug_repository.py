import os
import pandas as pd

OUTPUT_COLUMNS = [
    "timestamp", "instrument", "timeframe",
    "open", "high", "low", "close", "volume",
    "range", "body", "upper_shadow", "lower_shadow",
    "body_frac", "upper_frac", "lower_frac", "close_pos",
    "direction_candidate", "is_signal", "fail_reason", "fail_reasons",
    "params_profile",
    "tick_size", "tick_size_source",
]


def save_debug_csv(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    cols = [c for c in OUTPUT_COLUMNS if c in df.columns]
    df[cols].to_csv(path, index=False)
