import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
r = s3.list_objects_v2(Bucket=BUCKET, Prefix='ibkr/equities/daily/')
keys = [o['Key'] for o in r.get('Contents', [])]

ovn, intr = [], []
for k in keys:
    try:
        d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=BUCKET, Key=k)['Body'].read()))
    except Exception:
        continue
    if 'open' not in d or 'close' not in d: continue
    d = d.dropna(subset=['open', 'close'])
    if len(d) < 250: continue
    o = d['open'].values; c = d['close'].values
    # overnight = open[t]/close[t-1]-1 ; intraday = close[t]/open[t]-1
    ovn.append((o[1:] / c[:-1] - 1))
    intr.append((c[1:] / o[1:] - 1))

ovn = np.concatenate(ovn); intr = np.concatenate(intr)
n = len(ovn)
print(f"observations (stock-days): {n}")
print(f"OVERNIGHT (close->open): mean {ovn.mean()*1e4:+.2f}bp  median {np.median(ovn)*1e4:+.2f}bp  std {ovn.std()*1e4:.1f}bp  t={ovn.mean()/ovn.std()*np.sqrt(n):.1f}")
print(f"INTRADAY (open->close): mean {intr.mean()*1e4:+.2f}bp  median {np.median(intr)*1e4:+.2f}bp  std {intr.std()*1e4:.1f}bp  t={intr.mean()/intr.std()*np.sqrt(n):.1f}")
print(f"overnight share of total daily return: {ovn.mean()/(ovn.mean()+intr.mean())*100:.0f}%")
