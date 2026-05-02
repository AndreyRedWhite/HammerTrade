import argparse
import os
import sys
from datetime import timedelta

import pandas as pd

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}

TIMEFRAME_DELTA = {
    "1m":  timedelta(minutes=1),
    "5m":  timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h":  timedelta(hours=1),
    "1d":  timedelta(days=1),
}

GAP_THRESHOLD_MULTIPLIER = 2  # gap > 2x expected delta is reported


def load_candle_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Input file not found: {path}")

    df = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df


def analyze(df: pd.DataFrame, timeframe: str) -> dict:
    n_rows = len(df)
    first_ts = df["timestamp"].min()
    last_ts = df["timestamp"].max()
    n_dupes = df["timestamp"].duplicated().sum()

    ohlc_cols = ["open", "high", "low", "close"]
    missing_ohlc = df[ohlc_cols].isna().any(axis=1).sum()
    zero_range = (df["high"] == df["low"]).sum()
    zero_volume = (df["volume"] == 0).sum() if "volume" in df.columns else 0

    invalid_hl = (df["high"] < df["low"]).sum()
    nonpositive = (df[ohlc_cols] <= 0).any(axis=1).sum()

    gaps = []
    if timeframe in TIMEFRAME_DELTA and n_rows > 1:
        expected = TIMEFRAME_DELTA[timeframe]
        threshold = expected * GAP_THRESHOLD_MULTIPLIER
        sorted_df = df.sort_values("timestamp")
        deltas = sorted_df["timestamp"].diff().dropna()
        gap_mask = deltas > threshold
        gap_indices = deltas[gap_mask].index
        for idx in gap_indices:
            loc = sorted_df.index.get_loc(idx)
            gap_start = sorted_df["timestamp"].iloc[loc - 1]
            gap_end = sorted_df["timestamp"].iloc[loc]
            actual_delta = gap_end - gap_start
            gaps.append({
                "gap_start": gap_start,
                "gap_end": gap_end,
                "expected_delta": str(expected),
                "actual_delta": str(actual_delta),
            })

    return {
        "n_rows": n_rows,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "n_dupes": int(n_dupes),
        "missing_ohlc": int(missing_ohlc),
        "zero_range": int(zero_range),
        "zero_volume": int(zero_volume),
        "invalid_hl": int(invalid_hl),
        "nonpositive": int(nonpositive),
        "gaps": gaps,
    }


def print_console_report(r: dict, input_path: str) -> None:
    print("Data Quality Report")
    print("===================")
    print(f"Input:               {input_path}")
    print(f"Rows:                {r['n_rows']}")
    print(f"First timestamp:     {r['first_ts']}")
    print(f"Last timestamp:      {r['last_ts']}")
    print(f"Duplicate timestamps:{r['n_dupes']}")
    print(f"Missing OHLC values: {r['missing_ohlc']}")
    print(f"Zero range candles:  {r['zero_range']}")
    print(f"Zero volume candles: {r['zero_volume']}")
    print(f"high < low:          {r['invalid_hl']}")
    print(f"Non-positive prices: {r['nonpositive']}")
    print(f"Time gaps detected:  {len(r['gaps'])}")
    if r["gaps"]:
        for g in r["gaps"][:5]:
            print(f"  {g['gap_start']} -> {g['gap_end']}  (actual: {g['actual_delta']})")
        if len(r["gaps"]) > 5:
            print(f"  ... and {len(r['gaps']) - 5} more")


def build_markdown(r: dict, input_path: str) -> str:
    summary = (
        f"| Metric | Value |\n"
        f"|---|---:|\n"
        f"| Rows | {r['n_rows']} |\n"
        f"| First timestamp | {r['first_ts']} |\n"
        f"| Last timestamp | {r['last_ts']} |\n"
        f"| Duplicate timestamps | {r['n_dupes']} |\n"
        f"| Missing OHLC values | {r['missing_ohlc']} |\n"
        f"| Zero range candles | {r['zero_range']} |\n"
        f"| Zero volume candles | {r['zero_volume']} |\n"
        f"| high < low (invalid) | {r['invalid_hl']} |\n"
        f"| Non-positive prices | {r['nonpositive']} |\n"
    )

    if r["gaps"]:
        gap_rows = "\n".join(
            f"| {g['gap_start']} | {g['gap_end']} | {g['expected_delta']} | {g['actual_delta']} |"
            for g in r["gaps"]
        )
        gaps_table = (
            "| gap_start | gap_end | expected_delta | actual_delta |\n"
            "|---|---|---:|---:|\n"
            f"{gap_rows}\n"
        )
    else:
        gaps_table = "_No significant gaps detected._\n"

    return f"""# Data Quality Report

## Summary

{summary}
## Time gaps

{gaps_table}
## Notes

This report validates only candle data quality.
It does not validate strategy performance.
Source: `{input_path}`
"""


def main():
    parser = argparse.ArgumentParser(description="Candle data quality report")
    parser.add_argument("--input", required=True, help="Path to candle CSV")
    parser.add_argument("--output", required=True, help="Path to output Markdown report")
    parser.add_argument("--timeframe", default="1m",
                        choices=["1m", "5m", "15m", "1h", "1d"],
                        help="Expected candle timeframe for gap detection")
    args = parser.parse_args()

    try:
        df = load_candle_csv(args.input)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    result = analyze(df, args.timeframe)
    print_console_report(result, args.input)

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    md = build_markdown(result, args.input)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(md)

    print()
    print(f"Report saved: {args.output}")


if __name__ == "__main__":
    main()
