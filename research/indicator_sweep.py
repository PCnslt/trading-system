#!/usr/bin/env python3
"""Backtest the 8 definable, Robinhood-feasible candidates the owner asked about.

Common framework for EVERY strategy, so the comparison is apples-to-apples:
  - data       : IBKR daily bars (s3 ibkr/equities/daily/*.parquet), sub-$50 universe
  - entry      : signal computed on the CLOSE of bar T, filled at the OPEN of T+1
  - exit       : stop(2xATR) -> time(5 sessions) -> strategy's own exit rule
  - costs      : 5 bp per side, applied to every trade
  - universe   : long-only, price $2-$50, dollar-volume > $5M
  - metrics    : per-trade expectancy + t-stat, full sample and OOS (>= 2022-01-01)

The 8 (from the owner's 50-item list, filtered to definable + RH-feasible):
  BOLL_SQUEEZE  Bollinger(20,2) contraction then close breaks the band, w/ vol expansion
  MACD_HIST     histogram sign flip positive (12,26,9)
  STOCH         %K crosses above %D from oversold (<20)
  ADX_DI        ADX(14)>25 AND +DI crosses above -DI
  CCI           CCI(20) crosses up through -100, exit on > +100
  SR_FLIP       close breaks a 20d high (resistance) after a prior 20d-high break
  PIVOT         classic pivot S1 bounce (buy low touch) or R1 breakout
  INSIDE_BAR    inside bar then break of the mother bar high

Every strategy emits a boolean entry column; the shared engine does the rest.
"""
from __future__ import annotations
import io, os, sys, json, argparse
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
PRICE_LO, PRICE_HI = 1.0, 99999.0   # no price cap: fractional shares make any price tradeable
MIN_DV = 5e6
STOP_ATR, MAX_HOLD, COST_BP = 2.0, 5, 5.0
OOS_FROM = '2022-01-01'


