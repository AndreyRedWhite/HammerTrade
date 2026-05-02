"""Generate paper trading markdown report from SQLite state."""
from datetime import datetime, timezone
from typing import Optional

from src.paper.models import PaperTradeStatus, PaperExitReason
from src.paper.repository import PaperRepository


def generate_paper_report(
    repo: PaperRepository,
    output_path: str,
    ticker: Optional[str] = None,
    created_at: Optional[str] = None,
) -> str:
    trades = repo.list_recent_trades(ticker=ticker, limit=1000)
    now_str = created_at or datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    closed = [t for t in trades if t.status == PaperTradeStatus.CLOSED]
    open_trades = [t for t in trades if t.status == PaperTradeStatus.OPEN]

    total = len(trades)
    n_closed = len(closed)
    n_open = len(open_trades)

    net_pnl = sum(t.pnl_rub for t in closed if t.pnl_rub is not None)
    winners = [t for t in closed if t.pnl_rub is not None and t.pnl_rub > 0]
    losers = [t for t in closed if t.pnl_rub is not None and t.pnl_rub <= 0]
    winrate = len(winners) / n_closed * 100 if n_closed > 0 else 0.0

    gross_win = sum(t.pnl_rub for t in winners if t.pnl_rub is not None)
    gross_loss = abs(sum(t.pnl_rub for t in losers if t.pnl_rub is not None))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")

    lines = [
        "# Paper Trading Report",
        "",
        f"Generated: {now_str}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Trades total | {total} |",
        f"| Open trades | {n_open} |",
        f"| Closed trades | {n_closed} |",
        f"| Net PnL RUB | {net_pnl:.2f} |",
        f"| Winrate | {winrate:.1f}% |",
        f"| Profit Factor | {profit_factor:.2f} |",
        "",
    ]

    if open_trades:
        lines += [
            "## Open Trades",
            "",
            "| Trade ID | Ticker | Direction | Entry | Stop | Take | Bars held |",
            "|----------|--------|-----------|------:|-----:|-----:|----------:|",
        ]
        for t in open_trades:
            short_id = t.trade_id.split(":")[-1][:19] if ":" in t.trade_id else t.trade_id[:19]
            lines.append(
                f"| {short_id} | {t.ticker} | {t.direction} "
                f"| {t.entry_price:.4f} | {t.stop_price:.4f} | {t.take_price:.4f} "
                f"| {t.bars_held} |"
            )
        lines.append("")

    if closed:
        recent = sorted(closed, key=lambda t: t.exit_timestamp or t.entry_timestamp, reverse=True)[:20]
        lines += [
            "## Recent Closed Trades",
            "",
            "| Ticker | Dir | Entry | Exit | Reason | PnL RUB | Bars |",
            "|--------|-----|------:|-----:|--------|--------:|-----:|",
        ]
        for t in recent:
            reason = t.exit_reason.value if t.exit_reason else "-"
            pnl = f"{t.pnl_rub:.2f}" if t.pnl_rub is not None else "-"
            exit_p = f"{t.exit_price:.4f}" if t.exit_price is not None else "-"
            lines.append(
                f"| {t.ticker} | {t.direction} "
                f"| {t.entry_price:.4f} | {exit_p} | {reason} | {pnl} | {t.bars_held} |"
            )
        lines.append("")

    content = "\n".join(lines)

    import os
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write(content)

    return content
