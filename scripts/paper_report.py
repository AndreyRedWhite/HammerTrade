"""Generate a paper trading report from SQLite state."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper.repository import PaperRepository
from src.paper.report import generate_paper_report


def main():
    p = argparse.ArgumentParser(description="Generate paper trading markdown report")
    p.add_argument("--state-db", default="data/paper/paper_state.sqlite")
    p.add_argument("--output", default="reports/paper_report_SiM6_SELL.md")
    p.add_argument("--ticker", default=None, help="Filter by ticker (optional)")
    args = p.parse_args()

    if not Path(args.state_db).exists():
        print(f"ERROR: state DB not found: {args.state_db}", file=sys.stderr)
        sys.exit(1)

    repo = PaperRepository(args.state_db)
    repo.init_db()

    content = generate_paper_report(repo, args.output, ticker=args.ticker)
    print(f"Report written to: {args.output}")
    print()
    print(content)


if __name__ == "__main__":
    main()
