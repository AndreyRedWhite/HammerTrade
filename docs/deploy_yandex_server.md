# Deploy HammerTrade to Yandex Cloud VM

## Server

IP: 103.76.52.4

SSH config entry (`~/.ssh/config` on the server):

```
Host github-hammertrade
  HostName github.com
  User git
  IdentityFile ~/.ssh/hammertrade_github
  IdentitiesOnly yes
```

## Directory

```
/opt/hammertrade
```

## Runtime

Python venv: `/opt/hammertrade/.venv`

## Environment

`.env` is created manually on the server from `.env.example` and is never committed:

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Fill in `READONLY_TOKEN` only. Leave `SANDBOX_TOKEN` empty. Keep `LIVE_TRADING_ENABLED=false`.

## Basic commands

```bash
cd /opt/hammertrade
source .venv/bin/activate
pytest
```

## Pull updates

```bash
cd /opt/hammertrade
git pull
source .venv/bin/activate
pip install -r requirements.txt
```

## TLS check

```bash
curl -v https://invest-public-api.tbank.ru 2>&1 | grep -E "(SSL|certificate|error)"
```

Or via Python:

```bash
cd /opt/hammertrade
source .venv/bin/activate
python scripts/check_tbank_connectivity.py
```

## Isolated CA bundle for T-Bank API

The server's network routes T-Bank API through Russian Trusted Root CA. To enable API calls
without modifying the system trust store, create an isolated CA bundle for the HammerTrade
process only.

1. Place the Russian Trusted Root CA file:

```
/opt/hammertrade/certs/russian-trusted-root-ca.crt
```

2. Build the combined CA bundle:

```bash
cd /opt/hammertrade
bash scripts/build_tbank_ca_bundle.sh \
  --russian-root-ca /opt/hammertrade/certs/russian-trusted-root-ca.crt \
  --output /opt/hammertrade/certs/tbank-combined-ca.pem
```

3. Add to `/opt/hammertrade/.env`:

```env
GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/opt/hammertrade/certs/tbank-combined-ca.pem
SSL_CERT_FILE=/opt/hammertrade/certs/tbank-combined-ca.pem
REQUESTS_CA_BUNDLE=/opt/hammertrade/certs/tbank-combined-ca.pem
```

4. Verify connectivity:

```bash
cd /opt/hammertrade
source .venv/bin/activate
set -a; source .env; set +a
python scripts/check_tbank_connectivity.py \
  --ca-bundle /opt/hammertrade/certs/tbank-combined-ca.pem
```

Expected: `Result: PASS`

5. Rollback:

```bash
rm /opt/hammertrade/certs/tbank-combined-ca.pem
# Remove GRPC_DEFAULT_SSL_ROOTS_FILE_PATH / SSL_CERT_FILE / REQUESTS_CA_BUNDLE from .env
```

> **Important**: This setup intentionally trusts Russian Trusted Root CA only for the
> HammerTrade process through an isolated CA bundle.
>
> Do not install this CA globally with `update-ca-certificates`.
>
> Do not use this server for personal browsing, email, password managers, or unrelated services.
>
> At the current stage store only `READONLY_TOKEN` for paper/research. Sandbox token may be
> added later only when sandbox orders are implemented.

## Security

- Do not install Russian Trusted Root CA globally.
- Do not disable TLS verification.
- Do not use `verify=False` or `curl -k`.
- Do not store a live trading token on the server at this stage.
- `.env` is never committed.

## Paper trading daemon

Verify connectivity before starting:

```bash
cd /opt/hammertrade
source .venv/bin/activate
set -a; source .env; set +a
python scripts/check_tbank_connectivity.py --ca-bundle /opt/hammertrade/certs/tbank-combined-ca.pem
```

Smoke tests:

```bash
python scripts/run_paper_trader.py --once --dry-run
python scripts/run_paper_trader.py --once
python scripts/paper_report.py --state-db data/paper/paper_state.sqlite --output reports/paper_report_SiM6_SELL.md
```

Install as systemd service:

```bash
sudo cp deploy/systemd/hammertrade-paper.example.service /etc/systemd/system/hammertrade-paper.service
sudo systemctl daemon-reload
sudo systemctl enable hammertrade-paper
sudo systemctl start hammertrade-paper
sudo systemctl status hammertrade-paper
journalctl -u hammertrade-paper -f
```

State and output:

- SQLite state: `data/paper/paper_state.sqlite`
- CSV trades: `out/paper/paper_trades_SiM6_SELL.csv`
- Logs: `logs/paper_SiM6_SELL.log`
- Reports: `reports/paper_report_SiM6_SELL.md`
