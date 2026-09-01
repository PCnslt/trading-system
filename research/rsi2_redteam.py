import boto3, io, pandas as pd, numpy as np, re

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
r=s3.list_objects_v2(Bucket=BUCKET, Prefix='ibkr/equities/daily/', MaxKeys=400)
keys=[o['Key'] for o in r.get('Contents',[]) if o['Key'].endswith('.parquet')]
def is_common(s): return not re.search(r'[-.][WURPS]A?B?$|[-.]U$|PR[ABCDEFG]?$|[-.]WS$|[-.]WT$', s)
syms=[k.split('/')[-1].replace('.parquet','') for k in keys]
syms=sorted(set(s for s in syms if is_common(s)))
COST=0.0005

def load(sym):
    b=s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')['Body'].read()
    d=pd.read_parquet(io.BytesIO(b)).sort_index()
    d.columns=[c.lower() for c in d.columns]; return d

frames=[]
for s in syms:
    try: d=load(s)
    except Exception: continue
    if len(d)<400: continue
    c=d['close']; o=d['open']; v=d['volume']
    chg=c.diff(); up=chg.clip(lower=0).rolling(2).mean(); dn=(-chg.clip(upper=0)).rolling(2).mean()
    rsi2=100-100/(1+up/(dn+1e-12))
    roc=c/o-1; rco=o/c.shift(1)-1; ret=c.pct_change()
    df=pd.DataFrame({'rsi2':rsi2,'roc':roc,'rco':rco,'ret':ret}).dropna()
    if len(df)<300: continue
    df['sym']=s; frames.append(df)
p=pd.concat(frames); p['date']=p.index
print('=== threshold perturbation (RSI2 < X, intraday open->close) ===')
for th in [5,10,15,20,25,30]:
    sig=(p['rsi2']<th).astype(int)
    pnl=sig.shift(1)*p['roc']-COST*sig.shift(1).abs()
    print(f'  RSI2<{th:2d}: exp={pnl.mean()*1e4:+.2f}bp  PF={pnl[pnl>0].sum()/-pnl[pnl<0].sum():.2f}  n={int(sig.sum())}')
print('=== return-basis decomposition (RSI2<10) ===')
sig=(p['rsi2']<10).astype(int).shift(1)
for nm,col in [('overnight close->open','rco'),('intraday open->close','roc'),('full day close->close','ret')]:
    pnl=sig*p[col]-COST*sig.abs()
    print(f'  {nm:24s}: exp={pnl.mean()*1e4:+.2f}bp PF={pnl[pnl>0].sum()/-pnl[pnl<0].sum():.2f}')
print('=== clustered (daily-mean) significance, RSI2<10 intraday ===')
sig=(p['rsi2']<10).astype(int).shift(1); pnl=sig*p['roc']-COST*sig.abs()
daily=pnl.groupby(p['date']).mean()  # daily cross-sectional mean
t=daily.mean()/(daily.std()/np.sqrt(len(daily)))
print(f'  daily n={len(daily)}, mean={daily.mean()*1e4:+.2f}bp, t={t:.2f}')
print('=== walk-forward (5 chronological folds) RSI2<10 ===')
dates=np.sort(p['date'].unique()); edges=np.array_split(dates,5)
for i in range(1,5):
    tr_d=dates[:edges[i][0]]; te_d=dates[edges[i][0]:edges[i][-1]]
    te=pnl[p['date'].isin(te_d)]
    print(f'  fold {i} (OOS from {te_d[0].date()}): exp={te.mean()*1e4:+.2f}bp PF={te[te>0].sum()/-te[te<0].sum():.2f} n={int(te.abs().sum())}')
