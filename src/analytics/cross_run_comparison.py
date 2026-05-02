"""Cross-run comparison: reads archives/latest/Actual_*.zip and builds a comparison table."""
import re
import zipfile
from io import StringIO
from pathlib import Path
from typing import Optional

import pandas as pd


# ─── Manifest parsing ─────────────────────────────────────────────────────────

def parse_manifest(text: str) -> dict:
    result = {}
    files = []
    in_files = False
    for line in text.splitlines():
        if line.startswith("Files included:"):
            in_files = True
            continue
        if in_files:
            if line.startswith("- "):
                files.append(line[2:].strip())
        else:
            if ": " in line:
                key, _, val = line.partition(": ")
                result[key.strip()] = val.strip()
    result["files"] = files
    return result


# ─── Archive reading ──────────────────────────────────────────────────────────

def _read_csv_from_zip(zip_path: str, pattern: str) -> Optional[pd.DataFrame]:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            matches = [n for n in names if re.search(pattern, n)]
            if not matches:
                return None
            with zf.open(matches[0]) as f:
                return pd.read_csv(f)
    except Exception:
        return None


def _read_text_from_zip(zip_path: str, pattern: str) -> Optional[str]:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            matches = [n for n in names if re.search(pattern, n)]
            if not matches:
                return None
            with zf.open(matches[0]) as f:
                return f.read().decode("utf-8", errors="replace")
    except Exception:
        return None


# ─── Metric extraction ────────────────────────────────────────────────────────

def _extract_debug_metrics(debug_df: Optional[pd.DataFrame]) -> dict:
    if debug_df is None or debug_df.empty:
        return {"rows": None, "signals": None, "buy_signals": None, "sell_signals": None,
                "top_fail_reason": None}
    rows = len(debug_df)
    sig_mask = debug_df["is_signal"].astype(bool) & (debug_df["fail_reason"].astype(str) == "pass")
    signals = int(sig_mask.sum())
    buy_signals = int((sig_mask & (debug_df.get("direction_candidate", pd.Series(dtype=str)).str.upper() == "BUY")).sum())
    sell_signals = int((sig_mask & (debug_df.get("direction_candidate", pd.Series(dtype=str)).str.upper() == "SELL")).sum())

    top_fail_reason = None
    if "fail_reason" in debug_df.columns:
        failed = debug_df[~sig_mask]["fail_reason"].astype(str)
        failed = failed[failed != "pass"]
        if len(failed):
            top_fail_reason = failed.value_counts().index[0]

    return {"rows": rows, "signals": signals, "buy_signals": buy_signals,
            "sell_signals": sell_signals, "top_fail_reason": top_fail_reason}


def _extract_backtest_metrics(trades_df: Optional[pd.DataFrame]) -> dict:
    empty = {
        "closed_trades": None, "skipped_trades": None, "net_pnl_rub": None,
        "winrate": None, "profit_factor": None, "max_drawdown_rub": None,
        "avg_net_pnl_rub": None, "buy_net_pnl_rub": None, "sell_net_pnl_rub": None,
    }
    if trades_df is None or trades_df.empty:
        return empty

    closed = trades_df[trades_df["status"] == "closed"]
    skipped = trades_df[trades_df["status"] != "closed"]
    wins = closed[closed["net_pnl_rub"] > 0]
    losses = closed[closed["net_pnl_rub"] < 0]

    gross_profit = float(wins["net_pnl_rub"].sum()) if len(wins) else 0.0
    gross_loss = float(losses["net_pnl_rub"].sum()) if len(losses) else 0.0
    if gross_profit > 0 and gross_loss == 0:
        pf = float("inf")
    elif gross_profit == 0 and gross_loss == 0:
        pf = 0.0
    else:
        pf = gross_profit / abs(gross_loss)

    buy_closed = closed[closed["direction"] == "BUY"]
    sell_closed = closed[closed["direction"] == "SELL"]

    # Drawdown
    max_dd = 0.0
    if len(closed):
        equity = closed["net_pnl_rub"].reset_index(drop=True).cumsum()
        peak = equity.cummax()
        max_dd = float((peak - equity).max())

    return {
        "closed_trades": len(closed),
        "skipped_trades": len(skipped),
        "net_pnl_rub": float(closed["net_pnl_rub"].sum()) if len(closed) else 0.0,
        "winrate": len(wins) / len(closed) if len(closed) else 0.0,
        "profit_factor": pf,
        "max_drawdown_rub": max_dd,
        "avg_net_pnl_rub": float(closed["net_pnl_rub"].mean()) if len(closed) else 0.0,
        "buy_net_pnl_rub": float(buy_closed["net_pnl_rub"].sum()) if len(buy_closed) else 0.0,
        "sell_net_pnl_rub": float(sell_closed["net_pnl_rub"].sum()) if len(sell_closed) else 0.0,
    }


