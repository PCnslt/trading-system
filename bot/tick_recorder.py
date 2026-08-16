#!/usr/bin/env python3
"""Futures L1 tick recorder — persistent service (systemd), clientId=74.

Streams IBKR L1 (bid/ask/last/size) for the 23 CME/CBOT L1-live symbols
(`data/symbol_registry.py::L1_LIVE`) during RTH (09:30-16:00 ET Mon-Fri),
maximizing the CME/CBOT real-time subscription.

Capture:       EVENT-DRIVEN — `ib.pendingTickersEvent` fires on EVERY L1 update
               (bid/ask/last/size/volume); each tick is stamped with a
               sub-second `time.time()` float. No sampling loss at 5s — the 5s
               is only the S3 write-batch interval.
Writes (cold): S3  futures-ticks/<sym>/<date>/<ts>.jsonl — one JSONL line per
               tick, flushed every TICK_FLUSH_S seconds (default 5s) so we
               batch instead of creating per-tick objects (storage stays sane).
Writes (hot):  DynamoDB QUOTE#<sym> (sk='latest') — bid/ask/last/size/timestamp,
               overwritten every HOT_FLUSH_S seconds (default 1s) so the
               dashboard sees second-by-second quotes; TTL 1 day so a dead
               recorder self-cleans.

READ-ONLY on the trading side: reqMktData subscriptions only. No orders, no
account writes, no RUN# markers, no POSITION writes. Shares the paper gateway
with the bots (clientId 74 vs 70/71/72) — L1 streaming is a separate pacing
bucket from reqHistoricalData, so it never starves the bots' bar requests.

Reconnects automatically across the gateway's 00:00 ET daily restart.
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
from data.symbol_registry import L1_LIVE

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
CLIENT_ID = 74                       # distinct from live.py(70)/bonds(71)/intraday(72)/backfill(73)

TICK_FLUSH_S = float(os.getenv('TICK_FLUSH_S', '5'))     # S3 COLD flush (write batching)
HOT_FLUSH_S = float(os.getenv('HOT_FLUSH_S', '1'))       # DynamoDB QUOTE# HOT flush
QUOTE_TTL_S = int(os.getenv('QUOTE_TTL_S', '86400'))   # 1 day
NY = ZoneInfo('America/New_York')
RTH_OPEN = dt.time(9, 30)
RTH_CLOSE = dt.time(16, 0)

# Config-driven stream set: defaults to symbols with LIVE L1 on paper (CME + CBOT
# listings — see `data/symbol_registry.py::L1_LIVE`). NYMEX energy / COMEX metals
# are delayed-only on paper (Error 354) and are EXCLUDED so we never record delayed
# ticks as real-time; their historical BARS are still collected by the backfill +
# daily-collect scripts. Override with a comma list to shrink (or force a subset):
#   TICK_SYMBOLS=ES,NQ,MES,MNQ
SYMS = [s.strip().upper() for s in os.getenv(
    'TICK_SYMBOLS', ','.join(sorted(L1_LIVE))).split(',') if s.strip()]
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


class TickWriter:
    def __init__(self):
        self.s3 = boto3.client('s3', region_name=AWS_REGION)
        self.table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)

    def flush_s3(self, buffer):
        """COLD path: write buffered ticks to S3 JSONL (one object per symbol), then clear."""
        now = dt.datetime.now(dt.timezone.utc)  # S3 key date stays UTC (storage convention)
        date = now.strftime('%Y-%m-%d')
        ts = int(now.timestamp())
        for sym, ticks in list(buffer.items()):
            if not ticks:
                continue
            lines = '\n'.join(json.dumps(t) for t in ticks) + '\n'
            key = f'futures-ticks/{sym}/{date}/{ts}.jsonl'
            self.s3.put_object(Bucket=S3_BUCKET, Key=key, Body=lines)
            buffer[sym] = []

    def flush_hot(self, latest):
        """HOT path: overwrite QUOTE#<sym> sk='latest' with most-recent non-None
        value per field (bid/ask/last/size/volume). Runs every HOT_FLUSH_S (~1s)
        so the dashboard sees second-by-second quotes without inflating S3."""
        for sym, lq in latest.items():
            if not lq:
                continue
            q = {'pk': f'QUOTE#{sym}', 'sk': 'latest',
                 'bid': str(lq.get('bid')), 'ask': str(lq.get('ask')),
                 'last': str(lq.get('last')), 'ts': int(lq['ts']), 'ttl': int(lq['ts']) + QUOTE_TTL_S}
            for f in ('bidSize', 'askSize', 'lastSize', 'volume'):
                if lq.get(f) is not None:
                    q[f] = str(lq[f])
            self.table.put_item(Item=q)


def on_tick_factory(buffer, latest):
    def on_tick(tickers):
        if not _in_rth():
            return
        now = time.time()
        for t in tickers:
            sym = t.contract.symbol
            if sym not in SYMS:
                continue
            bid, ask, last = _num(t.bid), _num(t.ask), _num(t.last)
            if bid is None and ask is None and last is None:
                continue
            rec = {'ts': now, 'bid': bid, 'bidSize': _num(t.bidSize),
                   'ask': ask, 'askSize': _num(t.askSize),
                   'last': last, 'lastSize': _num(t.lastSize),
                   'volume': _num(t.volume)}
            buffer[sym].append(rec)
            lq = latest.setdefault(sym, {})
            for f in ('bid', 'ask', 'last', 'bidSize', 'askSize', 'lastSize', 'volume'):
                if rec.get(f) is not None:
                    lq[f] = rec[f]
            lq['ts'] = now
    return on_tick


def run_session():
    ib = IB()
    ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=15, readonly=True)
    ib.reqMarketDataType(1)          # request live (not delayed)
    log(f"connected clientId={CLIENT_ID} accounts={ib.managedAccounts()} (READ-ONLY)")
    for sym in SYMS:
        con = resolve_front(ib, sym, EXCHANGE[sym])
        if con is None:
            log(f"  SKIP {sym} — no contract (gapped subscription?)")
            continue
        t = ib.reqMktData(con, '', False, False)
        log(f"  subscribed {sym} {con.localSymbol} conId={con.conId} "
            f"marketDataType={t.marketDataType}")

    writer = TickWriter()
    buffer = defaultdict(list)
    latest = {}
    ib.pendingTickersEvent += on_tick_factory(buffer, latest)

    in_rth = _in_rth()
    log(f"RTH state at start: {'OPEN' if in_rth else 'CLOSED'} "
        f"(recording {RTH_OPEN}-{RTH_CLOSE} ET Mon-Fri)")
    last_cold = time.time()
    try:
        while True:
            ib.sleep(min(HOT_FLUSH_S, TICK_FLUSH_S))
            now = time.time()
            now_in_rth = _in_rth()
            if now_in_rth != in_rth:
                in_rth = now_in_rth
                log(f"RTH -> {'OPEN (recording)' if in_rth else 'CLOSED (idle)'}")
            writer.flush_hot(latest)
            if now - last_cold >= TICK_FLUSH_S:
                writer.flush_s3(buffer)
                last_cold = now
    finally:
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

