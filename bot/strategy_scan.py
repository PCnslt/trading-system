"""Short-horizon (intraday → a few days) strategy scanner.

Scans 4 strategies across ES=F, SPY, QQQ, TQQQ, SQQQ on daily OHLCV
(yfinance, free), 2015→present. Trades close within 1-5 days.

Strategies (all long AND short unless noted, close-to-close, NO lookahead):
  a. Donchian/ATR breakout  — close > 20d-high (long) / < 20d-low (short),
                             exit 2*ATR stop, opposite breakout, or max 5 days.
  b. RSI(2) mean-reversion (Connors) — RSI(2)<10 long / >90 short,
                             exit RSI(2)>70 / <30, or max 5 days.
  c. Fast/slow MA crossover — 5/20 SMA crossover momentum, exit opposite
                             cross or max 5 days.
  d. Bollinger reversal     — close outside band, enter toward mean,
                             exit at middle band (SMA20) or max 5 days.

Costs: 0.5% round-trip slippage (0.25% each side). All-in 1x, no leverage.

Metrics per strategy/ticker: trades, win rate, profit factor, CAGR, MaxDD,
avg hold days. Then walk-forward (60% train / 40% test) on the best strategy
by full-period profit factor, reporting in-sample and out-of-sample PF.

Results are also written to bot/strategy_scan_results.json for cron/summary.
"""
import json
import os

import numpy as np
import pandas as pd
import yfinance as yf

SLIP = 0.005          # 0.5% round-trip
MAX_HOLD = 5          # max holding period (days) for short-term exits
TICKERS = ['ES=F', 'SPY', 'QQQ', 'TQQQ', 'SQQQ']
START = '2015-01-01'

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(HERE, 'strategy_scan_results.json')


# ===== indicators (vectorized, no lookahead) =====
def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=2):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(50.0)


