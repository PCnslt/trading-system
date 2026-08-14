#!/usr/bin/env python3
"""Futures L1 tick recorder — persistent service (systemd), clientId=74.

Streams IBKR L1 (bid/ask/last/size) for MES/MNQ/ES/NQ/ZB/ZN during RTH
(13:30-20:00 UTC Mon-Fri), maximizing the CME/CBOT real-time subscription.

Writes (cold): S3  futures-ticks/<sym>/<date>/<ts>.jsonl — one JSONL line per
               tick, flushed every TICK_FLUSH_S seconds (default 5s) so we
               batch instead of creating per-tick objects.
Writes (hot):  DynamoDB QUOTE#<sym> (sk='latest') — bid/ask/last/timestamp,
               overwritten each flush; TTL 1 day so a dead recorder self-cleans.

READ-ONLY on the trading side: reqMktData subscriptions only. No orders, no
account writes, no RUN# markers, no POSITION writes. Shares the paper gateway
with the bots (clientId 74 vs 70/71/72) — L1 streaming is a separate pacing
bucket from reqHistoricalData, so it never starves the bots' bar requests.

Reconnects automatically across the gateway's 04:00 daily restart.
"""
import os
import sys
import math
import time
import json
import datetime as dt
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from dotenv import load_dotenv
from ib_insync import IB, Future

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from bot.futures_contracts import SYMBOLS, front_month

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
CLIENT_ID = 74                       # distinct from live.py(70)/bonds(71)/intraday(72)/backfill(73)

TICK_FLUSH_S = float(os.getenv('TICK_FLUSH_S', '5'))
QUOTE_TTL_S = int(os.getenv('QUOTE_TTL_S', '86400'))   # 1 day
RTH_OPEN_UTC = dt.time(13, 30)
RTH_CLOSE_UTC = dt.time(20, 0)

SYMS = ['MES', 'MNQ', 'ES', 'NQ', 'ZB', 'ZN']
EXCHANGE = {sym: ex for sym, ex in SYMBOLS}


def log(msg):
    print(f"[{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}] {msg}", flush=True)


def _in_rth(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now.weekday() < 5 and RTH_OPEN_UTC <= now.time() < RTH_CLOSE_UTC)


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

    def flush(self, buffer):
        """Write one S3 JSONL batch + latest QUOTE# per symbol, then clear."""
        now = dt.datetime.now(dt.timezone.utc)
        date = now.strftime('%Y-%m-%d')
        ts = int(now.timestamp())
        for sym, ticks in list(buffer.items()):
            if not ticks:
                continue
            lines = '\n'.join(json.dumps(t) for t in ticks) + '\n'
            key = f'futures-ticks/{sym}/{date}/{ts}.jsonl'
            self.s3.put_object(Bucket=S3_BUCKET, Key=key, Body=lines)
            last = ticks[-1]
            q = {'pk': f'QUOTE#{sym}', 'sk': 'latest',
                 'bid': str(last['bid']), 'ask': str(last['ask']),
                 'last': str(last['last']), 'ts': ts, 'ttl': ts + QUOTE_TTL_S}
            for f in ('bidSize', 'askSize', 'lastSize', 'volume'):
                if last.get(f) is not None:
                    q[f] = str(last[f])
            self.table.put_item(Item=q)
            n = len(ticks)
            buffer[sym] = []
        return


def on_tick_factory(buffer):
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
    return on_tick


def run_session():
    ib = IB()
    ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=15, readonly=True)
    ib.reqMarketDataType(1)          # request live (not delayed)
    log(f"connected clientId={CLIENT_ID} accounts={ib.managedAccounts()} (READ-ONLY)")
    for sym in SYMS:
        con = ib.qualifyContracts(Future(sym, front_month(), EXCHANGE[sym]))[0]
        t = ib.reqMktData(con, '', False, False)
        log(f"  subscribed {sym} {con.localSymbol} conId={con.conId} "
            f"marketDataType={t.marketDataType}")

    writer = TickWriter()
    buffer = defaultdict(list)
    ib.pendingTickersEvent += on_tick_factory(buffer)

    in_rth = _in_rth()
    log(f"RTH state at start: {'OPEN' if in_rth else 'CLOSED'} "
        f"(recording {RTH_OPEN_UTC}-{RTH_CLOSE_UTC} UTC Mon-Fri)")
    try:
        while True:
            ib.sleep(TICK_FLUSH_S)
            now_in_rth = _in_rth()
            if now_in_rth != in_rth:
                in_rth = now_in_rth
                log(f"RTH -> {'OPEN (recording)' if in_rth else 'CLOSED (idle)'}")
            writer.flush(buffer)
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
