#!/usr/bin/env python3
"""RSI(14)<25 flat-by-close PAPER forward-test — 2-day run, zero capital.

Matches the validated backtest exactly: signal = RSI(14)<25 on day T's close,
paper-ENTER at day T+1 open, paper-EXIT at day T+1 close (flat by close). Journals
each paper trade to DynamoDB RSIP#<sym> sk=<date> with gross/net bp.

Run once daily AFTER the close (cron ~20:30 ET, after the IBKR daily refresh), so
day T+1's bar is final in the archive. Pure read + journal — places NO orders.
"""
from __future__ import annotations
import io, os, sys, json, time
import datetime as dt
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()

import boto3
import numpy as np
import pandas as pd

NY = ZoneInfo('America/New_York')
REGION = os.getenv('AWS_REGION', 'us-east-1')
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
THRESH = float(os.getenv('RSI_PAPER_THRESH', '25'))
PERIOD = int(os.getenv('RSI_PAPER_PERIOD', '14'))
COST_BP = float(os.getenv('RSI_PAPER_COST_BP', '5'))
MIN_DV = 5e6


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100/(1 + up/dn.replace(0, np.nan))).fillna(50.0)


def main():
    table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)
    s3 = boto3.client('s3', region_name=REGION)
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'universe_1500.json')))['symbols']))
    now = dt.datetime.now(NY)

    def load(sym):
        try:
            o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
            df = pd.read_parquet(io.BytesIO(o['Body'].read()))
            if len(df) < 300:
                return None
            df.index = pd.to_datetime(df['date'].astype(str))
            df = df[['open','high','low','close','volume']].astype(float).sort_index()
            df['rsi14'] = rsi(df['close'], PERIOD)
            df['dv'] = (df['close']*df['volume']).rolling(20).mean()
            return df
        except Exception:
            return None

    print(f'RSI({PERIOD})<{THRESH} paper scan — {now.strftime("%Y-%m-%d %H:%M")} ET', flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        data = {s: d for s, d in zip(syms, ex.map(load, syms)) if d is not None}
    print(f'  loaded {len(data)} symbols', flush=True)

    trades = 0
    for sym, df in data.items():
        if len(df) < 2:
            continue
        # signal = RSI<thr at yesterday's close (index -2); trade = today (index -1) open->close
        if float(df['rsi14'].iloc[-2]) >= THRESH:
            continue
        if float(df['dv'].iloc[-2]) < MIN_DV:
            continue
        o = float(df['open'].iloc[-1]); c = float(df['close'].iloc[-1])
        if o <= 0:
            continue
        d = str(df.index[-1].date())
        gross_bp = (c/o - 1.0) * 1e4
        net_bp = gross_bp - 2*COST_BP
        table.put_item(Item={
            'pk': f'RSIP#{sym}', 'sk': d, 'date': d, 'symbol': sym,
            'entry_open': str(round(o,4)), 'exit_close': str(round(c,4)),
            'gross_bp': str(round(gross_bp,1)), 'net_bp': str(round(net_bp,1)),
            'rsi14_signal': str(round(float(df['rsi14'].iloc[-2]),2)),
            'mode': 'PAPER', 'strategy': 'RSI14-flat', 'ts': int(time.time())})
        trades += 1
    print(f'  journaled {trades} paper trade(s)', flush=True)


if __name__ == '__main__':
    main()
