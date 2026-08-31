import os, io, json, time
import datetime as dt
import urllib.request, urllib.parse
from zoneinfo import ZoneInfo
import boto3, pandas as pd, numpy as np

ET = ZoneInfo('America/New_York')
S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'
AV_KEY = None
for line in open('/home/ubuntu/trading-system/.env'):
    if line.startswith('ALPHAVANTAGE_API_KEY='):
        AV_KEY = line.split('=',1)[1].strip()

def load_universe():
    d = json.load(open('/home/ubuntu/trading-system/research/universe_1500.json'))
    syms = d['symbols'] if isinstance(d, dict) else d
    return [s for s in syms if isinstance(s, str)][:20]  # top 20 liquid (within 25/day quota)

def fetch_earnings(sym):
    url = f'https://www.alphavantage.co/query?function=EARNINGS&symbol={sym}&apikey={AV_KEY}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode())
    return d.get('quarterlyEarnings', [])

def load_daily(sym):
    try:
        o = S3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        df['date'] = pd.to_datetime(df['date'])
        return df.set_index('date')['close'].sort_index()
    except Exception:
        return None

def main():
    syms = load_universe()
    rows = []
    for i, sym in enumerate(syms):
        try:
            q = fetch_earnings(sym)
        except Exception as e:
            print(f'{sym}: fetch fail {e!r}'); continue
        if not q:
            continue
        px = load_daily(sym)
        if px is None or len(px) < 40:
            continue
        for r in q:
            rd = r.get('reportedDate')
            sp = r.get('surprisePercentage')
            if not rd or sp is None:
                continue
            try:
                d0 = pd.Timestamp(rd)
                sp = float(sp)
            except Exception:
                continue
            # first close on/after report date, then 20-day forward return
            fut = px[px.index >= d0]
            if len(fut) < 21:
                continue
            entry = fut.iloc[0]
            exit_ = fut.iloc[20]
            fwd = (exit_ / entry - 1.0) * 100.0  # %
            rows.append({'sym': sym, 'date': rd, 'surprise': sp, 'fwd20': fwd})
        time.sleep(1.0)
        print(f'{sym}: {len(q)} reports cached', flush=True)
    df = pd.DataFrame(rows)
    df.to_csv('/tmp/pead_events.csv', index=False)
    if df.empty:
        print('NO EVENTS'); return
    print(f'\ntotal earnings events: {len(df)}')
    df['decile'] = pd.qcut(df['surprise'], 5, labels=False, duplicates='drop')
    g = df.groupby('decile', observed=True)['fwd20'].agg(['count', 'mean', 'median'])
    print('\nsurprise quintile -> avg 20d forward return (%):')
    print(g.to_string())
    top = df[df['surprise'] > 0]['fwd20'].mean()
    bot = df[df['surprise'] <= 0]['fwd20'].mean()
    print(f'\npositive-surprise avg 20d fwd: {top:+.2f}%  vs  non/neg-surprise: {bot:+.2f}%  spread: {top-bot:+.2f}%')

if __name__ == '__main__':
    main()
