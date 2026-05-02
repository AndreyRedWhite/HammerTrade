# MOEXF Hammer Bot — MVP-0 Explainable Detector

**Research project. Live trading is strictly prohibited at this stage.**

This project detects hammer and inverted-hammer candlestick patterns in MOEX futures data
and produces an explainable debug CSV showing why each candle was accepted or rejected.

---

## Input CSV format

```
timestamp,open,high,low,close,volume
2024-01-15 10:00:00,87500,87600,87300,87550,1200
2024-01-15 10:01:00,87550,87700,87100,87650,980
```

The `timestamp` column must be parseable by `pandas.to_datetime`.

---

## How to run

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the detector:

```bash
python -m src.main \
  --input data/raw/sample.csv \
  --output out/debug_simple_all.csv \
  --params configs/hammer_detector_balanced.env \
  --instrument SiM6 \
  --timeframe 1m \
  --profile balanced
```

Available config profiles:
- `configs/hammer_detector_balanced.env` — baseline
- `configs/hammer_detector_strict.env` — tighter filters
- `configs/hammer_detector_loose.env` — relaxed filters
- `configs/hammer_detector_sell_upper_wick.env` — tuned for SELL upper-wick patterns

---

## Output: `out/debug_simple_all.csv`

One row per input candle. Key columns:

| Column | Description |
|--------|-------------|
| `direction_candidate` | `BUY` or `SELL` based on dominant shadow |
| `is_signal` | `True` if all filters passed |
| `fail_reason` | First filter that rejected the candle, or `pass` |
| `fail_reasons` | All failed filters separated by `\|` |
| `params_profile` | Config profile name used |

---

## `fail_reason` values

| Value | Meaning |
|-------|---------|
| `pass` | Candle is a valid signal |
| `invalid_range` | high == low, candle is degenerate |
| `range` | Candle range too small |
| `doji` | Body too small (body_frac < S_BODY_MIN_FRAC) |
| `body_big` | Body too large (body_frac > S_BODY_MAX_FRAC) |
| `wick_abs` | Working shadow too short in absolute ticks |
| `opp_abs` | Opposite shadow too large in absolute ticks |
| `dom_fail` | Working shadow doesn't dominate body or opposite shadow |
| `sil_fail` | Working shadow fraction of range is too small |
| `ext` | Candle is not a local extremum in the window |
| `neighbors` | Neighbor candle has a more extreme low/high |
| `close_pos` | Close not in expected zone (too low for BUY, too high for SELL) |
| `excursion` | Next bars don't move enough in signal direction |
| `confirm` | Next bar doesn't break signal high (BUY) or low (SELL) |
| `clearing` | Candle falls within clearing block window |
| `cooldown` | Too soon after previous signal |
| `no_candidate` | Neither shadow is dominant |

---

## Run tests

```bash
pytest
```

---

## T-Bank historical candles loader

This module downloads historical OHLCV candles from T-Bank Invest API
and saves them as CSV compatible with the hammer detector.

**Live trading is strictly prohibited. This module is read-only.**

### Install T-Bank SDK

The SDK is distributed via a custom PyPI index:

```bash
pip install t-tech-investments \
  --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple
```

### Tokens

Create `.env` in project root (copy from `.env.example`):

```env
READONLY_TOKEN=your_readonly_token
SANDBOX_TOKEN=your_sandbox_token
TBANK_ENV=prod
LIVE_TRADING_ENABLED=false
SANDBOX_TRADING_ENABLED=false
```

**Never commit `.env`.**

- `READONLY_TOKEN` — prod token with read-only access (market data only)
- `SANDBOX_TOKEN` — sandbox token (for testing)

### Load historical candles

```bash
python scripts/load_tbank_candles.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --from 2026-04-01 \
  --to 2026-04-10 \
  --timeframe 1m \
  --env prod \
  --output data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv
```

Supported timeframes: `1m`, `5m`, `15m`, `1h`, `1d`

### Check data quality

```bash
python -m src.analytics.data_quality_report \
  --input data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv \
  --output reports/data_quality_SiM6_1m.md \
  --timeframe 1m
```

### Full pipeline on downloaded data

