#!/usr/bin/env python3
"""Diagnose outliers in buyback drift + winsorized robustness."""
import json, re, io
import pandas as pd
import numpy as np
import boto3

BUCKET = 'trading-datalake-920641308584'
s3 = boto3.client('s3', region_name='us-east-1')
HITS = '/tmp/buyback_fts_hits.jsonl'
UNIV = '/tmp/universe_syms.json'
HOLD = 20; COST_BP = 6; DEDUPE_DAYS = 10

def extract_ticker(dn_list):
    for dn in (dn_list or []):
        m = re.search(r'\(([A-Z0-9.\-]{1,10})\)', dn)
        if m and not m.group(1).upper().startswith('CIK'):
            return m.group(1).upper()
    return None

universe = set(json.load(open(UNIV)))
rows = []
for line in open(HITS):
    r = json.loads(line)
    r['ticker'] = extract_ticker(r.get('display_names'))
    rows.append(r)
hits = pd.DataFrame(rows)
hits['file_date'] = pd.to_datetime(hits['file_date'], errors='coerce')
hits['items'] = hits['items'].apply(lambda x: x or [])
hits = hits.dropna(subset=['file_date', 'ticker'])
hits = hits[hits['ticker'].isin(universe)]

def keep_primary(it):
    return ('8.01' in it or '7.01' in it) and '2.02' not in it and '1.01' not in it

ev = hits[hits['items'].apply(keep_primary)].copy()
ev = ev.drop_duplicates(subset=['ticker','file_date']).sort_values('file_date')
keep, last = [], {}
for i, r in ev.iterrows():
    tk, fd = r['ticker'], r['file_date']
    if tk in last and (fd-last[tk]).days <= DEDUPE_DAYS: continue
    keep.append(i); last[tk] = fd
ev = ev.loc[keep].reset_index(drop=True)

def load_daily(sym):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')['Body'].read()
        df = pd.read_parquet(io.BytesIO(o)); df['date'] = pd.to_datetime(df['date'])
        return sym, df.set_index('date').sort_index()
    except Exception:
        return sym, None

from concurrent.futures import ThreadPoolExecutor
syms = sorted(ev['ticker'].unique())
with ThreadPoolExecutor(max_workers=24) as ex:
    loaded = list(ex.map(load_daily, syms))
bars = {tk: d for tk, d in loaded if d is not None and len(d) >= HOLD+40}

dolvol = {}
for tk, d in bars.items():
    dv = (d['close']*d['volume']).rolling(252).mean().dropna()
    dolvol[tk] = dv.mean() if len(dv) else 0.0
dvs = pd.Series(dolvol).sort_values(ascending=False)
liquid500 = set(dvs.index[:500])

mkt_rets = {tk: bars[tk]['close'].pct_change() for tk in liquid500 if tk in bars}
mkt = pd.DataFrame(mkt_rets).mean(axis=1).dropna()
mkt_idx = (1+mkt).cumprod()

rows_out = []
for _, r in ev.iterrows():
    d = bars.get(r['ticker'])
    if d is None: continue
    idx = d.index[d.index >= r['file_date']]
    if len(idx) < HOLD+1: continue
    e, x = idx[0], idx[HOLD]
    ret = d['close'].loc[x]/d['close'].loc[e]-1.0
    try: mr = mkt_idx.loc[x]/mkt_idx.loc[e]-1.0
    except Exception: continue
    rows_out.append({'sym': r['ticker'], 'entry': e, 'ret': ret, 'mkt': mr, 'dolvol': dolvol.get(r['ticker'],0)})
res = pd.DataFrame(rows_out)
res['mktadj'] = res['ret'] - res['mkt']
res['net'] = res['mktadj'] - COST_BP/1e4
res['liquid'] = res['sym'].isin(liquid500)

print('=== extreme |net| outliers (primary filter) ===')
ex = res.reindex(res['net'].abs().sort_values(ascending=False).index).head(15)
print(ex[['sym','entry','ret','mkt','net','dolvol','liquid']].to_string())
print(f'\nevents with |ret| > 100%: {(res.ret.abs()>1).sum()} / {len(res)}')
print(f'events with |ret| > 300%: {(res.ret.abs()>3).sum()} / {len(res)}')

# winsorized stats: cap net at +/-100% (and report median, which is robust)
def report(df, label):
    df = df.copy()
    dm = df.groupby('entry')['net'].mean()
    t_cl = dm.mean()/(dm.std()/np.sqrt(len(dm))) if len(dm)>1 else np.nan
    pos = df.loc[df.net>0,'net'].sum(); neg = -df.loc[df.net<0,'net'].sum()
    pf = pos/neg if neg>0 else np.inf
    win = (df.net>0).mean()
    print(f'{label:30s} n={len(df):5d}  mean={df.net.mean()*1e4:+7.1f}bp  med={df.net.median()*1e4:+7.1f}bp  '
          f'win={win*100:4.1f}%  PF={pf:.3f}  t_clust={t_cl:+.2f}')
    # winsorized mean (cap |net| at 100%)
    w = df['net'].clip(-1.0, 1.0)
    print(f'{"  (winsorized |net|<=100%)":30s} n={len(df):5d}  mean={w.mean()*1e4:+7.1f}bp  med={w.median()*1e4:+7.1f}bp')

print('\n=== primary filter, raw + winsorized ===')
report(res, 'ALL')
report(res[res.liquid], 'LIQUID top500')
report(res[~res.liquid], 'non-liquid')
