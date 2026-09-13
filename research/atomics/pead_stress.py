"""
PEAD 1-day continuation STRESS TEST — long-only leg.

Question: does ANY long-only, cost-adjusted version (buy beaters) have positive
expectancy, or is the +28.8bp top-minus-bottom 1-day continuation purely a
short-side effect?

Replicates the exact event construction of catalyst_test.py (same entry
convention, same universe-adjusted market proxy), then drills into the LONG leg:
  (a) net-of-cost expectancy of the top-surprise bucket across cost levels
  (b) concentration: few names / few dates vs broad
  (c) liquidity filters (>$5 / >$10)
  (d) parameter stability: bucket count + surprise-signal sweep
Also splits by reportTime (pre vs post market) — the long leg is heterogeneous.

Research only. Survivorship: current-universe-only (disclosed).
"""
import boto3, io, json, os
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

B = 'trading-datalake-920641308584'
s3 = boto3.client('s3', region_name='us-east-1')

RT_BPS = [0, 5, 10, 15, 20]


# ---------------------------------------------------------------------------
# data loading
# ---------------------------------------------------------------------------
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
        r = d['close'].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        r = r.clip(-0.5, 0.5)
        rets.append(r)
    allr = pd.concat(rets, axis=1)
    mkt_ret = allr.mean(axis=1).dropna()
    return (1.0 + mkt_ret).cumprod()


def cluster_ttest(vals, day):
    vals = np.asarray(vals, float); day = np.asarray(day)
    m = ~np.isnan(vals)
    vals, day = vals[m], day[m]
    if len(vals) == 0:
        return dict(mean=np.nan, t=np.nan, n_events=0, n_days=0)
    df = pd.DataFrame({'v': vals, 'd': day})
    daily = df.groupby('d')['v'].mean()
    n = len(daily)
    mean = daily.mean()
    sd = daily.std(ddof=1)
    t = mean / (sd / np.sqrt(n)) if (sd > 0 and n > 1) else np.nan
    return dict(mean=float(mean), t=float(t) if not np.isnan(t) else None,
                n_events=int(len(vals)), n_days=int(n))


def leg_stats(sub, day_key='entry_date', raw_col='ret_1', madj_col='madj_1'):
    """Per-trade + day-clustered stats for a long leg (raw + market-adjusted)."""
    out = {}
    for label, col in [('raw', raw_col), ('madj', madj_col)]:
        v = sub[col].values
        tt = cluster_ttest(v, sub[day_key].values)
        net = {}
        for c in RT_BPS:
            net[str(c)] = round(float(np.nanmean(v)) - c, 3)
        out[label] = {
            'mean_bp': float(np.nanmean(v)),
            'median_bp': float(np.nanmedian(v)),
            'std_bp': float(np.nanstd(v, ddof=1)),
            'win_rate': float((np.asarray(v) > 0).mean()) if len(v) else None,
            'day_clustered_t': tt['t'],
            'day_clustered_mean_bp': tt['mean'],
            'n_events': int(len(sub)),
            'n_days': int(sub[day_key].nunique()),
            'net_after_roundtrip_bp': net,
        }
    return out


