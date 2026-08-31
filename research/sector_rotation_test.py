import pandas as pd, numpy as np

SECTORS = ['XLK','XLF','XLE','XLV','XLI','XLY','XLP','XLU','XLB','XLRE','XLC','QQQ','IWM']
def load(s):
    df = pd.read_parquet(f'/tmp/{s}_daily.parquet')
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date').sort_index()['close']

closes = {s: load(s) for s in SECTORS + ['SPY']}
px = pd.DataFrame(closes).dropna()
spy = px['SPY']

mom20 = px / px.shift(20) - 1.0   # 20-day momentum
rows = []
for d in px.index[21:-22]:
    # weekly rebalance (every 5 trading days)
    if px.index.get_loc(d) % 5 != 0:
        continue
    m = mom20.loc[d].dropna()
    top = m.idxmax()                  # strongest sector
    top3 = m.nlargest(3).index
    fwd = {}
    for h in (10, 21):
        # forward return of strongest sector
        fwd[f'top{h}'] = px[top].asof(d + pd.Timedelta(days=h*2)) / px[top].loc[d] - 1.0
        # average of top3
        fwd[f'top3_{h}'] = np.mean([px[s].asof(d + pd.Timedelta(days=h*2)) / px[s].loc[d] - 1.0 for s in top3])
        # SPY benchmark
        fwd[f'spy{h}'] = spy.asof(d + pd.Timedelta(days=h*2)) / spy.loc[d] - 1.0
    rows.append({'date': d, 'top': top, **fwd})

r = pd.DataFrame(rows).set_index('date')
print('=== sector-rotation (strongest vs SPY) ===')
for h in (10, 21):
    top = r[f'top{h}']; spyf = r[f'spy{h}']
    spread = (top - spyf) * 10000
    print(f'{h}d: top-sector +{top.mean()*10000:.1f}bp  SPY +{spyf.mean()*10000:.1f}bp  SPREAD +{spread.mean():.1f}bp  win% {(spread>0).mean()*100:.0f}%  t={spread.mean()/spread.std()*np.sqrt(len(spread)):.2f}  n={len(r)}')
print()
print('=== top-3 average vs SPY ===')
for h in (10, 21):
    t3 = r[f'top3_{h}']; spyf = r[f'spy{h}']
    spread = (t3 - spyf) * 10000
    print(f'{h}d: top3 +{t3.mean()*10000:.1f}bp  SPY +{spyf.mean()*10000:.1f}bp  SPREAD +{spread.mean():.1f}bp  win% {(spread>0).mean()*100:.0f}%  t={spread.mean()/spread.std()*np.sqrt(len(spread)):.2f}')