```bash
# 1. Download candles
python scripts/load_tbank_candles.py \
  --ticker SiM6 --class-code SPBFUT \
  --from 2026-04-01 --to 2026-04-10 \
  --timeframe 1m --env prod \
  --output data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv

# 2. Check data quality
python -m src.analytics.data_quality_report \
  --input data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv \
  --output reports/data_quality_SiM6_1m.md \
  --timeframe 1m

# 3. Run hammer detector
python -m src.main \
  --input data/raw/tbank/SiM6_1m_2026-04-01_2026-04-10.csv \
  --output out/debug_simple_all.csv \
  --params configs/hammer_detector_balanced.env \
  --instrument SiM6 --timeframe 1m --profile balanced

# 4. Generate debug report
python -m src.analytics.debug_report \
  --input out/debug_simple_all.csv \
  --output reports/debug_report.md
```

---

## Backtest v1

Offline historical backtest on top of `out/debug_simple_all.csv`. **Does not place real or sandbox orders.**

### Entry modes

- `close` — enter at the close price of the signal candle
- `breakout` — enter on the first subsequent bar that breaks the signal high (BUY) or low (SELL) within `--entry-horizon-bars`

### Stop-loss

- BUY: `stop_price = signal_low - stop_buffer_points`
- SELL: `stop_price = signal_high + stop_buffer_points`

### Take-profit (R-multiple)

- BUY: `take_price = entry_price + (entry_price - stop_price) * take_r`
- SELL: `take_price = entry_price - (stop_price - entry_price) * take_r`

### Commission

```text
commission_rub = commission_per_trade * 2 * contracts
```

### Run backtest

```bash
python scripts/run_backtest.py \
  --input out/debug_simple_all.csv \
  --trades-output out/backtest_trades.csv \
  --report-output reports/backtest_report.md \
  --entry-mode breakout \
  --entry-horizon-bars 3 \
  --max-hold-bars 30 \
  --take-r 1.0 \
  --stop-buffer-points 0 \
  --point-value-rub 10 \
  --commission-per-trade 0.025 \
  --contracts 1
```

### Slippage model

Add `--slippage-points N` to model execution slippage. BUY: entry is worse by N, exit is worse by N (total impact ≈ 2N points). SELL: symmetric.

### Output files

- `out/backtest_trades.csv` — one row per signal; includes `entry_price_raw`, `exit_price_raw`, `slippage_points`
- `reports/backtest_report.md` — Markdown report with summary, drawdown, direction breakdown, exit reasons, trades table

---

## Backtest robustness / grid search

Grid backtest is used to check strategy robustness to parameter changes, **not** to fit parameters to historical data.

```bash
python scripts/run_backtest_grid.py \
  --input out/debug_simple_all.csv \
  --output out/backtest_grid_results.csv \
  --report-output reports/backtest_grid_report.md \
  --entry-modes breakout,close \
  --take-r-values 0.5,1.0,1.5,2.0 \
  --max-hold-bars-values 5,10,30,60 \
  --stop-buffer-points-values 0,1,2,5 \
  --slippage-points-values 0,1,2,5
```

Runs all combinations of the listed values (default above = 512 scenarios).

### Output files

- `out/backtest_grid_results.csv` — one row per scenario with all metrics
- `reports/backtest_grid_report.md` — top/worst scenarios, slippage/take-R/entry-mode/stop-buffer sensitivity tables, robust scenarios

---

## Walk-forward / multi-period backtest

Walk-forward analysis checks whether the strategy's profitability is stable across different time periods, or whether it was made by a single lucky stretch of history.

**Periods are counted in Moscow time (Europe/Moscow).** A UTC timestamp is converted to MSK before assigning a day/week/month key.

**Trades do not carry over across period boundaries.** Each period is an independent backtest — if a signal fires at the end of period N, its trade closes within period N (exit_reason = `timeout` or `end_of_data`), not in period N+1.

### Run single walk-forward

```bash
python scripts/run_walkforward.py \
  --input out/debug_simple_all.csv \
  --period week \
  --period-results-output out/walkforward_period_results.csv \
  --trades-output out/walkforward_trades.csv \
  --report-output reports/walkforward_report.md \
  --entry-mode breakout \
  --max-hold-bars 30 \
  --take-r 1.0 \
  --slippage-points 1
```

Supported periods: `day`, `week`, `month`.

### Run walk-forward grid

