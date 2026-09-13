#!/usr/bin/env python3
"""Collect buyback-announcement 8-K events via EDGAR full-text search (FTS).

Source: SEC EDGAR full-text search (efts.sec.gov/LATEST/search-index).
Query: "repurchase program" AND "authorized", form=8-K, per-year (2006..2026)
to stay under the 10,000-hit cap, fully paginated.

Output: JSONL at /tmp/buyback_fts_hits.jsonl  (one FTS hit per line)
Fields kept: file_date, ciks, display_names, adsh, form, items, sic, states.
"""
import json, time, urllib.request, urllib.parse, sys, os

H = {'User-Agent': 'PCnslt Research info@pcnslt.com'}
OUT = '/tmp/buyback_fts_hits.jsonl'
QUERY = '"repurchase program" AND "authorized"'
FORM = '8-K'

def fetch(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=H)
            return json.loads(urllib.request.urlopen(req, timeout=40).read())
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))

def year_bounds(y):
    return f'{y}-01-01', f'{y}-12-31'

def collect_year(y):
    s, e = year_bounds(y)
    rows = []
    from_ = 0
    while True:
        u = (f'https://efts.sec.gov/LATEST/search-index?q={urllib.parse.quote(QUERY)}'
             f'&forms={FORM}&startdt={s}&enddt={e}&from={from_}')
        d = fetch(u)
        hits = d['hits']['hits']
        total = d['hits']['total']['value']
        if not hits:
            break
        for h in hits:
            src = h['_source']
            rows.append({
                'file_date': src.get('file_date'),
                'ciks': src.get('ciks'),
                'display_names': src.get('display_names'),
                'adsh': src.get('adsh'),
                'form': src.get('form'),
                'items': src.get('items'),
                'sics': src.get('sics'),
            })
        from_ += len(hits)
        if from_ >= total or from_ >= 9900:
            break
        time.sleep(0.12)
    return rows, total

def main():
    start_year = int(sys.argv[1]) if len(sys.argv) > 1 else 2006
    end_year = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    all_rows = []
    for y in range(start_year, end_year + 1):
        try:
            rows, total = collect_year(y)
            all_rows.extend(rows)
            print(f'{y}: {total} hits -> {len(rows)} collected', flush=True)
        except Exception as e:
            print(f'{y}: ERROR {e}', flush=True)
        time.sleep(0.3)
    with open(OUT, 'w') as f:
        for r in all_rows:
            f.write(json.dumps(r) + '\n')
    print(f'TOTAL collected: {len(all_rows)} -> {OUT}', flush=True)

if __name__ == '__main__':
    main()
