#!/usr/bin/env python3
"""Cross-sectional crypto momentum (relative-strength) — honest backtest.

Queue item strat-20260827-crypto-crossmom. Claim under test (Zarattini-Pagani-
Barbon "Catching Crypto Trends" SSRN 5209907 + Liu-Tsyvinski "Risks and Returns
of Cryptocurrency"): crypto momentum is a CROSS-SECTIONAL relative effect —
rank BTC/ETH/SOL/XRP/LTC/ADA by trailing 3d/5d return, LONG the top-2 / AVOID
(or short) the bottom-2, 1-3 day hold, ~weekly rebalance.

Distinct from the per-coin time-series Donchian already swept (crypto_sweep.py,
Lane 13) and the crypto weekend seasonal (Lane 56): this tests whether the
strongest coins keep outperforming the weakest over short horizons.

Honest-fill rules copied from research/crypto_weekend_backtest.py (the repo's
validated crypto pattern): entry = next bar open + adverse slippage + fee;
exit = close (+ slippage + fee) or 2x ATR14 gap-aware stop; fee = 10 bps/side
(Binance.US spot taker) + 0/10/20 bps/side slippage stress; walk-forward
40/20/40 by entry date + post-2020 split; verdict bar = OOS PF > 1.3 at base
cost AND PF >= 1.0 at 2x cost (20 bps/side slip) AND OOS n >= 30.

Data: Binance.US daily 2019-09 -> 2026-08-15 (crypto-hist/*/daily.json). SOL
starts 2020-09; XRP has a 2021-01 -> 2023-07 delisting gap (SEC lawsuit), so
the cross-section ranks only coins *present* on each signal date (a live bot
cannot trade a delisted coin). Universe size on any date = coins with a bar
there (>=4 required).

Crypto is PAPER/RESEARCH ONLY — owner distrusts crypto; no orders, ever.
"""
import os
import json
import datetime as dt

import numpy as np
import boto3
from dotenv import load_dotenv

REPO = os.path.expanduser('~/trading-system')
load_dotenv(os.path.join(REPO, '.env'))
load_dotenv()

S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

FEE_BPS = 10.0                 # 0.1% per side (Binance.US spot taker)
SLIP_LEVELS = [0.0, 10.0, 20.0]   # bps per side, cost-stress axis
ATR_N = 14
STOP_ATR = 2.0
COINS = ['BTC', 'ETH', 'SOL', 'XRP', 'LTC', 'ADA']
MIN_UNIVERSE = 4               # need at least this many coins to rank


def _s3():
    return boto3.client('s3', region_name=AWS_REGION)


def load_coin(c):
    d = json.loads(_s3().get_object(Bucket=S3_BUCKET,
                                    Key=f'crypto-hist/{c}USDT/daily.json')['Body'].read())
    bars = sorted([{'date': b['date'][:10], 'open': float(b['open']),
                    'high': float(b['high']), 'low': float(b['low']),
                    'close': float(b['close'])} for b in d['bars']],
                  key=lambda x: x['date'])
    return bars


def wilder_atr(h, l, c, n=ATR_N):
    h = np.asarray(h, float); l = np.asarray(l, float); c = np.asarray(c, float)
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = np.zeros_like(c); atr[0] = tr[0]
    a = 1.0 / n
    for i in range(1, len(c)):
        atr[i] = (tr[i] + (n - 1) * atr[i - 1]) / n
    return atr


def stats(rets):
    rets = np.asarray(rets, float)
    rets = rets[~np.isnan(rets)]
    if len(rets) == 0:
        return {'n': 0, 'pf': float('nan'), 'win': float('nan'),
                'avg_bp': float('nan'), 'median_bp': float('nan'),
                't': float('nan')}
    gains = rets[rets > 0].sum()
    losses = abs(rets[rets < 0].sum())
    pf = gains / losses if losses > 0 else float('inf')
    avg = float(rets.mean())
    t = avg / (rets.std(ddof=1) / np.sqrt(len(rets))) if len(rets) > 1 and rets.std(ddof=1) > 0 else float('nan')
    return {'n': int(len(rets)), 'pf': float(pf), 'win': float((rets > 0).mean()),
            'avg_bp': avg * 10000.0, 'median_bp': float(np.median(rets)) * 10000.0,
            't': float(t)}


