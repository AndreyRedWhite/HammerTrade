"""Paper trading diagnostics: enrichment, bucket analysis, filter hypotheses."""

import csv
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Optional
from zoneinfo import ZoneInfo

_MSK = ZoneInfo("Europe/Moscow")
_WEEKDAY_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

_ENRICHED_COLUMNS = [
    "trade_id", "ticker", "class_code", "timeframe", "profile", "direction",
    "status",
    "signal_timestamp_utc", "signal_timestamp_msk",
    "entry_timestamp_utc", "entry_timestamp_msk",
    "entry_date_msk", "entry_hour_msk", "day_of_week_msk",
    "entry_price", "stop_price", "take_price",
    "exit_timestamp_utc", "exit_timestamp_msk",
    "exit_price", "exit_reason",
    "pnl_points", "pnl_rub",
    "risk_points", "reward_points", "actual_points", "rr",
    "pnl_sign", "abs_pnl_rub",
    "risk_bucket", "reward_bucket", "rr_bucket", "bars_bucket",
    "bars_held",
    "diagnostic_flags",
    "created_at", "updated_at",
]


@dataclass
class DiagnosticsResult:
    enriched: list[dict]
    summary: dict
    groups: dict  # group_key -> list[dict]
    hypotheses: list[str]
    warnings: list[str]
    source_label: str = ""


# ── Timestamp helpers ──────────────────────────────────────────────────────────

def _parse_ts(s: Optional[str], warnings: list[str], label: str) -> Optional[datetime]:
    if s is None or s == "":
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            warnings.append(f"Naive timestamp {label}: {s!r} — assumed UTC")
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        warnings.append(f"Cannot parse timestamp {label}: {s!r}")
        return None


def _iso_utc(dt: Optional[datetime]) -> str:
    return dt.isoformat() if dt else ""


