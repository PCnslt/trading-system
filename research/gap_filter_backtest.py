#!/usr/bin/env python3
"""Gap-down filter on the surviving RSI2 / Broken-Arrow mean-reversion lanes
(queue strat-20260901-2).

Cesar Alvarez (AlvarezQuantTrading) "Avoiding Gap Trades": skip any setup where
the stock gapped down >= 5% within the last 10 trading days -- recent gap-down
names are falling-knife continuation, not reversion. Claimed +28% CAR / +25%
avg P/L for only -6% trade count.

A/B the filter against the UNCONDITIONAL lanes on the deployed sub-$50 universe:
  1. RSI2<5 (Lane 1, via stock_mr_engine.run_symbol, next-open entry, 2xATR stop,
     5d/revert) -- gate = NOT(gapped down >=5% in last 10 trading days).
  2. BROKEN-ARROW (Lane 47: close > rising 40MA, close down >= 8%/10%, enter that
     close, exit next open) -- same gap-down skip.

gap-down def: open / prev_close - 1 <= -5% on ANY of the last 10 trading days
(incl. the signal day), rolling 10-day window, no lookahead.

Honest fills: multiplicative 5 bps/side primary, 10 bps/side 2x stress.
net = exit*(1-bps) / (entry*(1+bps)) - 1.  IS/OOS split at 2022-01-01.
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
RSI2_THR = 5.0
GAP_PCT = 0.05       # gap-down >= 5%
GAP_WINDOW = 10      # within the last 10 trading days
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
        df['ret1'] = df['close'] / pc - 1.0                     # close-to-close today
        df['c2o'] = df['open'].shift(-1) / df['close'] - 1.0    # close -> next open
        df['next_open'] = df['open'].shift(-1)
        df['ma40'] = df['close'].rolling(40).mean()
        df['ma40_rising'] = df['ma40'] > df['ma40'].shift(1)
        df['dollar_vol'] = (df['close'] * df['volume']).rolling(20).mean()
        df['gap'] = df['open'] / pc - 1.0
        # True if a >=5% gap-down occurred on ANY of the last 10 trading days
        df['gapdown10'] = (df['gap'] <= -GAP_PCT).rolling(GAP_WINDOW, min_periods=1).max().astype(bool)
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


def rsi2(data, skip_gapdown, bps):
    """RSI2<5 next-open, 2xATR stop + 5d/revert. skip_gapdown -> gate NOT gapdown10."""
    rets, dates = [], []
    for sym, df in data.items():
        gate = (~df['gapdown10']) if skip_gapdown else None
        for t in E.run_symbol(df, sym, RSI2_THR, 'fixed', gate=gate):
            px = t['entry_price']
            if not (PRICE_LO <= px <= PRICE_HI):
                continue
            dvol = float((df['close'] * df['volume']).rolling(20).mean().iloc[t['entry_i']])
            if dvol < DOLLAR_VOL_MIN or np.isnan(dvol):
                continue
            rets.append(t['exit_price'] * (1 - bps) / (px * (1 + bps)) - 1.0)
            dates.append(t['entry_date'])
    return rets, dates


def broken_arrow(data, drop, skip_gapdown, bps):
    """Close->next-open dip-buy (Lane 47). skip_gapdown -> require NOT gapdown10."""
    rets, dates = [], []
    for sym, df in data.items():
        setup = (df['close'].shift(1) > df['ma40'].shift(1)) & df['ma40_rising'].shift(1)
        m = (setup & (df['ret1'] <= -drop) & df['close'].between(PRICE_LO, PRICE_HI)
             & df['c2o'].notna() & (df['dollar_vol'] > DOLLAR_VOL_MIN))
        if skip_gapdown:
            m = m & (~df['gapdown10'])
        sub = df.loc[m]
        for d, row in sub.iterrows():
            rets.append(row['next_open'] * (1 - bps) / (row['close'] * (1 + bps)) - 1.0)
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

    print('=' * 96)
    print('#1 RSI2<5  — skip gap-down >=5% in last 10d (gate) vs unconditional')
    print('=' * 96)
    for bps in COSTS:
        b = f'{bps*1e4:.0f}bp'
        print(f'\n  @{b}/side:')
        base = cell(*rsi2(data, False, bps))
        filt = cell(*rsi2(data, True, bps))
        print(f'    unconditional  {fmt(base["all"]) if base else "n/a"}')
        print(f'                    IS {fmt(base["is"]) if base else ""}   OOS {fmt(base["oos"]) if base else ""}')
        print(f'    skip-gapdown   {fmt(filt["all"]) if filt else "n/a"}')
        print(f'                    IS {fmt(filt["is"]) if filt else ""}   OOS {fmt(filt["oos"]) if filt else ""}')
        if base and filt and base['all'] and filt['all']:
            d = filt['all']['avg_bp'] - base['all']['avg_bp']
            do = (filt['oos']['avg_bp'] - base['oos']['avg_bp']) if base['oos'] and filt['oos'] else float('nan')
            dn = (filt['all']['n'] / base['all']['n'] - 1) * 100
            print(f'    Δ filtered-vs-base  avg {d:+.1f}bp   OOS {do:+.1f}bp   nΔ {dn:+.1f}%')
        out[f'rsi2_base_{b}'] = base
        out[f'rsi2_skipgap_{b}'] = filt

    print('\n' + '=' * 96)
    print('#2 BROKEN-ARROW  — skip gap-down >=5% in last 10d vs unconditional')
    print('=' * 96)
    for drop in (0.08, 0.10):
        for bps in COSTS:
            b = f'{bps*1e4:.0f}bp'
            print(f'\n  drop <= {-drop*100:.0f}%   @{b}/side:')
            base = cell(*broken_arrow(data, drop, False, bps))
            filt = cell(*broken_arrow(data, drop, True, bps))
            print(f'    unconditional  {fmt(base["all"]) if base else "n/a"}')
            print(f'                    IS {fmt(base["is"]) if base else ""}   OOS {fmt(base["oos"]) if base else ""}')
            print(f'    skip-gapdown   {fmt(filt["all"]) if filt else "n/a"}')
            print(f'                    IS {fmt(filt["is"]) if filt else ""}   OOS {fmt(filt["oos"]) if filt else ""}')
            if base and filt and base['all'] and filt['all']:
                d = filt['all']['avg_bp'] - base['all']['avg_bp']
                do = (filt['oos']['avg_bp'] - base['oos']['avg_bp']) if base['oos'] and filt['oos'] else float('nan')
                dn = (filt['all']['n'] / base['all']['n'] - 1) * 100
                print(f'    Δ filtered-vs-base  avg {d:+.1f}bp   OOS {do:+.1f}bp   nΔ {dn:+.1f}%')
            out[f'ba_drop{int(drop*100)}_base_{b}'] = base
            out[f'ba_drop{int(drop*100)}_skipgap_{b}'] = filt

    json.dump(out, open(os.path.join(_ROOT, 'research', 'gap_filter_results.json'), 'w'),
              indent=1, default=str)
    print('\nwrote research/gap_filter_results.json')


if __name__ == '__main__':
    main()
