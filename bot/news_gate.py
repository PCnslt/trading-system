#!/usr/bin/env python3
"""Pre-buy news/catalyst gate — never buy a name with an unresolved negative story.

The 2026-08-27 AMAT miss: an oversold signal was real, but the decline was driven by
China export controls + a $252M BIS penalty. The signal didn't know; the news gate
exists so the BUY path does.

check_symbol(sym) -> (verdict, reason, headlines)
  verdict: 'CLEAN' (no red flags) | 'NEGATIVE' (catalyst found -> skip) | 'UNKNOWN' (no data)

Signal words for a negative catalyst (case-insensitive, matched in title+snippet):
  downgrade, guidance cut, misses, miss, china, export control, tariff, investigation,
  sec, lawsuit, fraud, bankruptcy, delisting, recall, layoff, data breach, warning,
  slumps, plunges, crashes, halt, suspension, short report, activist short

Also pulls the company name from a small map (fallback = the symbol) so the query is
meaningful. Uses Serper (google.serper.dev) via SERPER_API_KEY in .env — already wired
on this VPS. Returns UNKNOWN (fail-open, does NOT block) if the search fails, so the
gate can never deadlock a buy; the caller decides whether UNKNOWN is a block.

Use: from bot.news_gate import check_symbol
"""
from __future__ import annotations
import json, os, sys, urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

SERPER_KEY = os.getenv('SERPER_API_KEY', '')
ENDPOINT = 'https://google.serper.dev/search'

# SEVERE = hard skip (real thesis-breaker). MILD = surface as a warning, not a block.
SEVERE_WORDS = [
    'china export', 'export control', 'export ban', 'guidance cut', 'cuts guidance',
    'sec investigation', 'sec probe', 'lawsuit', 'class action', 'fraud',
    'bankruptcy', 'chapter 11', 'delisting', 'delisted', 'recall', 'data breach',
    'short report', 'activist short', 'penalty', 'restatement', 'accounting fraud',
    'subpoena', 'halted', 'suspension', 'loses a key', 'ceo resigns', 'ceo steps down',
    'misses earnings', 'earnings miss', 'revenue miss', 'tariff', 'sanctions',
]
MILD_WORDS = [
    'downgrade', 'downgraded', 'underperform', 'underweight', 'sell rating',
    'slumps', 'plunges', 'crashes', 'warning', 'layoff', 'investigation',
]

COMPANY = {
    'AMAT': 'Applied Materials', 'XOM': 'Exxon Mobil', 'NVDA': 'Nvidia',
    'AAPL': 'Apple', 'MSFT': 'Microsoft', 'AMZN': 'Amazon', 'TSLA': 'Tesla',
    'META': 'Meta', 'GOOGL': 'Alphabet', 'AVGO': 'Broadcom', 'INTC': 'Intel',
    'AMD': 'Advanced Micro Devices', 'MU': 'Micron', 'LRCX': 'Lam Research',
    'KLAC': 'KLA', 'ASML': 'ASML', 'TXN': 'Texas Instruments', 'QCOM': 'Qualcomm',
}


def _search(query: str, num: int = 6) -> list[dict]:
    if not SERPER_KEY:
        return []
    body = json.dumps({'q': query, 'num': num}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        'X-API-KEY': SERPER_KEY, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode())
        return d.get('organic', [])
    except Exception:
        return []


def check_symbol(sym: str) -> tuple[str, str, list[str]]:
    sym = sym.upper()
    name = COMPANY.get(sym, sym)
    headlines = []
    for q in (f'{name} {sym} stock news why down', f'{name} {sym} downgrade guidance china'):
        for r in _search(q):
            title = r.get('title') or ''
            snip = r.get('snippet') or ''
            headlines.append(title)
            blob = f'{title} {snip}'.lower()
            if any(w in blob for w in SEVERE_WORDS):
                return 'NEGATIVE', f'SEVERE catalyst: {title}', headlines
    # mild flags: warn but do not hard-block
    mild = [h for h in headlines if any(w in h.lower() for w in MILD_WORDS)]
    if mild:
        return 'WARN', f'{len(mild)} mild flag(s) (downgrade/etc): {mild[0]}', headlines
    if not headlines:
        return 'UNKNOWN', 'no news results (search unavailable)', []
    return 'CLEAN', 'no negative catalyst in top headlines', headlines


if __name__ == '__main__':
    for s in sys.argv[1:] or ['AMAT', 'XOM']:
        v, why, heads = check_symbol(s)
        print(f'{s}: {v} — {why}')
        for h in heads[:3]:
            print(f'   - {h}')
