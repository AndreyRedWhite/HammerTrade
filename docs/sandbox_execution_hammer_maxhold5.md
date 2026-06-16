# Sandbox Execution — Hammer MaxHold5

## Purpose

Place real T-Bank **sandbox-contour** orders for the `hammer-maxhold5`
strategy (SiU6, SELL, `max_hold_bars=5`) so its execution behaviour
(fills, slippage, commissions, position reconciliation) can be observed
under conditions closer to live trading — without any real money or
real orders. This is MVP-L1a: the architecture and tooling, not yet a
running daemon.

## Why separate from paper

`hammertrade-paper-maxhold5.service` (the existing paper control group)
keeps running completely unchanged: same DB
(`data/paper/paper_state_maxhold5.sqlite`), same status file, same CSV,
same `max_hold_bars=5` logic. It is the control group for the A/B
comparison.

The new sandbox layer:

- reuses the **same signal/entry/exit state machine**
  (`src.paper.engine.process_candle`, via `src/sandbox/engine.py`'s
  `process_sandbox_candle()` wrapper) — unchanged, `max_hold_bars=5`,
  `direction=SELL`,
- but writes to **its own DB/status/log/CSV** under `data/sandbox/`,
  `runtime/sandbox_status_*`, `logs/sandbox_*`, `out/sandbox/`,
- and additionally **places sandbox orders** via T-Bank `SandboxService`
  and reconciles the resulting sandbox account position against the
  bot's expected position.

Paper and sandbox never share a DB, CSV, or log file. Sandbox trades are
never written to the paper DB and vice versa.

## Token handling

Two separate T-Bank tokens are used, for two separate purposes:

| Env var | Contour | Used for |
|---|---|---|
| `READONLY_TOKEN` | prod (read-only) | candle fetching (`env="prod"`) — same as the paper services |
| `SANDBOX_TOKEN` | sandbox | order placement only, via `SandboxBroker` |
| `SANDBOX_ACCOUNT_ID` | sandbox | the sandbox account to trade on |

Candle data is fetched from the **prod contour with `READONLY_TOKEN`**
(`fetch_recent_candles(..., env="prod")`), exactly like the paper
services — sandbox accounts do not have their own market data feed worth
relying on. `SANDBOX_TOKEN` / `SANDBOX_ACCOUNT_ID` are only read in
non-dry-run mode, only to place/check sandbox orders and positions.

Rules enforced throughout this MVP:

- The token value is **never** logged, printed, written to a report, or
  committed. Status JSON only exposes `token_present` /
  `sandbox_account_id_present` booleans (see `src/sandbox/status.py`).
- `.env` is **not** tracked by git (verified: `git ls-files | grep '^\.env'`
  → only `.env.example`).
- `.env.example` already contains placeholder (empty) entries for
  `SANDBOX_TOKEN` and `SANDBOX_ACCOUNT_ID`.
- If `SANDBOX_TOKEN` (or `SANDBOX_ACCOUNT_ID`) is missing in non-dry-run
  mode, `scripts/run_hammer_maxhold5_sandbox.py` hard fails with a
  `CONFIG ERROR` naming the missing variable and pointing at
  `--dry-run` / `scripts/sandbox_account_setup.py` respectively
  (`check_token_and_account()`).
- `--dry-run` mode never reads `SANDBOX_TOKEN` / `SANDBOX_ACCOUNT_ID` and
  never opens a `SandboxRepository` — it only fetches candles and logs
  signals.

## Sandbox account

`scripts/sandbox_account_setup.py` is the only tool that talks to
`SandboxService` for account management:

```bash
.venv/bin/python scripts/sandbox_account_setup.py [--create-if-missing] [--top-up-rub 40000]
```

Behaviour:

1. Hard fails if `SANDBOX_TOKEN` is not set (never connects).
2. Lists existing sandbox accounts (`get_sandbox_accounts`). If one
   exists, uses the first one — never creates a second account silently.
3. With `--create-if-missing` and no existing account, opens one
   (`open_sandbox_account`).
4. With `--top-up-rub <amount>`, calls `sandbox_pay_in` to top up virtual
   RUB.
5. Prints **only** `SANDBOX_ACCOUNT_ID=<id>` — never the token — and
   instructs the operator to add that line to `.env`.

## Config

`configs/sandbox/hammer_maxhold5_siu6.yaml` — drives the runner. Key
fields:

