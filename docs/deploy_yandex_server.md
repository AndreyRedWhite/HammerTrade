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

**Known issue**: as of 2026-05-02, T-Bank API returns a self-signed certificate in the chain
on this server's network. This means live API calls (candle loading, instrument specs) will
fail with SSL errors. Research/backtest/analysis that does not call T-Bank API works normally.

Do not work around this by installing Russian Trusted Root CA, disabling TLS verification,
or using `curl -k`. If the TLS issue needs to be resolved, contact the hosting provider.

## Security

- Do not install Russian Trusted Root CA.
- Do not disable TLS verification.
- Do not store a live trading token on the server.
- `.env` is never committed.
