import sys, re, urllib.request, html as ihtml
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
    try:
        return urllib.request.urlopen(req, timeout=40).read().decode('utf-8','ignore')
    except Exception as e:
        return "ERR " + str(e)

snap = "http://web.archive.org/web/20251030040413/https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5648748"
h = fetch(snap)
# SSRN abstracts live inside <div class="abstract-text"> ... </div> or in a section
for pat in [r'class="abstract-text[^"]*"[^>]*>(.*?)</div>', r'abstract-text">(.*?)</', r'<meta name="citation_abstract" content="(.*?)"']:
    m = re.search(pat, h, re.S)
    if m:
        t = re.sub(r'<[^>]+>', ' ', m.group(1))
        t = ihtml.unescape(re.sub(r'\s+', ' ', t)).strip()
        print("=== ABSTRACT (%d) ===" % len(t))
        print(t)
        break
else:
    # dump text near "overreaction"
    idx = h.find("overreaction")
    seg = re.sub(r'<[^>]+>', ' ', h[idx:idx+3000])
    seg = ihtml.unescape(re.sub(r'\s+',' ',seg))
    print("=== around overreaction ===")
    print(seg[:2500])
