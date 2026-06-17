# Sandbox Recovery — stuck-position close, exit-retry guard, scheduled recovery

Tooling to safely flatten a stuck `hammer-maxhold5` sandbox position, guard
against infinite exit retries, and (optionally) automate recovery shortly after
the MOEX open. Everything here is **sandbox contour only** (`SANDBOX_TOKEN`,
virtual money) — there is no live/prod order path, and the paper services are
never touched.

## Background — why this exists

On 2026-06-15/16 the sandbox `hammer-maxhold5` service hit two execution
blockers after the `order_id`/UUID idempotency fix (see
`sandbox_execution_hammer_maxhold5.md`):

1. **Insufficient buying power on entry.** The T-Bank **sandbox** contour
   rejects a futures order unless the account has roughly the **full contract
   notional** free (~74k RUB for one SiU6 lot), not just the initial margin
   (~11.5k RUB). 40k was rejected with `30034 Not enough balance`; 200k let the
   entry fill.
2. **Insufficient buying power on exit → stuck short.** A sandbox short
   *reduces* `total_amount_portfolio` by the full notional, so the available
   buying power for the *next* order ≈ `portfolio − committed_notional`. After
   a 1-lot short on a 200k account that is ~50k, which is below the ~74k needed
   to place even the **closing** order. The close therefore also failed
   `30034`, and because exits run independently of the pre-trade risk checks,
   the daemon retried the close every cycle — 434 failed orders in ~7 hours.

**Rule of thumb:** keep the sandbox account funded to **≥ ~2× the contract
notional** so a closing order always has enough buying power *after* a position
is open. Empirically, 200k failed and **500k worked** for one SiU6 lot.

## Exit-retry guard (`src/sandbox/risk.py`, runner)

Exits bypass `check_pre_trade`, so an unfillable close would loop forever.
Guard added:

- `RiskLimits.max_exit_retries` (config `risk.max_exit_retries`, default `3`).
- `SandboxRiskState.exit_error_count` (persisted).
- `RiskManager.record_exit_error()` / `reset_exit_errors()` /
  `exit_retries_exhausted()`.
- In `_handle_exit` the runner blocks once the cap is hit, sets
  `trading_paused` with reason `max_exit_retries_exceeded`, logs a `RISK_BLOCK`
  event, and leaves the position OPEN for manual intervention. The counter is
  reset on any successful exit or fresh entry.

## Manual close — `scripts/sandbox_close_position.py`

Single-shot, dry-run by default. Closes exactly the **live account** net
position (opposite side, abs qty), never increases exposure.

```bash
# dry-run (no order)
.venv/bin/python scripts/sandbox_close_position.py --ticker SiU6
# MARKET close
.venv/bin/python scripts/sandbox_close_position.py --ticker SiU6 --execute
# crossing LIMIT close (offset in points)
.venv/bin/python scripts/sandbox_close_position.py --ticker SiU6 --execute --limit-offset 50
```

## Close + reconcile orchestrator — `scripts/sandbox_close_and_report.py`

End-to-end, conservative, always writes a report:

1. Refuse to run if `TINVEST_LIVE_TRADING_TOKEN` is set; back up the sandbox DB.
2. Bounded close: MARKET, then two crossing LIMIT fallbacks. On `30034` it
   tries the next variant; on any other error (e.g. `30079 Instrument is not
   available for trading` when the market is closed) it stops immediately —
   never loops.
3. Re-read the live position; **reconcile the DB to FLAT/CLOSED only if the
   account is actually flat** (open trade → `MANUAL_CLOSE`, position → FLAT,
   reset `exit_error_count`/`consecutive_errors`/`trading_paused`).
4. Run `sandbox_diagnostics.py`; write `reports/sandbox_manual_close_*.md`.
5. Never starts the daemon. Exit 0 = flat, 1 = still open.

`MANUAL_CLOSE` is a dedicated `SandboxExitReason` so a forced flatten is clearly
distinguishable from a strategy exit and is **not** a strategy result.

## Post-close recovery orchestrator — `scripts/sandbox_postclose_recover.py`

Phase-2, intended to run a few minutes after the close orchestrator:

- Account already FLAT → re-run the close+report orchestrator (no-op close +
  DB reconcile), then **restart** `hammertrade-sandbox-maxhold5.service`.
- Still short (close hit `30034`) → **top up** the sandbox account to
  `TARGET_BALANCE` (500k), re-run the close+report orchestrator (now with
  enough buying power), then restart the daemon if FLAT.
- Verifies status/diagnostics/logs; writes
  `reports/sandbox_postclose_recover_*.md`. Restart uses
  `sudo -n systemctl restart` (needs passwordless sudo for the service user).
- `--dry-run` reports the branch only (no top-up, no close, no restart).

## Scheduling on the server (one-shot systemd timers)

`/schedule` cloud routines run in Anthropic's cloud and **cannot reach the
server** (no SSH key, no `SANDBOX_TOKEN`) — do not use them for this, and never
commit the SSH key to a repo. Use server-side systemd one-shot timers instead.
Templates: `deploy/systemd/hammertrade-sandbox-close.example.{service,timer}`
and `hammertrade-sandbox-recover.example.{service,timer}`.

A **specific calendar date** in `OnCalendar` makes a timer inherently one-shot.
Schedule the close timer ~7 min after the MOEX open (09:07 MSK = 06:07 UTC,
server TZ is UTC) and the recover timer ~8 min after that (06:15 UTC):

```bash
# rename the .example files, set the dates, then:
sudo cp deploy/systemd/hammertrade-sandbox-close.example.service   /etc/systemd/system/hammertrade-sandbox-close.service
sudo cp deploy/systemd/hammertrade-sandbox-close.example.timer     /etc/systemd/system/hammertrade-sandbox-close.timer
sudo cp deploy/systemd/hammertrade-sandbox-recover.example.service /etc/systemd/system/hammertrade-sandbox-recover.service
sudo cp deploy/systemd/hammertrade-sandbox-recover.example.timer   /etc/systemd/system/hammertrade-sandbox-recover.timer
sudo systemctl daemon-reload
sudo systemctl enable --now hammertrade-sandbox-close.timer hammertrade-sandbox-recover.timer
systemctl list-timers 'hammertrade-*' --no-pager
```

After both have fired and the daemon is healthy, remove the one-shot units:

```bash
sudo systemctl disable --now hammertrade-sandbox-recover.timer hammertrade-sandbox-close.timer
sudo rm /etc/systemd/system/hammertrade-sandbox-{recover,close}.{timer,service}
sudo systemctl daemon-reload
```

## Outcome (2026-06-17)

The 09:07 close job with 200k still failed `30034`; the 09:15 recover job topped
up to 500k, the MARKET close filled immediately, the DB was reconciled to
`MANUAL_CLOSE`/FLAT, and the daemon was restarted healthy
(`WAITING_FOR_SIGNAL`). This confirmed the buying-power root cause (200k
insufficient, 500k sufficient).
