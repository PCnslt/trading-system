import json, boto3, pandas as pd, numpy as np
s3 = boto3.client('s3', region_name='us-east-1'); B = 'trading-datalake-920641308584'

# events (5,633, ordered) + already-resolved fwd30 (5,633, same order) -> positional join
body = s3.get_object(Bucket=B, Key='news/events/events.jsonl')['Body'].read().decode('utf-8')
ev = [json.loads(l) for l in body.splitlines() if l.strip()]
res = json.load(open('/tmp/news_resolved.json'))
assert len(ev) == len(res), f"length mismatch {len(ev)} vs {len(res)}"

df = pd.DataFrame(ev)
df['published_at'] = pd.to_datetime(df['published_at_utc'], errors='coerce')
df['observed_at'] = pd.to_datetime(df['observed_at_utc'], errors='coerce')
df['fwd30'] = [r['fwd30'] for r in res]
df = df.dropna(subset=['published_at', 'fwd30'])

# velocity: count articles for the SAME symbol published in [observed_at - 30m, observed_at]
df = df.sort_values(['symbol', 'observed_at'])
def velocity(g, win):
    pub = g['published_at'].values
    obs = g['observed_at'].values
    v = np.zeros(len(g))
    for i in range(len(g)):
        v[i] = ((pub < obs[i]) & (pub >= obs[i] - pd.Timedelta(minutes=win))).sum()
    return pd.Series(v, index=g.index)
df['vel30'] = df.groupby('symbol', group_keys=False).apply(lambda g: velocity(g, 30))

df['fwd30_bp'] = df['fwd30'] * 1e4
print("=== velocity (published_at) -> fwd30m return ===")
for lo, hi in [(0, 0), (1, 2), (3, 5), (6, 1000)]:
    m = (df['vel30'] >= lo) & (df['vel30'] <= hi)
    sub = df[m]
    if len(sub) == 0:
        continue
    print(f"vel30 {lo}-{hi}: n={len(sub)}, mean={sub['fwd30_bp'].mean():+.2f}bp, "
          f"P(up)={100*(sub['fwd30']>0).mean():.1f}%")
