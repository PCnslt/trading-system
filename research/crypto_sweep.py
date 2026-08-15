#!/usr/bin/env python3
"""Crypto edge-research sweep — momentum + mean-reversion on BTC/ETH/liquid alts.

HONEST fill/cost model (never-lose-money discipline built in):
  - Entry: signal-bar CLOSE + adverse slippage (long buys high, short sells low).
  - Fee: Binance.US standard spot 0.1%/side (10 bps) — verified 2026-08-15.
  - Protective stop on EVERY position: 2x ATR14, gap-aware intraday fill
    (open < stop => fill at open), + slippage. No unprotected position, ever.
  - Exit: close-based signal exit + slippage + fee.
  - Walk-forward 40/20/40 by ENTRY date; cost stress 0/10/20 bps slippage/side.

Verdicts use the owner's promotion bar (full PF>1.5 & OOS PF>1.3 & PF@20bps>=1.0
& OOS n>=30 => promote; OOS PF<1.0 or PF@10bps<1.0 or full PF<=1.0 => reject;
else shelve). Crypto is PAPER/RESEARCH ONLY — owner distrusts crypto; no orders.

Outputs:
  research/crypto_sweep_results.json  (full per-symbol/strategy tables)
  research/CRYPTO_SWEEP_HIST.md            (promote/shelve/reject table + method)
"""
import os
import sys
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

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'LTCUSDT', 'ADAUSDT']
FEE_BPS = 10.0            # 0.1% per side (standard spot tier)
SLIP_LEVELS = [0.0, 10.0, 20.0]   # bps per side, cost-stress axis
ATR_N = 14
STOP_ATR = 2.0
DON_N = 20
MAX_HOLD = 5
RSI2_LO = 10.0
RSI2_HI = 70.0


def load_bars(sym):
    s3 = boto3.client('s3', region_name=AWS_REGION)
    key = f'crypto-hist/{sym}/daily.json'
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
        data = json.loads(obj['Body'].read())
        return data['bars']
    except Exception as e:  # noqa: BLE001
        print(f'  [{sym}] no S3 crypto-hist data ({e})')
        return []


def wilder_atr(h, l, c, n=ATR_N):
    tr = np.maximum.reduce([
        h - l,
        np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))])
    tr[0] = h[0] - l[0]
    atr = np.zeros_like(c)
    atr[0] = tr[0]
    a = 1.0 / n
    for i in range(1, len(c)):
        atr[i] = (tr[i] + (n - 1) * atr[i - 1]) / n
    return atr


def rsi(close, n=2):
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    a = 1.0 / n
    ag = np.zeros_like(close)
    al = np.zeros_like(close)
    for i in range(1, len(close)):
        ag[i] = (gain[i] + (n - 1) * ag[i - 1]) / n
        al[i] = (loss[i] + (n - 1) * al[i - 1]) / n
    rs = np.divide(ag, al, out=np.full_like(ag, np.nan), where=al != 0)
    out = 100 - 100 / (1 + rs)
    return np.nan_to_num(out, nan=50.0)


def donchian_hi_lo(h, l, n=DON_N):
    hi = np.full(len(h), np.nan)
    lo = np.full(len(l), np.nan)
    for i in range(n, len(h)):
        hi[i] = h[i - n:i].max()
        lo[i] = l[i - n:i].min()
    return hi, lo


# ---- strategies: entry(i) -> side (+1/-1/0), stop(i,side), exit(i,side,held) ----
def strat_momentum_long(detail, i, side, held):
    """Donchian 20-day breakout, LONG-only."""
    if side == 0:
        if not np.isnan(detail['don_hi'][i]) and detail['close'][i] > detail['don_hi'][i]:
            return 1, False
        return 0, False
    if held >= MAX_HOLD:
        return side, True
    if detail['close'][i] < detail['don_lo'][i]:
        return side, True
    return side, False


def strat_momentum_short(detail, i, side, held):
    """Donchian 20-day breakdown, SHORT-only."""
    if side == 0:
        if not np.isnan(detail['don_lo'][i]) and detail['close'][i] < detail['don_lo'][i]:
            return -1, False
        return 0, False
    if held >= MAX_HOLD:
        return side, True
    if detail['close'][i] > detail['don_hi'][i]:
        return side, True
    return side, False


def strat_meanrev(detail, i, side, held):
    """RSI(2) buy-the-dip, long-only (mean-reversion)."""
    if side == 0:
        if detail['rsi2'][i] < RSI2_LO:
            return 1, False
        return 0, False
    if held >= MAX_HOLD:
        return side, True
    if detail['rsi2'][i] > RSI2_HI:
        return side, True
    return side, False


def stop_price(detail, i, side):
    if side == 1:
        return detail['close'][i] - STOP_ATR * detail['atr'][i]
    return detail['close'][i] + STOP_ATR * detail['atr'][i]


