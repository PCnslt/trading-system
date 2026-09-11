#!/usr/bin/env python3
"""Intraday half-hour periodicity + cross-half-hour reversal (queue strat-20260910-2).

Heston, Korajczyk & Sadka 2010, "Intraday Patterns in the Cross-section of Stock
Returns" (JF 65(6)): (a) PERIODICITY -- a stock's return in a given 30-min window
is positively autocorrelated with the SAME window on prior days (same-window
continuation); (b) REVERSAL -- strong cross-sectional reversal in the opening and
closing half-hours (names that sell off in a half-hour bounce next session).

This script tests BOTH honestly on intraday bars:

PART A -- verify the two claims directly:
  A1 periodicity : corr(same-window return[t], same-window return[t-1]) pooled
                   across symbols/windows (claim: strongly positive, ~30-min period).
  A2 reversal    : bottom-decile 30-min return -> next-window return, and next-open
                   return, by window (opening vs closing half-hours strongest).

PART B -- tradeable long-only mean-reversion (the queue's spec): buy the bottom-
         decile 30-min intraday return names, hold 1 session (next window, and next
         open), and the same-window periodicity continuation leg. Cost 5 bps/side
         primary, 10 bps/side 2x stress (intraday => cost-sensitive; kill if edge
         < 2x the ~14.4bp RTH round-trip).

Data: ibkr/equities/1min/{sym}/YYYY-MM.parquet (61 liquid names, ~2024-09..2026-09),
aggregated to 30-min windows (13 windows per RTH day). IS/OOS split at 2025-09-01.
"""
from __future__ import annotations

import io, os, sys, json, argparse
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'research'))

import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, '.env'))

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
OOS_FROM = '2025-09-01'
COSTS = (0.0005, 0.0010)   # 5 bps, 10 bps per side
NDEC = 10                  # decile rank for cross-sectional reversal
WIN_MIN = 30               # half-hour windows


def list_months(s3, sym):
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=f'ibkr/equities/1min/{sym}/', MaxKeys=100)
    return [o['Key'] for o in r.get('Contents', []) if o['Key'].endswith('.parquet')]


def load_sym(s3, sym):
    keys = list_months(s3, sym)
    parts = []
    for k in keys:
        try:
            o = s3.get_object(Bucket=BUCKET, Key=k)
            parts.append(pd.read_parquet(io.BytesIO(o['Body'].read())))
        except Exception:
            pass
    if not parts:
        return None
    df = pd.concat(parts).sort_values('ts')
    df['dt'] = pd.to_datetime(df['ts'], unit='s', utc=True).dt.tz_convert('America/New_York')
    df = df[df['dt'].dt.time >= pd.Timestamp('09:30').time()].copy()
    df = df[df['dt'].dt.time <= pd.Timestamp('15:59:59').time()].copy()
    df = df[['dt', 'open', 'close']].drop_duplicates('dt').set_index('dt')
    if len(df) < 5000:
        return None
    return df


