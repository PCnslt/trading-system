#!/usr/bin/env python3
"""BUYBACK ANNOUNCEMENT DRIFT backtest — final.

Event definition (primary): 8-K filings whose full text matches
"repurchase program" AND "authorized", filed under Item 8.01 or 7.01
(press-release / Reg FD), EXCLUDING earnings (2.02) and material-agreement
(1.01) items — i.e. event-disclosure 8-Ks announcing a buyback authorization,
not routine earnings progress reports or ASR/agreement filings.

Also reports sensitivity filters. Survivorship-biased current universe.
"""
import json, re, io, os, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import boto3
from scipy import stats

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

def load_hits():
    rows = []
    for line in open(HITS):
        r = json.loads(line)
        r['ticker'] = extract_ticker(r.get('display_names'))
        rows.append(r)
    df = pd.DataFrame(rows)
    df['file_date'] = pd.to_datetime(df['file_date'], errors='coerce')
    df['items'] = df['items'].apply(lambda x: x or [])
    return df.dropna(subset=['file_date', 'ticker'])

def build_events(df, universe, item_filter):
    df = df[df['ticker'].isin(universe)]
    if item_filter == 'primary':
        def keep(items):
            return ('8.01' in items or '7.01' in items) and '2.02' not in items and '1.01' not in items
    elif item_filter == '801':
        def keep(items):
            return '8.01' in items
    elif item_filter == '801no202':
        def keep(items):
            return '8.01' in items and '2.02' not in items
    elif item_filter == 'all':
        def keep(items):
            return True
    else:
        raise ValueError(item_filter)
    df = df[df['items'].apply(keep)]
    df = df.drop_duplicates(subset=['ticker', 'file_date']).sort_values('file_date')
    keep_idx, last = [], {}
    for i, r in df.iterrows():
        tk, fd = r['ticker'], r['file_date']
        if tk in last and (fd - last[tk]).days <= DEDUPE_DAYS:
            continue
        keep_idx.append(i)
        last[tk] = fd
    return df.loc[keep_idx].reset_index(drop=True)

def load_daily(sym):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')['Body'].read()
        df = pd.read_parquet(io.BytesIO(o))
        df['date'] = pd.to_datetime(df['date'])
        return df.set_index('date').sort_index()
    except Exception:
        return None

def summarize(df, label, cost_bp=COST_BP):
    df = df.copy()
    df['mktadj'] = df['ret'] - df['mkt']
    df['net'] = df['mktadj'] - cost_bp / 1e4
    dm = df.groupby('entry')['net'].mean()
    t_cl = dm.mean() / (dm.std() / np.sqrt(len(dm))) if len(dm) > 1 else np.nan
    t_pt = df['net'].mean() / (df['net'].std() / np.sqrt(len(df))) if len(df) > 1 else np.nan
    win = (df['net'] > 0).mean()
    pos = df.loc[df['net'] > 0, 'net'].sum()
    neg = -df.loc[df['net'] < 0, 'net'].sum()
    pf = pos / neg if neg > 0 else np.inf
    print(f'\n=== {label} === n={len(df)}  symbols={df.sym.nunique()}  dates={df.entry.min().date()}..{df.entry.max().date()}')
    print(f'  gross stock ret : mean={df["ret"].mean()*1e4:+7.1f}bp  med={df["ret"].median()*1e4:+7.1f}bp')
    print(f'  mkt-adj gross   : mean={df["mktadj"].mean()*1e4:+7.1f}bp  med={df["mktadj"].median()*1e4:+7.1f}bp')
    print(f'  mkt-adj NET-{cost_bp}bp: mean={df["net"].mean()*1e4:+7.1f}bp  med={df["net"].median()*1e4:+7.1f}bp')
    print(f'  win%={win*100:5.1f}%  PF(net)={pf:.3f}  t(per-trade)={t_pt:+.2f}  t(date-clust)={t_cl:+.2f} (n_dates={len(dm)})')
    return df, dict(n=len(df), mean_net_bp=df['net'].mean()*1e4, med_net_bp=df['net'].median()*1e4,
                    pf=pf, win=win, t_pt=t_pt, t_cl=t_cl, n_dates=len(dm))