```yaml
mode: sandbox
strategy: hammer_maxhold5
ticker: SiU6
direction: SELL
max_hold_bars: 5          # unchanged from paper control group

orders:
  enabled: true
  environment: sandbox     # must be "sandbox" or runner hard-fails
  real_orders_enabled: false  # hardcoded false; runner hard-fails if true
  account_id_env: SANDBOX_ACCOUNT_ID
  token_env: SANDBOX_TOKEN

risk:
  capital_budget_rub: 40000
  max_position_notional_rub: 40000
  max_order_notional_rub: 40000
  max_daily_loss_rub: 3000
  max_total_loss_rub: 10000
  max_trades_per_day: 5
  max_consecutive_errors: 3
  max_consecutive_losses: 3
  max_open_positions_per_strategy: 1
  kill_switch_file: runtime/STOP_SANDBOX_TRADING
  margin_per_lot_rub: 6000   # proxy "notional" for futures (see Risk limits)

artifacts:
  db: data/sandbox/sandbox_state_hammer_maxhold5_siu6.sqlite
  status: runtime/sandbox_status_hammer_maxhold5_SiU6.json
  trades_csv: out/sandbox/sandbox_trades_hammer_maxhold5_SiU6.csv
  orders_csv: out/sandbox/sandbox_orders_hammer_maxhold5_SiU6.csv
  log: logs/sandbox_hammer_maxhold5_SiU6.log

paper_control_service: hammertrade-paper-maxhold5.service
```

Signal/entry/exit parameters (`params_file`, `entry_mode`,
`entry_horizon_bars`, `take_r`, `stop_buffer_points`, `slippage_ticks`,
`max_hold_bars`, `contracts`) mirror
`hammertrade-paper-maxhold5.service` exactly and must not be changed
without updating the paper control service too (for comparability).

## Runner

`scripts/run_hammer_maxhold5_sandbox.py`:

```bash
.venv/bin/python scripts/run_hammer_maxhold5_sandbox.py \
    --config configs/sandbox/hammer_maxhold5_siu6.yaml \
    [--dry-run] [--once] [--max-cycles N]
```

Each cycle:

1. **Safety gate** (`validate_safety`) — runs first, before any other
   logic, in *every* mode including dry-run. Hard-fails (`CONFIG ERROR`,
   `SystemExit`) if `mode != "sandbox"`, `orders.environment !=
   "sandbox"`, `orders.real_orders_enabled` is truthy, or
   `TINVEST_LIVE_TRADING_TOKEN` is set in the environment.
2. Market-hours check (`src.market.market_hours`) — writes
   `trading_state=MARKET_CLOSED` and returns if the session is closed.
3. Fetch up to `lookback_candles` 1m SiU6 candles via
   `fetch_recent_candles(..., env="prod")` (READONLY_TOKEN), with a
   timeout. On error/timeout → `trading_state=API_ERROR`. On empty data →
   `NO_CANDLES`.
4. Run `HammerDetector` over the candles (same params/profile as paper).
5. **`--dry-run`**: log the signal/last-candle summary, write
   `trading_state=DRY_RUN`, return. No DB, no broker, no token access.
6. Otherwise, for each new closed candle: call
   `process_sandbox_candle()` (= unchanged `process_candle` state
   machine) and dispatch on the result:
   - `ENTRY` → risk check, then `SandboxBroker.post_order(...)`, journal
     the order/fill/trade/position/event.
   - `HOLD` → update the open trade's `bars_held`.
   - `EXIT` → `SandboxBroker.post_order(...)` for the closing side,
     journal order/fill/trade/position/event, update risk + daily-risk
     state.
7. **Reconciliation**: compare the bot's expected position
   (`expected_position_from_trade`) against `SandboxBroker.get_positions`.
8. Export `trades_csv` / `orders_csv`, compute `trading_state`, write the
   status JSON.
9. `--once` or `--dry-run` → exit after one cycle. Otherwise sleep
   `poll_interval_seconds` and repeat (or stop after `--max-cycles`).

Instrument resolution (`uid`/`figi`/`lot` for SiU6) is lazy: the runner
first checks the local catalog `data/instruments/moex_futures.csv`
(populated as a side effect of prod candle fetches), and only falls back
to a direct prod lookup (`src.tbank.instruments.resolve_instrument`) if
SiU6 isn't cached yet. This avoids any extra connection at startup.

## Risk manager

`src/sandbox/risk.py` — `RiskManager` / `RiskLimits`. Pure logic, no I/O
besides checking for the kill-switch file.

`check_pre_trade()` rejects (in order) if:

