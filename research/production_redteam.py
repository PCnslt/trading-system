import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS = ['AAPL','AMD','AMZN','AVGO','GOOGL','META','MSFT','MU','NFLX','NVDA','ORCL','PLTR','TSLA','INTC','LLY','TSM']

def load(sym):
    r=s3.list_objects_v2(Bucket=BUCKET,Prefix=f'ibkr/equities/1min/{sym}/')
    fr=[pd.read_parquet(io.BytesIO(s3.get_object(Bucket=BUCKET,Key=o['Key'])['Body'].read())) for o in r.get('Contents',[])]
    if not fr: return None
    df=pd.concat(fr).sort_values('ts'); df['ts']=pd.to_datetime(df['ts'],unit='s')
    return df.set_index('ts').sort_index()

def trades(stop=0.005, tgt=0.02, confirm=0.005, slip=0.0, lat=0):
    out=[]
    for sym in SYMS:
        df=load(sym)
        if df is None or len(df)<3000: continue
        o=df['open'].resample('1D').first(); c=df['close'].resample('1D').last(); v=df['volume'].resample('1D').sum()
        d=pd.DataFrame({'open':o,'close':c,'vol':v}).dropna()
        d['gap']=d['open']/d['close'].shift(1)-1; d['avol']=d['vol']/d['vol'].rolling(20).mean()
        ev=d[(d['gap'].abs()>=0.02)&(d['avol']>=1.5)]
        for day,r in ev.iterrows():
            intra=df[df.index.date==day.date()]
            if len(intra)<30: continue
            op=r['open']; sgn=np.sign(r['gap'])
            cum=intra['close']/op-1
            li=cum[cum*sgn>=confirm]
            if len(li)==0: continue
            t0=li.index[0]
            # latency: shift entry forward by 'lat' bars
            pos=intra.index.get_loc(t0)+lat
            if pos>=len(intra): continue
            t1=intra.index[pos]; ep=intra.loc[t1,'close']
            sub=intra[intra.index>=t1]['close']; ret=sub/ep-1
            sret=ret*sgn
            stop_hit=sret[sret<=-stop]; tgt_hit=sret[sret>=tgt]
            si=(stop_hit.index[0]-t1).total_seconds()/60 if len(stop_hit) else np.nan
            ti=(tgt_hit.index[0]-t1).total_seconds()/60 if len(tgt_hit) else np.nan
            if np.isnan(si) and np.isnan(ti): continue
            win=(not np.isnan(ti)) and (np.isnan(si) or ti<si)
            pnl=(tgt if win else -stop) - slip  # slip in % of underlying, round-trip
            out.append(dict(sym=sym, win=int(win), pnl=pnl, d=day))
    return pd.DataFrame(out)

T=trades()
n=len(T)
print(f"trades={n}")

# 5. SLIPPAGE STRESS
print("\n=== SLIPPAGE STRESS (expectancy%, PF) ===")
for slip in [0,0.0002,0.0005,0.001,0.002,0.003,0.005]:
    T=trades(slip=slip)
    exp=T.pnl.mean()*100
    pf=T[T.pnl>0].pnl.sum()/abs(T[T.pnl<0].pnl.sum()) if (T.pnl<0).any() else 99
    print(f"slip {slip*10000:.0f}bps: exp={exp:+.2f}% PF={pf:.2f}")

# 6. LATENCY STRESS (bars of delay, ~1min each)
print("\n=== LATENCY STRESS (expectancy%) ===")
for lat in [0,1,2,3,5,10]:
    T=trades(lat=lat)
    if len(T)==0: continue
    print(f"lat {lat}bar(s): exp={T.pnl.mean()*100:+.2f}% N={len(T)}")

# 11. OUTLIER TEST
print("\n=== OUTLIER CONTRIBUTION ===")
T=trades()
T=T.sort_values('pnl',ascending=False)
tot=T.pnl.sum()
for k in [1,5,10]:
    print(f"top {k}: {T.pnl.head(k).sum()/tot*100:.0f}% of total P&L")
print(f"total P&L = {tot*100:+.1f}% (sum of {n} trades)")

# 12. SYMBOL CONCENTRATION
print("\n=== SYMBOL CONCENTRATION (P&L contribution) ===")
g=T.groupby('sym').pnl.agg(['sum','count'])
g['contrib']=g['sum']/tot*100
print(g.sort_values('sum',ascending=False).head(6).round(1).to_string())

# 9. CAPITAL REALITY ($700, whole shares)
print("\n=== CAPITAL REALITY ($700) ===")
exp_per_trade=T.pnl.mean()*100
# assume $100 avg stock, 7 shares max (~$700)
# $700 / avg_price... use a simple $100/share -> 7 shares
shares=7
dollars_per_trade=exp_per_trade/100*100*shares  # exp% * share price * shares
sigs_per_month=len(T)/ (len(SYMS)*22)  # rough: trades per symbol-month... 
# better: count unique months
T['ym']=pd.to_datetime(T['d']).dt.to_period('M')
months=T['ym'].nunique()
trades_per_month=n/months
print(f"unique months={months}, trades={n}, trades/month={trades_per_month:.1f}")
print(f"expectancy/trade={exp_per_trade:+.2f}% -> on $700 (7 shares @$100) = ${dollars_per_trade:+.2f}/trade")
print(f"est $/month = ${dollars_per_trade*trades_per_month:+.2f}")

# 10. STOP/TARGET PLATEAU
print("\n=== STOP/TARGET PLATEAU (expectancy%, PF) ===")
for stop in [0.0025,0.005,0.0075,0.01]:
    row=[]
    for tgt in [0.01,0.015,0.02,0.025,0.03]:
        T=trades(stop,tgt)
        pf=T[T.pnl>0].pnl.sum()/abs(T[T.pnl<0].pnl.sum()) if (T.pnl<0).any() else 99
        row.append(f"{T.pnl.mean()*100:+.2f}/{pf:.1f}")
    print(f"stop {stop*100:.2f}: "+" | ".join(row))
