#!/usr/bin/env python3
"""Macro-event scanner — surfaces Fed speakers, FOMC, Jackson Hole, and key data
releases (CPI/PCE/NFP/GDP) BEFORE they move the market.

The 2026-08-27 miss: the owner had to tell us Jackson Hole / Fed Chair Warsh speaks
tomorrow (10:00 ET). A news_gate for per-stock catalysts is not enough — we need a
macro calendar. This scans a curated set of queries daily and emits a short digest.

Runs ~06:15 ET weekdays. Read-only. Uses Serper (SERPER_API_KEY in .env).
"""
from __future__ import annotations
import os, sys, json, urllib.request, urllib.parse
import datetime as dt
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

NY = ZoneInfo('America/New_York')
SERPER = os.getenv('SERPER_API_KEY', '')


def _search(q):
    if not SERPER:
        return []
    req = urllib.request.Request(
        'https://google.serper.dev/search',
        data=json.dumps({'q': q, 'num': 5}).encode(),
        headers={'X-API-KEY': SERPER, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r).get('organic', [])
    except Exception:
        return []


def main():
    now = dt.datetime.now(NY)
    today = now.strftime('%A %B %-d, %Y')
    tmrw = (now + dt.timedelta(days=1)).strftime('%A %B %-d, %Y')
    print(f'=== MACRO EVENTS — {today} ===')
    print(f'(tomorrow: {tmrw})\n')

    queries = [
        f'Fed speakers {today} schedule times',
        f'economic calendar {today} CPI PCE GDP',
        f'economic calendar {tmrw} Fed Powell Warsh speech',
        'FOMC meeting dates 2026',
        'Jackson Hole symposium 2026 schedule',
    ]
    seen = set()
    for q in queries:
        for o in _search(q):
            t = o.get('title', '').strip()
            if not t or t in seen:
                continue
            seen.add(t)
            sn = (o.get('snippet') or '').strip()
            d = o.get('date') or ''
            print(f'- {t} ({d})')
            if sn:
                print(f'    {sn[:200]}')
        print()

    if not seen:
        print('(no results — Serper key missing or search failed)')


if __name__ == '__main__':
    main()
