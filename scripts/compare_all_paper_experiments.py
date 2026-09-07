"""Compare all parallel paper trading experiments.

Reads hammer-baseline, hammer-maxhold5, and orb-or60-short2r DBs and
prints a comparison table.

Usage:
    python scripts/compare_all_paper_experiments.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compare all paper trading experiments")
    p.add_argument("--baseline-db", default="data/paper/paper_state_siu6.sqlite")
    p.add_argument("--maxhold5-db", default="data/paper/paper_state_siu6_maxhold5.sqlite")
    p.add_argument("--orb-db", default="data/paper/paper_state_siu6_orb.sqlite")
    p.add_argument("--baseline-ticker", default="SiU6")
    p.add_argument("--maxhold5-ticker", default="SiU6")
    p.add_argument("--orb-ticker", default="SiU6")
    p.add_argument("--orb-experiment", default="orb_or60_short2r")
    return p.parse_args()


# ──────────────────────────── Hammer metrics ─────────────────────────────────

def _load_hammer_trades(db_path: str) -> list:
    p = Path(db_path)
    if not p.exists():
        return []
    from src.paper.models import PaperTradeStatus
    from src.paper.repository import PaperRepository
    repo = PaperRepository(str(p))
    repo.init_db()
    return repo.list_recent_trades(limit=10000)


def _hammer_metrics(trades: list, name: str, direction: str = "SELL") -> dict:
    from src.paper.models import PaperTradeStatus

    closed = [t for t in trades if t.status == PaperTradeStatus.CLOSED]
    open_n = [t for t in trades if t.status == PaperTradeStatus.OPEN]
    wins = [t for t in closed if (t.pnl_rub or 0) > 0]
    losses = [t for t in closed if (t.pnl_rub or 0) < 0]
    gross_p = sum(t.pnl_rub for t in wins) if wins else 0.0
    gross_l = sum(t.pnl_rub for t in losses) if losses else 0.0
    net = sum(t.pnl_rub or 0 for t in closed)
    pf = (gross_p / abs(gross_l)) if gross_l != 0 else float("inf")
    winrate = 100.0 * len(wins) / len(closed) if closed else 0.0
    max_dd = _compute_drawdown_hammer(closed)

    dated = [t for t in closed if t.entry_timestamp]
    first_date = min(t.entry_timestamp for t in dated).strftime("%b%d") if dated else "—"
    last_date = max(t.entry_timestamp for t in dated).strftime("%b%d") if dated else "—"
    period = f"{first_date}-{last_date}" if dated else "(no data)"

    return {
        "name": name,
        "ticker": "SiU6",
        "direction": direction,
        "period": period,
        "closed_trades": len(closed),
        "open_trades": len(open_n),
        "winrate_pct": winrate,
        "net_pnl_rub": net,
        "profit_factor": pf,
        "max_dd_rub": max_dd,
    }


def _compute_drawdown_hammer(trades: list) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.entry_timestamp or datetime.min):
        equity += t.pnl_rub or 0.0
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return max_dd


# ──────────────────────────── ORB metrics ────────────────────────────────────

def _load_orb_trades(db_path: str, ticker: str) -> list:
    p = Path(db_path)
    if not p.exists():
        return []
    from src.paper.orb.repository import OrbRepository
    repo = OrbRepository(str(p))
    repo.init_db()
    return repo.list_all_trades(ticker=ticker)


def _orb_metrics(trades: list, name: str, experiment: str) -> dict:
    from src.paper.orb.models import OrbTradeStatus

    closed = [t for t in trades if t.status == OrbTradeStatus.CLOSED]
    open_n = [t for t in trades if t.status == OrbTradeStatus.OPEN]
    wins = [t for t in closed if (t.pnl_rub or 0) > 0]
    losses = [t for t in closed if (t.pnl_rub or 0) < 0]
    gross_p = sum(t.pnl_rub for t in wins) if wins else 0.0
    gross_l = sum(t.pnl_rub for t in losses) if losses else 0.0
    net = sum(t.pnl_rub or 0 for t in closed)
    pf = (gross_p / abs(gross_l)) if gross_l != 0 else float("inf")
    winrate = 100.0 * len(wins) / len(closed) if closed else 0.0
    max_dd = _compute_drawdown_orb(closed)

    direction = trades[0].direction if trades else "SHORT"

    dated = [t for t in closed if t.entry_timestamp]
    first_date = min(t.entry_timestamp for t in dated).strftime("%b%d") if dated else "—"
    last_date = max(t.entry_timestamp for t in dated).strftime("%b%d") if dated else "—"
    period = f"{first_date}-{last_date}" if dated else "(collecting)"

    return {
        "name": name,
        "ticker": "SiU6",
        "direction": direction,
        "period": period,
        "closed_trades": len(closed),
        "open_trades": len(open_n),
        "winrate_pct": winrate,
        "net_pnl_rub": net,
        "profit_factor": pf,
        "max_dd_rub": max_dd,
    }


def _compute_drawdown_orb(trades: list) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    from datetime import datetime as _dt
    for t in sorted(trades, key=lambda x: x.entry_timestamp or _dt.min):
        equity += t.pnl_rub or 0.0
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return max_dd


# ──────────────────────────── display ────────────────────────────────────────

def _fmt_pf(pf) -> str:
    if pf == float("inf"):
        return "∞"
    return f"{pf:.2f}"


def _fmt_pnl(v: float) -> str:
    return f"{v:+.0f}"


def _fmt_wr(v: float, n: int) -> str:
    if n == 0:
        return "--"
    return f"{v:.1f}%"


def main() -> int:
    args = _parse_args()
    now = datetime.now(tz=timezone.utc)

    baseline_trades = _load_hammer_trades(args.baseline_db)
    maxhold5_trades = _load_hammer_trades(args.maxhold5_db)
    orb_trades = _load_orb_trades(args.orb_db, args.orb_ticker)

    baseline = _hammer_metrics(baseline_trades, "hammer-baseline", "SELL")
    maxhold5 = _hammer_metrics(maxhold5_trades, "hammer-maxhold5", "SELL")
    orb = _orb_metrics(orb_trades, f"orb-{args.orb_experiment[:12]}", args.orb_experiment)

    print(f"\nPaper Experiment Comparison — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 90)
    header = (
        f"{'Experiment':<22} {'Ticker':<7} {'Dir':<6} "
        f"{'Period':<16} {'Trades':<7} {'WR%':<7} {'Net PnL':<10} {'PF':<7} {'MaxDD'}"
    )
    print(header)
    print("=" * 90)

    for m in [baseline, maxhold5, orb]:
        n = m["closed_trades"]
        pnl_str = _fmt_pnl(m["net_pnl_rub"]) if n > 0 else "0"
        wr_str = _fmt_wr(m["winrate_pct"], n)
        pf_str = _fmt_pf(m["profit_factor"]) if n > 0 else "--"
        dd_str = f"{m['max_dd_rub']:.0f}" if n > 0 else "--"

        print(
            f"{m['name']:<22} {m['ticker']:<7} {m['direction']:<6} "
            f"{m['period']:<16} {n:<7} {wr_str:<7} {pnl_str:<10} {pf_str:<7} {dd_str}"
        )

    print("=" * 90)
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
