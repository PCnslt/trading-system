import boto3, io, pandas as pd, numpy as np, re

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
r=s3.list_objects_v2(Bucket=BUCKET, Prefix='ibkr/equities/daily/', MaxKeys=400)
keys=[o['Key'] for o in r.get('Contents',[]) if o['Key'].endswith('.parquet')]

def is_common(sym):
    # drop warrants/units/preferred/rights/SPAC-suffixes
    return not re.search(r'[-.][WURPS]A?B?$|[-.]U$|PR[ABCDEFG]?$|[-.]WS$|[-.]WT$', sym)

syms=sorted(set(k.split('/')[-1].replace('.parquet','') for k in keys))
syms=[s for s in syms if is_common(s)]
print(f'common-stock symbols: {len(syms)}')

COST=0.0005  # 5 bps round-trip (conservative for liquid names)

def load(sym):
    b=s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')['Body'].read()
    d=pd.read_parquet(io.BytesIO(b))
    d=d.sort_index()
    d.columns=[c.lower() for c in d.columns]
    return d

# Build panel of daily returns + features
allr=[]; allsig=[]
for i,s in enumerate(syms):
    try: d=load(s)
    except Exception: continue
    if len(d)<400: continue
    o=d.get('open'); c=d.get('close'); v=d.get('volume')
    if o is None or c is None or v is None: continue
    ret=c.pct_change()                     # close-to-close (label basis)
    rco=(o/c.shift(1))-1                    # overnight (close t-1 -> open t)
    roc=(c/o)-1                             # intraday (open -> close)
    vol20=v.rolling(20).mean()
    rsi2=None
    # RSI(2) - Wilder
    chg=c.diff()
    up=chg.clip(lower=0).rolling(2).mean(); dn=(-chg.clip(upper=0)).rolling(2).mean()
    rs=up/(dn+1e-12); rsi2=100-100/(1+rs)
    don_hi=c.rolling(20).max().shift(1); don_lo=c.rolling(10).min().shift(1)
    # strategy signals (causal: known at close t)
    sig_mr = (rsi2<10).astype(int)
    sig_co = ((ret.shift(1)<0)&(v>1.5*vol20)).astype(int)  # down-day + vol gate -> buy close, sell next open
    sig_don = (c>don_hi).astype(int)
    df=pd.DataFrame({'ret':ret,'rco':rco,'roc':roc,'sig_mr':sig_mr,'sig_co':sig_co,'sig_don':sig_don})
    df=df.dropna()
    if len(df)<300: continue
    df['sym']=s
    allr.append(df[['ret','rco','roc','sig_mr','sig_co','sig_don','sym']])
panel=pd.concat(allr)
panel['date']=panel.index

def strat(sigcol, retcol):
    g=panel.dropna(subset=[retcol])
    s=g[sigcol]
    pnl=s.shift(1)*g[retcol]  # signal at t-1 -> return at t (entry t open after signal)
    pnl=pnl-COST*s.shift(1).abs()
    split=g['date'].quantile(0.7)
    tr=pnl[g['date']<split]; te=pnl[g['date']>=split]
    return tr, te

for name,sig,retcol in [('mean-reversion RSI2','sig_mr','roc'),
                        ('close-to-open volgate','sig_co','rco'),
                        ('donchian breakout','sig_don','ret')]:
    tr,te=strat(sig,retcol)
    n_tr,n_te=int(tr.abs().sum()),int(te.abs().sum())
    print(f'{name:26s} train exp={tr.mean()*1e4:+.2f}bp PF={tr[tr>0].sum()/-tr[tr<0].sum():.2f} n={n_tr} | OOS exp={te.mean()*1e4:+.2f}bp PF={te[te>0].sum()/-te[te<0].sum():.2f} n={n_te}')
