"""Perp funding-carry SANDBOX trading daemon — REAL fills on the T-Bank SANDBOX
contour (virtual money). Construction: SHORT perp + LONG front quarterly.

Economics (see scripts/research_perp_funding.py): retail longs pay perp funding
~28-30 %/yr while the quarterly implies 12-17 %/yr → net carry to the construction
(IMOEX +17.4 %/yr, GOLD +10.8 %/yr historically, before costs).

PnL has TWO components, journaled separately:
  * price PnL from real fills (basis convergence / drift), and
  * daily FUNDING accrual on the perp leg (cash flow, invisible in fills) —
    accrued from MOEX ISS SWAPRATE (points/day; positive → shorts receive).

Signal:
  enter when expected carry = fundingMA(N) − basis/DTE > entry threshold (bp/day)
  exit  when expected carry < exit threshold (funding regime flipped)
  roll  the quarterly leg when DTE < roll-dte (close old, open next front)

Safety: sandbox contour only; per-service trading flag; never leaves a one-legged
position; reconciliation halt; daily action cap; pause resets each MSK day.
"""
import argparse
import json
import logging
import math
import os
import sqlite3
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sandbox.broker import get_sandbox_broker

ISS = "https://iss.moex.com/iss"
DEFAULT_LEGS = "IMOEXF:MM"  # PERP:QUARTERLY_SERIES[,PERP:SERIES...]
MONTH_CODES = {"H": 3, "M": 6, "U": 9, "Z": 12}


# ───────────────────────── args ─────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Perp funding-carry SANDBOX daemon (real sandbox fills, virtual money).")
    p.add_argument("--legs", default=DEFAULT_LEGS,
                   help="Comma list PERP:QSERIES, e.g. IMOEXF:MM,GLDRUBF:GL")
    p.add_argument("--notional", type=float, default=45000.0,
                   help="Target notional per construction (both legs each ≈ this)")
    p.add_argument("--funding-ma-days", type=int, default=20)
    p.add_argument("--entry-carry-bp", type=float, default=1.0,
                   help="Enter when expected carry (bp/day) exceeds this")
    p.add_argument("--exit-carry-bp", type=float, default=0.0,
                   help="Exit when expected carry (bp/day) falls below this")
    p.add_argument("--roundtrip-cost-bps", type=float, default=10.0,
                   help="Expected full-cycle commission+spread cost in bps")
    p.add_argument("--expected-hold-days", type=float, default=10.0,
                   help="Conservative holding horizon used by the entry cost gate")
    p.add_argument("--min-cost-cover-multiple", type=float, default=2.0,
                   help="Projected carry must cover round-trip cost by this multiple")
    p.add_argument("--roll-dte", type=int, default=7,
                   help="Roll the quarterly leg when days-to-expiry < this")
    p.add_argument("--min-front-dte", type=int, default=10,
                   help="Front selection: nearest quarterly with DTE > this")
    p.add_argument("--max-actions-per-day", type=int, default=4,
                   help="Entries+exits+rolls cap per MSK day")
    p.add_argument("--account-id-env", default="SANDBOX_ACCOUNT_ID")
    p.add_argument("--account-id", default=None)
    p.add_argument("--trading-enabled-env", default="SANDBOX_TRADING_ENABLED")
    p.add_argument("--state-db", default="data/sandbox/sandbox_carry.sqlite")
    p.add_argument("--status-file", default="runtime/sandbox_status_CARRY.json")
    p.add_argument("--log-file", default="logs/sandbox_CARRY.log")
    p.add_argument("--poll-interval-seconds", type=int, default=900)
    p.add_argument("--market-hours-config", default="configs/market_hours/moex_futures.yaml")
    p.add_argument("--ignore-market-hours", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--once", action="store_true")
    return p.parse_args()


def _setup_logging(log_file: str) -> logging.Logger:
    logger = logging.getLogger("carry_sandbox")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [carry_sandbox] %(message)s")
    if not logger.handlers:
        sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); logger.addHandler(sh)
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file); fh.setFormatter(fmt); logger.addHandler(fh)
    return logger


def _today_msk(now_utc: Optional[datetime] = None) -> str:
    now_utc = now_utc or datetime.now(tz=timezone.utc)
    return (now_utc + timedelta(hours=3)).strftime("%Y-%m-%d")


# ───────────────────────── ISS market data (no token needed) ─────────────────
def _iss_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def iss_last_price(secid: str) -> Optional[float]:
    d = _iss_json(f"{ISS}/engines/futures/markets/forts/securities/{secid}.json"
                  f"?iss.meta=off&iss.only=marketdata&marketdata.columns=SECID,LAST,BOARDID")
    for row in d["marketdata"]["data"]:
        if row[1]:
            return float(row[1])
    return None


