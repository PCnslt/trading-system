import sys, time, json, urllib.request, urllib.parse
sys.path.insert(0, '/home/ubuntu/trading-system/venv/lib/python3.11/site-packages')
from ddgs import DDGS

def fetch(url, ua=True):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    try:
        return urllib.request.urlopen(req, timeout=30).read().decode('utf-8','ignore')
    except Exception as e:
        return "ERR " + str(e)

# 1. Wayback for SSRN 5648748
print("### SSRN 5648748 wayback availability")
print(fetch("http://archive.org/wayback/available?url=papers.ssrn.com/sol3/papers.cfm%3Fabstract_id%3D5648748"))
time.sleep(1)

# 2. OpenAlex for crypto-stock weekend effect + Dark Side
for q in ["crypto-stock weekend effect predicting Monday stock returns",
          "overnight price jumps short-term return predictability"]:
    print("\n### OpenAlex:", q)
    try:
        u = "https://api.openalex.org/works?filter=title.search:" + urllib.parse.quote(q) + "&per-page=3"
        d = json.loads(fetch(u))
        for w in d.get("results", []):
            print("-", w.get("title"))
            print("  year:", w.get("publication_year"), "doi:", w.get("doi"))
            inv = w.get("abstract_inverted_index")
            if inv:
                pos = {}
                for word, idxs in inv.items():
                    for i in idxs: pos[i]=word
                ab = " ".join(pos[i] for i in sorted(pos))[:600]
                print("  AB:", ab)
    except Exception as e:
        print("  ERR", e)
    time.sleep(1)

# 3. ddgs: broker API defect searches
d = DDGS()
queries2 = [
    "Robinhood API order idempotency duplicate order bug",
    "retail broker API automated trading failure rate limits good faith violation",
    "Alpaca API duplicate order idempotency client_order_id",
    "trading bot duplicate order fill idempotency best practices",
]
for q in queries2:
    print("\n### ddgs:", q)
    try:
        for r in d.text(q, max_results=4):
            print("-", r.get("title"), "|", r.get("href"))
            print("  ", (r.get("body") or "")[:180])
    except Exception as e:
        print("  ERR", e)
    time.sleep(2)