def main():
    # ---- symbol lists ----
    pag = s3.get_paginator('list_objects_v2')
    earn_keys = []
    for page in pag.paginate(Bucket=B, Prefix='av/earnings/'):
        earn_keys += [o['Key'] for o in page.get('Contents', []) if o['Key'].endswith('.json')]
    earn_syms = sorted(k.split('/')[-1].replace('.json', '') for k in earn_keys)

    daily_keys = []
    for page in pag.paginate(Bucket=B, Prefix='ibkr/equities/daily/'):
        daily_keys += [o['Key'] for o in page.get('Contents', []) if o['Key'].endswith('.parquet')]
    all_daily = set(k.split('/')[-1].replace('.parquet', '') for k in daily_keys)

    load_syms = [s for s in earn_syms if s in all_daily]
    daily = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for sym, df in ex.map(load_daily, load_syms):
            if df is not None:
                daily[sym] = df
    print(f'[load] daily for {len(daily)}/{len(load_syms)} earnings symbols', flush=True)
    mkt_idx = build_universe_index(daily)

    # ---- events (same convention as catalyst_test.py) ----
    rows = []
    for sym in earn_syms:
        if sym not in daily:
            continue
        d = daily[sym]
        close = d['close']; opn = d['open']; vol = d['volume']
        dates = close.index
        try:
            o = s3.get_object(Bucket=B, Key=f'av/earnings/{sym}.json')
            ed = json.loads(o['Body'].read().decode())
        except Exception:
            continue
        for r in ed.get('quarterlyEarnings', []):
            rd = r.get('reportedDate'); rt = r.get('reportTime')
            if not rd or not rt or rt not in ('pre-market', 'post-market'):
                continue
            try:
                D = pd.Timestamp(rd)
            except Exception:
                continue
            try:
                surp = float(r['surprise'])
            except Exception:
                continue
            est = r.get('estimatedEPS')
            try:
                est = float(est)
            except Exception:
                est = np.nan

            if rt == 'pre-market':
                pos = dates.searchsorted(D)
                if pos >= len(dates):
                    continue
                A_date = dates[pos]
                if pos == 0:
                    continue
                i_prior = pos - 1
            else:  # post-market
                pos = dates.searchsorted(D, side='right')
                if pos >= len(dates):
                    continue
                A_date = dates[pos]
                i_prior = pos - 1

            iA = close.index.get_loc(A_date)
            if iA + 1 >= len(dates):
                continue
            entry_close = float(close.iloc[iA])
            prior_close = float(close.iloc[i_prior])
            if not np.isfinite(entry_close) or not np.isfinite(prior_close) or entry_close <= 0 or prior_close <= 0:
                continue
            exit_close = float(close.iloc[iA + 1])
            if not np.isfinite(exit_close) or exit_close <= 0:
                continue
            ret = exit_close / entry_close - 1.0
            # universe market return over the same 1-day window
            try:
                m0 = mkt_idx.loc[A_date]; m1 = mkt_idx.loc[dates[iA + 1]]
                mret = m1 / m0 - 1.0
            except Exception:
                mret = np.nan
            vol_entry = vol.iloc[iA] if 'volume' in d.columns else np.nan
            rows.append({
                'sym': sym, 'entry_date': str(A_date.date()),
                'reportTime': rt,
                'surprise': surp, 'estimatedEPS': est,
                'surp_pct': surp / prior_close * 100.0,
                'sue': surp / abs(est) if (est is not None and not np.isnan(est) and est != 0) else np.nan,
                'entry_price': entry_close,
                'entry_volume': float(vol_entry) if np.isfinite(vol_entry) else np.nan,
                'ret_1': ret * 1e4,
                'madj_1': (ret - mret) * 1e4,
            })
    df = pd.DataFrame(rows).dropna(subset=['ret_1', 'madj_1'])
    df['surp_pct_w'] = df['surp_pct'].clip(-5, 5)
    df['sue_w'] = df['sue'].clip(-3, 3)
    df = df.sort_values('entry_date').reset_index(drop=True)
    print(f'[events] {len(df)} events, {df["sym"].nunique()} symbols, '
          f'{df["entry_date"].min()} .. {df["entry_date"].max()}', flush=True)

    results = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'n_events': int(len(df)), 'n_symbols': int(df['sym'].nunique()),
        'entry_date_range': [df['entry_date'].min(), df['entry_date'].max()],
        'survivorship': 'CURRENT-UNIVERSE-ONLY (149 mega/large-caps); upper-bound.',
        'convention': 'pre-market->close(D); post-market->close(D+1); forward = close->next close; madj = minus universe EW index.',
    }

    # ---- quintile assignment (rank-first to handle ties, as in catalyst_test) ----
    df['rank'] = df['surp_pct_w'].rank(method='first')
    df['q'] = pd.qcut(df['rank'], 5, labels=False)
    top = df[df['q'] == df['q'].max()]
    bot = df[df['q'] == df['q'].min()]

    # ---- (a) core long-only leg ----
    results['long_only_top_quintile'] = {
        'n_events': int(len(top)), 'n_symbols': int(top['sym'].nunique()),
        'stats': leg_stats(top),
    }
    results['short_side_bottom_quintile'] = {
        'n_events': int(len(bot)), 'n_symbols': int(bot['sym'].nunique()),
        'stats': leg_stats(bot),
    }
    # long-short spread for reference
    spread = cluster_ttest(
        np.concatenate([top['madj_1'].values, -bot['madj_1'].values]),
        np.concatenate([top['entry_date'].values, bot['entry_date'].values]))
    results['long_short_spread'] = {
        'spread_bp': float(top['madj_1'].mean() - bot['madj_1'].mean()),
        'day_clustered_t': spread['t'],
    }

    # ---- long-leg variants (could any be positive net of cost?) ----
    df = df.dropna(subset=['sue_w'])
    variants = {}
    # top decile
    df['decile'] = pd.qcut(df['rank'], 10, labels=False)
    variants['top_decile'] = leg_stats(df[df['decile'] == df['decile'].max()])
    # all positive surprise
    variants['all_positive_surprise'] = leg_stats(df[df['surp_pct_w'] > 0])
    # top quintile by SUE
    df['sue_rank'] = df['sue_w'].rank(method='first')
    df['sue_q'] = pd.qcut(df['sue_rank'], 5, labels=False)
    variants['top_quintile_by_sue'] = leg_stats(df[df['sue_q'] == df['sue_q'].max()])
    # reportTime split of the top surprise quintile
    for t in ['pre-market', 'post-market']:
        sub = top[top['reportTime'] == t]
        variants[f'top_quintile_{t}'] = {'n_events': int(len(sub)), **leg_stats(sub)}
    results['long_leg_variants'] = variants

    # ---- (b) concentration: names & dates ----
    conc = {}
    # name-level: mean raw 1d return per symbol within top quintile
    bysym = top.groupby('sym')['ret_1'].agg(['mean', 'count']).sort_values('mean', ascending=False)
    # total positive contribution and concentration
    sym_contrib = top.groupby('sym')['ret_1'].sum().sort_values(ascending=False)
    total_pos = sym_contrib[sym_contrib > 0].sum()
    cum = sym_contrib[sym_contrib > 0].cumsum() / total_pos
    n_for_half = int((cum <= 0.5).sum()) + 1
    conc['top_quintile_n_symbols'] = int(len(bysym))
    conc['symbols_for_50pct_positive_contrib'] = int(n_for_half)
    conc['top_10_symbols_mean_ret_bp'] = round(float(bysym.head(10)['mean'].mean()), 3)
    conc['top_10_symbols_event_share'] = round(float(bysym.head(10)['count'].sum() / len(top)), 3)
    # jackknife: drop top-10 contributing symbols
    keep = top[~top['sym'].isin(sym_contrib.head(10).index)]
    conc['excl_top10_symbols_long_mean_bp'] = round(float(keep['ret_1'].mean()), 3)
    conc['excl_top10_symbols_madj_mean_bp'] = round(float(keep['madj_1'].mean()), 3)
    conc['excl_top10_symbols_n'] = int(len(keep))
    # date-level: mean daily return of top-quintile events
    byday = top.groupby('entry_date')['ret_1'].mean().sort_values(ascending=False)
    conc['top_quintile_n_days'] = int(len(byday))
    conc['top_10_days_mean_ret_bp'] = round(float(byday.head(10).mean()), 3)
    conc['top_10_days_event_share'] = round(float(top[top['entry_date'].isin(byday.head(10).index)].shape[0] / len(top)), 3)
    keepd = top[~top['entry_date'].isin(byday.head(10).index)]
    conc['excl_top10_days_long_mean_bp'] = round(float(keepd['ret_1'].mean()), 3)
    conc['excl_top10_days_madj_mean_bp'] = round(float(keepd['madj_1'].mean()), 3)
    conc['excl_top10_days_n'] = int(len(keepd))
    # day-block bootstrap CI for the long leg (raw + madj)
    bs = {}
    for col in ['ret_1', 'madj_1']:
        daily_mean = top.groupby('entry_date')[col].mean().values
        rng = np.random.default_rng(0)
        means = [rng.choice(daily_mean, size=len(daily_mean), replace=True).mean()
                 for _ in range(2000)]
        means = np.sort(means)
        bs[col] = {'mean_bp': round(float(np.mean(daily_mean)), 3),
                   'ci_low_2.5': round(float(means[50]), 3),
                   'ci_high_97.5': round(float(means[1949]), 3)}
    conc['day_block_bootstrap_ci'] = bs
    results['concentration'] = conc

    # ---- (c) liquidity filters ----
    liq = {}
    for thr, label in [(5, 'gt_5'), (10, 'gt_10')]:
        sub = top[top['entry_price'] > thr]
        sub_liq = df[df['entry_price'] > thr]
        liq[label] = {
            'price_threshold': thr,
            'n_top_events': int(len(sub)), 'share_of_top': round(float(len(sub) / len(top)), 3),
            'top_long_stats': leg_stats(sub),
            # full-sample long-short spread on liquid-only subset (context)
            'full_long_short_on_liq': {
                'n': int(len(sub_liq)),
            },
        }
    # dollar-volume liquidity (>= $10M/day), if volume present
    if df['entry_volume'].notna().any():
        dv = top['entry_price'] * top['entry_volume']
        for thr, label in [(10e6, 'dvol_gt_10M'), (50e6, 'dvol_gt_50M')]:
            sub = top[dv > thr]
            liq[label] = {
                'dollar_volume_threshold': thr,
                'n_top_events': int(len(sub)), 'share_of_top': round(float(len(sub) / len(top)), 3),
                'top_long_stats': leg_stats(sub),
            }
    results['liquidity'] = liq

    # ---- (d) parameter stability: bucket count + signal sweep ----
    stab = {'bucket_count_sweep': {}, 'signal_sweep': {}}
    for nq in [2, 3, 4, 5, 6, 10]:
        rk = df['surp_pct_w'].rank(method='first')
        q = pd.qcut(rk, nq, labels=False)
        t = df[q == q.max()]; b = df[q == q.min()]
        stab['bucket_count_sweep'][str(nq)] = {
            'top_n': int(len(t)),
            'top_raw_mean_bp': round(float(t['ret_1'].mean()), 3),
            'top_madj_mean_bp': round(float(t['madj_1'].mean()), 3),
            'top_madj_t': cluster_ttest(t['madj_1'].values, t['entry_date'].values)['t'],
            'bot_madj_mean_bp': round(float(b['madj_1'].mean()), 3),
            'spread_madj_bp': round(float(t['madj_1'].mean() - b['madj_1'].mean()), 3),
            'spread_madj_t': cluster_ttest(
                np.concatenate([t['madj_1'].values, -b['madj_1'].values]),
                np.concatenate([t['entry_date'].values, b['entry_date'].values]))['t'],
        }
    for name, sig in [('surp_pct', df['surp_pct_w']), ('sue', df['sue_w'])]:
        rk = sig.rank(method='first')
        q = pd.qcut(rk, 5, labels=False)
        t = df[q == q.max()]; b = df[q == q.min()]
        stab['signal_sweep'][name] = {
            'top_n': int(len(t)),
            'top_raw_mean_bp': round(float(t['ret_1'].mean()), 3),
            'top_madj_mean_bp': round(float(t['madj_1'].mean()), 3),
            'top_madj_t': cluster_ttest(t['madj_1'].values, t['entry_date'].values)['t'],
            'bot_madj_mean_bp': round(float(b['madj_1'].mean()), 3),
            'spread_madj_bp': round(float(t['madj_1'].mean() - b['madj_1'].mean()), 3),
            'spread_madj_t': cluster_ttest(
                np.concatenate([t['madj_1'].values, -b['madj_1'].values]),
                np.concatenate([t['entry_date'].values, b['entry_date'].values]))['t'],
        }
    results['parameter_stability'] = stab

    # ---- verdict ----
    top_madj = float(top['madj_1'].mean()); top_raw = float(top['ret_1'].mean())
    results['verdict'] = {
        'long_leg_gross': {'raw_bp': round(top_raw, 3), 'madj_bp': round(top_madj, 3)},
        'net_at_5bp_raw': round(top_raw - 5, 3),
        'net_at_10bp_raw': round(top_raw - 10, 3),
        'net_at_15bp_raw': round(top_raw - 15, 3),
        'net_at_20bp_raw': round(top_raw - 20, 3),
    }

    out = '/home/ubuntu/trading-system/research/atomics/pead_stress_results.json'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w') as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f'\n[done] wrote {out}', flush=True)

    # ---- console summary ----
    print('\n================ PEAD STRESS ================')
    for k in ['long_only_top_quintile', 'short_side_bottom_quintile']:
        s = results[k]['stats']
        print(f"\n{k}: n={s['raw']['n_events']} events, {results[k]['n_symbols']} symbols")
        for lab in ['raw', 'madj']:
            x = s[lab]
            print(f"  {lab}: mean={x['mean_bp']:+.2f}bp med={x['median_bp']:+.2f}bp win={x['win_rate']*100:.1f}% t={x['day_clustered_t']:+.2f} n_days={x['n_days']}")
            print(f"       net: " + " ".join(f"{c}bp->{x['net_after_roundtrip_bp'][str(c)]:+.1f}" for c in RT_BPS))
    print('\n-- long leg variants (madj mean / t) --')
    for k, v in variants.items():
        mm = v.get('madj', v)
        print(f"  {k}: madj_mean={mm['mean_bp']:+.2f}bp t={mm['day_clustered_t']:+.2f} n={mm['n_events']}")
    print('\n-- concentration --')
    for k, v in conc.items():
        if k != 'day_block_bootstrap_ci':
            print(f"  {k}: {v}")
    print('\n-- liquidity --')
    for k, v in liq.items():
        ts = v['top_long_stats']['raw']
        print(f"  {k}: n={v['n_top_events']} raw_mean={ts['mean_bp']:+.2f}bp madj_mean={v['top_long_stats']['madj']['mean_bp']:+.2f}bp t={v['top_long_stats']['madj']['day_clustered_t']:+.2f}")
    print('\n-- bucket stability --')
    for k, v in stab['bucket_count_sweep'].items():
        print(f"  {k} buckets: top_madj={v['top_madj_mean_bp']:+.2f}bp t={v['top_madj_t']:+.2f} | spread={v['spread_madj_bp']:+.2f}bp t={v['spread_madj_t']:+.2f}")


if __name__ == '__main__':
    main()
