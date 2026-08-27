#!/usr/bin/env python3
"""Evaluate the 20 intraday strategies the owner pasted — which can we even test,
and which of the testable ones have an edge on our data (IBKR daily, sub-$50+full
universe, no shorting, RH fractional).

HARD FILTER — our data is DAILY bars + live RH quotes (no equity intraday minute
bars; IBKR intraday is futures-only). So any strategy needing 5-min/1-min/L2/orderflow
is UNTESTABLE as-is. The daily-testable ones get the same honest engine:

  signal on day T bar, ENTER at T+1 OPEN, EXIT at T+1 CLOSE (flat-by-close, matching
  the owner's "all positions closed before market close" rule), 5bp/side, long-only,
  no stop (same-day), 2xATR stop is reported too for the multi-day variants.

Signals (daily-approximable only):
  RED2GREEN  open<prev_close AND close>prev_close
  RSI14      RSI(14)<20
  BB_MEANREV close<lower_band(20,2) then revert
  MA_DIP     low touches rising 20d MA, close above it
  TURTLE     breaks 20d high intraday but closes back below (false breakout)
  MOMBREAK   close>20d high AND volume>1.5x avg
  RETEST     breaks 20d high then pulls back to it within 3 bars
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
MIN_DV = 5e6
COST_BP = 5.0
OOS_FROM = '2022-01-01'


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100/(1 + up/dn.replace(0, np.nan))).fillna(50.0)


def load(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 300:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open','high','low','close','volume']].astype(float).sort_index()
        df = df[df['close'] > 0]
        df['dv'] = (df['close']*df['volume']).rolling(20).mean()
        return df
    except Exception:
        return None


def signals(df):
    c, o, h, l, v = df['close'], df['open'], df['high'], df['low'], df['volume']
    pc = c.shift(1)
    sig = {}
    sig['RED2GREEN'] = (o < pc) & (c > pc)
    sig['RSI14'] = rsi(c, 14) < 20
    m = c.rolling(20).mean(); s = c.rolling(20).std()
    lo = m - 2*s
    sig['BB_MEANREV'] = (c < lo)
    ma20 = c.rolling(20).mean()
    sig['MA_DIP'] = (l <= ma20) & (c > ma20) & (ma20 > ma20.shift(1))
    hi20 = h.rolling(20).max().shift(1)
    sig['TURTLE'] = (h > hi20) & (c < hi20)   # broke out intraday, closed back under
    sig['MOMBREAK'] = (c > hi20) & (v > 1.5 * v.rolling(20).mean())
    brk = c > hi20
    sig['RETEST'] = brk.shift(3) & ((c - hi20).abs() / hi20 < 0.01)
    return sig


def run(df, name, sig_series):
    """ENTER next open, EXIT same-day close (flat by close)."""
    o = df['open'].values; c = df['close'].values; dv = df['dv'].values
    sig = sig_series.values
    idx = df.index; n = len(df)
    trades = []; i = 1
    while i < n - 1:
        if not (sig[i] and dv[i] >= MIN_DV and o[i+1] > 0):
            i += 1; continue
        ret = c[i+1]/o[i+1] - 1.0 - 2*COST_BP/1e4
        trades.append({'ret': ret, 'date': idx[i+1]})
        i += 2
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
        open('/home/ubuntu/trading-system/research/universe_1500.json'))['symbols']))
    s3 = boto3.client('s3', region_name='us-east-1')
    print(f'loading {len(syms)}…', flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)}\n', flush=True)

    NAMES = ['RED2GREEN','RSI14','BB_MEANREV','MA_DIP','TURTLE','MOMBREAK','RETEST']
    print(f'DAILY-TESTABLE intraday strategies, ENTER next open / EXIT same close (flat-by-close), @{COST_BP:.0f}bp\n')
    print(f'{"signal":12}{"n":>7}{"PF":>7}{"win%":>7}{"avg_bp":>9}{"t":>7}   '
          f'{"OOS n":>6}{"OOS PF":>7}{"OOS avg":>9}{"OOS t":>7}')
    for name in NAMES:
        trades = []
        for df in data.values():
            sg = signals(df)
            trades += run(df, name, sg[name])
        s, so = stats(trades), stats(trades, True)
        if s:
            print(f'{name:12}{s["n"]:>7}{s["PF"]:>7.3f}{s["win%"]:>7.1f}{s["avg_bp"]:>9.1f}'
                  f'{s["t"]:>7.2f}   {(so["n"] if so else 0):>6}'
                  f'{(so["PF"] if so else float("nan")):>7.3f}'
                  f'{(so["avg_bp"] if so else float("nan")):>9.1f}'
                  f'{(so["t"] if so else float("nan")):>7.2f}')


if __name__ == '__main__':
    main()
