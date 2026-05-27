"""SiM6 → SiU6 rollover diagnostic.

Checks:
  1. SiU6 instrument details (figi, uid, expiry, lot, min_price_increment)
  2. Recent 1m candle availability
  3. Orderbook: bid/ask spread, top-5 depth
  4. Side-by-side liquidity comparison SiM6 vs SiU6

Run on server:
  cd /opt/hammertrade
  .venv/bin/python scripts/check_rollover_siu6.py
"""
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.tbank.settings import load_tbank_settings
from src.tbank.client import get_tbank_client
from src.tbank.instruments import resolve_instrument
from src.tbank.candles import fetch_historical_candles

CLASS_CODE = "SPBFUT"
TICKERS = ["SiM6", "SiU6"]


def _fmt_price(v) -> str:
    if v is None:
        return "N/A"
    return f"{v:,.2f}"


def check_instrument(client, ticker: str) -> dict:
    print(f"\n{'='*55}")
    print(f"  Instrument: {ticker}")
    print(f"{'='*55}")
    try:
        instr = resolve_instrument(client, ticker, CLASS_CODE)
    except Exception as e:
        print(f"  ERROR: {e}")
        return {"ticker": ticker, "error": str(e)}

    print(f"  name               : {instr.get('name')}")
    print(f"  uid                : {instr.get('uid')}")
    print(f"  figi               : {instr.get('figi')}")
    print(f"  class_code         : {instr.get('class_code')}")
    print(f"  lot                : {instr.get('lot')}")
    print(f"  min_price_increment: {instr.get('min_price_increment')}")
    print(f"  expiration_date    : {instr.get('expiration_date')}")
    print(f"  first_1min_candle  : {instr.get('first_1min_candle_date')}")
    return instr


def check_candles(client, uid: str, ticker: str) -> dict:
    print(f"\n  --- 1m Candle Check ({ticker}) ---")
    now = datetime.now(tz=timezone.utc)
    # Last 2 trading days worth of 1m candles
    start = (now - timedelta(days=2)).replace(second=0, microsecond=0)
    end = now.replace(second=0, microsecond=0)
    try:
        df = fetch_historical_candles(client, uid, start, end, "1m")
    except Exception as e:
        print(f"  ERROR fetching candles: {e}")
        return {"candles_available": False, "error": str(e)}

    if df.empty:
        print(f"  WARN: no 1m candles returned for last 2 days")
        return {"candles_available": False, "count": 0}

    count = len(df)
    first = df["timestamp"].iloc[0]
    last = df["timestamp"].iloc[-1]
    vol_mean = df["volume"].mean()
    vol_max = df["volume"].max()
    vol_last10 = df["volume"].tail(10).mean()
    price_last = df["close"].iloc[-1]

    print(f"  candles (2d)       : {count}")
    print(f"  first candle       : {first}")
    print(f"  last candle        : {last}")
    print(f"  last close         : {_fmt_price(price_last)}")
    print(f"  avg volume/bar     : {vol_mean:.1f}")
    print(f"  max volume/bar     : {vol_max:.0f}")
    print(f"  avg vol last 10    : {vol_last10:.1f}")

    return {
        "candles_available": True,
        "count": count,
        "last_close": price_last,
        "avg_volume": vol_mean,
        "avg_vol_last10": vol_last10,
    }


