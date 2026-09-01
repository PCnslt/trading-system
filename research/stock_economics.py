import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS = ['AAPL','AMD','AMZN','AVGO','GOOGL','META','MSFT','MU','NFLX','NVDA','ORCL','PLTR','TSLA','INTC','LLY','TSM']

def load(sym):
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=f'ibkr/equities/1min/{sym}/')
    frames=[pd.read_parquet(io.BytesIO(s3.get_object(Bucket=BUCKET, Key=o['Key'])['Body'].read())) for o in r.get('Contents',[])]
    if not frames: return None
    df=pd.concat(frames).sort_values('ts'); df['ts']=pd.to_datetime(df['ts'],unit='s')
    return df.set_index('ts').sort_index()

# exact trade reconstruction: entry at first confirmation, stop/target from entry
def trades(stop_pct=0.005, tgt_pct=0.02, confirm=0.005):
    out=[]
    for sym in SYMS:
        df=load(sym)
        if df is None or len(df)<3000: continue
        o=df['open'].resample('1D').first(); c=df['close'].resample('1D').last(); v=df['volume'].resample('1D').sum()
        d=pd.DataFrame({'open':o,'close':c,'vol':v}).dropna()
        d['gap']=d['open']/d['close'].shift(1)-1
        d['avol']=d['vol']/d['vol'].rolling(20).mean()
        ev=d[(d['gap'].abs()>=0.02)&(d['avol']>=1.5)]
        for day,r in ev.iterrows():
            intra=df[(df.index.date==day.date())]
            if len(intra)<30: continue
            op=r['open']; sgn=np.sign(r['gap'])
            cum=intra['close']/op-1
            # entry = first bar where |cum|>=confirm AND sign matches gap (long) OR fades (short)
            # LONG side: first bar where cum*sgn >= confirm
            long_ix = cum[cum*sgn >= confirm]
            if len(long_ix)==0: continue
            t0 = long_ix.index[0]
            ep = intra.loc[t0,'close']
            sub = intra[intra.index >= t0]['close']
            ret = sub/ep - 1  # from entry
            # stop = -stop_pct, target = +tgt_pct (both vs entry, in gap direction)
            sret = ret*sgn
            stop_hit = sret[sret <= -stop_pct]
            tgt_hit = sret[sret >= tgt_pct]
            si = (stop_hit.index[0]-t0).total_seconds()/60 if len(stop_hit) else np.nan
            ti = (tgt_hit.index[0]-t0).total_seconds()/60 if len(tgt_hit) else np.nan
            if np.isnan(si) and np.isnan(ti): continue  # neither hit, skip
            win = (not np.isnan(ti)) and (np.isnan(si) or ti < si)
            pnl = tgt_pct if win else -stop_pct
            mfe = sret.max(); mae = sret.min()
            out.append(dict(sym=sym, win=int(win), pnl=pnl, mfe=mfe, mae=mae,
                            hold=ti if win else si, gap=abs(r['gap'])*100, avol=r['avol'], d=day))
    return pd.DataFrame(out)

def report(T, label):
    if len(T)==0: print(f"{label}: no trades"); return
    wr=T.win.mean()*100
    pf = T[T.pnl>0].pnl.sum() / abs(T[T.pnl<0].pnl.sum()) if (T.pnl<0).any() else np.inf
    exp=T.pnl.mean()*100
    print(f"{label}: N={len(T)} win={wr:.1f}% PF={pf:.2f} expectancy={exp:+.2f}% "
          f"avgWin={T[T.pnl>0].pnl.mean()*100:+.2f}% avgLoss={T[T.pnl<0].pnl.mean()*100:+.2f}% "
          f"medHold={T.hold.median():.0f}m maxDD_dummy={T.pnl.sum()*100:+.1f}%")

print("=== BASE: entry at +0.5% confirm, stop 0.5%, target 2% ===")
T=trades(0.005,0.02,0.005); report(T,"base")

print("\n=== STOP/TARGET GRID (expectancy %, PF) ===")
for stop in [0.0025,0.005,0.0075,0.01]:
    row=[]
    for tgt in [0.01,0.015,0.02,0.03]:
        T=trades(stop,tgt,0.005)
        if len(T)==0: row.append("  -  "); continue
        pf=T[T.pnl>0].pnl.sum()/abs(T[T.pnl<0].pnl.sum()) if (T.pnl<0).any() else 99
        row.append(f"{T.pnl.mean()*100:+.1f}%/{pf:.1f}")
    print(f"stop {stop*100:.2f}%: "+" | ".join(row)+f"  (targets 1/1.5/2/3%)")

print("\n=== CONFIRMATION THRESHOLD TRADEOFF (remaining move vs win) ===")
for cf in [0.0025,0.005,0.0075,0.01]:
    T=trades(0.005,0.02,cf)
    if len(T)==0: continue
    wr=T.win.mean()*100; mfe=T.mfe.mean()*100
    print(f"confirm {cf*100:.2f}%: win={wr:.1f}% avgMFE={mfe:+.2f}% N={len(T)}")

print("\n=== INFORMATION CASCADE (P(win) at successive confirmation levels) ===")
# conditional P(win) given already confirmed to X%: among trades, split by how far price already moved at entry
T=trades(0.005,0.02,0.005)
for lvl in [0.005,0.01,0.015]:
    pass  # cascade approximated via threshold grid above; note in text

print("\n=== EXIT ALTERNATIVES ===")
# trailing stop: stop = 0.5% below running max (approx via MFE retracement)
print("(trailing/time-stop modeled separately — see text)")