1. kill switch file exists,
2. `reconciliation_status != OK`,
3. `trading_paused` is already true,
4. `consecutive_errors >= max_consecutive_errors` (3),
5. `consecutive_losses >= max_consecutive_losses` (3),
6. `trades_today >= max_trades_per_day` (5),
7. `realized_pnl_rub <= -max_daily_loss_rub` (-3000),
8. `total_pnl_rub <= -max_total_loss_rub` (-10000),
9. `open_positions >= max_open_positions_per_strategy` (1),
10. `order_notional_rub > max_order_notional_rub` (40000),
11. `position_notional_rub > max_position_notional_rub` (40000).

`update_after_trade()` updates `total_pnl_rub`, `realized_pnl_rub`,
`trades_today`, `consecutive_losses`, and sets `trading_paused=true` with
a reason (`max_daily_loss_exceeded` / `max_total_loss_exceeded` /
`max_consecutive_losses_exceeded`) if a limit is breached.
`update_after_error()` / `reset_errors()` track `consecutive_errors`.
`mark_reconciliation_failed()` / `mark_reconciliation_ok()` flip
`reconciliation_status`.

**Notional proxy for futures**: SiU6 is a margined futures contract, so
`price * point_value_rub` (~730,000 RUB) is not a meaningful "notional"
and would always exceed `max_position/order_notional_rub=40,000`.
Instead, `margin_per_lot_rub: 6000` (config) is used as the notional
proxy: `order_notional_rub = position_notional_rub = margin_per_lot_rub *
qty`. **Verify this against the actual sandbox margin requirement on the
first sandbox order and adjust if needed.**

## Reconciliation

`src/sandbox/reconciliation.py`:

- `position_from_signed_qty(signed_qty)` → `PositionView(direction,
  qty)` where `direction` is `FLAT`/`LONG`/`SHORT`.
- `expected_position_from_trade(open_trade)` (in `src/sandbox/engine.py`)
  → the bot's expected position from its own open `SandboxTrade`
  (`SHORT` for `direction=SELL`, `FLAT` if no open trade).
- `reconcile_position(expected, actual)` → `RiskCheckResult`:
  - both `FLAT` → OK
  - expected `FLAT`, actual non-`FLAT` → FAIL
    (`expected_flat_actual_position`)
  - expected non-`FLAT`, actual `FLAT` → FAIL
    (`expected_position_actual_flat`)
  - direction mismatch → FAIL (`direction_mismatch`)
  - same direction, qty mismatch → FAIL (`qty_mismatch`)
  - same direction and qty → OK