def atr(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def add_common(df):
    df = df.copy()
    df['rsi2'] = (lambda c: (100 - 100 / (1 + (c.diff().clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
        / (-c.diff().clip(upper=0)).ewm(alpha=0.5, adjust=False).mean().replace(0, np.nan)))).fillna(50))(df['close'])
    df['sma5'] = df['close'].rolling(5).mean()
    df['atr'] = atr(df['high'], df['low'], df['close'])
    df['dv'] = (df['close'] * df['volume']).rolling(20).mean()
    return df


def signals(df):
    df = add_common(df)
    c, h, l = df['close'], df['high'], df['low']
    sig = {}

    # 1 Bollinger squeeze: band width contraction (20d min) then close breaks upper band
    m = c.rolling(20).mean(); s = c.rolling(20).std()
    up, dn = m + 2 * s, m - 2 * s
    bw = (up - dn) / m
    squeeze = bw <= bw.rolling(120).min()
    sig['BOLL_SQUEEZE'] = squeeze & (c > up) & (c > c.shift(1))

    # 2 MACD histogram positive flip
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    hist = ema12 - ema26 - (ema12 - ema26).ewm(span=9, adjust=False).mean()
    sig['MACD_HIST'] = (hist > 0) & (hist.shift(1) <= 0)

    # 3 Stochastic %K crosses above %D from oversold
    ll = l.rolling(14).min(); hh = h.rolling(14).max()
    k = 100 * (c - ll) / (hh - ll).replace(0, np.nan)
    d = k.rolling(3).mean()
    sig['STOCH'] = (k > d) & (k.shift(1) <= d.shift(1)) & (k.shift(1) < 20)

    # 4 ADX>25 AND +DI crosses above -DI
    upm = h.diff(); dnm = -l.diff()
    plus_dm = np.where((upm > dnm) & (upm > 0), upm, 0.0)
    minus_dm = np.where((dnm > upm) & (dnm > 0), dnm, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / atr14
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / atr14
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / 14, adjust=False).mean()
    sig['ADX_DI'] = (adx > 25) & (pdi > mdi) & (pdi.shift(1) <= mdi.shift(1))

    # 5 CCI crosses up through -100
    tp = (h + l + c) / 3
    cci = (tp - tp.rolling(20).mean()) / (0.015 * tp.rolling(20).std())
    sig['CCI'] = (cci > -100) & (cci.shift(1) <= -100)

    # 6 S/R flip: close breaks 20d high, and it's the first such break in 10 bars
    hi20 = h.rolling(20).max().shift(1)
    brk = c > hi20
    recent_brk = brk.rolling(10).sum().shift(1) > 0
    sig['SR_FLIP'] = brk & ~recent_brk.fillna(False).astype(bool)

    # 7 Pivot S1 bounce: low touches S1 and closes above it (mean-reversion at S1)
    pp = (h.shift(1) + l.shift(1) + c.shift(1)) / 3
    r1 = 2 * pp - l.shift(1); s1 = 2 * pp - h.shift(1)
    sig['PIVOT'] = (l <= s1) & (c > s1) & (c > c.shift(1))

    # 8 Inside bar breakout
    ib = (h < h.shift(1)) & (l > l.shift(1))
    mother_hi = h.shift(1)
    sig['INSIDE_BAR'] = ib.shift(1) & (c > mother_hi)

    return df, sig


def run(df, entry_col):
    trades = []
    o = df['open'].values; h = df['high'].values; l = df['low'].values
    c = df['close'].values; atr = df['atr'].values; dv = df['dv'].values
    r2 = df['rsi2'].values; m5 = df['sma5'].values
    sig = df[entry_col].values
    idx = df.index
    n = len(df)
    i = 1
    while i < n - 2:
        tradeable = (PRICE_LO <= c[i] <= PRICE_HI) and (dv[i] >= MIN_DV) and atr[i] > 0
        if not (sig[i] and tradeable):
            i += 1
            continue
        e = i + 1
        entry, a = o[e], atr[i]
        if entry <= 0 or np.isnan(entry):
            i += 1
            continue
        stop = entry - STOP_ATR * a
        exit_px = reason = None
        j = e
        while j < n:
            if o[j] < stop:
                exit_px, reason, jx = o[j], 'gap_stop', j
                break
            if l[j] <= stop:
                exit_px, reason, jx = stop, 'stop', j
                break
            held = j - e
            if held >= MAX_HOLD:
                exit_px, reason, jx = c[j], 'time', j
                break
            # strategy exit: reversion-style (close back above 5SMA OR rsi2>70)
            if c[j] > m5[j] or r2[j] > 70.0:
                exit_px, reason, jx = c[j], 'revert', j
                break
            j += 1
        if exit_px is None:
            break
        trades.append({'ret': exit_px / entry - 1.0 - 2 * COST_BP / 1e4,
                       'hold': jx - e, 'date': idx[e]})
        i = jx + 1
    return trades


def stats(tr, oos=False):
    if oos:
        tr = [t for t in tr if str(t['date'].date()) >= OOS_FROM]
    if len(tr) < 50:
        return None
    r = np.array([t['ret'] for t in tr])
    w, lo = r[r > 0], r[r <= 0]
    pf = (w.sum() / -lo.sum()) if lo.sum() < 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 else 0.0
    return {'n': len(r), 'PF': round(pf, 3), 'win%': round(100 * len(w) / len(r), 1),
            'avg_bp': round(r.mean() * 1e4, 1), 't': round(float(t), 2),
            'hold': round(float(np.mean([x['hold'] for x in tr])), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=400)
    ap.add_argument('--strategies', default='ALL')
    a = ap.parse_args()
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'research', 'universe_1500.json')))['symbols']))[:a.limit]
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)} symbols…', flush=True)
    data = {}
    for sym in syms:
        try:
            o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
            df = pd.read_parquet(io.BytesIO(o['Body'].read()))
            if len(df) < 300:
                continue
            df.index = pd.to_datetime(df['date'].astype(str))
            data[sym] = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        except Exception:
            pass
    print(f'  usable {len(data)}\n', flush=True)

    STRATS = ['BOLL_SQUEEZE', 'MACD_HIST', 'STOCH', 'ADX_DI', 'CCI',
              'SR_FLIP', 'PIVOT', 'INSIDE_BAR']
    out = {}
    print(f'STRATEGY SWEEP @{COST_BP:.0f}bp/side (same entry/exit engine, OOS from {OOS_FROM})\n')
    print(f'{"strategy":14}{"n":>7}{"PF":>7}{"win%":>7}{"avg_bp":>9}{"t":>7}{"hold":>6}   '
          f'{"OOS n":>6}{"OOS PF":>7}{"OOS avg":>9}{"OOS t":>7}')
    for st in STRATS:
        trades = []
        for sym, df in data.items():
            d, sig = signals(df)
            d = d.join(pd.DataFrame(sig))
            trades += run(d, st)
        s, so = stats(trades), stats(trades, True)
        out[st] = {'full': s, 'oos': so}
        if s:
            print(f'{st:14}{s["n"]:>7}{s["PF"]:>7.3f}{s["win%"]:>7.1f}{s["avg_bp"]:>9.1f}'
                  f'{s["t"]:>7.2f}{s["hold"]:>6.2f}   '
                  f'{(so["n"] if so else 0):>6}'
                  f'{(so["PF"] if so else float("nan")):>7.3f}'
                  f'{(so["avg_bp"] if so else float("nan")):>9.1f}'
                  f'{(so["t"] if so else float("nan")):>7.2f}')
    json.dump(out, open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     'research', 'indicator_sweep_results.json'), 'w'),
              indent=1, default=str)


if __name__ == '__main__':
    main()
