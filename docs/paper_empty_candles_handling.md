# Empty candles response handling

## Problem

The T-Bank API occasionally returns an empty response when queried for candles.
This triggers `pandas.errors.EmptyDataError: No columns to parse from file` somewhere
in the fetch/parse pipeline.  Before MVP-2.1a this error was caught by the generic
`except Exception` handler and reported as `API_ERROR`, indistinguishable from real
API failures.

## Symptoms (pre-MVP-2.1a)

```
ERROR [baseline] API_ERROR ticker=SiM6 error=No columns to parse from file
ERROR [maxhold5] API_ERROR ticker=SiM6 error=No columns to parse from file
```

Frequency observed 2026-05-13 – 2026-05-18: baseline 17×, maxhold5 28×.

## Status values

| Status | Meaning |
|--------|---------|
| `OK` | Candles fetched and processed normally |
| `EMPTY_CANDLES_RESPONSE` | API returned no/empty candle data (auto-recovers) |
| `API_TIMEOUT` | Fetch exceeded timeout (auto-recovers) |
| `API_ERROR` | Other unexpected fetch/parse error |
| `STALE_CANDLES` | Candles received but too old |
| `MARKET_CLOSED` | Outside trading hours |
| `NO_CANDLES_DURING_OPEN_SESSION` | Market open but no candles (weekend/holiday edge) |

## Expected daemon behavior on EMPTY_CANDLES_RESPONSE

1. Exception caught, classified by `_is_empty_candles_error()`.
2. `empty_response_count` incremented (cumulative, never resets).
3. `consecutive_empty_responses` incremented (resets to 0 on next successful fetch).
4. `last_empty_response_at` updated.
5. Status file written with `last_fetch_status = "EMPTY_CANDLES_RESPONSE"`.
6. Log line at WARNING level — no traceback.
7. Cycle returns early — **no further processing**.

## Impact on bars_held

**None.** The daemon returns before calling `process_candle()`.  
`bars_held` is only incremented inside `process_candle()`, which is never reached
when a fetch error (of any kind) occurs.

## Impact on max_hold_bars / MAX_HOLD_EXIT

**None.** The `max_hold_bars` counter is driven by `bars_held` which is only
incremented on a valid processed candle.  An empty response does not bring the
trade closer to `MAX_HOLD_EXIT`.

## New status file fields (MVP-2.1a)

```json
{
  "empty_response_count": 0,
  "consecutive_empty_responses": 0,
  "last_empty_response_at": null,
  "last_empty_response_message": null,
  "last_successful_fetch_at": "2026-05-18T08:15:40Z"
}
```

All fields are backward-compatible (absent in old status files → treated as 0/null).

## How to check status

```bash
# Human-readable health check
.venv/bin/python scripts/check_paper_status.py --status-file runtime/paper_status_SiM6_SELL.json

# Error summary for both experiments
.venv/bin/python scripts/paper_error_report.py

# Or specify files explicitly
.venv/bin/python scripts/paper_error_report.py \
  --status-files runtime/paper_status_SiM6_SELL.json runtime/paper_status_SiM6_SELL_maxhold5.json
```

## When to worry

| Condition | Action |
|-----------|--------|
| Single `EMPTY_CANDLES_RESPONSE`, recovers next cycle | Normal, ignore |
| `consecutive_empty_responses >= 3` | Check API connectivity |
| `consecutive_empty_responses >= 10` | Check T-Bank SDK / CA bundle |
| Frequency increasing over days | Investigate rate-limit or API degradation |
| `last_fetch_status` stuck at `EMPTY_CANDLES_RESPONSE` for > 5 min during market hours | Check `journalctl -u hammertrade-paper -n 50 --no-pager` |

## Rate-limit / parallel services hypothesis

Two daemons (`baseline` + `maxhold5`) make independent API calls on the same 20s
poll cycle.  The higher `EMPTY_CANDLES_RESPONSE` count in maxhold5 (28 vs 17) may
reflect timing differences rather than a true rate-limit effect — both use the same
gRPC endpoint with the same READONLY_TOKEN.

If the frequency continues to grow, consider **MVP-2.2: shared candle fetch/cache**,
where a single fetcher writes a local cache and both experiments read from it.

## Future improvement: shared candle fetch/cache

**Not in MVP-2.1a.**  Potential MVP-2.2 design:

```
one shared fetcher → local SQLite/file cache
baseline reads from cache
maxhold5 reads from cache
→ half the API calls, no divergence between experiments
```
