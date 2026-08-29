#!/usr/bin/env python3
"""Crypto weekend->Monday "Monday Asia Open Effect" — honest backtest.

Queue item strat-20260827-crypto-weekend. Claims under test (Concretum Group
2026-01-30 HF-trend benchmark + crypto day-of-week literature):

  (a) BTC has a CONCENTRATED positive window Sunday ~19:00 ET (Asia Monday open)
      through Monday, EXIT Monday (1-day hold) — the "Monday Asia Open Effect".
  (b) The simpler passive "Monday effect": positive Monday, negative weekend.

Tradeable-lane framing (daily): LONG at Monday 00:00 UTC open (~= Sunday 19:00 ET,
crypto trades 24/7 so there is no overnight gap), EXIT at Monday close (1-day hold),
2x ATR14 gap-aware protective stop on every position. Cost: 10 bps/side fee
(Binance.US spot taker, verified 2026-08-15) + 0/10/20 bps/side slippage stress.

Honest-fill rules copied from research/crypto_sweep.py (the repo's validated
crypto pattern): entry = bar close/open + adverse slippage + fee; stop gap-aware
(open-through => fill at open); exit + fee + slippage; walk-forward 40/20/40 by
entry date; verdict bar = full PF>1.5 AND OOS PF>1.3 AND PF@20bps>=1.0 AND OOS n>=30.

Data: yf/crypto/{BTC,ETH}-USD.json (daily 2014/2017->2026-08-28 + ~2y hourly) and
crypto-hist/SOLUSDT/daily.json (Binance.US 2019-09 -> 2026-08-15; SOL has no yf
history and no hourly). Daily candles are UTC midnight-to-midnight; the Monday UTC
candle is the cleanest proxy for "Sunday 19:00 ET -> Monday close" (19:00 ET =
23:00 UTC EDT / 00:00 UTC EST, i.e. within 1h of the Monday 00:00 UTC open).

Crypto is PAPER/RESEARCH ONLY — owner distrusts crypto; no orders, ever.
"""
import os
import json
import datetime as dt

import numpy as np
import boto3
from dotenv import load_dotenv

REPO = os.environ.get('TRADING_REPO', os.path.expanduser('~/trading-system'))
load_dotenv(os.path.join(REPO, '.env'))
load_dotenv()

S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

FEE_BPS = 10.0              # 0.1% per side (Binance.US standard spot taker)
SLIP_LEVELS = [0.0, 10.0, 20.0]   # bps per side, cost-stress axis
ATR_N = 14
STOP_ATR = 2.0

# Which daily series to use for the full-history day-of-week + lane test.
# (symbol, source, s3_key) — source 'yf' or 'binanceus'.
DAILY_SOURCES = [
    ('BTC', 'yf', 'yf/crypto/BTC-USD.json'),
    ('ETH', 'yf', 'yf/crypto/ETH-USD.json'),
    ('SOL', 'binanceus', 'crypto-hist/SOLUSDT/daily.json'),
]
HOURLY_SOURCES = [
    ('BTC', 'yf/crypto/BTC-USD.json'),
    ('ETH', 'yf/crypto/ETH-USD.json'),
]

WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def _s3():
    return boto3.client('s3', region_name=AWS_REGION)


def load_daily(key, source):
    obj = _s3().get_object(Bucket=S3_BUCKET, Key=key)
    d = json.loads(obj['Body'].read())
    if source == 'yf':
        bars = d['daily']
    else:
        bars = d['bars']
    out = []
    for b in bars:
        # yf: {'ts','open','high','low','close'}; binanceus: {'date','open','high','low','close'}
        date = b.get('ts', b.get('date'))[:10]
        out.append({'date': date, 'open': float(b['open']), 'high': float(b['high']),
                    'low': float(b['low']), 'close': float(b['close'])})
    out.sort(key=lambda x: x['date'])
    return out


def load_hourly(key):
    obj = _s3().get_object(Bucket=S3_BUCKET, Key=key)
    d = json.loads(obj['Body'].read())
    out = []
    for b in d['hourly']:
        t = dt.datetime.fromisoformat(b['ts'])  # naive UTC
        out.append({'ts': t, 'open': float(b['open']), 'high': float(b['high']),
                    'low': float(b['low']), 'close': float(b['close'])})
    out.sort(key=lambda x: x['ts'])
    return out


