#!/usr/bin/env python3
"""Volume-gated mean-reversion / dip-buy (queue strat-20260831-1).

Campbell, Grossman & Wang 1993, "Trading Volume and Serial Correlation in Stock
Returns" (QJE 108(4)): first-order daily autocorrelation DECLINES with volume, so a
down day on HIGH volume should bounce harder than a down day on LOW volume.

A/B test (the queue's exact question): does a volume gate (RVOL >= 1.5 / 2.0) add
>5bp/trade net vs the UNCONDITIONAL dip-buy on the surviving family?

Two dip-buy baselines are tested, both on the deployed sub-$50 universe:
  1. BROKEN-ARROW style: setup (close > rising 40MA) + trigger (close down >= 8%/10%),
     enter that day's CLOSE, exit the NEXT OPEN (1 overnight hold, no stop) -- the
     strongest overnight-hold lane in the registry (Lane 47).
  2. RSI2<5 (Lane 1): next-open entry, 2xATR(14) gap-aware stop -> 5d time stop ->
     revert (close>SMA5 | RSI2>70), via research/stock_mr_engine.py (the exact engine
     the live bot mirrors).

Volume gate: RVOL_t = volume_t / mean(volume[t-20 .. t-1])  (no lookahead: today's
volume vs the PRIOR 20 days). Gates tested at 1.5 and 2.0, applied to the signal day.

Honest fills: multiplicative 5 bps/side primary, 10 bps/side 2x stress.
net = exit*(1-bps) / (entry*(1+bps)) - 1.  IS/OOS split at 2022-01-01 (Lane-1 anchor).
"""
from __future__ import annotations

import io, os, sys, json, argparse
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
RSI2_THR = 5.0
RVOL_GATES = (1.5, 2.0)
COSTS = (0.0005, 0.0010)   # 5 bps, 10 bps per side


