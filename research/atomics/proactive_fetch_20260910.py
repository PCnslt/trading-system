import sys, time, json, urllib.request, urllib.parse, re
sys.path.insert(0, '/home/ubuntu/trading-system/venv/lib/python3.11/site-packages')

def fetch(url, ua=True):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
    try:
        return urllib.request.urlopen(req, timeout=40).read().decode('utf-8','ignore')
    except Exception as e:
        return "ERR " + str(e)

# 1. Dark Side abstract via Wayback SSRN snapshot (meta description carries abstract)
snap = "http://web.archive.org/web/20251030040413/https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5648748"
html = fetch(snap)
print("=== Dark Side snapshot bytes:", len(html))
m = re.search(r'<meta name="description" content="(.*?)"', html, re.S)
if m:
    print("DESC:", m.group(1)[:1200])
else:
    # fallback: find abstract in og:description or title
    m2 = re.search(r'property="og:description" content="(.*?)"', html, re.S)
    print("OG:", (m2.group(1)[:1200] if m2 else "none"))

# 2. OpenAlex abstract for Dark Side J BEF 2026
print("\n=== OpenAlex jbef 101220")
d = json.loads(fetch("https://api.openalex.org/works/https://doi.org/10.1016/j.jbef.2026.101220"))
inv = d.get("abstract_inverted_index")
if inv:
    pos={}
    for w,idxs in inv.items():
        for i in idxs: pos[i]=w
    print(" ".join(pos[i] for i in sorted(pos))[:1500])

# 3. Concretum article via jina
print("\n=== Concretum 10 lessons (jina)")
j = fetch("https://r.jina.ai/https://concretumgroup.com/building-reliable-trading-systems-algorithmic-trading-automation/")
print("bytes:", len(j))
print(j[:3500])