def check_orderbook(client, uid: str, ticker: str) -> dict:
    print(f"\n  --- Orderbook ({ticker}) ---")
    try:
        from t_tech.invest import GetOrderBookRequest
        resp = client.market_data.get_order_book(instrument_id=uid, depth=10)
    except Exception as e:
        print(f"  ERROR fetching orderbook: {e}")
        # Try alternative call signature
        try:
            resp = client.market_data.get_order_book(figi=None, depth=10, instrument_id=uid)
        except Exception as e2:
            print(f"  ERROR (alt): {e2}")
            return {"orderbook_available": False}

    from src.tbank.money import quotation_to_float

    bids = resp.bids
    asks = resp.asks

    if not bids and not asks:
        print(f"  WARN: empty orderbook (market may be closed)")
        return {"orderbook_available": True, "empty": True}

    def _q(v):
        try:
            return quotation_to_float(v)
        except Exception:
            return None

    rows_bid = [(_q(b.price), b.quantity) for b in bids[:10]]
    rows_ask = [(_q(a.price), a.quantity) for a in asks[:10]]

    best_bid = rows_bid[0][0] if rows_bid else None
    best_ask = rows_ask[0][0] if rows_ask else None
    spread = (best_ask - best_bid) if (best_bid and best_ask) else None
    spread_ticks = spread  # SiM6/SiU6 min_increment is 1.0

    top5_bid_vol = sum(q for _, q in rows_bid[:5])
    top5_ask_vol = sum(q for _, q in rows_ask[:5])
    top10_bid_vol = sum(q for _, q in rows_bid[:10])
    top10_ask_vol = sum(q for _, q in rows_ask[:10])

    print(f"  best bid           : {_fmt_price(best_bid)}")
    print(f"  best ask           : {_fmt_price(best_ask)}")
    print(f"  spread             : {spread} pts ({spread_ticks} ticks)")
    print(f"  top-5  bid/ask vol : {top5_bid_vol} / {top5_ask_vol}")
    print(f"  top-10 bid/ask vol : {top10_bid_vol} / {top10_ask_vol}")

    print(f"\n  Bids (top-10):")
    for price, qty in rows_bid[:10]:
        print(f"    {_fmt_price(price):>10}  x {qty:>6}")
    print(f"\n  Asks (top-10):")
    for price, qty in rows_ask[:10]:
        print(f"    {_fmt_price(price):>10}  x {qty:>6}")

    return {
        "orderbook_available": True,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "top5_bid_vol": top5_bid_vol,
        "top5_ask_vol": top5_ask_vol,
        "top10_bid_vol": top10_bid_vol,
        "top10_ask_vol": top10_ask_vol,
    }


def check_last_prices(client, uids: list[str], tickers: list[str]) -> dict:
    print(f"\n{'='*55}")
    print(f"  Last Prices Comparison")
    print(f"{'='*55}")
    results = {}
    for uid, ticker in zip(uids, tickers):
        try:
            resp = client.market_data.get_last_prices(instrument_id=[uid])
            if resp.last_prices:
                from src.tbank.money import quotation_to_float
                lp = resp.last_prices[0]
                price = quotation_to_float(lp.price)
                print(f"  {ticker:6}: last_price={_fmt_price(price)}")
                results[ticker] = price
            else:
                print(f"  {ticker:6}: no last price")
        except Exception as e:
            print(f"  {ticker:6}: ERROR {e}")
    return results


def main():
    settings = load_tbank_settings("prod")
    print(f"Rollover Diagnostic: SiM6 → SiU6")
    print(f"Run at: {datetime.now(tz=timezone.utc).isoformat()}")

    instruments = {}
    candles = {}
    orderbooks = {}

    with get_tbank_client(settings) as client:
        for ticker in TICKERS:
            instr = check_instrument(client, ticker)
            instruments[ticker] = instr

        uids = [
            instruments[t].get("uid")
            for t in TICKERS
            if "uid" in instruments.get(t, {})
        ]
        valid_tickers = [t for t in TICKERS if "uid" in instruments.get(t, {})]

        for ticker in valid_tickers:
            uid = instruments[ticker]["uid"]
            candles[ticker] = check_candles(client, uid, ticker)

        for ticker in valid_tickers:
            uid = instruments[ticker]["uid"]
            orderbooks[ticker] = check_orderbook(client, uid, ticker)

        check_last_prices(client, uids, valid_tickers)

    # ── Summary comparison ──────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  SUMMARY: SiM6 vs SiU6")
    print(f"{'='*55}")

    for ticker in TICKERS:
        instr = instruments.get(ticker, {})
        cv = candles.get(ticker, {})
        ob = orderbooks.get(ticker, {})

        if "error" in instr:
            print(f"\n  {ticker}: NOT FOUND — {instr['error']}")
            continue

        print(f"\n  {ticker}:")
        print(f"    expiration        : {instr.get('expiration_date', 'N/A')}")
        print(f"    min_price_incr    : {instr.get('min_price_increment', 'N/A')}")
        print(f"    lot               : {instr.get('lot', 'N/A')}")
        print(f"    candles_available : {cv.get('candles_available', False)}")
        if cv.get("candles_available"):
            print(f"    1m candles (2d)   : {cv.get('count', 0)}")
            print(f"    avg vol/bar       : {cv.get('avg_volume', 0):.1f}")
        if ob.get("orderbook_available") and not ob.get("empty"):
            print(f"    spread            : {ob.get('spread', 'N/A')} pts")
            print(f"    top-5 depth (B+A) : {ob.get('top5_bid_vol', 0) + ob.get('top5_ask_vol', 0)}")
            print(f"    top-10 depth(B+A) : {ob.get('top10_bid_vol', 0) + ob.get('top10_ask_vol', 0)}")
        elif ob.get("empty"):
            print(f"    orderbook         : EMPTY (market closed)")
        else:
            print(f"    orderbook         : unavailable")


if __name__ == "__main__":
    main()
