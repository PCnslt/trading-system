"""ALL-MARKETS short-horizon strategy scan — broad futures universe, realistic costs.

Extends bot/futures_scan.py (which validated Donchian/ATR LONG-ONLY on ES/NQ,
OOS PF ~2.1) to every other futures asset class, hunting for a real
short-horizon (intraday→few-day) edge beyond index futures.

UNIVERSE (daily bars 2015-now, yfinance):
  Indices   ES=F  NQ=F  YM=F  RTY=F
  Energy    CL=F  NG=F  RB=F
  Metals    GC=F  SI=F  HG=F
  Grains    ZC=F  ZS=F  ZW=F  SB=F
  Rates     ZN=F  ZB=F  ZF=F
  FX        6E=F  6J=F  6B=F  6A=F

COST (stated exactly): 1.3 bps = 0.00013 round-trip of notional per completed
trade, applied to returns (same as futures_scan.py — deliberately conservative,
bundles commission + exchange/NFA fees + slippage buffer). 1x notional, no
leverage, so % returns carry over to micro contracts.

STRATEGIES (each long-only AND long+short):
  a. Donchian/ATR breakout — close > 20d-high (< 20d-low short), 2*ATR stop,
     opposite breakout exit, 5-day hold.
  b. RSI(2) mean-reversion — RSI(2)<10 long (>90 short); exit RSI(2)>70 (<30), 5d.
  c. MA 5/20 crossover — momentum; exit opposite cross or 5d.
  d. Bollinger reversal — close outside 2σ band → mean; exit at SMA20 or 5d.
  e. ADX trend breakout — ported from live.py: close > 20d-high AND > SMA200 AND
     ADX>25; trailing 2*ATR stop; exit close < SMA200. Short mirrored.

Walk-forward 60/40 applied to ANY (strategy × direction) with pooled PF > 1.2
(across the whole universe), reporting per-market OOS PF so we can see WHICH
market actually carries the edge.

Results → bot/allmarkets_scan_results.json.
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# --- SSM-first secrets (infra/secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.secrets import bootstrap as _sb
_sb()
from data.s3_archive import archive_scan_results

COST = 0.00013        # 1.3 bps round-trip of notional
MAX_HOLD = 5          # time stop (days) for short-horizon strategies
STOP_ATR = 2.0
ADX_MIN = 25
START = '2015-01-01'

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(HERE, 'allmarkets_scan_results.json')

MARKETS = {
    'Indices': ['ES=F', 'NQ=F', 'YM=F', 'RTY=F'],
    'Energy':  ['CL=F', 'NG=F', 'RB=F'],
    'Metals':  ['GC=F', 'SI=F', 'HG=F'],
    'Grains':  ['ZC=F', 'ZS=F', 'ZW=F', 'SB=F'],
    'Rates':   ['ZN=F', 'ZB=F', 'ZF=F'],
    'FX':      ['6E=F', '6J=F', '6B=F', '6A=F'],
}
TICKERS = [tk for grp in MARKETS.values() for tk in grp]
TICKER_MARKET = {tk: m for m, grp in MARKETS.items() for tk in grp}


# ===== indicators (identical to futures_scan.py) =====
def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx_ind(h, l, c, n=14):
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


# ===== signal generators (identical to futures_scan.py) =====
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
                if short_ok:
                    p, entry_i = -1, i
                    stop = ci + stop_atr * atr.iloc[i]
                else:
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


SIGS = {'donchian': sig_donchian, 'rsi2': sig_rsi2,
        'ma_cross': sig_ma_cross, 'bollinger': sig_bollinger}


# ===== trade extraction + engine (identical to futures_scan.py) =====
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
    close = df['Close']
    ret = close.pct_change().fillna(0.0)
    gross = pos.shift(1).fillna(0.0) * ret
    turnover = pos.diff().abs().fillna(0.0)
    net = (gross - (cost / 2) * turnover).fillna(0.0)
    return net, extract_trades(pos, close, cost)


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
    ref = entry_px = entry_i = stop = None
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
                r_i = (exit_px / ref - 1) * pos - cost
                trades.append({'ret': (exit_px / entry_px - 1) * pos - cost,
                               'days': i - entry_i, 'dir': pos, 'exit': reason})
                pos, ref, entry_px, stop, entry_i = 0, None, None, None, None
            else:
                r_i = (ci / ref - 1) * pos
                if pos == 1:
                    ns = ci - stop_atr * atr.iloc[i]
                    if not np.isnan(ns) and ns > stop:
                        stop = ns
                else:
                    ns = ci + stop_atr * atr.iloc[i]
                    if not np.isnan(ns) and ns < stop:
                        stop = ns
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


def get_data(ticker):
    df = yf.download(ticker, start=START, interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=['Open', 'High', 'Low', 'Close'])


def run_one(df, kind, direction, adx_min=ADX_MIN):
    if kind == 'adx':
        return run_adx(df, direction, adx_min=adx_min)
    sig = SIGS[kind](df, short_ok=(direction == 'both'))
    return close_to_close(sig, df, COST)


STRAT_ORDER = ['donchian', 'rsi2', 'ma_cross', 'bollinger', 'adx']
STRAT_NAME = {'donchian': 'Donchian/ATR', 'rsi2': 'RSI(2) MR',
              'ma_cross': 'MA 5/20', 'bollinger': 'Bollinger', 'adx': 'ADX trend'}


def main():
    print("ALL-MARKETS short-horizon scan  (cost = %.5f = 1.3 bps/round-trip)" % COST)
    print("Universe: %d tickers across %s\n" % (len(TICKERS), ', '.join(MARKETS)))

    data, failed = {}, []
    for tk in TICKERS:
        try:
            df = get_data(tk)
            if df is None or len(df) < 260:
                failed.append((tk, 'insufficient data (%d rows)' % (0 if df is None else len(df))))
            else:
                data[tk] = df
        except Exception as e:  # noqa: BLE001
            failed.append((tk, f'{type(e).__name__}: {e}'))
    if failed:
        print("SKIPPED (yfinance could not fetch):")
        for tk, why in failed:
            print(f"  {tk:>6}  {why}")
        print()

    # Full-sample run: every (strategy, direction, ticker)
    rows = []
    combo_trades = {}            # (strategy, direction) -> pooled trades (all markets)
    market_trades = {}           # (strategy, direction, market) -> pooled trades
    for kind in STRAT_ORDER:
        for direction in ('long', 'both'):
            key = (kind, direction)
            combo_trades[key] = []
            for tk, df in data.items():
                net, trades = run_one(df, kind, direction)
                m = metrics(net, trades)
                rows.append({'strategy': kind, 'ticker': tk,
                             'market': TICKER_MARKET[tk], 'direction': direction, **m})
                combo_trades[key].extend(trades)
                mkt = (kind, direction, TICKER_MARKET[tk])
                market_trades.setdefault(mkt, []).extend(trades)

    # Pooled rank (strategy x direction) across whole universe
    ranking = sorted(combo_trades.keys(), key=lambda k: pf_from_trades(combo_trades[k]), reverse=True)
    print("Pooled PF rank (strategy x direction, whole universe):")
    for i, key in enumerate(ranking, 1):
        k, d = key
        pf = pf_from_trades(combo_trades[key])
        print(f"  {i:>2}. {STRAT_NAME[k]:<16} {d:>5}  pooled PF {pf:>7.2f}  (n={len(combo_trades[key])})")

    # Per-market pooled PF (full sample): which MARKET carries an edge per (strategy, dir)
    print("\nPer-market pooled PF (full sample, strategy x direction x market):")
    market_cells = sorted(market_trades.keys(),
                          key=lambda k: pf_from_trades(market_trades[k]), reverse=True)
    for (kind, direction, mkt) in market_cells:
        pf = pf_from_trades(market_trades[(kind, direction, mkt)])
        n = len(market_trades[(kind, direction, mkt)])
        if pf >= 1.10 or (pf >= 0.90 and mkt == 'Indices'):
            print(f"  {STRAT_NAME[kind]:<16} {direction:>5} {mkt:<8} PF {pf:>6.2f}  (n={n})")

    # Walk-forward 60/40 on EVERY (strategy x direction x ticker) cell: the report
    # needs a per-market OOS PF, and compute is cheap. Cells whose FULL-SAMPLE PF
    # is > 1.2 are the "candidates"; everything else is included for the honest table.
    print("\nWalk-forward 60/40 (train/test):")
    wf_rows = []          # per (strategy, direction, ticker)
    wf_market_trades = {}  # (strategy, direction, market) -> pooled OOS trades
    for kind in STRAT_ORDER:
        for direction in ('long', 'both'):
            for tk, df in data.items():
                split = int(len(df) * 0.6)
                tr, te = df.iloc[:split], df.iloc[split:]
                m_in = metrics(*run_one(tr, kind, direction))
                m_out = metrics(*run_one(te, kind, direction))
                _, oos_trades = run_one(te, kind, direction)
                r = {'strategy': kind, 'direction': direction, 'ticker': tk,
                     'market': TICKER_MARKET[tk],
                     'in_pf': m_in['pf'], 'in_trades': m_in['trades'],
                     'out_pf': m_out['pf'], 'out_trades': m_out['trades'],
                     'out_cagr': m_out['cagr'], 'out_maxdd': m_out['maxdd']}
                wf_rows.append(r)
                mkt = (kind, direction, TICKER_MARKET[tk])
                wf_market_trades.setdefault(mkt, []).extend(oos_trades)

    # Candidates: full-sample PF > 1.2 (the task's walk-forward trigger, per-market)
    candidates = [r for r in wf_rows if r['in_pf'] > 1.2]
    print(f"  cells with full-sample PF > 1.2: {len(candidates)} / {len(wf_rows)}")

    # Per-market pooled OOS PF (pool OOS trades across the tickers in a market)
    print("\nPer-market pooled OOS PF (strategy x direction x market, OOS n pooled):")
    for (kind, direction, mkt) in sorted(wf_market_trades.keys(),
                                         key=lambda k: pf_from_trades(wf_market_trades[k]),
                                         reverse=True):
        tr = wf_market_trades[(kind, direction, mkt)]
        pf = pf_from_trades(tr)
        if pf >= 1.20:
            print(f"  {STRAT_NAME[kind]:<16} {direction:>5} {mkt:<8} OOS PF {pf:>6.2f}  (n={len(tr)})")

    # Top-N by OOS PF across all walk-forward rows
    print("\n=== TOP 20 (strategy x market x direction) by OOS PF ===")
    print(f"{'#':>2} {'Strategy':<16} {'Market':<9} {'Dir':>5} {'OOS PF':>7} {'n':>4} "
          f"{'OOS CAGR%':>9} {'OOS MaxDD%':>10}  {'flag'}")
    top = sorted(wf_rows, key=lambda r: r['out_pf'], reverse=True)[:20]
    for i, r in enumerate(top, 1):
        flag = 'small' if 0 < r['out_trades'] < 30 else ''
        print(f"{i:>2} {STRAT_NAME[r['strategy']]:<16} {r['market']:<9} {r['direction']:>5} "
              f"{r['out_pf']:>7.2f} {r['out_trades']:>4} {r['out_cagr']*100:>9.1f} "
              f"{r['out_maxdd']*100:>10.1f}  {flag}")

    payload = {
        'cost': COST,
        'tickers': TICKERS,
        'failed': failed,
        'rank': [[k, d] for k, d in ranking],
        'rows': rows,
        'market_cells': [{'strategy': k, 'direction': d, 'market': m,
                          'pf': pf_from_trades(market_trades[(k, d, m)]),
                          'trades': len(market_trades[(k, d, m)])}
                         for (k, d, m) in market_cells],
        'walk_forward': wf_rows,
    }
    with open(RESULTS_FILE, 'w') as f:
        json.dump(payload, f, indent=2, default=float)
    print(f"\nSaved results → {RESULTS_FILE}")
    try:
        archive_scan_results('allmarkets', payload)
    except Exception as e:
        print(f"S3 archive failed: {e}")


if __name__ == '__main__':
    main()

