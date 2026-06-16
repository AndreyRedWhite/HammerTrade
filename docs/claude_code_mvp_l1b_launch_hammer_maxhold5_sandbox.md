# Claude Code Prompt — MVP-L1b: Launch Hammer MaxHold5 Sandbox Service

## Контекст

Проект: `HammerTrade / MOEXF`.

Сервер:

```text
Server: 158.160.204.201
User: vorontsov
Project path: /opt/hammertrade
Virtualenv: /opt/hammertrade/.venv
Current date: 2026-06-11
```

## Текущее состояние

Rollover уже выполнен:

```text
SiM6 → SiU6
```

Текущие paper-сервисы:

```text
1. hammer-baseline
   systemd: hammertrade-paper.service
   ticker: SiU6
   direction: SELL
   liveness: OK

2. hammer-maxhold5
   systemd: hammertrade-paper-maxhold5.service
   ticker: SiU6
   direction: SELL
   max_hold_bars: 5
   liveness: OK

3. orb-paper
   systemd: hammertrade-paper-orb.service
   ticker: SiU6
   direction: SHORT
   strategy: opening_range_breakout
   liveness: OK

4. momentum-paper
   prepared but not launched
```

MVP-L1a уже выполнен:

```text
Sandbox execution architecture for hammer-maxhold5 is ready.

Created:
  src/sandbox/{models,repository,risk,reconciliation,broker,status,engine}.py
  configs/sandbox/hammer_maxhold5_siu6.yaml
  scripts/run_hammer_maxhold5_sandbox.py
  scripts/sandbox_account_setup.py
  scripts/sandbox_diagnostics.py
  deploy/systemd/hammertrade-sandbox-maxhold5.example.service
  docs/sandbox_execution_hammer_maxhold5.md

Tests:
  85 sandbox tests passed
  674 full project tests passed
```

Important from MVP-L1a:

```text
paper maxhold5 remains untouched as control group.
sandbox maxhold5 is separate.
live trading is structurally blocked.
real_orders_enabled=false.
validate_safety() hard-fails before any API order call unless:
  mode=sandbox
  orders.environment=sandbox
  real_orders_enabled=false
  TINVEST_LIVE_TRADING_TOKEN is unset
```

---

# Goal

Launch the separate `hammer-maxhold5` sandbox service.

This task is no longer just architecture preparation.

This task should:

```text
1. Configure sandbox token/account safely.
2. Create/reuse sandbox account.
3. Top up sandbox account to 40_000 RUB.
4. Run dry-run once on the server.
5. Run one foreground non-dry-run smoke.
6. Install the sandbox systemd unit.
7. Start the sandbox service.
8. Verify daemon status, liveness, DB/status/log/CSV.
9. Confirm paper services remain untouched.
10. Confirm Momentum remains not launched.
```

Sandbox is not live trading. Do not over-block this task with live-trading-level bureaucracy.

However, live trading must remain impossible.

---

# Important token instruction

The user will provide the sandbox token separately, outside this prompt.

Do not ask the user to paste the token into code, docs, reports, or git-tracked files.

The token should be stored only in `/opt/hammertrade/.env`.

Expected env variables:

```text
TINVEST_SANDBOX_TOKEN=<provided separately by user>
TINVEST_SANDBOX_ACCOUNT_ID=<created/reused by sandbox_account_setup.py>
```

If the existing project/config uses shorter names like `SANDBOX_TOKEN`, normalize carefully and document the final names.

Security requirements:

```text
1. Never print the token.
2. Never log the token.
3. Never include token in reports.
4. Never commit token.
5. Never write token to docs.
6. Only show boolean token_present=true/false.
7. If token is missing, stop and ask user to add it to .env.
```

Before proceeding, verify:

```bash
cd /opt/hammertrade
git status --short
git check-ignore -v .env || true
```

Expected:

```text
.env is ignored / not tracked.
```

If `.env` is tracked, STOP and report before doing anything else.

