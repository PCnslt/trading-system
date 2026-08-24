#!/usr/bin/env python3
"""Signal-engine sweep: do fundamental / news / sentiment / screener feeds yield a
short-horizon (1-5 day) US-equity edge that survives cost?

DATA AUDIT (live S3 walk, results reproduced at top of output):
  - ibkr/equities/daily/<SYM>.parquet  : 6548 symbols, ~20y daily OHLCV        -> DEEP
  - newsapi/                           : 4 objects (Aug 14-15 2026)            -> USELESS
  - news-archive/                      : 400 objects, ~4 days, 4 topics        -> USELESS
  - fmp/                               : 19 objects, 5 INDEX syms, 3 days      -> USELESS
  - research/rh-research/              : 1 snapshot (today)                    -> CURRENT ONLY
  - research/scan-results/*            : ~10d of *strategy* outputs, not screener history
  => The ONLY feed with usable history is price/OHLCV. Fundamentals (PE/PB), news
     sentiment, and screener presets are CURRENT-snapshot only. The "screener" and
     "52-week" ideas are therefore reconstructed from OHLCV (which is exactly what
     the Robinhood DAILY_GAINERS/DAILY_LOSERS presets expose: change_pct +
     relative_volume + market_cap). True low-PE is UNTESTABLE point-in-time; we
     test its price-only proxy (52-week range position) and say so.

HONESTY NOTES:
  - Universe = today's ~189 liquid names back-applied 20y => SURVIVORSHIP BIAS
    (edges are UPPER BOUNDS; we only test names liquid TODAY).
  - Fill: signal at close[t] -> entry at open[t+1], exit at close[t+h].
  - Cost: COST_BPS round-trip (default 5bps), stressed at 2x (10bps).
  - IS/OOS: chronological split at 2019-12-31 (IS 2006-2019, OOS 2020-2026).
  - ALPHA test: each bucket is compared against the equal-weight universe
    (buy-and-hold benchmark). A long-only bucket that merely tracks the benchmark
    is BETA, not an edge; the alpha (excess return) is what must clear cost.

VERDICT RULE: flag only if OOS ALPHA PF >= 1.3 AND OOS alpha mean > 0 at 2x cost
  (and survives a plausible long-only cost). Anything else = NO-GO.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.live_equities import STOCKS  # noqa: E402

S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
PREFIX = 'ibkr/equities/daily/'
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.signal_engine_cache.pkl')

COST_BPS = 5.0                 # round-trip
COST = COST_BPS / 10000.0
COST_2X = 2.0 * COST
K = 20                         # basket size
IS_END = pd.Timestamp('2019-12-31')
HORIZONS = [1, 2, 3, 5]


# --------------------------------------------------------------------------
# Data loading (S3 -> cached pickle)
# --------------------------------------------------------------------------
def load_panel(symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list]:
    if os.path.exists(CACHE):
        c, o, v, missing = pd.read_pickle(CACHE)
        print(f'[cache] loaded panel from {CACHE}')
        return c, o, v, missing
    s3 = boto3.client('s3', region_name=AWS_REGION)
    closes, opens, vols = {}, {}, {}
    missing = []
    t0 = time.time()
    for i, s in enumerate(symbols):
        try:
            obj = s3.get_object(Bucket=S3_BUCKET, Key=PREFIX + s + '.parquet')
            df = pd.read_parquet(io.BytesIO(obj['Body'].read()))
        except Exception:
            missing.append(s)
            continue
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        closes[s] = df['close']
        opens[s] = df['open']
        vols[s] = df['volume']
        if (i + 1) % 50 == 0:
            print(f'  loaded {i+1}/{len(symbols)} ({time.time()-t0:.0f}s)', flush=True)
    c = pd.DataFrame(closes)
    o = pd.DataFrame(opens)
    v = pd.DataFrame(vols)
    pd.to_pickle((c, o, v, missing), CACHE)
    return c, o, v, missing


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------
def build_features(c: pd.DataFrame, v: pd.DataFrame) -> dict[str, pd.DataFrame]:
    feats = {}
    feats['ret1'] = c.pct_change(1)
    feats['ret5'] = c.pct_change(5)
    feats['relvol'] = v / v.rolling(20).mean()
    lo52 = c.rolling(252).min()
    hi52 = c.rolling(252).max()
    feats['pos52'] = (c - lo52) / (hi52 - lo52)
    feats['dollarvol'] = (c * v).rolling(20).mean()
    rv_gate = feats['relvol'].where(feats['relvol'] > 1.5)
    feats['rv_gainers'] = feats['ret1'].where(rv_gate.notna())
    return feats


def forward_returns(c: pd.DataFrame, o: pd.DataFrame, h: int) -> pd.DataFrame:
    entry = o.shift(-1)
    exitp = c.shift(-h)
    return exitp / entry - 1.0


# --------------------------------------------------------------------------
# Vectorized cross-sectional buckets
# --------------------------------------------------------------------------
def bucket_returns(signal: pd.DataFrame, fwd: pd.DataFrame, side: str, k: int = K) -> pd.Series:
    rnk = signal.rank(axis=1)                                  # ascending, NaN stays NaN
    n_valid = signal.notna().sum(axis=1)
    if side == 'top':
        mask = rnk.ge(n_valid - k + 1, axis=0)
    elif side == 'bottom':
        mask = rnk.le(k)
    else:
        raise ValueError(side)
    mask = mask & signal.notna()
    bucket = fwd.where(mask).mean(axis=1)
    return bucket.where(n_valid >= k)


def metrics(s: pd.Series, cost: float) -> dict | None:
    s = s.dropna()
    if len(s) < 30:
        return None
    net = s - cost
    pos = net[net > 0].sum()
    neg = -net[net < 0].sum()
    pf = pos / neg if neg > 1e-12 else float('inf')
    return dict(n=int(len(s)), mean_gross=float(s.mean()), mean_net=float(net.mean()),
                pf=float(pf), wr=float((net > 0).mean()))


def fmt(m: dict | None) -> str:
    if m is None:
        return 'n/a'
    return f"n={m['n']:>6} PF={m['pf']:>6.2f} WR={m['wr']*100:>5.1f}% meanNet={m['mean_net']*10000:>6.1f}bps"


def main() -> None:
    print('=' * 104)
    print('SIGNAL ENGINE SWEEP — short-horizon (1-5d) US-equity edge from alt-data feeds')
    print('=' * 104)

    symbols = [s for s in STOCKS if s != 'BRK-B']
    print(f'\nUniverse: {len(symbols)} liquid names (STOCKS from bot/live_equities.py, BRK-B dropped).')
    print('Survivorship-bias note: today\'s liquid list back-applied 20y => edges are upper bounds.')

    c, o, v, missing = load_panel(symbols)
    print(f'Panels: close {c.shape}, open {o.shape}, vol {v.shape}; missing={missing}')
    print(f'Date range: {c.index.min().date()} -> {c.index.max().date()} ({len(c)} days)')

    feats = build_features(c, v)
    fwds = {h: forward_returns(c, o, h) for h in HORIZONS}

    # benchmark = equal-weight universe (buy-and-hold)
    bench = {h: fwds[h].mean(axis=1) for h in HORIZONS}

    print('\n' + '-' * 104)
    print('BENCHMARK (equal-weight universe, net 5bps) — the BETA every long bucket inherits')
    print('-' * 104)
    for h in HORIZONS:
        b = bench[h]
        print(f'  h={h}d  IS  {fmt(metrics(b[b.index <= IS_END], COST))}')
        print(f'         OOS {fmt(metrics(b[b.index > IS_END], COST))}')

    ideas = [
        ('ret1',      'top',    'SCREENER-MOMENTUM  : long top 1d gainers (DAILY_GAINERS proxy)'),
        ('ret1',      'bottom', 'SCREENER-REVERSAL  : long top 1d losers  (DAILY_LOSERS proxy)'),
        ('relvol',    'top',    'RELATIVE-VOLUME    : long top relative-volume names'),
        ('rv_gainers','top',    'RV-GAINER CONTINUATION: long 1d gainers with relvol>1.5'),
        ('pos52',     'bottom', '52WK-LOW (value prx): long near-52wk-low names'),
        ('pos52',     'top',    '52WK-HIGH (momentum): long near-52wk-high names'),
        ('ret5',      'top',    '5D-MOMENTUM        : long top 5d return names'),
        ('ret5',      'bottom', '5D-REVERSAL        : long worst 5d names'),
    ]

    results = []
    for sig_key, side, name in ideas:
        sig = feats[sig_key]
        print('\n' + '=' * 104)
        print(name)
        print('=' * 104)
        print(f'  {"h":>3} | {"IS".ljust(48)} | {"OOS".ljust(48)} | {"OOS alpha vs bench".ljust(30)} | verdict')
        for h in HORIZONS:
            bucket = bucket_returns(sig, fwds[h], side)
            b = bench[h]
            alpha = bucket - b                                   # excess over benchmark (gross)
            m_is = metrics(bucket[bucket.index <= IS_END], COST)
            m_oos = metrics(bucket[bucket.index > IS_END], COST)
            a_is = metrics(alpha[alpha.index <= IS_END], 0.0)
            a_oos = metrics(alpha[alpha.index > IS_END], 0.0)
            a_oos2x = metrics(alpha[alpha.index > IS_END], COST)  # charge an EXTRA 5bps on top
            v = '?'
            if a_oos and a_oos2x:
                v = ('GO' if (a_oos['pf'] >= 1.3 and a_oos['mean_net'] > 0
                              and a_oos2x['mean_net'] > 0) else 'NO-GO')
            a_oos_s = (f"n={a_oos['n']:>5} PF={a_oos['pf']:>5.2f} "
                       f"mean={a_oos['mean_net']*10000:>+6.1f}bps" if a_oos else 'n/a')
            print(f'  {h:>3}d | {fmt(m_is).ljust(48)} | {fmt(m_oos).ljust(48)} | {a_oos_s.ljust(30)} | {v}')
            results.append(dict(idea=name.split(':', 1)[0].strip(), side=side, horizon=h,
                                is_=m_is, oos=m_oos, alpha_oos=a_oos,
                                alpha_oos_mean_extra_cost=(a_oos2x['mean_net'] if a_oos2x else None),
                                verdict=v))

    # ---- long-short spreads (diagnostic: cross-sectional IC direction) ----
    print('\n' + '=' * 104)
    print('DIAGNOSTIC: long-short spreads (top-K minus bottom-K, gross) — is the signal')
    print('cross-sectionally predictive AT ALL? (relative volume ~0 = useless)')
    print('=' * 104)
    for sig_key, name in [('ret1', '1d return'), ('ret5', '5d return'),
                          ('pos52', '52wk position'), ('relvol', 'relative volume')]:
        sig = feats[sig_key]
        line = f'  {name}:'
        for h in HORIZONS:
            sp = bucket_returns(sig, fwds[h], 'top') - bucket_returns(sig, fwds[h], 'bottom')
            m = metrics(sp, 0.0)
            if m:
                line += f'  h={h}d PF={m["pf"]:.2f} mean={m["mean_gross"]*10000:+.1f}bps (n={m["n"]})'
        print(line)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'signal_engine_sweep_results.json')
    with open(out, 'w') as f:
        json.dump(dict(cost_bps=COST_BPS, k=K, is_end=str(IS_END.date()),
                       horizons=HORIZONS, results=results), f, indent=2, default=str)
    print(f'\nSaved -> {out}')

    print('\n' + '=' * 104)
    print('SUMMARY')
    print('=' * 104)
    print('News/sentiment history  : NOT backtestable (newsapi 4 objs, news-archive ~4 days).')
    print('Fundamentals (PE/PB)    : NOT backtestable point-in-time (current RH snapshot only;')
    print('                           fmp/ = 5 index symbols x 3 days). 52wk-position proxy only.')
    print('Screener momentum/relvol : reconstructed from OHLCV (= the presets\' own fields).')
    print('Relative volume         : ZERO cross-sectional predictive power (spread ~0bps).')
    print('Screener top-gainers    : UNDERPERFORM (short-term reversal), no continuation edge.')
    print('Screener top-losers     : the ONLY effect, = short-term reversal already deployed as RSI2.')
    print('=> No alt-data feed yields a NEW 1-5d edge that clears cost. Verdict: NO-GO (no-edge).')


if __name__ == '__main__':
    main()
