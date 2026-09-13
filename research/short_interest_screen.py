#!/usr/bin/env python3
"""SHORT-INTEREST AVOIDANCE SCREEN — backtest on the live 524-name sub-$50 buy universe.

Question: does excluding the most-heavily-shorted names from the buy universe
improve OOS PF of the surviving long-only lanes (RSI2 / Broken Arrow) WITHOUT
collapsing trade count?

Data sources (verified free + point-in-time):
  * Short interest: FINRA bi-weekly Equity Short Interest files
      https://cdn.finra.org/equity/otcmarket/biweekly/shrtYYYYMMDD.csv
      (settlement 15th + month-end; full exchange-listed coverage since ~Jun 2021;
       earlier files are OTC-only per FINRA's own note). Fields used:
       currentShortPositionQuantity, averageDailyVolumeQuantity,
       daysToCoverQuantity, settlementDate.
  * Price bars: S3 ibkr/equities/daily/{SYM}.parquet (2006-08 .. 2026-09).
  * Universe: research/smallcap_universe_full.json (524 names, $2-$50, ADV>=50M).

Point-in-time discipline: a trade at date t uses the LATEST settlement snapshot s
with s <= t - PUB_LAG (PUB_LAG = 14 calendar days, >= FINRA's publication delay).
The screen ranks the universe by days-to-cover at snapshot s and drops names in the
top decile (>= p90) / top quintile (>= p80). Names absent from a snapshot are KEPT
(fail-open: they cannot be ranked).

Lanes (long-only, ~6bp round-trip = 3bp/side):
  * RSI2  : Connors RSI(2)<5 AND close>SMA200, enter next open, 2xATR stop,
            5-day time stop, revert (close>SMA5 | RSI2>70).  [stock_mr_engine]
  * BROKEN ARROW: prev close > rising 40MA, today close <= -8%, enter close,
            sell next open.  [candidate_backtest.py rule]
  * REV2  : index-futures lane (ES/NQ/YM) — N/A: no per-name short interest exists
            for index futures; screen does not apply.

Verdict rule (ACCEPT): OOS PF improvement > 0.05 AND >= 80% of trades retained.
"""
from __future__ import annotations
import io, os, sys, json, time, calendar, datetime as dt, urllib.request, urllib.error
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
import boto3
import numpy as np
import pandas as pd

import stock_mr_engine as E

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
UNIVERSE = os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')
SI_CACHE = '/tmp/short_interest_cache.json'
PUB_LAG = dt.timedelta(days=14)          # conservative publication lag
OOS_FROM = pd.Timestamp('2022-01-01')
BPS = 0.0003                              # 3bp/side = 6bp round-trip
PRICE_LO, PRICE_HI = 2.0, 50.0
MIN_DOLLAR_VOL = 5e6


# ----------------------------------------------------------------------------
# 1) universe + bars
# ----------------------------------------------------------------------------
def load_universe():
    return list(dict.fromkeys(json.load(open(UNIVERSE))['symbols']))


