#!/usr/bin/env python3
"""Volume LEAD-LAG cross-autocorrelation (queue strat-20260910-1).

Chordia & Swaminathan 2000, "Trading Volume and Cross-Autocorrelations in Stock
Returns" (JF 55(2)): high-turnover (high-volume) stocks LEAD low-turnover stocks
at the daily horizon -- the cross-autocorrelation of high-volume-portfolio returns
into low-volume-portfolio returns is strong and ASYMMETRIC (high->low autocorr
strong, low->high weak).

PART A -- VERIFY the core claim. Daily cross-sectional ranking of the universe by
         trailing 20d dollar turnover (close*volume) into deciles. Equal-weight
         daily returns of top-decile (high-turnover) and bottom-decile (low-turnover)
         portfolios. Report lead-lag cross-autocorrelations corr(hi[t-1],lo[t]) vs
         corr(lo[t-1],hi[t]) (claim: hi->lo significantly larger).

PART B -- TRADEABLE long-only lagged catch-up (the queue's spec): when the high-
         turnover portfolio is UP over the prior 1 day, buy the LOW-turnover
         (bottom-decile) names that have NOT yet moved (own 1-day return <= 0),
         enter next OPEN, exit after H=1/2/3 days (close) or 2xATR(14) stop. Plus
         the fast-leg control: buy HIGH-turnover names after a market up-day.

Honest fills: multiplicative 5 bps/side primary, 10 bps/side 2x stress.
net = exit*(1-bps) / (entry*(1+bps)) - 1.  IS/OOS split at 2022-01-01 (Lane-1 anchor).

Universe: research/universe_1500.json (S&P 1500, price>=2, ADV>=10M), daily bars
from S3 ibkr/equities/daily/{sym}.parquet.  Part B is vectorized over the aligned
date x symbol panel.
"""
from __future__ import annotations

import io, os, sys, json, argparse
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'research'))

import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, '.env'))

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
OOS_FROM = '2022-01-01'
COSTS = (0.0005, 0.0010)   # 5 bps, 10 bps per side
TURN_WIN = 20              # trailing dollar-turnover window


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
        df['ret1'] = df['close'] / pc - 1.0
        df['dollar_turn'] = (df['close'] * df['volume']).rolling(TURN_WIN).mean()
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift(1)).abs(),
            (df['low'] - df['close'].shift(1)).abs(),
        ], axis=1).max(axis=1)
        df['atr14'] = tr.ewm(alpha=1 / 14, adjust=False).mean()
        return df
    except Exception:
        return None


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


def build_matrices(data):
    closes, opens, lows, rets, turns, atrs = {}, {}, {}, {}, {}, {}
    for sym, df in data.items():
        closes[sym] = df['close']
        opens[sym] = df['open']
        lows[sym] = df['low']
        rets[sym] = df['ret1']
        turns[sym] = df['dollar_turn']
        atrs[sym] = df['atr14']
    C = pd.DataFrame(closes).sort_index()
    O = pd.DataFrame(opens).sort_index()
    L = pd.DataFrame(lows).sort_index()
    R = pd.DataFrame(rets).sort_index()
    T = pd.DataFrame(turns).sort_index()
    A = pd.DataFrame(atrs).sort_index()
    return C, O, L, R, T, A


def turnover_deciles(T):
    return T.rank(axis=1, pct=True).mul(10).apply(np.ceil).clip(1, 10)


def partA(R, T):
    D = turnover_deciles(T)
    hi = (D >= 10).astype(float)
    lo = (D <= 1).astype(float)
    hi_ret = (R * hi).sum(axis=1) / hi.sum(axis=1).replace(0, np.nan)
    lo_ret = (R * lo).sum(axis=1) / lo.sum(axis=1).replace(0, np.nan)
    m = hi_ret.notna() & lo_ret.notna()
    hi_ret, lo_ret = hi_ret[m], lo_ret[m]
    out = {}
    for name, a, b in [('hi->lo', hi_ret.shift(1), lo_ret),
                       ('lo->hi', lo_ret.shift(1), hi_ret),
                       ('hi->hi', hi_ret.shift(1), hi_ret),
                       ('lo->lo', lo_ret.shift(1), lo_ret)]:
        mm = a.notna() & b.notna()
        aa, bb = a[mm], b[mm]
        r = np.corrcoef(aa, bb)[0, 1] if len(aa) > 30 else float('nan')
        tt = r * np.sqrt((len(aa) - 2) / (1 - r * r)) if (len(aa) > 2 and abs(r) < 1) else float('nan')
        isr, oor = aa[aa.index < OOS_FROM], aa[aa.index >= OOS_FROM]
        o = {
            'corr': round(float(r), 4), 't': round(float(tt), 2), 'n': int(len(aa)),
            'corr_IS': round(float(np.corrcoef(isr, bb[bb.index < OOS_FROM])[0, 1]), 4) if len(isr) > 30 else None,
            'corr_OOS': round(float(np.corrcoef(oor, bb[bb.index >= OOS_FROM])[0, 1]), 4) if len(oor) > 30 else None,
        }
        out[name] = o
    return out, hi_ret, lo_ret