---

# Hard safety constraints

Strictly forbidden:

- real/live orders;
- using `TINVEST_LIVE_TRADING_TOKEN`;
- adding or keeping `TINVEST_LIVE_TRADING_TOKEN` in `.env` for this run;
- changing current paper services;
- stopping current paper services;
- changing hammer strategy params;
- changing `max_hold_bars=5`;
- launching Momentum;
- changing ORB;
- writing sandbox trades to paper DB;
- writing paper trades to sandbox DB;
- deleting old DB/CSV/logs;
- printing token;
- committing `.env`;
- committing secrets;
- enabling live mode.

Allowed in this task:

- run `sandbox_account_setup.py`;
- create/reuse sandbox account;
- top up sandbox account to 40_000 RUB;
- run sandbox dry-run once;
- run sandbox non-dry-run foreground smoke;
- install sandbox systemd unit from example;
- start sandbox systemd service;
- run diagnostics;
- create report;
- inspect logs/status/DB;
- place sandbox orders if a valid strategy signal occurs;
- keep service running after successful checks.

---

# Target service

Sandbox service name:

```text
hammertrade-sandbox-maxhold5.service
```

Source example unit:

```text
deploy/systemd/hammertrade-sandbox-maxhold5.example.service
```

Config:

```text
configs/sandbox/hammer_maxhold5_siu6.yaml
```

Expected artifacts:

```text
DB:
  data/sandbox/sandbox_state_hammer_maxhold5_siu6.sqlite

Status:
  runtime/sandbox_status_hammer_maxhold5_SiU6.json

Trades CSV:
  out/sandbox/sandbox_trades_hammer_maxhold5_SiU6.csv

Orders CSV:
  out/sandbox/sandbox_orders_hammer_maxhold5_SiU6.csv

Log:
  logs/sandbox_hammer_maxhold5_SiU6.log
```

Expected strategy:

```text
strategy: hammer-maxhold5
ticker: SiU6
direction: SELL
max_hold_bars: 5
mode: sandbox
orders.environment: sandbox
real_orders_enabled: false
capital_budget_rub: 40_000
max_daily_loss_rub: 3_000
max_total_loss_rub: 10_000
max_trades_per_day: 5
max_open_positions_per_strategy: 1
kill_switch_file: runtime/STOP_SANDBOX_TRADING
```

Note:

`max_open_positions_per_strategy=1` is acceptable for hammer-maxhold5 because this strategy should not hold multiple simultaneous positions. It is not meant as a final limitation for all future strategies.

---

# Step 0 — Current state check

Run:

```bash
cd /opt/hammertrade
source .venv/bin/activate

python scripts/check_all_paper_status.py
python scripts/paper_error_report.py

sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
sudo systemctl status hammertrade-paper-orb --no-pager
```

Confirm:

```text
paper baseline: active OK
paper maxhold5: active OK
orb-paper: active OK
momentum: not launched
```

Do not require paper open_trades=0 for sandbox launch.

If paper maxhold5 currently has an open trade:

```text
Do not try to mirror it.
Start sandbox as a separate fresh experiment from current time.
Record this caveat in report.
```

---

# Step 1 — Safety and config check

Run/inspect:

```bash
grep -R "real_orders_enabled" configs/sandbox/hammer_maxhold5_siu6.yaml src/sandbox scripts/run_hammer_maxhold5_sandbox.py
grep -R "TINVEST_LIVE_TRADING_TOKEN" configs/sandbox src/sandbox scripts/run_hammer_maxhold5_sandbox.py
```

Confirm:

```text
real_orders_enabled=false
mode=sandbox
orders.environment=sandbox
live token presence causes hard fail
no live order path is reachable
```

Also check:

```bash
test -f runtime/STOP_SANDBOX_TRADING && echo "KILL_SWITCH_PRESENT" || echo "NO_KILL_SWITCH"
```

If kill switch exists:

