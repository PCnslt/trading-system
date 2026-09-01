import boto3, json, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','AVAXUSDT','LINKUSDT','LTCUSDT','BCHUSDT','ADAUSDT','DOTUSDT','UNIUSDT','AAVEUSDT']

def load(s):
    d=json.loads(s3.get_object(Bucket=BUCKET, Key=f'crypto-hist/{s}/daily.json')['Body'].read())['bars']
    df=pd.DataFrame(d); df['date']=pd.to_datetime(df['date']); df=df.set_index('date')
    return df['close']

px=pd.DataFrame({s:load(s) for s in SYMS}).ffill()
px=px[px.notna().sum(axis=1)>=6]

print("Long-only TIME-SERIES momentum (sign of own past return): L=lookback, H=hold")
print(f"{'L':>2} {'H':>2} {'TSMOM net':>11} {'basket':>9} {'ALPHA':>9} {'t_alpha':>8} {'t_nonov':>8} {'n':>6}")
for L in [3,7,14,30]:
    for H in [3,7,14]:
        past=px.pct_change(L)               # own past L-day return
        fwd=px.pct_change(H).shift(-H)      # own future H-day return
        sig=(past>0).astype(float)          # long if own past return > 0, else flat
        # TSMOM portfolio = equal weight of long coins, net of 20bp
        # return per day = (sig * fwd).mean(axis=1) - cost applied on turn
        raw=(sig*fwd).mean(axis=1)
        # turnover cost: fraction of coins flipping sign each rebalance * 20bp
        flip=(sig.diff().abs()).mean(axis=1)
        cost=flip*0.002
        ts=raw-cost
        basket=fwd.mean(axis=1)
        both=pd.DataFrame({'ts':ts,'bk':basket}).dropna()
        alpha=both['ts']-both['bk']
        t_alpha=alpha.mean()/alpha.std()*np.sqrt(len(alpha))
        nono=alpha.iloc[::H]
        t_nono=nono.mean()/nono.std()*np.sqrt(len(nono))
        print(f"{L:>2} {H:>2} {both['ts'].mean()*1e4:>+10.1f}bp {both['bk'].mean()*1e4:>+8.1f}bp {alpha.mean()*1e4:>+8.1f}bp {t_alpha:>7.2f} {t_nono:>7.2f} {len(alpha):>6}")

# Placebo: shuffle the sign
print("\nPlacebo (shuffled signs, L14/H7):")
L,H=14,7
past=px.pct_change(L); fwd=px.pct_change(H).shift(-H)
rng=np.random.default_rng(0)
sig_sh=(past>0).astype(float); sig_sh[:]=rng.permutation(sig_sh.values, axis=1)
raw=(sig_sh*fwd).mean(axis=1); flip=(sig_sh.diff().abs()).mean(axis=1)
ts=raw-flip*0.002; bk=fwd.mean(axis=1)
both=pd.DataFrame({'ts':ts,'bk':bk}).dropna()
a=both['ts']-both['bk']
print(f"   shuffled TSMOM net {both['ts'].mean()*1e4:+.1f}bp, alpha {a.mean()*1e4:+.1f}bp (t={a.mean()/a.std()*np.sqrt(len(a)):.2f})")
