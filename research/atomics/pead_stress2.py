"""
PEAD stress follow-up: post-market deep-dive + beta decomposition + next-open
entry variant (the realistic long-only execution).
"""
import boto3, io, json, os
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

B = 'trading-datalake-920641308584'
s3 = boto3.client('s3', region_name='us-east-1')


def load_daily(sym):
    try:
        o = s3.get_object(Bucket=B, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        return sym, df[['open', 'high', 'low', 'close', 'volume']]
    except Exception:
        return sym, None


def build_universe_index(daily):
    rets = []
    for sym, d in daily.items():
        r = d['close'].pct_change().replace([np.inf, -np.inf], np.nan).dropna().clip(-0.5, 0.5)
        rets.append(r)
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


def full_stats(sub, retcol, daycol='entry_date'):
    v = sub[retcol].values
    tt = cluster_ttest(v, sub[daycol].values)
    daily_mean = sub.groupby(daycol)[retcol].mean().values
    rng = np.random.default_rng(0)
    bs = np.sort([rng.choice(daily_mean, size=len(daily_mean), replace=True).mean()
                  for _ in range(2000)]) if len(daily_mean) > 1 else np.array([np.nan])
    return {
        'mean_bp': float(np.nanmean(v)),
        'median_bp': float(np.nanmedian(v)),
        'win_rate': float((np.asarray(v) > 0).mean()),
        'day_clustered_t': tt['t'], 'n_events': int(len(v)), 'n_days': int(tt['n_days']),
        'bootstrap_ci': [round(float(bs[50]), 2), round(float(bs[1949]), 2)],
    }


def main():
    pag = s3.get_paginator('list_objects_v2')
    earn_keys = [o['Key'] for pg in pag.paginate(Bucket=B, Prefix='av/earnings/')
                 for o in pg.get('Contents', []) if o['Key'].endswith('.json')]
    earn_syms = sorted(k.split('/')[-1].replace('.json', '') for k in earn_keys)
    daily_keys = [o['Key'] for pg in pag.paginate(Bucket=B, Prefix='ibkr/equities/daily/')
                  for o in pg.get('Contents', []) if o['Key'].endswith('.parquet')]
    all_daily = set(k.split('/')[-1].replace('.parquet', '') for k in daily_keys)

    daily = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for sym, df in ex.map(load_daily, [s for s in earn_syms if s in all_daily]):
            if df is not None:
                daily[sym] = df
    mkt_idx = build_universe_index(daily)

    rows = []
    for sym in earn_syms:
        if sym not in daily:
            continue
        d = daily[sym]; close = d['close']; opn = d['open']
        dates = close.index
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
            if iA + 1 >= len(dates):
                continue
            ec = float(close.iloc[iA]); pc = float(close.iloc[i_prior])
            if not np.isfinite(ec) or not np.isfinite(pc) or ec <= 0 or pc <= 0:
                continue
            ec1 = float(close.iloc[iA + 1])
            mret = np.nan
            try:
                mret = mkt_idx.loc[dates[iA + 1]] / mkt_idx.loc[A] - 1.0
            except Exception:
                pass
            rec = {'sym': sym, 'entry_date': str(A.date()), 'reportTime': rt,
                   'surp_pct': surp / pc * 100.0,
                   'ret_close1': (ec1 / ec - 1.0) * 1e4,
                   'madj_close1': ((ec1 / ec - 1.0) - mret) * 1e4,
                   'mkt_ret_bp': mret * 1e4}
            # next-open entry variant (post-market: buy at open of A)
            if rt == 'post-market':
                oA = float(opn.iloc[iA])
                if np.isfinite(oA) and oA > 0:
                    # open of D+1 -> close of D+1 (reaction day) and -> close of D+2
                    for j, tag in [(iA, 'open_to_closeD1'), (iA + 1, 'open_to_closeD2')]:
                        cj = float(close.iloc[j])
                        rec[f'ret_{tag}'] = (cj / oA - 1.0) * 1e4
            rows.append(rec)
    df = pd.DataFrame(rows).dropna(subset=['ret_close1', 'madj_close1'])
    df['surp_pct_w'] = df['surp_pct'].clip(-5, 5)
    df['rank'] = df['surp_pct_w'].rank(method='first')
    df['q'] = pd.qcut(df['rank'], 5, labels=False)
    df['dec'] = pd.qcut(df['rank'], 10, labels=False)
    top = df[df['q'] == df['q'].max()]
    bot = df[df['q'] == df['q'].min()]

    R = {}
    # beta decomposition: raw vs madj vs mkt by quintile
    decomp = {}
    for q in range(5):
        sub = df[df['q'] == q]
        decomp[str(q)] = {
            'n': int(len(sub)),
            'raw_close1': round(float(sub['ret_close1'].mean()), 2),
            'madj_close1': round(float(sub['madj_close1'].mean()), 2),
            'mkt_ret_bp': round(float(sub['mkt_ret_bp'].mean()), 2),
        }
    R['beta_decomposition_by_quintile'] = decomp

    # full post-market / pre-market split (close entry)
    R['top_quintile_by_reportTime'] = {}
    for t in ['pre-market', 'post-market']:
        sub = top[top['reportTime'] == t]
        R['top_quintile_by_reportTime'][t] = {
            'close_entry_raw': full_stats(sub, 'ret_close1'),
            'close_entry_madj': full_stats(sub, 'madj_close1'),
        }
    # top decile post-market
    pm = df[(df['dec'] == df['dec'].max()) & (df['reportTime'] == 'post-market')]
    R['top_decile_postmarket_close'] = {
        'raw': full_stats(pm, 'ret_close1'), 'madj': full_stats(pm, 'madj_close1')}
    # next-open entry (post-market): open of D+1
    pmtop = top[top['reportTime'] == 'post-market'].dropna(subset=['ret_open_to_closeD1'])
    R['postmarket_top_nextopen'] = {
        'open_to_closeD1': full_stats(pmtop, 'ret_open_to_closeD1'),
        'open_to_closeD2': full_stats(pmtop, 'ret_open_to_closeD2'),
        'n': int(len(pmtop)),
    }
    # surprise threshold sweep (post-market, close entry)
    thr = {}
    for minsp in [0.5, 1.0, 2.0, 3.0]:
        sub = df[(df['reportTime'] == 'post-market') & (df['surp_pct_w'] >= minsp)]
        if len(sub) < 30:
            continue
        thr[str(minsp)] = {'n': int(len(sub)), 'raw': full_stats(sub, 'ret_close1'),
                           'madj': full_stats(sub, 'madj_close1')}
    R['postmarket_surprise_threshold_sweep'] = thr

    # net-of-cost for the key long legs (raw and madj)
    def net_table(stats):
        m = stats['mean_bp']
        return {str(c): round(m - c, 2) for c in [5, 10, 15, 20]}
    R['net_of_cost_key_long_legs'] = {
        'top_q_close_raw': net_table(full_stats(top, 'ret_close1')),
        'top_q_close_madj': net_table(full_stats(top, 'madj_close1')),
        'top_q_postmarket_close_raw': net_table(R['top_quintile_by_reportTime']['post-market']['close_entry_raw']),
        'top_q_postmarket_close_madj': net_table(R['top_quintile_by_reportTime']['post-market']['close_entry_madj']),
        'postmarket_nextopen_to_closeD1': net_table(R['postmarket_top_nextopen']['open_to_closeD1']),
    }

    out = '/home/ubuntu/trading-system/research/atomics/pead_stress_results.json'
    base = json.load(open(out))
    base['postmarket_deepdive'] = R
    with open(out, 'w') as fh:
        json.dump(base, fh, indent=2, default=str)
    print('[done] appended postmarket_deepdive to', out, flush=True)

    print('\n== beta decomposition (by surprise quintile) ==')
    for q, v in decomp.items():
        print(f"  q{q}: n={v['n']} raw={v['raw_close1']:+.2f} madj={v['madj_close1']:+.2f} mkt={v['mkt_ret_bp']:+.2f}")
    print('\n== top quintile by reportTime (close entry) ==')
    for t, v in R['top_quintile_by_reportTime'].items():
        rw, md = v['close_entry_raw'], v['close_entry_madj']
        print(f"  {t}: raw mean={rw['mean_bp']:+.2f} med={rw['median_bp']:+.2f} win={rw['win_rate']*100:.0f}% t={rw['day_clustered_t']:+.2f} | madj mean={md['mean_bp']:+.2f} t={md['day_clustered_t']:+.2f} CI={md['bootstrap_ci']}")
    print('\n== post-market next-open entry ==')
    for k, v in R['postmarket_top_nextopen'].items():
        if k == 'n':
            continue
        print(f"  {k}: mean={v['mean_bp']:+.2f} med={v['median_bp']:+.2f} win={v['win_rate']*100:.0f}% t={v['day_clustered_t']:+.2f} CI={v['bootstrap_ci']}")
    print('\n== surprise threshold (post-market, close entry) ==')
    for k, v in thr.items():
        print(f"  min {k}%: n={v['n']} raw={v['raw']['mean_bp']:+.2f} t={v['raw']['day_clustered_t']:+.2f} | madj={v['madj']['mean_bp']:+.2f} t={v['madj']['day_clustered_t']:+.2f}")


if __name__ == '__main__':
    main()
