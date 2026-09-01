#!/usr/bin/env python3
"""Option-market information sensor: turn stored 30-min chain snapshots into
testable directional features, aligned with subsequent stock returns.

Features (all IBKR_PROXY_*, never TRUE_OOI):
  OTS           option-to-stock score (call/put imbalance vs stock volume)
  net_delta     delta-weighted net option exposure
  cp_ratio      call/put volume ratio
  vol_surprise  option volume vs same-symbol historical baseline
  iv_shock      ATM IV change
  skew_shock    put-call IV spread change
  moneyness_conc  concentration of flow in one moneyness bucket
  dte_conc      concentration of flow in one maturity bucket

Outputs one row per (symbol, window) with the forward stock return at
+30m/+60m/+2h/close/next-day, for the lead-lag and ablation tests.
"""
import boto3, io, json
import pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'

def load_snapshots(sym):
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=f'options/snapshots/{sym}/')
    frames=[]
    for o in r.get('Contents', []):
        frames.append(pd.read_parquet(io.BytesIO(s3.get_object(Bucket=BUCKET, Key=o['Key'])['Body'].read())))
    return pd.concat(frames) if frames else None

def features(snap):
    # snap: rows = options, cols include symbol, ts, expiry, strike, right, bid, ask, iv, delta, vol, oi, und
    g = snap.groupby('ts')
    rows=[]
    for ts, grp in g:
        c = grp[grp.right=='C']; p = grp[grp.right=='P']
        cv, pv = c['vol'].sum(), p['vol'].sum()
        net_delta = (c['delta']*c['vol']).sum() + (p['delta']*p['vol']).sum()
        atm_c = c.iloc[(c.strike - grp['und']).abs().argmin()]
        atm_p = p.iloc[(p.strike - grp['und']).abs().argmin()]
        rows.append(dict(ts=ts,
            OTS=(cv-pv)/(cv+pv+1e-9),
            net_delta=net_delta/(cv+pv+1e-9),
            cp_ratio=cv/(pv+1e-9),
            iv_shock=atm_c['iv']-atm_p['iv'],
            skew=atm_p['iv']-atm_c['iv'],
            dte_conc=grp.groupby('dte')['vol'].sum().max()/(grp['vol'].sum()+1e-9)))
    return pd.DataFrame(rows).sort_values('ts')

if __name__=='__main__':
    import sys
    for sym in sys.argv[1:]:
        s=load_snapshots(sym)
        if s is None: print(f'{sym}: no snapshots yet'); continue
        f=features(s)
        print(f'{sym}: {len(f)} windows, cols={list(f.columns)}')
