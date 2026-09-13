#!/usr/bin/env python3
import json, time, urllib.request, urllib.parse, sys

QUERIES = [
    # news sentiment
    ("Tetlock 2007", "Giving content to investor sentiment the role of the media in the stock market"),
    ("Tetlock 2008", "More than words quantifying language to measure firms fundamentals"),
    ("Garcia 2013", "Sentiment during recessions"),
    ("Heston Sinha 2017", "News vs sentiment predicting stock returns from news stories"),
    ("Ke Kelly Xiu 2019", "Predicting returns with text data"),
    ("Sinha 2016", "Underreaction to news in the US stock market"),
    # analyst revision beyond banked
    ("Stickel 1991", "Common stock returns surrounding earnings forecast revisions more puzzling evidence"),
    ("Sticky expectations", "Sticky expectations and the profitability anomaly"),
    ("Diether dispersion 2002", "Differences of opinion and the cross section of stock returns"),
    ("Analyst selective coverage", "Analysts selective coverage and subsequent performance"),
    # insider + short interest
    ("Cohen Malloy Pomorski 2012", "Decoding inside information"),
    ("Desai short interest 2002", "An investigation of the informational role of short interest in the Nasdaq market"),
    ("Boehmer shorts 2008", "Which shorts are informed"),
    ("Rapach short interest 2016", "Short interest and aggregate stock returns"),
    ("Jeng Metrick insider", "Estimating the returns to insider trading a performance evaluation perspective"),
    ("Lakonishok Lee insider", "Are insider trades informative"),
    # textual tone
    ("Loughran McDonald 2011", "When is a liability not a liability textual analysis dictionaries and 10-Ks"),
    ("Loughran McDonald 2014", "Measuring readability in financial disclosures"),
    ("Li readability 2008", "Annual report readability current earnings and earnings persistence"),
    ("Lazy Prices", "Lazy prices"),
    ("MD&A tone", "Management's tone change post earnings announcement drift and accruals"),
    ("Lerman Livnat 8-K", "The new form 8-K disclosures"),
    # options flow / dark pool
    ("Pan Poteshman 2006", "The information in option volume for future stock prices"),
    ("Johnson So 2012", "The option to stock volume ratio and future returns"),
    ("Ge Lin Pearson O/S", "Why does the option to stock volume ratio predict stock returns"),
    ("Hu option trading", "Does option trading convey stock price information"),
    ("Dark pool price discovery", "Dark trading and price discovery"),
    ("Dark pool strategies", "Dark pool trading strategies market quality and welfare"),
]

def fetch(q, n=1):
    url = "https://api.openalex.org/works?filter=title.search:" + urllib.parse.quote(q) + "&per-page=" + str(n)
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
    return " ".join(pos[i] for i in sorted(pos))[:350]

out = []
for label, q in QUERIES:
    try:
        d = fetch(q)
        res = d.get("results", [])
        if not res:
            out.append(f"### {label}\n  NO RESULT for: {q}")
            continue
        w = res[0]
        src = (w.get("primary_location") or {}).get("source") or {}
        venue = src.get("display_name", "?")
        year = w.get("publication_year", "?")
        doi = w.get("doi", "")
        oa = (w.get("open_access") or {}).get("oa_url", "")
        cited = w.get("cited_by_count", 0)
        title = w.get("title", "")
        out.append(f"### {label}\n  TITLE: {title}\n  YEAR: {year} | VENUE: {venue} | CITED: {cited}\n  DOI: {doi}\n  OA: {oa}\n  ABS: {abstract_of(w)}")
    except Exception as e:
        out.append(f"### {label}\n  ERROR: {e}")
    time.sleep(0.3)

print("\n\n".join(out))
