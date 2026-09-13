import sys, time, json
sys.path.insert(0, '/home/ubuntu/trading-system/venv/lib/python3.11/site-packages')
from ddgs import DDGS

queries = [
    "new equity market anomaly 2025 short horizon overnight return paper arXiv",
    "intraday momentum anomaly 2025 2026 new paper SSRN",
    "retail order flow Robinhood signal predictable returns 2025 paper",
    "stock return predictability machine learning 2025 intraday",
    "weekend effect anomaly 2025 equity",
    "retail trading signal future returns 2025 2026",
]

d = DDGS()
for q in queries:
    print("=" * 80)
    print("QUERY:", q)
    try:
        for r in d.text(q, max_results=5):
            print("-", r.get("title"))
            print("  ", r.get("href"))
            print("  ", (r.get("body") or "")[:220])
    except Exception as e:
        print("  ERROR:", e)
    time.sleep(2)
