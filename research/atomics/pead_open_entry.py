"""
CLEAN falsification of the flagged post-market PEAD lead.

Lead under test: post-market earnings surprise -> buy at NEXT OPEN (day T+1)
-> hold 1 day (open->close) and 2 days (open->close).

The previously reported +55.6bp (2-day, next-open) was market-adjusted with a
CLOSE-to-CLOSE benchmark (and, for the 1-day leg, effectively no benchmark at
all).  This script re-adjusts with the CORRECT same-window benchmark:
    stock open(T+1)->close(T+k)  minus  universe EW open(T+1)->close(T+k)
and an open-to-open variant (pure gap continuation), both equal-weight over the
earnings universe (and, as a robustness, over a broad stride sample of all
daily symbols).  Reports top-minus-bottom quintile spread, net of 20bp, with
day-clustered t, IS(<2021)/OOS(>=2021) split, and single-date/name checks.

Research only.  No trading, no orders.
"""
import boto3, io, json
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

B = 'trading-datalake-920641308584'
s3 = boto3.client('s3', region_name='us-east-1')


def load_ohlc(sym, cols=('open', 'close')):
    try:
        o = s3.get_object(Bucket=B, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        return sym, df[list(cols)]
    except Exception:
        return sym, None


def _mean_ew(d):
    p = pd.concat(d, axis=1, sort=True)
    p = p.replace([np.inf, -np.inf], np.nan).clip(-0.5, 0.5)
    return p.mean(axis=1, skipna=True)


def build_benchmarks(daily):
    """Return dict of benchmark Series indexed by ENTRY date (date whose open is the base)."""
    o2c1, o2c2, o2o1, o2o2, c2c1 = {}, {}, {}, {}, {}
    for sym, d in daily.items():
        opn, clo = d['open'], d['close']
        o2c1[sym] = clo / opn - 1.0                # open(E)->close(E)
        o2c2[sym] = clo.shift(-1) / opn - 1.0      # open(E)->close(E+1)
        o2o1[sym] = opn.shift(-1) / opn - 1.0      # open(E)->open(E+1)
        o2o2[sym] = opn.shift(-2) / opn - 1.0      # open(E)->open(E+2)
        c2c1[sym] = clo.pct_change().shift(-1)     # close(E)->close(E+1), indexed at E
    return {
        'o2c1': _mean_ew(o2c1), 'o2c2': _mean_ew(o2c2),
        'o2o1': _mean_ew(o2o1), 'o2o2': _mean_ew(o2o2),
        'c2c1': _mean_ew(c2c1),
    }


def cluster_ttest(vals, day):
    vals = np.asarray(vals, float); day = np.asarray(day)
    m = ~np.isnan(vals); vals, day = vals[m], day[m]
    if len(vals) == 0:
        return dict(mean=np.nan, t=None, n_events=0, n_days=0)
    daily = pd.DataFrame({'v': vals, 'd': day}).groupby('d')['v'].mean()
    n = len(daily); mean = daily.mean(); sd = daily.std(ddof=1)
    t = mean / (sd / np.sqrt(n)) if (sd > 0 and n > 1) else np.nan
    return dict(mean=float(mean), t=float(t) if (t is not None and not np.isnan(t)) else None,
                n_events=int(len(vals)), n_days=int(n))


def day_boot_ci(vals, day, n=2000, seed=0):
    vals = np.asarray(vals, float); day = np.asarray(day)
    m = ~np.isnan(vals); vals, day = vals[m], day[m]
    dm = pd.DataFrame({'v': vals, 'd': day}).groupby('d')['v'].mean().values
    if len(dm) <= 1:
        return [None, None]
    rng = np.random.default_rng(seed)
    bs = np.sort([rng.choice(dm, size=len(dm), replace=True).mean() for _ in range(n)])
    return [round(float(bs[50]), 2), round(float(bs[1949]), 2)]


def stats(sub, col):
    v = sub[col].values
    tt = cluster_ttest(v, sub['entry_date'].values)
    dm = sub.groupby('entry_date')[col].mean().values
    m = float(np.nanmean(v))
    return {
        'mean_bp': round(m, 3),
        'median_bp': round(float(np.nanmedian(v)), 3),
        'std_bp': round(float(np.nanstd(v)), 2),
        'win_rate': round(float((np.asarray(v) > 0).mean()), 4),
        'day_clustered_t': round(tt['t'], 3) if tt['t'] is not None else None,
        'day_clustered_mean_bp': round(tt['mean'], 3),
        'n_events': int(len(v)), 'n_days': int(tt['n_days']),
        'bootstrap_ci': day_boot_ci(v, sub['entry_date'].values),
        'net_20bp': round(m - 20, 3),
        'net_40bp': round(m - 40, 3),
    }


def spread_stats(long_df, short_df, col):
    """Long-short spread with day-clustered t (per-day long mean - short mean)."""
    lg = long_df.groupby('entry_date')[col].mean()
    sh = short_df.groupby('entry_date')[col].mean()
    idx = lg.index.union(sh.index)
    sp = lg.reindex(idx).sub(sh.reindex(idx)).dropna()
    m = float(sp.mean())
    n = len(sp)
    sd = sp.std(ddof=1)
    t = m / (sd / np.sqrt(n)) if (sd > 0 and n > 1) else np.nan
    return {
        'spread_mean_bp': round(m, 3),
        'day_clustered_t': round(float(t), 3) if not np.isnan(t) else None,
        'n_days': int(n),
        'n_long': int(len(long_df)), 'n_short': int(len(short_df)),
        'net_20bp': round(m - 20, 3),
        'net_40bp': round(m - 40, 3),
    }


def concentration(sub, col, topn=10):
    g = sub.groupby('sym')[col].agg(['mean', 'count'])
    g = g.sort_values('mean', ascending=False)
    total = float(sub[col].sum())
    sym = {
        'n_symbols': int(len(g)),
        'top_symbols': [{'sym': s, 'mean_bp': round(float(r['mean']), 2),
                         'n': int(r['count'])} for s, r in g.head(topn).iterrows()],
        'top10_symbols_event_share': round(float(g.head(topn)['count'].sum()) / len(sub), 4),
        'excl_top10_symbols_mean_bp': round(float(sub[~sub['sym'].isin(g.head(topn).index)][col].mean()), 3),
        'excl_top10_symbols_n': int(len(sub) - int(g.head(topn)['count'].sum())),
    }
    dg = sub.groupby('entry_date')[col].mean().sort_values(ascending=False)
    day = {
        'n_days': int(len(dg)),
        'top_days': [{'date': str(d), 'mean_bp': round(float(v), 2)} for d, v in dg.head(topn).items()],
        'top10_days_event_share': round(float(sub[sub['entry_date'].isin(dg.head(topn).index)].shape[0]) / len(sub), 4),
        'excl_top10_days_mean_bp': round(float(sub[~sub['entry_date'].isin(dg.head(topn).index)][col].mean()), 3),
        'excl_top10_days_n': int(sub[~sub['entry_date'].isin(dg.head(topn).index)].shape[0]),
        'max_single_day_contrib_bp': round(float(dg.iloc[0]) if len(dg) else np.nan, 2),
    }
    return {'symbol': sym, 'day': day}


def main():
    pag = s3.get_paginator('list_objects_v2')
    earn_keys = [o['Key'] for pg in pag.paginate(Bucket=B, Prefix='av/earnings/')
                 for o in pg.get('Contents', []) if o['Key'].endswith('.json')]
    earn_syms = sorted(k.split('/')[-1].replace('.json', '') for k in earn_keys)
    daily_keys = [o['Key'] for pg in pag.paginate(Bucket=B, Prefix='ibkr/equities/daily/')
                  for o in pg.get('Contents', []) if o['Key'].endswith('.parquet')]
    all_daily = set(k.split('/')[-1].replace('.parquet', '') for k in daily_keys)

    # ---- load event universe OHLC ----
    daily = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for sym, df in ex.map(lambda s: load_ohlc(s), [s for s in earn_syms if s in all_daily]):
            if df is not None:
                daily[sym] = df
    print(f'[universe] {len(daily)} symbols with daily OHLC', flush=True)

    bench_u = build_benchmarks(daily)

    # ---- broad stride sample (robustness benchmark) ----
    broad_syms = [k.split('/')[-1].replace('.parquet', '') for k in daily_keys][::13]
    broad = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for sym, df in ex.map(lambda s: load_ohlc(s), broad_syms):
            if df is not None and len(df) >= 100:
                broad[sym] = df
    bench_b = build_benchmarks(broad)
    print(f'[broad] {len(broad)} symbols', flush=True)

    # ---- build event rows ----
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
            if not rd or rt != 'post-market':
                continue
            try:
                D = pd.Timestamp(rd); surp = float(r['surprise'])
            except Exception:
                continue
            pos = dates.searchsorted(D, side='right')  # first trading day > report date
            if pos >= len(dates) or pos < 1:
                continue
            E = dates[pos]; iE = pos
            if iE + 1 >= len(dates):
                continue
            pc = float(close.iloc[iE - 1])
            if not np.isfinite(pc) or pc <= 0:
                continue
            oE = float(opn.iloc[iE])
            if not np.isfinite(oE) or oE <= 0:
                continue
            cE = float(close.iloc[iE])
            cE1 = float(close.iloc[iE + 1])
            if not np.isfinite(cE) or not np.isfinite(cE1) or cE <= 0 or cE1 <= 0:
                continue
            rec = {
                'sym': sym, 'entry_date': str(E.date()), 'report_date': str(D.date()),
                'surp_pct': surp / pc * 100.0,
                'ret_1d_o2c': (cE / oE - 1.0) * 1e4,
                'ret_2d_o2c': (cE1 / oE - 1.0) * 1e4,
            }
            # open-to-open (gap continuation), 2-day needs open[iE+2]
            oE1 = float(opn.iloc[iE + 1]) if iE + 1 < len(opn) else np.nan
            rec['ret_1d_o2o'] = (oE1 / oE - 1.0) * 1e4 if np.isfinite(oE1) and oE1 > 0 else np.nan
            if iE + 2 < len(dates):
                oE2 = float(opn.iloc[iE + 2])
                rec['ret_2d_o2o'] = (oE2 / oE - 1.0) * 1e4 if np.isfinite(oE2) and oE2 > 0 else np.nan
            else:
                rec['ret_2d_o2o'] = np.nan
            rows.append(rec)

    df = pd.DataFrame(rows)
    df['surp_pct_w'] = df['surp_pct'].clip(-5, 5)
    df = df.dropna(subset=['surp_pct_w', 'ret_1d_o2c', 'ret_2d_o2c'])
    df['rank'] = df['surp_pct_w'].rank(method='first')
    df['q'] = pd.qcut(df['rank'], 5, labels=False)

    # market-adjust (universe + broad), same-window open-to-close & open-to-open
    for name, bench in [('u', bench_u), ('b', bench_b)]:
        for tag in ['o2c1', 'o2c2', 'o2o1', 'o2o2', 'c2c1']:
            s = bench[tag]
            df[f'{name}_{tag}'] = df['entry_date'].map(lambda x: s.loc[x] if x in s.index else np.nan) * 1e4
    # madj = stock - benchmark (both in bp)
    df['madj_1d_o2c'] = df['ret_1d_o2c'] - df['u_o2c1']
    df['madj_2d_o2c'] = df['ret_2d_o2c'] - df['u_o2c2']
    df['madj_1d_o2o'] = df['ret_1d_o2o'] - df['u_o2o1']
    df['madj_2d_o2o'] = df['ret_2d_o2o'] - df['u_o2o2']
    df['madj_2d_c2c_old'] = df['ret_2d_o2c'] - df['u_c2c1']  # old close-to-close style
    df['madj_2d_o2c_broad'] = df['ret_2d_o2c'] - df['b_o2c2']
    df['madj_1d_o2c_broad'] = df['ret_1d_o2c'] - df['b_o2c1']

    top = df[df['q'] == 4]
    bot = df[df['q'] == 0]
    print(f'[events] total post-market={len(df)} top_q={len(top)} bot_q={len(bot)}', flush=True)
    print(f'[range] {df.entry_date.min()} .. {df.entry_date.max()}', flush=True)

    R = {'generated_at': pd.Timestamp.now(tz='UTC').isoformat(),
         'n_postmarket_events': int(len(df)), 'n_symbols': int(df['sym'].nunique()),
         'entry_date_range': [str(df['entry_date'].min()), str(df['entry_date'].max())],
         'method': {
             'entry': 'post-market earnings reported day T -> buy at OPEN of first trading day T+1',
             'holds': {'1d': 'open(T+1)->close(T+1)', '2d': 'open(T+1)->close(T+2)'},
             'benchmark': 'equal-weight universe (earnings names) same-window open-to-close (o2c) '
                          'and open-to-open (o2o); plus broad stride-13 sample (b). c2c_old reproduces '
                          'the flawed close-to-close adjustment.',
             'surprise': 'surprise dollars / prior close, winsorized to [-5%,+5%], quintile-ranked',
         }}

    # ---- quintile monotonicity table (post-market next-open) ----
    qt = {}
    for k, col, adj in [('1d_raw', 'ret_1d_o2c', None), ('1d_madj_o2c', 'madj_1d_o2c', None),
                        ('2d_raw', 'ret_2d_o2c', None), ('2d_madj_o2c', 'madj_2d_o2c', None)]:
        q = {}
        for i in range(5):
            sub = df[df['q'] == i]
            q[str(i)] = {'n': int(len(sub)), 'mean_bp': round(float(sub[col].mean()), 3)}
        qt[k] = q
    R['quintile_monotonicity'] = qt

    # ---- top / bottom / spread ----
    R['top_quintile'] = {
        '1d': {'raw': stats(top, 'ret_1d_o2c'), 'madj_o2c': stats(top, 'madj_1d_o2c'),
               'madj_o2o': stats(top, 'madj_1d_o2o'), 'madj_o2c_broad': stats(top, 'madj_1d_o2c_broad')},
        '2d': {'raw': stats(top, 'ret_2d_o2c'), 'madj_o2c': stats(top, 'madj_2d_o2c'),
               'madj_o2o': stats(top, 'madj_2d_o2o'),
               'madj_c2c_old': stats(top, 'madj_2d_c2c_old'),
               'madj_o2c_broad': stats(top, 'madj_2d_o2c_broad')},
    }
    R['bottom_quintile'] = {
        '1d': {'raw': stats(bot, 'ret_1d_o2c'), 'madj_o2c': stats(bot, 'madj_1d_o2c')},
        '2d': {'raw': stats(bot, 'ret_2d_o2c'), 'madj_o2c': stats(bot, 'madj_2d_o2c')},
    }
    R['spread'] = {
        '1d': {'raw': spread_stats(top, bot, 'ret_1d_o2c'),
               'madj_o2c': spread_stats(top, bot, 'madj_1d_o2c')},
        '2d': {'raw': spread_stats(top, bot, 'ret_2d_o2c'),
               'madj_o2c': spread_stats(top, bot, 'madj_2d_o2c')},
    }

    # ---- IS / OOS ----
    iso = {}
    for lab, sub in [('is_<2021', df[df['entry_date'] < '2021-01-01']),
                     ('oos_>=2021', df[df['entry_date'] >= '2021-01-01'])]:
        t = sub[sub['q'] == 4]; b = sub[sub['q'] == 0]
        iso[lab] = {
            'n_events': int(len(sub)),
            'top_2d_raw': stats(t, 'ret_2d_o2c'),
            'top_2d_madj_o2c': stats(t, 'madj_2d_o2c'),
            'top_1d_madj_o2c': stats(t, 'madj_1d_o2c'),
            'spread_2d_madj_o2c': spread_stats(t, b, 'madj_2d_o2c'),
        }
    R['is_oos'] = iso

    # ---- concentration ----
    R['concentration'] = {
        'top_q_2d_madj_o2c': concentration(top, 'madj_2d_o2c', topn=10),
        'top_q_2d_raw': concentration(top, 'ret_2d_o2c', topn=10),
    }

    # ---- broad benchmark summary ----
    R['broad_benchmark'] = {
        'top_q_2d_madj_o2c_broad': stats(top, 'madj_2d_o2c_broad'),
        'top_q_1d_madj_o2c_broad': stats(top, 'madj_1d_o2c_broad'),
    }

    # ---- robustness: exclusion t-stats + contribution shares + signed spread ----
    top_by_sym = top.groupby('sym')['madj_2d_o2c'].mean().sort_values(ascending=False)
    top_by_day = top.groupby('entry_date')['madj_2d_o2c'].mean().sort_values(ascending=False)
    top10syms = top_by_sym.head(10).index
    top3syms = top_by_sym.head(3).index
    top10days = top_by_day.head(10).index
    tot_sum = float(top['madj_2d_o2c'].sum())
    rob = {
        'excl_top1_symbol_2d_madj_o2c': stats(top[top['sym'] != top_by_sym.index[0]], 'madj_2d_o2c'),
        'excl_top3_symbols_2d_madj_o2c': stats(top[~top['sym'].isin(top3syms)], 'madj_2d_o2c'),
        'excl_top10_symbols_2d_madj_o2c': stats(top[~top['sym'].isin(top10syms)], 'madj_2d_o2c'),
        'excl_top10_days_2d_madj_o2c': stats(top[~top['entry_date'].isin(top10days)], 'madj_2d_o2c'),
        'top10_symbols_sum_share': round(float(top[top['sym'].isin(top10syms)]['madj_2d_o2c'].sum()) / tot_sum, 4),
        'top10_days_sum_share': round(float(top[top['entry_date'].isin(top10days)]['madj_2d_o2c'].sum()) / tot_sum, 4),
        'top1_symbol_sum_share': round(float(top[top['sym'] == top_by_sym.index[0]]['madj_2d_o2c'].sum()) / tot_sum, 4),
    }
    # signed day-clustered spread (each event +1 top / -1 bottom, per-day mean of signed ret)
    signed = pd.concat([top.assign(s=1.0), bot.assign(s=-1.0)])[['entry_date', 'madj_2d_o2c', 's']]
    daily_signed = signed.groupby('entry_date').apply(
        lambda g: (g['madj_2d_o2c'] * g['s']).mean(), include_groups=False)
    rob['spread_2d_madj_o2c_signed'] = {
        'mean_bp': round(float(daily_signed.mean()), 3),
        'day_clustered_t': round(float(cluster_ttest(
            daily_signed.values, daily_signed.index.values)['t']), 3),
        'n_days': int(len(daily_signed)),
    }
    R['robustness'] = rob

    out = '/home/ubuntu/trading-system/research/atomics/pead_open_entry_results.json'
    with open(out, 'w') as fh:
        json.dump(R, fh, indent=2, default=str)
    print(f'[done] wrote {out}', flush=True)

    print('\n== robustness (top quintile 2-day madj_o2c) ==')
    for k in ['excl_top1_symbol_2d_madj_o2c', 'excl_top3_symbols_2d_madj_o2c',
              'excl_top10_symbols_2d_madj_o2c', 'excl_top10_days_2d_madj_o2c']:
        d = rob[k]
        print(f"  {k:34s} mean={d['mean_bp']:+8.2f} med={d['median_bp']:+8.2f} "
              f"t={d['day_clustered_t']} n={d['n_events']}/{d['n_days']}d net20={d['net_20bp']:+.2f}")
    print(f"  top10_symbols_sum_share={rob['top10_symbols_sum_share']} "
          f"top10_days_sum_share={rob['top10_days_sum_share']} "
          f"top1_symbol_sum_share={rob['top1_symbol_sum_share']}")
    print(f"  signed spread mean={rob['spread_2d_madj_o2c_signed']['mean_bp']:+.2f} "
          f"t={rob['spread_2d_madj_o2c_signed']['day_clustered_t']} "
          f"days={rob['spread_2d_madj_o2c_signed']['n_days']}")

    # ---- console summary ----
    def line(tag, d):
        t = d['day_clustered_t']
        print(f"  {tag:28s} mean={d['mean_bp']:+8.2f} med={d['median_bp']:+8.2f} "
              f"win={d['win_rate']*100:4.0f}% t={t if t is None else round(t,2)} "
              f"n={d['n_events']}/{d['n_days']}d net20={d['net_20bp']:+.2f}")

    print('\n== TOP quintile (post-market next-open) ==')
    print(' 1-day:')
    for k in ['raw', 'madj_o2c', 'madj_o2o', 'madj_o2c_broad']:
        line(k, R['top_quintile']['1d'][k])
    print(' 2-day:')
    for k in ['raw', 'madj_o2c', 'madj_o2o', 'madj_c2c_old', 'madj_o2c_broad']:
        line(k, R['top_quintile']['2d'][k])
    print('\n== SPREAD (top - bottom, post-market next-open) ==')
    for h in ['1d', '2d']:
        for k in ['raw', 'madj_o2c']:
            d = R['spread'][h][k]
            print(f"  {h} {k:10s} spread={d['spread_mean_bp']:+8.2f} t={d['day_clustered_t']} "
                  f"days={d['n_days']} net20={d['net_20bp']:+.2f} net40={d['net_40bp']:+.2f}")
    print('\n== IS/OOS (top quintile 2-day madj_o2c) ==')
    for k, v in iso.items():
        line(k, v['top_2d_madj_o2c'])
        d = v['spread_2d_madj_o2c']
        print(f"     {k} spread2d_madj_o2c={d['spread_mean_bp']:+.2f} t={d['day_clustered_t']} days={d['n_days']}")
    print('\n== quintile monotonicity (2d) ==')
    print('   raw  :', {k: v['mean_bp'] for k, v in qt['2d_raw'].items()})
    print('   madj :', {k: v['mean_bp'] for k, v in qt['2d_madj_o2c'].items()})


if __name__ == '__main__':
    main()
