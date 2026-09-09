#!/usr/bin/env python3
"""Market-level ORDER-IMBALANCE reversal (order-flow channel, not price-only)
(queue strat-20260908-2).

Chordia, Roll & Subrahmanyam (2002) JFE 65(1):111-130 — lag-1 daily order
imbalance autocorr 0.465, and corr(R_t, R_{t-1} | R_{t-1} < -1%) = -0.304:
big down days REVERSE, and the reversal is carried by order imbalance, not
price alone.

Approximate daily dollar order imbalance from IBKR index-futures 5-min bars
(Lee-Ready tick rule, no quotes available):
  OIB_t = sum( sign(bar) * $volume ) / sum( $volume ),  $volume = vol * close,
  sign = +1 if close > prev_close (buyer-initiated), -1 if close < prev_close.
LONG ES/MES/NQ at the NEXT open after a big down day (R_{t-1} < -1%) with
NEGATIVE order imbalance (OIB_{t-1} < 0), EXIT at the same day's close (1 day).
Also test the unconditional next-day imbalance -> return sign, and whether the
imbalance gate adds anything over the price-only down-day bounce.

Cost: index futures round trip = 2*slip_ticks*tick + 2*commission, reported as
1-tick/side slip (ES/MES/NQ tick 0.25) + IBKR retail commission, plus a 2-tick
stress. Gross and net.  Data is ~1y of RTH 5-min bars (ES 181 sessions), so
n is small and IS/OOS is a 60/40 chronological split — flagged honestly.

READ-ONLY: S3 get_object only.
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

import intraday_validate as IV

S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

SPECS = {  # (mult $/point, tick, commission $/side)
    'ES':  (50.0,  0.25, 1.60),
    'MES': (5.0,   0.25, 0.62),
    'NQ':  (20.0,  0.25, 1.60),
}
SYMS = ['ES', 'MES', 'NQ']
TF = '5min'
DOWN_THRESH = 0.01      # R_{t-1} < -1%
OOS_FRAC = 0.6          # 60/40 chronological split


def daily_series(df):
    """Aggregate RTH 5-min bars to daily: OIB (tick rule) + close-to-close return.

    Returns a DataFrame indexed by session date with columns
    [open, close, ret, oib].
    """
    d = df.copy()
    d['day'] = pd.to_datetime(d['day']).astype(str)
    d['px'] = d['close'].astype(float)
    d['vol'] = d['volume'].astype(float).fillna(0.0)
    d['dvol'] = d['px'] * d['vol']
    # Lee-Ready tick rule: buyer-initiated if close > prev close
    prev_close = d['px'].shift(1)
    sign = np.where(d['px'] > prev_close, 1.0, np.where(d['px'] < prev_close, -1.0, 0.0))
    d['signed_dvol'] = sign * d['dvol']

    rows = []
    for day, g in d.groupby('day'):
        o = g['open'].astype(float).iloc[0]
        c = g['px'].iloc[-1]
        tot = g['dvol'].sum()
        oib = (g['signed_dvol'].sum() / tot) if tot > 0 else np.nan
        rows.append((pd.Timestamp(day), o, c, oib))
    out = pd.DataFrame(rows, columns=['date', 'open', 'close', 'oib']).set_index('date').sort_index()
    out['ret'] = out['close'] / out['close'].shift(1) - 1.0
    out['oib_lag'] = out['oib'].shift(1)
    out['ret_lag'] = out['ret'].shift(1)
    # next-day trade: enter at open_t (same day), exit at close_t (same day)
    return out


def load_sym(sym):
    df = IV.load_intraday(sym, TF)
    if df is None or len(df) == 0:
        return None
    return daily_series(df)


def stats(rets_bp):
    r = np.asarray(rets_bp, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) == 0:
        return None
    w, l = r[r > 0].sum(), -r[r <= 0].sum()
    pf = w / l if l > 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 and len(r) > 1 else 0.0
    return {'n': int(len(r)), 'pf': round(pf, 3), 'win': round(float((r > 0).mean()), 3),
            'avg_bp': round(float(r.mean()), 1), 't': round(float(t), 2)}


def trade_returns(daily, down_thresh, oib_hi, mult, tick, comm, slip_ticks):
    """LONG next open (same day) after a down day w/ OIB <= oib_hi; exit close.

    Returns list of (net_bp, date) tuples. oib_hi=None -> price-only gate.
    """
    out = []
    m = daily['ret_lag'].notna() & (daily['ret_lag'] < -down_thresh) \
        & daily['open'].notna() & daily['close'].notna()
    if oib_hi is not None:
        m = m & daily['oib_lag'].notna() & (daily['oib_lag'] <= oib_hi)
    sub = daily.loc[m]
    for d, row in sub.iterrows():
        gross_bp = (row['close'] / row['open'] - 1.0) * 1e4
        slip_bp = 2 * slip_ticks * tick / row['open'] * 1e4
        comm_bp = 2 * comm / (mult * row['open']) * 1e4
        net_bp = gross_bp - slip_bp - comm_bp
        out.append((net_bp, d))
    return out


def cell(trades):
    if not trades:
        return None
    rets = [t[0] for t in trades]
    dates = [t[1] for t in trades]
    all_r = stats(rets)
    cut = sorted(set(dates))[int(len(set(dates)) * OOS_FRAC)] if len(set(dates)) > 2 else None
    if cut:
        isr = [t[0] for t in trades if t[1] < cut]
        oor = [t[0] for t in trades if t[1] >= cut]
    else:
        isr, oor = rets, []
    return {'all': all_r, 'is': stats(isr), 'oos': stats(oor) if oor else None}


def fmt(s):
    if not s or s['n'] == 0:
        return '          n/a'
    return (f"n={s['n']:>4} PF={s['pf']:>6.3f} win={s['win']*100:>5.1f}% "
            f"avg={s['avg_bp']:>7.1f}bp t={s['t']:>5.2f}")


def main():
    out = {}
    print(f'loading {TF} futures bars from S3 (RTH) for {SYMS}…', flush=True)
    series = {}
    for sym in SYMS:
        try:
            s = load_sym(sym)
            if s is None or len(s) == 0:
                print(f'  {sym}: no data', flush=True)
                continue
            series[sym] = s
            print(f'  {sym}: {len(s)} sessions  {s.index[0].date()} .. {s.index[-1].date()}', flush=True)
        except Exception as e:
            print(f'  {sym}: ERROR {e}', flush=True)

    for sym in SYMS:
        daily = series.get(sym)
        if daily is None or len(daily) < 30:
            continue
        mult, tick, comm = SPECS[sym]
        print('\n' + '=' * 96)
        print(f'{sym}  ({len(daily)} sessions)  — order-imbalance reversal')
        print('=' * 96)

        # (a) unconditional next-day return vs prior-day OIB sign
        pos = daily[daily['oib_lag'] > 0]['ret']
        neg = daily[daily['oib_lag'] < 0]['ret']
        print('  (a) next-day close-to-close return by prior-day OIB sign (gross, bp):')
        for lbl, s in [('OIB>0', pos), ('OIB<0', neg)]:
            if len(s):
                print(f'      {lbl:>6} n={len(s):>4} avg={s.mean()*1e4:>7.1f}bp '
                      f'median={s.median()*1e4:>7.1f}bp win={(s>0).mean()*100:>5.1f}%')
                out[f'{sym}_oibsign_{lbl}'] = {'n': int(len(s)),
                                               'avg_bp': round(float(s.mean()*1e4), 1),
                                               'median_bp': round(float(s.median()*1e4), 1),
                                               'win': round(float((s > 0).mean()), 3)}

        # (b) reversal correlation on down days
        dn = daily[daily['ret_lag'] < -DOWN_THRESH]
        if len(dn) >= 5:
            corr = dn['ret'].corr(dn['ret_lag'])
            print(f'  (b) corr(R_t, R_{{t-1}} | R_{{t-1}} < -1%) = {corr:+.3f}  (n={len(dn)}) '
                  f'[paper: -0.304]')
            out[f'{sym}_down_rev_corr'] = {'n': int(len(dn)), 'corr': round(float(corr), 3)}

        # (c) tradeable lane: price-only vs imbalance-gated, at 0/1/2 tick slip
        print('  (c) LONG next open, exit close — price-only (R<-1%) vs '
              '+OIB<=0 gate; net of 2 x slip-ticks + comm (1t and 2t):')
        for gate_lbl, oib_hi in [('price-only', None), ('+OIB<=0', 0.0),
                                 ('+OIB<=-0.2', -0.2), ('+OIB<=-0.3', -0.3)]:
            for slip in (1, 2):
                tr = trade_returns(daily, DOWN_THRESH, oib_hi, mult, tick, comm, slip)
                c = cell(tr)
                key = f'{sym}_gate_{gate_lbl}_slip{slip}'
                out[key] = c
                if c and c['all'] and c['all']['n'] >= 3:
                    print(f'      {gate_lbl:>11} @{slip}t  ALL {fmt(c["all"])}'
                          f'   IS {fmt(c["is"]) if c["is"] else ""}   OOS {fmt(c["oos"]) if c["oos"] else ""}')
                else:
                    print(f'      {gate_lbl:>11} @{slip}t  n<3 (insufficient)')

        # (d) gross price-only down-day bounce benchmark (no cost)
        tr0 = trade_returns(daily, DOWN_THRESH, None, mult, tick, comm, 0)
        r0 = [t[0] for t in tr0]
        print(f'  (d) price-only down-day bounce GROSS: n={len(r0)} avg={np.mean(r0):.1f}bp '
              f'win={100*(np.mean(np.asarray(r0)>0)):.1f}%')
        out[f'{sym}_down_bounce_gross'] = {'n': int(len(r0)),
                                           'avg_bp': round(float(np.mean(r0)), 1)}

    json.dump(out, open(os.path.join(_ROOT, 'research', 'order_imbalance_reversal_results.json'), 'w'),
              indent=1, default=str)
    print('\nwrote research/order_imbalance_reversal_results.json')


if __name__ == '__main__':
    main()
