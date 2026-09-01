import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
P5='ibkr/equities/5min/'
def load5(sym):
    o=s3.get_object(Bucket=BUCKET,Key=P5+sym+'.parquet')['Body'].read()
    df=pd.read_parquet(io.BytesIO(o)); df['date']=pd.to_datetime(df['date'])
    return df.set_index('date').tz_localize(None)
done=[l.split(':')[0].strip() for l in open('/tmp/intraday_backfill.log') if 'bars 2026' in l]
print(f'n symbols: {len(done)}')

rets={}
for sym in done:
    try:
        m5=load5(sym); rets[sym]=m5['close'].resample('30min').last().pct_change()
    except: pass
panel=pd.DataFrame(rets)  # rows=timestamps, cols=symbols

# intraday cross-sectional reversal: losers (bottom quintile) vs winners (top quintile) next 30m
rows=[]
for ts,row in panel.iterrows():
    r=row.dropna()
    if len(r)<10: continue
    q=r.quantile(0.2); top=r.quantile(0.8)
    losers=r[r<=q].index; winners=r[r>=top].index
    nxt=panel.shift(-1).loc[ts]
    rows.append({'disp':r.std(), 'loser_fut':nxt[losers].mean(), 'winner_fut':nxt[winners].mean()})
d=pd.DataFrame(rows).dropna()
# reversal: losers outperform winners next period
d['rev']=d['loser_fut']-d['winner_fut']
print(f'[cross-sectional reversal] next-30m (loser - winner) = {d["rev"].mean()*10000:.1f}bp  n={len(d)}')
print(f'  P(rev>0) = {(d["rev"]>0).mean():.3f}')
# dispersion persistence: does high dispersion predict next-period dispersion?
d['disp_next']=d['disp'].shift(-1)
corr=d['disp'].corr(d['disp_next'])
print(f'[dispersion] corr(disp, disp_next) = {corr:.3f}  (persistence)')
# high dispersion -> next-period cross-sectional reversal stronger?
hi=d[d['disp']>d['disp'].median()]
print(f'  high-disp next-30m reversal = {hi["rev"].mean()*10000:.1f}bp  vs low-disp {d[d["disp"]<=d["disp"].median()]["rev"].mean()*10000:.1f}bp')