```bash
python scripts/run_walkforward_grid.py \
  --input out/debug_simple_all.csv \
  --period week \
  --output out/walkforward_grid_results.csv \
  --report-output reports/walkforward_grid_report.md \
  --entry-modes breakout,close \
  --take-r-values 0.5,1.0,1.5,2.0 \
  --max-hold-bars-values 5,10,30,60 \
  --stop-buffer-points-values 0,1,2,5 \
  --slippage-points-values 0,1,2,5
```

### Reading the report

- **Stability summary** — profitable_periods_pct, period_profit_factor, best/worst period
- **Profit concentration** — how much of the profit came from the top 10% of trades or top 2 periods
- **Period results table** — one row per period with PnL, winrate, drawdown, BUY/SELL split
- **Scenario stability ranking** (grid) — each scenario ranked by how consistently it profits across periods
- **Robust scenarios** — scenarios that are profitable, stable, and not catastrophically volatile
- **Fragile scenarios** — profitable overall but depend on a few good periods

This is not live trading and does not prove the strategy is profitable in real markets.

---

## Full research pipeline

`scripts/run_full_research_pipeline.sh` runs the complete research workflow in one command:

1. Download raw candles from T-Bank API
2. Generate data quality report
3. Run HammerDetector → `out/debug_simple_all.csv` + run-specific copy
4. Generate debug report
5. Run single backtest (trades CSV + report)
6. Run grid backtest (512 scenarios)
7. Run weekly walk-forward
8. Run daily walk-forward grid
9. Run weekly walk-forward grid
10. Package all output into `archives/research_<RUN_ID>.zip`

> **Note:** T-Bank API access is required for step 1. If you are running this in an environment where T-Bank is not accessible (e.g. with VPN that blocks it), use `--skip-load` after the data is already downloaded locally.

### Basic run

```bash
./scripts/run_full_research_pipeline.sh \
  --ticker SiM6 \
  --class-code SPBFUT \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --timeframe 1m \
  --profile balanced \
  --env prod
```

### Different period or instrument

```bash
./scripts/run_full_research_pipeline.sh \
  --ticker BRM6 \
  --from 2026-01-01 \
  --to 2026-03-31
```

### Re-run analysis on already downloaded data

Use `--skip-load` to skip the T-Bank API call and reuse an existing raw CSV:

```bash
./scripts/run_full_research_pipeline.sh \
  --ticker SiM6 \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --profile balanced \
  --skip-load
```

The script expects `data/raw/tbank/SiM6_1m_2026-03-01_2026-04-10_balanced.csv` to already exist.

### Skip heavy grid steps

```bash
./scripts/run_full_research_pipeline.sh \
  --ticker SiM6 \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --skip-load \
  --skip-grid \
  --skip-walkforward-grid
```

Runs only: data quality → detector → debug report → single backtest → weekly walk-forward.

### Disable archive creation

```bash
./scripts/run_full_research_pipeline.sh \
  --ticker SiM6 \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --skip-load \
  --no-archive
```

### Archive location

Each run creates two copies of the archive and a manifest file:

```text
archives/latest/Actual_<RUN_ID>.zip          ← always the most recent run for this RUN_ID
archives/latest/Actual_<RUN_ID>.manifest.txt

archives/old/research_<RUN_ID>_<YYYYMMDD_HHMMSS>.zip          ← timestamped history
archives/old/research_<RUN_ID>_<YYYYMMDD_HHMMSS>.manifest.txt
```

Example:

```text
archives/latest/Actual_SiM6_1m_2026-03-01_2026-04-10_balanced.zip
archives/old/research_SiM6_1m_2026-03-01_2026-04-10_balanced_20260430_200130.zip
```

The manifest lists run parameters (ticker, period, tick size, etc.) and all files included. It never contains `.env` files or API tokens.

To find the freshest archive for any run:

```bash
ls -lt archives/latest/
ls -lt archives/old/ | head
```

### All options

```
./scripts/run_full_research_pipeline.sh --help
```

---

## Instrument specs-aware backtest

Using a universal `point_value_rub=10` gives wrong RUB P&L for instruments other than SiM6.
The correct formula is:

```
point_value_rub = min_price_increment_amount / min_price_increment
```

For example: SiM6 has `min_price_increment=1`, `min_price_increment_amount=10` → `point_value_rub=10`.
BRM6 has completely different values, so any cross-instrument comparison with `point_value_rub=10` is meaningless.

### Fetch and cache specs from T-Bank

```bash
python scripts/fetch_future_specs.py \
  --ticker SiM6 \
  --class-code SPBFUT \
  --env prod
```

