#!/usr/bin/env python3
"""RH RSI2 lane — position-sizing & concurrency validation (queue val-20260825-position-sizing-cap).

Question: is RH_MAX_POS_PCT=0.15 with RH_MAX_POSITIONS=5 the right risk unit for the
RSI2 lane at 2xATR stops, and what is the optimal max-concurrent given RSI2 signals
cluster on down days?

Method (mirrors bot/live_equities.py exactly):
  * Universe : research/smallcap_universe_full.json (524 sub-$50 RH whole-share names).
  * Bars     : S3 ibkr/equities/daily/<sym>.parquet; keep close>0, sort by date.
  * Filters  : entry price $2-$50 AND 20d avg $volume >= $5M (candidate_backtest.py screen).
  * Signal   : RSI(2)<5 AND close>SMA200, enter NEXT OPEN (no lookahead).
  * Exit     : 2xATR(14) intraday GTC stop (gap-aware) -> 5-day time stop ->
               revert (close>SMA5 | RSI2>70). One position per symbol, no pyramiding.
               Reuses research/stock_mr_engine.py — the exact engine the live bot mirrors.
  * Sizing   : size_usd = min(1%*equity/stop_pct, pos_pct*equity), WHOLE SHARES, cash-constrained.
               (identical to bot.position_size: 1% risk by stop distance, capped at pos_pct.)
  * Cost     : 5 bps/side primary, 10 bps/side 2x stress. net = exit*(1-b)/(entry*(1+b))-1.
  * Grid     : max_positions {3,5,10,20}  x  pos_pct {5,10,15,20}%.
  * IS/OOS   : split at 2022-01-01 (lane-1 OOS anchor).

Honest metrics: per-trade equal-weight PF (edge baseline) + portfolio PF (dollar-weighted,
whole-share, $700), daily mark-to-market max drawdown, gross-exposure concentration,
and the rejection breakdown (cap vs whole-share vs cash).
"""
from __future__ import annotations

import io
import os
import sys
import json
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'research'))

import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv

import stock_mr_engine as E

load_dotenv(os.path.join(_ROOT, '.env'))

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
PRICE_LO, PRICE_HI = 2.0, 50.0
DOLLAR_VOL_MIN = 5e6
OOS_FROM = '2022-01-01'
RISK_PCT = 0.01              # 1% risk by stop distance (live RH_RISK_PCT)
RSI2_THR = 5.0
INITIAL_CAPITAL = 700.0      # RH_PAPER_CAPITAL
GRID_POS = (3, 5, 10, 20)
GRID_PCT = (0.05, 0.10, 0.15, 0.20)
COSTS = (0.0005, 0.0010)     # 5 bps, 10 bps per side


