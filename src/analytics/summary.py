import pandas as pd


def print_summary(df: pd.DataFrame, output_path: str) -> None:
    total = len(df)
    signals = df[df["is_signal"] == True]
    n_signals = len(signals)
    n_buy = len(signals[signals["direction_candidate"] == "BUY"])
    n_sell = len(signals[signals["direction_candidate"] == "SELL"])

    rejected = df[df["is_signal"] == False]
    fail_counts = rejected["fail_reason"].value_counts()

    print(f"Rows processed: {total}")
    print(f"Signals found: {n_signals}")
    print(f"BUY signals: {n_buy}")
    print(f"SELL signals: {n_sell}")
    print(f"Output written: {output_path}")
    print("Top fail reasons:")
    for reason, count in fail_counts.head(10).items():
        print(f"  - {reason}: {count}")