This calls the T-Bank API, computes `point_value_rub`, and saves the result to `data/instruments/futures_specs.csv`.
Subsequent pipeline runs read from the local cache — no repeated API calls.

### Use in the pipeline

By default, the pipeline resolves `point_value_rub` automatically:

```bash
./scripts/run_full_research_pipeline.sh \
  --ticker SiM6 \
  --from 2026-03-01 \
  --to 2026-04-10
# --point-value-rub auto (default)
# --auto-specs true (default)
```

Resolution order:
1. Read from local cache (`data/instruments/futures_specs.csv`)
2. If not cached and `--auto-specs true`: call `fetch_future_specs.py`
3. If still unavailable: fall back to `--fallback-point-value-rub 10` with a WARNING

Override manually:

```bash
./scripts/run_full_research_pipeline.sh \
  --ticker BRM6 \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --point-value-rub 66.67
```

---

## Interactive research wizard

Instead of typing a long command with many flags, run the wizard:

```bash
python scripts/run_research_wizard.py
```

The wizard prompts for each parameter with a default shown in brackets. Press Enter to accept the default.
After collecting all parameters it shows the full command and asks for confirmation before running.

### Dry-run (show command, don't run)

```bash
python scripts/run_research_wizard.py --dry-run
```

### Use defaults, skip all prompts

```bash
python scripts/run_research_wizard.py --yes
```

### Combine both (CI-friendly preview)

```bash
python scripts/run_research_wizard.py --yes --dry-run
```

---

## Liquid futures universe scan

Find the most liquid SPBFUT futures over a given period, without downloading full history for all instruments:

```bash
python scripts/scan_liquid_futures.py \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --top 20 \
  --env prod \
  --output data/instruments/liquid_futures_2026-03-01_2026-04-10.csv \
  --report-output reports/liquid_futures_2026-03-01_2026-04-10.md
```

The scan downloads a short sample window (`--sample-days 5`) of 1-minute candles per instrument and computes:

```
activity_score = non_zero_volume_candles × median_volume_per_candle
```

The output CSV can be fed into a batch research runner:

```bash
python scripts/run_universe_research.py \
  --universe data/instruments/liquid_futures_2026-03-01_2026-04-10.csv \
  --top 5 \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --profile balanced \
  --env prod
```

This shows the list of tickers and asks for confirmation before running the full pipeline for each one.

Use `--skip-load` when raw candle CSV files already exist and you do not want to call T-Bank API again.
This is useful when network or TLS restrictions prevent connecting to T-Bank API:

```bash
python scripts/run_universe_research.py \
  --universe data/instruments/liquid_futures_2026-03-01_2026-04-10.csv \
  --top 5 \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --profile balanced \
  --env prod \
  --skip-load \
  --skip-walkforward-grid
```

---

## Direction filter: BUY-only / SELL-only

All backtest scripts and the full pipeline support `--direction-filter`:

```bash
# All signals (default)
./scripts/run_full_research_pipeline.sh \
  --ticker SiM6 \
  --from 2026-03-01 \
  --to 2026-04-10

# SELL signals only
./scripts/run_full_research_pipeline.sh \
  --ticker SiM6 \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --direction-filter SELL

# BUY signals only
./scripts/run_full_research_pipeline.sh \
  --ticker SiM6 \
  --from 2026-03-01 \
  --to 2026-04-10 \
  --direction-filter BUY
```

Valid values: `all` (default), `BUY`, `SELL`. Any other value raises a `ValueError`.

The filter applies in the backtest engine before trade entry — signals with the non-matching direction are skipped entirely. All reports include a "Direction filter" line so results are unambiguous.

The wizard also exposes this parameter:

```bash
python scripts/run_research_wizard.py
# Direction filter [all]:
```

---

## Slippage in ticks

By default, slippage is specified in price points (`--slippage-points`). This makes cross-instrument comparison difficult:

```text
CRM6 tick_size = 0.001   →  slippage_points=1  equals 1000 ticks
BRK6 tick_size = 0.01    →  slippage_points=1  equals 100 ticks
SiM6 tick_size = 1.0     →  slippage_points=1  equals 1 tick
```

Use `--slippage-ticks` for comparable analysis across instruments:

```bash
# Single backtest with 1-tick slippage
python scripts/run_backtest.py \
  --input out/debug_simple_all_BRK6_1m_2026-03-01_2026-04-10_balanced.csv \
  --slippage-ticks 1 \
  --tick-size 0.01 \
  --point-value-rub 746.947

# Grid backtest with tick-based slippage grid
python scripts/run_backtest_grid.py \
  --input out/debug_simple_all_BRK6_1m_2026-03-01_2026-04-10_balanced.csv \
  --slippage-ticks-values 0,1,2,5 \
  --tick-size 0.01 \
  --point-value-rub 746.947
```

The full pipeline uses tick-based grid by default (`--grid-slippage-ticks-values 0,1,2,5`). To override:

```bash
./scripts/run_full_research_pipeline.sh \
  --ticker BRK6 --from 2026-03-01 --to 2026-04-10 \
  --grid-slippage-ticks-values 0,1,2,5
```

Trades CSV includes: `slippage_points`, `slippage_ticks`, `effective_slippage_points`, `tick_size`.
Grid results include: `slippage_ticks`, `effective_slippage_points`, `tick_size`.

---

## Cross-run comparison

Compare research results across multiple instruments after running the pipeline for each:

```bash
# Compare all latest archives at once
python scripts/compare_research_runs.py \
  --latest \
  --output out/cross_run_comparison_latest.csv \
  --report-output reports/cross_run_comparison_latest.md

# Or compare specific archives
python scripts/compare_research_runs.py \
  --archives archives/latest/Actual_CRM6_*.zip archives/latest/Actual_BRK6_*.zip \
  --output out/cross_run_comparison.csv \
  --report-output reports/cross_run_comparison.md
```

The comparison report includes:

- **Runs overview** — ticker, period, direction, signals, net PnL, winrate, profit factor
- **Ranking by Net PnL / Profit Factor**
- **Signal density** — signals per 1000 bars, top fail reason
- **Slippage ticks robustness** — worst/median PnL at 0, 1, 2, 5 ticks slippage (if grid results present)

Data is extracted from `archives/latest/Actual_*.zip` — no T-Bank API call needed.

---

## Deployment

The project is deployed to `/opt/hammertrade` on a Yandex Cloud VM.

- Copy `.env.example` to `.env` on the server and fill in `READONLY_TOKEN` — never commit `.env`
- The server uses a read-only token for paper/research only
- Real orders and sandbox orders are not implemented
- See `docs/deploy_yandex_server.md` for full setup instructions

**Known TLS issue**: T-Bank API returns a self-signed certificate on the server's network.
Do not bypass this with `curl -k`, `verify=False`, or by installing the Russian Trusted Root CA.

### T-Bank TLS on some Russian networks

Some Russian networks/clouds serve the T-Bank API certificate chain via Russian Trusted Root CA.

HammerTrade does not install this CA globally and does not disable TLS verification.

If needed, create an isolated CA bundle and point only the HammerTrade process to it:

```bash
bash scripts/build_tbank_ca_bundle.sh \
  --russian-root-ca /opt/hammertrade/certs/russian-trusted-root-ca.crt \
  --output /opt/hammertrade/certs/tbank-combined-ca.pem
```

Then in `.env`:

```
GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/opt/hammertrade/certs/tbank-combined-ca.pem
```

See `docs/deploy_yandex_server.md` for full instructions.
The `deploy/systemd/hammertrade-paper.example.service` is a template for a future paper trading daemon (not yet implemented).

---

## Paper trading

Paper trading mode executes the HammerDetector strategy on live market data and tracks
virtual trades — no real or sandbox orders are placed. Uses `READONLY_TOKEN` only.

- State is stored in SQLite: `data/paper/paper_state.sqlite`
- One virtual trade at a time per ticker/timeframe/profile/direction
- Resistant to restarts (idempotent per candle timestamp)

**Dry-run (no DB writes):**

```bash
python scripts/run_paper_trader.py --once --dry-run
```

**One real paper-cycle:**

```bash
python scripts/run_paper_trader.py --once
```

**Continuous (for systemd):**

```bash
python scripts/run_paper_trader.py --ticker SiM6 --direction-filter SELL
```

**Generate report:**

```bash
python scripts/paper_report.py --state-db data/paper/paper_state.sqlite --output reports/paper_report_SiM6_SELL.md
```

Logs: `logs/paper_SiM6_SELL.log`  
Systemd template: `deploy/systemd/hammertrade-paper.example.service`  
See `docs/deploy_yandex_server.md` for server setup.
