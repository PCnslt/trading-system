import json, boto3, pandas as pd, numpy as np, time
from ib_insync import IB, Stock, util

s3 = boto3.client('s3', region_name='us-east-1'); B = 'trading-datalake-920641308584'

# --- load events ---
ev = [json.loads(l) for l in s3.get_object(Bucket=B, Key='news/events/events.jsonl')['Body'].read().decode().splitlines() if l.strip()]
df = pd.DataFrame(ev)
df['observed_at'] = pd.to_datetime(df['observed_at_utc'], utc=True, errors='coerce')
df = df.dropna(subset=['observed_at']).sort_values('observed_at')

# --- fetch 5-min prices for the 40 symbols (past ~8 days) ---
syms = sorted(df['symbol'].unique())
ib = IB(); ib.connect('127.0.0.1', 4001, clientId=210, timeout=20)
px = {}
for s in syms:
    try:
        c = Stock(s, 'SMART', 'USD'); ib.qualifyContracts(c)
        bars = ib.reqHistoricalData(c, '', '8 D', '5 mins', 'TRADES', useRTH=True, formatDate=2)
        d = util.df(bars)
        if len(d):
            d = d.set_index('date'); d.index = pd.to_datetime(d.index, utc=True)
            px[s] = d['close']
    except Exception as e:
        pass
    time.sleep(0.3)
ib.disconnect()
print(f'fetched prices for {len(px)}/{len(syms)} symbols')

# --- resolve 30m forward return for each event ---
def fwd_ret(sym, t, minutes):
    s = px.get(sym)
    if s is None: return np.nan
    fut = s[s.index >= t]
    if len(fut) < 2: return np.nan
    entry = fut.iloc[0]
    # find bar ~ minutes later
    tgt = t + pd.Timedelta(minutes=minutes)
    later = s[s.index <= tgt + pd.Timedelta(minutes=6)]
    if len(later) < 2: return np.nan
    exitp = later.iloc[-1]
    return (exitp / entry - 1) * 1e4  # bp

df['fwd30'] = [fwd_ret(r.symbol, r.observed_at, 30) for r in df.itertuples()]

# --- news velocity: events per symbol in prior 30m ---
def velocity(sym, t, window_min):
    w = df[(df.symbol == sym) & (df.observed_at < t) & (df.observed_at >= t - pd.Timedelta(minutes=window_min))]
    return len(w)

df['vel30'] = [velocity(r.symbol, r.observed_at, 30) for r in df.itertuples()]

res = df.dropna(subset=['fwd30'])
print(f'\nresolved outcomes: {len(res)} events')

# --- test: does velocity predict continuation/reversal? ---
base = res['fwd30'].mean()
print(f'\nUNCONDITIONAL: mean 30m fwd = {base:+.2f}bp, P(up)={100*(res["fwd30"]>0).mean():.1f}%, n={len(res)}')
for lo, hi, label in [(0,0,'vel=0 (no prior news)'), (1,3,'vel=1-3'), (4,100,'vel>=4 (news burst)')]:
    sub = res[(res['vel30']>=lo) & (res['vel30']<=hi)]
    if len(sub) >= 20:
        print(f'  {label}: mean={sub["fwd30"].mean():+.2f}bp, P(up)={100*(sub["fwd30"]>0).mean():.1f}%, n={len(sub)}')

# direction: does an event's implied direction (symbol momentum at event) continue?
# save resolved for later
res[['symbol','observed_at','fwd30','vel30']].to_json('/tmp/news_resolved.json', orient='records', date_format='iso')
print('\ndone')