def _extract(ret_df, signal, entry, exit_final):
    """return (rets list, dates list) for cells where signal & prices are valid."""
    mask = signal & entry.notna() & exit_final.notna() & ret_df.notna()
    vals = ret_df.values[mask.values]
    rows, cols = np.nonzero(mask.values)
    dates = [ret_df.index[r] for r in rows]
    return list(vals), dates


def tradeable_lagged(R, T, O, L, C, A, hi_ret, H, bps):
    D = turnover_deciles(T)
    lo = (D <= 1)
    not_moved = (R <= 0)
    hi_up = hi_ret.reindex(R.index).gt(0)
    signal = (lo & not_moved).mul(hi_up, axis=0).astype(bool)
    entry = O.shift(-1)
    exit_raw = C.shift(-H)
    stop = entry - 2.0 * A
    low_min = L.rolling(H, min_periods=H).min().shift(-H)   # min low over [t+1..t+H]
    hit = low_min <= stop
    exit_final = exit_raw.where(~hit, stop)
    ret = exit_final * (1 - bps) / (entry * (1 + bps)) - 1.0
    return _extract(ret, signal, entry, exit_final)


def tradeable_fastleg(R, T, O, L, C, A, hi_ret, H, bps):
    D = turnover_deciles(T)
    hi = (D >= 10)
    moved = (R > 0)
    hi_up = hi_ret.reindex(R.index).gt(0)
    signal = (hi & moved).mul(hi_up, axis=0).astype(bool)
    entry = O.shift(-1)
    exit_raw = C.shift(-H)
    stop = entry - 2.0 * A
    low_min = L.rolling(H, min_periods=H).min().shift(-H)
    hit = low_min <= stop
    exit_final = exit_raw.where(~hit, stop)
    ret = exit_final * (1 - bps) / (entry * (1 + bps)) - 1.0
    return _extract(ret, signal, entry, exit_final)


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
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'universe_1500.json')))['symbols']))
    if a.limit:
        syms = syms[:a.limit]
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)} symbols from S3…', flush=True)
    with ThreadPoolExecutor(max_workers=24) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)}   {min(d.index[0] for d in data.values()).date()}'
          f' .. {max(d.index[-1] for d in data.values()).date()}\n', flush=True)

    C, O, L, R, T, A = build_matrices(data)
    out = {}

    print('=' * 90)
    print('PART A — lead-lag cross-autocorrelation (daily turnover deciles)')
    print('=' * 90)
    Ares, hi_ret, lo_ret = partA(R, T)
    for name, o in Ares.items():
        print(f'  {name:8s}  corr={o["corr"]:+.4f} t={o["t"]:+.2f} n={o["n"]}'
              f'   IS={o["corr_IS"]}  OOS={o["corr_OOS"]}')
    out['partA'] = Ares
    asym = Ares['hi->lo']['corr'] - Ares['lo->hi']['corr']
    print(f'  => asymmetry hi->lo MINUS lo->hi = {asym:+.4f}  (claim: strongly positive)\n')

    print('=' * 90)
    print('PART B — tradeable long-only lagged catch-up (low-turnover, not-yet-moved)')
    print('=' * 90)
    for H in (1, 2, 3):
        print(f'\n--- HOLD {H} day ---')
        for bps in COSTS:
            print(f'  @{bps*1e4:.0f}bps/side:')
            r, d = tradeable_lagged(R, T, O, L, C, A, hi_ret, H, bps)
            c = cell(r, d)
            print(f'    lagged-catchup {fmt(c["all"]) if c else "n/a"}   '
                  f'IS {fmt(c["is"]) if c else ""}   OOS {fmt(c["oos"]) if c else ""}')
            out[f'lagged_H{H}_{bps}'] = c
            rf, dfd = tradeable_fastleg(R, T, O, L, C, A, hi_ret, H, bps)
            cf = cell(rf, dfd)
            print(f'    fast-leg ctrl  {fmt(cf["all"]) if cf else "n/a"}   '
                  f'IS {fmt(cf["is"]) if cf else ""}   OOS {fmt(cf["oos"]) if cf else ""}')
            out[f'fastleg_H{H}_{bps}'] = cf

    json.dump(out, open(os.path.join(_ROOT, 'research', 'volume_leadlag_results.json'), 'w'),
              indent=1, default=str)
    print('\nwrote research/volume_leadlag_results.json')


if __name__ == '__main__':
    main()
