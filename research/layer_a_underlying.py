import pandas as pd, numpy as np

SECTORS = ['XLK','XLF','XLE','XLV','XLI','XLY','XLP','XLU','XLB','XLRE','XLC','QQQ','IWM']
def load(s):
    df = pd.read_parquet(f'/tmp/{s}_daily.parquet')
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date').sort_index()['close']

px = pd.DataFrame({s: load(s) for s in SECTORS + ['SPY']}).dropna()
idx = px.index
spy = px['SPY']

def spread_vs_spy(lookback, skip, rebalance, topn, oos_frac=0.2):
    mom = px / px.shift(lookback + skip) - 1.0   # skip most recent `skip` days (momentum not reversal)
    # rebalance dates
    step = 5 if rebalance == 'weekly' else 21
    reb = idx[step::step]
    # OOS split: last oos_frac of REBALANCE dates untouched
    split_i = int(len(reb) * (1 - oos_frac))
    results = {}
    for seg, dates in [('IS', reb[:split_i]), ('OOS', reb[split_i:])]:
        rets = []
        for d in dates:
            m = mom.loc[d].dropna()
            if len(m) < 5:
                continue
            top = m.nlargest(topn).index
            # forward return to next rebalance date
            j = idx.get_loc(d)
            if j + step >= len(idx):
                continue
            d_next = idx[j + step]
            port = np.mean([px[s].loc[d_next] / px[s].loc[d] - 1.0 for s in top])
            bench = spy.loc[d_next] / spy.loc[d] - 1.0
            rets.append((port - bench) * 10000)
        results[seg] = np.array(rets)
    return results

print(f"{'lookback':>8} {'skip':>4} {'reb':>7} {'top':>4} | {'OOS spread':>10} {'win%':>5} {'t':>6} {'n':>4}")
print('-' * 70)
rows = []
for lookback in (5, 10, 20, 60):
    for skip in (0, 5):
        for reb in ('weekly', 'monthly'):
            for topn in (1, 3):
                r = spread_vs_spy(lookback, skip, reb, topn)
                oos = r['OOS']
                if len(oos) < 10:
                    continue
                t = oos.mean() / oos.std() * np.sqrt(len(oos))
                rows.append((lookback, skip, reb, topn, oos.mean(), (oos > 0).mean(), t, len(oos)))
                print(f"{lookback:>8} {skip:>4} {reb:>7} {topn:>4} | {oos.mean():>9.1f}bp {(oos>0).mean()*100:>4.0f}% {t:>6.2f} {len(oos):>4}")

# sort by OOS t
print('\n=== TOP 8 by OOS t-stat ===')
for r in sorted(rows, key=lambda x: -abs(x[6]))[:8]:
    print(f'lookback={r[0]} skip={r[1]} {r[2]} top{r[3]}: OOS {r[4]:+.1f}bp win{r[5]*100:.0f}% t={r[6]:.2f} n={r[7]}')