```text
Remove it only after explicitly confirming it was accidentally left from tests.
Otherwise stop and report.
```

---

# Step 2 — Token/account setup

The user will provide `TINVEST_SANDBOX_TOKEN` separately.

After token is added to `/opt/hammertrade/.env`, run:

```bash
cd /opt/hammertrade
set -a
source .env
set +a
source .venv/bin/activate

python scripts/sandbox_account_setup.py   --create-if-missing   --top-up-rub 40000
```

Expected:

```text
prints SANDBOX_ACCOUNT_ID or TINVEST_SANDBOX_ACCOUNT_ID
does not print token
does not create duplicate accounts silently
top-up to 40_000 RUB succeeds or reports clear limitation
```

If it prints:

```text
TINVEST_SANDBOX_ACCOUNT_ID=<id>
```

then add that exact line to `.env`.

If it prints:

```text
SANDBOX_ACCOUNT_ID=<id>
```

then either:
- add that exact line if config expects it;
- or normalize config/env to `TINVEST_SANDBOX_ACCOUNT_ID`.

After editing `.env`, verify:

```bash
set -a
source .env
set +a

python - <<'PY'
import os
print("TINVEST_SANDBOX_TOKEN present:", bool(os.getenv("TINVEST_SANDBOX_TOKEN") or os.getenv("SANDBOX_TOKEN")))
print("TINVEST_SANDBOX_ACCOUNT_ID present:", bool(os.getenv("TINVEST_SANDBOX_ACCOUNT_ID") or os.getenv("SANDBOX_ACCOUNT_ID")))
print("TINVEST_LIVE_TRADING_TOKEN present:", bool(os.getenv("TINVEST_LIVE_TRADING_TOKEN")))
PY
```

Expected:

```text
sandbox token present: True
sandbox account id present: True
live trading token present: False
```

Do not print token.

---

# Step 3 — Server dry-run once

Run:

```bash
cd /opt/hammertrade
set -a
source .env
set +a
source .venv/bin/activate

python scripts/run_hammer_maxhold5_sandbox.py   --config configs/sandbox/hammer_maxhold5_siu6.yaml   --dry-run   --once
```

Expected:

```text
SiU6 candle fetch works
safety gate passes
trading_state=DRY_RUN or equivalent
no sandbox order submitted
no real order possible
status file written/updated
```

If dry-run fails due to missing SDK/API/config:

```text
Fix if straightforward.
If not straightforward, STOP and report.
```

---

# Step 4 — Foreground non-dry-run smoke

Run one foreground non-dry-run once:

```bash
python scripts/run_hammer_maxhold5_sandbox.py   --config configs/sandbox/hammer_maxhold5_siu6.yaml   --once
```

Expected:

```text
safety gate passes
sandbox account visible
reconciliation runs
status file updates
if no signal: no order, this is OK
if signal occurs: sandbox order is placed and journaled
no real order possible
```

Important:

```text
Do not wait indefinitely for a signal.
If no signal, this is not a failure.
```

Then run diagnostics:

```bash
python scripts/sandbox_diagnostics.py
```

Expected:

```text
valid report
no crash if no trades
reconciliation status visible
risk state visible
```

---

# Step 5 — Install systemd unit

If steps 0–4 pass, install the sandbox unit.

Do not enable yet.

```bash
sudo cp deploy/systemd/hammertrade-sandbox-maxhold5.example.service   /etc/systemd/system/hammertrade-sandbox-maxhold5.service

sudo systemctl daemon-reload

systemctl cat hammertrade-sandbox-maxhold5.service
```

Verify unit:

```text
runs scripts/run_hammer_maxhold5_sandbox.py
uses configs/sandbox/hammer_maxhold5_siu6.yaml
does not reference live mode
does not reference SiM6
does not reference paper DB/status/log
```

---

# Step 6 — Start sandbox service

Start service:

```bash
sudo systemctl start hammertrade-sandbox-maxhold5.service
sleep 30
```

