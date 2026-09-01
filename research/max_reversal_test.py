import os, io, json
import boto3, pandas as pd, numpy as np

S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'

def load_universe():
    with open('/home/ubuntu/trading-system/research/universe_1500.json') as f:
        u = json.load(f)
    return u['symbols'] if 'symbols' in u else list(u.keys())

def load_closes(syms, n=400):
    closes = {}
    for s in syms[:n]:
        try:
            o = S3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{s}.parquet')
            df = pd.read_parquet(io.BytesIO(o['Body'].read()))
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            if len(df) > 500:
                closes[s] = df['close']
        except Exception:
            pass
    return closes

def tstat(x):
    x = np.asarray(x)
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 5 else np.nan

def main():
    syms = load_universe()
    closes = load_closes(syms)
    print(f"loaded {len(closes)} stocks")
    # align to a common calendar (use the most common index)
    all_idx = None
    for s, c in closes.items():
        if all_idx is None:
            all_idx = c.index
        else:
            all_idx = all_idx.intersection(c.index)
    print(f"common dates: {len(all_idx)} {all_idx.min()}..{all_idx.max()}")

    # weekly rebalance every 5 trading days; compute MAX (21d) + prior-week return (5d)
    rows = []
    dates = list(all_idx)
    for i in range(21, len(dates) - 5, 5):   # weekly, skip 5d forward for return
        d = dates[i]
        prev5 = dates[i-5] if i >= 5 else dates[0]
        for s, c in closes.items():
            try:
                hist = c.loc[:d]
                if len(hist) < 30:
                    continue
                ret = hist.pct_change().dropna()
                if len(ret) < 21:
                    continue
                max21 = ret.iloc[-21:].max()          # MAX: max daily return past 21d
                week_ret = hist.iloc[-1] / hist.iloc[-6] - 1.0  # prior week return
                fwd = c.loc[dates[i+5]] / c.loc[d] - 1.0 if i+5 < len(dates) else np.nan
                rows.append({'sym': s, 'max21': max21, 'week': week_ret, 'fwd': fwd, 'date': d})
            except Exception:
                pass
    df = pd.DataFrame(rows).dropna(subset=['fwd'])
    df['max_q'] = pd.qcut(df['max21'], 5, labels=False)
    df['week_q'] = pd.qcut(df['week'], 5, labels=False)

    def bucket(mq, wq, label):
        sub = df[(df['max_q'] == mq) & (df['week_q'] == wq)]
        return sub['fwd'].mean()*100, sub['fwd'].median()*100, (sub['fwd']>0).mean()*100, tstat(sub['fwd']), len(sub)

    hi = 4
    print("\n=== HIGH-MAX reversal (paper: losers +0.89%, winners -0.77%) ===")
    for label, mq, wq in [('high-MAX WINNER (buy PUT)', hi, 4), ('high-MAX LOSER (buy CALL)', hi, 0)]:
        m, med, wr, t, n = bucket(mq, wq, label)
        print(f"  {label:28s} fwd {m:+6.2f}% med {med:+6.2f}% win {wr:4.0f}% t {t:+5.2f} n={n}")

    print("\n=== reversal spread (LOSER - WINNER), high-MAX vs low-MAX ===")
    for label, mq in [('HIGH-MAX', 4), ('LOW-MAX', 0)]:
        win = df[(df['max_q']==mq)&(df['week_q']==4)]['fwd']
        lose = df[(df['max_q']==mq)&(df['week_q']==0)]['fwd']
        sp = lose.mean() - win.mean()
        print(f"  {label:10s} loser {lose.mean()*100:+5.2f}%  winner {win.mean()*100:+5.2f}%  spread {sp*100:+5.2f}%  n={len(lose)}/{len(win)}")

    print("\n=== OOS: 2023-2026 only (post-publication) ===")
    df2 = df[df['date'] >= '2023-01-01']
    df2 = df2.copy()
    df2['max_q'] = pd.qcut(df2['max21'], 5, labels=False)
    df2['week_q'] = pd.qcut(df2['week'], 5, labels=False)
    for label, mq, wq in [('high-MAX WINNER (PUT)', 4, 4), ('high-MAX LOSER (CALL)', 4, 0)]:
        sub = df2[(df2['max_q']==mq)&(df2['week_q']==wq)]
        print(f"  {label:24s} fwd {sub['fwd'].mean()*100:+6.2f}% t {tstat(sub['fwd']):+5.2f} n={len(sub)}")
    win = df2[(df2['max_q']==4)&(df2['week_q']==4)]['fwd']
    lose = df2[(df2['max_q']==4)&(df2['week_q']==0)]['fwd']
    print(f"  high-MAX spread (loser-winner) 2023-26: {(lose.mean()-win.mean())*100:+5.2f}%")

if __name__ == '__main__':
    main()