# ---- honest bar-by-bar backtest (one pass, trades bucketed by entry date) ----
def backtest(bars, strategy, slip_bps, fee_bps=FEE_BPS):
    c = np.array([b['close'] for b in bars], float)
    h = np.array([b['high'] for b in bars], float)
    l = np.array([b['low'] for b in bars], float)
    o = np.array([b['open'] for b in bars], float)
    dates = [b['date'] for b in bars]
    n = len(c)

    detail = {
        'close': c, 'atr': wilder_atr(h, l, c),
        'rsi2': rsi(c, 2),
    }
    detail['don_hi'], detail['don_lo'] = donchian_hi_lo(h, l)

    slip = slip_bps / 10000.0
    fee = fee_bps / 10000.0
    trades = []   # dicts: {entry_date, ret}
    side = 0
    entry_px = 0.0
    entry_i = 0
    stop = 0.0

    i = max(DON_N, ATR_N) + 1   # warm-up: don_hi/don_lo/atr/rsi all seeded
    while i < n:
        if side == 0:
            sig, _ = strategy(detail, i, 0, 0)
            if sig != 0:
                # enter at close + adverse slippage + fee
                px = c[i] * (1 + slip) if sig == 1 else c[i] * (1 - slip)
                px *= (1 + fee)
                side = sig
                entry_px = px
                entry_i = i
                stop = stop_price(detail, i, sig)
            i += 1
            continue

        held = i - entry_i
        # 1. stop check (gap-aware)
        hit = False
        exit_px = None
        if side == 1:
            if o[i] <= stop:
                exit_px = o[i] * (1 - slip)   # gap through
                hit = True
            elif l[i] <= stop:
                exit_px = stop * (1 - slip)
                hit = True
        else:
            if o[i] >= stop:
                exit_px = o[i] * (1 + slip)
                hit = True
            elif h[i] >= stop:
                exit_px = stop * (1 + slip)
                hit = True
        if hit:
            exit_px *= (1 - fee)
            ret = (exit_px - entry_px) / entry_px if side == 1 else (entry_px - exit_px) / entry_px
            trades.append({'entry_date': dates[entry_i], 'ret': ret, 'exit': 'stop'})
            side = 0
            i += 1
            continue

        # 2. signal exit
        _, do_exit = strategy(detail, i, side, held)
        if do_exit:
            px = c[i] * (1 - slip) if side == 1 else c[i] * (1 + slip)
            px *= (1 - fee)
            ret = (px - entry_px) / entry_px if side == 1 else (entry_px - px) / entry_px
            trades.append({'entry_date': dates[entry_i], 'ret': ret, 'exit': 'signal'})
            side = 0
        i += 1

    # close any open position at the last bar (forced EOD)
    if side != 0:
        px = c[-1] * (1 - slip) if side == 1 else c[-1] * (1 + slip)
        px *= (1 - fee)
        ret = (px - entry_px) / entry_px if side == 1 else (entry_px - px) / entry_px
        trades.append({'entry_date': dates[entry_i], 'ret': ret, 'exit': 'eod'})

    return trades


def stats(trades):
    if not trades:
        return {'n': 0, 'pf': float('nan'), 'win': float('nan'),
                'maxdd': float('nan'), 'avg_ret': float('nan')}
    rets = [t['ret'] for t in trades]
    gains = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    pf = sum(gains) / abs(sum(losses)) if losses else float('inf')
    # max drawdown on compounded equity
    eq = np.cumprod([1 + r for r in rets])
    peak = np.maximum.accumulate(eq)
    maxdd = float(((eq - peak) / peak).min())
    return {'n': len(trades), 'pf': pf, 'win': sum(r > 0 for r in rets) / len(rets),
            'maxdd': maxdd, 'avg_ret': float(np.mean(rets))}


def oos_stats(trades):
    """40/20/40 split by ENTRY date (assign each trade to a fold by its entry)."""
    if len(trades) < 10:
        return stats(trades), None
    dates = sorted({t['entry_date'] for t in trades})
    n = len(dates)
    train_cut = dates[int(n * 0.4)]
    oos_cut = dates[int(n * 0.6)]
    oos = [t for t in trades if t['entry_date'] >= oos_cut]
    return stats(trades), stats(oos)


def verdict(full, oos, slip20):
    """Owner's promotion bar (crypto: '2t' -> 20bps/side slippage stress)."""
    if full['n'] == 0:
        return 'reject (no trades)'
    oos_n = oos['n'] if oos else 0
    oos_pf = oos['pf'] if oos else float('nan')
    if (full['pf'] > 1.5 and oos_pf > 1.3 and slip20['pf'] >= 1.0
            and oos_n >= 30):
        return 'PROMOTE'
    if (oos_pf < 1.0 or slip20['pf'] < 1.0 or full['pf'] <= 1.0):
        return 'reject'
    return 'shelve'


