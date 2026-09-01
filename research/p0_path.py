import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS = ['AAPL','AMD','AMZN','AVGO','GOOGL','META','MSFT','MU','NFLX','NVDA','ORCL','PLTR','TSLA','INTC','LLY','TSM']

def load(sym):
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=f'ibkr/equities/1min/{sym}/')
    frames=[pd.read_parquet(io.BytesIO(s3.get_object(Bucket=BUCKET, Key=o['Key'])['Body'].read())) for o in r.get('Contents',[])]
    if not frames: return None
    df=pd.concat(frames).sort_values('ts'); df['ts']=pd.to_datetime(df['ts'],unit='s')
    return df.set_index('ts').sort_index()

rows=[]
for sym in SYMS:
    df=load(sym)
    if df is None or len(df)<3000: continue
    o=df['open'].resample('1D').first(); c=df['close'].resample('1D').last(); v=df['volume'].resample('1D').sum()
    d=pd.DataFrame({'open':o,'close':c,'vol':v}).dropna()
    d['gap']=d['open']/d['close'].shift(1)-1
    d['avol']=d['vol']/d['vol'].rolling(20).mean()
    ev=d[(d['gap'].abs()>=0.02)&(d['avol']>=1.5)]
    for day, r in ev.iterrows():
        intra=df[(df.index.date==day.date())]
        if len(intra)<30: continue
        op=r['open']; sgn=np.sign(r['gap'])
        cum=intra['close']/op-1
        # first 0.5% move direction (relative to gap direction)
        first_half = cum[cum.abs()>=0.005]
        first_half_dir = np.sign(first_half.iloc[0])*sgn if len(first_half) else 0  # +1=with gap, -1=against
        # which 2% target hits first
        hit_up = cum[cum>=0.02]; hit_dn = cum[cum<=-0.02]
        first_up = (hit_up.index[0]-intra.index[0]).total_seconds()/60 if len(hit_up) else np.nan
        first_dn = (hit_dn.index[0]-intra.index[0]).total_seconds()/60 if len(hit_dn) else np.nan
        if sgn>0: win = (not np.isnan(first_up)) and (np.isnan(first_dn) or first_up<first_dn)
        else: win = (not np.isnan(first_dn)) and (np.isnan(first_up) or first_dn<first_up)
        # adverse excursion before first 0.5% confirmation (vs gap dir)
        adv = (cum*sgn).min() if len(first_half) else np.nan
        rows.append(dict(sgn=sgn, win=win, first_half_dir=first_half_dir,
                         adv_before_confirm=adv, gap=abs(r['gap']), avol=r['avol'],
                         hod=day.hour, is_up=r['gap']>0))

E=pd.DataFrame(rows)
print(f"events: {len(E)}  |  overall P(win): {E.win.mean():.1%}")
print("\n=== PATH: does first 0.5% move predict the winner? ===")
for fd,lab in [(1,'first 0.5% WITH gap'),(-1,'first 0.5% AGAINST gap'),(0,'no 0.5% move')]:
    sub=E[E.first_half_dir==fd]
    if len(sub): print(f"  {lab:24s}: n={len(sub):3d}  P(win)={sub.win.mean():.1%}")
print("\n=== REGIMES: is 49% a mixture? ===")
for col,bins in [('gap',[0.02,0.04,1.0]),('avol',[0,2.5,99])]:
    E['b']=pd.cut(E[col],bins)
    print(f"  by {col}: " + " | ".join(f"{i.left}-{i.right}: {g.win.mean():.0%} (n={len(g)})" for i,g in E.groupby('b',observed=True)))
print(f"  by direction: up-gap {E[E.is_up].win.mean():.0%} vs down-gap {E[~E.is_up].win.mean():.0%}")
print(f"\n=== EARLY INVALIDATION (exit signal) ===")
print(f"  P(win | adverse < 0.5% before confirm) = {E[E.adv_before_confirm>-0.005].win.mean():.1%}")
print(f"  P(win | adverse >= 0.5% before confirm) = {E[E.adv_before_confirm<=-0.005].win.mean():.1%}")