Run every cycle (when an instrument is resolved): the runner calls
`SandboxBroker.get_positions(account_id)`, sums signed lot balances for
SiU6's `figi`, and reconciles against the bot's expected position. On
**any** mismatch: `risk_manager.mark_reconciliation_failed()` (sets
`reconciliation_status=RECONCILIATION_FAILED` and
`trading_paused=True`), an `ERROR`-level log line, and a
`RECONCILIATION_FAILED` event in `sandbox_events`. This blocks all new
entries via `check_pre_trade()` (check #2 above) until manually resolved
— per spec, MVP-L1a's reconciliation-failure behaviour is conservative:
**stop and require manual intervention**, no automatic recovery beyond
the next reconciliation matching again
(`mark_reconciliation_ok()` + an info log line
`RECONCILIATION_RECOVERED`).

If `SandboxBroker.get_positions` itself errors (API failure), that counts
as a `consecutive_errors` increment, not a reconciliation failure.

## Kill switch

`risk.kill_switch_file` (default `runtime/STOP_SANDBOX_TRADING`) is
checked at the start of every `check_pre_trade()` call
(`RiskManager.kill_switch_active()` = `os.path.exists(...)`). If the file
exists, no new entry orders are placed and `trading_state` becomes
`KILL_SWITCH_ACTIVE` (highest-priority state in
`_compute_trading_state`). Existing open positions are **not**
auto-closed by the kill switch — exits (`HOLD`/`EXIT` from
`process_sandbox_candle`) are independent of `check_pre_trade` and
continue to be managed normally.

To activate: `touch runtime/STOP_SANDBOX_TRADING` (note: `runtime/` is
gitignored, so this is a local/server-only file). To resume: remove the
file.

## Order/fill journal

`src/sandbox/repository.py` — `SandboxRepository`, completely separate
SQLite DB (`data/sandbox/sandbox_state_hammer_maxhold5_siu6.sqlite`,
gitignored via `*.sqlite`). Tables:

- `sandbox_orders` — one row per submitted order (order_id, signal_id,
  strategy, ticker, figi, instrument_uid, direction, order_side,
  order_type, requested_qty/price, submitted_at, status, filled_qty,
  avg_fill_price, commission_rub, slippage_points/rub,
  raw_response_json, created_at, updated_at).
- `sandbox_fills` — one row per fill (fill_id, order_id, ticker,
  direction, qty, price, commission_rub, fill_time,
  raw_response_json).
- `sandbox_positions` — one row per ticker, current FLAT/LONG/SHORT
  position (figi, instrument_uid, direction, qty, avg_price,
  updated_at).
- `sandbox_trades` — one row per round-trip trade (trade_id, signal_id,
  entry/exit_order_id, ticker, direction, qty, entry/exit time/price,
  stop/take price, status, exit_reason, gross/net/commission pnl,
  bars_held).
- `sandbox_events` — append-only event log (event_id, timestamp, ticker,
  event_type, message, payload_json) — `ENTRY`, `EXIT`, `ERROR`,
  `RISK_BLOCK`, `RECONCILIATION_FAILED`, etc.
- `sandbox_daily_risk` — one row per MSK date (trades_today,
  realized_pnl_rub, consecutive_losses, daily_loss_breached).
- `sandbox_state` — generic key/value store: cumulative `risk_state`
  JSON, `last_processed:<ticker>` candle timestamp,
  `pending_signal:<ticker>` JSON.

`export_orders_csv()` / `export_trades_csv()` write
`out/sandbox/sandbox_orders_hammer_maxhold5_SiU6.csv` /
`out/sandbox/sandbox_trades_hammer_maxhold5_SiU6.csv` after every cycle
(both gitignored via `out/`).

## Status

`runtime/sandbox_status_hammer_maxhold5_SiU6.json` (gitignored via
`runtime/`), written atomically (`*.tmp` → `Path.replace()`) every cycle
by `src/sandbox/status.py`. Key fields: `mode="sandbox"`,
`real_orders_enabled=false`, `paper_control_service`, `trading_state`
(`WAITING_FOR_SIGNAL` / `PENDING_ENTRY` / `IN_POSITION` /
`TRADING_PAUSED` / `RECONCILIATION_FAILED` / `KILL_SWITCH_ACTIVE` /
`MARKET_CLOSED` / `API_ERROR` / `NO_CANDLES` / `DRY_RUN`),
`kill_switch_active`, `token_present` / `sandbox_account_id_present`
(booleans only — **never** the values), `reconciliation_status`,
`open_positions_expected/actual`, `open_orders`, `daily_pnl_rub` /
`total_pnl_rub` and their limits, `trades_today` / `max_trades_per_day`,
`market_open` (+ `liveness`/`liveness_reason` from
`src.paper.liveness.compute_liveness`), and `last_*_at` /
`last_error_message` timestamps.

## Diagnostics

```bash
.venv/bin/python scripts/sandbox_diagnostics.py \
    --state-db data/sandbox/sandbox_state_hammer_maxhold5_siu6.sqlite \
    --ticker SiU6 \
    --output reports/sandbox_diagnostics_hammer_maxhold5_latest.md \
    --out-csv out/sandbox/sandbox_diagnostics_hammer_maxhold5_latest.csv
```

Produces a markdown report (Summary: closed/open trades, win/loss, gross
profit/loss, net PnL, profit factor, expectancy, best/worst trade, max
drawdown; Order Status Breakdown; Exit Reason Breakdown; Daily Breakdown;
Risk State; Today's Risk; Current Position; Recent Events; `LOW_SAMPLE`
warning if fewer than 20 closed trades) plus a per-trade CSV
(`export_trades_csv`). **Never crashes**: if the DB doesn't exist yet, it
writes a minimal "_No data yet_" report and a header-only CSV; if the DB
exists but has zero trades, every section degrades gracefully (e.g.
`_no orders yet_`, `_No position recorded yet (FLAT)._`,
`_No events recorded yet._`).

## How to run dry-run

```bash
cd /opt/hammertrade
source .env   # or rely on EnvironmentFile in the systemd unit
.venv/bin/python scripts/run_hammer_maxhold5_sandbox.py \
    --config configs/sandbox/hammer_maxhold5_siu6.yaml \
    --dry-run --once
```

Dry-run only fetches candles (READONLY_TOKEN, prod contour) and runs the
detector/state machine for logging — it never touches `SANDBOX_TOKEN`,
`SANDBOX_ACCOUNT_ID`, the sandbox DB, or `SandboxBroker`. It always
finishes with `trading_state=DRY_RUN` in the status file (unless market
is closed / candle fetch fails, in which case `MARKET_CLOSED` /
`API_ERROR` / `NO_CANDLES`).

## How to setup sandbox account

```bash
cd /opt/hammertrade
source .env
.venv/bin/python scripts/sandbox_account_setup.py --create-if-missing --top-up-rub 40000
```

Then copy the printed `SANDBOX_ACCOUNT_ID=...` line into `/opt/hammertrade/.env`
(never commit `.env`). Re-running without `--create-if-missing` is safe
— it reuses the first existing account and never creates a second one.

## What is still not live

- `orders.real_orders_enabled` is hardcoded `false` in
  `configs/sandbox/hammer_maxhold5_siu6.yaml`; the runner hard-fails
  (`validate_safety`) if it is ever set `true`.
- `orders.environment` must be `"sandbox"`; any other value (`"live"`,
  `"prod"`, missing) hard-fails before any API call.
- If `TINVEST_LIVE_TRADING_TOKEN` is present in the environment at all,
  the runner hard-fails immediately, regardless of config.
- All order placement goes through `SandboxBroker` →
  `client.sandbox.post_sandbox_order(...)` (T-Bank **sandbox contour**,
  `sandbox-invest-public-api.tbank.ru`) — structurally incapable of
  touching the prod/live order-placement endpoints.
- The sandbox daemon has **not** been started (no `systemctl
  enable/start`); the systemd unit is an `.example.service` only.
- No sandbox order has been placed yet (local dry-run smoke test only;
  SDK not installed locally, so even candle fetch fails locally with
  `API_ERROR` — this must be exercised on the server).

## Path to micro-live

1. Run the sandbox daemon for a sample large enough to be meaningful
   (the diagnostics report's `LOW_SAMPLE` threshold is 20 closed trades),
   watching `trading_state`, `reconciliation_status`, and PnL via
   `scripts/sandbox_diagnostics.py`.
2. Compare sandbox fills/slippage/commissions against the paper control
   group (`hammertrade-paper-maxhold5.service`) for the same period.
3. If reconciliation stays `OK` and risk limits are never breached
   unexpectedly, raise `risk.margin_per_lot_rub` toward the real SiU6
   margin requirement (verify against the sandbox account's actual
   margin usage) and re-validate the notional checks.
4. Only after a separate, explicit MVP: introduce a `live` environment
   wrapping `client` against the prod contour with real order placement,
   a *new* live token (`TINVEST_LIVE_TRADING_TOKEN` or similar, distinct
   from `READONLY_TOKEN`), and much smaller initial size (e.g. 1 lot,
   tight daily loss caps). The current `validate_safety()` gate must be
   relaxed deliberately and explicitly for that MVP — it is not a
   side-effect of any sandbox-layer change.

## Safety checklist

- [x] `mode: sandbox`, `orders.environment: sandbox`,
      `orders.real_orders_enabled: false` in
      `configs/sandbox/hammer_maxhold5_siu6.yaml`.
- [x] `validate_safety()` hard-fails on non-sandbox mode/environment,
      `real_orders_enabled=true`, or `TINVEST_LIVE_TRADING_TOKEN` set —
      covered by `tests/test_hammer_maxhold5_sandbox_cli.py`.
- [x] Missing `SANDBOX_TOKEN` / `SANDBOX_ACCOUNT_ID` hard-fails with a
      clear `CONFIG ERROR` in non-dry-run mode.
- [x] `--dry-run` never reads `SANDBOX_TOKEN`/`SANDBOX_ACCOUNT_ID`, never
      opens the sandbox DB, never calls `SandboxBroker`.
- [x] Token value never logged/printed/written to status or reports
      (`token_present`/`sandbox_account_id_present` booleans only).
- [x] `.env` not tracked by git; `.env.example` has placeholder
      `SANDBOX_TOKEN=` / `SANDBOX_ACCOUNT_ID=`.
- [x] Sandbox DB/status/log/CSV are entirely separate paths from the
      paper services; no shared files.
- [x] `hammertrade-paper-maxhold5.service` (and other paper services)
      not modified, not stopped.
- [x] Hammer detector params and `max_hold_bars=5` unchanged.
- [x] Momentum not launched; ORB risk caps not touched.
- [x] Risk manager (`RiskManager`/`RiskLimits`), kill switch, and
      position reconciliation implemented and unit-tested.
- [x] `deploy/systemd/hammertrade-sandbox-maxhold5.example.service`
      created, **not installed/enabled**.
- [ ] Sandbox daemon started on the server — **requires explicit
      approval**.
- [ ] First sandbox order placed — **requires explicit approval**.