def wilder_atr(h, l, c, n=ATR_N):
    tr = np.maximum.reduce([h - l, np.abs(h - np.roll(c, 1)),
                            np.abs(l - np.roll(c, 1))])
    tr[0] = h[0] - l[0]
    atr = np.zeros_like(c)
    atr[0] = tr[0]
    a = 1.0 / n
    for i in range(1, len(c)):
        atr[i] = (tr[i] + (n - 1) * atr[i - 1]) / n
    return atr


def dow(date_str):
    """0=Monday .. 6=Sunday."""
    return dt.date.fromisoformat(date_str).weekday()


def stats(rets):
    rets = np.asarray(rets, float)
    if len(rets) == 0:
        return {'n': 0, 'pf': float('nan'), 'win': float('nan'),
                'avg_bp': float('nan'), 'median_bp': float('nan'), 't': float('nan')}
    gains = rets[rets > 0].sum()
    losses = abs(rets[rets < 0].sum())
    pf = gains / losses if losses > 0 else float('inf')
    avg = float(rets.mean())
    t = avg / (rets.std(ddof=1) / np.sqrt(len(rets))) if len(rets) > 1 and rets.std(ddof=1) > 0 else float('nan')
    return {'n': len(rets), 'pf': pf, 'win': float((rets > 0).mean()),
            'avg_bp': avg * 10000.0, 'median_bp': float(np.median(rets)) * 10000.0, 't': t}


def walk_forward_split(dates):
    """Return (train_cut, oos_cut) dates for 40/20/40 by entry date."""
    uniq = sorted(set(dates))
    n = len(uniq)
    return uniq[int(n * 0.4)], uniq[int(n * 0.6)]


def backtest_monday_lane(bars, slip_bps, fee_bps=FEE_BPS, use_stop=True):
    """LONG Monday 00:00 UTC open -> EXIT Monday close. 1-day hold. 2x ATR14 stop.

    bars: list of daily dicts sorted by date. Entry only on Mondays.
    Returns list of {'entry_date','ret','exit'} trades.
    """
    c = np.array([b['close'] for b in bars], float)
    h = np.array([b['high'] for b in bars], float)
    l = np.array([b['low'] for b in bars], float)
    o = np.array([b['open'] for b in bars], float)
    dates = [b['date'] for b in bars]
    atr = wilder_atr(h, l, c)
    slip = slip_bps / 10000.0
    fee = fee_bps / 10000.0
    trades = []
    for i in range(1, len(bars)):
        if dow(dates[i]) != 0:            # only Mondays
            continue
        entry = o[i] * (1 + slip) * (1 + fee)
        stop = entry - STOP_ATR * atr[i - 1]  # ATR through Sunday close
        exit_px = None
        why = 'close'
        if use_stop:
            if o[i] <= stop:
                exit_px = o[i] * (1 - slip)
                why = 'stop_gap'
            elif l[i] <= stop:
                exit_px = stop * (1 - slip)
                why = 'stop'
        if exit_px is None:
            exit_px = c[i] * (1 - slip)
        exit_px *= (1 - fee)
        ret = (exit_px - entry) / entry
        trades.append({'entry_date': dates[i], 'ret': ret, 'exit': why})
    return trades


def dayofweek_table(bars):
    """Per-weekday candle-body return (open->close) and close-to-close return."""
    c = np.array([b['close'] for b in bars], float)
    o = np.array([b['open'] for b in bars], float)
    dates = [b['date'] for b in bars]
    body = c / o - 1.0
    c2c = np.diff(c) / c[:-1]
    rows = {}
    for wd in range(7):
        idx = [i for i in range(len(bars)) if dow(dates[i]) == wd]
        body_rets = body[idx]
        c2c_rets = c2c[np.array(idx) - 1] if len(idx) else np.array([])
        # drop first element if index -1 < 0
        c2c_ok = c2c[[i - 1 for i in idx if i >= 1]]
        rows[WEEKDAYS[wd]] = {
            'body': stats(body_rets), 'close2close': stats(c2c_ok)}
    return rows


