import pandas as pd

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}
NUMERIC_COLUMNS = ["open", "high", "low", "close", "volume"]


def load_candles(path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(path)
    except Exception as e:
        raise ValueError(f"Cannot read CSV file '{path}': {e}")

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    try:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    except Exception as e:
        raise ValueError(f"Cannot parse 'timestamp' column: {e}")

    for col in NUMERIC_COLUMNS:
        try:
            df[col] = pd.to_numeric(df[col], errors="raise")
        except Exception:
            raise ValueError(f"Column '{col}' contains non-numeric values")

    df = df.sort_values("timestamp").reset_index(drop=True)
    return df
