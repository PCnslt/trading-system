#!/usr/bin/env python3
"""PTH (price-to-52-week-high) + turnover conditioning on the 1-5d reversal/momentum
family — queue strat-20260909-2.

Chen, Stivers & Sun (2024, J. Empirical Finance 101556): short-horizon REVERSAL
declines with turnover + PTH and shifts to MOMENTUM (continuation) for high-turnover +
high-PTH names; reversal is strongest in low-PTH + low-turnover names (PTH-anchoring
underreaction + liquidity-provision channels).

Two tests on the deployed sub-$50 universe (2006-2026, OOS from 2022):
  (a) FILTER on the surviving RSI2<5 lane: restrict buys to low-PTH / low-PTH+low-turnover
      names; expect higher OOS PF vs unconditional.
  (b) STANDALONE short-horizon continuation leg in high-PTH + high-turnover names
      (buy next open after a >= +2% up day, hold 1/3/5d) + a gross quadrant summary.

PTH = close / max(close, 252d)  [exact].
turnover: true share turnover = volume/shares_outstanding is NOT available point-in-time
for free on this universe (FMP fundamentals = SPY/QQQ/indexes only; no per-stock shares-
outstanding history in the datalake). PROXY used here = 20d mean dollar volume
(close x volume), ranked cross-sectionally into terciles each day. Documented limitation:
dollar volume conflates price level + size with turnover; the turnover dimension is
indicative, the PTH dimension is exact.

Honest fills: multiplicative 5 bps/side primary, 10 bps/side 2x stress.
net = exit*(1-bps)/(entry*(1+bps)) - 1.  IS/OOS split at 2022-01-01.
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
PTH_LO = 0.80      # "low PTH"  = >= 20% below 52w high
PTH_HI = 0.90      # "high PTH" = within 10% of 52w high
UP_THR = 0.02      # "strong up day" for the continuation trigger
COSTS = (0.0005, 0.0010)
HORIZONS = (1, 3, 5)


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
        df['ret1'] = df['close'] / pc - 1.0
        df['pth'] = df['close'] / df['close'].rolling(252).max()
        df['dollar_vol'] = (df['close'] * df['volume']).rolling(20).mean()
        # continuation-leg forward returns: enter open_{t+1}, exit close_{t+H}
        nxt_open = df['open'].shift(-1)
        for h in HORIZONS:
            df[f'fwd{h}'] = df['close'].shift(-h) / nxt_open - 1.0
        df['fwd5cc'] = df['close'].shift(-5) / df['close'] - 1.0  # 5d close-to-close
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
    if out['all']:
        out['all']['t_day'] = day_t(rets, dates)
    if out['is']:
        out['is']['t_day'] = day_t(isr, isd)
    if out['oos']:
        out['oos']['t_day'] = day_t(oor, ood)
    return out


def fmt(s):
    if not s or s['n'] == 0:
        return '        n/a'
    return (f"n={s['n']:>6} PF={s['pf']:>6.3f} win={s['win']*100:>5.1f}% "
            f"avg={s['avg_bp']:>7.1f}bp t={s['t']:>5.2f} tday={s.get('t_day', 0):>5.2f}")


def rsi2_net(data, bps, gate_for):
    """RSI2<5 next-open, 2xATR stop + 5d/revert, with an optional per-symbol gate."""
    rets, dates = [], []
    for sym, df in data.items():
        gate = gate_for(sym, df)
        for t in E.run_symbol(df, sym, 5, 'fixed', gate=gate):
            px = t['entry_price']
            if not (PRICE_LO <= px <= PRICE_HI):
                continue
            dvol = float((df['close'] * df['volume']).rolling(20).mean().iloc[t['entry_i']])
            if dvol < DOLLAR_VOL_MIN or np.isnan(dvol):
                continue
            rets.append(t['exit_price'] * (1 - bps) / (px * (1 + bps)) - 1.0)
            dates.append(t['entry_date'])
    return rets, dates


def continuation_net(data, high_to, bps, h):
    """Standalone momentum leg: in high-PTH + high-turnover names, LONG next open
    after a >= +2% up day, exit close H days later."""
    rets, dates = [], []
    col = f'fwd{h}'
    for sym, df in data.items():
        ht = high_to[sym]
        m = (df['ret1'] >= UP_THR) & (df['pth'] > PTH_HI) & ht \
            & df[col].notna() & df['dollar_vol'].notna() \
            & (df['dollar_vol'] > DOLLAR_VOL_MIN) \
            & df['open'].shift(-1).between(PRICE_LO, PRICE_HI)
        sub = df.loc[m]
        for d, row in sub.iterrows():
            rets.append((1 + row[col]) * (1 - bps) / (1 + bps) - 1.0)
            dates.append(d)
    return rets, dates


def quadrants(data, low_to, high_to):
    """Gross fwd5d close-to-close return by PTH x turnover quadrant and move direction
    (pooled across all symbols)."""
    from collections import defaultdict
    pools = defaultdict(list)
    for sym, df in data.items():
        lt, ht = low_to[sym], high_to[sym]
        quads = {'loPTH/loTO': (df['pth'] < PTH_LO) & lt,
                 'loPTH/hiTO': (df['pth'] < PTH_LO) & ht,
                 'hiPTH/loTO': (df['pth'] > PTH_HI) & lt,
                 'hiPTH/hiTO': (df['pth'] > PTH_HI) & ht}
        for quad, mask in quads.items():
            up = mask & (df['ret1'] >= UP_THR) & df['fwd5cc'].notna()
            dn = mask & (df['ret1'] <= -UP_THR) & df['fwd5cc'].notna()
            if up.sum():
                pools[(quad, 'UP>=+2%')].extend(df.loc[up, 'fwd5cc'].tolist())
            if dn.sum():
                pools[(quad, 'DN<=-2%')].extend(df.loc[dn, 'fwd5cc'].tolist())
    rows = []
    for (quad, move) in sorted(pools):
        v = np.asarray(pools[(quad, move)])
        rows.append((quad, move, float(v.mean() * 1e4), int(len(v))))
    return rows


def main():
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')))['symbols']))
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)} symbols from S3…', flush=True)
    with ThreadPoolExecutor(max_workers=24) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)}   '
          f'{min(d.index[0] for d in data.values()).date()} .. '
          f'{max(d.index[-1] for d in data.values()).date()}', flush=True)

    # cross-sectional turnover (dollar-vol) terciles, ranked each day
    dv = pd.DataFrame({s: d['dollar_vol'] for s, d in data.items()})
    rk = dv.rank(axis=1, pct=True)
    low_to = {s: (rk[s] < 1 / 3).reindex(d.index).fillna(False) for s, d in data.items()}
    high_to = {s: (rk[s] > 2 / 3).reindex(d.index).fillna(False) for s, d in data.items()}

    out = {}

    # ---- (a) RSI2<5 filter A/B ----
    gates = {
        'unconditional': lambda s, d: None,
        'low-PTH (<0.80)': lambda s, d: (d['pth'] < PTH_LO),
        'high-PTH (>0.90)': lambda s, d: (d['pth'] > PTH_HI),
        'low-PTH + lo-turnover': lambda s, d: (d['pth'] < PTH_LO) & low_to[s],
        'high-PTH + hi-turnover': lambda s, d: (d['pth'] > PTH_HI) & high_to[s],
    }
    print('=' * 100)
    print('#a RSI2<5  — PTH / PTH+turnover gates vs unconditional')
    print('=' * 100)
    for bps in COSTS:
        b = f'{bps*1e4:.0f}bp'
        print(f'\n  @{b}/side:')
        base = None
        for name, gf in gates.items():
            c = cell(*rsi2_net(data, bps, gf))
            out[f'rsi2_{name.replace(" ", "").replace("(", "").replace(")", "").replace("<", "lt").replace(">", "gt")}_{b}'] = c
            if name == 'unconditional':
                base = c
            print(f'    {name:<24} ALL {fmt(c["all"]) if c else "n/a"}')
            print(f'                      IS  {fmt(c["is"]) if c else ""}   OOS {fmt(c["oos"]) if c else ""}')
            if name != 'unconditional' and base and c and base['oos'] and c['oos'] and base['oos']['n'] and c['oos']['n']:
                d_oos = c['oos']['pf'] - base['oos']['pf']
                d_avg = c['all']['avg_bp'] - base['all']['avg_bp']
                dn = (c['all']['n'] / base['all']['n'] - 1) * 100
                print(f'        Δ vs unconditional  OOS PF {d_oos:+.3f}   avg {d_avg:+.1f}bp   n {dn:+.1f}%')

    # ---- (b) standalone continuation leg + quadrant summary ----
    print('\n' + '=' * 100)
    print('#b high-PTH + high-turnover continuation leg (LONG next open after >= +2% up day)')
    print('=' * 100)
    for bps in COSTS:
        b = f'{bps*1e4:.0f}bp'
        print(f'\n  @{b}/side:')
        for h in HORIZONS:
            c = cell(*continuation_net(data, high_to, bps, h))
            out[f'cont_hiPTH_hiTO_h{h}_{b}'] = c
            print(f'    H={h}  ALL {fmt(c["all"]) if c else "n/a"}')
            print(f'           IS  {fmt(c["is"]) if c else ""}   OOS {fmt(c["oos"]) if c else ""}')

    # unconditional up-day continuation baseline (all names, ret1 >= +2%)
    print('\n  baseline: unconditional up-day continuation (all names, ret1 >= +2%)')
    for bps in COSTS:
        b = f'{bps*1e4:.0f}bp'
        for h in HORIZONS:
            rets, dates = [], []
            for sym, df in data.items():
                col = f'fwd{h}'
                m = (df['ret1'] >= UP_THR) & df[col].notna() & (df['dollar_vol'] > DOLLAR_VOL_MIN) \
                    & df['open'].shift(-1).between(PRICE_LO, PRICE_HI)
                sub = df.loc[m]
                for d, row in sub.iterrows():
                    rets.append((1 + row[col]) * (1 - bps) / (1 + bps) - 1.0)
                    dates.append(d)
            c = cell(rets, dates)
            out[f'cont_uncond_h{h}_{b}'] = c
            print(f'    H={h} @{b}/side  ALL {fmt(c["all"]) if c else "n/a"}   OOS {fmt(c["oos"]) if c else ""}')

    # quadrant gross summary
    print('\n' + '=' * 100)
    print('#c gross fwd5d close-to-close return by PTH x turnover quadrant (the "flip")')
    print('=' * 100)
    q = quadrants(data, low_to, high_to)
    print(f'    {"quadrant":<14} {"move":>10} {"fwd5d_bp":>9} {"n":>6}')
    for quad, move, bp, n in q:
        print(f'    {quad:<14} {move:>10} {bp:>9.1f} {n:>6}')
        out[f'quad_{quad.replace("/", "_")}_{move}'] = {'bp': round(bp, 1), 'n': n}

    json.dump(out, open(os.path.join(_ROOT, 'research', 'pth_turnover_results.json'), 'w'),
              indent=1, default=str)
    print('\nwrote research/pth_turnover_results.json')


if __name__ == '__main__':
    main()
