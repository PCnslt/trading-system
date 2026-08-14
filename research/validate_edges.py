#!/usr/bin/env python3
"""GATE-1 VALIDATION SUITE — promote/kill decision for the 2 live edges.

Edges under test (exact ports of the live bots' rules):
  EDGE 1 "index-LONG"  (bot/live.py, long-only, on ES/NQ/YM):
     DONCHIAN : close > prior 20d-high  -> long; FIXED 2*ATR GTC stop below
                entry (NOT trailed); exits = 5d time stop / stop hit / close
                < prior 20d-low.
     RSI2LONG : RSI(2) < 10 -> long (buy the dip); exits = RSI(2) > 70 or 5d
                time stop. NO stop order (2*ATR sizing proxy only).
  EDGE 2 "bonds fade-SHORT"  (bot/live_bondsfx.py, short-only, on ZB/ZN):
     RSI2SHORT : RSI(2) > 90 -> short; exits = RSI(2) <= 50 or 5d. NO stop.
     BBANDSHORT: close > upper(20,2.0) -> short; exits = close <= 20d mean or
                 5d. NO stop.

Honest fill model (this is the point — the owner's past defect was bad order
fulfilment):
  - Entry fills at the signal bar's CLOSE + adverse slippage (the bots compute
    at the daily close and act immediately).
  - Donchian's GTC stop is modelled INTRADAY: if a bar gaps through the stop
    (open < stop) the fill is the open; else if low <= stop the fill is the
    stop. Both + slippage.  A 'close' stop model is reported alongside for
    comparison (that is what the earlier close-to-close scans used and is why
    they overstate the stop edge).
  - Close-based exits (time stop / signal exit) fill at close + slippage.
  - One entry OR exit per bar; no double-fill.

Cost model (owner spec):
  - Fee: 1.3 bps round-trip of notional (baseline); 0 bps also reported as the
    ideal reference.
  - Slippage stress: 0 / 1 / 2 / 3 ticks per side.

Deliverables per edge: walk-forward (3 rolling OOS folds + a 40/20/40
train/validate/OOS split), parameter sensitivity, cost stress (PF/maxDD/net per
cell), regime split (trend/range, vol tercile), and a per-edge promote/kill
recommendation with the numbers.

Data: yfinance now (--source yfinance), IBKR S3 bars later (--source s3).
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(HERE, 'validate_edges_results.json')
START = '2010-01-01'

# ---- instrument specs: mult ($/point), tick ($), S3 symbol ----
# yfinance ticker -> (name, multiplier, tick, S3 symbol, edge)
SPECS = {
    'ES=F': ('ES E-mini S&P', 50.0, 0.25, 'ES', 'index'),
    'NQ=F': ('NQ E-mini Nasdaq', 20.0, 0.25, 'NQ', 'index'),
    'YM=F': ('YM E-mini Dow', 5.0, 1.0, 'YM', 'index'),
    'ZB=F': ('ZB 30yr', 1000.0, 0.03125, 'ZB', 'bonds'),
    'ZN=F': ('ZN 10yr', 1000.0, 0.015625, 'ZN', 'bonds'),
}

# default instruments per edge
EDGE_INSTRUMENTS = {
    'index': ['ES=F', 'NQ=F', 'YM=F'],
    'bonds': ['ZB=F', 'ZN=F'],
}

FEE_BPS = 0.00013        # 1.3 bps round-trip of notional (owner baseline)
SLIP_TICKS = [0, 1, 2, 3]


# ======================================================================
# indicators (vectorized, no lookahead)
# ======================================================================
def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=2):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def bollinger(close, n=20, k=2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid, mid + k * sd, mid - k * sd


def adx(h, l, c, n=14):
    up = h.diff()
    dn = -l.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


# ======================================================================
# data
# ======================================================================
def load_yfinance(tk):
    df = yf.download(tk, start=START, interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=['Open', 'High', 'Low', 'Close'])


def load_s3(sym, bucket=None):
    """Reconstruct a daily OHLCV frame from futures-bars/daily/<sym>/<date>.json."""
    import boto3
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
    bucket = bucket or os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
    region = os.getenv('AWS_REGION', 'us-east-1')
    s3 = boto3.client('s3', region_name=region)
    prefix = f'futures-bars/daily/{sym}/'
    rows = []
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            if not obj['Key'].endswith('.json'):
                continue
            r = json.loads(s3.get_object(Bucket=bucket, Key=obj['Key'])['Body'].read())
            rows.append(r)
    if not rows:
        return None
    df = pd.DataFrame(rows).sort_values('date')
    df['date'] = pd.to_datetime(df['date'])
    df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low',
                            'close': 'Close', 'volume': 'Volume'})
    df = df.set_index('date')[['Open', 'High', 'Low', 'Close']].astype(float)
    return df.dropna()


def get_data(tk, source='yfinance', bucket=None):
    if source == 's3':
        df = load_s3(SPECS[tk][3], bucket=bucket)
    else:
        df = load_yfinance(tk)
    return df


# ======================================================================
# backtest engine
# ======================================================================
def apply_slip(px, direction, ticks, tick_size):
    """Adverse slippage: long pays up on entry / down on exit; short reversed."""
    s = ticks * tick_size
    return px + s if direction == 1 else px - s


def trade_record(entry_px, entry_i, exit_px, exit_i, direction, reason,
                 mult, fee, mae, mfe):
    pnl = (exit_px - entry_px) * direction * mult - fee
    return {
        'dir': direction, 'entry': entry_px, 'exit': exit_px,
        'entry_i': int(entry_i), 'exit_i': int(exit_i), 'reason': reason,
        'pnl': pnl, 'days': int(exit_i - entry_i),
        'mae': mae, 'mfe': mfe,   # in points, signed relative to entry (direction-adjusted)
    }


def run_donchian(df, lookback=20, stop_atr=2.0, max_hold=5, mult=50.0, tick=0.25,
                 fee_bps=FEE_BPS, slip=0, stop_model='intraday'):
    """LONG-only Donchian breakout with a FIXED 2*ATR GTC stop."""
    c, h, l, o = df['Close'], df['High'], df['Low'], df['Open']
    atr = wilder_atr(h, l, c)
    don_hi = h.rolling(lookback).max().shift(1)
    don_lo = l.rolling(lookback).min().shift(1)
    warmup = lookback + 2
    trades, eq = [], []
    pos, entry_px, entry_i, stop = 0, 0.0, 0, 0.0
    cash = 0.0
    for i in range(warmup, len(df)):
        oi, ci, bar_h, bar_l = o.iloc[i], c.iloc[i], h.iloc[i], l.iloc[i]
        if pos == 0:
            if not np.isnan(don_hi.iloc[i]) and ci > don_hi.iloc[i]:
                entry_px = ci + slip * tick
                entry_i = i
                stop = ci - stop_atr * atr.iloc[i]
                pos = 1
        else:
            held = i - entry_i
            mae = (l.iloc[entry_i:i + 1].min() - entry_px)          # adverse for long
            mfe = (h.iloc[entry_i:i + 1].max() - entry_px)
            exit_px = reason = None
            if stop_model == 'intraday':
                if oi < stop:                       # gap through stop
                    exit_px, reason = oi - slip * tick, 'stop_gap'
                elif bar_l <= stop:
                    exit_px, reason = stop - slip * tick, 'stop'
            if exit_px is None and stop_model == 'close':
                if ci <= stop:
                    exit_px, reason = ci - slip * tick, 'stop'
            if exit_px is None and held >= max_hold:
                exit_px, reason = ci - slip * tick, 'time'
            if exit_px is None and not np.isnan(don_lo.iloc[i]) and ci < don_lo.iloc[i]:
                exit_px, reason = ci - slip * tick, 'breakout'
            if exit_px is not None:
                fee = fee_bps * entry_px * mult
                trades.append(trade_record(entry_px, entry_i, exit_px, i, 1,
                                           reason, mult, fee, mae, mfe))
                cash += trades[-1]['pnl']
                pos = 0
        eq.append(cash + (ci - entry_px) * mult if pos == 1 else cash)
    return trades, pd.Series(eq, index=df.index[warmup:])


def run_rsi2_long(df, lo=10.0, hi=70.0, max_hold=5, mult=50.0, tick=0.25,
                  fee_bps=FEE_BPS, slip=0):
    """LONG-only RSI(2) buy-the-dip. NO stop order."""
    c, h, l = df['Close'], df['High'], df['Low']
    r2 = rsi(c, 2)
    warmup = 3
    trades, eq = [], []
    pos, entry_px, entry_i = 0, 0.0, 0
    cash = 0.0
    for i in range(warmup, len(df)):
        ci, bar_h, bar_l = c.iloc[i], h.iloc[i], l.iloc[i]
        if pos == 0:
            if r2.iloc[i] < lo:
                entry_px, entry_i = ci + slip * tick, i
                pos = 1
        else:
            held = i - entry_i
            mae = (l.iloc[entry_i:i + 1].min() - entry_px)
            mfe = (h.iloc[entry_i:i + 1].max() - entry_px)
            if held >= max_hold or r2.iloc[i] > hi:
                reason = 'time' if held >= max_hold else 'signal'
                fee = fee_bps * entry_px * mult
                trades.append(trade_record(entry_px, entry_i, ci - slip * tick, i, 1,
                                           reason, mult, fee, mae, mfe))
                cash += trades[-1]['pnl']
                pos = 0
        eq.append(cash + (ci - entry_px) * mult if pos == 1 else cash)
    return trades, pd.Series(eq, index=df.index[warmup:])


def run_rsi2_short(df, hi=90.0, mid=50.0, max_hold=5, mult=1000.0, tick=0.015625,
                   fee_bps=FEE_BPS, slip=0):
    """SHORT-only RSI(2) fade-the-rally. NO stop order."""
    c, h, l = df['Close'], df['High'], df['Low']
    r2 = rsi(c, 2)
    warmup = 3
    trades, eq = [], []
    pos, entry_px, entry_i = 0, 0.0, 0
    cash = 0.0
    for i in range(warmup, len(df)):
        ci, bar_h, bar_l = c.iloc[i], h.iloc[i], l.iloc[i]
        if pos == 0:
            if r2.iloc[i] > hi:
                entry_px, entry_i = ci - slip * tick, i
                pos = -1
        else:
            held = i - entry_i
            mae = (entry_px - h.iloc[entry_i:i + 1].max())      # adverse for short
            mfe = (entry_px - l.iloc[entry_i:i + 1].min())
            if held >= max_hold or r2.iloc[i] <= mid:
                reason = 'time' if held >= max_hold else 'signal'
                fee = fee_bps * entry_px * mult
                trades.append(trade_record(entry_px, entry_i, ci + slip * tick, i, -1,
                                           reason, mult, fee, mae, mfe))
                cash += trades[-1]['pnl']
                pos = 0
        eq.append(cash + (entry_px - ci) * mult if pos == -1 else cash)
    return trades, pd.Series(eq, index=df.index[warmup:])


def run_bband_short(df, n=20, k=2.0, max_hold=5, mult=1000.0, tick=0.015625,
                    fee_bps=FEE_BPS, slip=0):
    """SHORT-only Bollinger fade. NO stop order."""
    c, h, l = df['Close'], df['High'], df['Low']
    mid, upper, lower = bollinger(c, n, k)
    warmup = n + 2
    trades, eq = [], []
    pos, entry_px, entry_i = 0, 0.0, 0
    cash = 0.0
    for i in range(warmup, len(df)):
        ci, bar_h, bar_l = c.iloc[i], h.iloc[i], l.iloc[i]
        if pos == 0:
            if not np.isnan(upper.iloc[i]) and ci > upper.iloc[i]:
                entry_px, entry_i = ci - slip * tick, i
                pos = -1
        else:
            held = i - entry_i
            mae = (entry_px - h.iloc[entry_i:i + 1].max())
            mfe = (entry_px - l.iloc[entry_i:i + 1].min())
            if held >= max_hold or ci <= mid.iloc[i]:
                reason = 'time' if held >= max_hold else 'signal'
                fee = fee_bps * entry_px * mult
                trades.append(trade_record(entry_px, entry_i, ci + slip * tick, i, -1,
                                           reason, mult, fee, mae, mfe))
                cash += trades[-1]['pnl']
                pos = 0
        eq.append(cash + (entry_px - ci) * mult if pos == -1 else cash)
    return trades, pd.Series(eq, index=df.index[warmup:])


SLEEVES = {
    'DONCHIAN':  ('index', 'long',  run_donchian),
    'RSI2LONG':  ('index', 'long',  run_rsi2_long),
    'RSI2SHORT': ('bonds', 'short', run_rsi2_short),
    'BBANDSHORT':('bonds', 'short', run_bband_short),
}


# ======================================================================
# metrics
# ======================================================================
def metrics(trades, equity, n_years):
    if not trades:
        return {'trades': 0, 'winrate': 0.0, 'pf': 0.0, 'net': 0.0, 'maxdd': 0.0,
                'ret_dd': 0.0, 'avg_trade': 0.0, 'avg_hold': 0.0, 'worst_streak': 0,
                'turnover': 0.0, 'mae': 0.0, 'mfe': 0.0, 'mae_worst': 0.0, 'mfe_worst': 0.0}
    pnls = np.array([t['pnl'] for t in trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.size and losses.sum() != 0 else float('inf')
    # drawdown from the equity curve
    dd = (equity - equity.cummax())
    maxdd = dd.min()                      # most negative $ (<=0)
    net = pnls.sum()
    # worst losing streak (consecutive <=0 trades)
    streak = cur = 0
    for p in pnls:
        cur = cur + 1 if p <= 0 else 0
        streak = max(streak, cur)
    mae = float(np.mean([t['mae'] for t in trades]))
    mfe = float(np.mean([t['mfe'] for t in trades]))
    return {
        'trades': len(trades),
        'winrate': 100.0 * wins.size / len(trades),
        'pf': float(pf),
        'net': float(net),
        'maxdd': float(maxdd),
        'ret_dd': float(net / abs(maxdd)) if maxdd < 0 else (float(net) if net else 0.0),
        'avg_trade': float(np.mean(pnls)),
        'avg_hold': float(np.mean([t['days'] for t in trades])),
        'worst_streak': int(streak),
        'turnover': float(len(trades) / n_years),
        'mae': mae, 'mfe': mfe,
        'mae_worst': float(np.min([t['mae'] for t in trades])),
        'mfe_worst': float(np.max([t['mfe'] for t in trades])),
    }


def run_sleeve(df, sleeve, spec, **kw):
    """Run a sleeve on one instrument; return (trades, equity, n_years)."""
    _, mult, tick, _, _ = SPECS[spec]
    fn = SLEEVES[sleeve][2]
    trades, eq = fn(df, mult=mult, tick=tick, **kw)
    n_years = (df.index[-1] - df.index[0]).days / 365.25
    return trades, eq, n_years


def bucket_trades(trades, df_index, fold_edges):
    """Assign trades to folds by ENTRY date. fold_edges = list of (start_idx, end_idx, label)."""
    out = {label: [] for _, _, label in fold_edges}
    for t in trades:
        ei = t['entry_i']
        for s, e, label in fold_edges:
            if s <= ei < e:
                out[label].append(t)
                break
    return out


def pf_of(trades):
    if not trades:
        return 0.0, 0
    pnls = np.array([t['pnl'] for t in trades])
    w, l = pnls[pnls > 0], pnls[pnls <= 0]
    pf = w.sum() / abs(l.sum()) if l.size and l.sum() != 0 else (float('inf') if w.size else 0.0)
    return float(pf), len(trades)


def walk_forward(df, sleeve, spec, folds=3, **kw):
    n = len(df)
    warmup = 25
    edge_idx = [warmup] + [warmup + int((n - warmup) * f / folds) for f in range(1, folds)] + [n]
    fold_edges = [(edge_idx[i], edge_idx[i + 1], f'fold{i+1}') for i in range(folds)]
    trades, eq, n_years = run_sleeve(df, sleeve, spec, **kw)
    buckets = bucket_trades(trades, df.index, fold_edges)
    rows = {}
    pooled_oos = []
    for label in [f'fold{i+1}' for i in range(folds)]:
        b = buckets[label]
        pf, nt = pf_of(b)
        rows[label] = {'pf': pf, 'trades': nt}
        pooled_oos.extend(b)
    poos_pf, poos_nt = pf_of(pooled_oos)
    # train = trades before the last fold start (in-sample anchor)
    train = [t for t in trades if t['entry_i'] < edge_idx[-2]]
    tr_pf, tr_nt = pf_of(train)
    return {
        'folds': rows, 'pooled_oos_pf': poos_pf, 'pooled_oos_trades': poos_nt,
        'train_pf': tr_pf, 'train_trades': tr_nt,
    }


def split_40_20_40(df, sleeve, spec, **kw):
    n = len(df)
    warmup = 25
    a = warmup + int((n - warmup) * 0.4)
    b = warmup + int((n - warmup) * 0.6)
    edges = [(warmup, a, 'train'), (a, b, 'validate'), (b, n, 'oos')]
    trades, eq, n_years = run_sleeve(df, sleeve, spec, **kw)
    buckets = bucket_trades(trades, df.index, edges)
    return {label: {'pf': pf_of(buckets[label])[0], 'trades': pf_of(buckets[label])[1]}
            for label in ('train', 'validate', 'oos')}


def cost_stress(df, sleeve, spec, fee_levels=(0.0, FEE_BPS), slip_ticks=SLIP_TICKS, **kw):
    """PF / maxDD / net for each (fee, slippage) cell."""
    table = {}
    for fee in fee_levels:
        for s in slip_ticks:
            trades, eq, n_years = run_sleeve(df, sleeve, spec, fee_bps=fee, slip=s, **kw)
            m = metrics(trades, eq, n_years)
            table[f'fee{fee:.5f}_slip{s}'] = {
                'fee_bps': fee, 'slip_ticks': s,
                'pf': m['pf'], 'maxdd': m['maxdd'], 'net': m['net'],
                'trades': m['trades'], 'winrate': m['winrate'],
            }
    return table


def regime_analysis(df, sleeve, spec, **kw):
    """Split trades by ADX (trend/range) and by ATR vol tercile at entry."""
    c, h, l = df['Close'], df['High'], df['Low']
    a = adx(h, l, c)
    atr = wilder_atr(h, l, c)
    atrp = atr / c
    # vol tercile thresholds (pooled)
    lo_t, hi_t = atrp.quantile(0.3333), atrp.quantile(0.6667)
    trades, eq, n_years = run_sleeve(df, sleeve, spec, **kw)
    trend = [t for t in trades if not np.isnan(a.iloc[t['entry_i']]) and a.iloc[t['entry_i']] > 25]
    rng = [t for t in trades if not np.isnan(a.iloc[t['entry_i']]) and a.iloc[t['entry_i']] <= 25]
    def vol_bucket(cond):
        return [t for t in trades if cond(atrp.iloc[t['entry_i']])]
    high_v = vol_bucket(lambda x: not np.isnan(x) and x > hi_t)
    low_v = vol_bucket(lambda x: not np.isnan(x) and x <= lo_t)
    mid_v = vol_bucket(lambda x: not np.isnan(x) and lo_t < x <= hi_t)
    def summ(ts):
        pf, nt = pf_of(ts)
        wr = 100.0 * np.mean([t['pnl'] > 0 for t in ts]) if ts else 0.0
        return {'pf': pf, 'trades': nt, 'winrate': wr}
    return {
        'trend': summ(trend), 'range': summ(rng),
        'high_vol': summ(high_v), 'mid_vol': summ(mid_v), 'low_vol': summ(low_v),
    }


def daily_pnl_series(df, sleeve, spec, **kw):
    """Daily $ P&L series (mark-to-market) for correlation."""
    trades, eq, n_years = run_sleeve(df, sleeve, spec, **kw)
    return eq.diff().fillna(0.0)


# ======================================================================
# parameter sensitivity
# ======================================================================
def param_sweep(df, sleeve, spec, param, values, **kw):
    out = {}
    for v in values:
        try:
            trades, eq, n_years = run_sleeve(df, sleeve, spec, **{param: v}, **kw)
            m = metrics(trades, eq, n_years)
            out[str(v)] = {'pf': m['pf'], 'net': m['net'], 'maxdd': m['maxdd'],
                           'trades': m['trades'], 'winrate': m['winrate']}
        except Exception as e:  # noqa: BLE001
            out[str(v)] = {'error': str(e)}
    return out


# ======================================================================
# recommendation
# ======================================================================
def recommend(edge_name, sleeves_detail):
    """Combine sleeve numbers into an edge-level promote/hold/kill."""
    # skip internal underscore keys (e.g. _corr_matrix, _composite)
    sleeves = [(n, d) for n, d in sleeves_detail.items() if not n.startswith('_')]
    verdicts = []
    for name, d in sleeves:
        oos_pf = d.get('oos_pf', 0.0)      # 40/20/40 last-40% out-of-sample PF
        oos_n = d.get('oos_trades', 0)
        c1 = d.get('cost_pf_1tick', 0.0)
        c2 = d.get('cost_pf_2tick', 0.0)
        thin = oos_n < 30
        if oos_pf >= 1.2 and c2 >= 1.0 and not thin:
            v = 'promote'
        elif oos_pf < 1.0 or c1 < 1.0 or thin:
            v = 'kill'
        else:
            v = 'hold'
        verdicts.append((name, v))
    vs = [v for _, v in verdicts]
    if all(v == 'promote' for v in vs):
        rec = 'PROMOTE'
    elif all(v == 'kill' for v in vs):
        rec = 'KILL'
    elif any(v == 'kill' for v in vs) and not any(v == 'promote' for v in vs):
        rec = 'KILL'
    else:
        rec = 'HOLD'       # mixed / needs refinement
    return rec, verdicts


# ======================================================================
# main
# ======================================================================
def fmt_pf(pf):
    return ' inf' if pf == float('inf') else f'{pf:6.2f}'


def run_edge(dfs, edge, sleeve_names, source):
    """Run the full validation battery for one edge and return a report dict."""
    # representative instrument for correlation
    rep = EDGE_INSTRUMENTS[edge][0]
    detail = {}
    corr_series = {}
    for sleeve in sleeve_names:
        d = {}
        # pooled across the edge's instruments (baseline params)
        pooled = []
        for tk in EDGE_INSTRUMENTS[edge]:
            if dfs.get(tk) is None:
                continue
            trades, eq, n_years = run_sleeve(dfs[tk], sleeve, tk)
            pooled.extend(trades)
        p_pf, p_nt = pf_of(pooled)
        d['pooled_pf'] = p_pf
        d['pooled_trades'] = p_nt

        # walk-forward on the representative instrument
        wf = walk_forward(dfs[rep], sleeve, rep)
        d['pooled_oos_pf'] = wf['pooled_oos_pf']
        d['pooled_oos_trades'] = wf['pooled_oos_trades']
        d['walk_forward'] = wf
        sp = split_40_20_40(dfs[rep], sleeve, rep)
        d['split_40_20_40'] = sp
        d['oos_pf'] = sp['oos']['pf']
        d['oos_trades'] = sp['oos']['trades']
        d['validate_pf'] = sp['validate']['pf']

        # cost stress on the representative instrument
        cs = cost_stress(dfs[rep], sleeve, rep)
        d['cost_stress'] = cs
        d['cost_pf_2tick'] = cs[f'fee{FEE_BPS:.5f}_slip2']['pf']
        d['cost_pf_0tick'] = cs['fee0.00000_slip0']['pf']
        d['cost_pf_1tick'] = cs[f'fee{FEE_BPS:.5f}_slip1']['pf']
        d['cost_pf_3tick'] = cs[f'fee{FEE_BPS:.5f}_slip3']['pf']

        # full metrics (baseline, representative instrument)
        trades, eq, n_years = run_sleeve(dfs[rep], sleeve, rep)
        d['metrics'] = metrics(trades, eq, n_years)

        # regime
        d['regime'] = regime_analysis(dfs[rep], sleeve, rep)

        # param sweep
        if sleeve == 'DONCHIAN':
            d['sweep_lookback'] = param_sweep(dfs[rep], sleeve, rep, 'lookback', [10, 20, 30])
            d['sweep_stop_atr'] = param_sweep(dfs[rep], sleeve, rep, 'stop_atr', [1.0, 2.0, 3.0])
            d['stop_model_close'] = {k: v for k, v in
                                     cost_stress(dfs[rep], sleeve, rep, stop_model='close').items()
                                     if k.startswith(f'fee{FEE_BPS:.5f}')}
        elif sleeve == 'RSI2LONG':
            d['sweep_lo'] = param_sweep(dfs[rep], sleeve, rep, 'lo', [5.0, 10.0, 15.0])
        elif sleeve == 'RSI2SHORT':
            d['sweep_hi'] = param_sweep(dfs[rep], sleeve, rep, 'hi', [85.0, 90.0, 95.0])
        elif sleeve == 'BBANDSHORT':
            d['sweep_n'] = param_sweep(dfs[rep], sleeve, rep, 'n', [10, 20, 30])
            d['sweep_k'] = param_sweep(dfs[rep], sleeve, rep, 'k', [1.5, 2.0, 2.5, 3.0])

        # correlation series on representative instrument
        corr_series[sleeve] = daily_pnl_series(dfs[rep], sleeve, rep)
        detail[sleeve] = d

    # correlation matrix across the edge's sleeves
    if len(corr_series) >= 2:
        m = pd.DataFrame(corr_series)
        detail['_corr_matrix'] = m.corr().round(3).to_dict()
    # composite daily $ P&L (sum of sleeves) on the representative instrument,
    # for cross-edge correlation. Stored as {date_iso: pnl}.
    if corr_series:
        comp = pd.concat(corr_series, axis=1).sum(axis=1).fillna(0.0)
        detail['_composite'] = {str(d.date()): float(v) for d, v in comp.items()}
    return detail


def build_correlation(edge_details):
    """Cross-edge correlation: index-LONG composite vs bonds-SHORT composite."""
    out = {}
    # within-edge matrices already stored; here expose cross-edge on ES vs ZN
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', default='yfinance', choices=['yfinance', 's3'])
    ap.add_argument('--quick', action='store_true', help='smoke test: index edge only, ES only')
    args = ap.parse_args()

    print(f"GATE-1 VALIDATION — source={args.source}, fee={FEE_BPS:.5f} (1.3bp), "
          f"slippage 0/1/2/3 ticks/side")
    print("=" * 100)

    edges = [('index', ['DONCHIAN', 'RSI2LONG'], 'EDGE 1 — index-LONG (Donchian + RSI2 buy-dip)'),
             ('bonds', ['RSI2SHORT', 'BBANDSHORT'], 'EDGE 2 — bonds fade-SHORT (RSI2 + Bollinger)')]
    if args.quick:
        edges = [('index', ['DONCHIAN', 'RSI2LONG'], 'EDGE 1 — index-LONG')]

    tickers = ['ES=F', 'NQ=F', 'YM=F', 'ZB=F', 'ZN=F']
    if args.quick:
        tickers = ['ES=F']

    dfs, failed = {}, []
    for tk in tickers:
        try:
            df = get_data(tk, source=args.source)
            if df is None or len(df) < 260:
                failed.append((tk, 'insufficient data'))
            else:
                dfs[tk] = df
        except Exception as e:  # noqa: BLE001
            failed.append((tk, f'{type(e).__name__}: {e}'))
    if failed:
        print("SKIPPED:", failed, "\n")

    report = {'source': args.source, 'fee_bps': FEE_BPS, 'failed': failed, 'edges': {}}
    for edge, sleeves, label in edges:
        if not any(tk in dfs for tk in EDGE_INSTRUMENTS[edge]):
            continue
        print(f"\n{label}\n" + "-" * 100)
        detail = run_edge(dfs, edge, sleeves, args.source)
        rec, verdicts = recommend(edge, detail)
        report['edges'][edge] = {'label': label, 'sleeves': sleeves,
                                 'recommendation': rec, 'sleeve_verdicts': dict(verdicts),
                                 'detail': detail}

        for sleeve in sleeves:
            d = detail[sleeve]
            m = d['metrics']
            wf = d['walk_forward']
            print(f"  [{sleeve}] trades={m['trades']} win={m['winrate']:.0f}% "
                  f"PF={fmt_pf(m['pf'])} net=${m['net']:,.0f} maxDD=${m['maxdd']:,.0f} "
                  f"ret/DD={m['ret_dd']:.2f} MAE={m['mae']:.1f}pt MFE={m['mfe']:.1f}pt "
                  f"streak={m['worst_streak']} hold={m['avg_hold']:.1f}d turn={m['turnover']:.0f}/yr")
            print(f"         pooled(all mkts) PF={fmt_pf(d['pooled_pf'])} (n={d['pooled_trades']}) | "
                  f"full-sample PF={fmt_pf(wf['pooled_oos_pf'])} (n={wf['pooled_oos_trades']})")
            print(f"         folds OOS: " + "  ".join(
                f"{k}={fmt_pf(v['pf'])}({v['trades']})" for k, v in wf['folds'].items()))
            sp = d['split_40_20_40']
            print(f"         40/20/40: train {fmt_pf(sp['train']['pf'])}/{sp['train']['trades']}  "
                  f"validate {fmt_pf(sp['validate']['pf'])}/{sp['validate']['trades']}  "
                  f"OOS {fmt_pf(sp['oos']['pf'])}/{sp['oos']['trades']}")
            # cost stress table
            print(f"         cost stress (PF / maxDD$ / net$):")
            for fee in (0.0, FEE_BPS):
                row = [d['cost_stress'][f'fee{fee:.5f}_slip{s}'] for s in SLIP_TICKS]
                cells = "  ".join(
                    f"s{s}:[{fmt_pf(r['pf'])}/{r['maxdd']:,.0f}/{r['net']:,.0f}]" for s, r in zip(SLIP_TICKS, row))
                print(f"           fee {fee*1e4:5.1f}bp  {cells}")
            rg = d['regime']
            print(f"         regime: trend {fmt_pf(rg['trend']['pf'])}(n={rg['trend']['trades']}) "
                  f"range {fmt_pf(rg['range']['pf'])}(n={rg['range']['trades']}) | "
                  f"hiVol {fmt_pf(rg['high_vol']['pf'])}(n={rg['high_vol']['trades']}) "
                  f"midVol {fmt_pf(rg['mid_vol']['pf'])}(n={rg['mid_vol']['trades']}) "
                  f"loVol {fmt_pf(rg['low_vol']['pf'])}(n={rg['low_vol']['trades']})")
            if 'stop_model_close' in d:
                # honest fill-model comparison: intraday GTC stop vs close-based stop
                ic = d['cost_stress'][f'fee{FEE_BPS:.5f}_slip1']['pf']
                cc = d['stop_model_close'][f'fee{FEE_BPS:.5f}_slip1']['pf']
                print(f"         fill model @1tick: intraday-GTC PF={fmt_pf(ic)} vs close-based PF={fmt_pf(cc)} "
                      f"(close-based overstates the stop edge)")
            if '_corr_matrix' in detail:
                print(f"         corr(matrix) = {json.dumps(detail['_corr_matrix'])}")

        print(f"  >> EDGE recommendation: {rec}  (sleeves: "
              f"{', '.join(f'{s}={v}' for s, v in verdicts)})")

    # cross-edge correlation (index-LONG composite vs bonds-SHORT composite)
    comps = {e: report['edges'][e]['detail'].get('_composite') for e in report['edges']}
    if all(comps.get(e) for e in ('index', 'bonds')):
        a = pd.Series(comps['index'], name='index_LONG')
        b = pd.Series(comps['bonds'], name='bonds_SHORT')
        both = pd.concat([a, b], axis=1).dropna()
        cc = float(both.corr().iloc[0, 1]) if len(both) > 30 else None
        report['cross_edge_corr'] = {'index_LONG_vs_bonds_SHORT': cc, 'n_days': int(len(both))}
        print(f"\nCROSS-EDGE correlation (index-LONG composite vs bonds-SHORT composite): "
              f"{cc:.3f} (n={len(both)} days)  " + ("-> genuine diversifier" if cc is not None and abs(cc) < 0.3 else
              "-> same bet" if cc is not None and cc > 0.5 else "-> modest") if cc is not None else "n/a")

    with open(RESULTS_FILE, 'w') as f:
        json.dump(report, f, indent=2, default=float)
    print(f"\nSaved -> {RESULTS_FILE}")

    try:
        from data.s3_archive import archive_scan_results
        archive_scan_results('validate-edges', report)
        print("Archived to S3 research/scan-results/validate-edges/")
    except Exception as e:  # noqa: BLE001
        print(f"S3 archive failed: {e}")


if __name__ == '__main__':
    main()
