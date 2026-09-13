#!/usr/bin/env python3
import json, time, urllib.request, urllib.parse

QUERIES = [
    ("Tetlock 2008 More than words", "More than words quantifying language to measure firms fundamentals"),
    ("Ke Kelly Xiu", "Predicting returns with text data"),
    ("Sinha underreaction news", "Underreaction to news in the US stock market"),
    ("Rapach short interest aggregate", "Short interest and aggregate stock returns"),
    ("Li readability persistence", "Annual report readability current earnings and earnings persistence"),
    ("Lerman Livnat 8K", "The new form 8-K disclosures"),
    ("Pan Poteshman option volume", "The information in option volume for future stock prices"),
    ("GDELT tone stock returns", "GDELT tone stock returns sentiment"),
    ("Hafez media sentiment returns", "Media sentiment and stock returns the role of news"),
    ("Uhl GDELT", "GDELT sentiment trading"),
]

def fetch(q):
    url = "https://api.openalex.org/works?filter=title.search:" + urllib.parse.quote(q) + "&per-page=1"
    req = urllib.request.Request(url, headers={"User-Agent": "research/1.0 (mailto:research@example.com)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def abstract_of(w):
    aii = w.get("abstract_inverted_index")
    if not aii:
        return ""
    pos = {}
    for word, idxs in aii.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))[:400]

for label, q in QUERIES:
    for attempt in range(3):
        try:
            d = fetch(q)
            res = d.get("results", [])
            if not res:
                print(f"### {label}\n  NO RESULT: {q}\n"); break
            w = res[0]
            src = (w.get("primary_location") or {}).get("source") or {}
            print(f"### {label}\n  TITLE: {w.get('title','')}\n  YEAR: {w.get('publication_year','?')} | VENUE: {src.get('display_name','?')} | CITED: {w.get('cited_by_count',0)}\n  DOI: {w.get('doi','')}\n  OA: {(w.get('open_access') or {}).get('oa_url','')}\n  ABS: {abstract_of(w)}\n")
            break
        except Exception as e:
            if attempt == 2:
                print(f"### {label}\n  ERROR: {e}\n")
            time.sleep(2.0)
    time.sleep(1.5)