def load_bars(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 60:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        return df[df['close'] > 0]
    except Exception:
        return None


# ----------------------------------------------------------------------------
# 2) short-interest snapshots (point-in-time, lagged)
# ----------------------------------------------------------------------------
def _biz(d):
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def settlement_dates(start, end):
    ds = []
    y, m = start.year, start.month
    cur = dt.date(y, m, 1)
    last = dt.date(end.year, end.month, 1)
    while cur <= last:
        ds.append(_biz(dt.date(cur.year, cur.month, 15)))
        ds.append(_biz(dt.date(cur.year, cur.month, calendar.monthrange(cur.year, cur.month)[1])))
        cur = dt.date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return sorted({d.strftime('%Y%m%d') for d in ds if start <= d <= end})


def fetch_si_file(date8, uset):
    url = f'https://cdn.finra.org/equity/otcmarket/biweekly/shrt{date8}.csv'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        raw = urllib.request.urlopen(req, timeout=40).read()
    except (urllib.error.HTTPError, urllib.error.URLError):
        return None
    df = pd.read_csv(io.BytesIO(raw), sep='|', dtype=str, usecols=[
        'symbolCode', 'daysToCoverQuantity', 'currentShortPositionQuantity',
        'averageDailyVolumeQuantity', 'settlementDate'])
    sub = df[df['symbolCode'].isin(uset)]
    out = {}
    for _, r in sub.iterrows():
        try:
            dtc = float(r['daysToCoverQuantity'])
        except (ValueError, TypeError):
            continue
        if dtc >= 999.0 or dtc <= 0:
            continue
        out[r['symbolCode']] = dtc
    return out


def load_si(uset):
    if os.path.exists(SI_CACHE):
        d = json.load(open(SI_CACHE))
        return {k: v for k, v in d.items()}
    dates = settlement_dates(dt.date(2021, 6, 1), dt.date(2026, 8, 31))
    snap = {}
    for i, d8 in enumerate(dates):
        r = fetch_si_file(d8, uset)
        if r:
            snap[d8] = r
        if (i + 1) % 25 == 0:
            print(f'  [si] {i+1}/{len(dates)} files', flush=True)
    json.dump(snap, open(SI_CACHE, 'w'))
    return snap


# ----------------------------------------------------------------------------
# 3) screen: at entry date t, drop the trade if its name is top-decile/quintile
# ----------------------------------------------------------------------------
def build_screen(si):
    """Returns (dates_sorted, pct_by_date, si_by_date)."""
    keys = sorted(si.keys())
    pct = {}
    for k in keys:
        vals = np.array(list(si[k].values()))
        if len(vals) < 20:
            pct[k] = {'p90': np.nan, 'p80': np.nan}
            continue
        pct[k] = {'p90': float(np.percentile(vals, 90)),
                  'p80': float(np.percentile(vals, 80))}
    return keys, pct, si


def snapshot_for(keys, date):
    """Latest settlement key <= date - PUB_LAG."""
    target = date - PUB_LAG
    # linear scan from the end (snapshots are bi-weekly; cheap)
    best = None
    for k in keys:
        kd = pd.Timestamp(k)
        if kd <= target:
            best = k
        else:
            break
    return best


def apply_screen(trades, keys, pct, si, top_frac):
    """Return trades surviving the screen (drop top-decile/quintile SIR names)."""
    if top_frac is None:
        return trades
    q = 'p90' if top_frac == 0.10 else 'p80'
    kept, dropped, unranked = [], 0, 0
    for t in trades:
        d = t['entry_date']
        s = snapshot_for(keys, d)
        if s is None or s not in si or t['symbol'] not in si[s]:
            unranked += 1
            kept.append(t)            # fail-open: cannot rank -> keep
            continue
        thr = pct[s][q]
        if np.isnan(thr):
            kept.append(t)
            continue
        if si[s][t['symbol']] >= thr:
            dropped += 1
        else:
            kept.append(t)
    return kept


# ----------------------------------------------------------------------------
# 4) lane trade generators
# ----------------------------------------------------------------------------
def rsi2_trades(data):
    tr = []
    for sym, df in data.items():
        tr.extend(E.run_symbol(df, sym, 5, 'fixed'))
    return tr


def broken_arrow_trades(data):
    tr = []
    for sym, df in data.items():
        d = df.copy()
        pc = d['close'].shift(1)
        d['ma40'] = d['close'].rolling(40).mean()
        d['ma40_rising'] = d['ma40'] > d['ma40'].shift(1)
        d['ret1'] = d['close'] / pc - 1.0
        d['dvol'] = (d['close'] * d['volume']).rolling(20).mean()
        d['c2o'] = d['open'].shift(-1) / d['close'] - 1.0
        setup = (d['close'].shift(1) > d['ma40'].shift(1)) & d['ma40_rising'].shift(1)
        m = (setup & (d['ret1'] <= -0.08) & d['close'].between(PRICE_LO, PRICE_HI)
             & d['c2o'].notna() & (d['dvol'] > MIN_DOLLAR_VOL))
        for i in np.where(m.to_numpy())[0]:
            tr.append({
                'symbol': sym,
                'entry_date': d.index[i],
                'entry_price': float(d['close'].iloc[i]),
                'exit_price': float(d['open'].iloc[i + 1]),
                'reason': 'next_open',
                'hold_days': 1,
                'ret': float(d['c2o'].iloc[i]),
            })
    return tr


# ----------------------------------------------------------------------------
# 5) stats
# ----------------------------------------------------------------------------
def ret_of(t, bps):
    return (t['exit_price'] * (1 - bps)) / (t['entry_price'] * (1 + bps)) - 1.0


def stats(trades, bps=BPS):
    if not trades:
        return {'n': 0, 'PF': float('nan'), 'win%': float('nan'),
                'avg_bp': float('nan'), 't': float('nan')}
    r = np.array([ret_of(t, bps) for t in trades])
    w = r[r > 0].sum()
    l = -r[r < 0].sum()
    pf = w / l if l > 0 else float('inf')
    tstat = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 else 0.0
    return {'n': int(len(r)), 'PF': round(float(pf), 3),
            'win%': round(100 * float((r > 0).mean()), 1),
            'avg_bp': round(float(r.mean() * 1e4), 1),
            't': round(float(tstat), 2)}


def oos(trades, since=OOS_FROM):
    return [t for t in trades if t['entry_date'] >= since]


# ----------------------------------------------------------------------------
# 6) main
# ----------------------------------------------------------------------------
def main():
    t0 = time.time()
    syms = load_universe()
    print(f'universe: {len(syms)} names', flush=True)
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))

    print('loading bars…', flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load_bars(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)} symbols  '
          f'span {min(d.index[0] for d in data.values()).date()} .. '
          f'{max(d.index[-1] for d in data.values()).date()}', flush=True)

    print('loading short interest (FINRA bi-weekly, 2021-06+ consolidated)…', flush=True)
    si = load_si(set(data.keys()))
    keys, pct, si = build_screen(si)
    print(f'  {len(keys)} SI snapshots: {keys[0]} .. {keys[-1]}', flush=True)

    print('running lanes…', flush=True)
    lanes = {
        'RSI2': rsi2_trades(data),
        'BROKEN_ARROW': broken_arrow_trades(data),
    }

    res = {'universe_n': len(data), 'si_snapshots': len(keys),
           'pub_lag_days': PUB_LAG.days, 'bps_side': BPS, 'cost_bp_rt': BPS * 2 * 1e4,
           'oos_from': str(OOS_FROM.date()),
           'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}

    print('\n' + '=' * 86)
    print('SHORT-INTEREST AVOIDANCE SCREEN — OOS (entry >= 2022-01-01) at 6bp round-trip')
    print('=' * 86)
    for lane, trades in lanes.items():
        base_all = stats(trades)
        base_oos = stats(oos(trades))
        res[lane] = {'base_full': base_all, 'base_oos': base_oos, 'screens': {}}
        print(f'\n## {lane}')
        print(f'  baseline full  : n={base_all["n"]:>6}  PF={base_all["PF"]:>6.3f}  '
              f'win={base_all["win%"]:>5.1f}%  avg={base_all["avg_bp"]:>7.1f}bp')
        print(f'  baseline OOS   : n={base_oos["n"]:>6}  PF={base_oos["PF"]:>6.3f}  '
              f'win={base_oos["win%"]:>5.1f}%  avg={base_oos["avg_bp"]:>7.1f}bp  t={base_oos["t"]}')

        for label, frac in [('exclude top 10%', 0.10), ('exclude top 20%', 0.20)]:
            kept = apply_screen(trades, keys, pct, si, frac)
            so = stats(oos(kept))
            retained = so['n'] / base_oos['n'] if base_oos['n'] else float('nan')
            d_pf = (so['PF'] - base_oos['PF']) if so['n'] else float('nan')
            res[lane]['screens'][label] = {'oos': so,
                                           'retained_frac': round(float(retained), 3),
                                           'oos_pf_delta': round(float(d_pf), 3)}
            print(f'  {label:>16}: n={so["n"]:>6}  PF={so["PF"]:>6.3f}  '
                  f'win={so["win%"]:>5.1f}%  avg={so["avg_bp"]:>7.1f}bp  t={so["t"]}  '
                  f'retained={retained*100:>5.1f}%  dPF={d_pf:+.3f}')

    # also report SI-covered full window (entry >= 2021-07-01) for power
    print('\n' + '=' * 86)
    print('SECONDARY — SI-covered window (entry >= 2021-07-01, first post-consolidation)')
    print('=' * 86)
    for lane, trades in lanes.items():
        b = stats([t for t in trades if t['entry_date'] >= pd.Timestamp('2021-07-01')])
        print(f'\n## {lane}')
        print(f'  baseline       : n={b["n"]:>6}  PF={b["PF"]:>6.3f}  win={b["win%"]:>5.1f}%  '
              f'avg={b["avg_bp"]:>7.1f}bp')
        for label, frac in [('exclude top 10%', 0.10), ('exclude top 20%', 0.20)]:
            kept = apply_screen(trades, keys, pct, si, frac)
            sk = [t for t in kept if t['entry_date'] >= pd.Timestamp('2021-07-01')]
            s = stats(sk)
            retained = s['n'] / b['n'] if b['n'] else float('nan')
            d_pf = (s['PF'] - b['PF']) if s['n'] else float('nan')
            print(f'  {label:>16}: n={s["n"]:>6}  PF={s["PF"]:>6.3f}  win={s["win%"]:>5.1f}%  '
                  f'avg={s["avg_bp"]:>7.1f}bp  retained={retained*100:>5.1f}%  dPF={d_pf:+.3f}')

    out = os.path.join(_ROOT, 'research', 'short_interest_screen_results.json')
    json.dump(res, open(out, 'w'), indent=1, default=str)
    print(f'\nwrote {out} in {time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()
