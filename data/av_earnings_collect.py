#!/usr/bin/env python3
"""AlphaVantage earnings-surprise collector.

Fetches the free `EARNINGS` endpoint (122 quarters of analyst surprise) for the most
liquid names, 25/day (AV free quota), caching to S3. Run daily; it advances through the
target list each day.

Usage: python data/av_earnings_collect.py [max_today]
"""
import os, sys, json, time
import urllib.request
import boto3

# load .env for the key
_env = {}
for _line in open(os.path.join(os.path.dirname(__file__), '..', '.env')):
    _line = _line.strip()
    if _line and not _line.startswith('#') and '=' in _line:
        _k, _v = _line.split('=', 1)
        _env[_k.strip()] = _v.strip().strip('"').strip("'")
AV_KEY = _env.get('ALPHAVANTAGE_API_KEY') or os.getenv('ALPHAVANTAGE_API_KEY')
S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'

def targets():
    with open('research/universe_1500.json') as f:
        raw = json.load(f)
    syms = raw['symbols'] if isinstance(raw, dict) and 'symbols' in raw else raw
    return [s for s in syms if isinstance(s, str)][:150]  # top-150 liquid

def cached(sym):
    try:
        S3.head_object(Bucket=BUCKET, Key=f'av/earnings/{sym}.json')
        return True
    except Exception:
        return False

def fetch(sym):
    url = ('https://www.alphavantage.co/query?function=EARNINGS&symbol=%s&apikey=%s'
           % (sym, AV_KEY))
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.load(r)
    if 'quarterlyEarnings' not in data:
        return False
    S3.put_object(Bucket=BUCKET, Key=f'av/earnings/{sym}.json',
                  Body=json.dumps(data))
    return True

def main():
    max_today = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    todo = [s for s in targets() if not cached(s)]
    n = 0
    for sym in todo:
        if n >= max_today:
            break
        ok = fetch(sym)
        n += 1
        print(f'{"OK " if ok else "FAIL"} {sym} ({n}/{max_today})')
        time.sleep(13)  # AV rate limit ~5/min
    print(f'done {n} fetches; {len(targets())} total targets, {sum(1 for s in targets() if cached(s))} cached')

if __name__ == '__main__':
    main()