def walk_forward_split(dates):
    uniq = sorted(set(dates))
    n = len(uniq)
    if n == 0:
        return None, None
    return uniq[int(n * 0.4)], uniq[int(n * 0.6)]


def build_panel(coins):
    data = {c: load_coin(c) for c in coins}
    all_dates = sorted(set(d for c in coins for b in data[c] for d in [b['date']]))
    bmap = {c: {b['date']: b for b in data[c]} for c in coins}
    # aligned matrices (NaN where a coin has no bar)
    idx = {d: i for i, d in enumerate(all_dates)}
    n = len(all_dates)
    O = np.full((n, len(coins)), np.nan)
    H = np.full((n, len(coins)), np.nan)
    L = np.full((n, len(coins)), np.nan)
    C = np.full((n, len(coins)), np.nan)
    for j, c in enumerate(coins):
        for d, b in bmap[c].items():
            i = idx[d]
            O[i, j] = b['open']; H[i, j] = b['high']
            L[i, j] = b['low']; C[i, j] = b['close']
    # ATR per coin on its own series, then align
    ATR = np.full((n, len(coins)), np.nan)
    for j, c in enumerate(coins):
        bars = data[c]
        atr = wilder_atr([b['high'] for b in bars], [b['low'] for b in bars],
                         [b['close'] for b in bars])
        for b, a in zip(bars, atr):
            ATR[idx[b['date']], j] = a
    return all_dates, O, H, L, C, ATR


def scores_at(C, i, N):
    """Trailing N-day close return for each coin at date index i (NaN where N/A)."""
    if i - N < 0:
        return np.full(C.shape[1], np.nan)
    prev = C[i - N]
    cur = C[i]
    with np.errstate(invalid='ignore'):
        return cur / prev - 1.0


def top_bottom(C, i, N, k=2, min_univ=MIN_UNIVERSE):
    s = scores_at(C, i, N)
    valid = [j for j in range(len(s)) if not np.isnan(s[j])]
    if len(valid) < min_univ:
        return None, None, len(valid)
    order = sorted(valid, key=lambda j: -s[j])
    return order[:k], order[-k:], len(valid)


def long_position_ret(i, j, all_dates, O, H, L, C, ATR, hold, slip, fee, use_stop):
    """LONG coin j entered at open of date i+1, held 'hold' days, exit close of
    date i+hold (or 2xATR gap-aware stop). Returns net fractional return or nan."""
    e = i + 1
    if e >= len(all_dates) or np.isnan(O[e, j]):
        return float('nan')
    entry = O[e, j] * (1 + slip / 10000.0) * (1 + fee / 10000.0)
    stop = entry * (1 - STOP_ATR * ATR[i, j] / C[i, j]) if use_stop and not np.isnan(ATR[i, j]) else None
    x = min(i + hold, len(all_dates) - 1)
    exit_px = None
    if stop is not None:
        for k in range(e, x + 1):
            if np.isnan(L[k, j]) or np.isnan(O[k, j]):
                continue
            if O[k, j] <= stop:
                exit_px = O[k, j] * (1 - slip / 10000.0)   # gapped through stop
                break
            if L[k, j] <= stop:
                exit_px = stop * (1 - slip / 10000.0)
                break
    if exit_px is None:
        if np.isnan(C[x, j]):
            return float('nan')
        exit_px = C[x, j] * (1 - slip / 10000.0)
    exit_px *= (1 - fee / 10000.0)
    return exit_px / entry - 1.0


def run_lane(all_dates, O, H, L, C, ATR, N, hold, rebalance, slip, use_stop=True,
             short_bottom=False, min_univ=MIN_UNIVERSE):
    """Cross-sectional momentum lane. LONG top-2 (and optionally SHORT bottom-2).
    Rebalance every 'rebalance' days, hold 'hold' days. Per-position net returns."""
    fee = FEE_BPS
    trades = []
    for i in range(len(all_dates)):
        if i % rebalance != 0:
            continue
        if i + 1 >= len(all_dates):
            continue
        top, bot, n_avail = top_bottom(C, i, N, min_univ=min_univ)
        if top is None:
            continue
        for j in top:
            r = long_position_ret(i, j, all_dates, O, H, L, C, ATR, hold, slip, fee, use_stop)
            if not np.isnan(r):
                trades.append({'entry_date': all_dates[i + 1], 'coin': COINS[j],
                               'leg': 'long', 'ret': r})
        if short_bottom:
            for j in bot:
                r = short_position_ret(i, j, all_dates, O, H, L, C, ATR, hold, slip, fee, use_stop)
                if not np.isnan(r):
                    trades.append({'entry_date': all_dates[i + 1], 'coin': COINS[j],
                                   'leg': 'short', 'ret': r})
    return trades


