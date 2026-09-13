"""
PEAD stress final: broad-market adjustment (less contaminated than the in-universe
index) for the key long legs, incl. the post-market next-open variant.
Determines whether the +56bp raw post-market next-open 2-day return is alpha or beta.
"""
import boto3, io, json
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

B = 'trading-datalake-920641308584'
s3 = boto3.client('s3', region_name='us-east-1')


def load_close(sym):
    try:
        o = s3.get_object(Bucket=B, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        df['date'] = pd.to_datetime(df['date'])
        return sym, df.set_index('date')['close'].sort_index()
    except Exception:
        return sym, None


def load_ohlc(sym):
    try:
        o = s3.get_object(Bucket=B, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        return sym, df[['open', 'close']]
    except Exception:
        return sym, None


def build_index(rets):
    allr = pd.concat(rets, axis=1, sort=True)
    return (1.0 + allr.mean(axis=1).dropna()).cumprod()


def cluster_ttest(vals, day):
    vals = np.asarray(vals, float); day = np.asarray(day)
    m = ~np.isnan(vals); vals, day = vals[m], day[m]
    if len(vals) == 0:
        return dict(mean=np.nan, t=np.nan, n_events=0, n_days=0)
    daily = pd.DataFrame({'v': vals, 'd': day}).groupby('d')['v'].mean()
    n = len(daily); mean = daily.mean(); sd = daily.std(ddof=1)
    t = mean / (sd / np.sqrt(n)) if (sd > 0 and n > 1) else np.nan
    return dict(mean=float(mean), t=float(t) if not np.isnan(t) else None,
                n_events=int(len(vals)), n_days=int(n))


def main():
    pag = s3.get_paginator('list_objects_v2')
    earn_keys = [o['Key'] for pg in pag.paginate(Bucket=B, Prefix='av/earnings/')
                 for o in pg.get('Contents', []) if o['Key'].endswith('.json')]
    earn_syms = sorted(k.split('/')[-1].replace('.json', '') for k in earn_keys)
    daily_keys = [o['Key'] for pg in pag.paginate(Bucket=B, Prefix='ibkr/equities/daily/')
                  for o in pg.get('Contents', []) if o['Key'].endswith('.parquet')]
    all_daily = sorted(k.split('/')[-1].replace('.parquet', '') for k in daily_keys)

    # broad index: stride-13 sample (same as catalyst_test)
    broad_syms = all_daily[::13]
    broad_rets = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for sym, s in ex.map(load_close, broad_syms):
            if s is None or len(s) < 100:
                continue
            r = s.pct_change().replace([np.inf, -np.inf], np.nan).dropna().clip(-0.5, 0.5)
            broad_rets.append(r)
    broad_idx = build_index(broad_rets)
    print(f'[broad] {len(broad_rets)} symbols', flush=True)

    # load event universe OHLC
    daily = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for sym, df in ex.map(load_ohlc, [s for s in earn_syms if s in all_daily]):
            if df is not None:
                daily[sym] = df

    rows = []
    for sym in earn_syms:
        if sym not in daily:
            continue
        d = daily[sym]; close = d['close']; opn = d['open']; dates = close.index
        try:
            ed = json.loads(s3.get_object(Bucket=B, Key=f'av/earnings/{sym}.json')['Body'].read().decode())
        except Exception:
            continue
        for r in ed.get('quarterlyEarnings', []):
            rd, rt = r.get('reportedDate'), r.get('reportTime')
            if not rd or rt not in ('pre-market', 'post-market'):
                continue
            try:
                D = pd.Timestamp(rd); surp = float(r['surprise'])
            except Exception:
                continue
            if rt == 'pre-market':
                pos = dates.searchsorted(D)
                if pos >= len(dates) or pos == 0:
                    continue
                A = dates[pos]; iA = close.index.get_loc(A); i_prior = pos - 1
            else:
                pos = dates.searchsorted(D, side='right')
                if pos >= len(dates) or pos == 0:
                    continue
                A = dates[pos]; iA = close.index.get_loc(A); i_prior = pos - 1
            if iA + 2 >= len(dates):
                continue
            ec = float(close.iloc[iA]); pc = float(close.iloc[i_prior])
            if not np.isfinite(ec) or not np.isfinite(pc) or ec <= 0 or pc <= 0:
                continue
            rec = {'sym': sym, 'entry_date': str(A.date()), 'reportTime': rt,
                   'surp_pct': surp / pc * 100.0}
            # close-entry 1d (close A -> close A+1), broad-adjusted
            ec1 = float(close.iloc[iA + 1])
            rec['ret_c1'] = (ec1 / ec - 1.0) * 1e4
            try:
                br = broad_idx.loc[dates[iA + 1]] / broad_idx.loc[A] - 1.0
            except Exception:
                br = np.nan
            rec['badj_c1'] = rec['ret_c1'] - br * 1e4
            # next-open (post-market): open A -> close A+1 and open A -> close A+2
            if rt == 'post-market':
                oA = float(opn.iloc[iA])
                if np.isfinite(oA) and oA > 0:
                    for j, tag in [(iA, 'no1'), (iA + 1, 'no2')]:
                        cj = float(close.iloc[j])
                        rec[f'ret_{tag}'] = (cj / oA - 1.0) * 1e4
                        try:
                            brj = broad_idx.loc[dates[j]] / broad_idx.loc[A] - 1.0
                        except Exception:
                            brj = np.nan
                        rec[f'badj_{tag}'] = rec[f'ret_{tag}'] - brj * 1e4
            rows.append(rec)
    df = pd.DataFrame(rows).dropna(subset=['ret_c1', 'badj_c1'])
    df['surp_pct_w'] = df['surp_pct'].clip(-5, 5)
    df['rank'] = df['surp_pct_w'].rank(method='first')
    df['q'] = pd.qcut(df['rank'], 5, labels=False)
    df['dec'] = pd.qcut(df['rank'], 10, labels=False)
    top = df[df['q'] == df['q'].max()]
    pmtop = top[top['reportTime'] == 'post-market'].dropna(subset=['ret_no1'])

    def stats(sub, col):
        tt = cluster_ttest(sub[col].values, sub['entry_date'].values)
        dm = sub.groupby('entry_date')[col].mean().values
        rng = np.random.default_rng(0)
        bs = np.sort([rng.choice(dm, size=len(dm), replace=True).mean() for _ in range(2000)]) if len(dm) > 1 else np.array([np.nan])
        return {'mean_bp': round(float(np.nanmean(sub[col])), 2),
                'median_bp': round(float(np.nanmedian(sub[col])), 2),
                'win_rate': round(float((np.asarray(sub[col]) > 0).mean()), 3),
                'day_clustered_t': round(tt['t'], 3) if tt['t'] is not None else None,
                'n_events': int(len(sub)), 'n_days': int(tt['n_days']),
                'bootstrap_ci': [round(float(bs[50]), 2), round(float(bs[1949]), 2)],
                'net_5': round(float(np.nanmean(sub[col])) - 5, 2),
                'net_10': round(float(np.nanmean(sub[col])) - 10, 2),
                'net_15': round(float(np.nanmean(sub[col])) - 15, 2),
                'net_20': round(float(np.nanmean(sub[col])) - 20, 2)}

    R = {}
    R['broad_adjusted_top_quintile_close1'] = {'raw': stats(top, 'ret_c1'), 'badj': stats(top, 'badj_c1')}
    R['broad_adjusted_postmarket_top_nextopen'] = {
        'open_to_closeD1_raw': stats(pmtop, 'ret_no1'),
        'open_to_closeD1_badj': stats(pmtop, 'badj_no1'),
        'open_to_closeD2_raw': stats(pmtop, 'ret_no2'),
        'open_to_closeD2_badj': stats(pmtop, 'badj_no2'),
        'n': int(len(pmtop)),
    }
    # broad-adjusted by reportTime (close entry)
    rt = {}
    for t in ['pre-market', 'post-market']:
        sub = top[top['reportTime'] == t]
        rt[t] = {'raw': stats(sub, 'ret_c1'), 'badj': stats(sub, 'badj_c1')}
    R['broad_adjusted_top_quintile_by_reportTime'] = rt

    out = '/home/ubuntu/trading-system/research/atomics/pead_stress_results.json'
    base = json.load(open(out))
    base['broad_market_adjusted'] = R
    with open(out, 'w') as fh:
        json.dump(base, fh, indent=2, default=str)
    print('[done] appended broad_market_adjusted', flush=True)

    print('\n== broad-adjusted top quintile (close entry) ==')
    for k, v in R['broad_adjusted_top_quintile_close1'].items():
        print(f"  {k}: mean={v['mean_bp']:+.2f} med={v['median_bp']:+.2f} win={v['win_rate']*100:.0f}% t={v['day_clustered_t']} CI={v['bootstrap_ci']} net5/10/15/20={v['net_5']}/{v['net_10']}/{v['net_15']}/{v['net_20']}")
    print('\n== broad-adjusted top quintile by reportTime ==')
    for t, v in rt.items():
        print(f"  {t}: raw={v['raw']['mean_bp']:+.2f} t={v['raw']['day_clustered_t']} | badj={v['badj']['mean_bp']:+.2f} t={v['badj']['day_clustered_t']} CI={v['badj']['bootstrap_ci']}")
    print('\n== broad-adjusted post-market next-open ==')
    for k, v in R['broad_adjusted_postmarket_top_nextopen'].items():
        if k == 'n':
            continue
        print(f"  {k}: mean={v['mean_bp']:+.2f} med={v['median_bp']:+.2f} win={v['win_rate']*100:.0f}% t={v['day_clustered_t']} CI={v['bootstrap_ci']} net5={v['net_5']} net10={v['net_10']} net20={v['net_20']}")


if __name__ == '__main__':
    main()
