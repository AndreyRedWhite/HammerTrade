# Momentum Continuation Paper Engine — Spec

## Purpose

Paper-trade the Momentum Continuation strategy on MOEX Si futures using a virtual
state machine. No real or sandbox orders are placed; the engine records all
signals, entries, and exits to SQLite and exports a CSV after each cycle.

## Candidate Source

- Backtest research: `src/strategies/momentum_continuation/strategy.py`
- Best backtest scenario: `MC_atr2.0_vol2.0_r2.0` (A/B concluded 2026-05-30,
  PF 1.163 vs baseline 0.992)
- Target instrument: SiU6 (after rollover from SiM6, deadline 2026-06-10)

## Exact Signal Parameters

| Parameter | Value | Source |
|---|---|---|
| Direction | SHORT only | strategy.py |
| ATR window | 14 bars | strategy.py |
| ATR multiplier (`atr_mult`) | 2.0 | strategy.py |
| Volume window | 20 bars | strategy.py |
| Volume multiplier (`vol_mult`) | 2.0 | strategy.py |
| Close near low (`close_near_low_pct`) | ≤ 0.25 | strategy.py |
| Take R multiple (`take_r`) | 2.0 | strategy.py |
| Time exit (MSK) | 18:40 | strategy.py |
| Max trades/day | 1 | strategy.py |

## State Machine

```
WAITING_FOR_SIGNAL
    → (signal conditions met) → IN_TRADE
    → (time >= 18:40 MSK, no open trade) → DONE_FOR_DAY

IN_TRADE
    → (stop hit: high >= stop_price) → DONE_FOR_DAY
    → (take hit: low <= take_price) → DONE_FOR_DAY
    → (time >= 18:40 MSK) → DONE_FOR_DAY

DONE_FOR_DAY
    → (next calendar day in MSK) → WAITING_FOR_SIGNAL (reset)

MARKET_CLOSED
    → (market opens) → WAITING_FOR_SIGNAL
```

## Signal Logic (SHORT)

Given the last closed 1-minute candle and recent N candles:

1. Compute ATR-14 from `recent_candles` using `compute_atr()` (from `src.research.vwap`)
2. Compute `vol_mean` = rolling mean of `volume` over last 20 candles
3. Check all three conditions:
   - `candle_range = candle.high - candle.low >= 2.0 * atr_val`
   - `close_pos = (candle.close - candle.low) / candle_range <= 0.25`
   - `candle.volume >= 2.0 * vol_mean`
   - Guard: `atr_val > 0` and `candle_range > 0`
4. If all pass → signal confirmed

## Entry / Stop / Take / Exit