def short_position_ret(i, j, all_dates, O, H, L, C, ATR, hold, slip, fee, use_stop):
    """SHORT coin j: sell at open of i+1, cover at close of i+hold (or 2xATR stop)."""
    e = i + 1
    if e >= len(all_dates) or np.isnan(O[e, j]):
        return float('nan')
    entry = O[e, j] * (1 - slip / 10000.0) * (1 - fee / 10000.0)   # proceeds per unit
    stop = entry * (1 + STOP_ATR * ATR[i, j] / C[i, j]) if use_stop and not np.isnan(ATR[i, j]) else None
    x = min(i + hold, len(all_dates) - 1)
    exit_px = None
    if stop is not None:
        for k in range(e, x + 1):
            if np.isnan(H[k, j]) or np.isnan(O[k, j]):
                continue
            if O[k, j] >= stop:
                exit_px = O[k, j] * (1 + slip / 10000.0)
                break
            if H[k, j] >= stop:
                exit_px = stop * (1 + slip / 10000.0)
                break
    if exit_px is None:
        if np.isnan(C[x, j]):
            return float('nan')
        exit_px = C[x, j] * (1 + slip / 10000.0)
    exit_px *= (1 + fee / 10000.0)
    return entry / exit_px - 1.0    # positive when price fell


def diagnostic(all_dates, O, C, N, hold, min_univ=MIN_UNIVERSE):
    """Gross cross-sectional momentum spread: forward 'hold'-day close-to-close
    return of top-2 minus bottom-2 (no cost)."""
    top_rets, bot_rets, all_rets = [], [], []
    for i in range(len(all_dates)):
        x = i + hold
        if x >= len(all_dates):
            continue
        top, bot, _ = top_bottom(C, i, N, min_univ=min_univ)
        if top is None:
            continue
        fwd = C[x] / C[i] - 1.0
        tv = [fwd[j] for j in top if not np.isnan(fwd[j])]
        bv = [fwd[j] for j in bot if not np.isnan(fwd[j])]
        av = [fwd[j] for j in range(len(fwd)) if not np.isnan(fwd[j])]
        if tv and bv:
            top_rets.append(np.mean(tv)); bot_rets.append(np.mean(bv))
        if av:
            all_rets.append(np.mean(av))
    return {'top2': stats(top_rets), 'bottom2': stats(bot_rets),
            'all': stats(all_rets),
            'spread': stats([t - b for t, b in zip(top_rets, bot_rets)])}


def split_stats(trades, split='wf'):
    if not trades:
        return {'full': stats([]), 'is': stats([]), 'oos': stats([])}
    dates = [t['entry_date'] for t in trades]
    rets = [t['ret'] for t in trades]
    full = stats(rets)
    if split == 'wf':
        train_cut, oos_cut = walk_forward_split(dates)
        if oos_cut is None:
            return {'full': full, 'is': stats([]), 'oos': stats([])}
        is_r = [r for r, d in zip(rets, dates) if d < oos_cut]
        oos_r = [r for r, d in zip(rets, dates) if d >= oos_cut]
    else:  # post-2020
        is_r = [r for r, d in zip(rets, dates) if d < '2020-01-01']
        oos_r = [r for r, d in zip(rets, dates) if d >= '2020-01-01']
    return {'full': full, 'is': stats(is_r), 'oos': stats(oos_r)}


