import argparse
import os
import sys

import pandas as pd

REQUIRED_COLUMNS = {
    "timestamp", "direction_candidate", "is_signal", "fail_reason", "fail_reasons",
    "open", "high", "low", "close", "params_profile",
}


def load_debug_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Input file not found: {path}")

    df = pd.read_csv(path)

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Input CSV missing required columns: {sorted(missing)}")

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["is_signal"] = df["is_signal"].astype(bool)
    return df


def build_report(df: pd.DataFrame) -> dict:
    total = len(df)
    signals = df[df["is_signal"]]
    n_signals = len(signals)
    n_buy = len(signals[signals["direction_candidate"] == "BUY"])
    n_sell = len(signals[signals["direction_candidate"] == "SELL"])

    profile = df["params_profile"].iloc[0] if "params_profile" in df.columns and len(df) else ""
    instrument = df["instrument"].iloc[0] if "instrument" in df.columns and len(df) else ""
    timeframe = df["timeframe"].iloc[0] if "timeframe" in df.columns and len(df) else ""

    tick_size_vals = sorted(df["tick_size"].dropna().unique().tolist()) if "tick_size" in df.columns else []
    tick_size_str = ", ".join(str(v) for v in tick_size_vals) if tick_size_vals else "n/a"
    tick_src_vals = sorted(df["tick_size_source"].dropna().unique().tolist()) if "tick_size_source" in df.columns else []
    tick_src_str = ", ".join(tick_src_vals) if tick_src_vals else "n/a"

    rejected = df[~df["is_signal"]]
    fail_counts = rejected["fail_reason"].value_counts()

    buy_candidates = df[df["direction_candidate"] == "BUY"]
    buy_rejected = buy_candidates[~buy_candidates["is_signal"]]
    buy_fail_counts = buy_rejected["fail_reason"].value_counts()

    sell_candidates = df[df["direction_candidate"] == "SELL"]
    sell_rejected = sell_candidates[~sell_candidates["is_signal"]]
    sell_fail_counts = sell_rejected["fail_reason"].value_counts()

    signals_by_hour = (
        signals["timestamp"].dt.hour.value_counts().sort_index()
        if n_signals > 0 else pd.Series(dtype=int)
    )

    return {
        "total": total,
        "n_signals": n_signals,
        "n_buy": n_buy,
        "n_sell": n_sell,
        "profile": profile,
        "instrument": instrument,
        "timeframe": timeframe,
        "fail_counts": fail_counts,
        "buy_fail_counts": buy_fail_counts,
        "sell_fail_counts": sell_fail_counts,
        "signals_by_hour": signals_by_hour,
        "signals_df": signals,
        "tick_size_str": tick_size_str,
        "tick_src_str": tick_src_str,
    }


def print_console_report(r: dict, input_path: str) -> None:
    print("Debug report")
    print("============")
    print()
    print(f"Input: {input_path}")
    print(f"Rows: {r['total']}")
    print(f"Signals: {r['n_signals']}")
    print(f"BUY signals: {r['n_buy']}")
    print(f"SELL signals: {r['n_sell']}")
    print()

    print("Top fail_reason:")
    for reason, count in r["fail_counts"].head(10).items():
        print(f"  - {reason}: {count}")
    print()

    print("BUY candidates fail_reason:")
    for reason, count in r["buy_fail_counts"].head(10).items():
        print(f"  - {reason}: {count}")
    print()

    print("SELL candidates fail_reason:")
    for reason, count in r["sell_fail_counts"].head(10).items():
        print(f"  - {reason}: {count}")
    print()

    print("Signals by hour:")
    if r["n_signals"] == 0:
        print("  (no signals)")
    else:
        for hour, count in r["signals_by_hour"].items():
            print(f"  {hour:02d}:00 - {count}")


def _fail_table(counts: pd.Series, total: int) -> str:
    if len(counts) == 0:
        return "| (none) | — | — |\n"
    lines = []
    for reason, count in counts.items():
        pct = count / total * 100 if total > 0 else 0.0
        lines.append(f"| {reason} | {count} | {pct:.1f}% |")
    return "\n".join(lines) + "\n"


def build_markdown(r: dict, input_path: str) -> str:
    total = r["total"]
    signals_df = r["signals_df"]

    # Summary table
    summary = (
        f"| Metric | Value |\n"
        f"|---|---:|\n"
        f"| Rows processed | {total} |\n"
        f"| Signals found | {r['n_signals']} |\n"
        f"| BUY signals | {r['n_buy']} |\n"
        f"| SELL signals | {r['n_sell']} |\n"
        f"| Profile | {r['profile']} |\n"
        f"| Instrument | {r['instrument']} |\n"
        f"| Timeframe | {r['timeframe']} |\n"
        f"| Tick size | {r['tick_size_str']} |\n"
        f"| Tick size source | {r['tick_src_str']} |\n"
    )

    # fail_reason table header
    fr_header = "| fail_reason | count | percent |\n|---|---:|---:|\n"

    top_fail = fr_header + _fail_table(r["fail_counts"].head(15), total)
    buy_fail = fr_header + _fail_table(r["buy_fail_counts"].head(15), total)
    sell_fail = fr_header + _fail_table(r["sell_fail_counts"].head(15), total)

    # Signals by hour
    if r["n_signals"] == 0:
        signals_by_hour = "| hour | signals |\n|---|---:|\n| (no signals) | — |\n"
    else:
        rows = "\n".join(
            f"| {h:02d}:00 | {c} |"
            for h, c in r["signals_by_hour"].items()
        )
        signals_by_hour = f"| hour | signals |\n|---|---:|\n{rows}\n"

    # Signals list
    if len(signals_df) == 0:
        signals_table = "_No signals detected._\n"
    else:
        header = "| timestamp | direction_candidate | open | high | low | close | fail_reason |\n|---|---|---:|---:|---:|---:|---|\n"
        rows = []
        for _, row in signals_df.iterrows():
            rows.append(
                f"| {row['timestamp']} | {row['direction_candidate']} "
                f"| {row['open']} | {row['high']} | {row['low']} | {row['close']} "
                f"| {row['fail_reason']} |"
            )
        signals_table = header + "\n".join(rows) + "\n"

    return f"""# Hammer Detector Debug Report

## Summary

{summary}
## Top fail_reason

{top_fail}
## BUY candidates fail_reason

{buy_fail}
## SELL candidates fail_reason

{sell_fail}
## Signals by hour

{signals_by_hour}
## Signals

{signals_table}
## Notes

This report is based on explainable detector output.
It does not include P&L, entries, exits, slippage or backtest results.
Source: `{input_path}`
"""


def main():
    parser = argparse.ArgumentParser(description="Hammer Detector — Debug Report")
    parser.add_argument("--input", required=True, help="Path to debug_simple_all.csv")
    parser.add_argument("--output", required=True, help="Path to output Markdown report")
    args = parser.parse_args()

    try:
        df = load_debug_csv(args.input)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    report = build_report(df)
    print_console_report(report, args.input)

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    md = build_markdown(report, args.input)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(md)

    print()
    print(f"Report saved: {args.output}")


if __name__ == "__main__":
    main()
