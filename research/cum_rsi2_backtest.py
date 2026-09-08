#!/usr/bin/env python3
"""Cumulative RSI(2) mean-reversion (queue strat-20260901-1).

Connors & Alvarez 2008 "Short Term Trading Strategies That Work" + Quantitativo
2024-06-22 "Squeezing more profits with cumulative RSI": cum-RSI(2,2) = RSI(2) of
today PLUS RSI(2) of yesterday; entry when cum-RSI(2,2) < 10 AND close > 200-day
SMA. Claimed +1.0% expected return / 65% win vs vanilla RSI2<5 (+0.6% / 74% win).

A/B vs the DEPLOYED vanilla RSI2<5 lane on the SAME sub-$50 universe, same exits.
  vanilla : rsi2 < 5,  close > SMA200, next-open entry
  cum-RSI : rsi2 + rsi2.shift(1) < 10,  close > SMA200, next-open entry
Exit (house style, identical across both): 2xATR(14) hard stop (gap-aware) ->
5-day time stop -> revert (close > SMA5 OR RSI2 > hi). hi = 70 (vanilla, engine
default) / 65 (cum-RSI, per the article's published exit).

Honest fills: multiplicative 5 bps/side primary, 10 bps/side 2x stress.
net = exit*(1-bps) / (entry*(1+bps)) - 1.  IS/OOS split at 2022-01-01 (Lane-1
anchor). Universe: research/smallcap_universe_full.json (sub-$50), dollar-vol
> $5M, RSI2 computed via research/stock_mr_engine.py (the exact engine the live
bot mirrors).
"""
from __future__ import annotations

import io, os, sys, json
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'research'))

import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv

import stock_mr_engine as E

load_dotenv(os.path.join(_ROOT, '.env'))

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
PRICE_LO, PRICE_HI = 2.0, 50.0
DOLLAR_VOL_MIN = 5e6
OOS_FROM = '2022-01-01'
MAX_HOLD = 5
STOP_ATR = 2.0
COSTS = (0.0005, 0.0010)   # 5 bps, 10 bps per side