def weekend_table(bars):
    """Weekend = Fri close -> Sun close (Sat+Sun) and Fri close -> Mon open."""
    dates = [b['date'] for b in bars]
    dmap = {dates[i]: i for i in range(len(bars))}
    c = np.array([b['close'] for b in bars], float)
    o = np.array([b['open'] for b in bars], float)
    fri_sun = []   # Fri close -> Sun close
    fri_mono = []  # Fri close -> Mon open
    for i in range(len(bars)):
        if dow(dates[i]) != 4:   # Friday
            continue
        # find the following Sunday and Monday by date
        fd = dt.date.fromisoformat(dates[i])
        sun = (fd + dt.timedelta(days=2)).isoformat()
        mon = (fd + dt.timedelta(days=3)).isoformat()
        if sun in dmap:
            fri_sun.append(c[dmap[sun]] / c[i] - 1.0)
        if mon in dmap:
            fri_mono.append(o[dmap[mon]] / c[i] - 1.0)
    return {'fri_close_to_sun_close': stats(fri_sun),
            'fri_close_to_mon_open': stats(fri_mono)}


# ---------------- hourly: Sunday 19:00 ET -> Monday windows ----------------
def hourly_window_returns(hbars, window_hours=24, skip_n_bars=None):
    """Measure 24h window returns for several start-anchors, in bp.

    We anchor windows to a time-of-week in UTC. Because ET is UTC-4 (EDT) /
    UTC-5 (EST), "Sunday 19:00 ET" maps to Sunday 23:00 UTC (EDT) or Monday
    00:00 UTC (EST). We measure BOTH anchors and report.
    """
    # build map ts -> index
    ts = [h['ts'] for h in hbars]
    t0 = ts[0]
    # index of each hourly bar
    idx = {}
    for i, h in enumerate(hbars):
        idx[h['ts']] = i

    results = {}
    # Windows: start Sunday 23:00 UTC (EDT proxy) and Monday 00:00 UTC (EST proxy)
    # and comparison windows (Tue 00:00, Sat 00:00, etc.)
    anchors = {
        'sun_19ET_EDT(=Sun23UTC)->24h': (23, 0),   # Sunday 23:00 UTC
        'sun_19ET_EST(=Mon00UTC)->24h': (0, 0),    # Monday 00:00 UTC
        'mon_00UTC->24h (same as EST proxy)': (0, 0),
        'tue_00UTC->24h': (0, 1),
        'sat_00UTC->24h': (0, 5),
    }
    # find all (weekday, hour) starts
    # group hourly bars by (weekday, hour)
    from collections import defaultdict
    starts = defaultdict(list)
    for i, h in enumerate(hbars):
        t = h['ts']
        starts[(t.weekday(), t.hour)].append(i)

    for name, (hr, wd) in anchors.items():
        rets = []
        for s in starts.get((wd, hr), []):
            e = s + window_hours
            if e >= len(hbars):
                continue
            if hbars[e]['ts'] - hbars[s]['ts'] != dt.timedelta(hours=window_hours):
                continue
            rets.append(hbars[e]['close'] / hbars[s]['open'] - 1.0)
        results[name] = stats(rets)
    return results


def split_stats(trades, split='wf'):
    """IS/OOS split by entry date. Returns dict with full + oos (and is)."""
    if not trades:
        return {'full': stats([]), 'is': stats([]), 'oos': stats([])}
    dates = [t['entry_date'] for t in trades]
    full = stats([t['ret'] for t in trades])
    if split == 'wf':
        train_cut, oos_cut = walk_forward_split(dates)
        is_tr = [t for t in trades if t['entry_date'] < oos_cut]
        oos_tr = [t for t in trades if t['entry_date'] >= oos_cut]
    else:  # post-2020 split
        is_tr = [t for t in trades if t['entry_date'] < '2020-01-01']
        oos_tr = [t for t in trades if t['entry_date'] >= '2020-01-01']
    return {'full': full, 'is': stats([t['ret'] for t in is_tr]),
            'oos': stats([t['ret'] for t in oos_tr])}


