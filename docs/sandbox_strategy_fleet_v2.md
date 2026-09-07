# Sandbox Strategy Fleet v2

Five cost-aware strategy services for restarting HammerTrade experiments.
Every order-producing service uses the T-Bank **sandbox contour only**.  Large
notionals are intentional: funds are virtual, while real fills, commission,
partial execution and reconciliation remain part of the experiment.

## Services

| Unit template | Strategy | Default virtual exposure |
|---|---|---:|
| `hammertrade-sandbox-orb-v2` | two-sided IMOEXF ORB, close-confirmed | 50 contracts |
| `hammertrade-sandbox-volbreak` | IMOEXF 1h compression breakout | 50 contracts |
| `hammertrade-sandbox-carry` | IMOEXF + GOLD perp/quarterly carry | 1M RUB per construction |
| `hammertrade-sandbox-pairs-v2` | TATN + RTKM rolling-beta pairs | 1M RUB per leg |
| `hammertrade-sandbox-xsec-momentum` | 3 long / 3 short equity momentum | 1M RUB per name |

Notional is not a safety boundary. Dedicated accounts, idempotency,
two-leg handling, reconciliation, actual-fill PnL and backlog guards are data
quality boundaries and must remain enabled.

Every v2 service also owns a fresh state database. Earlier experiment data is
kept for reference but is never mixed into current fleet metrics.

## One-time account setup

Use one account per strategy family. Reusing an account makes an executor see
another strategy's position as a reconciliation failure.

```bash
cd /opt/hammertrade
source .venv/bin/activate
python scripts/sandbox_account_setup.py --help
```

Configure all five named accounts and bind them to `.env` in one step:

```bash
python scripts/configure_sandbox_fleet.py --create-missing
```

The command backs up `.env`, writes account IDs atomically and keeps each
strategy switch disabled. Add `--enable` only after virtual funding and dry-run
validation. To fund an individual account manually, for example:

```bash
python scripts/sandbox_account_setup.py --dedicated \
  --account-name hammertrade-volbreak --top-up-rub 100000000
```

The T-Bank sandbox may require an SMS confirmation for a large virtual pay-in.

Record the resulting IDs in `/opt/hammertrade/.env`:

```dotenv
SANDBOX_ACCOUNT_ID_ORB_V2=...
SANDBOX_ACCOUNT_ID_VOLBREAK=...
SANDBOX_ACCOUNT_ID_CARRY=...
SANDBOX_ACCOUNT_ID_PAIRS_V2=...
SANDBOX_ACCOUNT_ID_XSEC=...

SANDBOX_ORB_V2_ENABLED=true
SANDBOX_VOLBREAK_ENABLED=true
SANDBOX_CARRY_ENABLED=true
SANDBOX_PAIRS_V2_ENABLED=true
SANDBOX_XSEC_ENABLED=true
```

`SANDBOX_TOKEN` and `READONLY_TOKEN` are also required. Never set a live-order
token; each new executor refuses to run when `TINVEST_LIVE_TRADING_TOKEN` is
present.

## Smoke test before installing units

Run each command from its unit with `--dry-run --once`. Dry-run still resolves
instruments and downloads production market data, but places no order.

```bash
.venv/bin/python scripts/run_orb_sandbox_trader.py --dry-run --once
.venv/bin/python scripts/run_volatility_breakout_sandbox_trader.py --dry-run --once
.venv/bin/python scripts/run_carry_sandbox_trader.py --dry-run --once
.venv/bin/python scripts/run_pairs_sandbox_trader.py --dry-run --once
.venv/bin/python scripts/run_xsec_momentum_sandbox_trader.py --dry-run --once
```

Use explicit state/status/log paths from the unit templates for a realistic
smoke test and avoid mixing dry-run state with the final experiment database.

## Install

```bash
sudo cp deploy/systemd/hammertrade-sandbox-orb-v2.example.service \
  /etc/systemd/system/hammertrade-sandbox-orb-v2.service
sudo cp deploy/systemd/hammertrade-sandbox-volbreak.example.service \
  /etc/systemd/system/hammertrade-sandbox-volbreak.service
sudo cp deploy/systemd/hammertrade-sandbox-carry.example.service \
  /etc/systemd/system/hammertrade-sandbox-carry.service
sudo cp deploy/systemd/hammertrade-sandbox-pairs-v2.example.service \
  /etc/systemd/system/hammertrade-sandbox-pairs-v2.service
sudo cp deploy/systemd/hammertrade-sandbox-xsec-momentum.example.service \
  /etc/systemd/system/hammertrade-sandbox-xsec-momentum.service
sudo systemctl daemon-reload
sudo systemctl enable --now \
  hammertrade-sandbox-orb-v2 \
  hammertrade-sandbox-volbreak \
  hammertrade-sandbox-carry \
  hammertrade-sandbox-pairs-v2 \
  hammertrade-sandbox-xsec-momentum
```

The dashboard discovers these services from systemd automatically.

## Verify

```bash
python scripts/check_all_paper_status.py
python scripts/generate_fleet_report.py
systemctl --no-pager --full status \
  hammertrade-sandbox-orb-v2 \
  hammertrade-sandbox-volbreak \
  hammertrade-sandbox-carry \
  hammertrade-sandbox-pairs-v2 \
  hammertrade-sandbox-xsec-momentum
```

The dashboard remains available through the SSH tunnel at
`http://localhost:8787`.

## Strategy-specific notes

- ORB v2 acts only on the latest closed bar, so a restart cannot replay a
  morning breakout at today's market price. Point value comes from T-Bank.
- Volatility breakout uses shifted Donchian levels and a prior ATR-compression
  gate, then exits on stop, take or the shorter channel.
- Carry requires projected carry over the conservative holding horizon to cover
  full-cycle costs by 2x.
- Pairs can use a rolling hedge ratio and block entries when correlation or beta
  stability deteriorates. The hard PnL-space stop remains authoritative.
- Cross-sectional momentum closes and reopens a whole basket every 21 calendar
  days during the main session. It excludes today's incomplete D1 candle and
  records aggregate actual-fill PnL for each holding period.
