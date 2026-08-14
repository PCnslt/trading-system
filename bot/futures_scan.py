"""Futures-only short-horizon strategy scan — REALISTIC futures costs.

Universe: ES=F and NQ=F (liquid index futures; MES/MNQ are 1/10 size, same % returns,
so results on % returns carry over).

COST ASSUMPTION (stated exactly):
  Round-trip cost = 1.3 bps = 0.00013 of notional, applied to each completed
  trade's return. This is the user-specified "~1.3 bps per trade" figure. It is
  DELIBERATELY CONSERVATIVE vs raw IBKR commission (~$2.48 ES round trip ≈ 0.08 bps
  of ~$300k notional): the 1.3 bps intentionally bundles commissions + exchange/
  NFA fees + a slippage buffer. If anything it OVERSTATES real costs, so any edge
  that survives is real. 1x notional, no leverage (returns = index % moves).

Strategies (each tested long-only AND long+short):
  a. Donchian/ATR breakout  — close > 20d-high (long) / < 20d-low (short),
                             2*ATR stop, opposite breakout exit, max 5-day hold.
  b. RSI(2) mean-reversion   — RSI(2)<10 long / >90 short; exit RSI(2)>70 / <30, 5d.
  c. MA 5/20 crossover       — 5/20 SMA momentum; exit opposite cross or 5d.
  d. Bollinger reversal      — close outside 2σ band → mean; exit at SMA20 or 5d.
  e. ADX trend breakout      — PORTED FROM bot/live.py (PF 2.73 long-only claim):
                              Entry close > 20d-high AND close > SMA200 AND ADX>25;
                              trailing 2*ATR stop (ratcheted daily, never reversed);
                              exit close < SMA200. Short = mirrored. NO time stop.
                              Trailing stop uses intraday Low/High for stop fills
                              (gap = fill at open); SMA200 exit at close.

Walk-forward 60/40 (train/test) on the top 2 (strategy × direction) by pooled PF.

Results also written to bot/futures_scan_results.json for cron/summary.
"""
import json
import os

import numpy as np
import pandas as pd
import yfinance as yf

COST = 0.00013        # 1.3 bps round-trip, applied to returns (see docstring)
MAX_HOLD = 5          # time stop (days) for the short-horizon strategies only
STOP_ATR = 2.0
ADX_MIN = 25
TICKERS = ['ES=F', 'NQ=F']
START = '2015-01-01'

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(HERE, 'futures_scan_results.json')


