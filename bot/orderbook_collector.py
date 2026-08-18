#!/usr/bin/env python3
"""Order-flow orderbook-depth + tick collector (Phase 2 of the order-flow lane).

Two venues, one snapshot stream, persisted to S3 + DynamoDB (`ORDERBOOK#`):

1) **IBKR futures (MES/MNQ)** — L2 `reqMktDepth` is NOT entitled on paper
   (Error 354 "not subscribed", verified 2026-08-18; L2 depth is a separate
   paid package). Honest fallback = **L1 top-of-book** (bid/ask/size/last via
   `reqMktData`), recorded with `depth='L1'` and the entitlement gap flagged.
2) **Robinhood equities (15 small-ticket names)** — **L2 price book** via
   `get_equity_price_book` (`asks[]`/`bids[]` level arrays, best-first) +
   **L1 top-of-book** via `get_equity_quotes`. Polled over the MCP HTTP
   gateway (max 4 symbols per price-book call).

Persistence (never discard paid data):
  - S3  `orderbook/<sym>/<date>.jsonl` — one JSON line per snapshot, flushed
     every FLUSH_S seconds (batched so storage stays sane).
  - DynamoDB `ORDERBOOK#<sym>` sk='latest' — hot overwrite, TTL'd so a dead
     collector self-cleans.

This is the *equities + depth* half of the order-flow universe; the futures
trade-tick/quote half is already `bot/tick_recorder.py` (bid/ask/last/size for
the CME/CBOT L1-live symbols). Together they cover "trade ticks + bid/ask +
orderbook depth" for the order-flow universe.

READ-ONLY on the trading side: `reqMktData` + RH read tools only. No orders.
clientId=80 (distinct). RTH-gated (equities 09:30-16:00 ET; futures RTH kept
for consistency).
"""
import os
import sys
import math
import time
import json
import datetime as dt
from zoneinfo import ZoneInfo
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from dotenv import load_dotenv
from ib_insync import IB, Future

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
# --- SSM-first secrets (infra/secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.secrets import bootstrap as _sb
_sb()

from bot.futures_contracts import SYMBOLS, resolve_front
from hardening.rh_client import RHClient

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
CLIENT_ID = 80                       # distinct from all other clientIds

SNAP_S = float(os.getenv('ORDERBOOK_SNAP_S', '5'))   # snapshot interval (both venues)
FLUSH_S = float(os.getenv('ORDERBOOK_FLUSH_S', '10'))  # S3 flush batch interval
TTL_S = int(os.getenv('ORDERBOOK_TTL_S', '86400'))    # 1 day hot-item TTL
RH_ENABLED = os.getenv('RH_ENABLED', 'true').lower() == 'true'
IBKR_ENABLED = os.getenv('IBKR_ENABLED', 'true').lower() == 'true'

NY = ZoneInfo('America/New_York')
RTH_OPEN = dt.time(9, 30)
RTH_CLOSE = dt.time(16, 0)

# IBKR futures sleeve (L2 not entitled -> L1 top-of-book)
IBKR_SYMBOLS = ['MES', 'MNQ']

# Robinhood small-ticket liquid universe (~15 names, whole-share-tradeable at
# ~$700; from the laptop directive: F AAL T KHC PFE WBD KVUE DOW SNAP NIO etc.)
SMALL_TICKET_UNIVERSE = [
    'F', 'AAL', 'T', 'KHC', 'PFE', 'WBD', 'KVUE', 'DOW', 'SNAP', 'NIO',
    'INTC', 'SOFI', 'PARA', 'HPE', 'CCL',
]

EXCHANGE = {sym: ex for sym, ex in SYMBOLS}


def log(msg):
    print(f"[{dt.datetime.now(NY).isoformat(timespec='seconds')}] {msg}", flush=True)


def _in_rth(now=None):
    now = now or dt.datetime.now(NY)
    return (now.weekday() < 5 and RTH_OPEN <= now.time() < RTH_CLOSE)


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


# ===== IBKR L1 snapshot =====
def snapshot_ibkr(tickers):
    """Build per-symbol L1 top-of-book snapshots from ib_insync Tickers.

    L2 depth is not entitled on paper (Error 354), so we capture the best
    bid/ask with size + last trade — the honest 'depth' available — and mark
    depth='L1'. Returns {sym: snapshot_dict}.
    """
    out = {}
    for t in tickers:
        sym = t.contract.symbol
        if sym not in IBKR_SYMBOLS:
            continue
        bid, ask, last = _num(t.bid), _num(t.ask), _num(t.last)
        if bid is None and ask is None and last is None:
            continue
        out[sym] = {
            'venue': 'ibkr', 'depth': 'L1',
            'bid': bid, 'ask': ask, 'last': last,
            'bidSize': _num(t.bidSize), 'askSize': _num(t.askSize),
            'lastSize': _num(t.lastSize), 'volume': _num(t.volume),
            'l2_entitled': False,   # honest flag: L2 depth is a separate paid package
        }
    return out


