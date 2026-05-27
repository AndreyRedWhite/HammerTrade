# Trading Liveness Guard (MVP-2.3a)

## Problem

`systemctl status` can show a service as `active (running)` while the trading daemon
is in a permanent error loop and not processing candles at all.
This happened in the incident below — 790 API errors over ~2 days with no candle fetch.

## Incident 2026-05-25 — 2026-05-27

- **Symptom**: both paper services `active`, but last successful fetch was ~2 days ago.
  About 790 `API_ERROR` entries per service.
- **Root cause**: T-Bank API started returning `expiration_date='2026-06-19'`
  (SiM6 futures expiry). `pd.read_csv()` had inferred `expiration_date` as `float64`
  (NaN). Assigning the date string to that column raised
  `Invalid value '2026-06-19' for dtype 'float64'`.
- **Fix**: `pd.read_csv(INSTRUMENTS_CSV, dtype=object)` in `src/tbank/instruments.py`
  (commit b4608fb).
- **Detection gap**: the old monitoring only checked `last_cycle_at_utc` age, not
  whether candle fetches were actually succeeding.

## Status fields added (MVP-2.3a)

New fields in the status JSON (all backward-compatible; old consumers get `None`/`0`
defaults if fields are absent):

| Field | Type | Description |
|---|---|---|
| `trading_liveness_status` | str | `OK` / `DEGRADED` / `STALLED` |
| `trading_liveness_reason` | str\|null | Human-readable reason string |
| `total_api_errors` | int | Lifetime total of API errors (never resets) |
| `last_api_error_at` | str\|null | ISO UTC timestamp of last API error |
| `last_api_error_message` | str\|null | Message of last API error |
| `minutes_since_last_successful_fetch` | float\|null | Minutes since last OK fetch |
| `liveness_checked_at` | str | ISO UTC when liveness was last computed |

Existing fields unchanged: `consecutive_api_errors`, `last_successful_fetch_at`,
`empty_response_count`, `consecutive_empty_responses`, etc.

## Liveness statuses

### OK
- Market is closed, **OR**
- Market is open AND `consecutive_api_errors < 5` AND
  `minutes_since_last_successful_fetch < 15` AND
  `consecutive_empty_responses < 3`

### DEGRADED
Market is open AND any of:
- `consecutive_api_errors >= 5`
- `minutes_since_last_successful_fetch >= 15`
- `consecutive_empty_responses >= 3`

### STALLED
Market is open AND any of:
- `consecutive_api_errors >= 20`
- `minutes_since_last_successful_fetch >= 30`

## Thresholds (`src/paper/liveness.py`)

```python
DEGRADED_AFTER_CONSECUTIVE_ERRORS = 5
STALLED_AFTER_CONSECUTIVE_ERRORS  = 20
DEGRADED_AFTER_FETCH_MINUTES      = 15
STALLED_AFTER_FETCH_MINUTES       = 30
DEGRADED_AFTER_EMPTY_RESPONSES    = 3
```

## Edge cases

- **Market closed** → always `OK`, regardless of error counts or fetch age.
  Error counters (`consecutive_api_errors`) are reset when market closes.
- **Market just opened** → `last_successful_fetch_at` is reset to `None` on the
  open transition, so time-based STALLED/DEGRADED won't fire immediately.
  Only the consecutive-errors threshold applies until the first successful fetch.
- **`last_successful_fetch_at=None`** → time-based checks are skipped entirely.

## How `check_paper_status.py` interprets status

Exit codes:
- `0` — liveness OK
- `1` — liveness DEGRADED
- `2` — liveness STALLED, status file missing/unreadable, or daemon stale

Console output format:
```
[OK]  SiM6 SELL  pid=12345
[DEGRADED] (consecutive_api_errors=7)  SiM6 SELL  pid=12345
[STALLED] (consecutive_api_errors=790)  SiM6 SELL  pid=12345
```

## How `paper_error_report.py` reports problems

- Liveness summary at the top of the report
- For STALLED: `CRITICAL: service is active but trading liveness is STALLED`
- For DEGRADED: `** WARNING: one or more services are DEGRADED **`

## How to react to DEGRADED

1. Run `check_paper_status.py` on the server to see the full detail.
2. Check `journalctl -u hammertrade-paper -n 50 --no-pager` for the error messages.
3. Look at `last_api_error_message` — it usually tells you exactly what's wrong.
4. If the error is transient (network blip, rate limit), wait — the daemon recovers
   automatically when fetch succeeds.
5. If the error is structural (wrong ticker, expired contract, SDK change),
   fix the root cause and restart the service.

## How to react to STALLED

Same as DEGRADED, but act immediately — trading has been interrupted for 20+ errors
or 30+ minutes.

1. `ssh vorontsov@158.160.204.201`
2. `cd /opt/hammertrade`
3. `.venv/bin/python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json`
4. `journalctl -u hammertrade-paper --since '1 hour ago' --no-pager | tail -30`
5. Fix root cause.
6. `sudo systemctl restart hammertrade-paper`
7. Wait 30s, then re-run `check_paper_status.py` — expect `[OK]`.

## What this guard does NOT do

- Does **not** auto-restart services.
- Does **not** send Telegram/email alerts.
- Does **not** place any orders.
- Does **not** change trading strategy.

Only detects and reports stalled trading.

## Future improvements

- `MVP-2.3b`: Telegram/email alert on STALLED
- `MVP-2.4`: Futures rollover SiM6 → SiU6 (expiry 2026-06-19)
- `MVP-2.5`: Shared candle fetch/cache for baseline and experiments
