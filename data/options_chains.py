#!/usr/bin/env python3
"""Options-on-futures CHAIN METADATA collector (metadata only — no option bars).

For liquid futures-options underlyings, calls reqSecDefOptParams (contract-
definition data: expiries + strikes) and archives the chain metadata to
  - S3       options/<sym>/chains.json   (cold)
  - DynamoDB OPTCHAIN#<sym>  sk='latest' (hot: expiry/strike counts + ranges)

HONEST GAP: historical option BARS (and real-time option quotes) are a SEPARATE
IBKR subscription — NOT included in the CME Group L1 bundle. This collector
only stores the free contract-definition chain (expiries + strikes). Do not
attempt reqHistoricalData on options; it will fail / is not entitled.

READ-ONLY on the trading side: reqContractDetails + reqSecDefOptParams + S3 +
DynamoDB OPTCHAIN# writes only. No orders. clientId 77 (distinct from bots
70/71/72, backfill 73, tick 74, daily 75, reconcile 76).
"""
import os
import sys
import time
import json
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from dotenv import load_dotenv
from ib_insync import IB, Future

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from data.symbol_registry import OPTION_UNDERLYINGS, ASSET_CLASSES  # noqa: E402
from bot.futures_contracts import SYMBOLS, resolve_front          # noqa: E402

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
CLIENT_ID = 77                       # distinct from all other clients

EXCHANGE = {sym: ex for sym, ex in SYMBOLS}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_chains(ib, sym):
    """reqSecDefOptParams -> merged {expirations, strikes, tradingClasses} for sym.

    reqSecDefOptParams returns one OptionChain per (exchange, tradingClass).
    Each carries expirations[] and strikes[]. We UNION them (a chain's strikes
    differ per expiry, so the union is the full strike axis) and also keep the
    per-tradingClass breakdown.

    The FRONT contract's options can be degenerate (near/at expiry, e.g. ZS the
    day of expiry, or GC front with rolled options). So we walk the active
    chain (front -> next few expiries) and use the first contract that returns a
    non-empty options chain.
    """
    exchange = EXCHANGE[sym]
    today = dt.date.today().strftime('%Y%m%d')
    cd = ib.reqContractDetails(Future(sym, exchange=exchange))
    if not cd and exchange != '':
        cd = ib.reqContractDetails(Future(sym, exchange=''))
    if not cd:
        return None, 'no underlying contract (gapped)'
    # active expiries (>= today), sorted ascending
    exps = sorted({c.contract.lastTradeDateOrContractMonth for c in cd
                   if c.contract.lastTradeDateOrContractMonth >= today})
    if not exps:
        exps = sorted({c.contract.lastTradeDateOrContractMonth for c in cd}, reverse=True)

    chains, chosen = [], None
    for exp in exps[:4]:   # try front + next 3 expiries
        con = next((c.contract for c in cd if c.contract.lastTradeDateOrContractMonth == exp), None)
        if con is None:
            continue
        try:
            chains = ib.reqSecDefOptParams(con.symbol, con.exchange, con.secType, con.conId)
        except Exception:
            chains = []
        if chains:
            chosen = con
            break
    if not chains:
        return None, 'empty chain (no optionable expiry found)'
    if chosen is None:
        return None, 'empty chain'

    expirations, strikes = set(), set()
    classes = []
    for ch in chains:
        for e in (ch.expirations or []):
            expirations.add(e)
        for s in (ch.strikes or []):
            strikes.add(_num(s))
        classes.append({
            'exchange': ch.exchange,
            'underlyingConId': ch.underlyingConId,
            'tradingClass': ch.tradingClass,
            'multiplier': ch.multiplier,
            'n_expirations': len(ch.expirations or []),
            'n_strikes': len(ch.strikes or []),
        })
    strikes.discard(None)
    return {
        'symbol': sym,
        'underlyingConId': chosen.conId,
        'underlyingExpiry': chosen.lastTradeDateOrContractMonth,
        'exchange': chosen.exchange,
        'expirations': sorted(expirations),
        'strikes': sorted(strikes),
        'tradingClasses': classes,
    }, None


def write_chain(s3, table, sym, data):
    data['fetchedAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
    data['asset_class'] = ASSET_CLASSES.get(sym, '')
    s3.put_object(Bucket=S3_BUCKET, Key=f'options/{sym}/chains.json',
                  Body=json.dumps(data, indent=2, default=str))
    strikes = data['strikes']
    exps = data['expirations']
    item = {
        'pk': f'OPTCHAIN#{sym}', 'sk': 'latest',
        'underlyingConId': int(data['underlyingConId']),
        'underlyingExpiry': data['underlyingExpiry'],
        'exchange': data['exchange'],
        'n_expirations': len(exps),
        'n_strikes': len(strikes),
        'min_expiry': exps[0] if exps else '',
        'max_expiry': exps[-1] if exps else '',
        'min_strike': str(strikes[0]) if strikes else '',
        'max_strike': str(strikes[-1]) if strikes else '',
        'ts': int(time.time()),
    }
    table.put_item(Item=item)


def main():
    ib = IB()
    s3 = boto3.client('s3', region_name=AWS_REGION)
    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    done = 0
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=15, readonly=True)
        print(f"connected clientId={CLIENT_ID} accounts={ib.managedAccounts()} (READ-ONLY)")
        for sym in OPTION_UNDERLYINGS:
            try:
                data, err = fetch_chains(ib, sym)
                if data is None:
                    print(f"[{sym}] SKIP — {err}")
                    continue
                write_chain(s3, table, sym, data)
                print(f"[{sym}] {len(data['expirations'])} expiries, "
                      f"{len(data['strikes'])} strikes "
                      f"({data['expirations'][0]}..{data['expirations'][-1]}) "
                      f"-> options/{sym}/chains.json + OPTCHAIN#{sym}")
                done += 1
            except Exception as e:
                print(f"[{sym}] FAILED: {e!r}")
            time.sleep(1)
    finally:
        ib.disconnect()
    print(f"\nDONE: {done}/{len(OPTION_UNDERLYINGS)} option chains written. "
          "Metadata only — no option bars (separate subscription).")


if __name__ == '__main__':
    main()