Check:

```bash
sudo systemctl status hammertrade-sandbox-maxhold5.service --no-pager

python scripts/sandbox_diagnostics.py

cat runtime/sandbox_status_hammer_maxhold5_SiU6.json
```

Expected:

```text
service active/running
mode=sandbox
ticker=SiU6
real_orders_enabled=false
orders_enabled=true
kill_switch_active=false
reconciliation_status OK or equivalent
liveness OK
token_present=true
sandbox_account_id_present=true
no token value exposed
```

If service fails:

```text
do not enable
inspect logs
fix if straightforward
otherwise stop and report
```

Logs:

```bash
journalctl -u hammertrade-sandbox-maxhold5.service -n 100 --no-pager
tail -100 logs/sandbox_hammer_maxhold5_SiU6.log
```

---

# Step 7 — Enable service only if healthy

If service is active and diagnostics OK:

```bash
sudo systemctl enable hammertrade-sandbox-maxhold5.service
```

Then verify:

```bash
systemctl is-enabled hammertrade-sandbox-maxhold5.service
```

If not healthy:

```text
leave service stopped or running manually only, do not enable
report reason
```

---

# Step 8 — Post-launch full status

Run:

```bash
python scripts/check_all_paper_status.py
python scripts/sandbox_diagnostics.py
python scripts/paper_error_report.py

sudo systemctl status hammertrade-paper --no-pager
sudo systemctl status hammertrade-paper-maxhold5 --no-pager
sudo systemctl status hammertrade-paper-orb --no-pager
sudo systemctl status hammertrade-sandbox-maxhold5 --no-pager
```

Expected final architecture:

```text
paper:
  hammer-baseline     active OK
  hammer-maxhold5     active OK
  orb-paper           active OK

sandbox:
  hammer-maxhold5     active OK

not launched:
  momentum-paper
```

---

# Step 9 — Report

Create:

```text
reports/mvp_l1b_launch_sandbox_maxhold5_20260611.md
reports/mvp_l1b_launch_sandbox_maxhold5_latest.md
```

If actual date differs, use actual date for dated file, but update latest.

Report structure:

```markdown
# MVP-L1b Launch Hammer MaxHold5 Sandbox Service

## Summary

## Pre-launch paper service health

## Token/account setup

## Sandbox account/top-up

## Dry-run result

## Foreground non-dry-run smoke

## Systemd installation

## Service start result

## Enable status

## Sandbox status

## Reconciliation

## Risk state

## Orders/fills/trades

## Diagnostics

## What was NOT changed

## What was NOT launched

## Issues / warnings

## Recommendation

## Next monitoring plan
```

---

# Success criteria

The task is successful if:

```text
1. Existing paper services remain active and untouched.
2. Momentum remains not launched.
3. Sandbox token/account are configured without exposing token.
4. Sandbox account exists and is topped up to 40_000 RUB or clear limitation reported.
5. Dry-run once succeeds.
6. Foreground non-dry-run once succeeds.
7. Systemd unit installed.
8. Sandbox service started.
9. Sandbox service enabled only if healthy.
10. runtime/sandbox_status_hammer_maxhold5_SiU6.json exists and is valid.
11. diagnostics report exists.
12. No real/live orders are possible.
13. No live token is present/used.
```

Partial success is acceptable if:

```text
architecture is OK,
token/account setup is OK,
dry-run works,
but service start is blocked by a clear issue.
```

In that case do not enable service and report the blocker.

---

# Final response format

Claude final response:

```markdown
## MVP-L1b Launch Hammer MaxHold5 Sandbox Service — готово / частично / не выполнено

### Decision

### Summary

### Paper services

### Token/account

### Dry-run

### Non-dry-run smoke

### Systemd

### Sandbox service status

### Sandbox diagnostics

### Orders/fills/trades

### Safety confirmation

### What was NOT changed

### What was NOT launched

### Issues / warnings

### Artifacts

### Next steps
```