def bollinger(close, n=20, k=2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid, mid + k * sd, mid - k * sd


# ===== strategy signal generators: return a position Series (+1/0/-1) =====
# position[t] is established at close of day t (info <= t), earns return of t+1.
def sig_donchian(df, lookback=20, stop_atr=2.0, hold=MAX_HOLD):
    c, h, l = df['Close'], df['High'], df['Low']
    don_hi = h.rolling(lookback).max().shift(1)
    don_lo = l.rolling(lookback).min().shift(1)
    atr = wilder_atr(h, l, c)
    pos = pd.Series(0.0, index=df.index)
    p, entry_i, entry_px, stop = 0, 0, np.nan, np.nan
    for i in range(len(df)):
        ci, hi, li = c.iloc[i], h.iloc[i], l.iloc[i]
        if p == 0:
            if ci > don_hi.iloc[i] and not np.isnan(don_hi.iloc[i]):
                p, entry_i, entry_px = 1, i, ci
                stop = ci - stop_atr * atr.iloc[i]
            elif ci < don_lo.iloc[i] and not np.isnan(don_lo.iloc[i]):
                p, entry_i, entry_px = -1, i, ci
                stop = ci + stop_atr * atr.iloc[i]
        else:
            if i - entry_i >= hold:                                   # time stop
                p = 0
            elif p == 1 and ci <= stop:                               # close-based ATR stop
                p = 0
            elif p == -1 and ci >= stop:
                p = 0
            elif p == 1 and ci < don_lo.iloc[i] and not np.isnan(don_lo.iloc[i]):  # opposite breakout
                p, entry_i, entry_px = -1, i, ci
                stop = ci + stop_atr * atr.iloc[i]
            elif p == -1 and ci > don_hi.iloc[i] and not np.isnan(don_hi.iloc[i]):
                p, entry_i, entry_px = 1, i, ci
                stop = ci - stop_atr * atr.iloc[i]
        pos.iloc[i] = p
    return pos


def sig_rsi2(df, lo=10.0, hi=90.0, exit_hi=70.0, exit_lo=30.0, hold=MAX_HOLD):
    c = df['Close']
    r = rsi(c, 2)
    pos = pd.Series(0.0, index=df.index)
    p, entry_i = 0, 0
    for i in range(len(df)):
        ri = r.iloc[i]
        if p == 0:
            if ri < lo:
                p, entry_i = 1, i
            elif ri > hi:
                p, entry_i = -1, i
        else:
            if i - entry_i >= hold:
                p = 0
            elif p == 1 and ri > exit_hi:
                p = 0
            elif p == -1 and ri < exit_lo:
                p = 0
        pos.iloc[i] = p
    return pos


def sig_ma_cross(df, fast=5, slow=20, hold=MAX_HOLD):
    c = df['Close']
    f = c.rolling(fast).mean()
    s = c.rolling(slow).mean()
    pos = pd.Series(0.0, index=df.index)
    p, entry_i = 0, 0
    for i in range(len(df)):
        fi, si = f.iloc[i], s.iloc[i]
        if p == 0:
            if not (np.isnan(fi) or np.isnan(si)):
                if fi > si:
                    p, entry_i = 1, i
                elif fi < si:
                    p, entry_i = -1, i
        else:
            if i - entry_i >= hold:
                p = 0
            elif p == 1 and fi < si:
                p, entry_i = -1, i
            elif p == -1 and fi > si:
                p, entry_i = 1, i
        pos.iloc[i] = p
    return pos


def sig_bollinger(df, n=20, k=2.0, hold=MAX_HOLD):
    c = df['Close']
    mid, upper, lower = bollinger(c, n, k)
    pos = pd.Series(0.0, index=df.index)
    p, entry_i = 0, 0
    for i in range(len(df)):
        ci, mi, ui, li = c.iloc[i], mid.iloc[i], upper.iloc[i], lower.iloc[i]
        if np.isnan(mi):
            pos.iloc[i] = 0
            continue
        if p == 0:
            if ci < li:                 # close below lower band → long (mean up)
                p, entry_i = 1, i
            elif ci > ui:               # close above upper band → short (mean down)
                p, entry_i = -1, i
        else:
            if i - entry_i >= hold:
                p = 0
            elif p == 1 and ci >= mi:   # reverted to mean → take profit
                p = 0
            elif p == -1 and ci <= mi:
                p = 0
        pos.iloc[i] = p
    return pos


STRATEGIES = [
    ('Donchian/ATR breakout', sig_donchian),
    ('RSI(2) mean-reversion', sig_rsi2),
    ('MA 5/20 crossover', sig_ma_cross),
    ('Bollinger reversal', sig_bollinger),
]


# ===== engine =====
def _extract_trades(pos, close, index):
    trades = []
    p, entry_px, entry_i = 0, np.nan, None
    for i in range(len(pos)):
        pi = int(pos.iloc[i])
        ci = close.iloc[i]
        if p == 0 and pi != 0:
            p, entry_px, entry_i = pi, ci, i
        elif p != 0 and pi != p:
            r = (ci / entry_px - 1) * p - SLIP
            trades.append({'ret': r, 'days': i - entry_i, 'dir': p})
            if pi == 0:
                p = 0
            else:                       # flip → new position same bar
                p, entry_px, entry_i = pi, ci, i
    if p != 0:                          # close open position at series end
        r = (close.iloc[-1] / entry_px - 1) * p - SLIP
        trades.append({'ret': r, 'days': len(pos) - 1 - entry_i, 'dir': p})
    return trades


def metrics(pos, df):
    close = df['Close']
    ret = close.pct_change().fillna(0.0)
    strat = (pos.shift(1).fillna(0.0) * ret)
    turnover = pos.diff().abs().fillna(0.0)
    cost = (SLIP / 2) * turnover
    net = (strat - cost).fillna(0.0)
    equity = (1.0 + net).cumprod()
    n = len(close)
    cagr = equity.iloc[-1] ** (252.0 / n) - 1.0
    maxdd = (equity / equity.cummax() - 1.0).min()
    trades = _extract_trades(pos, close, df.index)
    if not trades:
        return {'trades': 0, 'winrate': 0.0, 'pf': 0.0, 'cagr': cagr,
                'maxdd': maxdd, 'avg_days': 0.0, 'final': float(equity.iloc[-1])}
    rets = np.array([t['ret'] for t in trades])
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.size and losses.sum() != 0 else float('inf')
    return {
        'trades': len(trades),
        'winrate': 100.0 * wins.size / len(trades),
        'pf': pf,
        'cagr': cagr,
        'maxdd': maxdd,
        'avg_days': float(np.mean([t['days'] for t in trades])),
        'final': float(equity.iloc[-1]),
    }


# ===== data =====
def get_data(ticker):
    df = yf.download(ticker, start=START, interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    return df


# ===== main =====
def main():
    # fetch each ticker once (yfinance rate-limits; 5 ticks not 20)
    data = {tk: get_data(tk) for tk in TICKERS}

    rows = []          # per (strategy, ticker)
    strat_totals = {}  # per strategy: pooled PF across tickers for ranking
    strat_pf = {name: [] for name, _ in STRATEGIES}

    print(f"{'Strategy':<22} {'Ticker':>7} {'Trades':>7} {'Win%':>6} {'PF':>7} "
          f"{'CAGR%':>8} {'MaxDD%':>8} {'AvgDays':>8}")
    print('-' * 84)

    for name, fn in STRATEGIES:
        for tk in TICKERS:
            df = data[tk]
            if len(df) < 60:
                print(f"{name:<22} {tk:>7}  (insufficient data)")
                continue
            pos = fn(df)
            m = metrics(pos, df)
            rows.append({'strategy': name, 'ticker': tk, **m})
            strat_pf[name].append(m['pf'])
            print(f"{name:<22} {tk:>7} {m['trades']:>7} {m['winrate']:>6.0f} "
                  f"{m['pf']:>7.2f} {m['cagr']*100:>7.1f}% {m['maxdd']*100:>7.1f}% "
                  f"{m['avg_days']:>8.1f}")

    print()
    # rank strategies by mean PF across tickers (ignore inf for ranking robustness)
    ranking = sorted(STRATEGIES, key=lambda s: np.nanmean(
        [x for x in strat_pf[s[0]] if np.isfinite(x)]) if strat_pf[s[0]] else -1, reverse=True)
    print("Strategy rank (mean PF across tickers):")
    for i, (name, _) in enumerate(ranking, 1):
        pfs = [x for x in strat_pf[name] if np.isfinite(x)]
        print(f"  {i}. {name:<22} mean PF {np.nanmean(pfs):.2f}  (n={len(pfs)})")

    best_name = ranking[0][0]
    best_fn = dict(STRATEGIES)[best_name]
    print(f"\n=== Walk-forward (60% train / 40% test) on BEST: {best_name} ===")
    wf = []
    for tk in TICKERS:
        df = data[tk]
        split = int(len(df) * 0.6)
        tr, te = df.iloc[:split], df.iloc[split:]
        m_in = metrics(best_fn(tr), tr)
        m_out = metrics(best_fn(te), te)
        wf.append({'ticker': tk, 'in_pf': m_in['pf'], 'out_pf': m_out['pf'],
                   'in_trades': m_in['trades'], 'out_trades': m_out['trades'],
                   'out_cagr': m_out['cagr'], 'out_maxdd': m_out['maxdd']})
        print(f"  {tk:>6}: in-sample PF {m_in['pf']:>7.2f} ({m_in['trades']:>3} trades) | "
              f"out-of-sample PF {m_out['pf']:>7.2f} ({m_out['trades']:>3} trades) "
              f"CAGR {m_out['cagr']*100:>5.1f}% MaxDD {m_out['maxdd']*100:>5.1f}%")

    out_pfs = [w['out_pf'] for w in wf if np.isfinite(w['out_pf'])]
    print(f"\n  BEST-strategy pooled out-of-sample PF (mean): {np.nanmean(out_pfs):.2f}")

    # persist for cron / daily summary
    payload = {
        'best_strategy': best_name,
        'rank': [n for n, _ in ranking],
        'rows': rows,
        'walk_forward': wf,
    }
    with open(RESULTS_FILE, 'w') as f:
        json.dump(payload, f, indent=2, default=float)
    print(f"\nSaved results → {RESULTS_FILE}")


if __name__ == '__main__':
    main()
