#!/usr/bin/env python3
"""Short-term (intraday / 1-3 day) strategy study — 4 tests, honest fills.

Test 1: RSI2 dip-buy with EXPLICIT profit targets (vs current RSI2>70/5d hold).
Test 2: Opening-range FADE (mean reversion, not breakout) on 5-min MES.
Test 3: Time-of-day seasonality (avg return per 30-min bucket, 5-min MES).
Test 4: Bollinger lower-band mean-reversion with profit target (daily).

Cost model (honest, drawdown-first): entry at signal + 1-tick slip; GTC stop
gap-aware (open<stop -> fill at open); profit target intraday fill, STOP-FIRST
when both hit same bar (conservative); signal exit at close + slip. Report
win%, PF, maxDD, avg-hold, trade count per variant.
"""
import json
import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf
import boto3

NY = ZoneInfo('America/New_York')
S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'

# ---- cost ----
SLIP_PT = 0.25          # 1 tick ES/NQ/MES = 0.25 pt per side
ES_PV, NQ_PV, MES_PV = 50.0, 20.0, 5.0


def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=2):
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = g / l.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def fetch_daily(tkr):
    df = yf.download(tkr, period='26y', interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    return df


# =====================================================================
# Shared daily backtest engine (long-only, stop + optional profit target)
# =====================================================================
def run_daily(df, entry_fn, exit_close_fn, stop_atr, pt_targets=None, pv=ES_PV,
              max_hold=5, label=''):
    """entry_fn(detail)->bool, exit_close_fn(detail, held)->bool at close.
    pt_targets: list of (name, target_fn(entry, detail, atr)) for profit targets."""
    h, l, c = df['High'], df['Low'], df['Close']
    atr = wilder_atr(h, l, c, 14)
    r2 = rsi(c, 2)
    sma200 = c.rolling(200).mean()
    n = len(df)
    rows = []
    pos = None  # dict(entry, stop, atr, held, day)
    for i in range(1, n):
        if pos is not None:
            pos['held'] += 1
            stop = pos['stop']
            e = pos['entry']
            o, hi, lo, cl = float(h.iloc[i]), float(l.iloc[i]), float(c.iloc[i]), float(c.iloc[i])
            # 1. hard stop (gap-aware)
            if o < stop:  # gap through
                pnl = (o - e) * pv
                rows.append((pos['day'], 'STOP-GAP', pnl, pos['held']))
                pos = None
                continue
            if lo <= stop:
                pnl = (stop - e) * pv
                rows.append((pos['day'], 'STOP', pnl, pos['held']))
                pos = None
                continue
            # 2. profit target (if set) — checked AFTER stop (conservative)
            if pos['target'] is not None and hi >= pos['target']:
                pnl = (pos['target'] - e) * pv
                rows.append((pos['day'], 'TARGET', pnl, pos['held']))
                pos = None
                continue
            # 3. time stop
            if pos['held'] >= max_hold:
                pnl = (cl - e) * pv
                rows.append((pos['day'], 'TIME', pnl, pos['held']))
                pos = None
                continue
            # 4. close-based signal exit
            detail = dict(close=cl, rsi2=float(r2.iloc[i]), sma200=float(sma200.iloc[i]))
            if exit_close_fn(detail, pos['held']):
                pnl = (cl - e) * pv
                rows.append((pos['day'], 'SIGNAL', pnl, pos['held']))
                pos = None
        else:
            detail = dict(close=float(c.iloc[i]), rsi2=float(r2.iloc[i]),
                          sma200=float(sma200.iloc[i]), atr=float(atr.iloc[i]))
            if entry_fn(detail):
                e = float(c.iloc[i]) + SLIP_PT
                st = e - stop_atr * detail['atr']
                pos = dict(entry=e, stop=st, atr=detail['atr'], held=0, day=df.index[i])
                # set target (first matching variant is the one being tested; pass pt_targets=[(name,fn)] only)
                pos['target'] = None
    return rows


# =====================================================================
# TEST 1 — RSI2 profit-target exits
# =====================================================================
def test1_rsi2_pt():
    print('=' * 70)
    print('TEST 1 — RSI2 dip-buy: profit-target vs current exit (ES + NQ, 26y)')
    print('=' * 70)
    LO, HI = 10.0, 70.0

    def entry(detail):
        return detail['rsi2'] < LO and not np.isnan(detail['sma200']) and detail['close'] > detail['sma200']

    variants = {
        'baseline (RSI2>70 / 5d)': (None, lambda d, held: d['rsi2'] > HI),
        'PT +0.5%': (lambda e, d, a: e * 1.005, lambda d, held: False),
        'PT +1xATR': (lambda e, d, a: e + 1.0 * a, lambda d, held: False),
        'PT +1R (1:1)': (lambda e, d, a: e + (2.0 * a), lambda d, held: False),  # 2xATR stop = 2R risk, 1R target = +2xATR
    }
    for tkr, pv in [('ES=F', ES_PV), ('NQ=F', NQ_PV)]:
        df = fetch_daily(tkr)
        print(f'\n  --- {tkr} ---')
        for name, (tfn, efn) in variants.items():
            rows = []
            h, l, c, o = df['High'], df['Low'], df['Close'], df['Open']
            atr = wilder_atr(h, l, c, 14)
            r2 = rsi(c, 2)
            sma200 = c.rolling(200).mean()
            n = len(df)
            pos = None
            for i in range(1, n):
                if pos is not None:
                    pos['held'] += 1
                    e, st, a = pos['entry'], pos['stop'], pos['atr']
                    opn, hi, lo, cl = float(o.iloc[i]), float(h.iloc[i]), float(l.iloc[i]), float(c.iloc[i])
                    if opn < st:
                        rows.append((cl - e) * pv); pos = None; continue
                    if lo <= st:
                        rows.append((st - e) * pv); pos = None; continue
                    if pos['target'] is not None and hi >= pos['target']:
                        rows.append((pos['target'] - e) * pv); pos = None; continue
                    if pos['held'] >= 5:
                        rows.append((cl - e) * pv); pos = None; continue
                    if efn(dict(rsi2=float(r2.iloc[i])), pos['held']):
                        rows.append((cl - e) * pv); pos = None
                else:
                    d = dict(close=float(c.iloc[i]), rsi2=float(r2.iloc[i]),
                             sma200=float(sma200.iloc[i]), atr=float(atr.iloc[i]))
                    if entry(d):
                        e = float(c.iloc[i]) + SLIP_PT
                        st = e - 2.0 * d['atr']
                        tg = tfn(e, d, d['atr']) if tfn else None
                        pos = dict(entry=e, stop=st, atr=d['atr'], target=tg, held=0)
            if not rows:
                print(f'    {name:26s} 0 trades')
                continue
            pnl = pd.Series(rows)
            wins = (pnl > 0).sum()
            winrate = wins / len(pnl)
            gross_w, gross_l = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
            pf = (gross_w / gross_l) if gross_l > 0 else float('inf')
            eq = pnl.cumsum()
            maxdd = (eq - eq.cummax()).min()
            print(f'    {name:26s} n={len(pnl):4d}  win%={winrate:5.1%}  PF={pf:5.2f}  '
                  f'maxDD=${maxdd:8,.0f}  avgWin=${pnl[pnl>0].mean():6,.0f} avgLoss=${pnl[pnl<0].mean():6,.0f}')


# =====================================================================
# TEST 4 — Bollinger lower-band MR with profit target
# =====================================================================
def test4_bb_pt():
    print('\n' + '=' * 70)
    print('TEST 4 — Bollinger(20,2σ) lower-band MR: profit-target exits (ES + NQ, 26y)')
    print('=' * 70)
    def entry(detail):
        return detail['close'] < detail['bb_lo']

    variants = {
        'revert-to-mid (SMA20)': (None, lambda d, held: d['close'] > d['sma20']),
        'PT +0.5%': (lambda e, d, a: e * 1.005, lambda d, held: False),
        'PT +1xATR': (lambda e, d, a: e + 1.0 * a, lambda d, held: False),
    }
    for tkr, pv in [('ES=F', ES_PV), ('NQ=F', NQ_PV)]:
        df = fetch_daily(tkr)
        print(f'\n  --- {tkr} ---')
        h, l, c, o = df['High'], df['Low'], df['Close'], df['Open']
        atr = wilder_atr(h, l, c, 14)
        sma20 = c.rolling(20).mean()
        sd20 = c.rolling(20).std()
        bb_lo = sma20 - 2 * sd20
        n = len(df)
        for name, (tfn, efn) in variants.items():
            rows = []
            pos = None
            for i in range(1, n):
                if pos is not None:
                    pos['held'] += 1
                    e, st, a = pos['entry'], pos['stop'], pos['atr']
                    opn, hi, lo, cl = float(o.iloc[i]), float(h.iloc[i]), float(l.iloc[i]), float(c.iloc[i])
                    if opn < st:
                        rows.append((cl - e) * pv); pos = None; continue
                    if lo <= st:
                        rows.append((st - e) * pv); pos = None; continue
                    if pos['target'] is not None and hi >= pos['target']:
                        rows.append((pos['target'] - e) * pv); pos = None; continue
                    if pos['held'] >= 5:
                        rows.append((cl - e) * pv); pos = None; continue
                    if efn(dict(close=cl, sma20=float(sma20.iloc[i])), pos['held']):
                        rows.append((cl - e) * pv); pos = None
                else:
                    d = dict(close=float(c.iloc[i]), bb_lo=float(bb_lo.iloc[i]),
                             atr=float(atr.iloc[i]), sma20=float(sma20.iloc[i]))
                    if not np.isnan(d['bb_lo']) and entry(d):
                        e = float(c.iloc[i]) + SLIP_PT
                        st = e - 2.0 * d['atr']
                        tg = tfn(e, d, d['atr']) if tfn else None
                        pos = dict(entry=e, stop=st, atr=d['atr'], target=tg, held=0)
            if not rows:
                print(f'    {name:26s} 0 trades'); continue
            pnl = pd.Series(rows)
            wins = (pnl > 0).sum()
            pf = (pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()) if (pnl < 0).any() else float('inf')
            eq = pnl.cumsum(); maxdd = (eq - eq.cummax()).min()
            print(f'    {name:26s} n={len(pnl):4d}  win%={wins/len(pnl):5.1%}  PF={pf:5.2f}  '
                  f'maxDD=${maxdd:8,.0f}  avgWin=${pnl[pnl>0].mean():6,.0f} avgLoss=${pnl[pnl<0].mean():6,.0f}')


# =====================================================================
# intraday data loader
# =====================================================================
def load_mes_5min():
    frames = []
    pag = boto3.client('s3', region_name='us-east-1').get_paginator('list_objects_v2')
    keys = []
    for page in pag.paginate(Bucket=BUCKET, Prefix='futures-bars/intraday/MES/5min/'):
        keys += [o['Key'] for o in page.get('Contents', [])]
    for k in keys:
        obj = S3.get_object(Bucket=BUCKET, Key=k)
        data = json.loads(obj['Body'].read())
        bars = data.get('bars', [])
        if not bars:
            continue
        df = pd.DataFrame(bars)
        df['ts'] = pd.to_datetime(df['ts'])
        frames.append(df[['ts', 'open', 'high', 'low', 'close', 'volume']])
    out = pd.concat(frames).sort_values('ts').drop_duplicates('ts').reset_index(drop=True)
    out['ts'] = pd.to_datetime(out['ts'], utc=True).dt.tz_convert(NY)
    out['date'] = out['ts'].dt.date
    return out


# =====================================================================
# TEST 2 — Opening-range fade (mean reversion)
# =====================================================================
def test2_or_fade():
    print('\n' + '=' * 70)
    print('TEST 2 — Opening-range FADE (mean reversion) on 5-min MES')
    print('=' * 70)
    df = load_mes_5min()
    print(f'  bars={len(df)}  days={df["date"].nunique()}  range={df["date"].min()}..{df["date"].max()}')
    OR_MIN = 30
    trades = []
    for date, g in df.groupby('date'):
        g = g.sort_values('ts').reset_index(drop=True)
        g['min'] = (g['ts'].dt.hour * 60 + g['ts'].dt.minute) - (9 * 60 + 30)
        orr = g[g['min'] < OR_MIN]
        if orr.empty:
            continue
        or_hi = orr['high'].max()
        or_lo = orr['low'].min()
        or_mid = (or_hi + or_lo) / 2
        post = g[g['min'] >= OR_MIN]
        atr14 = wilder_atr(g['high'], g['low'], g['close'], 14).iloc[-1]
        entered = None  # 'LONG' or 'SHORT'
        entry_px = stop = None
        for _, bar in post.iterrows():
            if entered is None:
                # fade the first break of the OR
                if bar['close'] < or_lo:   # downside break -> LONG (fade)
                    entry_px = bar['close'] - SLIP_PT
                    stop = entry_px - 1.5 * atr14
                    entered = 'LONG'
                elif bar['close'] > or_hi:  # upside break -> SHORT (fade)
                    entry_px = bar['close'] + SLIP_PT
                    stop = entry_px + 1.5 * atr14
                    entered = 'SHORT'
                if entered:
                    continue
            else:
                # manage: stop first, then target (revert to OR mid), then EOD
                if entered == 'LONG':
                    if bar['low'] <= stop:
                        trades.append((date, 'LONG', (stop - entry_px) * MES_PV)); break
                    if bar['high'] >= or_mid:
                        trades.append((date, 'LONG', (or_mid - entry_px) * MES_PV)); break
                    if bar['min'] >= 15 * 60 + 45:  # 15:45 EOD flatten
                        trades.append((date, 'LONG', (bar['close'] - entry_px) * MES_PV)); break
                else:
                    if bar['high'] >= stop:
                        trades.append((date, 'SHORT', (entry_px - stop) * MES_PV)); break
                    if bar['low'] <= or_mid:
                        trades.append((date, 'SHORT', (entry_px - or_mid) * MES_PV)); break
                    if bar['min'] >= 15 * 60 + 45:
                        trades.append((date, 'SHORT', (entry_px - bar['close']) * MES_PV)); break
    if not trades:
        print('  0 trades'); return
    tdf = pd.DataFrame(trades, columns=['date', 'side', 'pnl'])
    pnl = tdf['pnl']
    wins = (pnl > 0).sum()
    pf = (pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()) if (pnl < 0).any() else float('inf')
    eq = pnl.cumsum(); maxdd = (eq - eq.cummax()).min()
    print(f'  n={len(pnl)}  win%={wins/len(pnl):5.1%}  PF={pf:5.2f}  maxDD=${maxdd:8,.0f}  '
          f'net=${pnl.sum():,.0f}  avgWin=${pnl[pnl>0].mean():6,.0f} avgLoss=${pnl[pnl<0].mean():6,.0f}')
    print(f'  by side: LONG n={(tdf.side=="LONG").sum()} net=${tdf[tdf.side=="LONG"].pnl.sum():,.0f} | '
          f'SHORT n={(tdf.side=="SHORT").sum()} net=${tdf[tdf.side=="SHORT"].pnl.sum():,.0f}')


# =====================================================================
# TEST 3 — Time-of-day seasonality
# =====================================================================
def test3_seasonality():
    print('\n' + '=' * 70)
    print('TEST 3 — Time-of-day seasonality (avg return per 30-min bucket, 5-min MES)')
    print('=' * 70)
    df = load_mes_5min()
    df['min'] = (df['ts'].dt.hour * 60 + df['ts'].dt.minute) - (9 * 60 + 30)
    df['bucket'] = (df['min'] // 30).astype(int)  # 0=9:30-10:00, 1=10:00-10:30 ... 12=15:30-16:00
    # return = close-to-close of the bucket (buy bucket open, sell bucket close), in points
    rows = []
    for (date, b), g in df.groupby(['date', 'bucket']):
        g = g.sort_values('ts')
        if len(g) < 2:
            continue
        o = g['open'].iloc[0]
        c = g['close'].iloc[-1]
        rows.append((b, c - o))
    sdf = pd.DataFrame(rows, columns=['bucket', 'ret'])
    print('  bucket      n    avg(pts)  win%   net($, 1 MES)')
    print('  ' + '-' * 52)
    labels = ['09:30', '10:00', '10:30', '11:00', '11:30', '12:00', '12:30',
              '13:00', '13:30', '14:00', '14:30', '15:00', '15:30']
    for b in range(13):
        sub = sdf[sdf.bucket == b]
        if sub.empty:
            continue
        avg = sub['ret'].mean()
        win = (sub['ret'] > 0).mean()
        net = sub['ret'].sum() * MES_PV
        lab = labels[b] if b < len(labels) else '?'
        print(f'  {lab:>8}-next  n={len(sub):4d}  {avg:+7.2f}   {win:5.1%}   {net:+8,.0f}')


if __name__ == '__main__':
    test1_rsi2_pt()
    test4_bb_pt()
    test2_or_fade()
    test3_seasonality()
