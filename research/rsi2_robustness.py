"""RSI2-LONG robustness pass — the review's "statistically thin" gaps, filled.

Answers, on the SAME strategy the live bot runs (bot/live.py RSI2<10 long,
exit RSI2>70 or 5-day max-hold, NO stop), across the LONG sample (2000→now, so
the 2000-02 dotcom + 2008 GFC + 2022 bear are all IN-sample this time):

  1. return distribution (mean/median/skew/kurtosis/tail percentiles)
  2. bootstrap drawdown distribution (iid + block) -> expected & tail maxDD
  3. slippage stress 0/1/2/3/4/5 ticks per side (2x/3x/5x the 1-tick live assumption)
  4. entry-timing sensitivity: fill one bar later (and exit one bar later)
  5. RSI threshold sensitivity: lo x hi grid
  6. OOS-specific worst losing streak + worst $ drawdown (last 40% by entry date)
  7. per-year PF (bear-year decay check: 2008 / 2022 / 2018 / 2011)
  8. MAE/MFE excursion distribution

Reuses the exact fill model + cost convention from validate_edges.py (honest
fills: entry at signal close + adverse slip; exits at close + slip; fee 1.3bp).
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from validate_edges import (  # noqa: E402
    rsi, run_rsi2_long, load_yfinance, SPECS, FEE_BPS,
)

LONG_START = '2000-01-01'   # futures yfinance ticks start ~2000-08; we take earliest
SLIP_TICKS = [0, 1, 2, 3, 4, 5]
LO_GRID = [8.0, 9.0, 10.0, 11.0, 12.0, 15.0]
HI_GRID = [60.0, 70.0, 80.0]
N_BOOT = 5000


def pnl_distribution(trades):
    p = np.array([t['pnl'] for t in trades], dtype=float)
    if p.size == 0:
        return {}
    wins, losses = p[p > 0], p[p <= 0]
    return {
        'n': int(p.size),
        'mean': float(p.mean()),
        'median': float(np.median(p)),
        'std': float(p.std(ddof=1)) if p.size > 1 else 0.0,
        'skew': float(pd.Series(p).skew()),
        'kurtosis': float(pd.Series(p).kurt()),
        'min': float(p.min()),
        'max': float(p.max()),
        'p5': float(np.percentile(p, 5)),
        'p25': float(np.percentile(p, 25)),
        'p75': float(np.percentile(p, 75)),
        'p95': float(np.percentile(p, 95)),
        'winrate': float((p > 0).mean()),
        'avg_win': float(wins.mean()) if wins.size else 0.0,
        'avg_loss': float(losses.mean()) if losses.size else 0.0,
        'payoff': float(wins.mean() / abs(losses.mean())) if wins.size and losses.size else 0.0,
    }


def maxdd_from_pnls(pnls):
    eq = np.cumsum(np.concatenate([[0.0], pnls]))
    return (eq - np.maximum.accumulate(eq)).min()


def bootstrap_maxdd(trades, n_iter=N_BOOT, block=None, seed=0):
    p = np.array([t['pnl'] for t in trades], dtype=float)
    rng = np.random.default_rng(seed)
    dds = np.empty(n_iter)
    n = p.size
    for it in range(n_iter):
        if block:
            n_blocks = int(np.ceil(n / block))
            starts = rng.integers(0, n, size=n_blocks)
            s = np.concatenate([p[s:s + block] for s in starts])[:n]
        else:
            s = rng.choice(p, size=n, replace=True)
        dds[it] = maxdd_from_pnls(s)
    return {
        'mean': float(dds.mean()),
        'median': float(np.median(dds)),
        'p50': float(np.percentile(dds, 50)),
        'p90': float(np.percentile(dds, 90)),
        'p95': float(np.percentile(dds, 95)),
        'p99': float(np.percentile(dds, 99)),
        'worst': float(dds.min()),
    }


def run_late(df, lo=10.0, hi=70.0, max_hold=5, mult=50.0, tick=0.25,
             fee_bps=FEE_BPS, slip=0, entry_lag=0, exit_lag=0):
    """run_rsi2_long variant with fill lags (entry_lag/exit_lag bars late)."""
    c, h, l = df['Close'], df['High'], df['Low']
    r2 = rsi(c, 2)
    warmup = 3
    trades = []
    pos, entry_px, entry_i = 0, 0.0, 0
    n = len(df)
    for i in range(warmup, n):
        ci = c.iloc[i]
        if pos == 0:
            ei = i + entry_lag
            if ei < n and r2.iloc[i] < lo:
                entry_px = c.iloc[ei] + slip * tick
                entry_i = ei
                pos = 1
        else:
            held = i - entry_i
            mae = (l.iloc[entry_i:i + 1].min() - entry_px)
            mfe = (h.iloc[entry_i:i + 1].max() - entry_px)
            if held >= max_hold or r2.iloc[i] > hi:
                xi = min(i + exit_lag, n - 1)
                reason = 'time' if held >= max_hold else 'signal'
                fee = fee_bps * entry_px * mult
                pnl = (c.iloc[xi] - slip * tick - entry_px) * 1 * mult - fee
                trades.append({'pnl': pnl, 'entry_i': int(entry_i), 'exit_i': int(xi),
                               'reason': reason, 'mae': mae, 'mfe': mfe})
                pos = 0
    return trades


def per_year_pf(trades, df):
    """PF + n per calendar year of the EXIT date."""
    idx = list(df.index)
    rows = {}
    for t in trades:
        y = idx[t['exit_i']].year
        b = rows.setdefault(y, {'wins': 0.0, 'losses': 0.0, 'n': 0})
        b['n'] += 1
        if t['pnl'] > 0:
            b['wins'] += t['pnl']
        else:
            b['losses'] += abs(t['pnl'])
    out = {}
    for y in sorted(rows):
        b = rows[y]
        pf = b['wins'] / b['losses'] if b['losses'] > 0 else float('inf')
        out[y] = {'pf': round(pf, 3), 'n': b['n'], 'net': round(b['wins'] - b['losses'], 0)}
    return out


def worst_streak_and_dd(trades):
    p = [t['pnl'] for t in trades]
    streak = cur = 0
    for v in p:
        cur = cur + 1 if v <= 0 else 0
        streak = max(streak, cur)
    # worst $-drawdown over the trade sequence (chronological)
    return streak, maxdd_from_pnls(np.array(p))


def oos_slice(trades, frac=0.4):
    """Split by entry index -> last `frac` of trades (by entry date)."""
    if not trades:
        return [], []
    entry_is = sorted(set(t['entry_i'] for t in trades))
    cut = entry_is[int(len(entry_is) * (1 - frac))]
    oos = [t for t in trades if t['entry_i'] >= cut]
    ins = [t for t in trades if t['entry_i'] < cut]
    return ins, oos


def main():
    out = {}
    for sym in ['ES', 'NQ', 'YM']:
        tk = f'{sym}=F'
        mult, tick = SPECS[tk][1], SPECS[tk][2]
        try:
            import yfinance as yf
            df = yf.download(tk, start=LONG_START, interval='1d',
                             progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
        except Exception as e:
            out[sym] = {'error': str(e)}
            continue
        if df is None or df.empty:
            out[sym] = {'error': 'no data'}
            continue
        # extend to long sample (2000→) for the robustness pass
        df = df[df.index >= LONG_START]
        r = {'rows': len(df), 'start': str(df.index[0].date()),
             'end': str(df.index[-1].date()), 'mult': mult, 'tick': tick}

        # baseline: 1 tick/side = the realistic live assumption (also 0 = ideal)
        base_trades, base_eq = run_rsi2_long(df, mult=mult, tick=tick, slip=1)
        r['baseline_n'] = len(base_trades)
        r['return_distribution'] = pnl_distribution(base_trades)
        r['bootstrap_dd_iid'] = bootstrap_maxdd(base_trades, block=None)
        r['bootstrap_dd_block10'] = bootstrap_maxdd(base_trades, block=10)

        # slippage stress 0-5 ticks (2x/3x/5x the 1-tick assumption)
        r['slippage'] = {}
        for s in SLIP_TICKS:
            tr, eq = run_rsi2_long(df, mult=mult, tick=tick, slip=s)
            p = np.array([t['pnl'] for t in tr], dtype=float)
            wins, losses = p[p > 0].sum(), abs(p[p <= 0].sum())
            pf = wins / losses if losses > 0 else float('inf')
            r['slippage'][f'{s}tick'] = {
                'pf': round(pf, 3), 'net': round(p.sum(), 0),
                'maxdd': round(maxdd_from_pnls(p), 0), 'n': len(tr)}

        # entry-timing sensitivity
        r['entry_lag'] = {}
        for lag in [1, 2]:
            tr = run_late(df, mult=mult, tick=tick, slip=1, entry_lag=lag)
            p = np.array([t['pnl'] for t in tr], dtype=float)
            wins, losses = p[p > 0].sum(), abs(p[p <= 0].sum())
            pf = wins / losses if losses > 0 else float('inf')
            r['entry_lag'][f'{lag}bar'] = {
                'pf': round(pf, 3), 'net': round(p.sum(), 0),
                'maxdd': round(maxdd_from_pnls(p), 0), 'n': len(tr)}
        # exit one bar later
        tr = run_late(df, mult=mult, tick=tick, slip=1, exit_lag=1)
        p = np.array([t['pnl'] for t in tr], dtype=float)
        wins, losses = p[p > 0].sum(), abs(p[p <= 0].sum())
        pf = wins / losses if losses > 0 else float('inf')
        r['exit_lag_1bar'] = {'pf': round(pf, 3), 'net': round(p.sum(), 0),
                              'maxdd': round(maxdd_from_pnls(p), 0), 'n': len(tr)}

        # RSI threshold sensitivity (lo x hi grid)
        r['rsi_grid'] = {}
        for lo in LO_GRID:
            for hi in HI_GRID:
                tr, eq = run_rsi2_long(df, lo=lo, hi=hi, mult=mult, tick=tick, slip=1)
                p = np.array([t['pnl'] for t in tr], dtype=float)
                wins, losses = p[p > 0].sum(), abs(p[p <= 0].sum())
                pf = wins / losses if losses > 0 else float('inf')
                r['rsi_grid'][f'lo{lo:.0f}_hi{hi:.0f}'] = {
                    'pf': round(pf, 3), 'net': round(p.sum(), 0),
                    'maxdd': round(maxdd_from_pnls(p), 0), 'n': len(tr)}

        # OOS-specific worst streak + worst $ dd (last 40% by entry date)
        ins, oos = oos_slice(base_trades, frac=0.4)
        r['oos40'] = {
            'n': len(oos),
            'worst_streak': worst_streak_and_dd(oos)[0],
            'maxdd': round(worst_streak_and_dd(oos)[1], 0),
            'pf': round(
                (sum(t['pnl'] for t in oos if t['pnl'] > 0) /
                 abs(sum(t['pnl'] for t in oos if t['pnl'] <= 0))), 3)
            if any(t['pnl'] <= 0 for t in oos) else float('inf'),
        }
        r['insample_60'] = {
            'n': len(ins),
            'worst_streak': worst_streak_and_dd(ins)[0],
            'maxdd': round(worst_streak_and_dd(ins)[1], 0)}

        # per-year PF (bear-year decay)
        r['per_year'] = per_year_pf(base_trades, df)

        # MAE/MFE excursion distribution
        mae = np.array([t['mae'] for t in base_trades], dtype=float)
        mfe = np.array([t['mfe'] for t in base_trades], dtype=float)
        r['excursions'] = {
            'mae_p5': float(np.percentile(mae, 5)), 'mae_p50': float(np.percentile(mae, 50)),
            'mae_p95': float(np.percentile(mae, 95)), 'mae_worst': float(mae.min()),
            'mfe_p5': float(np.percentile(mfe, 5)), 'mfe_p50': float(np.percentile(mfe, 50)),
            'mfe_p95': float(np.percentile(mfe, 95)), 'mfe_worst': float(mfe.max())}

        out[sym] = r
        print(f"[{sym}] {len(df)} bars {r['start']}→{r['end']} · "
              f"baseline n={len(base_trades)} · OOS40 n={len(oos)}")

    with open(os.path.join(HERE, 'rsi2_robustness_results.json'), 'w') as f:
        json.dump(out, f, indent=1, default=str)
    print('\nwrote research/rsi2_robustness_results.json')


if __name__ == '__main__':
    main()
