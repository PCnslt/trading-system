#!/usr/bin/env python3
"""Robustness sweep for buyback drift — loads bars once, runs all filters/tiers."""
import json, re, io, os, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import boto3

BUCKET = 'trading-datalake-920641308584'
s3 = boto3.client('s3', region_name='us-east-1')
HITS = '/tmp/buyback_fts_hits.jsonl'
UNIV = '/tmp/universe_syms.json'
HOLD = 20
COST_BP = 6
DEDUPE_DAYS = 10

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

def make_events(items_mask_fn):
    df = hits[hits['items'].apply(items_mask_fn)].copy()
    df = df.drop_duplicates(subset=['ticker', 'file_date']).sort_values('file_date')
    keep, last = [], {}
    for i, r in df.iterrows():
        tk, fd = r['ticker'], r['file_date']
        if tk in last and (fd - last[tk]).days <= DEDUPE_DAYS:
            continue
        keep.append(i); last[tk] = fd
    return df.loc[keep].reset_index(drop=True)

FILTERS = {
    'primary': lambda it: ('8.01' in it or '7.01' in it) and '2.02' not in it and '1.01' not in it,
    '801':     lambda it: '8.01' in it,
    '801no202':lambda it: '8.01' in it and '2.02' not in it,
    'all':     lambda it: True,
}

# load bars for the union of tickers across all filters
all_syms = sorted(hits['ticker'].unique())
print(f'universe-matched tickers to load: {len(all_syms)}', flush=True)
def load_daily(sym):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')['Body'].read()
        df = pd.read_parquet(io.BytesIO(o))
        df['date'] = pd.to_datetime(df['date'])
        return sym, df.set_index('date').sort_index()
    except Exception:
        return sym, None
with ThreadPoolExecutor(max_workers=24) as ex:
    loaded = list(ex.map(load_daily, all_syms))
bars = {tk: d for tk, d in loaded if d is not None and len(d) >= HOLD + 40}
print(f'usable bars: {len(bars)}', flush=True)

# dollar volume
dolvol = {}
for tk, d in bars.items():
    dv = (d['close'] * d['volume']).rolling(252).mean().dropna()
    dolvol[tk] = dv.mean() if len(dv) else 0.0
dolvol_s = pd.Series(dolvol).sort_values(ascending=False)
liquid500 = set(dolvol_s.index[:500])
liquid20M = set(dolvol_s[dolvol_s >= 20_000_000].index)
print(f'liquid500={len(liquid500)}  liquid20M={len(liquid20M)}', flush=True)

# market proxy (equal-weight over liquid500)
mkt_rets = {tk: bars[tk]['close'].pct_change() for tk in liquid500 if tk in bars}
mkt = pd.DataFrame(mkt_rets).mean(axis=1).dropna()
mkt_idx = (1 + mkt).cumprod()

def fwd_row(ticker, fd):
    d = bars.get(ticker)
    if d is None:
        return None
    idx = d.index[d.index >= fd]
    if len(idx) < HOLD + 1:
        return None
    e, x = idx[0], idx[HOLD]
    ret = d['close'].loc[x] / d['close'].loc[e] - 1.0
    try:
        mr = mkt_idx.loc[x] / mkt_idx.loc[e] - 1.0
    except Exception:
        return None
    return ticker, e, ret, mr

def build_res(events):
    out = []
    for _, r in events.iterrows():
        res = fwd_row(r['ticker'], r['file_date'])
        if res:
            tk, e, ret, mr = res
            out.append({'sym': tk, 'entry': e, 'ret': ret, 'mkt': mr, 'dolvol': dolvol.get(tk, 0)})
    return pd.DataFrame(out)

def block(df, label):
    df = df.copy()
    df['net'] = (df['ret'] - df['mkt']) - COST_BP/1e4
    dm = df.groupby('entry')['net'].mean()
    t_cl = dm.mean()/(dm.std()/np.sqrt(len(dm))) if len(dm) > 1 else np.nan
    pos = df.loc[df.net > 0, 'net'].sum(); neg = -df.loc[df.net < 0, 'net'].sum()
    pf = pos/neg if neg > 0 else np.inf
    win = (df.net > 0).mean()
    print(f'  {label:28s} n={len(df):5d}  net_mean={df.net.mean()*1e4:+7.1f}bp  med={df.net.median()*1e4:+7.1f}bp  win={win*100:4.1f}%  PF={pf:.3f}  t_clust={t_cl:+.2f}', flush=True)
    return dict(n=len(df), net_bp=df.net.mean()*1e4, pf=pf, win=win, t_clust=t_cl)

for fname, fmask in FILTERS.items():
    ev = make_events(fmask)
    res = build_res(ev)
    print(f'\n##### FILTER={fname}  events={len(ev)}  matched={len(res)}', flush=True)
    if len(res) == 0:
        continue
    block(res, 'ALL')
    block(res[res['sym'].isin(liquid500)], 'liquid top500')
    block(res[~res['sym'].isin(liquid500)], 'non-liquid (ex top500)')
    block(res[res['sym'].isin(liquid20M)], 'liquid >=20M/day')
    # OOS for liquid top500
    liq = res[res['sym'].isin(liquid500)].sort_values('entry')
    n = len(liq); split = int(n*0.6)
    if n > 30:
        block(liq.iloc[:split], '  liquid IS (60%)')
        block(liq.iloc[split:], '  liquid OOS (40%)')
