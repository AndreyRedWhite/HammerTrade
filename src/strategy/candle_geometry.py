import pandas as pd


def compute_geometry(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["range"] = df["high"] - df["low"]
    df["body"] = (df["close"] - df["open"]).abs()
    df["upper_shadow"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_shadow"] = df[["open", "close"]].min(axis=1) - df["low"]

    valid = df["range"] > 0
    df["valid_candle"] = valid

    df["body_frac"] = (df["body"] / df["range"]).where(valid)
    df["upper_frac"] = (df["upper_shadow"] / df["range"]).where(valid)
    df["lower_frac"] = (df["lower_shadow"] / df["range"]).where(valid)
    df["close_pos"] = ((df["close"] - df["low"]) / df["range"]).where(valid)

    return df


def get_geometry_for_candle(open_: float, high: float, low: float, close: float) -> dict:
    range_ = high - low
    body = abs(close - open_)
    upper_shadow = high - max(open_, close)
    lower_shadow = min(open_, close) - low

    if range_ <= 0:
        return {
            "range": range_,
            "body": body,
            "upper_shadow": upper_shadow,
            "lower_shadow": lower_shadow,
            "body_frac": None,
            "upper_frac": None,
            "lower_frac": None,
            "close_pos": None,
            "valid_candle": False,
        }

    return {
        "range": range_,
        "body": body,
        "upper_shadow": upper_shadow,
        "lower_shadow": lower_shadow,
        "body_frac": body / range_,
        "upper_frac": upper_shadow / range_,
        "lower_frac": lower_shadow / range_,
        "close_pos": (close - low) / range_,
        "valid_candle": True,
    }