def _extract_grid_metrics(grid_df: Optional[pd.DataFrame]) -> dict:
    empty = {
        "grid_scenarios": None, "grid_profitable_scenarios": None,
        "grid_profitable_scenarios_pct": None,
        "best_grid_net_pnl_rub": None, "worst_grid_net_pnl_rub": None,
        "median_grid_net_pnl_rub": None,
    }
    if grid_df is None or grid_df.empty or "net_pnl_rub" not in grid_df.columns:
        return empty

    n = len(grid_df)
    profitable = int((grid_df["net_pnl_rub"] > 0).sum())
    return {
        "grid_scenarios": n,
        "grid_profitable_scenarios": profitable,
        "grid_profitable_scenarios_pct": profitable / n if n else 0.0,
        "best_grid_net_pnl_rub": float(grid_df["net_pnl_rub"].max()),
        "worst_grid_net_pnl_rub": float(grid_df["net_pnl_rub"].min()),
        "median_grid_net_pnl_rub": float(grid_df["net_pnl_rub"].median()),
    }


def _extract_walkforward_metrics(wf_df: Optional[pd.DataFrame]) -> dict:
    empty = {
        "periods_total": None, "profitable_periods": None, "losing_periods": None,
        "profitable_periods_pct": None,
        "best_period_net_pnl_rub": None, "worst_period_net_pnl_rub": None,
    }
    if wf_df is None or wf_df.empty or "net_pnl_rub" not in wf_df.columns:
        return empty

    n = len(wf_df)
    profitable = int((wf_df["net_pnl_rub"] > 0).sum())
    losing = int((wf_df["net_pnl_rub"] < 0).sum())
    return {
        "periods_total": n,
        "profitable_periods": profitable,
        "losing_periods": losing,
        "profitable_periods_pct": profitable / n if n else 0.0,
        "best_period_net_pnl_rub": float(wf_df["net_pnl_rub"].max()),
        "worst_period_net_pnl_rub": float(wf_df["net_pnl_rub"].min()),
    }


def _extract_slippage_grid_metrics(grid_df: Optional[pd.DataFrame]) -> dict:
    result = {}
    if grid_df is None or grid_df.empty:
        return result
    if "slippage_ticks" not in grid_df.columns:
        return result

    for ticks_val, grp in grid_df.groupby("slippage_ticks"):
        key = int(ticks_val) if float(ticks_val) == int(ticks_val) else ticks_val
        result[f"worst_net_pnl_slip{key}t"] = float(grp["net_pnl_rub"].min())
        result[f"median_net_pnl_slip{key}t"] = float(grp["net_pnl_rub"].median())
    return result


# ─── Single archive row ───────────────────────────────────────────────────────

def build_comparison_row(zip_path: str, manifest_path: str) -> dict:
    # Parse manifest
    manifest_text = Path(manifest_path).read_text(encoding="utf-8") if Path(manifest_path).exists() else ""
    manifest = parse_manifest(manifest_text)

    row = {
        "run_id": manifest.get("Run ID", Path(zip_path).stem),
        "created_at": manifest.get("Created at", ""),
        "ticker": manifest.get("Ticker", ""),
        "class_code": manifest.get("Class code", ""),
        "timeframe": manifest.get("Timeframe", ""),
        "period": manifest.get("Period", ""),
        "profile": manifest.get("Profile", ""),
        "direction_filter": manifest.get("Direction filter", ""),
        "point_value_rub": manifest.get("Point value RUB", ""),
        "tick_size": manifest.get("Tick size", ""),
        "tick_size_source": manifest.get("Tick size source", ""),
        "archive": Path(zip_path).name,
    }

    debug_df = _read_csv_from_zip(zip_path, r"debug_simple_all_")
    trades_df = _read_csv_from_zip(zip_path, r"backtest_trades_")
    grid_df = _read_csv_from_zip(zip_path, r"backtest_grid_results_")
    wf_df = _read_csv_from_zip(zip_path, r"walkforward_period_results_")

    row.update(_extract_debug_metrics(debug_df))
    row.update(_extract_backtest_metrics(trades_df))
    row.update(_extract_grid_metrics(grid_df))
    row.update(_extract_walkforward_metrics(wf_df))
    row.update(_extract_slippage_grid_metrics(grid_df))

    # Normalized metrics
    closed = row.get("closed_trades") or 0
    signals = row.get("signals") or 0
    rows_count = row.get("rows") or 0
    net_pnl = row.get("net_pnl_rub")

    row["net_pnl_per_trade_rub"] = (net_pnl / closed) if closed and net_pnl is not None else None
    row["net_pnl_per_signal_rub"] = (net_pnl / signals) if signals and net_pnl is not None else None
    row["signals_per_1000_rows"] = (signals / rows_count * 1000) if rows_count else None
    row["closed_trades_per_1000_rows"] = (closed / rows_count * 1000) if rows_count else None

    return row