def halfhour_windows(df):
    """Aggregate 1-min to 30-min windows. Return DataFrame with columns
    day, win (0..12), wopen, wclose, prev_close."""
    df = df.copy()
    day = df.index.normalize().tz_localize(None)   # naive date for clean IS/OOS compare
    minutes = df.index.hour * 60 + df.index.minute - 570   # 09:30 => 0
    win = (minutes // WIN_MIN).astype(int)
    g = df.groupby([day, win])
    wopen = g['open'].first()
    wclose = g['close'].last()
    res = pd.DataFrame({'wopen': wopen, 'wclose': wclose})
    # previous window close (for return); for win 0 use prior day close
    res = res.sort_index()
    res.index.names = ['day', 'win']
    res['prev_close'] = res['wclose'].shift(1)
    return res


def stats(rets):
    r = np.asarray([x for x in rets if x == x and np.isfinite(x)], dtype=float)
    if len(r) < 30:
        return None
    w, l = r[r > 0].sum(), -r[r <= 0].sum()
    pf = w / l if l > 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 and len(r) > 1 else 0.0
    return {'n': int(len(r)), 'pf': round(pf, 3), 'win': round(float((r > 0).mean()), 3),
            'avg_bp': round(float(r.mean() * 1e4), 1), 't': round(float(t), 2)}


def net_ret(entry, exit_, bps):
    return exit_ * (1 - bps) / (entry * (1 + bps)) - 1.0


def split_rets(rets, dates):
    isr = [r for r, d in zip(rets, dates) if d < pd.Timestamp(OOS_FROM)]
    oor = [r for r, d in zip(rets, dates) if d >= pd.Timestamp(OOS_FROM)]
    return isr, oor


def cell(rets, dates):
    if not rets:
        return None
    isr, oor = split_rets(rets, dates)
    return {'all': stats(rets), 'is': stats(isr), 'oos': stats(oor)}


def fmt(s):
    if not s or s['n'] == 0:
        return '     n/a'
    return (f"n={s['n']:>6} PF={s['pf']:>6.3f} win={s['win']*100:>5.1f}% "
            f"avg={s['avg_bp']:>7.1f}bp t={s['t']:>5.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix='ibkr/equities/1min/', Delimiter='/')
    syms = sorted(c['Prefix'].split('/')[-2] for c in r.get('CommonPrefixes', []))
    if a.limit:
        syms = syms[:a.limit]
    print(f'loading {len(syms)} symbols 1-min bars…', flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        loaded = {s: d for s, d in zip(syms, ex.map(lambda x: load_sym(s3, x), syms)) if d is not None}
    print(f'  usable {len(loaded)} symbols\n', flush=True)

    # Build (symbol -> window table)
    wins = {}
    for sym, df in loaded.items():
        wins[sym] = halfhour_windows(df)

    out = {}

    # ============ PART A1: periodicity (same-window autocorr) ============
    print('=' * 88)
    print('PART A1 — same-window PERIODICITY (corr window-w return[t] vs return[t-1])')
    print('=' * 88)
    periodicity = {}
    for lag in (1, 5):
        cors, ns = [], 0
        corr_by_win = defaultdict(list)
        for sym, w in wins.items():
            ret = w['wclose'] / w['prev_close'] - 1.0
            s = ret.rename('ret').reset_index()
            for wi, grp in s.groupby('win'):
                g = grp.set_index('day')['ret']
                a, b = g.shift(lag), g
                m = a.notna() & b.notna()
                if m.sum() > 20:
                    c = np.corrcoef(a[m], b[m])[0, 1]
                    corr_by_win[wi].append(c)
                    cors.append(c); ns += 1
        cors = np.asarray(cors)
        mean_c = cors.mean() if len(cors) else float('nan')
        se = cors.std(ddof=1) / np.sqrt(len(cors)) if len(cors) > 1 else float('nan')
        t = mean_c / se if se and se > 0 else float('nan')
        periodicity[f'lag{lag}'] = {
            'mean_corr': round(float(mean_c), 4), 't': round(float(t), 2),
            'n_series': int(ns), 'corr_by_win': {int(k): round(float(np.mean(v)), 4) for k, v in sorted(corr_by_win.items())},
        }
        print(f'  lag {lag}d: mean same-window corr = {mean_c:+.4f}  t={t:+.2f}  (n_series={ns})')
    out['partA1_periodicity'] = periodicity
    print('  (claim: strongly positive ~30-min period)\n')

    # ============ PART A2: reversal (bottom-decile 30min -> next-window / next-open) ============
    print('=' * 88)
    print('PART A2 — cross-sectional REVERSAL: bottom-decile 30-min return -> fwd return')
    print('=' * 88)
    # For each (day, win), rank symbols by window return; bottom decile.
    # Build per-symbol window table keyed by (day, win) for vectorized cross-section.
    sym_ret = {}
    sym_prev = {}
    for sym, w in wins.items():
        w = w.copy()
        w['ret'] = w['wclose'] / w['prev_close'] - 1.0
        w['next_win_ret'] = w.groupby(level='day')['wclose'].shift(-1) / w['wclose'] - 1.0
        w['next_open'] = w.groupby(level='day')['wopen'].shift(-1)
        # next trading day's OPEN (first window wopen), aligned per (day,win)
        first_open = w[w.index.get_level_values('win') == 0][['wopen']]
        first_open = first_open.reset_index().set_index('day')['wopen']  # day -> wopen[win0]
        ndo = first_open.shift(-1)                                       # next day's open
        w['next_day_open'] = ndo.reindex(w.index.get_level_values('day')).values
        sym_ret[sym] = w
    # assemble cross-sectional frame: index (day, win), columns = symbols
    ret_panel = pd.DataFrame({s: w['ret'] for s, w in sym_ret.items()})
    nextwin_panel = pd.DataFrame({s: w['next_win_ret'] for s, w in sym_ret.items()})
    nextopen_panel = pd.DataFrame({s: w['next_day_open'] / w['wclose'] - 1.0 for s, w in sym_ret.items()})

    # reversal: bottom decile by window return
    rank = ret_panel.rank(axis=1, pct=True)
    bottom = (rank <= 1 / NDEC)

    def decile_fwd(fwd_panel, bottom_mask, bps=None):
        """mean next-window return of bottom-decile names each (day,win)."""
        n = bottom_mask.sum(axis=1)
        fwd = (fwd_panel * bottom_mask).sum(axis=1) / n.replace(0, np.nan)
        fwd = fwd.dropna()
        rets = []
        for v in fwd.values:
            rets.append(v if bps is None else v - 2 * bps)   # round-trip = 2 sides
        return fwd, rets, list(fwd.index.get_level_values(0))

    print('  bottom-decile 30-min return -> NEXT WINDOW return (mean, by half-hour):')
    fwd_nw, rets_nw, dates_nw = decile_fwd(nextwin_panel, bottom)
    by_win = {}
    for wi, grp in fwd_nw.groupby(level=1):
        by_win[int(wi)] = round(float(grp.mean() * 1e4), 1)
    for wi in (0, 1, 6, 11, 12):
        print(f'    win {wi:2d} ({(wi*30+570)//60:02d}:{(wi*30+570)%60:02d}): '
              f'{by_win.get(wi, float("nan")):+.1f} bp')
    s0 = stats([r for r in rets_nw if r == r])
    print(f'    pooled gross: {fmt(stats([r + 0 for r in rets_nw if r == r])) if s0 else "n/a"}')

    # next-OPEN reversal (closing half-hours -> next open), the paper's headline
    print('\n  bottom-decile 30-min return -> NEXT OPEN return (mean, by half-hour):')
    fwd_no, rets_no, dates_no = decile_fwd(nextopen_panel, bottom)
    by_win_no = {}
    for wi, grp in fwd_no.groupby(level=1):
        by_win_no[int(wi)] = round(float(grp.mean() * 1e4), 1)
    for wi in (0, 11, 12):
        print(f'    win {wi:2d}: {by_win_no.get(wi, float("nan")):+.1f} bp')
    out['partA2'] = {
        'nextwin_by_win_bp': by_win, 'nextopen_by_win_bp': by_win_no,
        'nextwin_pooled_gross': stats([r for r in rets_nw if r == r]),
    }

    # ============ PART B: tradeable long-only reversal lane ============
    print('\n' + '=' * 88)
    print('PART B — tradeable long-only: buy bottom-decile 30-min losers')
    print('=' * 88)
    for bps in COSTS:
        print(f'\n  @{bps*1e4:.0f}bps/side:')
        # (1) hold next window
        rets, dates = [], []
        for (d, wi) in bottom.index:
            names = [s for s in bottom.columns if bottom.loc[(d, wi), s]]
            if not names:
                continue
            for s in names:
                e = sym_ret[s].loc[(d, wi), 'wclose']
                x = sym_ret[s].loc[(d, wi), 'wclose'] * (1 + nextwin_panel.loc[(d, wi), s]) if pd.notna(nextwin_panel.loc[(d, wi), s]) else np.nan
                if pd.notna(e) and pd.notna(x):
                    rets.append(net_ret(e, x, bps)); dates.append(d)
        c = cell(rets, dates)
        print(f'    next-window hold {fmt(c["all"]) if c else "n/a"}   IS {fmt(c["is"]) if c else ""}   OOS {fmt(c["oos"]) if c else ""}')
        out[f'B_nextwin_{bps}'] = c
        # (2) hold to next open (overnight after closing half-hours only, win>=10)
        rets, dates = [], []
        for (d, wi) in bottom.index:
            if wi < 10:
                continue
            names = [s for s in bottom.columns if bottom.loc[(d, wi), s]]
            for s in names:
                e = sym_ret[s].loc[(d, wi), 'wclose']
                x = sym_ret[s].loc[(d, wi), 'next_day_open']   # exit = next day open (PRICE)
                if pd.notna(e) and pd.notna(x) and e > 0:
                    rets.append(net_ret(e, x, bps)); dates.append(d)
        c = cell(rets, dates)
        print(f'    close-half->next-open {fmt(c["all"]) if c else "n/a"}   IS {fmt(c["is"]) if c else ""}   OOS {fmt(c["oos"]) if c else ""}')
        out[f'B_nextopen_closehalf_{bps}'] = c

    # PART B periodicity continuation leg (same-window yesterday up -> buy window open -> window close)
    print('\n' + '=' * 88)
    print('PART B-cont — same-window periodicity CONTINUATION (tradeable leg)')
    print('=' * 88)
    for bps in COSTS:
        rets, dates = [], []
        for sym, w in wins.items():
            ret = w['wclose'] / w['prev_close'] - 1.0
            # yesterday's same-window return
            s = ret.rename('ret').reset_index()
            for wi, grp in s.groupby('win'):
                g = grp.set_index('day')['ret']
                prev = g.shift(1)
                m = prev.notna() & (prev > 0)
                for d in g.index[m]:
                    # buy window open, sell window close (today)
                    e = wins[sym].loc[(d, wi), 'wopen']
                    x = wins[sym].loc[(d, wi), 'wclose']
                    if pd.notna(e) and pd.notna(x) and e > 0:
                        rets.append(net_ret(e, x, bps)); dates.append(d)
        c = cell(rets, dates)
        print(f'  @{bps*1e4:.0f}bps/side same-win-continuation {fmt(c["all"]) if c else "n/a"}   '
              f'IS {fmt(c["is"]) if c else ""}   OOS {fmt(c["oos"]) if c else ""}')
        out[f'Bcont_periodicity_{bps}'] = c

    json.dump(out, open(os.path.join(_ROOT, 'research', 'intraday_periodicity_results.json'), 'w'),
              indent=1, default=str)
    print('\nwrote research/intraday_periodicity_results.json')


if __name__ == '__main__':
    main()