def main():
    out = {'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
           'fee_bps_per_side': FEE_BPS, 'slip_bps_per_side_levels': SLIP_LEVELS,
           'stop': f'{STOP_ATR}x ATR{ATR_N} (gap-aware)', 'universe': COINS,
           'min_universe': MIN_UNIVERSE,
           'note': 'cross-sectional rank over coins present each signal date '
                   '(SOL starts 2020-09, XRP delisted 2021-01..2023-07)',
           'diagnostic': {}, 'lane': {}}

    all_dates, O, H, L, C, ATR = build_panel(COINS)
    print('=== CROSS-SECTIONAL CRYPTO MOMENTUM (relative strength) ===')
    print(f'{len(all_dates)} common trading dates '
          f'({all_dates[0]} .. {all_dates[-1]}) over {len(COINS)} coins '
          f'({", ".join(COINS)})')
    print(f'fee={FEE_BPS}bps/side, slip stress={SLIP_LEVELS}bps/side, '
          f'stop={STOP_ATR}xATR{ATR_N}, min universe={MIN_UNIVERSE}\n')

    # 1. gross diagnostic (is there ANY cross-sectional signal?)
    print('--- GROSS diagnostic (no cost): forward H-day return top2 vs bottom2 ---')
    for N in (3, 5):
        for hold in (1, 3, 7):
            d = diagnostic(all_dates, O, C, N, hold)
            out['diagnostic'][f'N{N}_H{hold}'] = d
            sp = d['spread']
            print(f'  N={N}d H={hold}d: top2 {d["top2"]["avg_bp"]:+.1f}bp '
                  f'(n={d["top2"]["n"]}) | bot2 {d["bottom2"]["avg_bp"]:+.1f}bp | '
                  f'all {d["all"]["avg_bp"]:+.1f}bp | '
                  f'SPREAD {sp["avg_bp"]:+.1f}bp t={sp["t"]:.2f} win={sp["win"]:.0%}')

    # 2. tradeable lane (LONG top-2, honest cost)
    print('\n--- TRADEABLE lane: LONG top-2, net of fee+slip ---')
    configs = [(3, 1, 1, 'N3_H1_daily'), (5, 1, 1, 'N5_H1_daily'),
               (3, 3, 3, 'N3_H3_3d'), (5, 7, 7, 'N5_H7_weekly')]
    for N, hold, reb, tag in configs:
        out['lane'][tag] = {}
        print(f'  [{tag}] N={N}d, hold={hold}d, rebalance={reb}d:')
        for sl in SLIP_LEVELS:
            tr = run_lane(all_dates, O, H, L, C, ATR, N, hold, reb, sl, use_stop=True)
            ss = split_stats(tr, 'wf')
            out['lane'][tag][f'slip{int(sl)}bps'] = {
                'full': ss['full'], 'is': ss['is'], 'oos': ss['oos'],
                'n': ss['full']['n']}
            f = ss['full']
            print(f'    @slip{int(sl)}: n={f["n"]} PF={f["pf"]:.2f} '
                  f'IS={ss["is"]["pf"]:.2f} OOS={ss["oos"]["pf"]:.2f} '
                  f'(n={ss["oos"]["n"]}) avg={f["avg_bp"]:+.1f}bp t={f["t"]:.2f}')
        # post-2020 split at base slip
        tr0 = run_lane(all_dates, O, H, L, C, ATR, N, hold, reb, 0.0, use_stop=True)
        pp = split_stats(tr0, 'post2020')
        out['lane'][tag]['post2020'] = {'full': pp['full'], 'is': pp['is'], 'oos': pp['oos']}
        print(f'    post-2020 split @slip0: IS PF={pp["is"]["pf"]:.2f} '
              f'OOS PF={pp["oos"]["pf"]:.2f} (n={pp["oos"]["n"]}) '
              f'avg={pp["oos"]["avg_bp"]:+.1f}bp')

    # 3. long/short (short bottom-2) as a diagnostic, base slip only
    print('\n--- TRADEABLE lane (L/S): LONG top-2 + SHORT bottom-2, base slip ---')
    out['lane']['LONG_SHORT'] = {}
    for N, hold, reb, tag in [(3, 1, 1, 'N3_H1'), (5, 7, 7, 'N5_H7')]:
        tr = run_lane(all_dates, O, H, L, C, ATR, N, hold, reb, 0.0,
                      use_stop=True, short_bottom=True)
        ss = split_stats(tr, 'wf')
        out['lane']['LONG_SHORT'][tag] = {'full': ss['full'], 'is': ss['is'],
                                          'oos': ss['oos'], 'n': ss['full']['n']}
        f = ss['full']
        print(f'  [{tag}] @slip0: n={f["n"]} PF={f["pf"]:.2f} IS={ss["is"]["pf"]:.2f} '
              f'OOS={ss["oos"]["pf"]:.2f} avg={f["avg_bp"]:+.1f}bp t={f["t"]:.2f}')

    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'crypto_crossmom_results.json')
    with open(outpath, 'w') as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f'\nWrote {outpath}')


if __name__ == '__main__':
    main()