# ===== indicators =====
def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx_ind(h, l, c, n=14):
    """Wilder ADX — exact port of live.py._adx."""
    up = h.diff().to_numpy()
    dn = (-l.diff()).to_numpy()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = wilder_atr(h, l, c, n)
    idx = h.index
    plus_di = 100 * pd.Series(plus_dm, index=idx).ewm(alpha=1 / n, adjust=False).mean() / tr
    minus_di = 100 * pd.Series(minus_dm, index=idx).ewm(alpha=1 / n, adjust=False).mean() / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def rsi2(close, n=2):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def bollinger(close, n=20, k=2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid, mid + k * sd, mid - k * sd


# ===== close-to-close signal generators (position series +1/0/-1) =====
def sig_donchian(df, lookback=20, stop_atr=2.0, hold=MAX_HOLD, short_ok=True):
    c, h, l = df['Close'], df['High'], df['Low']
    don_hi = h.rolling(lookback).max().shift(1)
    don_lo = l.rolling(lookback).min().shift(1)
    atr = wilder_atr(h, l, c)
    pos = pd.Series(0.0, index=df.index)
    p, entry_i, stop = 0, 0, np.nan
    for i in range(len(df)):
        ci = c.iloc[i]
        if p == 0:
            if ci > don_hi.iloc[i] and not np.isnan(don_hi.iloc[i]):
                p, entry_i = 1, i
                stop = ci - stop_atr * atr.iloc[i]
            elif short_ok and ci < don_lo.iloc[i] and not np.isnan(don_lo.iloc[i]):
                p, entry_i = -1, i
                stop = ci + stop_atr * atr.iloc[i]
        else:
            if i - entry_i >= hold:
                p = 0
            elif p == 1 and ci <= stop:
                p = 0
            elif p == -1 and ci >= stop:
                p = 0
            elif p == 1 and ci < don_lo.iloc[i] and not np.isnan(don_lo.iloc[i]):
                if short_ok:  # opposite breakout → flip
                    p, entry_i = -1, i
                    stop = ci + stop_atr * atr.iloc[i]
                else:          # long-only → exit, stay flat
                    p = 0
            elif p == -1 and ci > don_hi.iloc[i] and not np.isnan(don_hi.iloc[i]):
                if short_ok:
                    p, entry_i = 1, i
                    stop = ci - stop_atr * atr.iloc[i]
                else:
                    p = 0
        pos.iloc[i] = p
    return pos


def sig_rsi2(df, lo=10.0, hi=90.0, exit_hi=70.0, exit_lo=30.0, hold=MAX_HOLD, short_ok=True):
    c = df['Close']
    r = rsi2(c, 2)
    pos = pd.Series(0.0, index=df.index)
    p, entry_i = 0, 0
    for i in range(len(df)):
        ri = r.iloc[i]
        if p == 0:
            if ri < lo:
                p, entry_i = 1, i
            elif short_ok and ri > hi:
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


def sig_ma_cross(df, fast=5, slow=20, hold=MAX_HOLD, short_ok=True):
    c = df['Close']
    f = c.rolling(fast).mean()
    s = c.rolling(slow).mean()
    pos = pd.Series(0.0, index=df.index)
    p, entry_i = 0, 0
    for i in range(len(df)):
        fi, si = f.iloc[i], s.iloc[i]
        if np.isnan(fi) or np.isnan(si):
            pos.iloc[i] = 0
            continue
        if p == 0:
            if fi > si:
                p, entry_i = 1, i
            elif short_ok and fi < si:
                p, entry_i = -1, i
        else:
            if i - entry_i >= hold:
                p = 0
            elif p == 1 and fi < si:
                if short_ok:
                    p, entry_i = -1, i
                else:
                    p = 0
            elif p == -1 and fi > si:
                if short_ok:
                    p, entry_i = 1, i
                else:
                    p = 0
        pos.iloc[i] = p
    return pos


def sig_bollinger(df, n=20, k=2.0, hold=MAX_HOLD, short_ok=True):
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
            if ci < li:
                p, entry_i = 1, i
            elif short_ok and ci > ui:
                p, entry_i = -1, i
        else:
            if i - entry_i >= hold:
                p = 0
            elif p == 1 and ci >= mi:
                p = 0
            elif p == -1 and ci <= mi:
                p = 0
        pos.iloc[i] = p
    return pos


SIGS = {
    'donchian': sig_donchian,
    'rsi2': sig_rsi2,
    'ma_cross': sig_ma_cross,
    'bollinger': sig_bollinger,
}


# ===== trade extraction + engine =====
def extract_trades(pos, close, cost):
    trades = []
    p, entry_px, entry_i = 0, np.nan, None
    for i in range(len(pos)):
        pi = int(pos.iloc[i])
        ci = close.iloc[i]
        if p == 0 and pi != 0:
            p, entry_px, entry_i = pi, ci, i
        elif p != 0 and pi != p:
            trades.append({'ret': (ci / entry_px - 1) * p - cost, 'days': i - entry_i, 'dir': p})
            if pi == 0:
                p = 0
            else:
                p, entry_px, entry_i = pi, ci, i
    if p != 0:
        trades.append({'ret': (close.iloc[-1] / entry_px - 1) * p - cost,
                       'days': len(pos) - 1 - entry_i, 'dir': p})
    return trades


def close_to_close(pos, df, cost):
    """Position series → (net daily returns, trades) with round-trip cost via turnover."""
    close = df['Close']
    ret = close.pct_change().fillna(0.0)
    gross = pos.shift(1).fillna(0.0) * ret
    turnover = pos.diff().abs().fillna(0.0)
    net = (gross - (cost / 2) * turnover).fillna(0.0)
    return net, extract_trades(pos, close, cost)


# ===== ADX trend breakout (ported from live.py, bar-simulated w/ trailing stop) =====
def run_adx(df, direction, adx_min=ADX_MIN, stop_atr=STOP_ATR, cost=COST):
    h, l, c, o = df['High'], df['Low'], df['Close'], df['Open']
    sma200 = c.rolling(200).mean()
    don_hi = h.rolling(20).max().shift(1)
    don_lo = l.rolling(20).min().shift(1)
    atr = wilder_atr(h, l, c, 14)
    adx = adx_ind(h, l, c, 14)
    n = len(df)
    net = pd.Series(0.0, index=df.index)
    trades = []
    pos = 0
    ref = None          # mark price as of prior close (for daily MTM returns)
    entry_px = None     # actual entry price (for per-trade P&L)
    entry_i = None
    stop = None
    for i in range(n):
        ci, hi, li, oi = c.iloc[i], h.iloc[i], l.iloc[i], o.iloc[i]
        r_i = 0.0
        if pos != 0:
            last = (i == n - 1)
            stop_hit = (pos == 1 and li <= stop) or (pos == -1 and hi >= stop)
            sma_exit = (not np.isnan(sma200.iloc[i])) and (
                (pos == 1 and ci < sma200.iloc[i]) or (pos == -1 and ci > sma200.iloc[i]))
            if stop_hit:
                gap = (pos == 1 and oi < stop) or (pos == -1 and oi > stop)
                exit_px = oi if gap else stop
                reason = 'stop'
            elif sma_exit:
                exit_px = ci
                reason = 'sma'
            elif last:
                exit_px = ci
                reason = 'eod'
            else:
                exit_px = None
            if exit_px is not None:
                r_i = (exit_px / ref - 1) * pos - cost      # daily MTM realized
                trades.append({'ret': (exit_px / entry_px - 1) * pos - cost,
                               'days': i - entry_i, 'dir': pos, 'exit': reason})
                pos, ref, entry_px, stop, entry_i = 0, None, None, None, None
            else:
                r_i = (ci / ref - 1) * pos                       # mark-to-market
                if pos == 1:
                    ns = ci - stop_atr * atr.iloc[i]
                    if not np.isnan(ns) and ns > stop:
                        stop = ns                                # ratchet up only
                else:
                    ns = ci + stop_atr * atr.iloc[i]
                    if not np.isnan(ns) and ns < stop:
                        stop = ns                                # ratchet down only
                ref = ci
        else:
            if direction in ('long', 'both') and not np.isnan(don_hi.iloc[i]) \
                    and not np.isnan(sma200.iloc[i]) and not np.isnan(adx.iloc[i]) \
                    and ci > don_hi.iloc[i] and ci > sma200.iloc[i] and adx.iloc[i] > adx_min:
                pos, ref, entry_px, entry_i = 1, ci, ci, i
                stop = ci - stop_atr * atr.iloc[i]
            elif direction == 'both' and not np.isnan(don_lo.iloc[i]) \
                    and not np.isnan(sma200.iloc[i]) and not np.isnan(adx.iloc[i]) \
                    and ci < don_lo.iloc[i] and ci < sma200.iloc[i] and adx.iloc[i] > adx_min:
                pos, ref, entry_px, entry_i = -1, ci, ci, i
                stop = ci + stop_atr * atr.iloc[i]
        net.iloc[i] = r_i
    return net, trades


# ===== metrics =====
def pf_from_trades(trades):
    if not trades:
        return 0.0
    rets = np.array([t['ret'] for t in trades])
    wins, losses = rets[rets > 0], rets[rets <= 0]
    if losses.size == 0:
        return float('inf') if wins.size else 0.0
    if losses.sum() == 0:
        return float('inf')
    return wins.sum() / abs(losses.sum())


def metrics(net, trades):
    equity = (1.0 + net).cumprod()
    n = len(net)
    cagr = equity.iloc[-1] ** (252.0 / n) - 1.0 if n else 0.0
    maxdd = (equity / equity.cummax() - 1.0).min()
    if not trades:
        return {'trades': 0, 'winrate': 0.0, 'pf': 0.0, 'cagr': cagr,
                'maxdd': maxdd, 'avg_days': 0.0, 'final': float(equity.iloc[-1])}
    rets = np.array([t['ret'] for t in trades])
    wins = rets[rets > 0]
    return {
        'trades': len(trades),
        'winrate': 100.0 * wins.size / len(trades),
        'pf': pf_from_trades(trades),
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
    return df.dropna(subset=['Open', 'High', 'Low', 'Close'])


# ===== run one (strategy, direction, ticker) =====
def run_one(df, kind, direction, adx_min=ADX_MIN):
    if kind == 'adx':
        return run_adx(df, direction, adx_min=adx_min)
    sig = SIGS[kind](df, short_ok=(direction == 'both'))
    return close_to_close(sig, df, COST)


def fmt(m, flag_small=False):
    s = f"{m['trades']:>7} {m['winrate']:>6.0f} {m['pf']:>7.2f} {m['cagr']*100:>7.1f}% " \
        f"{m['maxdd']*100:>7.1f}% {m['avg_days']:>8.1f}"
    if flag_small and 0 < m['trades'] < 30:
        s += '  !small'
    return s


STRAT_ORDER = ['donchian', 'rsi2', 'ma_cross', 'bollinger', 'adx']
STRAT_NAME = {'donchian': 'Donchian/ATR', 'rsi2': 'RSI(2) MR',
              'ma_cross': 'MA 5/20', 'bollinger': 'Bollinger', 'adx': 'ADX trend'}


def main():
    data = {tk: get_data(tk) for tk in TICKERS}

    print(f"FUTURES-ONLY short-horizon scan  (cost = {COST:.5f} = 1.3 bps/round-trip of notional)")
    print(f"{'Strategy':<16} {'Ticker':>7} {'Dir':>6} {'Trades':>7} {'Win%':>6} {'PF':>7} "
          f"{'CAGR%':>8} {'MaxDD%':>8} {'AvgDays':>8}")
    print('-' * 82)

    rows = []                       # per (strategy, ticker, direction)
    combo_trades = {}               # (strategy, direction) -> pooled trades across tickers
    for kind in STRAT_ORDER:
        for direction in ('long', 'both'):
            key = (kind, direction)
            combo_trades[key] = []
            for tk in TICKERS:
                df = data[tk]
                if len(df) < 260:
                    print(f"{STRAT_NAME[kind]:<16} {tk:>7} {direction:>6}  (insufficient data)")
                    continue
                net, trades = run_one(df, kind, direction)
                m = metrics(net, trades)
                rows.append({'strategy': kind, 'ticker': tk, 'direction': direction, **m})
                combo_trades[key].extend(trades)
                print(f"{STRAT_NAME[kind]:<16} {tk:>7} {direction:>6} {fmt(m, flag_small=True)}")
        print()

    # rank (strategy, direction) by pooled PF
    def pooled_pf(key):
        return pf_from_trades(combo_trades[key])
    ranking = sorted(combo_trades.keys(), key=pooled_pf, reverse=True)
    print("Rank (pooled PF across ES=NQ):")
    for i, key in enumerate(ranking, 1):
        k, d = key
        tr = combo_trades[key]
        pf = pooled_pf(key)
        print(f"  {i}. {STRAT_NAME[k]:<16} {d:>5}  pooled PF {pf:>7.2f}  (n={len(tr)})")

    top2 = ranking[:2]
    print(f"\n=== Walk-forward 60/40 on TOP 2: "
          f"{STRAT_NAME[top2[0][0]]} {top2[0][1]} + {STRAT_NAME[top2[1][0]]} {top2[1][1]} ===")
    wf = []
    for key in top2:
        kind, direction = key
        for tk in TICKERS:
            df = data[tk]
            split = int(len(df) * 0.6)
            tr, te = df.iloc[:split], df.iloc[split:]
            m_in = metrics(*run_one(tr, kind, direction))
            m_out = metrics(*run_one(te, kind, direction))
            wf.append({'strategy': kind, 'direction': direction, 'ticker': tk,
                       'in_pf': m_in['pf'], 'in_trades': m_in['trades'],
                       'out_pf': m_out['pf'], 'out_trades': m_out['trades'],
                       'out_cagr': m_out['cagr'], 'out_maxdd': m_out['maxdd']})
            small = ' !small' if 0 < m_out['trades'] < 30 else ''
            print(f"  {STRAT_NAME[kind]:<16} {direction:>5} {tk:>7}: "
                  f"in PF {m_in['pf']:>7.2f} ({m_in['trades']:>3}t) | "
                  f"out PF {m_out['pf']:>7.2f} ({m_out['trades']:>3}t) "
                  f"CAGR {m_out['cagr']*100:>5.1f}% MaxDD {m_out['maxdd']*100:>5.1f}%{small}")

    # ADX threshold sensitivity (relaxed 25 -> 20 -> 18)
    print("\n=== ADX threshold sensitivity (trade-off: selectivity vs sample size) ===")
    for adx_min in (25, 20, 18):
        for direction in ('long', 'both'):
            for tk in TICKERS:
                df = data[tk]
                net, trades = run_one(df, 'adx', direction, adx_min=adx_min)
                m = metrics(net, trades)
                small = ' !small' if 0 < m['trades'] < 30 else ''
                print(f"  ADX>{adx_min:<3} {direction:>5} {tk:>7}: "
                      f"{m['trades']:>4}t {m['winrate']:>5.0f}% PF {m['pf']:>6.2f} "
                      f"CAGR {m['cagr']*100:>6.1f}% MaxDD {m['maxdd']*100:>6.1f}%{small}")

    payload = {
        'cost': COST,
        'tickers': TICKERS,
        'rank': [[k, d] for k, d in ranking],
        'rows': rows,
        'walk_forward': wf,
    }
    with open(RESULTS_FILE, 'w') as f:
        json.dump(payload, f, indent=2, default=float)
    print(f"\nSaved results → {RESULTS_FILE}")


if __name__ == '__main__':
    main()
