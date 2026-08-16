#!/usr/bin/env python3
"""INTRADAY candidate validation — Gate-1 for the intraday-first build.

Backtests the 5 intraday candidates (ORB / MOM / VWAP / DONCH15 / FADESHORT)
on IBKR intraday bars archived to S3 `futures-bars/intraday/` (RTH only),
with HONEST fills + a BRUTAL cost model (0/1/2/3 ticks per-side slippage +
flat per-contract commission on every round trip).

Primary dataset: 5-min bars (~1y, 117-251 sessions) for the LIQUID universe
(MES MNQ ES NQ RTY YM GC CL NG). DONCH15 runs on real 15-min bars (matches
live_intraday.py). A THIN 1-min smoke test (30 sessions) runs on MES/MNQ only
and is flagged as not statistically meaningful.

Method (from the trading-backtest-validation skill):
  - Entry at signal-bar CLOSE + adverse slippage.
  - Protective stop is GTC intraday: gap-through -> open, else stop; + slip.
  - Signal/EOD exits at close + slip. One entry/exit per bar, one position.
  - EOD flatten (no overnight risk). No pyramiding.
  - Walk-forward 60/40 by session date. OOS = last 40% of sessions.
  - Metrics: n, win%, PF, net, maxDD (daily curve), Sharpe (daily buckets).

P&L is computed in TICKS (scale-invariant across contract sizes) so pooled
PF/Sharpe/maxDD are comparable; per-symbol $ uses mult*tick.

READ-ONLY: S3 get_object only. No IBKR, no DynamoDB, no orders.
"""
import argparse
import json
import os
import sys
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import boto3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')

# ---- contract specs: (mult, tick_size, $/tick, commission_per_side) ----
# mult = $/point, tick = min price increment in the same price units as the
# archived bars, commission = conservative IBKR retail per-side USD.
SPECS = {
    'MES': dict(mult=5.0,   tick=0.25,  comm=0.62),
    'MNQ': dict(mult=2.0,   tick=0.25,  comm=0.62),
    'ES':  dict(mult=50.0,  tick=0.25,  comm=1.60),
    'NQ':  dict(mult=20.0,  tick=0.25,  comm=1.60),
    'RTY': dict(mult=50.0,  tick=0.10,  comm=1.60),
    'YM':  dict(mult=5.0,   tick=1.00,  comm=1.60),
    'GC':  dict(mult=100.0, tick=0.10,  comm=2.25),
    'CL':  dict(mult=1000.0, tick=0.01, comm=2.25),
    'NG':  dict(mult=10000.0, tick=0.001, comm=2.25),
}
LIQUID = ['MES', 'MNQ', 'ES', 'NQ', 'RTY', 'YM', 'GC', 'CL', 'NG']

# ---- strategy params (match intraday_scan.py + live_intraday.py) ----
ORB_MIN_BARS = 6        # 30-min opening range on 5m bars (30 bars on 1m)
MOM_N = 10              # ROC lookback (bars)
MOM_HOLD = 6            # hold bars before exit
MOM_THRESH = 0.0015     # |ROC| entry threshold
VWAP_K = 2.0
VWAP_SD_N = 10
DC_N = 20
DC_ATR_N = 14
DC_STOP_ATR = 2.0
FADE_RSI2_OB = 90.0
FADE_BOLL_N = 20
FADE_BOLL_K = 2.0
FADE_STOP_ATR = 2.0
ATR_N = 14
KAMA_N = 10              # efficiency-ratio lookback (bars)
KAMA_FAST = 2            # fast EMA period (fast smoothing constant)
KAMA_SLOW = 30           # slow EMA period (slow smoothing constant)
KAMA_STOP_ATR = 2.0      # 2xATR hard stop

CACHE_DIR = '/tmp/intraday_validate_cache'


# ==================== data loading ====================
def _load_one(args):
    sym, tf, key = args
    s3 = boto3.client('s3', region_name=AWS_REGION)
    o = s3.get_object(Bucket=S3_BUCKET, Key=key)
    d = json.loads(o['Body'].read())
    rows = []
    for b in d.get('bars', []):
        ts = b.get('ts') or b.get('date')
        rows.append((ts, b['open'], b['high'], b['low'], b['close'], b.get('volume')))
    return rows