- **Entry**: `entry_price = candle.close` (SHORT on signal candle's close)
- **Stop**: `stop_price = candle.high` (impulse high)
- **Risk**: `risk = stop_price - entry_price` (must be > 0)
- **Take**: `take_price = entry_price - risk * 2.0`
- **Stop priority**: if same candle touches both `high >= stop` and `low <= take` → STOP wins (exit at stop_price)
- **Time exit**: candle MSK time >= 18:40 → exit at candle `open`, reason = TIME_EXIT
- **PnL (SHORT)**: `pnl_points = entry_price - exit_price`; `pnl_rub = pnl_points * 10.0 - 0.05`
- **Trade ID**: `f"momentum:{ticker}:{experiment_name}:{candle_ts_utc.isoformat()}"`

## Storage

### SQLite tables

**`momentum_daily_state`** — one row per MSK date:
- `date_msk` (PK), `state`, `trades_today`, `done_for_day`, `last_processed_candle_ts`, `created_at`, `updated_at`

**`momentum_paper_trades`** — one row per paper trade:
- `trade_id` (PK), `strategy_name`, `experiment_name`, `ticker`, `direction`
- `signal_timestamp`, `entry_timestamp`, `entry_price`, `stop_price`, `take_price`
- `atr_value`, `volume_value`, `volume_avg`, `candle_range`, `close_position`
- `status`, `exit_timestamp`, `exit_price`, `exit_reason`
- `pnl_points`, `pnl_rub`, `bars_held`, `created_at`, `updated_at`

Default paths:
- DB: `data/paper/paper_state_siu6_momentum.sqlite`
- CSV: `out/paper/paper_trades_SiU6_MOMENTUM.csv`

## Status Fields

Written to `runtime/paper_status_SiU6_MOMENTUM.json` after every cycle:

| Field | Description |
|---|---|
| `service` | `"hammertrade-paper-momentum"` |
| `mode` | `"paper"` |
| `strategy` | `"momentum_continuation"` |
| `experiment_name` | from config |
| `ticker` | from config |
| `direction` | `"SHORT"` |
| `signal_params` | dict with all signal parameters |
| `market_open` | bool |
| `session` | session name from market hours config |
| `fetch_status` | OK / API_ERROR / MARKET_CLOSED / NO_CANDLES |
| `last_cycle_at_utc` | ISO timestamp |
| `trading_liveness_status` | OK / DEGRADED / STALLED |
| `trading_liveness_reason` | reason string or null |
| `daily_state` | current day state dict |
| `open_trade` | open trade dict or null |
| `closed_trades_total` | int |
| `net_pnl_total_rub` | float |
| `pid` | daemon PID |

## How to Run (Dry-Run, One Cycle)

```bash
cd /opt/hammertrade
source .env
.venv/bin/python scripts/run_momentum_paper_trader.py \
    --config configs/paper/momentum_continuation_siu6_paper_example.yaml \
    --dry-run --once
```

Expected output on dry-run: API error (SiU6 not available pre-rollover) or
signal detection log lines. Confirms "NO REAL ORDERS" banner and safety guard.

## How to Launch After Rollover (2026-06-10)

1. Verify SiU6 candle data is available via T-Bank API (smoke test)
2. Copy service file: `sudo cp deploy/systemd/hammertrade-paper-momentum.example.service /etc/systemd/system/hammertrade-paper-momentum.service`
3. `sudo systemctl daemon-reload`
4. `sudo systemctl enable --now hammertrade-paper-momentum`
5. Monitor: `journalctl -fu hammertrade-paper-momentum`
6. Check status: `python scripts/check_all_paper_status.py`

## Safety Constraints

- `orders_enabled` must remain `false` in config; daemon exits with code 1 if `true`
- Uses `READONLY_TOKEN` only — no account/order API calls
- Banner printed at startup: `MOMENTUM PAPER TRADER — PAPER MODE ONLY — NO REAL ORDERS`
- Do NOT deploy before rollover (SiM6 → SiU6)
- Do NOT start/enable service until confirmed

## Known Risks

1. **Low sample size**: ~20–30 signals/month; need 60+ closed trades for statistical significance
2. **Rollover timing**: SiU6 becomes primary on 2026-06-10; earlier data may have wider spreads
3. **ATR cold-start**: first candles of the day have low ATR history; engine requires `recent_candles` ≥ 2 rows and uses `min_periods=1` rolling
4. **Stop placement risk**: stop = impulse candle high; can be wide on very large candles
5. **Config drift**: all parameters loaded from YAML; changing `orders_enabled: true` causes immediate exit

## Stop Conditions

Stop the service if:
- `trading_liveness_status` = STALLED for > 15 minutes during market hours
- More than 5 consecutive losses in a week (investigate before resuming)
- SiU6 instrument is replaced (next rollover to SiZ6 around September 2026)

## Files

| Path | Description |
|---|---|
| `src/paper/momentum/models.py` | Data models (MomentumDayState, MomentumPaperTrade, ...) |
| `src/paper/momentum/engine.py` | Core state machine (process_candle_momentum) |
| `src/paper/momentum/repository.py` | SQLite repository (MomentumRepository) |
| `src/paper/momentum/status.py` | Status JSON builder |
| `scripts/run_momentum_paper_trader.py` | Daemon entry point |
| `scripts/momentum_paper_diagnostics.py` | Diagnostics report generator |
| `configs/paper/momentum_continuation_siu6_paper_example.yaml` | Example config |
| `deploy/systemd/hammertrade-paper-momentum.example.service` | Example systemd unit |