def load(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 300:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        df = df[df['close'] > 0]
        df['dollar_vol'] = (df['close'] * df['volume']).rolling(20).mean()
        return df
    except Exception:
        return None


def generate_trades(data):
    """RSI2<5 long trades per symbol, enriched with stop_pct + dollar_vol + price/liquidity filter."""
    trades = []
    for sym, df in data.items():
        ind = E.indicators(df)
        atr14 = ind['atr14'].to_numpy()
        dv = ind['dollar_vol'].to_numpy()
        for t in E.run_symbol(df, sym, RSI2_THR, 'fixed'):
            ei = t['entry_i']
            px = t['entry_price']
            stop = px - E.STOP_ATR * atr14[ei]
            stop_pct = (px - stop) / px if px > 0 else 1.0
            dvol = float(dv[ei]) if not np.isnan(dv[ei]) else 0.0
            if not (PRICE_LO <= px <= PRICE_HI):
                continue
            if dvol < DOLLAR_VOL_MIN:
                continue
            trades.append({
                'sym': sym,
                'entry_date': pd.Timestamp(t['entry_date']),
                'exit_date': pd.Timestamp(t['exit_date']),
                'entry_price': float(px),
                'exit_price': float(t['exit_price']),
                'stop_pct': float(stop_pct),
                'dollar_vol': dvol,
                'reason': t['reason'],
                'hold_days': int(t['hold_days']),
            })
    return trades


def stats_pf(rets):
    rets = np.asarray([r for r in rets if r == r], dtype=float)
    if len(rets) == 0:
        return {'n': 0, 'pf': float('nan'), 'avg_bp': float('nan'), 'win': float('nan')}
    w = rets[rets > 0].sum()
    l = -rets[rets < 0].sum()
    return {'n': int(len(rets)), 'pf': float(w / l) if l > 0 else float('inf'),
            'avg_bp': float(rets.mean() * 1e4), 'win': float((rets > 0).mean())}


def per_trade_baseline(trades, bps):
    """Equal-weight per-trade fractional return (the registry's IS/OOS PF convention)."""
    def ret(t):
        return t['exit_price'] * (1 - bps) / (t['entry_price'] * (1 + bps)) - 1.0
    all_r = [ret(t) for t in trades]
    is_r = [ret(t) for t in trades if t['entry_date'] < pd.Timestamp(OOS_FROM)]
    oos_r = [ret(t) for t in trades if t['entry_date'] >= pd.Timestamp(OOS_FROM)]
    return {'all': stats_pf(all_r), 'is': stats_pf(is_r), 'oos': stats_pf(oos_r)}


def run_portfolio(trades, max_pos, pos_pct, bps, close_map):
    """Cash-account portfolio sim: $700, whole shares, size=min(1%/stop, pos_pct%)."""
    trades = sorted(trades, key=lambda t: (t['entry_date'], -t['dollar_vol'], t['sym']))
    pending = defaultdict(list)
    for t in trades:
        pending[t['entry_date']].append(t)
    # global trading calendar = union of every symbol's dates
    calendar = sorted({d for m in close_map.values() for d in m.keys()})

    cash = INITIAL_CAPITAL
    open_pos = []
    realized = []          # (entry_date, pnl_usd)
    n_cap = n_share = n_cash = 0
    max_conc = 0
    gross_peak = 0.0
    eq_curve = []

    for d in calendar:
        # 1) close positions exiting today
        still = []
        for p in open_pos:
            if p['exit_date'] == d:
                proceeds = p['shares'] * p['exit_price'] * (1 - bps)
                cash += proceeds
                realized.append((p['entry_date'], proceeds - p['cost']))
            else:
                still.append(p)
        open_pos = still
        # 2) daily MTM equity
        eq = cash
        for p in open_pos:
            eq += p['shares'] * close_map[p['sym']].get(d, p['entry_price'])
        eq_curve.append(eq)
        max_conc = max(max_conc, len(open_pos))
        if eq > 0:
            gross_peak = max(gross_peak, (eq - cash) / eq)
        # 3) open entries today (liquidity priority, then symbol)
        for t in pending.get(d, []):
            if len(open_pos) >= max_pos:
                n_cap += 1
                continue
            eq_now = cash + sum(p['shares'] * close_map[p['sym']].get(d, p['entry_price']) for p in open_pos)
            sp = t['stop_pct']
            if sp <= 0:
                continue
            size_usd = min(RISK_PCT * eq_now / sp, pos_pct * eq_now)
            entry_net = t['entry_price'] * (1 + bps)
            shares = int(size_usd // entry_net)
            if shares < 1:
                n_share += 1
                continue
            cost = shares * entry_net
            if cost > cash + 1e-9:
                n_cash += 1
                continue
            cash -= cost
            open_pos.append({'sym': t['sym'], 'shares': shares, 'cost': cost,
                             'entry_price': t['entry_price'], 'exit_price': t['exit_price'],
                             'exit_date': t['exit_date'], 'entry_date': t['entry_date']})
        # 4) close same-day round-trips (entry & stop-out on the same bar)
        still = []
        for p in open_pos:
            if p['exit_date'] == d:
                proceeds = p['shares'] * p['exit_price'] * (1 - bps)
                cash += proceeds
                realized.append((p['entry_date'], proceeds - p['cost']))
            else:
                still.append(p)
        open_pos = still

    # force-close any residual positions at last close
    for p in open_pos:
        realized.append((p['entry_date'], p['shares'] * p['exit_price'] * (1 - bps) - p['cost']))

    pnls = [p for _, p in realized]
    w = sum(x for x in pnls if x > 0)
    l = -sum(x for x in pnls if x < 0)
    pf = w / l if l > 0 else float('inf')
    is_p = [p for d, p in realized if d < pd.Timestamp(OOS_FROM)]
    oos_p = [p for d, p in realized if d >= pd.Timestamp(OOS_FROM)]
    def _pf(x):
        ww = sum(v for v in x if v > 0); ll = -sum(v for v in x if v < 0)
        return ww / ll if ll > 0 else float('inf')
    eq = np.asarray(eq_curve, dtype=float)
    runmax = np.maximum.accumulate(eq)
    maxdd = float(((eq - runmax) / runmax).min()) if len(eq) else float('nan')
    return {
        'n_taken': len(pnls), 'n_rej_cap': n_cap, 'n_rej_share': n_share, 'n_rej_cash': n_cash,
        'max_conc': max_conc, 'gross_peak_pct': round(gross_peak * 100, 1),
        'pf': round(pf, 3), 'is_pf': round(_pf(is_p), 3), 'oos_pf': round(_pf(oos_p), 3),
        'net_usd': round(sum(pnls), 2), 'maxdd_pct': round(maxdd * 100, 2),
        'oos_n': len(oos_p), 'is_n': len(is_p),
    }


def concentration(trades):
    """How many distinct symbols enter on the same calendar day (the down-day clustering)."""
    by_day = defaultdict(int)
    for t in trades:
        by_day[t['entry_date']] += 1
    c = np.asarray(list(by_day.values()), dtype=int)
    return {
        'entry_days': int(len(c)),
        'p50_per_day': int(np.percentile(c, 50)),
        'p90_per_day': int(np.percentile(c, 90)),
        'p99_per_day': int(np.percentile(c, 99)),
        'max_per_day': int(c.max()),
        'days_ge_5': int((c >= 5).sum()),
        'days_ge_9': int((c >= 9).sum()),
        'frac_entries_on_days_ge_5': float(c[c >= 5].sum() / c.sum()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')))['symbols']))
    if a.limit:
        syms = syms[:a.limit]
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)} symbols from S3…', flush=True)
    with ThreadPoolExecutor(max_workers=24) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)}   '
          f'{min(d.index[0] for d in data.values()).date()} .. '
          f'{max(d.index[-1] for d in data.values()).date()}', flush=True)

    trades = generate_trades(data)
    print(f'  RSI2<{RSI2_THR:.0f} trades after price/liquidity screen: {len(trades)}', flush=True)

    close_map = {s: {ts: float(c) for ts, c in df['close'].items()} for s, df in data.items()}

    out = {'universe_n': len(data), 'n_trades': len(trades),
           'concentration': concentration(trades), 'baseline': {}, 'grid': {}}

    print('\n=== per-trade equal-weight PF (edge baseline, registry convention) ===')
    print(f'{"cost":>8}{"n":>7}{"PF":>7}{"win%":>7}{"avg_bp":>9}   '
          f'{"IS PF":>7}{"OOS PF":>8}{"OOS n":>7}')
    for bps in COSTS:
        b = per_trade_baseline(trades, bps)
        out['baseline'][f'{bps:.4f}'] = b
        a_, is_, oos_ = b['all'], b['is'], b['oos']
        print(f'{bps*1e4:>7.0f}bp{a_["n"]:>7}{a_["pf"]:>7.3f}{a_["win"]*100:>6.1f}%'
              f'{a_["avg_bp"]:>9.1f}   {is_["pf"]:>7.3f}{oos_["pf"]:>8.3f}{oos_["n"]:>7}')

    print('\n=== portfolio grid ($700 whole-share, cash-constrained) @5bps/side ===')
    for pos in GRID_POS:
        for pct in GRID_PCT:
            r = run_portfolio(trades, pos, pct, 0.0005, close_map)
            out['grid'][f'pos{pos}_pct{pct:.2f}'] = r
            print(f'pos={pos:>2} pct={pct*100:>3.0f}%  '
                  f'PF={r["pf"]:>6.3f}  IS={r["is_pf"]:>5.2f} OOS={r["oos_pf"]:>5.2f}  '
                  f'maxDD={r["maxdd_pct"]:>6.1f}%  net=${r["net_usd"]:>8.2f}  '
                  f'taken={r["n_taken"]:>5} rej(cap/share/cash)={r["n_rej_cap"]}/{r["n_rej_share"]}/{r["n_rej_cash"]} '
                  f'maxconc={r["max_conc"]} grossPeak={r["gross_peak_pct"]}%')

    # 2x cost stress on the LIVE cell (pos=5, pct=15%) and best-diversified cell
    print('\n=== 2x cost stress (10bps/side) ===')
    for key in ('pos5_pct0.15', 'pos10_pct0.10', 'pos20_pct0.05'):
        pos = int(key.split('_')[0][3:]); pct = float(key.split('pct')[1])
        r = run_portfolio(trades, pos, pct, 0.0010, close_map)
        out['grid'][key + '_10bps'] = r
        print(f'{key} @10bps  PF={r["pf"]:>6.3f} IS={r["is_pf"]:>5.2f} OOS={r["oos_pf"]:>5.2f} '
              f'maxDD={r["maxdd_pct"]:>6.1f}%  net=${r["net_usd"]:>8.2f}')

    with open(os.path.join(_ROOT, 'research', 'position_sizing_results.json'), 'w') as f:
        json.dump(out, f, indent=1, default=str)
    print('\nwrote research/position_sizing_results.json')


if __name__ == '__main__':
    main()