# ===== Robinhood L2 + L1 snapshot =====
def snapshot_rh(client):
    """Robinhood L2 price book + L1 quotes for the small-ticket universe.

    Returns {sym: snapshot_dict}. Missing symbols (market closed / unresolved)
    are surfaced via the 'error' key, never silently dropped.
    """
    out = {}
    # L2 price book (max 4 symbols/call)
    for chunk in _chunks(SMALL_TICKET_UNIVERSE, 4):
        try:
            raw = client._tool('get_equity_price_book', symbols=chunk)
        except Exception as e:
            log(f"  RH get_equity_price_book failed for {chunk}: {e!r}")
            continue
        books = ((raw.get('data') or {}).get('books') or [])
        for b in books:
            sym = b.get('symbol')
            out[sym] = {
                'venue': 'rh', 'depth': 'L2',
                'bids': b.get('bids') or [],
                'asks': b.get('asks') or [],
                'updated_at': b.get('updated_at'),
            }
        for err in ((raw.get('data') or {}).get('errors') or []):
            sym = err.get('symbol') if isinstance(err, dict) else str(err)
            out.setdefault(sym, {})['error'] = err if isinstance(err, dict) else str(err)
    # L1 top-of-book quotes (fills bid/ask/last for symbols; also the fallback
    # when the market is closed and the price book returns empty levels)
    try:
        quotes = client.get_quotes(SMALL_TICKET_UNIVERSE)
    except Exception as e:
        log(f"  RH get_equity_quotes failed: {e!r}")
        quotes = []
    for r in quotes:
        q = r.get('quote') or {}
        sym = q.get('symbol') or r.get('symbol')
        if not sym:
            continue
        s = out.setdefault(sym, {'venue': 'rh', 'depth': 'L2'})
        s['bid'] = _num(q.get('bid_price'))
        s['ask'] = _num(q.get('ask_price'))
        s['last'] = _num(q.get('last_trade_price'))
    return out


# ===== writer =====
class OrderbookWriter:
    def __init__(self):
        self.s3 = boto3.client('s3', region_name=AWS_REGION)
        self.table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)

    def flush_s3(self, buffer):
        now = dt.datetime.now(dt.timezone.utc)  # S3 key date stays UTC (storage convention)
        date = now.strftime('%Y-%m-%d')
        ts = int(now.timestamp())
        for sym, snaps in list(buffer.items()):
            if not snaps:
                continue
            lines = '\n'.join(json.dumps(s, default=str) for s in snaps) + '\n'
            key = f'orderbook/{sym}/{date}/{ts}.jsonl'
            self.s3.put_object(Bucket=S3_BUCKET, Key=key, Body=lines)
            buffer[sym] = []

    def flush_hot(self, snapshots):
        now = int(time.time())
        for sym, snap in snapshots.items():
            item = {'pk': f'ORDERBOOK#{sym}', 'sk': 'latest',
                    'ts': now, 'ttl': now + TTL_S}
            for k in ('venue', 'depth', 'bid', 'ask', 'last', 'bidSize', 'askSize',
                      'lastSize', 'volume', 'l2_entitled', 'updated_at', 'error'):
                if snap.get(k) is not None:
                    item[k] = str(snap[k])
            if snap.get('bids') is not None:
                item['bids'] = json.dumps(snap['bids'])
            if snap.get('asks') is not None:
                item['asks'] = json.dumps(snap['asks'])
            self.table.put_item(Item=item)


def run_session():
    ib = IB()
    tickers = {}
    rh = None
    if IBKR_ENABLED:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=15, readonly=True)
        ib.reqMarketDataType(1)
        log(f"IBKR connected clientId={CLIENT_ID} accounts={ib.managedAccounts()} (READ-ONLY)")
        for sym in IBKR_SYMBOLS:
            con = resolve_front(ib, sym, EXCHANGE[sym])
            if con is None:
                log(f"  SKIP {sym} — no contract")
                continue
            tickers[sym] = ib.reqMktData(con, '', False, False)
            log(f"  subscribed {sym} {con.localSymbol} (L1 top-of-book; L2 not entitled)")
    if RH_ENABLED:
        try:
            rh = RHClient()
            log("Robinhood client ready (L2 price book + L1 quotes)")
        except Exception as e:
            log(f"Robinhood client failed: {e!r} — RH side disabled this run")
            rh = None

    writer = OrderbookWriter()
    buffer = defaultdict(list)
    in_rth = _in_rth()
    log(f"RTH state at start: {'OPEN' if in_rth else 'CLOSED'} "
        f"(snap {SNAP_S}s, flush {FLUSH_S}s)")
    last_flush = time.time()
    try:
        while True:
            ib.sleep(min(SNAP_S, FLUSH_S) if IBKR_ENABLED else SNAP_S)
            now = time.time()
            now_in_rth = _in_rth()
            if now_in_rth != in_rth:
                in_rth = now_in_rth
                log(f"RTH -> {'OPEN (recording)' if in_rth else 'CLOSED (idle)'}")

            snapshots = {}
            if in_rth:
                if IBKR_ENABLED:
                    # pendingTickers gives the freshest L1; fall back to cached
                    # tickers if no new update arrived this cycle.
                    for t in getattr(ib, 'pendingTickers', lambda: [])():
                        pass  # drain so cached tickers hold latest values
                    snapshots.update(snapshot_ibkr(list(tickers.values())))
                if rh is not None:
                    snapshots.update(snapshot_rh(rh))

            if snapshots:
                writer.flush_hot(snapshots)
                for sym, s in snapshots.items():
                    s['ts'] = now
                    buffer[sym].append(s)

            if now - last_flush >= FLUSH_S:
                writer.flush_s3(buffer)
                last_flush = now
    finally:
        if IBKR_ENABLED:
            ib.disconnect()


def main():
    while True:
        try:
            run_session()
        except KeyboardInterrupt:
            log("stopped")
            break
        except Exception as e:
            log(f"session error: {e!r} — reconnecting in 10s")
            time.sleep(10)


if __name__ == '__main__':
    main()