def _to_msk(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.astimezone(_MSK) if dt else None


# ── Direction helpers ──────────────────────────────────────────────────────────

def _infer_direction(row: dict) -> Optional[str]:
    try:
        entry = float(row["entry_price"])
        stop = float(row["stop_price"])
        take = float(row["take_price"])
        if stop > entry and take < entry:
            return "SELL"
        if stop < entry and take > entry:
            return "BUY"
    except (KeyError, TypeError, ValueError):
        pass
    return None


# ── Risk/Reward ────────────────────────────────────────────────────────────────

def _compute_rr_fields(row: dict, direction: Optional[str], warnings: list[str]) -> dict:
    out = {"risk_points": None, "reward_points": None, "actual_points": None, "rr": None}
    if not direction:
        return out
    tid = row.get("trade_id", "?")
    try:
        entry = float(row["entry_price"])
        stop = float(row["stop_price"])
        take = float(row["take_price"])
        ep = row.get("exit_price")

        if direction == "SELL":
            risk = stop - entry
            reward = entry - take
            actual = (entry - float(ep)) if ep not in (None, "") else None
        else:  # BUY
            risk = entry - stop
            reward = take - entry
            actual = (float(ep) - entry) if ep not in (None, "") else None

        out["risk_points"] = risk
        out["reward_points"] = reward
        if actual is not None:
            out["actual_points"] = actual
        if risk > 0 and reward >= 0:
            out["rr"] = reward / risk
    except (TypeError, ValueError, KeyError) as exc:
        warnings.append(f"RR calc failed for {tid}: {exc}")
    return out


# ── Buckets ────────────────────────────────────────────────────────────────────

def _risk_bucket(v: Optional[float]) -> str:
    if v is None:
        return "RISK_UNKNOWN"
    if v <= 10:
        return "RISK_000_010"
    if v <= 25:
        return "RISK_011_025"
    if v <= 50:
        return "RISK_026_050"
    return "RISK_051_PLUS"


def _reward_bucket(v: Optional[float]) -> str:
    if v is None:
        return "REWARD_UNKNOWN"
    if v < 5:
        return "REWARD_LT_005"
    if v <= 10:
        return "REWARD_005_010"
    if v <= 25:
        return "REWARD_011_025"
    if v <= 50:
        return "REWARD_026_050"
    return "REWARD_051_PLUS"


def _rr_bucket(v: Optional[float]) -> str:
    if v is None:
        return "RR_UNKNOWN"
    if v < 0.8:
        return "RR_LT_0_8"
    if v < 1.0:
        return "RR_0_8_1_0"
    if v < 1.2:
        return "RR_1_0_1_2"
    return "RR_GT_1_2"


def _bars_bucket(v) -> str:
    if v is None or v == "":
        return "BARS_UNKNOWN"
    try:
        b = int(v)
    except (ValueError, TypeError):
        return "BARS_UNKNOWN"
    if b <= 1:
        return "BARS_001"
    if b <= 3:
        return "BARS_002_003"
    if b <= 10:
        return "BARS_004_010"
    return "BARS_011_PLUS"


# ── Diagnostic flags ───────────────────────────────────────────────────────────

def _compute_flags(row: dict, rr: dict, direction: Optional[str]) -> list[str]:
    flags: list[str] = []

    if not direction:
        flags.append("UNKNOWN_DIRECTION")

    risk = rr["risk_points"]
    reward = rr["reward_points"]
    rr_val = rr["rr"]

    if risk is not None and risk <= 0:
        flags.append("INVALID_RISK")
    if reward is not None and reward <= 0:
        flags.append("INVALID_REWARD")

    if rr_val is not None and rr_val < 0.8:
        flags.append("LOW_RR")
    if reward is not None and reward < 5 and "INVALID_REWARD" not in flags:
        flags.append("TINY_TAKE")
    if risk is not None and risk > 40 and "INVALID_RISK" not in flags:
        flags.append("BIG_RISK")

    reason = row.get("exit_reason") or ""
    bars = row.get("bars_held")
    try:
        bars_i = int(bars) if bars not in (None, "") else None
    except (ValueError, TypeError):
        bars_i = None

    if reason == "STOP" and bars_i is not None and bars_i <= 1:
        flags.append("ONE_BAR_STOP")
    if reason == "TAKE" and bars_i is not None and bars_i <= 1:
        flags.append("ONE_BAR_TAKE")

    status = row.get("status") or ""
    if status == "OPEN":
        flags.append("OPEN_TRADE")
    elif status == "CLOSED":
        if not row.get("exit_price") and row.get("exit_price") != 0:
            flags.append("NO_EXIT_DATA")
        elif not row.get("exit_timestamp"):
            flags.append("NO_EXIT_DATA")

    required_fields = ["trade_id", "entry_price", "stop_price", "take_price"]
    if any(row.get(f) in (None, "") for f in required_fields):
        flags.append("MISSING_FIELDS")

    return flags


# ── Single-trade enrichment ────────────────────────────────────────────────────

def enrich_trade(row: dict) -> tuple[dict, list[str]]:
    """Enrich a raw trade dict with computed diagnostic fields."""
    warnings: list[str] = []
    tid = row.get("trade_id", "?")

    enriched = dict(row)

    # Timestamps
    sig_utc = _parse_ts(row.get("signal_timestamp"), warnings, f"{tid}.signal_timestamp")
    ent_utc = _parse_ts(row.get("entry_timestamp"), warnings, f"{tid}.entry_timestamp")
    ext_utc = _parse_ts(row.get("exit_timestamp"), warnings, f"{tid}.exit_timestamp")

    ent_msk = _to_msk(ent_utc)
    sig_msk = _to_msk(sig_utc)
    ext_msk = _to_msk(ext_utc)

    enriched["signal_timestamp_utc"] = _iso_utc(sig_utc)
    enriched["signal_timestamp_msk"] = _iso_utc(sig_msk)
    enriched["entry_timestamp_utc"] = _iso_utc(ent_utc)
    enriched["entry_timestamp_msk"] = _iso_utc(ent_msk)
    enriched["entry_date_msk"] = ent_msk.strftime("%Y-%m-%d") if ent_msk else ""
    enriched["entry_hour_msk"] = ent_msk.hour if ent_msk else ""
    enriched["day_of_week_msk"] = _WEEKDAY_RU[ent_msk.weekday()] if ent_msk else ""
    enriched["exit_timestamp_utc"] = _iso_utc(ext_utc)
    enriched["exit_timestamp_msk"] = _iso_utc(ext_msk)

    # Direction (from data or inferred)
    direction = row.get("direction") or None
    if not direction:
        direction = _infer_direction(row)
        if direction:
            enriched["direction"] = direction
            warnings.append(f"Direction inferred as {direction} for {tid}")

    # Risk/Reward
    rr = _compute_rr_fields(row, direction, warnings)
    enriched.update(rr)

    # Buckets
    enriched["risk_bucket"] = _risk_bucket(rr["risk_points"])
    enriched["reward_bucket"] = _reward_bucket(rr["reward_points"])
    enriched["rr_bucket"] = _rr_bucket(rr["rr"])
    enriched["bars_bucket"] = _bars_bucket(row.get("bars_held"))

    # PnL sign
    pnl = row.get("pnl_rub")
    if pnl is None or pnl == "":
        enriched["pnl_sign"] = "UNKNOWN"
        enriched["abs_pnl_rub"] = ""
    else:
        p = float(pnl)
        enriched["pnl_sign"] = "WIN" if p > 0 else ("LOSS" if p < 0 else "FLAT")
        enriched["abs_pnl_rub"] = abs(p)

    # Diagnostic flags
    flags = _compute_flags(row, rr, direction)
    enriched["diagnostic_flags"] = ";".join(flags)

    return enriched, warnings


# ── Data loading ───────────────────────────────────────────────────────────────

def load_from_sqlite(
    db_path: str,
    ticker: Optional[str] = None,
    direction: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> tuple[list[dict], list[str], str]:
    """Returns (rows, warnings, source_label)."""
    warnings: list[str] = []
    path = Path(db_path)
    if not path.exists():
        return [], [f"SQLite not found: {db_path}"], ""

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "paper_trades" not in tables:
            return [], [f"Table paper_trades not found in {db_path}"], ""

        q = "SELECT * FROM paper_trades WHERE 1=1"
        params: list = []
        if ticker:
            q += " AND ticker=?"
            params.append(ticker)
        if direction:
            q += " AND direction=?"
            params.append(direction)
        if from_date:
            q += " AND entry_timestamp >= ?"
            params.append(from_date)
        if to_date:
            # inclusive: include whole day
            q += " AND entry_timestamp < ?"
            end = to_date + "T23:59:59.999999+00:00" if "T" not in to_date else to_date
            # just add one day
            from datetime import timedelta
            try:
                d = datetime.fromisoformat(to_date)
                end = (d + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+00:00")
            except ValueError:
                end = to_date + "T23:59:59Z"
            params.append(end)
        q += " ORDER BY entry_timestamp"

        rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    finally:
        conn.close()

    return rows, warnings, f"SQLite {db_path}"


def load_from_csv(
    csv_path: str,
    ticker: Optional[str] = None,
    direction: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> tuple[list[dict], list[str], str]:
    """Returns (rows, warnings, source_label)."""
    warnings: list[str] = []
    path = Path(csv_path)
    if not path.exists():
        return [], [f"CSV fallback not found: {csv_path}"], ""

    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if ticker and row.get("ticker") != ticker:
                continue
            if direction and row.get("direction") != direction:
                continue
            if from_date and row.get("entry_timestamp", "") < from_date:
                continue
            if to_date and row.get("entry_timestamp", "") > to_date + "Z":
                continue
            rows.append(row)

    return rows, warnings, f"CSV fallback {csv_path}"


# ── Aggregate stats ────────────────────────────────────────────────────────────

def _safe_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def compute_summary(enriched: list[dict]) -> dict:
    closed = [r for r in enriched if r.get("status") == "CLOSED"]
    open_trades = [r for r in enriched if r.get("status") == "OPEN"]

    wins = [r for r in closed if r.get("pnl_sign") == "WIN"]
    losses = [r for r in closed if r.get("pnl_sign") == "LOSS"]
    flats = [r for r in closed if r.get("pnl_sign") == "FLAT"]

    n_closed = len(closed)
    pnl_vals = [f for r in closed if (f := _safe_float(r.get("pnl_rub"))) is not None]

    gross_profit = sum(v for v in pnl_vals if v > 0)
    gross_loss = abs(sum(v for v in pnl_vals if v < 0))
    net_pnl = sum(pnl_vals)
    pf = gross_profit / gross_loss if gross_loss > 0 else None

    win_vals = [v for v in pnl_vals if v > 0]
    loss_vals = [v for v in pnl_vals if v < 0]

    risk_vals = [f for r in closed if (f := _safe_float(r.get("risk_points"))) is not None]
    rew_vals = [f for r in closed if (f := _safe_float(r.get("reward_points"))) is not None]
    rr_vals = [f for r in closed if (f := _safe_float(r.get("rr"))) is not None]
    bar_vals = [int(r["bars_held"]) for r in closed
                if r.get("bars_held") not in (None, "") and str(r["bars_held"]).isdigit()]

    def _avg(lst): return sum(lst) / len(lst) if lst else None
    def _med(lst): return median(lst) if lst else None

    return {
        "total_trades": len(enriched),
        "closed_trades": n_closed,
        "open_trades": len(open_trades),
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(flats),
        "winrate_pct": len(wins) / n_closed * 100 if n_closed else 0.0,
        "gross_profit_rub": gross_profit,
        "gross_loss_rub": gross_loss,
        "net_pnl_rub": net_pnl,
        "profit_factor": pf,
        "avg_pnl_rub": _avg(pnl_vals),
        "median_pnl_rub": _med(pnl_vals),
        "best_trade_rub": max(pnl_vals) if pnl_vals else None,
        "worst_trade_rub": min(pnl_vals) if pnl_vals else None,
        "avg_win_rub": _avg(win_vals),
        "avg_loss_rub": _avg(loss_vals),
        "expectancy_rub": net_pnl / n_closed if n_closed else None,
        "avg_risk_points": _avg(risk_vals),
        "avg_reward_points": _avg(rew_vals),
        "avg_rr": _avg(rr_vals),
        "avg_bars_held": _avg(bar_vals),
    }


def _group_row_stats(group_label, rows: list[dict]) -> dict:
    wins = [r for r in rows if r.get("pnl_sign") == "WIN"]
    losses = [r for r in rows if r.get("pnl_sign") == "LOSS"]
    flats = [r for r in rows if r.get("pnl_sign") == "FLAT"]
    pnl_vals = [f for r in rows if (f := _safe_float(r.get("pnl_rub"))) is not None]
    gross_profit = sum(v for v in pnl_vals if v > 0)
    gross_loss = abs(sum(v for v in pnl_vals if v < 0))
    net_pnl = sum(pnl_vals)
    n = len(rows)
    return {
        "group": group_label,
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(flats),
        "winrate_pct": len(wins) / n * 100 if n else 0.0,
        "gross_profit_rub": gross_profit,
        "gross_loss_rub": gross_loss,
        "net_pnl_rub": net_pnl,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "avg_pnl_rub": net_pnl / n if n else None,
    }


def compute_group_stats(enriched: list[dict], group_by: str) -> list[dict]:
    """Group closed trades by field; for diagnostic_flags each flag is its own group."""
    closed = [r for r in enriched if r.get("status") == "CLOSED"]
    if not closed:
        return []

    if group_by == "diagnostic_flags":
        # explode: one trade can belong to multiple flag groups
        from collections import defaultdict
        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in closed:
            flags_str = r.get("diagnostic_flags") or ""
            flags = [f for f in flags_str.split(";") if f]
            if not flags:
                buckets["(no flags)"].append(r)
            else:
                for flag in flags:
                    buckets[flag].append(r)
    else:
        from collections import defaultdict
        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in closed:
            key = str(r.get(group_by) or "(unknown)")
            buckets[key].append(r)

    result = [_group_row_stats(k, v) for k, v in sorted(buckets.items())]
    return result


# ── Filter hypotheses ──────────────────────────────────────────────────────────

def _compute_hypotheses(enriched: list[dict], summary: dict) -> list[str]:
    hypotheses: list[str] = []
    closed = [r for r in enriched if r.get("status") == "CLOSED"]
    if not closed:
        return hypotheses

    note = ("Выборка мала, выводы предварительные. Использовать эти гипотезы только "
            "для последующего backtest/grid-теста, не как готовые правила торговли.")
    hypotheses.append(note)

    # TINY_TAKE
    tiny = [r for r in closed if "TINY_TAKE" in (r.get("diagnostic_flags") or "")]
    if tiny:
        tiny_pnl = sum(f for r in tiny if (f := _safe_float(r.get("pnl_rub"))) is not None)
        if tiny_pnl < 0:
            hypotheses.append(
                "TINY_TAKE: сделки с reward_points < 5 показали отрицательный net PnL "
                f"({tiny_pnl:+.2f} RUB, {len(tiny)} сделок). "
                "Гипотеза: проверить фильтр MIN_REWARD_POINTS в backtest/grid."
            )

    # BIG_RISK
    big_risk = [r for r in closed if "BIG_RISK" in (r.get("diagnostic_flags") or "")]
    if big_risk:
        br_pnl = sum(f for r in big_risk if (f := _safe_float(r.get("pnl_rub"))) is not None)
        br_pnl_vals = [f for r in big_risk if (f := _safe_float(r.get("pnl_rub"))) is not None]
        worst = min(br_pnl_vals) if br_pnl_vals else None
        worst_overall = summary.get("worst_trade_rub")
        is_worst = worst is not None and worst_overall is not None and abs(worst - worst_overall) < 0.01
        if br_pnl < 0 or is_worst:
            hypotheses.append(
                "BIG_RISK: сделки с risk_points > 40 суммарно дали "
                f"{br_pnl:+.2f} RUB ({len(big_risk)} сделок). "
                "Гипотеза: проверить ограничение MAX_RISK_POINTS или "
                "отдельный режим для больших стопов. "
                "Осторожно: крупные импульсные движения могут давать и большую прибыль."
            )

    # LOW_RR
    low_rr = [r for r in closed if "LOW_RR" in (r.get("diagnostic_flags") or "")]
    if low_rr:
        lr_pnl = sum(f for r in low_rr if (f := _safe_float(r.get("pnl_rub"))) is not None)
        if lr_pnl < 0:
            hypotheses.append(
                "LOW_RR: сделки с R/R < 0.8 показали отрицательный net PnL "
                f"({lr_pnl:+.2f} RUB, {len(low_rr)} сделок). "
                "Гипотеза: проверить минимальный R/R перед входом в backtest/grid."
            )

    # ONE_BAR_STOP
    obs = [r for r in closed if "ONE_BAR_STOP" in (r.get("diagnostic_flags") or "")]
    if obs:
        hypotheses.append(
            f"ONE_BAR_STOP: {len(obs)} сделок закрылись по стопу уже на первом баре. "
            "Гипотеза: проверить дополнительное подтверждение входа."
        )

    # Profit concentration
    gross_profit = summary.get("gross_profit_rub") or 0
    net_pnl = summary.get("net_pnl_rub") or 0
    if gross_profit > 0:
        win_trades = sorted(
            [r for r in closed if _safe_float(r.get("pnl_rub")) and float(r["pnl_rub"]) > 0],
            key=lambda r: float(r["pnl_rub"]),
            reverse=True,
        )
        top2_sum = sum(float(r["pnl_rub"]) for r in win_trades[:2]) if len(win_trades) >= 2 else (
            float(win_trades[0]["pnl_rub"]) if win_trades else 0
        )
        ref = max(abs(gross_profit), abs(net_pnl))
        if ref > 0 and top2_sum / ref > 0.70:
            hypotheses.append(
                f"КОНЦЕНТРАЦИЯ ПРИБЫЛИ: top-2 сделки дают {top2_sum:.2f} RUB "
                f"({top2_sum/ref*100:.0f}% от gross_profit). "
                "Результат может сильно зависеть от нескольких импульсных сделок — "
                "проверить устойчивость на большей выборке."
            )

    return hypotheses


# ── Markdown report ────────────────────────────────────────────────────────────

def _fmt(v, decimals=2, suffix="") -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{decimals}f}{suffix}"
    return str(v)


def _pf_str(pf: Optional[float]) -> str:
    if pf is None:
        return "N/A"
    if pf == float("inf"):
        return "∞"
    return f"{pf:.2f}"


def _md_table(headers: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |"]
    sep = "|" + "|".join("-" * (len(h) + 2) for h in headers) + "|"
    lines.append(sep)
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return lines


def _group_table(groups: list[dict]) -> list[str]:
    if not groups:
        return ["_Нет данных._"]
    headers = ["Группа", "Сделок", "W", "L", "WR%", "Gross+", "Gross−", "Net", "PF", "Avg"]
    rows_out = []
    for g in groups:
        rows_out.append([
            g["group"],
            g["trades"],
            g["wins"],
            g["losses"],
            _fmt(g["winrate_pct"], 1),
            _fmt(g["gross_profit_rub"], 2),
            _fmt(g["gross_loss_rub"], 2),
            _fmt(g["net_pnl_rub"], 2),
            _pf_str(g["profit_factor"]),
            _fmt(g["avg_pnl_rub"], 2),
        ])
    return _md_table(headers, rows_out)


def build_markdown_report(
    enriched: list[dict],
    summary: dict,
    groups: dict,
    hypotheses: list[str],
    warnings: list[str],
    source_label: str,
    ticker: str,
    direction: str,
    generated_at: str,
) -> str:
    closed = [r for r in enriched if r.get("status") == "CLOSED"]
    open_trades = [r for r in enriched if r.get("status") == "OPEN"]

    dates = sorted(set(r.get("entry_date_msk", "") for r in enriched if r.get("entry_date_msk")))
    period_str = f"{dates[0]} – {dates[-1]}" if len(dates) > 1 else (dates[0] if dates else "—")

    lines: list[str] = [
        f"# Paper Trading Diagnostics — {ticker} {direction}",
        "",
        f"Сгенерировано: {generated_at}",
        "",
        "## Период",
        "",
        period_str,
        "",
        "## Источник данных",
        "",
        source_label,
        "",
        "## Общая статистика",
        "",
    ]

    s = summary
    stats_rows = [
        ("Всего сделок", s["total_trades"]),
        ("Закрытых", s["closed_trades"]),
        ("Открытых", s["open_trades"]),
        ("Побед (WIN)", s["wins"]),
        ("Поражений (LOSS)", s["losses"]),
        ("Ровных (FLAT)", s["flats"]),
        ("Winrate", _fmt(s["winrate_pct"], 1, "%")),
        ("Gross profit RUB", _fmt(s["gross_profit_rub"])),
        ("Gross loss RUB", _fmt(s["gross_loss_rub"])),
        ("Net PnL RUB", _fmt(s["net_pnl_rub"])),
        ("Profit Factor", _pf_str(s["profit_factor"])),
        ("Avg PnL RUB", _fmt(s["avg_pnl_rub"])),
        ("Median PnL RUB", _fmt(s["median_pnl_rub"])),
        ("Best trade RUB", _fmt(s["best_trade_rub"])),
        ("Worst trade RUB", _fmt(s["worst_trade_rub"])),
        ("Avg win RUB", _fmt(s["avg_win_rub"])),
        ("Avg loss RUB", _fmt(s["avg_loss_rub"])),
        ("Expectancy RUB", _fmt(s["expectancy_rub"])),
        ("Avg risk pts", _fmt(s["avg_risk_points"], 1)),
        ("Avg reward pts", _fmt(s["avg_reward_points"], 1)),
        ("Avg R/R", _fmt(s["avg_rr"], 2)),
        ("Avg bars held", _fmt(s["avg_bars_held"], 1)),
    ]
    lines += _md_table(["Метрика", "Значение"], stats_rows)
    lines.append("")

    def _section(title: str, group_key: str):
        lines.append(f"## {title}")
        lines.append("")
        lines.extend(_group_table(groups.get(group_key, [])))
        lines.append("")

    _section("Статистика по дням", "entry_date_msk")
    _section("Статистика по часам входа", "entry_hour_msk")
    _section("Статистика по exit_reason", "exit_reason")
    _section("Risk buckets", "risk_bucket")
    _section("Reward buckets", "reward_bucket")
    _section("R/R buckets", "rr_bucket")
    _section("Bars held buckets", "bars_bucket")
    _section("Diagnostic flags", "diagnostic_flags")

    # Suspicious trades
    lines += ["## Подозрительные сделки", ""]
    suspicious = [r for r in closed if r.get("diagnostic_flags")]
    if not suspicious:
        lines.append("_Подозрительных сделок нет._")
    else:
        show = sorted(suspicious, key=lambda r: _safe_float(r.get("pnl_rub")) or 0)[:50]
        if len(suspicious) > 50:
            lines.append(f"_Показаны 50 из {len(suspicious)} подозрительных сделок (худшие по PnL)._")
        hdrs = ["Вход (МСК)", "Dir", "Entry", "Stop", "Take", "Exit", "Reason",
                "PnL RUB", "Risk", "Reward", "RR", "Bars", "Flags"]
        tbl_rows = []
        for r in show:
            tbl_rows.append([
                r.get("entry_timestamp_msk", "")[:16],
                r.get("direction", ""),
                _fmt(_safe_float(r.get("entry_price")), 0),
                _fmt(_safe_float(r.get("stop_price")), 0),
                _fmt(_safe_float(r.get("take_price")), 0),
                _fmt(_safe_float(r.get("exit_price")), 0),
                r.get("exit_reason", ""),
                _fmt(_safe_float(r.get("pnl_rub"))),
                _fmt(_safe_float(r.get("risk_points")), 1),
                _fmt(_safe_float(r.get("reward_points")), 1),
                _fmt(_safe_float(r.get("rr")), 2),
                r.get("bars_held", ""),
                r.get("diagnostic_flags", ""),
            ])
        lines += _md_table(hdrs, tbl_rows)
    lines.append("")

    def _top_bottom_table(trades_list: list[dict], title: str):
        lines.append(f"## {title}")
        lines.append("")
        hdrs = ["Вход (МСК)", "Reason", "PnL RUB", "Risk", "Reward", "RR", "Bars", "Flags"]
        tbl_rows = []
        for r in trades_list:
            tbl_rows.append([
                r.get("entry_timestamp_msk", "")[:16],
                r.get("exit_reason", ""),
                _fmt(_safe_float(r.get("pnl_rub"))),
                _fmt(_safe_float(r.get("risk_points")), 1),
                _fmt(_safe_float(r.get("reward_points")), 1),
                _fmt(_safe_float(r.get("rr")), 2),
                r.get("bars_held", ""),
                r.get("diagnostic_flags", ""),
            ])
        lines.extend(_md_table(hdrs, tbl_rows))
        lines.append("")

    pnl_sorted = sorted(closed, key=lambda r: _safe_float(r.get("pnl_rub")) or 0, reverse=True)
    _top_bottom_table(pnl_sorted[:5], "Лучшие сделки (top 5)")
    _top_bottom_table(pnl_sorted[-5:] if len(pnl_sorted) >= 5 else pnl_sorted, "Худшие сделки (bottom 5)")

    # Open trades
    lines += ["## Открытые сделки", ""]
    if not open_trades:
        lines.append("_Открытых сделок нет._")
    else:
        hdrs = ["trade_id", "Вход (МСК)", "Dir", "Entry", "Stop", "Take", "Bars", "Flags"]
        tbl_rows = []
        for r in open_trades:
            tbl_rows.append([
                (r.get("trade_id") or "")[-20:],
                r.get("entry_timestamp_msk", "")[:16],
                r.get("direction", ""),
                _fmt(_safe_float(r.get("entry_price")), 0),
                _fmt(_safe_float(r.get("stop_price")), 0),
                _fmt(_safe_float(r.get("take_price")), 0),
                r.get("bars_held", ""),
                r.get("diagnostic_flags", ""),
            ])
        lines += _md_table(hdrs, tbl_rows)
    lines.append("")

    # Hypotheses
    lines += ["## Предварительные гипотезы фильтров", ""]
    if not hypotheses:
        lines.append("_Гипотез для текущей выборки не сформировано._")
    else:
        for h in hypotheses:
            lines.append(f"- {h}")
    lines.append("")

    # Warnings
    lines += ["## Warnings", ""]
    if not warnings:
        lines.append("_Предупреждений нет._")
    else:
        for w in warnings:
            lines.append(f"- {w}")
    lines.append("")

    return "\n".join(lines)


# ── Main entry point ───────────────────────────────────────────────────────────

def run_diagnostics(
    db_path: str = "data/paper/paper_state.sqlite",
    csv_fallback: str = "out/paper/paper_trades_SiM6_SELL.csv",
    ticker: Optional[str] = None,
    direction: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> DiagnosticsResult:
    all_warnings: list[str] = []

    rows, load_warnings, source = load_from_sqlite(db_path, ticker, direction, from_date, to_date)
    all_warnings += load_warnings

    if not rows and not source:
        rows, load_warnings, source = load_from_csv(csv_fallback, ticker, direction, from_date, to_date)
        all_warnings += load_warnings
        if source:
            all_warnings.append(f"SQLite unavailable — using CSV fallback: {csv_fallback}")

    if not rows:
        all_warnings.append("No trades found — report will be empty.")

    enriched: list[dict] = []
    for row in rows:
        e, w = enrich_trade(row)
        enriched.append(e)
        all_warnings += w

    summary = compute_summary(enriched)

    group_keys = [
        "entry_date_msk", "entry_hour_msk", "exit_reason",
        "risk_bucket", "reward_bucket", "rr_bucket", "bars_bucket", "diagnostic_flags",
    ]
    groups = {k: compute_group_stats(enriched, k) for k in group_keys}

    hypotheses = _compute_hypotheses(enriched, summary)

    return DiagnosticsResult(
        enriched=enriched,
        summary=summary,
        groups=groups,
        hypotheses=hypotheses,
        warnings=all_warnings,
        source_label=source,
    )
