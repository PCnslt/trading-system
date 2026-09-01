import requests, json, pandas as pd, numpy as np

BASE='https://data-api.binance.vision/api/v3'
SYMS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT']

def fetch(sym, interval='1h', limit=1000):
    out=[]
    end=None
    for _ in range(10):  # ~10k bars ≈ 1.1yr of 1h
        p={'symbol':sym,'interval':interval,'limit':limit}
        if end: p['endTime']=end
        r=requests.get(f'{BASE}/klines',params=p,timeout=30); r.raise_for_status()
        k=r.json()
        if not k: break
        out=k+out
        end=k[0][0]-1
        if len(k)<limit: break
    df=pd.DataFrame(out,columns=['ot','o','h','l','c','v','ct','q','n','tb','tq','ig'])
    df['ts']=pd.to_datetime(df['ot'],unit='ms'); df['c']=df['c'].astype(float)
    return df.set_index('ts')['c']

px={}
for s in SYMS:
    try: px[s]=fetch(s)
    except Exception as e: print(f"{s} fetch fail: {e}")

p=pd.DataFrame(px).ffill().dropna()
print(f"1h bars: {len(p)} rows, {p.index[0]} .. {p.index[-1]}")

# Intraday time-series momentum: sign of past L return -> next H return (long-only)
print(f"\n{'L':>3} {'H':>3} {'mom net20bp':>12} {'basket':>9} {'ALPHA':>9} {'t':>7}")
for L in [4,12,24]:
    for H in [4,12]:
        past=p.pct_change(L); fwd=p.pct_change(H).shift(-H)
        sig=(past>0).astype(float)
        ts=(sig*fwd).mean(axis=1); flip=(sig.diff().abs()).mean(axis=1); cost=flip*0.002
        ts=ts-cost; bk=fwd.mean(axis=1)
        d=pd.DataFrame({'ts':ts,'bk':bk}).dropna()
        a=d['ts']-d['bk']
        t=a.mean()/a.std()*np.sqrt(len(a))
        print(f"{L:>3} {H:>3} {d['ts'].mean()*1e4:>+11.1f}bp {d['bk'].mean()*1e4:>+8.1f}bp {a.mean()*1e4:>+8.1f}bp {t:>6.2f}")

# Liquidation-cascade: after an extreme -5% hour, does next 4h continue or reverse?
print("\nLiquidation-cascade (extreme -4% 1h candle -> next 4h):")
extreme=(p.pct_change()<-0.04)
fwd4=p.pct_change(4).shift(-4)
cont=[]; rev=[]
for s in SYMS:
    e=extreme[s]; f=fwd4[s]
    m=pd.DataFrame({'e':e,'f':f}).dropna()
    cont.append(m[m['e']]['f']); rev.append(m[~m['e']]['f'])
c=pd.concat(cont); r=pd.concat(rev)
print(f"  after -4% hour: next4h {c.mean()*1e4:+.1f}bp (n={len(c)}) vs unconditional {r.mean()*1e4:+.1f}bp")
