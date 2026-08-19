"""SPY / QQQ trend-breakout backtest — baseline vs full strategy.

Mirrors the logic in bot/live.py (ES long-only trend breakout):

  Entry  : Close > 20-day rolling high (shifted 1) AND Close > SMA200 AND ADX(14) > 25
  Stop   : trailing 2*ATR(14) (moved up daily, never down)
  Exit   : Close < SMA200 (trend broken) -> close position

Two variants are backtested per symbol:

  (a) BASELINE   long-only, no filter:  entry Close > 20-day high (shifted 1),
                                        exit Close < 20-day low (shifted 1).
      (No SMA200, no ADX, no trailing stop — a plain Donchian channel breakout.)

  (b) FULL       SMA200 + ADX>25 + 2*ATR trailing stop (as in live.py).

Buy & Hold is also reported as an absolute reference.

Position model: all-in long (full equity, fractional shares, no commission/slippage),
compounding. Profit factor is computed on per-trade % returns (size/order independent).

Uses Wilder smoothing (ewm alpha=1/n) for ATR and ADX, identical to live.py.
"""
import sys

import yfinance as yf
import numpy as np
import pandas as pd
# --- SSM-first secrets (infra/ssm_secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.ssm_secrets import bootstrap as _sb
_sb()

SYMBOLS = ['SPY', 'QQQ']
PERIOD = '10y'
ADX_MIN = 25
STOP_ATR = 2.0
N_ATR = 14
N_DON = 20
SMA_N = 200
START_IDX = 200  # warm-up for SMA200


