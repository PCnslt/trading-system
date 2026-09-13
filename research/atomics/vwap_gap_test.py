#!/usr/bin/env python3
"""
VWAP mean-reversion + pre-market gap continuation/reversal — intraday 5-min bar test.

Two causal, market-adjusted, cost-net, chronologically-OOS tests on the 40-symbol
ibkr/equities/5min/ universe.

  (1) VWAP mean-reversion:
      Signal at bar t (session cumulative VWAP from open, using IBKR bar `average`
      price): dist = close_t / session_vwap_t - 1.  If dist > thr (extended above
      VWAP) do we see mean-reversion (negative forward return) over the next 30m/60m?
      Only info <= t is used; forward return strictly after t and same-day only.
      Primary = first-cross-per-day (non-overlapping), secondary = all bars.

  (2) Pre-market gap variant:
      gap = open / prior_close - 1.  first-30m RVOL = first-6-bar volume / 20d mean
      (shifted 1 day, causal).  Enter at the 10:00 close (after observing the opening
      volume), exit at the close.  Does gap direction + opening volume predict
      continuation (fwd sign == gap sign) vs reversal?  Bucket by gap direction x
      RVOL (>=1 vs <1, plus terciles).

Market adjustment: subtract the equal-weight cross-sectional mean forward return of the
40 symbols over the same window/timestamp (no index in this universe).
Costs: 5 / 10 / 20 bp total round-trip.
OOS: chronological 70/30 split by calendar date (no fitting -> split is a stability
check, not model selection).
"""
import io, json
import numpy as np
import pandas as pd
import boto3

S3 = boto3.client('s3', region_name='us-east-1')
B = 'trading-datalake-920641308584'
P5 = 'ibkr/equities/5min/'

COSTS_BP = [5, 10, 20]
HORIZONS = {'30m': 6, '60m': 12}
VWAP_THRESHOLDS = [0.015, 0.020, 0.025]
GAP_MIN = [0.005, 0.010]  # abs gap floor (fraction)
WARMUP_BARS = 6            # bars into session before VWAP signal is allowed


def load_syms():
    r = S3.list_objects_v2(Bucket=B, Prefix=P5)
    syms = sorted(o['Key'].split('/')[-1].replace('.parquet', '')
                  for o in r.get('Contents', []))
    frames = {}
    for s in syms:
        o = S3.get_object(Bucket=B, Key=f'{P5}{s}.parquet')['Body'].read()
        df = pd.read_parquet(io.BytesIO(o))
        df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
        df = df.set_index('date')
        df = df[~df.index.duplicated(keep='last')]
        df['sym'] = s
        df['day'] = df.index.normalize()
        frames[s] = df
    return frames


def build_long(frames):
    L = pd.concat(frames.values())
    L = L.sort_values(['sym', 'day', 'date'])
    # session cumulative VWAP from IBKR bar-average price
    L['av_v'] = L['average'] * L['volume']
    L['cum_av_v'] = L.groupby(['sym', 'day'])['av_v'].cumsum()
    L['cum_v'] = L.groupby(['sym', 'day'])['volume'].cumsum()
    L['vwap'] = L['cum_av_v'] / L['cum_v']
    L['dist'] = L['close'] / L['vwap'] - 1.0
    # running session high (for "extended" = making new intraday high)
    L['sess_high_run'] = L.groupby(['sym', 'day'])['high'].cummax()
    # bar index within day
    L['bar_idx'] = L.groupby(['sym', 'day']).cumcount()
    return L


def add_forward_returns(L):
    """Forward close returns over h bars, same-day masked."""
    for name, h in HORIZONS.items():
        c = L.groupby('sym')['close']
        L[f'close_fwd_{h}'] = c.shift(-h)
        d = L.groupby('sym')['day']
        L[f'day_fwd_{h}'] = d.shift(-h)
        same = L[f'day_fwd_{h}'] == L['day']
        L[f'fwd_{name}'] = np.where(same, L[f'close_fwd_{h}'] / L['close'] - 1.0, np.nan)
        # market (cross-sectional) forward return at same timestamp
        mkt = L.groupby('date')[f'fwd_{name}'].transform('mean')
        L[f'fwd_{name}_adj'] = L[f'fwd_{name}'] - mkt
    return L