def load(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 300:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        df = df[df['close'] > 0]
        pc = df['close'].shift(1)
        df['ret1'] = df['close'] / pc - 1.0                    # today's close-to-close
        df['c2o'] = df['open'].shift(-1) / df['close'] - 1.0   # close -> next open
        df['next_open'] = df['open'].shift(-1)                  # exit price for close->next-open
        df['sma200'] = df['close'].rolling(200).mean()
        df['ma40'] = df['close'].rolling(40).mean()
        df['ma40_rising'] = df['ma40'] > df['ma40'].shift(1)
        df['dollar_vol'] = (df['close'] * df['volume']).rolling(20).mean()
        # volume gate: today's volume vs the PRIOR 20-day mean (no lookahead)
        df['rvol'] = df['volume'] / df['volume'].rolling(20).mean().shift(1)
        return df
    except Exception:
        return None


def stats(rets):
    """per-trade net returns -> PF / win / avg_bp / t (registry convention)."""
    r = np.asarray([x for x in rets if x == x and np.isfinite(x)], dtype=float)
    if len(r) == 0:
        return None
    w, l = r[r > 0].sum(), -r[r <= 0].sum()
    pf = w / l if l > 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 and len(r) > 1 else 0.0
    return {'n': int(len(r)), 'pf': round(pf, 3), 'win': round(float((r > 0).mean()), 3),
            'avg_bp': round(float(r.mean() * 1e4), 1), 't': round(float(t), 2)}


def net_ret(entry, exit_, bps):
    return exit_ * (1 - bps) / (entry * (1 + bps)) - 1.0


def split(rets, dates):
    isr = [r for r, d in zip(rets, dates) if d < pd.Timestamp(OOS_FROM)]
    oor = [r for r, d in zip(rets, dates) if d >= pd.Timestamp(OOS_FROM)]
    return isr, oor


def broken_arrow(data, drop, rvol_gate, bps):
    """Close->next-open dip-buy (Lane 47). Returns (all_rets, all_dates)."""
    rets, dates = [], []
    for sym, df in data.items():
        setup = (df['close'].shift(1) > df['ma40'].shift(1)) & df['ma40_rising'].shift(1)
        m = (setup & (df['ret1'] <= -drop) & df['close'].between(PRICE_LO, PRICE_HI)
             & df['c2o'].notna() & (df['dollar_vol'] > DOLLAR_VOL_MIN))
        if rvol_gate is not None:
            m = m & (df['rvol'] >= rvol_gate)
        sub = df.loc[m]
        for d, row in sub.iterrows():
            rets.append(row['next_open'] * (1 - bps) / (row['close'] * (1 + bps)) - 1.0)
            dates.append(d)
    return rets, dates


def rsi2_dip(data, rvol_gate, bps):
    """RSI2<5 next-open entry, 2xATR stop + 5d/revert (Lane 1), optional volume gate."""
    rets, dates = [], []
    for sym, df in data.items():
        gate = None
        if rvol_gate is not None:
            gate = (df['rvol'] >= rvol_gate)
        ind = E.indicators(df)
        atr14 = ind['atr14'].to_numpy()
        dv = ind['dollar_vol'] if 'dollar_vol' in ind else (df['close'] * df['volume']).rolling(20).mean()
        for t in E.run_symbol(df, sym, RSI2_THR, 'fixed', gate=gate):
            ei = t['entry_i']
            px = t['entry_price']
            if not (PRICE_LO <= px <= PRICE_HI):
                continue
            dvol = float(dv.iloc[ei]) if not np.isnan(dv.iloc[ei]) else 0.0
            if dvol < DOLLAR_VOL_MIN:
                continue
            rets.append(t['exit_price'] * (1 - bps) / (px * (1 + bps)) - 1.0)
            dates.append(t['entry_date'])
    return rets, dates


def cell(rets, dates):
    if not rets:
        return None
    isr, oor = split(rets, dates)
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
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')))['symbols']))
    if a.limit:
        syms = syms[:a.limit]
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)} symbols from S3…', flush=True)
    with ThreadPoolExecutor(max_workers=24) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)}   {min(d.index[0] for d in data.values()).date()}'
          f' .. {max(d.index[-1] for d in data.values()).date()}\n', flush=True)

    out = {}

    print('=' * 90)
    print('#1 BROKEN-ARROW dip-buy (close -> next open) — volume gate A/B')
    print('=' * 90)
    for drop in (0.08, 0.10):
        print(f'\n--- drop <= {-drop*100:.0f}% ---')
        for bps in COSTS:
            print(f'  @{bps*1e4:.0f}bps/side:')
            base = cell(*broken_arrow(data, drop, None, bps))
            print(f'    unconditional  {fmt(base["all"]) if base else "n/a"}   '
                  f'IS {fmt(base["is"]) if base else ""}   OOS {fmt(base["oos"]) if base else ""}')
            out[f'ba_drop{int(drop*100)}_base_{bps}'] = base
            for g in RVOL_GATES:
                gtd = cell(*broken_arrow(data, drop, g, bps))
                delta = (gtd['all']['avg_bp'] - base['all']['avg_bp']) if (gtd and base) else float('nan')
                print(f'    RVOL>={g:<3}     {fmt(gtd["all"]) if gtd else "n/a"}   '
                      f'IS {fmt(gtd["is"]) if gtd else ""}   OOS {fmt(gtd["oos"]) if gtd else ""}   '
                      f'Δavg={delta:+.1f}bp')
                out[f'ba_drop{int(drop*100)}_rvol{g}_{bps}'] = gtd

    print('\n' + '=' * 90)
    print('#2 RSI2<5 dip-buy (next open, 2xATR stop) — volume gate A/B')
    print('=' * 90)
    for bps in COSTS:
        print(f'\n  @{bps*1e4:.0f}bps/side:')
        base = cell(*rsi2_dip(data, None, bps))
        print(f'    unconditional  {fmt(base["all"]) if base else "n/a"}   '
              f'IS {fmt(base["is"]) if base else ""}   OOS {fmt(base["oos"]) if base else ""}')
        out[f'rsi2_base_{bps}'] = base
        for g in RVOL_GATES:
            gtd = cell(*rsi2_dip(data, g, bps))
            delta = (gtd['all']['avg_bp'] - base['all']['avg_bp']) if (gtd and base) else float('nan')
            print(f'    RVOL>={g:<3}     {fmt(gtd["all"]) if gtd else "n/a"}   '
                  f'IS {fmt(gtd["is"]) if gtd else ""}   OOS {fmt(gtd["oos"]) if gtd else ""}   '
                  f'Δavg={delta:+.1f}bp')
            out[f'rsi2_rvol{g}_{bps}'] = gtd

    json.dump(out, open(os.path.join(_ROOT, 'research', 'volume_gate_results.json'), 'w'),
              indent=1, default=str)
    print('\nwrote research/volume_gate_results.json')


if __name__ == '__main__':
    main()
