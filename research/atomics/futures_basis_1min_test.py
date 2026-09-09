"""EXACT 1-min 'Overnight Futures Basis Mispricing' test (09:31->10:00). v2.

Anchors (bar-start labeling): ES open = 09:30 open (proxy for 09:29); ES prev close =
last close <=16:15; SPY open = 09:30 open; SPY prev close = last close <=16:00 (15:59 bar);
entry = 09:31 open; exit = 10:00 open. 2bp RT. Placebo = shuffled basis_delta.
"""
import boto3, io, pandas as pd, numpy as np
from scipy import stats as st

s3=boto3.client('s3',region_name='us-east-1'); b='trading-datalake-920641308584'

frames=[]
for m in ['2026-06','2026-07','2026-08','2026-09']:
    df=pd.read_parquet(io.BytesIO(s3.get_object(Bucket=b,Key=f'ibkr/futures/1min/ES/{m}.parquet')['Body'].read()))
    df['ts']=pd.to_datetime(df['ts'],unit='s',utc=True).dt.tz_convert('America/New_York').dt.tz_localize(None)
    real=(df['open']!=df['high'])|(df['high']!=df['low'])|(df['low']!=df['close'])|(df['volume']>0)
    frames.append(df[real])
es=pd.concat(frames).sort_values('ts').drop_duplicates('ts').set_index('ts')

spy=pd.read_parquet('/home/ubuntu/trading-system/research/atomics/spy_1min_2026.parquet')
spy['ts']=pd.to_datetime(spy['date']).dt.tz_localize(None)
spy=spy.set_index('ts').sort_index()

def first_open(df, hh, mm):
    d=df[(df.index.hour==hh)&(df.index.minute==mm)]
    return d['open'].resample('1D').first()
def last_close(df, hh, mm):
    d=df[(df.index.hour*60+df.index.minute)<=(hh*60+mm)]
    return d['close'].resample('1D').last()

es_open = first_open(es, 9, 30)      # ~09:29 futures
es_prev = last_close(es, 16, 15)     # futures prev close (settlement)
spy_open= first_open(spy, 9, 30)     # cash open print
spy_prev= last_close(spy, 16, 0)     # cash prev close (15:59 bar)
spy_ent = first_open(spy, 9, 31)     # entry
spy_exit= first_open(spy, 10, 0)     # exit

idx = sorted(set(es.index.normalize()) & set(spy.index.normalize()))
D = pd.DataFrame(index=pd.DatetimeIndex(idx))
D['es_open']=es_open.reindex(D.index); D['es_prev']=es_prev.reindex(D.index)
D['spy_open']=spy_open.reindex(D.index); D['spy_prev']=spy_prev.reindex(D.index)
D['spy_ent']=spy_ent.reindex(D.index); D['spy_exit']=spy_exit.reindex(D.index)

D['futures_gap']=D['es_open']/D['es_prev'].shift(1)-1
D['cash_gap']=D['spy_open']/D['spy_prev'].shift(1)-1
D['basis_delta']=D['futures_gap']-D['cash_gap']
D['bd_std']=D['basis_delta'].rolling(20).std()
D['bd_z']=D['basis_delta']/D['bd_std']
D['ret']=D['spy_exit']/D['spy_ent']-1

D=D.dropna(subset=['bd_z','ret'])
print(f"aligned days={len(D)}  basis_delta mean={D['basis_delta'].mean()*1e4:.1f}bp std={D['basis_delta'].std()*1e4:.1f}bp autocorr={D['basis_delta'].autocorr(1):+.2f}")

COST=0.0002
def run(z, ret, seed=None):
    z=pd.Series(z)
    if seed is not None: z=pd.Series(np.random.default_rng(seed).permutation(z.values),index=z.index)
    long_s=z<-1.5; short_s=z>1.5; sig=long_s|short_s
    pnl=pd.Series(np.nan,index=z.index)
    pnl[long_s]= ret[long_s]-COST
    pnl[short_s]=-ret[short_s]-COST
    s=pnl[sig]; n=int(sig.sum())
    if n==0: return dict(n=0, mean_bp=np.nan, t=np.nan, win=np.nan)
    m=s.mean(); t=m/(s.std()/np.sqrt(n)) if n>1 else np.nan
    return dict(n=n, mean_bp=m*1e4, t=t, win=(s>0).mean())

real=run(D['bd_z'], D['ret'])
print(f"\nREAL fade (|z|>1.5): n={real['n']}  mean={real['mean_bp']:+.1f}bp  t={real['t']:+.2f}  win={real['win']:.0%}")

tp=[]
for s in range(500):
    p=run(D['bd_z'], D['ret'], seed=s)
    if p['n']>=2 and not np.isnan(p['t']): tp.append(p['t'])
if len(tp)>=10:
    tp=np.array(tp)
    print(f"placebo t-dist: mean={tp.mean():+.2f} p95={np.percentile(tp,95):+.2f}")
    print(f"real t={real['t']:+.2f} vs placebo p95={np.percentile(tp,95):+.2f} -> "
          f"{'REJECT (fails placebo)' if real['t']<np.percentile(tp,95) else 'pass'}")
else:
    print(f"placebo: SKIPPED — only {real['n']} signal events in 42d (too few for placebo/t-stat)")

c=np.corrcoef(D['basis_delta'], D['ret'])[0,1]
tt=c*np.sqrt((len(D)-2)/(1-c*c))
print(f"\ncorr(basis_delta, fwd 30-min SPY ret) = {c:+.3f}  t={tt:+.2f}  (fade needs NEGATIVE |t|>=2)")

for lbl, zsel, sgn in [('LONG BD<-1.5', D['bd_z']<-1.5, 1), ('SHORT BD>+1.5', D['bd_z']>1.5, -1)]:
    s=D['ret'][zsel]*sgn-COST
    print(f"  {lbl}: n={len(s)} mean={s.mean()*1e4:+.1f}bp")
