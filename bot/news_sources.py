#!/usr/bin/env python3
"""Free news sources — replace paid Serper with no-key RSS search.

Sources (all free, no API key):
  - Bing News RSS  https://www.bing.com/news/search?q=...&format=rss
  - Google News RSS https://news.google.com/rss/search?q=... (fallback)
  - CNBC / Reuters / MarketWatch RSS (continuous feed)
"""

import urllib.request, urllib.parse
import xml.etree.ElementTree as ET

_UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'ignore')


def bing_news(query, n=8):
    """Search headlines via Bing News RSS. Returns [{title, link, snippet}]."""
    url = ('https://www.bing.com/news/search?q='
           + urllib.parse.quote(query) + '&format=rss')
    try:
        root = ET.fromstring(_fetch(url))
    except Exception:
        return []
    out = []
    for it in root.iter('item'):
        out.append({
            'title': it.findtext('title') or '',
            'link': it.findtext('link') or '',
            'snippet': it.findtext('description') or '',
        })
        if len(out) >= n:
            break
    return out


def google_news(query, n=8):
    """Google News RSS fallback."""
    url = ('https://news.google.com/rss/search?q='
           + urllib.parse.quote(query) + '&hl=en-US&gl=US&ceid=US:en')
    try:
        root = ET.fromstring(_fetch(url))
    except Exception:
        return []
    out = []
    for it in root.iter('item'):
        t = it.findtext('title') or ''
        out.append({'title': t, 'link': it.findtext('link') or '', 'snippet': ''})
        if len(out) >= n:
            break
    return out


def search_news(query, n=8):
    """Primary: Bing News RSS; fallback: Google News RSS."""
    r = bing_news(query, n)
    return r if r else google_news(query, n)
