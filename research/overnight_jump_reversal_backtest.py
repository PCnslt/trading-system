#!/usr/bin/env python3
"""Overnight PRICE-JUMP reversal — fade the vol-standardized overnight jump
(queue strat-20260908-1).

Bahcivan, Dam & Gonenc (May 2025) "Dark Side of the Day": overnight price
jumps, detected Lee-Mykland-style (overnight return standardized by LOCAL
realized vol, NOT a fixed % gap), negatively predict short-term returns in
BOTH signs; the reversal is concentrated in the subsequent DAYTIME session
and holds 1-3 trading days. A 1-month contrarian decile LOSES, so the edge is
short-horizon only.

Tradeable lane (LONG-only — Robinhood cash acct cannot short):
  jump_t = (open_t / close_{t-1} - 1) / vol_{t-1}   (vol = 21d rolling std of
  close-to-close returns, shifted 1 so no lookahead through the open).
  ENTRY at open_t when jump_t <= -Z (fade a negative jump), EXIT at the close
  H trading days later (H=1 same-day daytime, H=2, H=3). No stop (short hold).
  Positive-jump leg reported as the AVOID/SHORT side (not RH-executable).

Honest fills: multiplicative 5 bps/side primary, 10 bps/side 2x stress.
net = exit*(1-bps) / (entry*(1+bps)) - 1.  IS/OOS split at 2022-01-01.
Per-trade t AND day-clustered t (jumps cluster on market down days).
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

load_dotenv(os.path.join(_ROOT, '.env'))

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
PRICE_LO, PRICE_HI = 2.0, 50.0
DOLLAR_VOL_MIN = 5e6
OOS_FROM = '2022-01-01'
VOL_WINDOW = 21          # local realized vol window (trading days)
Z_THRESHOLDS = (2.0, 2.5, 3.0)
HORIZONS = (1, 2, 3)     # exit = close H trading days after entry open
COSTS = (0.0005, 0.0010)


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
        df['ret1'] = df['close'] / pc - 1.0                       # close-to-close
        df['on_ret'] = df['open'] / pc - 1.0                      # overnight (close->open)
        df['vol'] = df['ret1'].rolling(VOL_WINDOW).std().shift(1)  # local vol thru t-1
        df['jump'] = df['on_ret'] / df['vol']                     # vol-standardized jump
        df['dollar_vol'] = (df['close'] * df['volume']).rolling(20).mean()
        # forward open->close returns at horizons H=1,2,3 (entry at open_t)
        for h in HORIZONS:
            df[f'fwd{h}'] = df['close'].shift(-(h - 1)) / df['open'] - 1.0
        return df
    except Exception:
        return None


def stats(rets):
    r = np.asarray([x for x in rets if x == x and np.isfinite(x)], dtype=float)
    if len(r) == 0:
        return None
    w, l = r[r > 0].sum(), -r[r <= 0].sum()
    pf = w / l if l > 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 and len(r) > 1 else 0.0
    return {'n': int(len(r)), 'pf': round(pf, 3), 'win': round(float((r > 0).mean()), 3),
            'avg_bp': round(float(r.mean() * 1e4), 1), 't': round(float(t), 2)}


def day_t(rets, dates):
    """Day-clustered t: t of the cross-sectional MEAN per day."""
    s = pd.Series(rets, index=pd.to_datetime(dates))
    g = s.groupby(s.index).mean()
    g = g[g.notna()]
    if len(g) < 5 or g.std(ddof=1) == 0:
        return 0.0
    return round(float(g.mean() / (g.std(ddof=1) / np.sqrt(len(g)))), 2)


def cell(rets, dates):
    if not rets:
        return None
    isr = [r for r, d in zip(rets, dates) if pd.Timestamp(d) < pd.Timestamp(OOS_FROM)]
    oor = [r for r, d in zip(rets, dates) if pd.Timestamp(d) >= pd.Timestamp(OOS_FROM)]
    isd = [d for d in dates if pd.Timestamp(d) < pd.Timestamp(OOS_FROM)]
    ood = [d for d in dates if pd.Timestamp(d) >= pd.Timestamp(OOS_FROM)]
    out = {'all': stats(rets), 'is': stats(isr), 'oos': stats(oor)}
    out['all']['t_day'] = day_t(rets, dates)
    out['is']['t_day'] = day_t(isr, isd)
    out['oos']['t_day'] = day_t(oor, ood)
    return out


def fmt(s):
    if not s or s['n'] == 0:
        return '          n/a'
    return (f"n={s['n']:>6} PF={s['pf']:>6.3f} win={s['win']*100:>5.1f}% "
            f"avg={s['avg_bp']:>7.1f}bp t={s['t']:>5.2f} tday={s.get('t_day', 0):>5.2f}")


def gather(data, jump_lo, jump_hi, h, bps):
    """Pool forward H-day returns for names whose jump is in (jump_lo, jump_hi).

    jump_lo/jump_hi are z-scores; None = unbounded. jump_hi INCLUSIVE for the
    negative leg means jump <= jump_hi. Cost applied multiplicatively per side
    on the entry open / exit close.
    """
    rets, dates = [], []
    col = f'fwd{h}'
    for sym, df in data.items():
        m = df['jump'].notna() & df[col].notna() \
            & df['open'].between(PRICE_LO, PRICE_HI) \
            & (df['dollar_vol'] > DOLLAR_VOL_MIN)
        if jump_lo is not None:
            m = m & (df['jump'] > jump_lo)
        if jump_hi is not None:
            m = m & (df['jump'] <= jump_hi)
        sub = df.loc[m]
        for d, row in sub.iterrows():
            rets.append(row[col] * (1 - bps) / (1 + bps) - 2 * bps)  # entry+exit cost
            dates.append(d)
    return rets, dates


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

    # ---- 0) sanity: does a vol-standardized negative jump predict a bounce? ----
    print('=' * 100)
    print('#0 gross forward open->close return by jump bucket (H=1 same-day daytime)')
    print('=' * 100)
    print(f'{"bucket":>12} {"n":>7} {"avg_bp":>9} {"median_bp":>10} {"win%":>6} {"t":>6}')
    for name, lo, hi in [('jump<=-3', None, -3.0), ('-3<jump<=-2', -3.0, -2.0),
                         ('-2<jump<=-1', -2.0, -1.0), ('|jump|<1', -1.0, 1.0),
                         ('1<=jump<2', 1.0, 2.0), ('2<=jump<3', 2.0, 3.0), ('jump>=3', 3.0, None)]:
        rets, _ = gather(data, lo, hi, 1, 0.0)
        r = np.asarray(rets)
        if len(r) == 0:
            print(f'{name:>12} {0:>7}   -- no trades')
            continue
        t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 else 0.0
        print(f'{name:>12} {len(r):>7} {r.mean()*1e4:>9.1f} {np.median(r)*1e4:>10.1f} '
              f'{(r>0).mean()*100:>6.1f} {t:>6.2f}')
        out[f'bucket_{name}'] = {'n': int(len(r)), 'avg_bp': round(float(r.mean()*1e4), 1),
                                 'median_bp': round(float(np.median(r)*1e4), 1),
                                 'win': round(float((r > 0).mean()), 3), 't': round(float(t), 2)}

    # ---- 1) tradeable LONG-negative-jump lane, z-threshold x horizon sweep ----
    print('\n' + '=' * 100)
    print('#1 LONG negative-jump (fade the down-jump) — net PF by z-threshold x horizon')
    print('=' * 100)
    for bps in COSTS:
        b = f'{bps*1e4:.0f}bp'
        print(f'\n  @{b}/side:')
        for z in Z_THRESHOLDS:
            for h in HORIZONS:
                rets, dates = gather(data, None, -z, h, bps)
                c = cell(rets, dates)
                key = f'long_negjump_z{z}_h{h}_{b}'
                out[key] = c
                if c and c['all']:
                    print(f'    z<=-{z} H={h}  ALL {fmt(c["all"])}')
                    print(f'                 IS  {fmt(c["is"])}   OOS {fmt(c["oos"])}')

    # ---- 2) positive-jump AVOID leg (short not RH-executable) ----
    print('\n' + '=' * 100)
    print('#2 positive-jump names (the SHORT/AVOID side — report only, RH cannot short)')
    print('=' * 100)
    for bps in COSTS:
        b = f'{bps*1e4:.0f}bp'
        print(f'\n  @{b}/side (gross-of-cost for the AVOID evidence):')
        for z in (2.0, 3.0):
            for h in HORIZONS:
                rets, dates = gather(data, z, None, h, bps)
                c = cell(rets, dates)
                key = f'posjump_z{z}_h{h}_{b}'
                out[key] = c
                if c and c['all']:
                    print(f'    jump>={z} H={h}  ALL {fmt(c["all"])}')
                    print(f'                 IS  {fmt(c["is"])}   OOS {fmt(c["oos"])}')

    # ---- 3) unconditional baseline for the same horizon/cost ----
    print('\n' + '=' * 100)
    print('#3 unconditional baseline (all names, same filters/cost) for comparison')
    print('=' * 100)
    for h in HORIZONS:
        rets, dates = gather(data, None, None, h, COSTS[0])
        c = cell(rets, dates)
        out[f'baseline_h{h}'] = c
        if c and c['all']:
            print(f'    H={h} @5bp  ALL {fmt(c["all"])}')

    json.dump(out, open(os.path.join(_ROOT, 'research', 'overnight_jump_reversal_results.json'), 'w'),
              indent=1, default=str)
    print('\nwrote research/overnight_jump_reversal_results.json')


if __name__ == '__main__':
    main()
