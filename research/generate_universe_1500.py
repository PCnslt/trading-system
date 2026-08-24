#!/usr/bin/env python3
"""Generate the tradeable broad universe (S&P 1500 + liquid screen) for breadth.

Expands the RSI2 universe from 190 -> ~1,400+ names. Source: S&P 500 + S&P 400
(MidCap) + S&P 600 (SmallCap) constituents from Wikipedia (free, keyless).
Minimal tradeable filter: last close > $2 AND 20d avg $volume >= $10M (filters
delisted/untradeable; keeps the full mid/small-cap breadth).

Outputs:
  - research/universe_1500.json  (sorted list, local)
  - s3://trading-datalake-920641308584/data-engine/universe/tradeable-1500.json

The PAPER lane trades this broad universe; the LIVE lane stays on the
sub-$35 whole-share SMALL_CAP_STOCKS subset (unchanged).
"""
import json
import sys
import os

import pandas as pd
import yfinance as yf
import requests
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import boto3  # noqa: E402

S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
PRICE_MIN = 2.0
ADV_MIN_M = 10.0  # $10M/day — minimal tradeable, keeps mid/small-cap breadth


def wiki_tickers(url, col):
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (research)'}, timeout=30)
    r.raise_for_status()
    tables = pd.read_html(StringIO(r.text))
    for t in tables:
        if col in t.columns:
            return [str(x).replace('.', '-') for x in t[col].tolist() if str(x) != 'nan']
    return []


def get_sp1500():
    sp500 = wiki_tickers('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', 'Symbol')
    sp400 = wiki_tickers('https://en.wikipedia.org/wiki/List_of_S%26P_400_companies', 'Symbol')
    sp600 = wiki_tickers('https://en.wikipedia.org/wiki/List_of_S%26P_600_companies', 'Symbol')
    uni = sorted(set(sp500 + sp400 + sp600))
    return [s for s in uni if s.isalpha() or '-' in s]


def main():
    uni = get_sp1500()
    print(f'S&P 1500 tickers: {len(uni)}')
    data = yf.download(uni, period='3mo', interval='1d', auto_adjust=True,
                       progress=False, group_by='ticker', threads=True)
    tradeable = []
    for sym in uni:
        try:
            df = data[sym] if isinstance(data.columns, pd.MultiIndex) else data
            if df is None or df.empty or 'Close' not in df or 'Volume' not in df:
                continue
            close = float(df['Close'].dropna().iloc[-1])
            if close <= PRICE_MIN:
                continue
            vol20 = df['Volume'].dropna().tail(20)
            if len(vol20) < 15:
                continue
            adv = float((vol20 * df['Close'].reindex(vol20.index)).mean()) / 1e6
            if adv >= ADV_MIN_M:
                tradeable.append((sym, round(close, 2), round(adv, 1)))
        except Exception:
            continue
    tradeable.sort(key=lambda x: -x[2])
    symbols = [s for s, _, _ in tradeable]
    print(f'tradeable (price>${PRICE_MIN:.0f}, adv>=${ADV_MIN_M:.0f}M): {len(symbols)}')

    payload = {'generatedAt': pd.Timestamp.now(tz='UTC').isoformat(),
               'source': 'sp1500_wikipedia', 'count': len(symbols),
               'filters': {'price_min': PRICE_MIN, 'adv_min_m': ADV_MIN_M},
               'symbols': symbols}
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'universe_1500.json')
    with open(out, 'w') as f:
        json.dump(payload, f, indent=2)
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.put_object(Bucket=S3_BUCKET, Key='data-engine/universe/tradeable-1500.json',
                  Body=json.dumps(payload))
    print(f'saved -> {out} + s3://{S3_BUCKET}/data-engine/universe/tradeable-1500.json')
    print('first 20:', ', '.join(symbols[:20]))


if __name__ == '__main__':
    main()
