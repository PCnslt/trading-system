"""Overnight futures-cash basis mispricing test (prompt: fade basis-delta extremes at open).

Honest reduced form using daily bars (entry=open, exit=close; the 30-min intraday
version needs 1-min /ES+SPY which I lack enough history for — noted in report).
Signal: basis_delta = (ES open - ES prev close) - (SPY open - SPY prev close),
fade at +/-1.5 rolling-20d sigma. Net 2bp RT. Placebo = shuffled basis_delta.
"""
import numpy as np, pandas as pd
import yfinance as yf

print("pulling SPY + ES=F daily (2000-2026)...")
spy = yf.download('SPY', start='2000-01-01', end='2026-09-09', auto_adjust=False, progress=False)
es  = yf.download('ES=F', start='2000-01-01', end='2026-09-09', auto_adjust=False, progress=False)
spy.columns = [c[0] for c in spy.columns]
es.columns  = [c[0] for c in es.columns]

df = pd.DataFrame(index=spy.index)
df['spy_open'] = spy['Open']; df['spy_close'] = spy['Close']
df['es_open'] = es['Open'];   df['es_close'] = es['Close']

df['futures_gap'] = df['es_open']/df['es_close'].shift(1) - 1
df['cash_gap']    = df['spy_open']/df['spy_close'].shift(1) - 1
df['basis_delta'] = (df['futures_gap'] - df['cash_gap']).clip(-0.01, 0.01)  # winsorize roll/ETF-premium artifacts

df['bd_std'] = df['basis_delta'].rolling(20).std()
df['bd_z']   = df['basis_delta']/df['bd_std']

# forward SPY return: open->close (same day)
df['ret'] = df['spy_close']/df['spy_open'] - 1
df = df.dropna(subset=['bd_z','ret'])

COST = 0.0002  # 2bp round trip

def run(z, ret, seed=None):
    z = pd.Series(z)
    if seed is not None:
        z = pd.Series(np.random.default_rng(seed).permutation(z.values), index=z.index)
    long_s  = z < -1.5
    short_s = z > 1.5
    sig = long_s | short_s
    pnl = pd.Series(0.0, index=z.index)
    pnl[long_s]  =  ret[long_s]  - COST
    pnl[short_s] = -ret[short_s] - COST
    n = int(sig.sum())
    if n == 0: return dict(n=0)
    m = pnl[sig].mean(); s = pnl[sig].std()
    t = m/(s/np.sqrt(n))
    win = (pnl[sig] > 0).mean()
    return dict(n=n, mean_bp=m*1e4, t=t, win=win, pf=pnl[sig][pnl[sig]>0].sum()/abs(pnl[sig][pnl[sig]<0].sum()) if (pnl[sig]<0).any() else np.inf)

print(f"\ndays={len(df)}  basis_delta mean={df['basis_delta'].mean()*1e4:.2f}bp std={df['basis_delta'].std()*1e4:.2f}bp")
print(f"basis_delta autocorr(1)={df['basis_delta'].autocorr(1):.3f}  (should be ~0 if pure artifact)")

real = run(df['bd_z'], df['ret'])
print(f"\nREAL fade signal (|z|>1.5): n={real['n']}  mean={real['mean_bp']:.2f}bp  t={real['t']:.2f}  win={real['win']:.1%}  PF={real['pf']:.2f}")

# placebo: shuffle basis_delta across days, 200 draws
t_placebo = []
for s in range(200):
    p = run(df['bd_z'], df['ret'], seed=s)
    if p['n'] > 0: t_placebo.append(p['t'])
t_placebo = np.array(t_placebo)
print(f"placebo t-dist: mean={t_placebo.mean():.2f}  p5={np.percentile(t_placebo,5):.2f}  p95={np.percentile(t_placebo,95):.2f}")
print(f"real t={real['t']:.2f} vs placebo 95th pct t={np.percentile(t_placebo,95):.2f} -> "
      f"{'REJECT (fails placebo)' if real['t'] < np.percentile(t_placebo,95) else 'would pass placebo'}")

# direct predictive test: does basis_delta predict forward SPY return? (fade => negative corr)
corr = np.corrcoef(df['basis_delta'], df['ret'])[0,1]
print(f"\ncorr(basis_delta, fwd SPY open->close return) = {corr:+.4f}  (fade thesis needs NEGATIVE)")

# simple gap-fade benchmark (SPY gap alone) for comparison
df['z_gap'] = (df['cash_gap'] - df['cash_gap'].rolling(20).mean())/df['cash_gap'].rolling(20).std()
g = run(df['z_gap'], df['ret'])
print(f"plain SPY gap-fade (|z_gap|>1.5): n={g['n']}  mean={g['mean_bp']:.2f}bp  t={g['t']:.2f}")
