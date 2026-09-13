#!/usr/bin/env python3
import json, time, urllib.request, urllib.parse

QUERIES = [
    ("Tetlock 2008 More than words", "More than words quantifying language to measure firms fundamentals"),
    ("Garcia 2013", "Sentiment during recessions"),
    ("Ke Kelly Xiu", "Predicting returns with text data"),
    ("Sinha underreaction news", "Underreaction to news in the US stock market"),
    ("Analyst selective coverage", "Analysts selective coverage and subsequent performance"),
    ("Cohen Malloy Pomorski", "Decoding inside information"),
    ("Boehmer which shorts", "Which shorts are informed"),
    ("Rapach short interest aggregate", "Short interest and aggregate stock returns"),
    ("Lakonishok Lee insider", "Are insider trades informative"),
    ("Loughran McDonald readability", "Measuring readability in financial disclosures"),
    ("Li readability persistence", "Annual report readability current earnings and earnings persistence"),
    ("Lerman Livnat 8K", "The new form 8-K disclosures"),
    ("Pan Poteshman option volume", "The information in option volume for future stock prices"),
    ("Comerton Forde dark price discovery", "Dark trading and price discovery"),
    ("GDELT stock returns", "GDELT news tone stock returns"),
    ("RavenPack media sentiment", "RavenPack news analytics trading strategy"),
    ("Hafez news sentiment", "Media sentiment and stock returns"),
    ("Cremers Pareek patient investor", "Patient capital outperformance the investment skill of high active share managers"),
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
    try:
        d = fetch(q)
        res = d.get("results", [])
        if not res:
            print(f"### {label}\n  NO RESULT: {q}\n")
            time.sleep(1.0); continue
        w = res[0]
        src = (w.get("primary_location") or {}).get("source") or {}
        print(f"### {label}\n  TITLE: {w.get('title','')}\n  YEAR: {w.get('publication_year','?')} | VENUE: {src.get('display_name','?')} | CITED: {w.get('cited_by_count',0)}\n  DOI: {w.get('doi','')}\n  OA: {(w.get('open_access') or {}).get('oa_url','')}\n  ABS: {abstract_of(w)}\n")
    except Exception as e:
        print(f"### {label}\n  ERROR: {e}\n")
    time.sleep(1.0)
