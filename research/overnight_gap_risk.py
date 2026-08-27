"""Overnight-gap risk on the sub-$50 universe — how big is the gap a stop can't catch?

RH stops are RTH-only, so for EVERY name (tradable or not) a stop that triggers
overnight actually fills at the 09:30 OPEN, not at the stop price. The question the
owner is really asking: "if I hold an untradable name overnight, how much worse can
the fill be than my stop, and can sizing absorb it?"

This measures the close->next-open gap distribution for names that close DOWN hard
(the ones a 2xATR stop would be threatening), from the IBKR daily archive.
"""
from __future__ import annotations
import io, os, sys, json
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/trading-system/.env')

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
PRICE_LO, PRICE_HI = 2.0, 50.0


def load(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 300:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        df = df[df['close'] > 0]
        pc = df['close'].shift(1)
        df['close_ret'] = df['close'] / pc - 1.0
        df['overnight_gap'] = df['open'] / pc - 1.0        # close T-1 -> open T
        df['price_ok'] = pc.between(PRICE_LO, PRICE_HI)
        return df.dropna(subset=['overnight_gap'])
    except Exception:
        return None


def main():
    syms = list(dict.fromkeys(json.load(
        open('/home/ubuntu/trading-system/research/smallcap_universe_full.json'))['symbols']))[:400]
    s3 = boto3.client('s3', region_name='us-east-1')
    with ThreadPoolExecutor(max_workers=16) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    gaps_all, gaps_down = [], []
    for df in data.values():
        m = df['price_ok']
        gaps_all += list(df.loc[m, 'overnight_gap'].values)
        md = m & (df['close_ret'] <= -0.05)   # names that just fell hard (stop at risk)
        gaps_down += list(df.loc[md, 'overnight_gap'].values)

    for label, g in (('ALL sub-$50 nights', gaps_all), ('after a -5% day', gaps_down)):
        g = np.asarray(g)
        g = g[(g > -0.5) & (g < 0.5)]
        p = np.percentile(g, [0.1, 0.5, 1, 2, 5, 50])
        print(f'{label}:')
        print(f'  n={len(g)}  p50={p[5]*100:+.1f}%  p5={p[4]*100:+.1f}%  '
              f'p2={p[3]*100:+.1f}%  p1={p[2]*100:+.1f}%  '
              f'p0.5={p[1]*100:+.1f}%  p0.1={p[0]*100:+.1f}%')
    # worst single-night gaps ever seen
    w = sorted(gaps_all)[:10]
    print('\nworst 10 single nights on any sub-$50 name (close->open):')
    for x in w:
        print(f'  {x*100:+.1f}%')


if __name__ == '__main__':
    main()
