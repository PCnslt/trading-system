import json, os, urllib.request
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/trading-system/.env')
SERPER = os.getenv('SERPER_API_KEY')

QUERIES = [
    "profitable short term trading strategies that survive transaction costs 2024",
    "overnight return anomaly buy close sell open trading strategy",
    "intraday mean reversion profitability academic evidence",
    "short term reversal strategy 2 3 day holding period",
    "trend following volatility scaling momentum crash protection research",
    "cross sectional momentum short term stock anomaly",
]

def serper(q, n=6):
    body = json.dumps({'q': q, 'num': n}).encode()
    req = urllib.request.Request('https://google.serper.dev/search', data=body,
                                 headers={'X-API-KEY': SERPER, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())

for q in QUERIES:
    print('=' * 90)
    print('Q:', q)
    try:
        d = serper(q)
        for o in d.get('organic', []):
            print(f"- {o.get('title','')}")
            print(f"  {o.get('link','')}")
            print(f"  {o.get('snippet','')[:220]}")
        # also answer box / knowledge graph if any
        if d.get('answerBox'):
            print('  ANSWER:', str(d['answerBox'])[:200])
    except Exception as e:
        print('  ERR', e)