def load(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 300:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        df = df[df['close'] > 0]
        return df
    except Exception:
        return None


def run(df, cum: bool, hi_thr: float):
    """Bar-by-bar mean-reversion walker mirroring stock_mr_engine._stop_exit.

    Returns list of {entry_date, entry_i, entry_price, exit_i, exit_price, reason}.
    Entry signal computed at bar i close, filled at bar i+1 open.
    """
    d = E.indicators(df)
    n = len(d)
    o = d['open'].to_numpy()
    h = d['high'].to_numpy()
    l = d['low'].to_numpy()
    c = d['close'].to_numpy()
    rsi2 = d['rsi2'].to_numpy()
    sma5 = d['sma5'].to_numpy()
    sma200 = d['sma200'].to_numpy()
    atr14 = d['atr14'].to_numpy()

    trades = []
    i = 200
    while i < n - 1:
        above = c[i] > sma200[i] and not np.isnan(sma200[i])
        if cum:
            sig = (rsi2[i] + rsi2[i - 1]) < 10.0
        else:
            sig = rsi2[i] < 5.0
        if sig and above:
            entry_i = i + 1
            entry_price = float(o[entry_i])
            if entry_price > 0 and not np.isnan(entry_price):
                stop = entry_price - STOP_ATR * atr14[entry_i]
                exit_i = exit_price = None
                reason = 'end'
                for j in range(entry_i, n):
                    if l[j] <= stop:
                        exit_i, exit_price, reason = j, float(o[j] if o[j] < stop else stop), 'stop'
                        break
                    if j - entry_i >= MAX_HOLD:
                        exit_i, exit_price, reason = j, float(c[j]), 'time'
                        break
                    if c[j] > sma5[j] or rsi2[j] > hi_thr:
                        exit_i, exit_price, reason = j, float(c[j]), 'revert'
                        break
                if exit_i is None:
                    exit_i, exit_price = n - 1, float(c[n - 1])
                trades.append({
                    'entry_date': d.index[entry_i], 'entry_i': entry_i,
                    'entry_price': entry_price, 'exit_i': exit_i,
                    'exit_price': exit_price, 'reason': reason,
                    'hold_days': int(exit_i - entry_i),
                })
                i = exit_i + 1
                continue
        i += 1
    return trades


def apply_cost(trades, df, bps):
    rets, dates = [], []
    dollar_vol = (df['close'] * df['volume']).rolling(20).mean()
    for t in trades:
        px = t['entry_price']
        if not (PRICE_LO <= px <= PRICE_HI):
            continue
        dvol = float(dollar_vol.iloc[t['entry_i']])
        if dvol < DOLLAR_VOL_MIN or np.isnan(dvol):
            continue
        rets.append(t['exit_price'] * (1 - bps) / (px * (1 + bps)) - 1.0)
        dates.append(t['entry_date'])
    return rets, dates


def stats(rets):
    r = np.asarray([x for x in rets if x == x and np.isfinite(x)], dtype=float)
    if len(r) == 0:
        return None
    w, l = r[r > 0].sum(), -r[r <= 0].sum()
    pf = w / l if l > 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 and len(r) > 1 else 0.0
    return {'n': int(len(r)), 'pf': round(pf, 3), 'win': round(float((r > 0).mean()), 3),
            'avg_bp': round(float(r.mean() * 1e4), 1), 't': round(float(t), 2)}


def cell(rets, dates):
    if not rets:
        return None
    isr = [r for r, d in zip(rets, dates) if d < pd.Timestamp(OOS_FROM)]
    oor = [r for r, d in zip(rets, dates) if d >= pd.Timestamp(OOS_FROM)]
    return {'all': stats(rets), 'is': stats(isr), 'oos': stats(oor)}


def fmt(s):
    if not s or s['n'] == 0:
        return '          n/a'
    return (f"n={s['n']:>6} PF={s['pf']:>6.3f} win={s['win']*100:>5.1f}% "
            f"avg={s['avg_bp']:>7.1f}bp t={s['t']:>5.2f}")


def main():
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')))['symbols']))
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)} symbols from S3…', flush=True)
    with ThreadPoolExecutor(max_workers=24) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)}   {min(d.index[0] for d in data.values()).date()}'
          f' .. {max(d.index[-1] for d in data.values()).date()}\n', flush=True)

    out = {}

    # collect raw trades once per variant (cost-free), then apply costs
    for variant, cum, hi in (('vanilla_RSI2<5', False, 70.0), ('cumRSI(2,2)<10', True, 65.0)):
        raw = {s: run(df, cum, hi) for s, df in data.items()}
        n_raw = sum(len(v) for v in raw.values())
        out[variant] = {'n_raw': n_raw, 'costs': {}}
        for bps in COSTS:
            rets, dates = [], []
            for s, df in data.items():
                r, dd = apply_cost(raw[s], df, bps)
                rets += r
                dates += dd
            out[variant]['costs'][f'{bps*1e4:.0f}bp'] = cell(rets, dates)

    print('=' * 96)
    print('cumulative RSI(2,2)<10  vs  deployed vanilla RSI2<5   (same exits, sub-$50)')
    print('=' * 96)
    for bps in COSTS:
        b = f'{bps*1e4:.0f}bp'
        print(f'\n  @{b}/side:')
        v = out['vanilla_RSI2<5']['costs'][b]
        c = out['cumRSI(2,2)<10']['costs'][b]
        print(f"    vanilla RSI2<5     {fmt(v['all']) if v else 'n/a'}")
        print(f"                        IS {fmt(v['is']) if v else ''}   OOS {fmt(v['oos']) if v else ''}")
        print(f"    cum RSI(2,2)<10    {fmt(c['all']) if c else 'n/a'}")
        print(f"                        IS {fmt(c['is']) if c else ''}   OOS {fmt(c['oos']) if c else ''}")
        if v and c and v['all'] and c['all']:
            d = c['all']['avg_bp'] - v['all']['avg_bp']
            do = (c['oos']['avg_bp'] - v['oos']['avg_bp']) if c['oos'] and v['oos'] else float('nan')
            print(f"    Δ cum-vs-vanilla   avg {d:+.1f}bp   OOS {do:+.1f}bp")

    json.dump(out, open(os.path.join(_ROOT, 'research', 'cum_rsi2_results.json'), 'w'),
              indent=1, default=str)
    print('\nwrote research/cum_rsi2_results.json')


if __name__ == '__main__':
    main()