def main():
    out = {'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
           'fee_bps_per_side': FEE_BPS, 'slip_bps_per_side_levels': SLIP_LEVELS,
           'stop': f'{STOP_ATR}x ATR{ATR_N} hard stop on every position',
           'symbols': {}, 'hourly': {}}
    print('=== CRYPTO WEEKEND->MONDAY ("Monday Asia Open Effect") ===')
    print(f'fee={FEE_BPS}bps/side, slip stress={SLIP_LEVELS}bps/side, '
          f'stop={STOP_ATR}xATR{ATR_N}\n')

    for sym, source, key in DAILY_SOURCES:
        bars = load_daily(key, source)
        print(f'--- {sym}: {len(bars)} daily bars ({bars[0]["date"]} .. {bars[-1]["date"]}) ---')

        # 1. day-of-week candle-body (the Monday "effect")
        dow_tab = dayofweek_table(bars)
        print('  day-of-week candle-body return (open->close), bp:')
        for wd in WEEKDAYS:
            r = dow_tab[wd]['body']
            print(f'    {wd:3s} n={r["n"]:4d} avg={r["avg_bp"]:+6.1f}bp '
                  f'median={r["median_bp"]:+6.1f}bp win={r["win"]:.0%} t={r["t"]:.2f}')

        # 2. weekend
        wk = weekend_table(bars)
        for k, v in wk.items():
            print(f'    {k}: n={v["n"]} avg={v["avg_bp"]:+6.1f}bp '
                  f'median={v["median_bp"]:+6.1f}bp win={v["win"]:.0%} t={v["t"]:.2f}')

        # 3. tradeable lane: Monday open -> Monday close, honest costs
        lane = {}
        for use_stop in (True, False):
            tag = 'with_stop' if use_stop else 'close_only'
            lane[tag] = {}
            for sl in SLIP_LEVELS:
                tr = backtest_monday_lane(bars, sl, use_stop=use_stop)
                ss = split_stats(tr, 'wf')
                lane[tag][f'slip{int(sl)}bps'] = {
                    'full': ss['full'], 'is': ss['is'], 'oos': ss['oos'],
                    'n': ss['full']['n']}
        # post-2020 split at 0 slip for the "post-2020 stronger" claim
        tr0 = backtest_monday_lane(bars, 0.0, use_stop=True)
        lane['post2020'] = split_stats(tr0, 'post2020')

        out['symbols'][sym] = {'source': source, 'dayofweek': dow_tab,
                               'weekend': wk, 'lane': lane}

        # print lane summary @0bps and @20bps
        for tag in ('with_stop', 'close_only'):
            f0 = lane[tag]['slip0bps']
            f20 = lane[tag]['slip20bps']
            print(f'  lane[{tag}] @fee10/slip0 : n={f0["n"]} PF={f0["full"]["pf"]:.2f} '
                  f'IS={f0["is"]["pf"]:.2f} OOS={f0["oos"]["pf"]:.2f}(n={f0["oos"]["n"]}) '
                  f'avg={f0["full"]["avg_bp"]:+.1f}bp')
            print(f'  lane[{tag}] @fee10/slip20: PF={f20["full"]["pf"]:.2f} '
                  f'IS={f20["is"]["pf"]:.2f} OOS={f20["oos"]["pf"]:.2f} '
                  f'avg={f20["full"]["avg_bp"]:+.1f}bp')
        pp = lane['post2020']
        print(f'  lane[with_stop] post-2020 split: IS PF={pp["is"]["pf"]:.2f} '
              f'(n={pp["is"]["n"]}) OOS(>=2020) PF={pp["oos"]["pf"]:.2f} '
              f'(n={pp["oos"]["n"]}) avg={pp["oos"]["avg_bp"]:+.1f}bp')
        print()

    # 4. hourly window analysis (BTC/ETH, ~2y)
    print('=== hourly: Sunday 19:00 ET -> Monday window (2y, UTC hourly) ===')
    for sym, key in HOURLY_SOURCES:
        hb = load_hourly(key)
        hr = hourly_window_returns(hb)
        out['hourly'][sym] = hr
        print(f'  {sym}: {len(hb)} hourly bars ({hb[0]["ts"]} .. {hb[-1]["ts"]})')
        for name, v in hr.items():
            print(f'    {name:38s} n={v["n"]:4d} avg={v["avg_bp"]:+6.1f}bp '
                  f'median={v["median_bp"]:+6.1f}bp win={v["win"]:.0%} t={v["t"]:.2f}')

    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'crypto_weekend_results.json')
    with open(outpath, 'w') as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f'\nWrote {outpath}')


if __name__ == '__main__':
    main()
