"""ES trend-following — parameter comparison: trailing stop, regime filter, shorts.

Runs multiple configs and prints a comparison table.
"""
import yfinance as yf
import pandas as pd
import numpy as np


def wilder_atr(high, low, close, n=14):
    tr = pd.concat([high - low,
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def adx(high, low, close, n=14):
    up = high.diff()
    dn = -low.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=high.index)
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/n, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/n, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/n, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1/n, adjust=False).mean()


def run(df, allow_short=True, use_trailing=True, use_regime=True, adx_thresh=20):
    close = df['Close']; high = df['High']; low = df['Low']
    sma200 = close.rolling(200).mean()
    atr = wilder_atr(high, low, close)
    adxv = adx(high, low, close)
    don_hi = high.rolling(20).max().shift(1)
    don_lo = low.rolling(20).min().shift(1)

    equity = 100_000.0
    risk_pct = 0.01; commission = 4.5; slippage = 0.25; MULT = 50

    pos = 0; entry = 0.0; stop = 0.0; target = 0.0; direc = 0
    best = 0.0  # best price since entry (for trailing)
    trades = []

    for i in range(200, len(df)):
        c = close.iloc[i]; h = high.iloc[i]; l = low.iloc[i]; a = atr.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        trending = (not use_regime) or (adxv.iloc[i] > adx_thresh)

        if pos == 0:
            if trending and c > don_hi.iloc[i] and c > sma200.iloc[i]:
                entry = c + slippage; stop = entry - 2.0*a; target = entry + 3.0*a
                direc = 1; best = entry
            elif allow_short and trending and c < don_lo.iloc[i] and c < sma200.iloc[i]:
                entry = c - slippage; stop = entry + 2.0*a; target = entry - 3.0*a
                direc = -1; best = entry
            else:
                continue
            rpc = abs(entry - stop)
            if rpc <= 0: continue
            size = max(1, int((equity * risk_pct) / (rpc * MULT)))
            pos = size * direc
            equity -= size * commission
            trades.append({'dir': direc, 'entry': entry, 'stop': stop, 'target': target,
                           'size': size, 'date': df.index[i]})
        else:
            exit_reason = None; exit_price = None
            if direc == 1:
                best = max(best, h)
                # trailing: move stop to breakeven after +1R, then chandelier 2*ATR
                if use_trailing:
                    r = entry - stop
                    if h >= entry + r:  # 1R in favor → breakeven
                        stop = max(stop, entry)
                    stop = max(stop, best - 2.0*a)  # chandelier trail
                if l <= stop: exit_reason='stop'; exit_price=stop
                elif h >= target: exit_reason='target'; exit_price=target
                elif c < sma200.iloc[i]: exit_reason='trend_break'; exit_price=c
            else:
                best = min(best, l)
                if use_trailing:
                    r = stop - entry
                    if l <= entry - r:
                        stop = min(stop, entry)
                    stop = min(stop, best + 2.0*a)
                if h >= stop: exit_reason='stop'; exit_price=stop
                elif l <= target: exit_reason='target'; exit_price=target
                elif c > sma200.iloc[i]: exit_reason='trend_break'; exit_price=c

            if exit_reason:
                exit_price = exit_price - slippage if direc==1 else exit_price + slippage
                pnl = (exit_price - entry) * direc * MULT * abs(pos)
                equity += pnl - abs(pos)*commission
                trades[-1].update({'exit': exit_price, 'exit_date': df.index[i], 'pnl': pnl,
                                   'exit_reason': exit_reason,
                                   'r': ((exit_price-entry)*direc)/abs(entry-stop)})
                pos = 0

    closed = [t for t in trades if 'exit_reason' in t]
    if not closed:
        return {'trades': 0, 'return': 0, 'pf': 0, 'dd': 0, 'sharpe': 0}
    eq = pd.Series([equity])
    wins = [t for t in closed if t['pnl'] > 0]
    losses = [t for t in closed if t['pnl'] <= 0]
    gw = sum(t['pnl'] for t in wins); gl = abs(sum(t['pnl'] for t in losses))
    pf = gw/gl if gl > 0 else float('inf')
    wr = len(wins)/len(closed)
    # simple drawdown from trade pnl sequence
    cum = np.cumsum([t['pnl'] for t in closed])
    peak = np.maximum.accumulate(cum); dd = ((cum - peak)/100_000).min()
    return {'trades': len(closed), 'return': (equity/100_000-1)*100, 'pf': pf,
            'wr': wr*100, 'dd': dd*100, 'sharpe': np.mean([t['r'] for t in closed]) if closed else 0,
            'avgR': np.mean([t['r'] for t in closed])}


df = yf.download('ES=F', period='5y', interval='1d', progress=False)
df.columns = [c[0] for c in df.columns]
df = df.dropna()

configs = [
    ("Baseline (long+short, no trail, no regime)", dict(allow_short=True, use_trailing=False, use_regime=False)),
    ("+ trailing stop", dict(allow_short=True, use_trailing=True, use_regime=False)),
    ("+ regime filter (ADX>20)", dict(allow_short=True, use_trailing=False, use_regime=True)),
    ("+ trail + regime", dict(allow_short=True, use_trailing=True, use_regime=True)),
    ("Long-only + trail + regime", dict(allow_short=False, use_trailing=True, use_regime=True)),
    ("Long-only + trail + regime (ADX>25)", dict(allow_short=False, use_trailing=True, use_regime=True, adx_thresh=25)),
]

print(f"{'Config':<42} {'Trades':>6} {'Ret%':>7} {'PF':>5} {'Win%':>5} {'MaxDD%':>7} {'AvgR':>5}")
print('-'*85)
for name, kw in configs:
    r = run(df, **kw)
    print(f"{name:<42} {r['trades']:>6} {r['return']:>6.1f}% {r['pf']:>5.2f} {r['wr']:>5.0f}% {r['dd']:>6.1f}% {r['avgR']:>5.2f}")
