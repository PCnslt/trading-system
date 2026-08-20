import numpy as np, pandas as pd, yfinance as yf
from short_horizon_edges_study import fetch_daily, wilder_atr, rsi

def fwd_ret(c, n=3):
    return c.shift(-n) / c - 1

for tkr in ['ES=F', 'NQ=F']:
    df = fetch_daily(tkr)
    c = df['Close']
    atr = wilder_atr(df['High'], df['Low'], c, 14)
    ret2 = c.pct_change(2)
    fwd3 = fwd_ret(c, 3)
    r2 = rsi(c, 2)
    sma200 = c.rolling(200).mean()
    k = 1.0 * atr / c
    any_drop = ret2 < 0
    rev2 = ret2 < -k
    rsi2_sig = (r2 < 10) & (c > sma200)
    n = len(df)
    m = any_drop & rev2.notna() & fwd3.notna()
    m2 = rev2 & rev2.notna() & fwd3.notna()
    m3 = rsi2_sig & fwd3.notna() & sma200.notna()
    print(f"### {tkr} (n={n})")
    print(f"  ANY 2d-drop:        n={any_drop[m].sum():4d}  avg 3d-fwd={fwd3[m].mean():+.3%}  win={(fwd3[m] > 0).mean():.1%}")
    print(f"  REV2 (>1xATR):      n={rev2[m2].sum():4d}  avg 3d-fwd={fwd3[m2].mean():+.3%}  win={(fwd3[m2] > 0).mean():.1%}")
    print(f"  RSI2 (<10, >200d):  n={rsi2_sig[m3].sum():4d}  avg 3d-fwd={fwd3[m3].mean():+.3%}  win={(fwd3[m3] > 0).mean():.1%}")
    print(f"  buy&hold: {c.pct_change().mean() * 252:+.1%}/yr")
    co = (rev2 & rsi2_sig).sum()
    print(f"  co-fire REV2&RSI2: {co} days | REV2 {rev2.sum()}d, RSI2 {rsi2_sig.sum()}d -> {co / max(rev2.sum(), 1):.0%} of REV2 days also fire RSI2")
    print()
