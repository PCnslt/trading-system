#!/usr/bin/env python3
"""Does a MID-DAY market entry beat the next-open entry? (the owner's question)

The live lane signals on yesterday's CLOSE and fills at today's OPEN. The owner wants
to know if buying MID-DAY (same-day, at market, using yesterday's signal) is fine or
better. We cannot reconstruct a true "mid-day price" from daily bars, so we approximate
the mid-day entry two honest ways and compare to the next-open baseline:

  A) NEXT_OPEN  : fill at day T+1 open          (current live behaviour)
  B) MIDDAY_HLC : fill at (H+L+C)/3 of day T+1   (typical-day mid-session price proxy)
  C) MIDDAY_VWAP: fill at a VWAP proxy = (H+L+C+VWAP-ish)/3 -> same as B at daily grain

Daily bars can't give a true intraday timestamp, so B is the best available proxy and
this is flagged as an approximation. Entry rule identical to live: rsi2<5 AND
close>SMA200, sub-$50 universe, 2xATR stop, 5d/revert exit, 5bp/side.
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
STOP_ATR, MAX_HOLD, COST_BP = 2.0, 5, 5.0
OOS_FROM = '2022-01-01'


def rsi(c, n=2):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100/(1 + up/dn.replace(0, np.nan))).fillna(50.0)


def atr14(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def load(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 300:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open','high','low','close','volume']].astype(float).sort_index()
        df = df[df['close'] > 0]
        df['rsi2'] = rsi(df['close'], 2)
        df['sma200'] = df['close'].rolling(200).mean()
        df['sma5'] = df['close'].rolling(5).mean()
        df['atr'] = atr14(df['high'], df['low'], df['close'])
        df['mid'] = (df['high'] + df['low'] + df['close']) / 3.0
        return df.dropna()
    except Exception:
        return None


def run(df, variant):
    o = df['open'].values; h = df['high'].values; l = df['low'].values
    c = df['close'].values; mid = df['mid'].values; atr = df['atr'].values
    r2 = df['rsi2'].values; m200 = df['sma200'].values; m5 = df['sma5'].values
    idx = df.index; n = len(df)
    trades = []; i = 1
    while i < n - 2:
        if not (r2[i] < 5.0 and c[i] > m200[i] and PRICE_LO <= c[i] <= PRICE_HI and atr[i] > 0):
            i += 1; continue
        e = i + 1
        entry = o[e] if variant == 'NEXT_OPEN' else mid[e]
        if entry <= 0 or np.isnan(entry):
            i += 1; continue
        stop = entry - STOP_ATR * atr[i]
        exit_px = None; j = e
        while j < n:
            if o[j] < stop:
                exit_px, jx = o[j], j; break
            if l[j] <= stop:
                exit_px, jx = stop, j; break
            held = j - e
            if held >= MAX_HOLD:
                exit_px, jx = c[j], j; break
            if c[j] > m5[j] or r2[j] > 70.0:
                exit_px, jx = c[j], j; break
            j += 1
        if exit_px is None:
            break
        trades.append({'ret': exit_px/entry - 1.0 - 2*COST_BP/1e4, 'hold': jx - e, 'date': idx[e]})
        i = jx + 1
    return trades


def stats(tr, oos=False):
    if oos:
        tr = [t for t in tr if str(t['date'].date()) >= OOS_FROM]
    if len(tr) < 50:
        return None
    r = np.array([t['ret'] for t in tr])
    w, lo = r[r > 0], r[r <= 0]
    pf = (w.sum()/-lo.sum()) if lo.sum() < 0 else float('inf')
    t = r.mean()/(r.std(ddof=1)/np.sqrt(len(r))) if r.std() > 0 else 0.0
    return {'n': len(r), 'PF': round(pf,3), 'win%': round(100*len(w)/len(r),1),
            'avg_bp': round(r.mean()*1e4,1), 't': round(float(t),2)}


def main():
    syms = list(dict.fromkeys(json.load(
        open('/home/ubuntu/trading-system/research/smallcap_universe_full.json'))['symbols']))[:400]
    s3 = boto3.client('s3', region_name='us-east-1')
    with ThreadPoolExecutor(max_workers=16) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'usable {len(data)}\n')
    print(f'ENTRY-TIMING COMPARISON @{COST_BP:.0f}bp (daily-bar proxy for mid-day)\n')
    print(f'{"variant":12}{"n":>7}{"PF":>7}{"win%":>7}{"avg_bp":>9}{"t":>7}   '
          f'{"OOS PF":>7}{"OOS avg":>9}{"OOS t":>7}')
    for v in ('NEXT_OPEN', 'MIDDAY_HLC'):
        t = []
        for df in data.values():
            t += run(df, v)
        s, so = stats(t), stats(t, True)
        if s:
            print(f'{v:12}{s["n"]:>7}{s["PF"]:>7.3f}{s["win%"]:>7.1f}{s["avg_bp"]:>9.1f}'
                  f'{s["t"]:>7.2f}   {(so["PF"] if so else float("nan")):>7.3f}'
                  f'{(so["avg_bp"] if so else float("nan")):>9.1f}'
                  f'{(so["t"] if so else float("nan")):>7.2f}')


if __name__ == '__main__':
    main()