def run(item_filter='primary', liquid_mode='top500'):
    universe = set(json.load(open(UNIV)))
    hits = load_hits()
    ev = build_events(hits, universe, item_filter)
    print(f'[filter={item_filter}] events: {len(ev)} across {ev.ticker.nunique()} tickers')

    syms = sorted(ev['ticker'].unique())
    with ThreadPoolExecutor(max_workers=24) as ex:
        loaded = list(ex.map(load_daily, syms))
    bars = {}
    for tk, d in zip(syms, loaded):
        if d is not None and len(d) >= HOLD + 40:
            bars[tk] = d
    print(f'  symbols with usable bars: {len(bars)}')

    # dollar volume (recent 252d avg)
    dolvol = {}
    for tk, d in bars.items():
        dv = (d['close'] * d['volume']).rolling(252).mean().dropna()
        dolvol[tk] = dv.mean() if len(dv) else 0.0
    dolvol_s = pd.Series(dolvol).sort_values(ascending=False)
    if liquid_mode == 'top500':
        liquid = set(dolvol_s.index[:500])
    elif liquid_mode == '20M':
        liquid = set(dolvol_s[dolvol_s >= 20_000_000].index)
    elif liquid_mode == 'all':
        liquid = set(bars.keys())
    else:
        raise ValueError(liquid_mode)
    print(f'  liquid tier ({liquid_mode}): {len(liquid)} symbols')

    # market proxy = equal-weight daily return over liquid tier
    mkt_rets = {}
    for tk in liquid:
        d = bars.get(tk)
        if d is not None:
            mkt_rets[tk] = d['close'].pct_change()
    mkt = pd.DataFrame(mkt_rets).mean(axis=1).dropna()
    mkt_idx = (1 + mkt).cumprod()
    print(f'  market proxy: {len(mkt)} days ({mkt.index.min().date()}..{mkt.index.max().date()})')

    rows = []
    for _, r in ev.iterrows():
        d = bars.get(r['ticker'])
        if d is None:
            continue
        idx = d.index[d.index >= r['file_date']]
        if len(idx) < HOLD + 1:
            continue
        e, x = idx[0], idx[HOLD]
        ret = d['close'].loc[x] / d['close'].loc[e] - 1.0
        try:
            mr = mkt_idx.loc[x] / mkt_idx.loc[e] - 1.0
        except Exception:
            continue
        rows.append({'sym': r['ticker'], 'entry': e, 'exit': x, 'ret': ret, 'mkt': mr,
                     'dolvol': dolvol.get(r['ticker'], np.nan), 'file_date': r['file_date']})
    res = pd.DataFrame(rows)
    print(f'  matched forward +{HOLD}d: {len(res)}')
    if len(res) == 0:
        return None

    liq = res[res['sym'].isin(liquid)].sort_values('entry')
    full, _ = summarize(res, f'FULL (filter={item_filter}, liquid={liquid_mode})')
    liqdf, lstats = summarize(liq, f'LIQUID TIER (filter={item_filter}, liquid={liquid_mode})')

    n = len(liq)
    split = int(n * 0.6)
    is_d, oos_d = liq.iloc[:split], liq.iloc[split:]
    summarize(is_d, 'LIQUID IS (first 60% entry dates)')
    oos_df, oos = summarize(oos_d, 'LIQUID OOS (last 40% entry dates)')
    print(f'    OOS date range: {oos_d.entry.min().date()} .. {oos_d.entry.max().date()}')

    if len(oos_d) > 0:
        net = oos_d.copy()
        net['net'] = net['ret'] - net['mkt'] - COST_BP/1e4
        tot = net['net'].sum()
        topn = net.groupby('sym')['net'].sum().sort_values().tail(10).sum()
        topd = net.groupby('entry')['net'].sum().sort_values().tail(10).sum()
        print(f'    OOS concentration: top-10 names={topn/tot*100:.0f}%  top-10 dates={topd/tot*100:.0f}% of net P&L')

    # per-year net (liquid)
    print('  per-year net mkt-adj (liquid, bp):')
    liq['yr'] = liq['entry'].dt.year
    for y, g in liq.groupby('yr'):
        net = g['ret'] - g['mkt'] - COST_BP/1e4
        pos = net[net > 0].sum(); neg = -net[net < 0].sum()
        pf = (pos / neg) if neg > 0 else float('inf')
        print(f'    {y}: n={len(g):3d}  mean={net.mean()*1e4:+7.1f}bp  med={net.median()*1e4:+7.1f}bp  PF={pf:.2f}')
    return dict(full=full, liq=lstats, oos=oos, res=res, liq_df=liq)

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'primary'
    run(item_filter=mode, liquid_mode='top500')
