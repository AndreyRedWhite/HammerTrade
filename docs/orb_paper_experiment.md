# ORB Paper Experiment (MVP-R1b)

## Purpose

Run an Opening Range Breakout (ORB) strategy in paper mode in parallel with the
hammer paper trader. No real or sandbox orders are placed. The purpose is to
collect live signal statistics on MOEX futures (SiM6/SiU6) without capital risk.

## Profile

| Parameter | Value |
|---|---|
| Strategy | ORB (Opening Range Breakout) |
| Ticker | SiM6 (rolls to SiU6 by 2026-06-10) |
| Class code | SPBFUT |
| Timeframe | 1m |
| Direction | SHORT |
| OR window | 10:00–11:00 MSK |
| OR min candles | 5 |
| OR min range | 10 pts |
| Take-profit ratio | 2R |
| Time exit | 18:40 MSK |
| Point value | 10 RUB/pt |
| Commission | 0.05 RUB/trade round-trip |
| Orders enabled | **always False** |

## State Machine

Each day proceeds through these states:

1. **WAITING_FOR_OR_START** — before 10:00 MSK, no action
2. **BUILDING_OPENING_RANGE** — 10:00–11:00 MSK, accumulate OR high/low
3. **WAITING_FOR_BREAKOUT** — after 11:00 MSK, wait for price to break OR
4. **IN_TRADE** — open position is being tracked
5. **DONE_FOR_DAY** — trade closed or time exit or invalid OR
6. **MARKET_CLOSED** — outside trading hours

Day context resets on each new calendar date (MSK).

## Entry / Stop / Take

**SHORT breakout:**
- Entry trigger: candle low < OR low (1-minute candle breaks below OR low)
- Entry price: OR low (breakout level)
- Stop: OR high
- Risk (R): OR high − OR low
- Take: entry − 2R
- One trade per day maximum

**OR validity checks:**
- Must have ≥ 5 candles in OR window
- OR range must be ≥ 10 points (to filter flat days)

**Time exit:**
- If position still open at 18:40 MSK, exit at candle close
- No new entries after 18:40 MSK

**Stop vs Take priority:**
- If both stop and take are hit in the same candle, STOP wins

## Storage

| File | Purpose |
|---|---|
| `data/paper/paper_state_orb.sqlite` | SQLite DB: `orb_daily_state` + `orb_paper_trades` |
| `out/paper/paper_trades_SiM6_ORB.csv` | CSV export of all trades |
| `runtime/paper_status_SiM6_ORB.json` | Live status JSON |
| `logs/paper_SiM6_ORB.log` | Daemon log |

## Status JSON Fields

The status file `runtime/paper_status_SiM6_ORB.json` contains:

| Field | Description |
|---|---|
| `service` | `"hammertrade-paper-orb"` |
| `strategy` | `"ORB"` |
| `experiment_name` | e.g. `"orb_or60_short2r"` |
| `ticker` / `direction` | Current instrument and direction |
| `opening_range.start/end` | OR window times |
| `take_r` | Take-profit ratio |
| `market_open` | Is market currently open |
| `session` | Current session name |
| `fetch_status` | Last fetch result: `OK`, `API_TIMEOUT`, `NO_CANDLES`, etc. |
| `last_cycle_at_utc` | UTC timestamp of last cycle |
| `last_successful_fetch_at` | UTC timestamp of last successful fetch |
| `consecutive_api_errors` | Rolling error count |
| `trading_liveness_status` | `OK`, `DEGRADED`, or `STALLED` |
| `trading_liveness_reason` | Why liveness is not OK |
| `daily_state` | Current day's ORB context (state, or_high, or_low, etc.) |
| `open_trade` | Current open trade or null |
| `closed_trades_total` | Total closed trades since start |
| `net_pnl_total_rub` | Total net PnL since start |
| `pid` | Daemon process ID |

## How to Start

### Copy and install the service

```bash
sudo cp deploy/systemd/hammertrade-paper-orb.example.service \
    /etc/systemd/system/hammertrade-paper-orb.service
sudo systemctl daemon-reload
sudo systemctl enable hammertrade-paper-orb
sudo systemctl start hammertrade-paper-orb
```

### Check status

```bash
# Service status
sudo systemctl status hammertrade-paper-orb --no-pager

# Live status JSON
python scripts/check_all_paper_status.py

# Compare all experiments
python scripts/compare_all_paper_experiments.py

# Single service status
python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_ORB.json

# Live log
tail -f logs/paper_SiM6_ORB.log
```

### Test locally (one cycle, no market hours guard)

```bash
venv/bin/python scripts/run_orb_paper_trader.py \
    --once \
    --ignore-market-hours \
    --state-db /tmp/test_orb.sqlite \
    --status-file /tmp/test_orb_status.json \
    --csv-output /tmp/test_orb.csv
```

## Diagnostics

```bash
# Generate diagnostics report
venv/bin/python scripts/orb_paper_diagnostics.py \
    --state-db data/paper/paper_state_orb.sqlite \
    --ticker SiM6 \
    --experiment-name orb_or60_short2r \
    --output reports/orb_paper_diagnostics_SiM6_latest.md

# View the report
cat reports/orb_paper_diagnostics_SiM6_latest.md
```

The diagnostics report includes:
- Closed/open trade counts
- Wins, losses, winrate
- Net PnL, gross profit/loss, Profit Factor, Expectancy
- Best/worst trade
- Maximum drawdown
- Exit reason breakdown (STOP / TAKE / TIME_EXIT)
- Daily breakdown
- Average OR range

## Rollover Notes

When SiM6 expires (deadline: 2026-06-10), update the service to use SiU6:

```bash
sudo systemctl stop hammertrade-paper-orb
# Edit /etc/systemd/system/hammertrade-paper-orb.service
# Change: --ticker SiM6 → --ticker SiU6
# Change: --state-db data/paper/paper_state_orb.sqlite →
#         --state-db data/paper/paper_state_orb_SiU6.sqlite
# Change: --status-file runtime/paper_status_SiM6_ORB.json →
#         --status-file runtime/paper_status_SiU6_ORB.json
# Change: --csv-output out/paper/paper_trades_SiM6_ORB.csv →
#         --csv-output out/paper/paper_trades_SiU6_ORB.csv
sudo systemctl daemon-reload
sudo systemctl start hammertrade-paper-orb
sudo systemctl status hammertrade-paper-orb --no-pager
```

## Stop Conditions

Stop the ORB experiment if any of these conditions are met:
- The strategy has ≥ 30 closed trades and Profit Factor < 0.8 (clear underperformance)
- The market rolls over and configuration hasn't been updated within 24 hours
- The daemon is STALLED (trading_liveness_status=STALLED) for more than 2 hours

## Architecture Notes

- `src/paper/orb/` — standalone ORB package, does **not** share state with hammer paper engine
- `src/paper/orb/engine.py` — pure state machine (no I/O), easy to unit test
- `src/paper/orb/repository.py` — SQLite persistence (separate DB from hammer)
- `src/paper/orb/status.py` — JSON status builder, reuses `compute_liveness()` from `src/paper/liveness.py`
- `scripts/run_orb_paper_trader.py` — daemon following same pattern as `run_paper_trader.py`
