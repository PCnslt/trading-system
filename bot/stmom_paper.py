#!/usr/bin/env python3
"""STMOM paper forward-test — monthly-rebalance, 20-day hold, top-25 winners.

Matches the validated backtest (research/stmom_backtest.py): rank liquid names on
prior-month return (skip last 5 days), buy top-25 at close, hold ~20 trading days.
PAPER ONLY — journals to DynamoDB, places no orders.

Runs daily after close. No-op on hold days; exits + re-opens a basket every ~28 days.
"""
import os, sys, json, io, time
import datetime as dt
from zoneinfo import ZoneInfo
import boto3, pandas as pd, numpy as np

ET = ZoneInfo('America/New_York')
S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'
DDB = boto3.resource('dynamodb', region_name='us-east-1').Table('trading-data')

TOP_N = 25
HOLD_DAYS = 28      # ~20 trading days
SKIP = 5            # skip most-recent week (avoid short-term reversal)
LOOKBACK = 25       # prior-month window end


def today():
    return dt.datetime.now(ET).date().isoformat()


def liquid_syms(n=150):
    with open(os.path.join(os.path.dirname(__file__), '..', 'research', 'universe_1500.json')) as f:
        raw = json.load(f)
    syms = raw['symbols'] if isinstance(raw, dict) and 'symbols' in raw else raw
    return [s for s in syms if isinstance(s, str)][:n]


def load_close(sym):
    try:
        o = S3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            return df.set_index('date')['close'].sort_index()
        return df['close'].sort_index()
    except Exception:
        return None


def prior_month_ret(close):
    if close is None or len(close) < LOOKBACK + 1:
        return None
    return float(close.iloc[-SKIP - 1]) / float(close.iloc[-LOOKBACK]) - 1.0


def open_basket():
    sig = {}
    closes = {}
    for s in liquid_syms():
        c = load_close(s)
        if c is None:
            continue
        closes[s] = c
        r = prior_month_ret(c)
        if r is not None:
            sig[s] = r
    top = sorted(sig, key=sig.get, reverse=True)[:TOP_N]
    entry = {}
    for s in top:
        entry[s] = float(closes[s].iloc[-1])
    item = {'pk': 'STMOMBASKET#latest', 'sk': 'current', 'date': today(),
            'syms': json.dumps(top), 'entry': json.dumps(entry), 'status': 'OPEN'}
    DDB.put_item(Item=item)
    print(f'OPENED basket {today()}: {len(top)} names, top = {top[:5]}')


def settle_and_reopen(basket):
    entry = json.loads(basket.get('entry', '{}'))
    syms = json.loads(basket.get('syms', '[]'))
    rets = []
    for s in syms:
        c = load_close(s)
        if c is None or not entry.get(s):
            continue
        r = float(c.iloc[-1]) / float(entry[s]) - 1.0
        rets.append(r)
        DDB.put_item(Item={'pk': f'STMOMTRADE#{s}', 'sk': basket['date'],
                           'entry': str(entry[s]), 'exit': str(float(c.iloc[-1])),
                           'ret_bp': str(round(r * 10000, 1))})
    if rets:
        avg = float(np.mean(rets))
        print(f'SETTLED basket {basket["date"]}: {len(rets)} names, avg {avg*100:.2f}%, '
              f'win {100*sum(1 for r in rets if r > 0)/len(rets):.0f}%')
    # close old basket
    DDB.put_item(Item={'pk': 'STMOMBASKET#latest', 'sk': 'current', 'date': basket['date'],
                       'syms': basket['syms'], 'entry': basket['entry'], 'status': 'CLOSED'})
    open_basket()


def main():
    r = DDB.get_item(Key={'pk': 'STMOMBASKET#latest', 'sk': 'current'}).get('Item')
    if not r or r.get('status') != 'OPEN':
        open_basket()
        return
    # age check
    bdate = r.get('date')
    try:
        age = (dt.datetime.now(ET).date() - dt.date.fromisoformat(bdate)).days
    except Exception:
        age = 0
    if age >= HOLD_DAYS:
        settle_and_reopen(r)
    else:
        print(f'holding basket {bdate} (day {age}/{HOLD_DAYS})')


if __name__ == '__main__':
    main()