def load_intraday(sym, tf):
    """Load all archived bars for (sym, tf) -> continuous RTH DataFrame.

    Index = tz-aware NY timestamps, sorted. Column 'day' = session date.
    Cached to /tmp pickle so re-runs skip S3.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f'{sym}_{tf}.pkl')
    if os.path.exists(cache):
        return pd.read_pickle(cache)

    s3 = boto3.client('s3', region_name=AWS_REGION)
    prefix = f'futures-bars/intraday/{sym}/{tf}/'
    keys = []
    pag = s3.get_paginator('list_objects_v2')
    for p in pag.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for o in p.get('Contents', []):
            keys.append(o['Key'])
    if not keys:
        return pd.DataFrame()

    all_rows = []
    with ThreadPoolExecutor(max_workers=32) as ex:
        for rows in ex.map(_load_one, [(sym, tf, k) for k in keys]):
            all_rows.extend(rows)

    df = pd.DataFrame(all_rows, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], utc=True).dt.tz_convert('America/New_York')
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    df = df.sort_values('ts').drop_duplicates('ts').set_index('ts')
    df['day'] = df.index.date
    df = df[['open', 'high', 'low', 'close', 'volume', 'day']]
    df.to_pickle(cache)
    return df


# ==================== indicators ====================
def wilder_atr(h, l, c, n=ATR_N):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=2):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def bollinger(close, n, k):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid, mid + k * sd, mid - k * sd


def session_cumsum(s):
    """Cumulative sum reset at each day boundary (for VWAP)."""
    out = s.copy()
    cur = 0.0
    prev_day = None
    for i in range(len(s)):
        d = s.index[i].date()
        if d != prev_day:
            cur = 0.0
            prev_day = d
        v = s.iloc[i]
        cur += (0.0 if pd.isna(v) else v)
        out.iloc[i] = cur
    return out


# ==================== trade engine ====================
def run_engine(o, h, l, c, days, enter_fn, exit_fn, stop_fn):
    """Bar-by-bar event loop over a continuous RTH series.

    days = list of session dates aligned to bars. One position at a time,
    first signal wins. EOD flatten at the last bar of each session.
    Returns list of trades: {side, entry_i, exit_i, entry_px, exit_px, reason,
    entry_day}.
    """
    n = len(o)
    trades = []
    pos = 0
    entry_px = entry_i = stop_px = None
    for i in range(n):
        bar_o, bar_h, bar_l, bar_c = o[i], h[i], l[i], c[i]
        is_last = (i == n - 1) or (days[i] != days[i + 1])
        if pos == 0:
            side = enter_fn(i)
            if side:
                pos = side
                entry_px = bar_c
                entry_i = i
                stop_px = stop_fn(i, bar_c, side) if stop_fn else None
                continue
        else:
            exit_px = reason = None
            if stop_px is not None:
                if pos == 1 and bar_l <= stop_px:
                    # gap through -> open, else stop
                    exit_px = bar_o if bar_o < stop_px else stop_px
                    reason = 'stop'
                elif pos == -1 and bar_h >= stop_px:
                    exit_px = bar_o if bar_o > stop_px else stop_px
                    reason = 'stop'
            if exit_px is None and exit_fn(i, pos, entry_px, entry_i, stop_px):
                exit_px = bar_c
                reason = 'signal'
            if exit_px is None and is_last:
                exit_px = bar_c
                reason = 'EOD'
            if exit_px is not None:
                trades.append(dict(side=pos, entry_i=entry_i, exit_i=i,
                                   entry_px=float(entry_px), exit_px=float(exit_px),
                                   reason=reason, entry_day=days[entry_i]))
                pos = 0
                entry_px = entry_i = stop_px = None
    return trades


# ==================== strategy definitions ====================
def make_orb(df):
    o = df['open'].to_numpy(); h = df['high'].to_numpy()
    l = df['low'].to_numpy(); c = df['close'].to_numpy()
    days = list(df['day'])
    # per-day opening range (first ORB_MIN_BARS bars)
    day_start = {}
    day_id = []
    cur = -1
    prev = None
    for d in days:
        if d != prev:
            cur += 1
            day_start[cur] = None
            prev = d
        day_id.append(cur)
    # precompute range hi/lo for each bar's day (first 6 bars)
    n = len(o)
    rng_hi = np.full(n, np.nan)
    rng_lo = np.full(n, np.nan)
    for i in range(n):
        did = day_id[i]
        # first ORB_MIN_BARS bars of this day
        if did not in day_start or day_start[did] is None:
            day_start[did] = i
        s = day_start[did]
        if i - s >= ORB_MIN_BARS - 1:
            rng_hi[i] = h[s:s + ORB_MIN_BARS].max()
            rng_lo[i] = l[s:s + ORB_MIN_BARS].min()

    def enter_fn(i):
        if np.isnan(rng_hi[i]):
            return 0
        if c[i] > rng_hi[i]:
            return 1
        if c[i] < rng_lo[i]:
            return -1
        return 0

    def exit_fn(i, pos, entry_px, entry_i, stop):
        return False  # EOD only

    def stop_fn(i, entry_px, side):
        # opposite boundary of the opening range
        if np.isnan(rng_lo[i]) or np.isnan(rng_hi[i]):
            return None
        return rng_lo[i] if side == 1 else rng_hi[i]

    return run_engine(o, h, l, c, days, enter_fn, exit_fn, stop_fn)


def make_mom(df):
    o = df['open'].to_numpy(); h = df['high'].to_numpy()
    l = df['low'].to_numpy(); c = df['close'].to_numpy()
    days = list(df['day'])
    atr = wilder_atr(df['high'], df['low'], df['close'], ATR_N).to_numpy()

    def enter_fn(i):
        if i < MOM_N or days[i - MOM_N] != days[i]:
            return 0
        roc = c[i] / c[i - MOM_N] - 1
        if roc > MOM_THRESH:
            return 1
        if roc < -MOM_THRESH:
            return -1
        return 0

    def exit_fn(i, pos, entry_px, entry_i, stop):
        return (i - entry_i) >= MOM_HOLD

    def stop_fn(i, entry_px, side):
        a = atr[i]
        return None if (a != a) else (entry_px - 2.0 * a if side == 1 else entry_px + 2.0 * a)

    return run_engine(o, h, l, c, days, enter_fn, exit_fn, stop_fn)


def make_vwap(df):
    o = df['open'].to_numpy(); h = df['high'].to_numpy()
    l = df['low'].to_numpy(); c = df['close'].to_numpy()
    days = list(df['day'])
    atr = wilder_atr(df['high'], df['low'], df['close'], ATR_N).to_numpy()
    tp = (df['high'] + df['low'] + df['close']) / 3
    vol = df['volume'].clip(lower=0.0)
    # per-day cumulative VWAP
    vwap = session_cumsum(tp * vol) / session_cumsum(vol).replace(0, np.nan)
    dev = df['close'] - vwap
    # per-day rolling std of deviation
    sd = dev.groupby(df['day']).rolling(VWAP_SD_N, min_periods=VWAP_SD_N).std().reset_index(level=0, drop=True)
    vwap_a = vwap.to_numpy()
    sd_a = sd.to_numpy()

    def enter_fn(i):
        s = sd_a[i]
        if s != s or s == 0:
            return 0
        z = (c[i] - vwap_a[i]) / s
        if z < -VWAP_K:
            return 1
        if z > VWAP_K:
            return -1
        return 0

    def exit_fn(i, pos, entry_px, entry_i, stop):
        v = vwap_a[i]
        return (pos == 1 and c[i] >= v) or (pos == -1 and c[i] <= v)

    def stop_fn(i, entry_px, side):
        a = atr[i]
        return None if (a != a) else (entry_px - 2.0 * a if side == 1 else entry_px + 2.0 * a)

    return run_engine(o, h, l, c, days, enter_fn, exit_fn, stop_fn)


def make_donch15(df):
    o = df['open'].to_numpy(); h = df['high'].to_numpy()
    l = df['low'].to_numpy(); c = df['close'].to_numpy()
    days = list(df['day'])
    hi = df['high'].rolling(DC_N).max().shift(1).to_numpy()
    lo = df['low'].rolling(DC_N).min().shift(1).to_numpy()
    atr = wilder_atr(df['high'], df['low'], df['close'], DC_ATR_N).to_numpy()

    def enter_fn(i):
        if i < DC_N or hi[i] != hi[i]:
            return 0
        if c[i] > hi[i]:
            return 1
        if c[i] < lo[i]:
            return -1
        return 0

    def exit_fn(i, pos, entry_px, entry_i, stop):
        if i < DC_N or hi[i] != hi[i]:
            return False
        mid = (hi[i] + lo[i]) / 2
        return (pos == 1 and c[i] < mid) or (pos == -1 and c[i] > mid)

    def stop_fn(i, entry_px, side):
        a = atr[i]
        return None if (a != a) else (entry_px - DC_STOP_ATR * a if side == 1 else entry_px + DC_STOP_ATR * a)

    return run_engine(o, h, l, c, days, enter_fn, exit_fn, stop_fn)


def make_fadeshort(df):
    o = df['open'].to_numpy(); h = df['high'].to_numpy()
    l = df['low'].to_numpy(); c = df['close'].to_numpy()
    days = list(df['day'])
    close = df['close']
    mid, upper, _ = bollinger(close, FADE_BOLL_N, FADE_BOLL_K)
    rsi2 = rsi(close, 2)
    atr = wilder_atr(df['high'], df['low'], close, ATR_N)
    mid_a = mid.to_numpy(); upper_a = upper.to_numpy()
    rsi_a = rsi2.to_numpy(); atr_a = atr.to_numpy()

    def enter_fn(i):
        if mid_a[i] != mid_a[i]:
            return 0
        if rsi_a[i] > FADE_RSI2_OB and c[i] > upper_a[i]:
            return -1  # SHORT only (fade rally)
        return 0

    def exit_fn(i, pos, entry_px, entry_i, stop):
        return c[i] <= mid_a[i]  # reversion done

    def stop_fn(i, entry_px, side):
        a = atr_a[i]
        return None if (a != a) else entry_px + FADE_STOP_ATR * a  # above entry (short)

    return run_engine(o, h, l, c, days, enter_fn, exit_fn, stop_fn)


def kama(c, n=KAMA_N, fast=KAMA_FAST, slow=KAMA_SLOW):
    """Kaufman Adaptive Moving Average (efficiency-ratio adaptive trend line).

    ER = |change over n| / sum(|bar-to-bar change| over n); SC = (ER*(f-s)+s)^2;
    KAMA[i] = KAMA[i-1] + SC*(price[i]-KAMA[i-1]). Fast in trends, flat in chop —
    attacks whipsaw drawdown. Returns np array aligned to `c` (NaN warmup).
    """
    c = pd.Series(np.asarray(c, dtype=float))
    m = len(c)
    out = np.full(m, np.nan)
    if m < n + 2:
        return out
    change = c.diff(n).abs().to_numpy()                       # |c[i]-c[i-n]|
    vol = c.diff().abs().rolling(n).sum().to_numpy()          # sum of n abs returns
    fast_sc = 2.0 / (fast + 1.0)
    slow_sc = 2.0 / (slow + 1.0)
    out[n - 1] = c.iloc[:n].mean()                            # seed
    for i in range(n, m):
        er = change[i] / vol[i] if vol[i] > 0 else 0.0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        out[i] = out[i - 1] + sc * (c.iloc[i] - out[i - 1])
    return out


def make_kama(df):
    """KAMA trend-follow: long on close crossing above KAMA, short below;
    exit on close crossing back; 2xATR hard stop."""
    o = df['open'].to_numpy(); h = df['high'].to_numpy()
    l = df['low'].to_numpy(); c = df['close'].to_numpy()
    days = list(df['day'])
    k = kama(c)
    atr = wilder_atr(df['high'], df['low'], df['close'], ATR_N).to_numpy()

    def enter_fn(i):
        if i < 2 or np.isnan(k[i]) or np.isnan(k[i - 1]):
            return 0
        if c[i] > k[i] and c[i - 1] <= k[i - 1]:
            return 1
        if c[i] < k[i] and c[i - 1] >= k[i - 1]:
            return -1
        return 0

    def exit_fn(i, pos, entry_px, entry_i, stop):
        if np.isnan(k[i]):
            return False
        if pos == 1 and c[i] < k[i]:
            return True
        if pos == -1 and c[i] > k[i]:
            return True
        return False

    def stop_fn(i, entry_px, side):
        if np.isnan(atr[i]):
            return None
        return (entry_px - KAMA_STOP_ATR * atr[i] if side == 1
                else entry_px + KAMA_STOP_ATR * atr[i])

    return run_engine(o, h, l, c, days, enter_fn, exit_fn, stop_fn)


STRATEGIES = {
    'ORB':      dict(fn=make_orb,      tf='5min'),
    'MOM':      dict(fn=make_mom,      tf='5min'),
    'VWAP':     dict(fn=make_vwap,     tf='5min'),
    'DONCH15':  dict(fn=make_donch15,  tf='15min'),
    'FADESHORT': dict(fn=make_fadeshort, tf='5min'),
    'KAMA':     dict(fn=make_kama,     tf='5min'),
}


# ==================== cost + metrics ====================
def apply_cost(trades, spec, slip_ticks, use_comm):
    """Return per-trade net P&L in TICKS (scale-invariant).

    net_ticks = gross_ticks - 2*slip_ticks - comm_rt_ticks
    where gross_ticks = (exit-entry)/tick * side.
    """
    mult = spec['mult']; tick = spec['tick']
    comm_ticks = (2 * spec['comm'] / (mult * tick)) if use_comm else 0.0
    net = []
    for t in trades:
        gross = (t['exit_px'] - t['entry_px']) / tick * t['side']
        net.append(gross - 2 * slip_ticks - comm_ticks)
    return np.array(net)


def summarize(net_ticks, daily_buckets=None):
    """Metrics from a per-trade net-tick array (+ optional daily tick P&L)."""
    if len(net_ticks) == 0:
        return dict(n=0, win=0.0, pf=0.0, net=0.0, maxdd=0.0, sharpe=0.0)
    wins = net_ticks[net_ticks > 0].sum()
    losses = abs(net_ticks[net_ticks <= 0].sum())
    pf = (wins / losses) if losses > 0 else float('inf')
    # daily curve for maxDD + sharpe
    if daily_buckets is not None and len(daily_buckets):
        daily = np.array(sorted(daily_buckets.values()))
        eq = np.cumsum(daily)
        peak = np.maximum.accumulate(eq)
        maxdd = float((eq - peak).min())
        mu, sd = daily.mean(), daily.std(ddof=1)
        sharpe = (mu / sd * np.sqrt(252)) if sd > 0 else 0.0
    else:
        maxdd = 0.0
        sharpe = 0.0
    return dict(n=len(net_ticks), win=100.0 * (net_ticks > 0).mean(),
                pf=float(pf), net=float(net_ticks.sum()),
                maxdd=maxdd, sharpe=float(sharpe))


def walk_forward_split(trades):
    """Split trades into train (first 60% sessions) / OOS (last 40%)."""
    days = sorted({t['entry_day'] for t in trades})
    if not days:
        return [], []
    cut = days[int(len(days) * 0.6)]
    train = [t for t in trades if t['entry_day'] < cut]
    oos = [t for t in trades if t['entry_day'] >= cut]
    return train, oos


def daily_buckets(net_ticks, trades):
    b = {}
    for tick, t in zip(net_ticks, trades):
        b[t['entry_day']] = b.get(t['entry_day'], 0.0) + tick
    return b


# ==================== main ====================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', default=','.join(LIQUID))
    ap.add_argument('--tf', default='', help="'5min'|'1min' override (default per-strategy)")
    ap.add_argument('--smoke', action='store_true', help='1-min thin smoke test on MES/MNQ')
    args = ap.parse_args()

    syms = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
    slip_levels = [0, 1, 2, 3]
    headline_slip = 3

    results = {'specs': SPECS, 'cost_model': 'slip ticks/side + flat commission/side (x2 RT)',
               'slip_levels': slip_levels, 'headline_slip': headline_slip,
               'strategies': {}}

    print('=' * 100)
    print('INTRADAY CANDIDATE VALIDATION — honest fills, 3-tick + commission cost stress')
    print('=' * 100, flush=True)

    # ---- load all data once ----
    data = {}
    for sym in syms:
        for tf in ('5min', '15min'):
            df = load_intraday(sym, tf)
            if not df.empty:
                data[(sym, tf)] = df
            print(f'  loaded {sym} {tf}: {len(df)} bars', flush=True)

    for name, meta in STRATEGIES.items():
        tf = meta['tf']
        strat_results = {}
        all_trades = []        # pooled trades (all symbols)
        # store per-symbol trades once, reuse for everything
        per_sym_trades = {}

        for sym in syms:
            df = data.get((sym, tf))
            if df is None:
                strat_results[sym] = dict(error='no data')
                continue
            trades = meta['fn'](df)
            per_sym_trades[sym] = trades
            if not trades:
                strat_results[sym] = dict(n=0)
                continue
            spec = SPECS[sym]
            train, oos = walk_forward_split(trades)
            row = {}
            for slip in slip_levels:
                for comm in (True, False):
                    label = f'slip{slip}_comm{int(comm)}'
                    nt = apply_cost(trades, spec, slip, comm)
                    oo_nt = apply_cost(oos, spec, slip, comm)
                    s = summarize(nt, daily_buckets(nt, trades))
                    so = summarize(oo_nt, daily_buckets(oo_nt, oos))
                    row[label] = dict(pf=s['pf'], net=s['net'], n=s['n'],
                                      win=s['win'], maxdd=s['maxdd'], sharpe=s['sharpe'],
                                      oos_pf=so['pf'], oos_n=so['n'])
            strat_results[sym] = row
            all_trades.extend(trades)
            h = row[f'slip{headline_slip}_comm1']
            print(f"  {name:10s} {sym:4s}  n={h['n']:4d}  win={h['win']:5.1f}%  "
                  f"PF={h['pf']:6.2f}  net={h['net']:9.1f}t  maxDD={h['maxdd']:9.1f}t  "
                  f"Sharpe={h['sharpe']:5.2f}  | OOS PF={h['oos_pf']:6.2f} (n={h['oos_n']})",
                  flush=True)

        # pooled cost-sensitivity curve (net ticks + PF, headline commission)
        curve = {}
        for slip in slip_levels:
            nts = []
            for sym in syms:
                for t in per_sym_trades.get(sym, []):
                    nts.append(apply_cost([t], SPECS[sym], slip, True)[0])
            if nts:
                nts = np.array(nts)
                wins = nts[nts > 0].sum(); losses = abs(nts[nts <= 0].sum())
                pf = wins / losses if losses > 0 else float('inf')
                curve[f'slip{slip}'] = dict(pf=float(pf), net=float(nts.sum()), n=len(nts))

        # pooled headline + OOS (headline cost)
        all_net = []; all_net_oos = []; all_trades_oos = []
        for sym in syms:
            for t in per_sym_trades.get(sym, []):
                all_net.append(apply_cost([t], SPECS[sym], headline_slip, True)[0])
            tr, oo = walk_forward_split(per_sym_trades.get(sym, []))
            for t in oo:
                all_net_oos.append(apply_cost([t], SPECS[sym], headline_slip, True)[0])
                all_trades_oos.append(t)

        pooled = {}
        if all_net:
            pooled = dict(full=summarize(np.array(all_net), daily_buckets(np.array(all_net), all_trades)),
                          oos=summarize(np.array(all_net_oos), daily_buckets(np.array(all_net_oos), all_trades_oos)))

        results['strategies'][name] = dict(tf=tf, per_symbol=strat_results,
                                           cost_curve=curve, pooled=pooled)
        pf_full = pooled.get('full', {}).get('pf', 0)
        pf_oos = pooled.get('oos', {}).get('pf', 0)
        n_full = pooled.get('full', {}).get('n', 0)
        n_oos = pooled.get('oos', {}).get('n', 0)
        sh = pooled.get('full', {}).get('sharpe', 0)
        dd = pooled.get('full', {}).get('maxdd', 0)
        print(f"  {name} POOLED (3-tick+comm): n={n_full} PF={pf_full:.2f} Sharpe={sh:.2f} "
              f"maxDD={dd:.1f}t | OOS PF={pf_oos:.2f} (n={n_oos})", flush=True)
        print('  cost curve (slip/side + comm): ' +
              '  '.join(f"{k}: PF={v['pf']:.2f} net={v['net']:.0f}t" for k, v in curve.items()),
              flush=True)
        print('-' * 100, flush=True)

    out = '/tmp/intraday_validate_results.json'
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f'\nwrote {out}')
    repo_out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'research', 'intraday_validate_results.json')
    with open(repo_out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f'wrote {repo_out}')


if __name__ == '__main__':
    main()
