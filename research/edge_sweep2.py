#!/usr/bin/env python3
"""EDGE SWEEP 2 — four new strategy families from laptop research.

Families (paper-only, no live):
  1. COMMODITY CARRY / TERM-STRUCTURE — cross-sectional roll-return ranking
     (near-far calendar spread from IBKR per-contract chain). PROXY — see caveats.
  2. CROSS-SECTIONAL MOMENTUM — futures (yfinance 16y + IBKR 5y) and
     equities (~5.8k US stocks, 20y).
  3. VOLATILITY TARGETING OVERLAY — 1/realized-vol scaling on existing
     Donchian + RSI2 edges (ES, GC).
  4. VALUE / LONG-TERM REVERSAL — spot vs 5y rolling mean, cross-sectional +
     time-series, futures.

Cost model (futures, tick-grid): fee 1.3 bps round-trip of notional + slippage
0/1/2/3 ticks per side (per-symbol tick sizes from verified specs). Monthly
cross-sectional portfolios model cost as turnover x (fee + 2 x slip x tick/price)
per position; turnover assumed 1.0 (positions re-established monthly) unless the
position is unchanged.
Equities cost: bps {0,2,5,10} + cents/share {0,1,2,3} per side (Lane-C convention).

Honest-fill note: monthly cross-sectional portfolios are mark-to-market at
month-end close; entry at the month-end close that generates the signal, so
forward return = close[m]/close[m-1] - 1 (no lookahead).

Run per-family:  ./venv/bin/python research/edge_sweep2.py --family carry
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(HERE, 'edge_sweep2_results.json')

import boto3  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(HERE, '..', '.env'))
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3 = boto3.client('s3', region_name=AWS_REGION)

FEE_BPS = 0.00013          # 1.3 bps round-trip notional (owner baseline)
SLIP_TICKS = [0, 1, 2, 3]
EQ_BPS = [0, 2, 5, 10]     # equities slippage per side (bps)
EQ_CENTS = [0, 1, 2, 3]    # equities slippage per side (cents/share)

# ---- verified tick sizes (price units) for futures slippage stress ----
# (futures-contract-specs.md + asset-class defaults for IBKR-only symbols)
TICK = {
    # yfinance index
    'ES=F': 0.25, 'NQ=F': 0.25, 'YM=F': 1.0, 'RTY=F': 0.1,
    # energy (NYMEX)
    'CL=F': 0.01, 'NG=F': 0.001, 'RB=F': 0.0001, 'HO=F': 0.0001,
    # metals (COMEX)
    'GC=F': 0.1, 'SI=F': 0.005, 'HG=F': 0.0005, 'PL=F': 0.1, 'PA=F': 0.05,
    # ags
    'ZC=F': 0.25, 'ZW=F': 0.25, 'ZS=F': 0.25, 'ZM=F': 0.1, 'ZL=F': 0.01,
    'HE=F': 0.025, 'LE=F': 0.025,
    # fx
    '6E=F': 0.00005, '6B=F': 0.0001, '6A=F': 0.00005, '6C=F': 0.00005,
    '6S=F': 0.0001, '6M=F': 0.00005,
    # rates
    'ZB=F': 0.03125, 'ZN=F': 0.015625,
}
# IBKR-continuous symbols (root) -> tick, for the 56-sym set
TICK_ROOT = {
    # index
    'ES': 0.25, 'NQ': 0.25, 'YM': 1.0, 'RTY': 0.1, 'MES': 0.25, 'MNQ': 0.25,
    'MYM': 0.5, 'M2K': 0.05, 'EMD': 0.1, 'NKD': 5.0, 'NIY': 5.0,
    # energy
    'CL': 0.01, 'NG': 0.001, 'RB': 0.0001, 'HO': 0.0001, 'QM': 0.025,
    'QG': 0.0025, 'BZ': 0.01, 'MCL': 0.01, 'GF': 0.1,
    # metals
    'GC': 0.1, 'SI': 0.005, 'HG': 0.0005, 'PL': 0.1, 'PA': 0.05, 'MGC': 0.1,
    'MHG': 0.0005, 'ALI': 0.05,
    # ags
    'ZC': 0.25, 'ZW': 0.25, 'ZS': 0.25, 'ZM': 0.1, 'ZL': 0.01, 'ZO': 0.01,
    'HE': 0.025, 'LE': 0.025, 'ZR': 0.01, 'KE': 0.25, 'YK': 0.05,
    # fx
    '6M': 0.00005, 'M6A': 0.00005, 'M6B': 0.0001, 'M6E': 0.00005,
    # rates
    'ZB': 0.03125, 'ZN': 0.015625, 'ZF': 0.0078125, 'ZT': 0.00390625,
    'ZQ': 0.0025, 'UB': 0.03125, 'TN': 0.015625,
    '10Y': 0.015625, '2YY': 0.0078125, '5YY': 0.0078125, '30Y': 0.03125,
}

# asset class (for carry universe)
ASSET_CLASS = {
    'CL': 'energy', 'NG': 'energy', 'RB': 'energy', 'HO': 'energy',
    'QM': 'energy', 'QG': 'energy', 'BZ': 'energy', 'MCL': 'energy',
    'GC': 'metals', 'SI': 'metals', 'HG': 'metals', 'PL': 'metals',
    'PA': 'metals', 'MGC': 'metals', 'MHG': 'metals', 'ALI': 'metals',
    'ZC': 'ags', 'ZW': 'ags', 'ZS': 'ags', 'ZM': 'ags', 'ZL': 'ags',
    'ZO': 'ags', 'HE': 'ags', 'LE': 'ags', 'ZR': 'ags', 'KE': 'ags', 'YK': 'ags',
    'GF': 'ags',
    '6M': 'fx', 'M6A': 'fx', 'M6B': 'fx', 'M6E': 'fx',
    'ZB': 'rates', 'ZN': 'rates', 'ZF': 'rates', 'ZT': 'rates', 'ZQ': 'rates',
    'UB': 'rates', 'TN': 'rates', '10Y': 'rates', '2YY': 'rates',
    '5YY': 'rates', '30Y': 'rates',
    'ES': 'index', 'NQ': 'index', 'YM': 'index', 'RTY': 'index', 'MES': 'index',
    'MNQ': 'index', 'MYM': 'index', 'M2K': 'index', 'EMD': 'index',
    'NKD': 'index', 'NIY': 'index',
}


# ======================================================================
# data loaders (S3)
# ======================================================================
def s3_get(key):
    r = S3.get_object(Bucket=S3_BUCKET, Key=key)
    return r['Body'].read()


def list_keys(prefix):
    keys, token = [], None
    while True:
        kw = dict(Bucket=S3_BUCKET, Prefix=prefix, MaxKeys=1000)
        if token:
            kw['ContinuationToken'] = token
        r = S3.list_objects_v2(**kw)
        keys.extend([x['Key'] for x in r.get('Contents', [])])
        if r.get('IsTruncated'):
            token = r.get('NextContinuationToken')
        else:
            break
    return keys


def load_yf_futures(sym):
    """yfinance continuous daily -> DataFrame indexed by date (Close etc.)."""
    d = json.loads(s3_get(f'yf/futures/{sym}.json'))
    df = pd.DataFrame(d['daily'])
    df['ts'] = pd.to_datetime(df['ts'])
    df = df.rename(columns={'ts': 'date', 'open': 'Open', 'high': 'High',
                            'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
    return df.set_index('date')[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)


def load_ibkr_continuous(sym):
    """IBKR CONTFUT continuous -> DataFrame indexed by date."""
    import io
    df = pd.read_parquet(io.BytesIO(s3_get(f'ibkr/futures/daily/{sym}_continuous.parquet')))
    df['date'] = pd.to_datetime(df['date'])
    df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low',
                            'close': 'Close', 'volume': 'Volume'})
    return df.set_index('date')[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)


def load_ibkr_percontract(sym):
    """Current-chain per-contract daily -> {expiry_yyyymmdd: DataFrame}."""
    import io
    out = {}
    for k in list_keys(f'ibkr/futures/daily/{sym}/'):
        if not k.endswith('.parquet'):
            continue
        exp = k.split('/')[-1].replace('.parquet', '')
        df = pd.read_parquet(io.BytesIO(s3_get(k)))
        df['date'] = pd.to_datetime(df['date'])
        df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low',
                                'close': 'Close', 'volume': 'Volume'})
        out[exp] = df.set_index('date')[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
    return out


def load_equities(min_history=1260, min_price=5.0, min_dv=1_000_000.0,
                  max_syms=None, cache='/tmp/eq_mom_panel.pkl'):
    """Liquid US equity universe -> dict sym -> month-end close Series.

    Filters (survivorship caveat: universe = current-listing snapshot, so
    delisted names are absent; see report). Only reads close+volume columns.
    """
    import io
    from concurrent.futures import ThreadPoolExecutor

    if os.path.exists(cache):
        d = pd.read_pickle(cache)
        print(f'[equities] cached {len(d)} symbols from {cache}')
        return d

    keys = list_keys('ibkr/equities/daily/')
    syms = [k.split('/')[-1].replace('.parquet', '') for k in keys if k.endswith('.parquet')]
    if max_syms:
        syms = syms[:max_syms]

    def one(sym):
        try:
            df = pd.read_parquet(io.BytesIO(s3_get(f'ibkr/equities/daily/{sym}.parquet')),
                                 columns=['date', 'close', 'volume'])
            df['date'] = pd.to_datetime(df['date'])
            df = df.dropna(subset=['close'])
            if len(df) < min_history:
                return None
            med_close = df['close'].median()
            if med_close < min_price:
                return None
            med_dv = (df['close'] * df['volume']).median()
            if med_dv < min_dv:
                return None
            # month-end closes
            me = df.set_index('date')['close'].resample('ME').last().dropna()
            if len(me) < 60:  # >=5y of monthly closes
                return None
            return sym, me.astype('float32')
        except Exception:
            return None

    out = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=32) as ex:
        for r in ex.map(one, syms):
            if r:
                out[r[0]] = r[1]
    pd.to_pickle(out, cache)
    print(f'[equities] {len(out)}/{len(syms)} passed filter in {time.time()-t0:.0f}s '
          f'(min_hist={min_history}, min_price={min_price}, min_dv={min_dv})')
    return out


# ======================================================================
# metrics
# ======================================================================
def pf_of(pnls):
    pnls = np.asarray(pnls, dtype=float)
    wins = pnls[pnls > 0].sum()
    losses = pnls[pnls <= 0].sum()
    if losses == 0:
        return (float('inf') if wins > 0 else 0.0)
    return float(wins / abs(losses))


def portfolio_metrics(ret, ann=12):
    """ret = Series of net monthly (or daily) portfolio returns (fraction)."""
    ret = ret.dropna()
    if len(ret) < 2:
        return {'n': int(len(ret)), 'pf': 0.0, 'net': 0.0, 'maxdd': 0.0,
                'sharpe': 0.0, 'ann_ret': 0.0}
    eq = (1.0 + ret).cumprod()
    pos = ret[ret > 0].sum()
    neg = ret[ret <= 0].sum()
    pf = pos / abs(neg) if neg != 0 else (float('inf') if pos > 0 else 0.0)
    maxdd = float((eq / eq.cummax() - 1.0).min())
    sharpe = float(ret.mean() / ret.std() * np.sqrt(ann)) if ret.std() > 0 else 0.0
    net = float(eq.iloc[-1] - 1.0)
    ann_ret = float(eq.iloc[-1] ** (ann / len(ret)) - 1.0) if eq.iloc[-1] > 0 else -1.0
    return {'n': int(len(ret)), 'pf': float(pf), 'net': net, 'maxdd': maxdd,
            'sharpe': sharpe, 'ann_ret': ann_ret}


def walk_forward_ret(ret):
    """40/20/40 split of a monthly return series by DATE."""
    n = len(ret)
    a = int(n * 0.4)
    b = int(n * 0.6)
    return {
        'train': portfolio_metrics(ret.iloc[:a]),
        'validate': portfolio_metrics(ret.iloc[a:b]),
        'oos': portfolio_metrics(ret.iloc[b:]),
    }


# ======================================================================
# monthly cross-sectional portfolio engine (futures)
# ======================================================================
def month_end_closes(df):
    return df['Close'].resample('ME').last().dropna()


def xsectional_futures(closes, scores, n_top, n_bot, ticks_map, slip_ticks=SLIP_TICKS,
                       fee_bps=FEE_BPS, hold_months=1):
    """Cross-sectional monthly long/short on a panel of month-end closes.

    closes: DataFrame [month-end x symbol] of closes (float)
    scores: DataFrame [month-end x symbol] of signal at that month-end (uses info
            available AT that date; the signal must be computed WITHOUT the
            forward return, which the caller guarantees).
    n_top/n_bot: number of names in each leg (top = long, bottom = short).
    Returns {slipN: monthly net-return Series}.
    """
    months = closes.index
    results = {s: [] for s in slip_ticks}
    dates = []
    for m in range(hold_months, len(months)):
        t0 = months[m - hold_months]      # rebalance date (positions held from here)
        t1 = months[m]                    # valuation date
        score_t = scores.loc[t0].dropna()
        if len(score_t) < (n_top + n_bot):
            continue
        rank = score_t.rank(ascending=False)
        longs = rank[rank <= n_top].index
        shorts = rank[rank >= (len(rank) - n_bot + 1)].index
        fwd = closes.loc[t1] / closes.loc[t0] - 1.0
        # per-leg gross return (equal weight)
        long_ret = fwd[longs].mean()
        short_ret = -fwd[shorts].mean()
        gross = (long_ret + short_ret) / 2.0
        for s in slip_ticks:
            # cost: turnover=1.0 (re-establish monthly); fee + 2*s*tick/price per side
            cost_long = np.mean([fee_bps + 2 * s * ticks_map.get(x, 0.01) / closes.loc[t0, x]
                                 for x in longs])
            cost_short = np.mean([fee_bps + 2 * s * ticks_map.get(x, 0.01) / closes.loc[t0, x]
                                  for x in shorts])
            results[s].append((gross - (cost_long + cost_short) / 2.0))
        dates.append(t1)
    out = {}
    for s in slip_ticks:
        out[s] = pd.Series(results[s], index=pd.DatetimeIndex(dates))
    return out


def momentum_score(closes, skip_months=1, lookback_months=11):
    """Trailing 12m return skipping most recent month: close[t-1]/close[t-12]-1."""
    return closes.shift(skip_months) / closes.shift(skip_months + lookback_months) - 1.0


# ======================================================================
# FAMILY 1 — commodity carry (term-structure proxy)
# ======================================================================
def family_carry(min_history=756, n_top_bot=2):
    """Cross-sectional roll-return ranking on IBKR per-contract chain.

    PROXY: roll return = (near - far)/near between the two contracts in the
    CURRENT chain with the longest overlapping history (fixed calendar spread,
    NOT rolling near/far). Universe = energy+metals+ags+rates.
    """
    print('\n' + '=' * 90)
    print('FAMILY 1 — COMMODITY CARRY / TERM STRUCTURE (fixed-calendar-spread proxy)')
    print('=' * 90)

    # candidate universe: symbols with per-contract data, commodity/rates
    roots = set()
    for k in list_keys('ibkr/futures/daily/'):
        parts = k.split('/')
        if len(parts) >= 5 and parts[4].endswith('.parquet') and parts[3] != '':
            roots.add(parts[3])
    roots = sorted(r for r in roots if ASSET_CLASS.get(r) in ('energy', 'metals', 'ags', 'rates'))

    closes, scores = {}, {}
    for sym in roots:
        pc = load_ibkr_percontract(sym)
        if len(pc) < 2:
            continue
        # pick the pair (near, far) with the longest common history
        exps = sorted(pc.keys())
        best = None
        for i in range(len(exps)):
            for j in range(i + 1, len(exps)):
                common = pc[exps[i]]['Close'].dropna().reindex(
                    pc[exps[j]]['Close'].dropna().index).dropna()
                if len(common) >= min_history:
                    if best is None or len(common) > best[0]:
                        best = (len(common), exps[i], exps[j])
        if best is None:
            continue
        _, near_exp, far_exp = best
        near = pc[near_exp]['Close']
        far = pc[far_exp]['Close']
        both = pd.concat([near, far], axis=1, keys=['near', 'far']).dropna()
        roll_ret = (both['near'] - both['far']) / both['near']
        # month-end roll-return signal (use last value of month)
        sig = roll_ret.resample('ME').last().dropna()
        # P&L on the continuous contract
        cont = load_ibkr_continuous(sym)
        me = month_end_closes(cont)
        # align signal to month-end closes
        common_idx = me.index.intersection(sig.index)
        closes[sym] = me.reindex(common_idx)
        scores[sym] = sig.reindex(common_idx)
        print(f'  {sym:4s} pair {near_exp[:6]}->{far_exp[:6]}  roll-return window '
              f'{common_idx.min().date()}..{common_idx.max().date()} ({len(common_idx)} months)')

    if len(closes) < (n_top_bot * 2):
        print(f'  insufficient symbols ({len(closes)}) for carry cross-section')
        return None
    closes_df = pd.DataFrame(closes)
    scores_df = pd.DataFrame(scores)
    tmap = {s: TICK_ROOT.get(s, 0.01) for s in closes_df.columns}

    res = {}
    slip_series = xsectional_futures(closes_df, scores_df, n_top_bot, n_top_bot, tmap)
    for s, ret in slip_series.items():
        res[f'slip{s}'] = portfolio_metrics(ret)
    # walk-forward on the 0-tick series (signal quality independent of cost)
    wf = walk_forward_ret(slip_series[0])
    res['walk_forward'] = wf
    res['n_symbols'] = int(len(closes_df.columns))
    res['n_months'] = int(len(closes_df))
    res['note'] = ('PROXY: fixed calendar spread of CURRENT forward chain, not '
                   'rolling near/far term structure. True carry (1979-2004 style) '
                   'needs historical near+far contract prices (unavailable: expired '
                   'contracts -> Error 200).')
    _print_portfolio('carry', res, slip_series)
    return res


# ======================================================================
# FAMILY 2 — cross-sectional momentum
# ======================================================================
def family_xsmom_futures(n_top_bot=3):
    print('\n' + '=' * 90)
    print('FAMILY 2a — CROSS-SECTIONAL MOMENTUM (futures)')
    print('=' * 90)

    # primary: yfinance 14 symbols x 16y
    yf_syms = ['CL=F', 'GC=F', 'NG=F', 'SI=F', 'ZC=F', 'ZS=F', 'ZW=F',
               'ES=F', 'NQ=F', 'YM=F', 'RTY=F', 'ZB=F', 'ZN=F', '6E=F']
    closes, ticks = {}, {}
    for s in yf_syms:
        try:
            df = load_yf_futures(s)
            me = month_end_closes(df)
            if len(me) < 120:
                continue
            closes[s] = me
            ticks[s] = TICK.get(s, 0.01)
        except Exception as e:
            print(f'  {s} load failed: {e}')
    cdf = pd.DataFrame(closes)
    scores = momentum_score(cdf)
    print(f'  yfinance universe: {len(cdf.columns)} symbols, '
          f'{cdf.index.min().date()}..{cdf.index.max().date()} ({len(cdf)} months)')

    slip_series = xsectional_futures(cdf, scores, n_top_bot, n_top_bot, ticks)
    res = {}
    for s, ret in slip_series.items():
        res[f'slip{s}'] = portfolio_metrics(ret)
    res['walk_forward'] = walk_forward_ret(slip_series[0])
    res['n_symbols'] = int(len(cdf.columns))
    res['n_months'] = int(len(cdf))
    res['universe'] = 'yfinance continuous (16y)'
    _print_portfolio('xsmom_futures_yf', res, slip_series)

    # secondary: IBKR 56 symbols x ~5y (wider cross-section, shorter history)
    roots = [k.split('/')[-1].replace('_continuous.parquet', '')
             for k in list_keys('ibkr/futures/daily/')
             if k.endswith('_continuous.parquet')]
    closes2, ticks2 = {}, {}
    for r in roots:
        try:
            df = load_ibkr_continuous(r)
            me = month_end_closes(df)
            if len(me) < 24:
                continue
            closes2[r] = me
            ticks2[r] = TICK_ROOT.get(r, 0.01)
        except Exception:
            pass
    cdf2 = pd.DataFrame(closes2)
    scores2 = momentum_score(cdf2)
    print(f'  IBKR universe: {len(cdf2.columns)} symbols, '
          f'{cdf2.index.min().date()}..{cdf2.index.max().date()} ({len(cdf2)} months)')
    n_top2 = max(2, int(len(cdf2.columns) * 0.2))
    slip_series2 = xsectional_futures(cdf2, scores2, n_top2, n_top2, ticks2)
    res2 = {}
    for s, ret in slip_series2.items():
        res2[f'slip{s}'] = portfolio_metrics(ret)
    res2['walk_forward'] = walk_forward_ret(slip_series2[0])
    res2['n_symbols'] = int(len(cdf2.columns))
    res2['n_months'] = int(len(cdf2))
    res2['universe'] = 'IBKR continuous (~5y, wider cross-section)'
    res2['n_top_bot'] = n_top2
    _print_portfolio('xsmom_futures_ibkr', res2, slip_series2)

    return {'yfinance': res, 'ibkr': res2}


def family_xsmom_equities(n_top_bot=None, quintile=True):
    print('\n' + '=' * 90)
    print('FAMILY 2b — CROSS-SECTIONAL MOMENTUM (US equities, Jegadeesh-Titman)')
    print('=' * 90)
    eq = load_equities()
    panel = pd.DataFrame({s: v for s, v in eq.items()})
    panel = panel.sort_index()
    print(f'  liquid universe panel: {panel.shape[1]} symbols, '
          f'{panel.index.min().date()}..{panel.index.max().date()} ({panel.shape[0]} months)')

    scores = momentum_score(panel, skip_months=1, lookback_months=11)
    if quintile:
        n_bucket = max(1, int(panel.shape[1] // 5))
        n_top_bot = n_bucket
    else:
        n_top_bot = n_top_bot or max(2, int(panel.shape[1] * 0.2))

    # run cross-sectional with a bps+cents cost grid
    months = panel.index
    legs = []  # (date, gross_ret, turnover, n_long, n_short)
    for m in range(1, len(months)):
        t0 = months[m - 1]
        t1 = months[m]
        score_t = scores.loc[t0].dropna()
        if len(score_t) < 2 * n_top_bot:
            continue
        rank = score_t.rank(ascending=False)
        longs = rank[rank <= n_top_bot].index
        shorts = rank[rank >= (len(rank) - n_top_bot + 1)].index
        fwd = panel.loc[t1] / panel.loc[t0] - 1.0
        gross = (fwd[longs].mean() - fwd[shorts].mean()) / 2.0
        n = len(longs) + len(shorts)
        legs.append((t1, gross, n, len(longs), len(shorts), panel.loc[t0, longs], panel.loc[t0, shorts]))

    dates = [x[0] for x in legs]
    gross = pd.Series([x[1] for x in legs], index=dates)
    n_pos = pd.Series([x[2] for x in legs], index=dates)

    res = {}
    for bps in EQ_BPS:
        for cents in EQ_CENTS:
            # cost per position: 2 sides x (bps*price + cents) / price, avg over legs
            costs = []
            for (_, g, n, nl, ns, pl, ps) in legs:
                # fractional cost per leg (turnover=1.0)
                cost_long = np.mean(2 * (bps / 1e4) + 2 * cents / pl) if len(pl) else 0.0
                cost_short = np.mean(2 * (bps / 1e4) + 2 * cents / ps) if len(ps) else 0.0
                costs.append((cost_long + cost_short) / 2.0)
            cost = pd.Series(costs, index=dates)
            net = gross - cost
            res[f'bps{bps}_cents{cents}'] = portfolio_metrics(net)
    res['walk_forward'] = walk_forward_ret(gross - 0.0)  # gross OOS for reference
    res['n_symbols'] = int(panel.shape[1])
    res['n_months'] = int(panel.shape[0])
    res['n_top_bot'] = n_top_bot
    res['note'] = ('Survivorship bias: universe is the current-listing snapshot '
                   '(delisted names absent) -> short leg (recent losers) is biased; '
                   'long-short spread is OVERSTATED. Delisted losers missing from the '
                   'short leg. Treat as upper bound.')

    # print headline
    print(f'  long/short legs: {n_top_bot} names each ({2*n_top_bot} positions), '
          f'{len(gross)} months')
    print(f'  GROSS  : PF={portfolio_metrics(gross)["pf"]:.2f} '
          f'sharpe={portfolio_metrics(gross)["sharpe"]:.2f} '
          f'ann={portfolio_metrics(gross)["ann_ret"]*100:.1f}% '
          f'maxDD={portfolio_metrics(gross)["maxdd"]*100:.1f}%')
    for bps in EQ_BPS:
        row = [res[f'bps{bps}_cents{c}'] for c in EQ_CENTS]
        cells = '  '.join(f'c{c}:[PF {r["pf"]:.2f} / sh {r["sharpe"]:.2f} / dd {r["maxdd"]*100:.0f}%]'
                          for c, r in zip(EQ_CENTS, row))
        print(f'  slip {bps}bps/side: {cells}')
    wf = res['walk_forward']
    print(f'  GROSS walk-forward 40/20/40: train PF {wf["train"]["pf"]:.2f} / '
          f'val {wf["validate"]["pf"]:.2f} / OOS {wf["oos"]["pf"]:.2f} (n={wf["oos"]["n"]})')
    return res


# ======================================================================
# FAMILY 3 — volatility targeting overlay
# ======================================================================
def realized_vol(close, n=20, ann=252):
    r = np.log(close / close.shift(1))
    return r.rolling(n).std() * np.sqrt(ann)


def family_vol_overlay(target_vols=(0.10, 0.20, 0.30), cap=3.0, floor=0.0):
    from research.validate_edges import run_donchian, run_rsi2_long

    print('\n' + '=' * 90)
    print('FAMILY 3 — VOLATILITY TARGETING OVERLAY (1/realized-vol) on Donchian + RSI2')
    print('=' * 90)
    print('  Return-space comparison (scale-invariant): does 1/realized-vol scaling')
    print('  improve the Sharpe / maxDD of the underlying trade stream?')

    specs = {'ES=F': (50.0, 0.25), 'GC=F': (100.0, 0.1)}
    out = {}
    for sym, (mult, tick) in specs.items():
        df = load_yf_futures(sym)
        vol = realized_vol(df['Close'], 20).shift(1)  # known at entry (t-1)
        c = df['Close']
        r = c.pct_change().fillna(0.0)
        for strat, fn, kw in [('DONCHIAN', run_donchian, {}),
                              ('RSI2', run_rsi2_long, {})]:
            trades, eq_base = fn(df, mult=mult, tick=tick, slip=0, **kw)
            if not trades:
                continue
            idx = df.index
            ret_base = pd.Series(0.0, index=idx)
            ret_over = {tv: pd.Series(0.0, index=idx) for tv in target_vols}
            for t in trades:
                ei, xi, dr = t['entry_i'], t['exit_i'], t['dir']
                for k in range(ei + 1, xi + 1):
                    ret_base.iloc[k] = dr * r.iloc[k]
                for tv in target_vols:
                    v = vol.iloc[ei]
                    w = 1.0 if (np.isnan(v) or v <= 0) else min(cap, max(floor, tv / v))
                    for k in range(ei + 1, xi + 1):
                        ret_over[tv].iloc[k] = w * dr * r.iloc[k]
            base_m = _daily_metrics(ret_base)
            print(f'  [{sym} {strat}] n={len(trades)}  base: sharpe={base_m["sharpe"]:.2f} '
                  f'maxDD={base_m["maxdd"]*100:.1f}% ann={base_m["ann_ret"]*100:.1f}%')
            ov = {}
            for tv in target_vols:
                m = _daily_metrics(ret_over[tv])
                ov[f'tv{tv*100:.0f}'] = m
                print(f'           overlay tv={tv*100:.0f}%: sharpe={m["sharpe"]:.2f} '
                      f'maxDD={m["maxdd"]*100:.1f}% ann={m["ann_ret"]*100:.1f}%')
            out[f'{sym}_{strat}'] = {'trades': len(trades), 'base': base_m, 'overlay': ov}
    return out


def _daily_metrics(ret):
    ret = ret.dropna()
    sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) if len(ret) > 2 and ret.std() > 0 else 0.0
    eq = (1.0 + ret).cumprod()
    maxdd = float((eq / eq.cummax() - 1.0).min())
    return {'sharpe': sharpe, 'maxdd': maxdd, 'ann_ret': float(eq.iloc[-1] ** (252 / len(ret)) - 1.0),
            'n': int(len(ret))}


# ======================================================================
# FAMILY 4 — value / long-term reversal (futures)
# ======================================================================
def family_value(n_top_bot=3, mean_years=5):
    print('\n' + '=' * 90)
    print('FAMILY 4 — VALUE / LONG-TERM REVERSAL (spot vs rolling 5y mean)')
    print('=' * 90)

    yf_syms = ['CL=F', 'GC=F', 'NG=F', 'SI=F', 'ZC=F', 'ZS=F', 'ZW=F',
               'ES=F', 'NQ=F', 'YM=F', 'RTY=F', 'ZB=F', 'ZN=F', '6E=F']
    closes, ticks = {}, {}
    for s in yf_syms:
        try:
            df = load_yf_futures(s)
            me = month_end_closes(df)
            if len(me) < mean_years * 12 + 24:
                continue
            closes[s] = me
            ticks[s] = TICK.get(s, 0.01)
        except Exception as e:
            print(f'  {s} load failed: {e}')
    cdf = pd.DataFrame(closes)
    # value signal: log(spot / 5y rolling mean). negative = cheap -> long.
    mean5 = cdf.rolling(mean_years * 12).mean()
    val_score = np.log(cdf / mean5)

    print(f'  universe: {len(cdf.columns)} symbols, {cdf.index.min().date()}..{cdf.index.max().date()}')

    # (a) cross-sectional: long cheap quintile / short rich quintile
    slip_series = xsectional_futures(cdf, val_score, n_top_bot, n_top_bot, ticks)
    res_cs = {}
    for s, ret in slip_series.items():
        res_cs[f'slip{s}'] = portfolio_metrics(ret)
    res_cs['walk_forward'] = walk_forward_ret(slip_series[0])
    res_cs['n_symbols'] = int(len(cdf.columns))
    res_cs['n_months'] = int(len(cdf))
    _print_portfolio('value_crosssectional', res_cs, slip_series)

    # (b) time-series: per symbol, long if spot < 5y mean, short if above; monthly
    res_ts = {}
    for s in slip_series:
        pass
    all_ret = {}
    for sym in cdf.columns:
        sig = (cdf[sym] < mean5[sym]).astype(float)  # 1=long, 0
        sig = sig.replace(0.0, -1.0)                  # -1=short
        fwd = cdf[sym].pct_change().shift(-1)
        # position set at month-end t, return realized over next month
        pos = sig.shift(1)
        r = pos * fwd
        all_ret[sym] = r
    ts_panel = pd.DataFrame(all_ret)
    ts_ret = ts_panel.mean(axis=1).dropna()
    res_ts['gross'] = portfolio_metrics(ts_ret)
    res_ts['walk_forward'] = walk_forward_ret(ts_ret)
    # cost stress (avg fee+slip across symbols each month)
    res_ts['slip'] = {}
    for s in SLIP_TICKS:
        cost = pd.Series(index=ts_ret.index, dtype=float)
        for sym in cdf.columns:
            c = 2 * s * ticks[sym] / cdf[sym] + FEE_BPS
            cost = cost.add(c / len(cdf.columns), fill_value=0.0)
        res_ts['slip'][s] = portfolio_metrics(ts_ret - cost)
    print(f'  TIME-SERIES value (per symbol, long cheap/short rich, pooled):')
    print(f'    gross PF={res_ts["gross"]["pf"]:.2f} sharpe={res_ts["gross"]["sharpe"]:.2f} '
          f'ann={res_ts["gross"]["ann_ret"]*100:.1f}% maxDD={res_ts["gross"]["maxdd"]*100:.1f}% '
          f'(n={res_ts["gross"]["n"]})')
    print(f'    cost PF: ' + '  '.join(f's{s}={res_ts["slip"][s]["pf"]:.2f}' for s in SLIP_TICKS))
    wf = res_ts['walk_forward']
    print(f'    OOS 40/20/40: train {wf["train"]["pf"]:.2f} / val {wf["validate"]["pf"]:.2f} / '
          f'OOS {wf["oos"]["pf"]:.2f} (n={wf["oos"]["n"]})')
    return {'crosssectional': res_cs, 'timeseries': res_ts}


# ======================================================================
# helpers
# ======================================================================
def _print_portfolio(name, res, slip_series):
    print(f'  [{name}] {res.get("n_symbols", "?")} symbols, {res.get("n_months", "?")} months')
    print(f'    PF (slip 0/1/2/3): ' + '  '.join(
        f's{s}={res[f"slip{s}"]["pf"]:.2f}' for s in SLIP_TICKS))
    r0 = res['slip0']
    print(f'    gross: PF={r0["pf"]:.2f} sharpe={r0["sharpe"]:.2f} '
          f'ann={r0["ann_ret"]*100:.1f}% maxDD={r0["maxdd"]*100:.1f}% net={r0["net"]*100:.1f}% (n={r0["n"]})')
    wf = res['walk_forward']
    print(f'    walk-forward 40/20/40 (gross): train PF {wf["train"]["pf"]:.2f} / '
          f'val {wf["validate"]["pf"]:.2f} / OOS {wf["oos"]["pf"]:.2f} (n={wf["oos"]["n"]})')


FAMILIES = {
    'carry': family_carry,
    'xsmom_fut': family_xsmom_futures,
    'xsmom_eq': family_xsmom_equities,
    'vol': family_vol_overlay,
    'value': family_value,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--family', default='all', choices=list(FAMILIES) + ['all'])
    ap.add_argument('--quick', action='store_true')
    args = ap.parse_args()

    report = {'fee_bps': FEE_BPS, 'generated_at': pd.Timestamp.utcnow().isoformat()}
    fams = list(FAMILIES) if args.family == 'all' else [args.family]
    for f in fams:
        try:
            r = FAMILIES[f]()
            if r is not None:
                report[f] = r
        except Exception as e:
            import traceback
            print(f'[{f}] FAILED: {e}')
            traceback.print_exc()
            report[f] = {'error': f'{type(e).__name__}: {e}'}

    with open(RESULTS_FILE, 'w') as fh:
        json.dump(report, fh, indent=2, default=_json_default)
    print(f'\nSaved -> {RESULTS_FILE}')


def _json_default(o):
    if isinstance(o, (pd.Timestamp,)):
        return str(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    return str(o)


if __name__ == '__main__':
    main()