# ---- indicators (Wilder, identical to live.py) ---------------------------------
def wilder_atr(high, low, close, n=N_ATR):
    tr = pd.concat([high - low,
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(high, low, close, n=N_ATR):
    up = high.diff().to_numpy()
    dn = (-low.diff()).to_numpy()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    idx = high.index
    tr = wilder_atr(high, low, close, n)
    plus_di = 100 * pd.Series(plus_dm, index=idx).ewm(alpha=1 / n, adjust=False).mean() / tr
    minus_di = 100 * pd.Series(minus_dm, index=idx).ewm(alpha=1 / n, adjust=False).mean() / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


# ---- metrics -------------------------------------------------------------------
def metrics(trades, equity_curve, years):
    """Compute report metrics from a trade list + equity curve (equity_curve[0] = 1.0)."""
    if equity_curve is None or len(equity_curve) == 0:
        return dict(total=0.0, cagr=0.0, pf=0.0, dd=0.0, trades=0, winrate=0.0)
    eq = np.asarray(equity_curve, dtype=float)
    total = eq[-1] / eq[0] - 1.0
    cagr = (eq[-1] / eq[0]) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    dd = (eq / peak - 1.0).min()
    if trades:
        rs = np.array([t['r'] for t in trades])
        wins = rs[rs > 0].sum()
        losses = abs(rs[rs <= 0].sum())
        pf = wins / losses if losses > 0 else float('inf')
        winrate = (rs > 0).mean()
        n = len(trades)
    else:
        pf = 0.0
        winrate = 0.0
        n = 0
    return dict(total=total * 100, cagr=cagr * 100, pf=pf, dd=dd * 100,
                trades=n, winrate=winrate * 100)


# ---- backtests -----------------------------------------------------------------
def backtest_baseline(df):
    """Long-only, no filter: 20d Donchian breakout, symmetric channel exit."""
    close = df['Close'].to_numpy()
    high = df['High'].to_numpy()
    low = df['Low'].to_numpy()
    don_hi = df['High'].rolling(N_DON).max().shift(1).to_numpy()
    don_lo = df['Low'].rolling(N_DON).min().shift(1).to_numpy()

    equity = 1.0
    in_pos = False
    shares = 0.0
    entry_price = 0.0
    entry_bar = 0
    trades = []
    eq = []

    for i in range(START_IDX, len(df)):
        c = close[i]
        if in_pos:
            if c < don_lo[i]:
                equity = shares * c
                trades.append(dict(entry_bar=entry_bar, exit_bar=i,
                                   entry=entry_price, exit=c, r=c / entry_price - 1.0))
                in_pos = False
                shares = 0.0
            mark = shares * c if in_pos else equity
        else:
            if c > don_hi[i]:
                entry_price = c
                shares = equity / c
                in_pos = True
                entry_bar = i
            mark = equity if not in_pos else shares * c
        eq.append(mark)
    return trades, eq


def backtest_strategy(df):
    """Full strategy from live.py: SMA200 + ADX>25 + 2*ATR trailing stop."""
    close = df['Close'].to_numpy()
    high = df['High'].to_numpy()
    low = df['Low'].to_numpy()
    sma200 = df['Close'].rolling(SMA_N).mean().to_numpy()
    don_hi = df['High'].rolling(N_DON).max().shift(1).to_numpy()
    atr = wilder_atr(df['High'], df['Low'], df['Close']).to_numpy()
    adxv = adx(df['High'], df['Low'], df['Close']).to_numpy()

    equity = 1.0
    in_pos = False
    shares = 0.0
    entry_price = 0.0
    entry_bar = 0
    stop = 0.0
    trades = []
    eq = []

    for i in range(START_IDX, len(df)):
        c, h, l, a = close[i], high[i], low[i], atr[i]
        if in_pos:
            exit_price = None
            reason = None
            if i > entry_bar:  # stop is live from the bar after entry
                if l <= stop:
                    exit_price = stop
                    reason = 'stop'
                elif c < sma200[i]:
                    exit_price = c
                    reason = 'sma200'
                else:
                    stop = max(stop, c - STOP_ATR * a)  # trail up, never down
            if exit_price is not None:
                equity = shares * exit_price
                trades.append(dict(entry_bar=entry_bar, exit_bar=i,
                                   entry=entry_price, exit=exit_price,
                                   r=exit_price / entry_price - 1.0, reason=reason))
                in_pos = False
                shares = 0.0
            mark = shares * c if in_pos else equity
        else:
            if c > don_hi[i] and c > sma200[i] and adxv[i] > ADX_MIN:
                entry_price = c
                shares = equity / c
                stop = c - STOP_ATR * a
                in_pos = True
                entry_bar = i
            mark = equity if not in_pos else shares * c
        eq.append(mark)
    return trades, eq


def buy_and_hold(df):
    close = df['Close'].to_numpy()[START_IDX:]
    return close / close[0]


# ---- main ----------------------------------------------------------------------
def main():
    results = {}
    for sym in SYMBOLS:
        print(f'Downloading {sym} ({PERIOD}, auto_adjust=True)...', file=sys.stderr)
        df = yf.download(sym, period=PERIOD, interval='1d', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) <= START_IDX + 10:
            print(f'{sym}: insufficient data ({len(df)} rows)', file=sys.stderr)
            continue

        years = (df.index[-1] - df.index[START_IDX]).days / 365.25

        b_trades, b_eq = backtest_baseline(df)
        s_trades, s_eq = backtest_strategy(df)
        bh_eq = buy_and_hold(df)

        results[sym] = {
            'baseline': metrics(b_trades, b_eq, years),
            'strategy': metrics(s_trades, s_eq, years),
            'buyhold': metrics([], list(bh_eq), years),
            'years': years,
            'start': df.index[START_IDX].date(),
            'end': df.index[-1].date(),
        }

    # ---- report ----
    hdr = (f"{'Symbol':<6} {'Variant':<40} {'TotRet%':>9} {'CAGR%':>8} {'PF':>7} "
           f"{'MaxDD%':>8} {'Trades':>7} {'Win%':>6}")
    print()
    print(hdr)
    print('-' * len(hdr))
    for sym, r in results.items():
        rows = [
            ('Baseline (no filter)', r['baseline']),
            ('Full (SMA200+ADX25+2ATR)', r['strategy']),
            ('Buy & Hold (reference)', r['buyhold']),
        ]
        for name, m in rows:
            pf = f"{m['pf']:.2f}" if np.isfinite(m['pf']) else '  inf'
            print(f"{sym:<6} {name:<40} {m['total']:>8.1f}% {m['cagr']:>7.1f}% "
                  f"{pf:>7} {m['dd']:>7.1f}% {m['trades']:>7} {m['winrate']:>5.0f}%")
        print(f"      ({r['start']} -> {r['end']}, {r['years']:.1f} yrs)")
        print()

    # concise verdict
    print('Summary (full strategy vs baseline, per symbol):')
    for sym, r in results.items():
        b, s = r['baseline'], r['strategy']
        print(f"  {sym}: PF {b['pf']:.2f} -> {s['pf']:.2f} | MaxDD {b['dd']:.1f}% -> {s['dd']:.1f}% | "
              f"trades {b['trades']} -> {s['trades']} | CAGR {b['cagr']:.1f}% -> {s['cagr']:.1f}% "
              f"(B&H CAGR {r['buyhold']['cagr']:.1f}%)")


if __name__ == '__main__':
    main()