def stats(x_bp, x_days):
    x = np.asarray(x_bp, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return None
    d = np.asarray(x_days)[~np.isnan(x_bp)] if len(x_days) else np.array([])
    n = len(x)
    mean = float(x.mean())
    med = float(np.median(x))
    std = float(x.std(ddof=1)) if n > 1 else 0.0
    tstat = float(mean / (std / np.sqrt(n))) if std > 0 else 0.0
    # date-clustered t-stat (mean of daily means)
    tc = 0.0
    n_days = 0
    if len(d):
        daily = pd.Series(x).groupby(pd.Series(d)).mean()
        n_days = len(daily)
        dstd = daily.std(ddof=1) if n_days > 1 else 0.0
        tc = float(daily.mean() / (dstd / np.sqrt(n_days))) if dstd > 0 else 0.0
    return dict(n=n, n_days=n_days, mean_bp=mean, median_bp=med,
                std_bp=std, tstat=tstat, tstat_daily=tc)


def reversion_block(events, label):
    """For a set of VWAP events: report reversion over both horizons + net short."""
    out = {}
    for name in HORIZONS:
        col = f'fwd_{name}'
        adj = f'fwd_{name}_adj'
        for kind, c in [('raw', col), ('market_adj', adj)]:
            r = stats(events[c] * 1e4, events['day'])
            if r is None:
                continue
            hit = float((events[c] < 0).mean())
            r['reversion_hit_rate'] = hit
            out[f'{name}_{kind}'] = r
        # net short return (market-adjusted) at each cost
        net = {}
        adj_bp = events[adj] * 1e4
        for cbp in COSTS_BP:
            t = -adj_bp - cbp
            net[f'{cbp}bp'] = stats(t, events['day'])
        out[f'{name}_net_short'] = net
    return out


def vwap_analysis(L, oos_days):
    results = {}
    variants = {
        'vwap_only': L['dist'] > 0,          # placeholder, set per-thr below
        'vwap_extended': L['dist'] > 0,      # placeholder
    }
    for thr in VWAP_THRESHOLDS:
        thr_res = {}
        base = L['dist'] > thr
        variants = {
            'vwap_only': base,
            'vwap_extended': base & (L['close'] >= L['sess_high_run'] * 0.9995),
        }
        for vname, extra in variants.items():
            sig = extra & (L['bar_idx'] >= WARMUP_BARS)
            cross = L[sig].copy()
            cross = cross.sort_values(['sym', 'day', 'date'])
            first = cross.groupby(['sym', 'day'], as_index=False).first()
            allb = L[sig].copy()
            vres = {}
            for scope, ev in [('first_cross_per_day', first), ('all_bars', allb)]:
                sc = {}
                for split, mask in [('full', ev['day'].notna()),
                                    ('oos', ev['day'].isin(oos_days))]:
                    sub = ev[mask]
                    sc[split] = reversion_block(sub, scope)
                vres[scope] = sc
            thr_res[vname] = vres
        results[f'thr_{thr:.3f}'] = thr_res
    return results


def gap_analysis(L, oos_days):
    """Gap direction x opening-volume -> continuation vs reversal to close."""
    L = L.copy()
    # prior close per symbol
    day_close = L.groupby(['sym', 'day'])['close'].last()
    day_open = L.groupby(['sym', 'day'])['open'].first()
    first30 = L[L['bar_idx'] < 6].groupby(['sym', 'day'])['volume'].sum()
    entry10 = L[L['bar_idx'] == 5].groupby(['sym', 'day'])['close'].last()

    rows = []
    for (sym, day), oc in day_open.items():
        if (sym, day) not in day_close.index:
            continue
        dc = day_close.loc[(sym, day)]
        if (sym, day) not in entry10.index:
            continue
        e10 = entry10.loc[(sym, day)]
        if oc <= 0 or dc <= 0 or e10 <= 0:
            continue
        rows.append((sym, day, oc, dc, e10, first30.get((sym, day), np.nan)))
    g = pd.DataFrame(rows, columns=['sym', 'day', 'open', 'close', 'entry10', 'first30vol'])

    # prior close: previous session close per symbol
    g = g.sort_values(['sym', 'day'])
    g['prior_close'] = g.groupby('sym')['close'].shift(1)
    g['gap'] = g['open'] / g['prior_close'] - 1.0
    # first-30m RVOL: rolling 20-day mean shifted 1 day
    g['f30_roll'] = g.groupby('sym')['first30vol'].transform(
        lambda s: s.rolling(20, min_periods=10).mean().shift(1))
    g['rvol'] = g['first30vol'] / g['f30_roll']
    g['fwd'] = g['close'] / g['entry10'] - 1.0  # entry 10:00 -> close
    g['fwd_open'] = g['close'] / g['open'] - 1.0  # open -> close (reference)

    # market adjustment: cross-sectional mean of same-day forward (entry->close)
    mkt = g.groupby('day')['fwd'].transform('mean')
    g['fwd_adj'] = g['fwd'] - mkt
    mkt_open = g.groupby('day')['fwd_open'].transform('mean')
    g['fwd_open_adj'] = g['fwd_open'] - mkt_open

    g['gap_dir'] = np.sign(g['gap'])
    g = g[g['gap'].abs() >= GAP_MIN[0]].copy()  # base filter applied in per-threshold loops

    results = {}
    for gmin in GAP_MIN:
        gg = g[g['gap'].abs() >= gmin].copy()
        gg['signed'] = gg['gap_dir'] * gg['fwd']           # trade-with-gap return (entry->close)
        gg['signed_adj'] = gg['gap_dir'] * gg['fwd_adj']
        gg['cont'] = (np.sign(gg['fwd']) == gg['gap_dir']).astype(float)
        gg['cont_adj'] = (np.sign(gg['fwd_adj']) == gg['gap_dir']).astype(float)

        # RVOL tercile cutpoints fit on IS only (chronological, no lookahead)
        is_mask = ~gg['day'].isin(oos_days)
        terc = np.quantile(gg.loc[is_mask, 'rvol'].dropna(), [1/3, 2/3])
        gg['rvol_bucket'] = pd.cut(gg['rvol'],
                                   [-np.inf, terc[0], terc[1], np.inf],
                                   labels=['low', 'mid', 'high'])

        r = {}
        # overall
        r['overall'] = _gap_stats(gg, oos_days)
        # by gap direction
        for dname, dmask in [('gap_up', gg['gap_dir'] > 0), ('gap_down', gg['gap_dir'] < 0)]:
            r[dname] = _gap_stats(gg[dmask], oos_days)
        # by RVOL (>=1 vs <1) within each gap direction
        for dname, dmask in [('gap_up', gg['gap_dir'] > 0), ('gap_down', gg['gap_dir'] < 0)]:
            sub = gg[dmask]
            r[f'{dname}_rvol_hi'] = _gap_stats(sub[sub['rvol'] >= 1.0], oos_days)
            r[f'{dname}_rvol_lo'] = _gap_stats(sub[sub['rvol'] < 1.0], oos_days)
        # tercile x direction
        for dname, dmask in [('gap_up', gg['gap_dir'] > 0), ('gap_down', gg['gap_dir'] < 0)]:
            sub = gg[dmask]
            for b in ['low', 'mid', 'high']:
                r[f'{dname}_{b}'] = _gap_stats(sub[sub['rvol_bucket'] == b], oos_days)
        results[f'gap_min_{gmin:.3f}'] = r
    return results


def _gap_stats(sub, oos_days):
    sub = sub.dropna(subset=['fwd_adj'])
    out = {}
    for split, mask in [('full', sub['day'].notna()),
                        ('oos', sub['day'].isin(oos_days))]:
        s = sub[mask]
        out[split] = dict(
            n=int(len(s)),
            continuation_rate=float(s['cont'].mean()) if len(s) else None,
            continuation_rate_adj=float(s['cont_adj'].mean()) if len(s) else None,
            mean_fwd_bp=float(s['fwd'].mean() * 1e4) if len(s) else None,
            mean_fwd_adj_bp=float(s['fwd_adj'].mean() * 1e4) if len(s) else None,
            mean_signed_bp=float(s['signed'].mean() * 1e4) if len(s) else None,
            mean_signed_adj_bp=float(s['signed_adj'].mean() * 1e4) if len(s) else None,
            net_5bp=float((s['signed_adj'] * 1e4 - 5).mean()) if len(s) else None,
            net_10bp=float((s['signed_adj'] * 1e4 - 10).mean()) if len(s) else None,
            net_20bp=float((s['signed_adj'] * 1e4 - 20).mean()) if len(s) else None,
            tstat_signed_adj=(float(s['signed_adj'].mean() /
                               (s['signed_adj'].std(ddof=1) / np.sqrt(len(s))))
                              if len(s) > 1 and s['signed_adj'].std() > 0 else None),
        )
    return out


def main():
    frames = load_syms()
    L = build_long(frames)
    L = add_forward_returns(L)

    days = np.sort(L['day'].unique())
    split = int(len(days) * 0.7)
    oos_days = set(days[split:])

    print(f'symbols={len(frames)} bars={len(L)} days={len(days)} '
          f'date_range={L["day"].min().date()}..{L["day"].max().date()} '
          f'OOS starts {pd.Timestamp(days[split]).date()}')

    vwap = vwap_analysis(L, oos_days)
    gap = gap_analysis(L, oos_days)

    out = {
        'task': 'vwap_gap_intraday',
        'description': ('VWAP mean-reversion (dist>thr above session VWAP -> 30m/60m reversion) '
                        'and pre-market gap continuation/reversal (gap dir x first-30m RVOL -> close). '
                        'Causal (info<=t), market-adjusted (cross-sectional mean), net of 5/10/20bp round-trip, '
                        'chronological 70/30 OOS. Session VWAP uses IBKR bar `average` price.'),
        'data': {
            'bucket': B, 'prefix': P5, 'n_symbols': len(frames),
            'n_bars': int(len(L)), 'n_days': int(len(days)),
            'date_min': str(L['day'].min().date()),
            'date_max': str(L['day'].max().date()),
            'oos_start': str(pd.Timestamp(days[split]).date()),
            'horizons': HORIZONS, 'vwap_thresholds': VWAP_THRESHOLDS,
            'warmup_bars': WARMUP_BARS, 'costs_bp': COSTS_BP,
            'gap_min': GAP_MIN,
        },
        'vwap_mean_reversion': vwap,
        'gap_continuation': gap,
        'notes': [
            'VWAP reversion_hit_rate = fraction of events with negative forward return '
            '(price reverted toward VWAP).  net_short = -(market_adj forward) - cost (a short).',
            'VWAP signal uses bar close vs cumulative session VWAP; entry at signal-bar close, '
            'exit close[t+h] same-day only (late-day events excluded). '
            'vwap_only = dist>thr; vwap_extended = dist>thr AND close at/near running session high.',
            'first_cross_per_day = one non-overlapping trade per symbol-day (primary); '
            'all_bars = every qualifying bar (overlapping, for reference).',
            'Gap: gap=open/prior_close-1; rvol=first30m vol / 20d mean (shift 1). Enter at 10:00 '
            'close (after observing opening volume), exit at close. continuation = sign(fwd)==sign(gap).',
            'signed return = sign(gap)*fwd (trade WITH the gap); net subtracts round-trip cost. '
            'A continuation_rate > 0.5 means gaps continue; < 0.5 means they reverse.',
            'RVOL terciles are fit on IS only (no lookahead); hi/lo split at rvol=1.0 is data-free.',
        ],
    }
    with open('research/atomics/vwap_gap_results.json', 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print('wrote research/atomics/vwap_gap_results.json')

    # ---- concise console summary ----
    print('\n===== VWAP MEAN-REVERSION (first-cross-per-day, market-adj) =====')
    for thr in VWAP_THRESHOLDS:
        for vname in ['vwap_only', 'vwap_extended']:
            node = vwap[f'thr_{thr:.3f}'][vname]['first_cross_per_day']
            for split in ['full', 'oos']:
                b = node[split]
                line = f'thr={thr*100:.1f}% {vname:14s} {split:4s}'
                for h in HORIZONS:
                    r = b[f'{h}_market_adj']
                    if r and r['n']:
                        line += (f' | {h} n={r["n"]} mean={r["mean_bp"]:+.1f}bp '
                                 f'rev={r["reversion_hit_rate"]*100:.0f}% t={r["tstat_daily"]:+.1f}')
                print(line)
    print('\n===== GAP CONTINUATION (signed_adj = trade-with-gap, market-adj) =====')
    for gmin in GAP_MIN:
        node = gap[f'gap_min_{gmin:.3f}']
        for k in ['overall', 'gap_up', 'gap_down', 'gap_up_rvol_hi', 'gap_up_rvol_lo',
                  'gap_down_rvol_hi', 'gap_down_rvol_lo']:
            s = node[k]['full']
            o = node[k]['oos']
            print(f'gm={gmin*100:.1f}% {k:16s} n={s["n"]} cont_adj={s["continuation_rate_adj"]*100:.0f}% '
                  f'signed_adj={s["mean_signed_adj_bp"]:+.1f}bp net10={s["net_10bp"]:+.1f}bp '
                  f'| OOS n={o["n"]} cont_adj={o["continuation_rate_adj"]*100:.0f}% '
                  f'signed_adj={o["mean_signed_adj_bp"]:+.1f}bp')


if __name__ == '__main__':
    main()