def iss_funding_history(secid: str, days: int = 40) -> list[tuple[str, float]]:
    """[(TRADEDATE, SWAPRATE_points), ...] for the last ~`days` calendar days."""
    frm = (datetime.now(tz=timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    d = _iss_json(f"{ISS}/history/engines/futures/markets/forts/securities/{secid}.json"
                  f"?iss.meta=off&from={frm}&history.columns=TRADEDATE,SWAPRATE,SETTLEPRICE")
    return [(r[0], float(r[1])) for r in d["history"]["data"] if r[1] is not None]


# ───────────────────────── pure signal math (unit-tested) ─────────────────────
def funding_ma_bp(funding_pts: list[float], price_pts: float, n: int) -> Optional[float]:
    """Rolling-mean funding in bp/day of perp price; None if not enough history."""
    if price_pts <= 0 or len(funding_pts) < max(n // 2, 3):
        return None
    tail = funding_pts[-n:]
    return sum(tail) / len(tail) / price_pts * 1e4


def expected_carry_bp(funding_ma: float, perp_px: float, q_px: float, dte: int) -> float:
    """bp/day to SHORT perp + LONG quarterly: funding received − basis decay paid."""
    basis_bp = (q_px / perp_px - 1) * 1e4
    return funding_ma - basis_bp / max(dte, 1)


def required_daily_carry(roundtrip_cost_bps: float, expected_hold_days: float,
                         cover_multiple: float) -> float:
    """Minimum bp/day needed to cover full-cycle costs with a safety margin."""
    if roundtrip_cost_bps < 0 or expected_hold_days <= 0 or cover_multiple < 1:
        raise ValueError("invalid carry cost-gate parameters")
    return roundtrip_cost_bps * cover_multiple / expected_hold_days


def pick_front(contracts: list[dict], now_utc: datetime, min_dte: int) -> Optional[dict]:
    """Nearest quarterly with DTE > min_dte. contracts: [{ticker, uid, expiry(datetime), ...}]"""
    live = [c for c in contracts if (c["expiry"] - now_utc).days > min_dte]
    return min(live, key=lambda c: c["expiry"]) if live else None


def leg_lots(notional: float, perp_px: float, perp_pv: float,
             q_px: float, q_pv: float) -> tuple[int, int]:
    """Lots per leg targeting `notional`, then matching the smaller leg's notional."""
    perp_lots = max(int(round(notional / (perp_px * perp_pv))), 1)
    target = perp_lots * perp_px * perp_pv
    q_lots = max(int(round(target / (q_px * q_pv))), 1)
    return perp_lots, q_lots


def fill_points(total_rub, lots, point_value):
    """API executed_order_price is TOTAL RUB — journal stores points per contract."""
    if total_rub is None or not lots or not point_value:
        return None
    return total_rub / (lots * point_value)


def funding_rub(swaprate_pts: float, perp_lots: int, perp_pv: float) -> float:
    """Daily funding cash flow to a SHORT perp position (positive = we receive)."""
    return swaprate_pts * perp_pv * perp_lots


# ───────────────────────── persistence ─────────────────────────
class CarryDB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS carry_trades (
            trade_id TEXT PRIMARY KEY, asset TEXT, status TEXT, direction TEXT,
            perp_ticker TEXT, q_ticker TEXT,
            perp_lots INTEGER, q_lots INTEGER,
            perp_pv REAL, q_pv REAL,
            perp_entry_pts REAL, q_entry_pts REAL,
            perp_exit_pts REAL, q_exit_pts REAL,
            entry_carry_bp REAL, exit_carry_bp REAL,
            commission_rub REAL, price_pnl_rub REAL,
            funding_rub REAL DEFAULT 0, net_pnl_rub REAL,
            entry_ts TEXT, exit_ts TEXT, exit_reason TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS funding_ledger (
            asset TEXT, date_trade TEXT, swaprate_pts REAL,
            perp_lots INTEGER, rub REAL,
            PRIMARY KEY (asset, date_trade)
        );
        CREATE TABLE IF NOT EXISTS daily_risk (date_msk TEXT PRIMARY KEY,
            actions_today INTEGER DEFAULT 0, paused INTEGER DEFAULT 0, pause_reason TEXT);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, asset TEXT, kind TEXT, message TEXT);
        """)
        self.con.commit()

    def open_trade(self, asset: str) -> Optional[sqlite3.Row]:
        return self.con.execute("SELECT * FROM carry_trades WHERE asset=? AND status='OPEN' "
                                "ORDER BY entry_ts DESC LIMIT 1", (asset,)).fetchone()

    def upsert_trade(self, t: dict):
        cols = ",".join(t.keys()); ph = ",".join("?" * len(t))
        upd = ",".join(f"{k}=excluded.{k}" for k in t if k != "trade_id")
        self.con.execute(f"INSERT INTO carry_trades({cols}) VALUES({ph}) "
                         f"ON CONFLICT(trade_id) DO UPDATE SET {upd}", list(t.values()))
        self.con.commit()

    def add_funding(self, asset: str, date_trade: str, swaprate: float,
                    perp_lots: int, rub: float, trade_id: Optional[str] = None) -> bool:
        """True if inserted (new date), False if already accrued.
        When trade_id is given, the amount is also attributed to that trade."""
        try:
            self.con.execute("INSERT INTO funding_ledger VALUES(?,?,?,?,?)",
                             (asset, date_trade, swaprate, perp_lots, rub))
        except sqlite3.IntegrityError:
            return False
        if trade_id:
            self.con.execute(
                "UPDATE carry_trades SET funding_rub=COALESCE(funding_rub,0)+?, "
                "updated_at=? WHERE trade_id=?",
                (rub, datetime.now(tz=timezone.utc).isoformat(), trade_id))
        self.con.commit()
        return True

    def last_funding_date(self, asset: str) -> Optional[str]:
        r = self.con.execute("SELECT MAX(date_trade) m FROM funding_ledger WHERE asset=?",
                             (asset,)).fetchone()
        return r["m"]

    def funding_total(self) -> float:
        r = self.con.execute("SELECT COALESCE(SUM(rub),0) s FROM funding_ledger").fetchone()
        return float(r["s"])

    def event(self, asset: str, kind: str, msg: str):
        self.con.execute("INSERT INTO events(ts,asset,kind,message) VALUES(?,?,?,?)",
                         (datetime.now(tz=timezone.utc).isoformat(), asset, kind, msg))
        self.con.commit()

    def daily(self, date_msk: str) -> sqlite3.Row:
        r = self.con.execute("SELECT * FROM daily_risk WHERE date_msk=?", (date_msk,)).fetchone()
        if r is None:
            self.con.execute("INSERT INTO daily_risk(date_msk) VALUES(?)", (date_msk,))
            self.con.commit()
            r = self.con.execute("SELECT * FROM daily_risk WHERE date_msk=?", (date_msk,)).fetchone()
        return r

    def set_pause(self, date_msk: str, paused: bool, reason: str = ""):
        self.daily(date_msk)  # ensure the row exists
        self.con.execute(
            "UPDATE daily_risk SET paused=?, pause_reason=? WHERE date_msk=?",
            (1 if paused else 0, reason, date_msk))
        self.con.commit()

    def bump_actions(self, date_msk: str):
        self.con.execute("UPDATE daily_risk SET actions_today=actions_today+1 WHERE date_msk=?",
                         (date_msk,))
        self.con.commit()

    def all_closed(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM carry_trades WHERE status='CLOSED'").fetchall()

    def all_open(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM carry_trades WHERE status='OPEN'").fetchall()


# ───────────────────────── execution ─────────────────────────
def _order(broker, account_id, uid, lots, side, point_value, dry_run, logger, tag,
           dry_px: Optional[float] = None):
    """MARKET order one leg → (avg_fill_points, commission_rub, filled_lots).

    Posted lot-by-lot: the sandbox rejects multi-lot market orders on some
    futures with a bogus 30034 'Not enough balance' (single lots fill fine),
    and the order rate limit is 2/sec anyway. A slice failure after partial
    fills returns the partial count so the caller's unwind logic engages.
    """
    if dry_run:
        logger.info(f"DRY_ORDER {tag} side={side} lots={lots}")
        return dry_px, 0.0, lots
    total_rub, comm, filled = 0.0, 0.0, 0
    for i in range(lots):
        time.sleep(0.7)
        try:
            res = broker.post_order(account_id=account_id, instrument_uid=uid,
                                    quantity_lots=1, direction=side, order_type="MARKET",
                                    idempotency_key=str(uuid.uuid4()))
        except Exception as e:
            if filled == 0:
                raise
            logger.error(f"ORDER {tag} slice {i + 1}/{lots} failed after {filled} fills: {e}")
            break
        filled += res.lots_executed or 0
        total_rub += res.executed_price or 0.0
        comm += res.commission_rub or 0.0
    pts = fill_points(total_rub, filled, point_value)
    logger.info(f"ORDER {tag} side={side} lots={lots} filled={filled} "
                f"avg_pts={pts} total={total_rub} comm={comm}")
    return pts, comm, filled


def _open_construction(broker, account_id, db, logger, dry_run, *, asset, perp, front,
                       perp_px, q_px, carry_bp, notional, ts):
    perp_lots, q_lots = leg_lots(notional, perp_px, perp["pv"], q_px, front["pv"])
    # leg 1: SHORT perp (an order exception here leaves nothing open — just abort)
    try:
        pf, pc, pfl = _order(broker, account_id, perp["uid"], perp_lots, "SELL", perp["pv"],
                             dry_run, logger, f"{asset}/ENTRY/perp", dry_px=perp_px)
    except Exception as e:
        logger.error(f"ENTRY_LEG1_ERROR {asset}: {e}")
        db.event(asset, "ENTRY_ABORT", f"perp order error: {str(e)[:200]}")
        return None
    if not dry_run and pfl < perp_lots:
        logger.error(f"ENTRY_LEG1_FAIL {asset} perp filled={pfl}/{perp_lots}; flattening")
        if pfl > 0:
            _order(broker, account_id, perp["uid"], pfl, "BUY", perp["pv"],
                   dry_run, logger, f"{asset}/UNWIND/perp")
        db.event(asset, "ENTRY_ABORT", f"perp partial {pfl}/{perp_lots}")
        return None
    # leg 2: LONG quarterly — any failure (partial OR exception) must unwind leg 1,
    # otherwise a one-legged short survives until the reconciliation halt
    try:
        qf, qc, qfl = _order(broker, account_id, front["uid"], q_lots, "BUY", front["pv"],
                             dry_run, logger, f"{asset}/ENTRY/q", dry_px=q_px)
    except Exception as e:
        logger.error(f"ENTRY_LEG2_ERROR {asset}: {e}; flattening perp leg")
        _order(broker, account_id, perp["uid"], perp_lots, "BUY", perp["pv"],
               dry_run, logger, f"{asset}/UNWIND/perp")
        db.event(asset, "ENTRY_ABORT", f"q order error: {str(e)[:200]}")
        return None
    if not dry_run and qfl < q_lots:
        logger.error(f"ENTRY_LEG2_FAIL {asset} q filled={qfl}/{q_lots}; flattening BOTH")
        _order(broker, account_id, perp["uid"], perp_lots, "BUY", perp["pv"],
               dry_run, logger, f"{asset}/UNWIND/perp")
        if qfl > 0:
            _order(broker, account_id, front["uid"], qfl, "SELL", front["pv"],
                   dry_run, logger, f"{asset}/UNWIND/q")
        db.event(asset, "ENTRY_ABORT", f"q partial {qfl}/{q_lots}")
        return None

    now = datetime.now(tz=timezone.utc).isoformat()
    t = dict(trade_id=f"sbcarry:{asset}:{ts}", asset=asset, status="OPEN",
             direction="NEUTRAL",
             perp_ticker=perp["ticker"], q_ticker=front["ticker"],
             perp_lots=perp_lots, q_lots=q_lots, perp_pv=perp["pv"], q_pv=front["pv"],
             perp_entry_pts=pf if pf is not None else perp_px,
             q_entry_pts=qf if qf is not None else q_px,
             perp_exit_pts=None, q_exit_pts=None,
             entry_carry_bp=round(carry_bp, 3), exit_carry_bp=None,
             commission_rub=(pc or 0) + (qc or 0), price_pnl_rub=None,
             funding_rub=0.0, net_pnl_rub=None,
             entry_ts=str(ts), exit_ts=None, exit_reason=None,
             created_at=now, updated_at=now)
    db.upsert_trade(t)
    logger.info(f"CARRY_ENTRY {asset} carry={carry_bp:.2f}bp/d SHORT {perp_lots}x{perp['ticker']} "
                f"@{t['perp_entry_pts']} LONG {q_lots}x{front['ticker']} @{t['q_entry_pts']}")
    return t


def _verify_flat(broker, account_id, uids, dry_run) -> tuple[bool, dict]:
    """Read the ACCOUNT and report whether every uid is flat.

    An order response says what the exchange did with one request; only a
    position read says what the account holds. Closing on the former is how a
    trade got marked CLOSED with a zero-lot fill while both legs were still on.
    """
    if dry_run:
        return True, {}
    held = {}
    for p in broker.get_positions(account_id):
        if p.instrument_uid in uids and int(p.balance) != 0:
            held[p.instrument_uid] = int(p.balance)
    return (not held), held


def _close_construction(broker, account_id, db, logger, dry_run, *, t, perp_uid, q_uid,
                        perp_px, q_px, carry_bp, ts, reason):
    try:
        pf, pc, pfl = _order(broker, account_id, perp_uid, t["perp_lots"], "BUY", t["perp_pv"],
                             dry_run, logger, f"{t['asset']}/EXIT/perp", dry_px=perp_px)
    except Exception as e:
        # nothing changed — still fully hedged; retry the exit next cycle
        logger.error(f"EXIT_LEG1_ERROR {t['asset']}: {e}; exit postponed")
        db.event(t["asset"], "EXIT_RETRY", f"perp order error: {str(e)[:200]}")
        return None
    try:
        qf, qc, qfl = _order(broker, account_id, q_uid, t["q_lots"], "SELL", t["q_pv"],
                             dry_run, logger, f"{t['asset']}/EXIT/q", dry_px=q_px)
    except Exception:
        logger.exception(f"EXIT_LEG2_ERROR {t['asset']}; retrying q leg once")
        time.sleep(2.0)
        try:
            qf, qc, qfl = _order(broker, account_id, q_uid, t["q_lots"], "SELL", t["q_pv"],
                                 dry_run, logger, f"{t['asset']}/EXIT/q-retry", dry_px=q_px)
        except Exception as e:
            # perp is closed, quarterly still long: reconcile will halt this asset
            logger.critical(f"EXIT_ONELEG {t['asset']}: q leg unsold ({e}); "
                            f"trade left OPEN for reconcile halt")
            db.event(t["asset"], "EXIT_ONELEG", f"q order error: {str(e)[:200]}")
            return None
    # ── Invariant: CLOSED requires the BROKER to confirm both legs are flat ──
    # Previously this function substituted the bar price when a leg did not fill
    # (`pf if pf is not None else perp_px`) and then wrote status=CLOSED
    # unconditionally, so a zero-lot exit produced a closed, profitable-looking
    # trade with both legs still on the account.
    flat, held = _verify_flat(broker, account_id, {perp_uid, q_uid}, dry_run)
    if not flat:
        logger.critical(
            f"EXIT_NOT_FLAT {t['asset']} reason={reason} broker still holds {held} "
            f"(perp filled={pfl}/{t['perp_lots']}, q filled={qfl}/{t['q_lots']}); "
            f"trade stays OPEN, no PnL booked, entries blocked until resolved")
        db.event(t["asset"], "EXIT_INCOMPLETE",
                 f"reason={reason} held={held} perp={pfl}/{t['perp_lots']} "
                 f"q={qfl}/{t['q_lots']}")
        db.set_pause(_today_msk(), True, f"exit_incomplete {held}")
        return None

    if pf is None or qf is None:
        # Flat, but we never learned a fill price — cannot compute honest PnL.
        logger.error(
            f"EXIT_NO_FILL_PRICE {t['asset']}: legs are flat but a fill price is "
            f"missing (perp={pf}, q={qf}); refusing to invent one")
        db.event(t["asset"], "EXIT_NO_FILL_PRICE", f"perp={pf} q={qf}")
        db.set_pause(_today_msk(), True, "exit without a fill price")
        return None

    perp_exit = pf
    q_exit = qf
    # SHORT perp + LONG quarterly
    perp_pnl = (t["perp_entry_pts"] - perp_exit) * t["perp_pv"] * t["perp_lots"]
    q_pnl = (q_exit - t["q_entry_pts"]) * t["q_pv"] * t["q_lots"]
    commission = (t["commission_rub"] or 0) + (pc or 0) + (qc or 0)
    now = datetime.now(tz=timezone.utc).isoformat()
    price_pnl = round(perp_pnl + q_pnl - commission, 2)
    funding = float(t.get("funding_rub") or 0)
    upd = dict(t)
    upd.update(status="CLOSED", perp_exit_pts=perp_exit, q_exit_pts=q_exit,
               exit_carry_bp=round(carry_bp, 3), commission_rub=commission,
               price_pnl_rub=price_pnl, net_pnl_rub=round(price_pnl + funding, 2),
               exit_ts=str(ts), exit_reason=reason, updated_at=now)
    db.upsert_trade(upd)
    logger.info(f"CARRY_EXIT {t['asset']} reason={reason} carry={carry_bp:.2f}bp/d "
                f"price_pnl={price_pnl:.1f} funding={funding:.1f} "
                f"net={upd['net_pnl_rub']:.1f} comm={commission:.2f}")
    return upd


# ───────────────────────── reconciliation ─────────────────────────
def _reconcile(broker, account_id, open_t, perp_uid, q_uid):
    exp = {perp_uid: 0, q_uid: 0}
    if open_t is not None and str(open_t["status"]) == "OPEN":
        exp[perp_uid] = -int(open_t["perp_lots"])   # short
        exp[q_uid] = int(open_t["q_lots"])          # long
    actual = {perp_uid: 0, q_uid: 0}
    for p in broker.get_positions(account_id):
        if p.instrument_uid in actual:
            actual[p.instrument_uid] = int(p.balance)
    mism = [(u, exp[u], actual[u]) for u in exp if exp[u] != actual[u]]
    if mism:
        return False, "; ".join(f"uid={u[:8]} exp={e} act={a}" for u, e, a in mism)
    return True, "OK"


# ───────────────────────── instrument resolution ─────────────────────────
def resolve_legs(legs_spec: str, logger) -> dict:
    """{asset: {perp: {...}, quarterlies: [{...}]}} with point values from the API."""
    from src.tbank.client import get_tbank_client
    from src.tbank.settings import load_tbank_settings
    from src.tbank.money import quotation_to_float as q2f

    spec = [tok.strip().split(":") for tok in legs_spec.split(",") if tok.strip()]
    out = {}
    with get_tbank_client(load_tbank_settings(env="prod")) as c:
        futs = c.instruments.futures().instruments
        by_ticker = {f.ticker: f for f in futs}
        for perp_ticker, series in spec:
            perp_f = by_ticker.get(perp_ticker)
            if perp_f is None:
                raise SystemExit(f"perp {perp_ticker} not found in API")

            def _details(f):
                from t_tech.invest import InstrumentIdType
                d = c.instruments.future_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_UID, id=f.uid).instrument
                step = q2f(d.min_price_increment) or 1.0
                step_rub = q2f(d.min_price_increment_amount) or step
                expiry = d.last_trade_date
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                return {"ticker": f.ticker, "uid": f.uid, "pv": step_rub / step,
                        "expiry": expiry}

            perp = _details(perp_f)
            quarterlies = []
            for f in futs:
                if f.basic_asset == perp_f.basic_asset and f.ticker != perp_ticker \
                        and f.ticker[:len(series)] == series:
                    quarterlies.append(_details(f))
            if not quarterlies:
                raise SystemExit(f"no quarterlies of series {series} for {perp_ticker}")
            out[perp_ticker] = {"perp": perp, "quarterlies": quarterlies}
            logger.info(f"LEGS {perp_ticker}: perp pv={perp['pv']} + "
                        f"{len(quarterlies)} quarterlies (series {series})")
    return out


# ───────────────────────── per-asset cycle ─────────────────────────
def _process_asset(args, broker, account_id, db, logger, asset, legs, now_utc, dry_run):
    perp = legs["perp"]
    try:
        perp_px = iss_last_price(perp["ticker"])
        funding = iss_funding_history(perp["ticker"], days=args.funding_ma_days * 2)
    except Exception as e:
        return {"asset": asset, "status": "ISS_ERROR", "detail": str(e)[:120]}
    front = pick_front(legs["quarterlies"], now_utc, args.min_front_dte)
    if front is None:
        return {"asset": asset, "status": "NO_FRONT"}
    try:
        q_px = iss_last_price(front["ticker"])
    except Exception as e:
        return {"asset": asset, "status": "ISS_ERROR", "detail": str(e)[:120]}
    if not perp_px or not q_px or not funding:
        return {"asset": asset, "status": "NO_MARKET_DATA"}

    fma = funding_ma_bp([f for _, f in funding], perp_px, args.funding_ma_days)
    if fma is None:
        return {"asset": asset, "status": "NO_FUNDING_HISTORY"}
    dte = (front["expiry"] - now_utc).days
    carry = expected_carry_bp(fma, perp_px, q_px, dte)
    cost_gate = required_daily_carry(
        args.roundtrip_cost_bps, args.expected_hold_days, args.min_cost_cover_multiple
    )
    entry_gate = max(args.entry_carry_bp, cost_gate)

    open_t = db.open_trade(asset)
    open_t = dict(open_t) if open_t is not None else None

    if not dry_run:
        ok, detail = _reconcile(broker, account_id, open_t, perp["uid"], front["uid"] if
                                open_t is None or open_t["q_ticker"] == front["ticker"]
                                else _uid_by_ticker(legs, open_t["q_ticker"]))
        if not ok:
            logger.error(f"RECONCILE_FAIL {asset} {detail}")
            db.event(asset, "RECONCILE_FAIL", detail)
            return {"asset": asset, "status": "RECONCILE_FAILED", "detail": detail,
                    "carry_bp": round(carry, 2), "has_open": open_t is not None}

    # daily funding accrual for an open SHORT perp (once per ISS trade date)
    if open_t is not None:
        last = db.last_funding_date(asset)
        accrued = False
        for date_trade, swap in funding:
            if date_trade <= (open_t["entry_ts"] or "")[:10]:
                continue  # entered later that day — no funding for entry date
            if last is not None and date_trade <= last:
                continue
            rub = funding_rub(swap, open_t["perp_lots"], open_t["perp_pv"])
            if db.add_funding(asset, date_trade, swap, open_t["perp_lots"], rub,
                              trade_id=open_t["trade_id"]):
                accrued = True
                logger.info(f"FUNDING {asset} {date_trade} swap={swap}pts -> {rub:+.1f} RUB")
        if accrued:
            open_t = dict(db.open_trade(asset))  # refresh funding_rub before a close

    date_msk = _today_msk(now_utc)
    daily = db.daily(date_msk)
    ts = now_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    if open_t is None:
        if not daily["paused"] and daily["actions_today"] < args.max_actions_per_day \
                and carry >= entry_gate:
            t = _open_construction(broker, account_id, db, logger, dry_run, asset=asset,
                                   perp=perp, front=front, perp_px=perp_px, q_px=q_px,
                                   carry_bp=carry, notional=args.notional, ts=ts)
            if t is not None:
                db.bump_actions(date_msk)
                open_t = t
    else:
        held_front_uid = _uid_by_ticker(legs, open_t["q_ticker"])
        held_dte = None
        for q in legs["quarterlies"]:
            if q["ticker"] == open_t["q_ticker"]:
                held_dte = (q["expiry"] - now_utc).days

        # The exit decision must be made on the contract we ACTUALLY HOLD.
        # `carry` above is computed against the current front, which after a roll
        # is a different instrument with a different basis and DTE — so a sign
        # change in a contract we do not own could close the one we do.
        q_held_px = iss_last_price(open_t["q_ticker"]) or q_px
        if held_dte is not None:
            held_carry = expected_carry_bp(fma, perp_px, q_held_px, held_dte)
        else:
            held_carry = carry
            logger.warning(f"HELD_DTE_UNKNOWN {asset} {open_t['q_ticker']}: "
                           f"falling back to front carry for the exit decision")

        reason = None
        if held_carry <= args.exit_carry_bp:
            reason = "CARRY_FLIP"
        elif held_dte is not None and held_dte < args.roll_dte:
            reason = "ROLL"
        if reason and daily["actions_today"] < args.max_actions_per_day:
            _close_construction(broker, account_id, db, logger, dry_run, t=open_t,
                                perp_uid=perp["uid"], q_uid=held_front_uid,
                                perp_px=perp_px, q_px=q_held_px, carry_bp=held_carry,
                                ts=ts, reason=reason)
            db.bump_actions(date_msk)
            open_t = None
            # ROLL re-enters immediately on the new front (next cycle would too,
            # but do it now to avoid an unhedged gap in carry accrual)
            if reason == "ROLL" and carry >= entry_gate \
                    and db.daily(date_msk)["actions_today"] < args.max_actions_per_day:
                t = _open_construction(broker, account_id, db, logger, dry_run, asset=asset,
                                       perp=perp, front=front, perp_px=perp_px, q_px=q_px,
                                       carry_bp=carry, notional=args.notional, ts=ts)
                if t is not None:
                    db.bump_actions(date_msk)
                    open_t = t

    return {"asset": asset, "status": "OK", "carry_bp": round(carry, 2),
            "entry_gate_bp": round(entry_gate, 2),
            "funding_ma_bp": round(fma, 2), "dte": dte, "front": front["ticker"],
            "has_open": open_t is not None}


def _uid_by_ticker(legs: dict, ticker: str) -> Optional[str]:
    for q in legs["quarterlies"]:
        if q["ticker"] == ticker:
            return q["uid"]
    return legs["perp"]["uid"] if legs["perp"]["ticker"] == ticker else None


# ───────────────────────── contractual cashflows we cannot see ───────────────
#: Perpetuals on a PRICE index carry a dividend adjustment in addition to
#: funding. MOEX credits it to longs and DEBITS it from shorts, and this
#: construction is short the perpetual — so it is an obligation, not income.
#: Verified 2026-09: IMOEXF tracks the IMOEX price index to within ~5 bps
#: (2024-01..2026-09: perp -28.0% vs IMOEX -28.0%, while total-return MCFTRR was
#: -11.7%), and the ISS history endpoint used here returns no such column.
#: Omitting it inflates computed carry by roughly the index dividend yield:
#: 3.16 bp/day over 2023-2026 and 4.05 bp/day in 2026, against an entry gate of
#: 2.00 bp/day. On the 2026 regime that turns a claimed +2.51 into about -1.54.
INDEX_PERPETUALS_WITH_DIVIDEND_ADJUSTMENT = {"IMOEXF"}


def _missing_cashflows(legs_spec: str) -> list[str]:
    """Contractual cashflows known to be unobservable for the configured legs."""
    missing = []
    for tok in legs_spec.split(","):
        perp = tok.strip().split(":")[0].strip()
        if perp in INDEX_PERPETUALS_WITH_DIVIDEND_ADJUSTMENT:
            missing.append(f"{perp}:INDEX_DIV")
    return missing


# ───────────────────────── status ─────────────────────────
def _write_status(args, db, results, market_open, session, fetch_status, account_id, dry_run):
    closed = db.all_closed()
    price_pnl = sum((r["price_pnl_rub"] or 0) for r in closed)
    comm = sum((r["commission_rub"] or 0) for r in closed)
    funding = db.funding_total()
    status = {
        "strategy": "perp_funding_carry_sandbox", "contour": "sandbox", "dry_run": dry_run,
        "account_id": account_id, "pairs": args.legs,
        "params": {"notional": args.notional, "funding_ma_days": args.funding_ma_days,
                   "entry_carry_bp": args.entry_carry_bp, "exit_carry_bp": args.exit_carry_bp,
                   "roll_dte": args.roll_dte, "roundtrip_cost_bps": args.roundtrip_cost_bps,
                   "expected_hold_days": args.expected_hold_days,
                   "min_cost_cover_multiple": args.min_cost_cover_multiple},
        "market_open": market_open, "session": session, "fetch_status": fetch_status,
        "per_asset": results,
        "open_trades_total": len(db.all_open()), "closed_trades_total": len(closed),
        # ── REAL vs MODEL ────────────────────────────────────────────────────
        # Only fills and commissions are broker-confirmed. Funding is OUR figure,
        # derived from ISS SWAPRATE; the sandbox does not settle it to us. It was
        # previously published as `funding_accrued_rub_REAL` and summed into
        # `net_pnl_rub_REAL`, which is the same mislabelling that produced a false
        # ADVANCE verdict once before.
        "price_pnl_rub_REAL": round(price_pnl, 1),
        "commission_rub_REAL": round(comm, 1),
        "net_pnl_rub_REAL": round(price_pnl, 1),
        "funding_accrued_rub_MODEL": round(funding, 1),
        "net_pnl_rub_WITH_MODEL": round(price_pnl + funding, 1),
        # Known contractual cashflows this ledger cannot observe. For an index
        # perpetual MOEX debits a dividend adjustment (IndexDiv) from the SHORT
        # leg, and the ISS history endpoint used here exposes SWAPRATE only. Any
        # IMOEXF PnL below is therefore INCOMPLETE, not merely approximate.
        "missing_cashflows": _missing_cashflows(args.legs),
        "pnl_is_complete": not _missing_cashflows(args.legs),
        "pid": os.getpid(),
        "updated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    Path(args.status_file).parent.mkdir(parents=True, exist_ok=True)
    with open(args.status_file, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, default=str)


# ───────────────────────── main ─────────────────────────
def _resolve_account(args, broker, logger) -> str:
    if args.account_id:
        return args.account_id
    env_id = os.getenv(args.account_id_env, "")
    if env_id:
        return env_id
    accts = broker.get_accounts()
    if accts:
        return accts[0]["id"]
    raise RuntimeError("No sandbox account found; run scripts/sandbox_account_setup.py")


def main():
    args = _parse_args()
    load_dotenv()
    logger = _setup_logging(args.log_file)
    dry_run = args.dry_run

    logger.info("=" * 60)
    logger.info("Perp Funding-Carry SANDBOX Trader — SANDBOX contour (virtual money)")
    logger.info(f"  legs={args.legs} notional={args.notional} dry_run={dry_run}")
    logger.info(f"  funding_ma={args.funding_ma_days}d entry>{args.entry_carry_bp}bp "
                f"exit<{args.exit_carry_bp}bp roll_dte={args.roll_dte} "
                f"cost_gate={required_daily_carry(args.roundtrip_cost_bps, args.expected_hold_days, args.min_cost_cover_multiple):.2f}bp/day")
    logger.info("=" * 60)

    # The entry gate divides the round trip by --expected-hold-days, but the hold
    # is bounded by --min-front-dte and --roll-dte. If those contradict, the gate
    # understates the requirement and the service happily trades below its own
    # break-even. Refuse to start rather than discover it in a report.
    from src.carry import front_selection_is_consistent
    ok, detail = front_selection_is_consistent(
        min_front_dte=args.min_front_dte,
        roll_dte=args.roll_dte,
        expected_hold_days=args.expected_hold_days,
    )
    if not ok:
        raise SystemExit(f"inconsistent carry horizon: {detail}")
    logger.info(f"  horizon check: {detail}")

    missing = _missing_cashflows(args.legs)
    if missing:
        logger.warning(
            f"INCOMPLETE_PNL: these legs carry contractual cashflows this daemon "
            f"cannot observe: {missing}. Reported PnL is INCOMPLETE — for an index "
            f"perpetual the exchange debits a dividend adjustment from the SHORT "
            f"leg, worth roughly the index dividend yield (~3-4 bp/day), which is "
            f"larger than the entry gate. Do not treat these numbers as an edge.")

    if os.getenv("TINVEST_LIVE_TRADING_TOKEN"):
        raise SystemExit("live trading token present — refusing to run sandbox executor")
    if not dry_run:
        if not os.getenv("SANDBOX_TOKEN"):
            raise SystemExit("SANDBOX_TOKEN missing — refusing to place sandbox orders.")
        if os.getenv(args.trading_enabled_env, "false").lower() != "true":
            raise SystemExit(f"{args.trading_enabled_env} != true — refusing to trade.")

    legs = resolve_legs(args.legs, logger)
    db = CarryDB(args.state_db)

    market_config = None
    if not args.ignore_market_hours:
        try:
            from src.market.market_hours import load_market_hours_config
            market_config = load_market_hours_config(args.market_hours_config)
        except Exception as e:
            logger.warning(f"market hours config load failed: {e}; running without gate")

    def cycle(broker, account_id):
        now_utc = datetime.now(tz=timezone.utc)
        session, market_open = "unknown", True
        if market_config:
            from src.market.market_hours import is_session_open, get_session_name
            session = get_session_name(now_utc, market_config)
            market_open = is_session_open(now_utc, market_config)
        if not market_open and not args.ignore_market_hours:
            _write_status(args, db, [], market_open, session, "MARKET_CLOSED",
                          account_id, dry_run)
            return
        results = []
        for asset, l in legs.items():
            try:
                results.append(_process_asset(args, broker, account_id, db, logger,
                                              asset, l, now_utc, dry_run))
            except Exception as e:
                logger.exception(f"CYCLE_ERROR asset={asset}")
                db.event(asset, "CYCLE_ERROR", str(e)[:300])
                results.append({"asset": asset, "status": "ERROR", "detail": str(e)[:120]})
        fetch = "OK" if all(r.get("status") not in ("ISS_ERROR", "NO_MARKET_DATA")
                            for r in results) else "API_ERROR"
        _write_status(args, db, results, market_open, session, fetch, account_id, dry_run)
        for r in results:
            logger.info(f"CYCLE {r}")

    def run_loop(broker, account_id):
        cycle(broker, account_id)
        while not args.once:
            time.sleep(args.poll_interval_seconds)
            cycle(broker, account_id)

    if dry_run:
        run_loop(None, None)
    else:
        with get_sandbox_broker() as broker:
            account_id = _resolve_account(args, broker, logger)
            logger.info(f"SANDBOX account: {account_id}")
            run_loop(broker, account_id)


if __name__ == "__main__":
    main()
