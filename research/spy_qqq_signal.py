import pandas as pd, numpy as np

def load(s):
    df = pd.read_parquet(f'/tmp/{s}_daily.parquet')
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    return df

for sym in ['SPY', 'QQQ']:
    df = load(sym)
    c = df['close']
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    mom5 = c.pct_change(5)
    # RSI(2) pullback: rsi2 between 30 and 70 (recently dipped but not oversold-extreme)
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1/2, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1/2, adjust=False).mean()
    rsi2 = 100 - 100/(1 + up/dn)

    rows = []
    for hor in [7, 10, 14, 21]:
        fwd = c.shift(-hor) / c - 1.0
        # baseline: always long
        base = fwd.dropna()
        # signal: trend (c>ema50) + momentum (mom5>0) + rsi2 pullback (10<rsi2<70)
        sig = ((c > ema50) & (mom5 > 0) & (rsi2.between(10, 70))).astype(int)
        sig_fwd = fwd[sig == 1].dropna()
        base_fwd = fwd.dropna()
        def stats(x):
            if len(x) < 20: return 'n<20'
            w = (x > 0).mean()*100
            pf = x[x>0].mean()/-x[x<0].mean() if (x<0).any() else 99
            t = x.mean()/(x.std()/np.sqrt(len(x)))
            return f'n={len(x)} win={w:.0f}% avg={x.mean()*100:.2f}% PF={pf:.2f} t={t:.2f}'
        rows.append(f'  {hor}d: BASE {stats(base_fwd)}')
        rows.append(f'       SIG  {stats(sig_fwd)}')
    print(f'=== {sym} (2021-2026) ===')
    print('\n'.join(rows))
    print()
