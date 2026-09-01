import pandas as pd, numpy as np

vix = pd.read_parquet('/tmp/vix_daily.parquet')
spy = pd.read_parquet('/tmp/SPY_daily.parquet')
spy['date'] = pd.to_datetime(spy['date'])
spy = spy.set_index('date').sort_index()
spy_ret = spy['close'].pct_change()

def rv(series, window):
    return series.rolling(window).std() * np.sqrt(252) * 100  # in vol points, match VIX

rv20 = rv(spy_ret, 20)          # trailing realized vol (points)
fwd_rv20 = (spy_ret.rolling(20).std() * np.sqrt(252) * 100).shift(-20)  # NEXT 20d realized vol (points)

df = pd.DataFrame({'vix': vix['vix'], 'rv20': rv20, 'fwd_rv20': fwd_rv20}).dropna()
# align dates
df = df[df.index >= spy.index[30]]

# 1. Aggregate VRP: does VIX overstate forward realized?
spread = df['fwd_rv20'] - df['vix']
print('=== AGGREGATE (all days, aligned) ===')
print(f'VIX mean {df.vix.mean():.1f}, fwd RV20 mean {df.fwd_rv20.mean():.1f}, spread {spread.mean():+.1f} pts')
print(f'% days fwd_RV > VIX: {(spread>0).mean()*100:.1f}%')

# 2. By VIX quintile (regime)
print('\n=== BY VIX REGIME (quintile) ===')
df['q'] = pd.qcut(df['vix'], 5, labels=['vlow','low','mid','high','vhigh'])
g = df.groupby('q', observed=True).agg(vix_m=('vix','mean'), fwd=('fwd_rv20','mean'), 
    spread=('fwd_rv20', lambda s: (s - df.loc[s.index,'vix']).mean()), win=('fwd_rv20', lambda s: ((s - df.loc[s.index,'vix'])>0).mean()*100))
print(g.round(1))

# 3. Vol compression -> expansion (low trailing RV)
print('\n=== VOL COMPRESSION (low trailing RV20) ===')
lo = df[df['rv20'] < df['rv20'].quantile(0.2)]
hi = df[df['rv20'] > df['rv20'].quantile(0.8)]
print(f'low-RV days: fwd_RV20 {lo.fwd_rv20.mean():.1f} vs trailing RV20 {lo.rv20.mean():.1f} -> expansion {lo.fwd_rv20.mean()-lo.rv20.mean():+.1f}')
print(f'low-RV days: fwd_RV vs VIX spread { (lo.fwd_rv20-lo.vix).mean():+.1f}, win {(lo.fwd_rv20>lo.vix).mean()*100:.0f}%')
print(f'high-RV days: fwd_RV20 {hi.fwd_rv20.mean():.1f} vs VIX {hi.vix.mean():.1f} spread {(hi.fwd_rv20-hi.vix).mean():+.1f}')

# 4. VIX transitions (low->rising)
print('\n=== VIX TRANSITION (VIX rising vs falling, from low base) ===')
df['d_vix'] = df['vix'].diff()
low_base = df[df['vix'] < df['vix'].median()]
rising = low_base[low_base['d_vix'] > 0]
falling = low_base[low_base['d_vix'] < 0]
print(f'low-VIX & rising: fwd_RV-VIX { (rising.fwd_rv20-rising.vix).mean():+.1f}, win {(rising.fwd_rv20>rising.vix).mean()*100:.0f}%')
print(f'low-VIX & falling: fwd_RV-VIX { (falling.fwd_rv20-falling.vix).mean():+.1f}, win {(falling.fwd_rv20>falling.vix).mean()*100:.0f}%')