# ─── Build comparison DataFrame ───────────────────────────────────────────────

def build_comparison_df(zip_paths: list) -> pd.DataFrame:
    rows = []
    for zp in zip_paths:
        zp = str(zp)
        # Manifest is alongside the zip with same stem + .manifest.txt
        stem = Path(zp).stem
        manifest_path = str(Path(zp).parent / f"{stem}.manifest.txt")
        try:
            r = build_comparison_row(zp, manifest_path)
            rows.append(r)
        except Exception as e:
            rows.append({"archive": Path(zp).name, "error": str(e)})
    return pd.DataFrame(rows)


# ─── Markdown report ─────────────────────────────────────────────────────────

def generate_comparison_report(df: pd.DataFrame, output_path: str, created_at: str = "") -> None:
    lines = []
    lines.append("# Cross-run Research Comparison\n")

    lines.append("## Summary\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Runs compared | {len(df)} |")
    lines.append(f"| Created at | {created_at} |")
    lines.append("")

    overview_cols = [
        "ticker", "period", "direction_filter", "tick_size", "point_value_rub",
        "signals", "closed_trades", "net_pnl_rub", "winrate", "profit_factor",
        "profitable_periods_pct",
    ]
    lines.append("## Runs overview\n")
    lines.append(_table(df, overview_cols))
    lines.append("")

    rank_cols = [
        "ticker", "direction_filter", "net_pnl_rub", "profit_factor",
        "closed_trades", "grid_profitable_scenarios_pct", "worst_grid_net_pnl_rub",
    ]
    sorted_by_pnl = df.sort_values("net_pnl_rub", ascending=False) if "net_pnl_rub" in df.columns else df
    lines.append("## Ranking by Net PnL\n")
    lines.append(_table(sorted_by_pnl, rank_cols))
    lines.append("")

    sorted_by_pf = df.sort_values("profit_factor", ascending=False) if "profit_factor" in df.columns else df
    lines.append("## Ranking by Profit Factor\n")
    lines.append(_table(sorted_by_pf, rank_cols))
    lines.append("")

    density_cols = ["ticker", "rows", "signals", "signals_per_1000_rows", "top_fail_reason"]
    lines.append("## Signal density\n")
    lines.append(_table(df, density_cols))
    lines.append("")

    # Slippage ticks robustness — show columns that exist
    slip_cols = [c for c in df.columns if c.startswith("worst_net_pnl_slip")]
    if slip_cols:
        rob_cols = ["ticker", "direction_filter"] + sorted(slip_cols)
        lines.append("## Slippage ticks robustness\n")
        lines.append(_table(df, rob_cols))
        lines.append("")

    lines.append("## Notes\n")
    lines.append("- Cross-run comparison is offline research only.")
    lines.append("- Results do not include live execution, order book liquidity, queue position, partial fills or real broker execution.")
    lines.append("- Slippage in ticks is more comparable across instruments than slippage in price points.")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─── Table helper ─────────────────────────────────────────────────────────────

def _table(df: pd.DataFrame, cols: list) -> str:
    avail = [c for c in cols if c in df.columns]
    if not avail:
        return "_No data_"
    sub = df[avail].copy()
    header = "| " + " | ".join(avail) + " |"
    seps = []
    for c in avail:
        dtype = sub[c].dtype
        seps.append("---" if dtype == object else "---:")
    sep_line = "| " + " | ".join(seps) + " |"
    data_lines = [header, sep_line]
    for _, row in sub.iterrows():
        cells = []
        for c in avail:
            v = row[c]
            try:
                is_na = pd.isna(v)
            except (TypeError, ValueError):
                is_na = False
            if is_na:
                cells.append("")
            elif isinstance(v, float):
                if c in ("winrate", "profitable_periods_pct", "grid_profitable_scenarios_pct"):
                    cells.append(f"{v:.1%}")
                elif c == "profit_factor" and v == float("inf"):
                    cells.append("inf")
                else:
                    cells.append(f"{v:.2f}")
            else:
                cells.append(str(v))
        data_lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(data_lines)
