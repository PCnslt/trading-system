import sys, re, urllib.request
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
    try:
        return urllib.request.urlopen(req, timeout=40).read().decode('utf-8','ignore')
    except Exception as e:
        return "ERR " + str(e)

# Full Dark Side abstract from snapshot
snap = "http://web.archive.org/web/20251030040413/https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5648748"
html = fetch(snap)
m = re.search(r'<meta name="description" content="(.*?)"', html, re.S)
if m:
    txt = m.group(1)
    print("=== Dark Side full DESC (%d chars) ===" % len(txt))
    print(txt)
    print()

# Concretum rest
j = fetch("https://r.jina.ai/https://concretumgroup.com/building-reliable-trading-systems-algorithmic-trading-automation/")
print("=== Concretum (tail) ===")
print(j[3500:9000])