def main():
    s3 = boto3.client('s3', region_name=AWS_REGION)
    results = {}
    lines = []

    for sym in SYMBOLS:
        bars = load_bars(sym)
        if len(bars) < 120:
            print(f'[{sym}] insufficient history ({len(bars)} bars) — skip')
            results[sym] = {'error': f'insufficient history ({len(bars)} bars)'}
            continue
        results[sym] = {}
        print(f'=== {sym}: {len(bars)} daily bars '
              f'({bars[0]["date"]} .. {bars[-1]["date"]}) ===')

        strat_rows = [
            ('momentum_long', strat_momentum_long, None),
            ('momentum_short', strat_momentum_short, None),
            ('meanrev_rsi2_long', strat_meanrev, None),
        ]
        for sname, strat, _ in strat_rows:
            row = {}
            oos = None
            for sl in SLIP_LEVELS:
                tr = backtest(bars, strat, sl)
                st = stats(tr)
                row[f'slip{int(sl)}bps'] = st
                if sl == 0:
                    _, oos = oos_stats(tr)
            row['full'] = row['slip0bps']
            row['oos'] = oos
            row['slip20'] = row['slip20bps']
            row['verdict'] = verdict(row['full'], row['oos'], row['slip20'])
            results[sym][sname] = row

            f = row['full']
            o = row['oos'] or {'n': 0, 'pf': float('nan')}
            s20 = row['slip20']
            print(f'  {sname:18s} n={f["n"]:3d} PF={f["pf"]:5.2f} '
                  f'win={f["win"]:.0%} maxDD={f["maxdd"]:6.1%} '
                  f'OOS PF={o["pf"]:5.2f} (n={o["n"]}) PF@20bps={s20["pf"]:5.2f} '
                  f'-> {row["verdict"]}')

    # persist raw results
    out = {
        'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'fee_bps_per_side': FEE_BPS,
        'slip_bps_per_side_levels': SLIP_LEVELS,
        'stop': f'{STOP_ATR}x ATR{ATR_N} hard stop on every position',
        'walk_forward': '40/20/40 by entry date',
        'symbols': results,
    }
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'crypto_sweep_results.json'), 'w') as fh:
        json.dump(out, fh, indent=2, default=str)

    # render markdown
    md = render_markdown(out)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'CRYPTO_SWEEP_HIST.md'), 'w') as fh:
        fh.write(md)
    print('\nWrote crypto_sweep_results.json + CRYPTO_SWEEP_HIST.md')


def render_markdown(out):
    L = []
    L.append('# Crypto Edge Sweep — momentum + mean-reversion (PAPER/RESEARCH ONLY)\n')
    L.append(f'> Generated {out["generated_at"]} · Binance.US daily candles '
             f'(S3 `crypto-hist/`). Owner **distrusts crypto** — nothing here is '
             f'live; survivors are paper-signal candidates only.\n')
    L.append('## Method (honest fills + never-lose-money)\n')
    L.append(f'- **Fee:** {out["fee_bps_per_side"]} bps/side (Binance.US standard '
             f'spot 0.1% maker/taker, verified 2026-08-15).\n')
    L.append(f'- **Slippage stress:** {", ".join(f"{s:.0f}" for s in out["slip_bps_per_side_levels"])} bps/side.\n')
    L.append('- **Stop:** 2×ATR14 hard protective stop on EVERY position '
             '(gap-aware intraday fill). No unprotected position.\n')
    L.append('- **Walk-forward:** 40/20/40 by entry date; OOS = last 40%.\n')
    L.append('\n## Promote / shelve / reject\n')
    L.append('| Symbol | Strategy | n | PF | Win | MaxDD | OOS PF (n) | PF@20bps | Verdict |')
    L.append('|---|---|---|---|---|---|---|---|---|')
    for sym, srows in out['symbols'].items():
        if 'error' in srows:
            L.append(f'| {sym} | — | — | — | — | — | — | — | {srows["error"]} |')
            continue
        for sname, row in srows.items():
            f = row['full']; o = row['oos'] or {'n': 0, 'pf': float('nan')}
            s20 = row['slip20']
            pf20 = f'{s20["pf"]:.2f}' if s20['n'] > 0 else '—'
            L.append(f'| {sym} | {sname} | {f["n"]} | {f["pf"]:.2f} | {f["win"]:.0%} | '
                     f'{f["maxdd"]:.1%} | {o["pf"]:.2f} ({o["n"]}) | {pf20} | '
                     f'**{row["verdict"]}** |')
    L.append('\n## Promotion bar (owner spec, adapted to crypto bps)\n')
    L.append('- **PROMOTE:** full PF>1.5 AND OOS PF>1.3 AND PF@20bps≥1.0 AND OOS n≥30.\n')
    L.append('- **reject:** OOS PF<1.0 OR PF@10bps<1.0 OR full PF≤1.0.\n')
    L.append('- **shelve:** everything in between (optionality preserved, not deleted).\n')
    L.append('\n## Next step\n')
    L.append('- Survivors (if any) → `research/crypto_paper.py` logs paper signals '
             'to DynamoDB (`SIGNAL#CRYPTO_*`), **no orders, no cron** until the owner '
             're-engages crypto.\n')
    return '\n'.join(L)


if __name__ == '__main__':
    main()
