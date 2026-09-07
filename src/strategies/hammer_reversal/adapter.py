"""Hammer Reversal strategy — legacy / paper-driven adapter.

This module documents that the Hammer Reversal strategy is currently implemented
as a live paper-trading pipeline (src/paper/, src/strategy/) driven by real-time
candle detection via src/strategy/hammer_detector.py.

It has NOT been ported to the Strategy ABC yet. The reasons:

1. The live paper engine has significant state (OPEN trades, status tracking, SQLite
   persistence) that does not map cleanly to stateless generate_signals() + simulate_trade().
2. The hammer detector parameters (upper_wick_ratio, body_ratio, etc.) are loaded from
   environment profiles (.env files in configs/) at runtime.
3. Full backtesting of the hammer strategy is handled by src/backtest/engine.py and
   scripts/run_backtest_grid.py — these already produce StrategyResult-equivalent metrics.

Migration plan (future work):
  - Wrap HammerDetector in an adapter that implements Strategy ABC
  - Accept detector params as config_dict rather than env vars
  - Port simulate_trade() logic from src/backtest/engine.py
"""


class HammerReversalStrategyAdapter:
    """Placeholder documenting the legacy hammer reversal strategy structure.

    Not yet implementing the Strategy ABC — see module docstring for rationale.

    Paper-trading live implementation:
      - Signal generation: src/strategy/hammer_detector.py
      - Trade execution: src/paper/engine.py
      - State persistence: src/paper/repository.py (SQLite)
      - CLI entry-point: scripts/run_paper_trader.py
      - Services: hammertrade-paper.service, hammertrade-paper-maxhold5.service

    Backtest (historical) implementation:
      - Engine: src/backtest/engine.py
      - Grid runner: scripts/run_backtest_grid.py
      - Config: configs/backtest_*.yaml
    """

    name = "hammer_reversal"

    def __init__(self):
        raise NotImplementedError(
            "HammerReversalStrategyAdapter is not yet ported to the Strategy ABC. "
            "Use src/backtest/engine.py for historical backtests."
        )
