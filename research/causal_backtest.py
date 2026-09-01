import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS = ['AAPL','AMD','AMZN','AVGO','GOOGL','META','MSFT','MU','NFLX','NVDA','ORCL','PLTR','TSLA','INTC','LLY','TSM']

def load(sym):
    r=s3.list_objects_v2(Bucket=BUCKET,Prefix=f'ibkr/equities/1min/{sym}/')
    fr=[pd.read_parquet(io.BytesIO(s3.get_object(Bucket=BUCKET,Key=o['Key'])['Body'].read())) for o in r.get('Contents',[])]
    if not fr: return None
    df=pd.concat(fr).sort_values('ts'); df['ts']=pd.to_datetime(df['ts'],unit='s')
    return df.set_index('ts').sort_index()

def backtest(causal=True):
    """causal=True: intraday-volume vs same-time-of-day 20d avg.
       causal=False (OLD): full-day volume vs 20d avg day volume (look-ahead)."""
    rows=[]
    for sym in SYMS:
        df=load(sym)
        if df is None or len(df)<3000: continue
        o=df['open'].resample('1D').first(); c=df['close'].resample('1D').last(); v=df['volume'].resample('1D').sum()
        d=pd.DataFrame({'open':o,'close':c,'vol':v}).dropna()
        d['gap']=d['open']/d['close'].shift(1)-1
        d['avol']=d['vol']/d['vol'].rolling(20).mean()
        df['m']=df.index.hour*60+df.index.minute
        df['day']=df.index.date
        df['cumvol']=df.groupby('day')['volume'].cumsum()
        for day,r in d.iterrows():
            if abs(r['gap'])<0.02: continue
            intra=df[df.index.date==day.date()]
            if len(intra)<30: continue
            op=r['open']; sgn=np.sign(r['gap'])
            cum=intra['close']/op-1
            li=cum[cum*sgn>=0.005]
            if len(li)==0: continue
            t0=li.index[0]
            if causal:
                m=t0.hour*60+t0.minute
                cv=intra.loc[t0,'cumvol']
                prior=df[(df.index.date<day.date())&(df['m']==m)]
                if len(prior)==0: continue
                base=prior.groupby(prior.index.date)['cumvol'].last().mean()
                if base<=0 or cv < 1.5*base: continue
            else:
                if d.loc[day,'avol']<1.5: continue
            # trade: entry at confirmation, stop 0.5% target 2%
            ep=intra.loc[t0,'close']; sub=intra[intra.index>=t0]['close']; ret=sub/ep-1
            sret=ret*sgn
            sh=sret[sret<=-0.005]; th=sret[sret>=0.02]
            si=(sh.index[0]-t0).total_seconds()/60 if len(sh) else np.nan
            ti=(th.index[0]-t0).total_seconds()/60 if len(th) else np.nan
            if np.isnan(si) and np.isnan(ti): continue
            win=(not np.isnan(ti)) and (np.isnan(si) or ti<si)
            pnl=0.02 if win else -0.005
            rows.append(dict(sym=sym, win=int(win), pnl=pnl, hold=ti if win else si, d=day))
    return pd.DataFrame(rows)

def rep(T,label):
    if len(T)==0: print(f"{label}: NO EVENTS"); return
    exp=T.pnl.mean()*100; wr=T.win.mean()*100
    pf=T[T.pnl>0].pnl.sum()/abs(T[T.pnl<0].pnl.sum()) if (T.pnl<0).any() else 99
    m=T.d.nunique()
    print(f"{label}: N={len(T)} win={wr:.1f}% exp={exp:+.2f}% PF={pf:.2f} medHold={T.hold.median():.0f}m trades/mo={len(T)/m:.1f}")

print("=== OLD (retrospective full-day volume) vs CORRECTED (causal intraday volume) ===")
rep(backtest(causal=False), "OLD    ")
rep(backtest(causal=True),  "CORRECTED")
