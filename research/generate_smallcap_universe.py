#!/usr/bin/env python3
"""Screen the FULL US common-stock universe (~6,000) for sub-PRICE_HI whole-share names.

The LIVE lane needs WHOLE shares (Robinhood fractional can't carry a stop), so
with $700 the tradeable universe is sub-$35 names. The current SMALL_CAP_STOCKS
(154) was screened from S&P 1500 ONLY — this expands it to the full ~6,000-stock
universe (Nasdaq/NYSE listings via data_engine).

Filter: $2 <= close <= $35 AND 20d avg $volume >= $50M (liquid enough to trade
whole-share without severe slippage).

Outputs research/smallcap_universe_full.json + S3 data-engine/universe/smallcap-full.json.
"""
import json
import os
import sys

import boto3
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_engine.universe import load_symbols  # noqa: E402

PRICE_LO, PRICE_HI = 2.0, 50.0
ADV_MIN_M = 50.0


def main():
    uni = load_symbols()
    print(f'full universe: {len(uni)} common stocks')
    out = []
    CH = 500
    for i in range(0, len(uni), CH):
        chunk = uni[i:i + CH]
        try:
            data = yf.download(chunk, period='3mo', interval='1d', auto_adjust=True,
                               progress=False, group_by='ticker', threads=True)
        except Exception as e:
            print(f'  chunk {i} failed: {e!r}')
            continue
        for sym in chunk:
            try:
                df = data[sym] if isinstance(data.columns, pd.MultiIndex) else data
                if df is None or df.empty or 'Close' not in df or 'Volume' not in df:
                    continue
                close = float(df['Close'].dropna().iloc[-1])
                if not (PRICE_LO <= close <= PRICE_HI):
                    continue
                vol20 = df['Volume'].dropna().tail(20)
                if len(vol20) < 15:
                    continue
                adv = float((vol20 * df['Close'].reindex(vol20.index)).mean()) / 1e6
                if adv >= ADV_MIN_M:
                    out.append((sym, round(close, 2), round(adv, 1)))
            except Exception:
                continue
        print(f'  ...processed through {min(i + CH, len(uni))}/{len(uni)} ({len(out)} sub-${PRICE_HI:.0f} so far)')
    out.sort(key=lambda x: -x[2])
    symbols = [s for s, _, _ in out]
    payload = {'generatedAt': pd.Timestamp.now(tz='UTC').isoformat(),
               'source': 'us_common_stocks_full',
               'count': len(symbols),
               'filters': {'price_lo': PRICE_LO, 'price_hi': PRICE_HI, 'adv_min_m': ADV_MIN_M},
               'symbols': symbols}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'smallcap_universe_full.json')
    with open(p, 'w') as f:
        json.dump(payload, f, indent=2)
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.put_object(Bucket='trading-datalake-920641308584',
                  Key='data-engine/universe/smallcap-full.json', Body=json.dumps(payload))
    print(f'\\nsub-${PRICE_HI:.0f} liquid: {len(symbols)} names -> {p}')
    print('top 30 by ADV:', ', '.join(symbols[:30]))


if __name__ == '__main__':
    main()
