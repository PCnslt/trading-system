#!/usr/bin/env python3
"""Expand the tradeable RSI2 universe via breadth (the stated 'volume via breadth' goal).

Screens the full S&P 1500 (500 + MidCap 400 + SmallCap 600) for:
  (a) SMALL-TICKET: close $3-$35 AND 20d avg $volume >= $50M  -> RH live whole-share
  (b) LIQUID (any price): 20d avg $volume >= $500M           -> IBKR paper + RH large-cap

Output is two sorted lists to hardcode into bot/live_equities.py.
"""
import pandas as pd
import yfinance as yf
import requests
from io import StringIO

def wiki_tickers(url, col):
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (research)'}, timeout=30)
    r.raise_for_status()
    tables = pd.read_html(StringIO(r.text))
    for t in tables:
        if col in t.columns:
            return [str(x).replace('.', '-') for x in t[col].tolist() if str(x) != 'nan']
    return []

def get_universe():
    sp500 = wiki_tickers('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', 'Symbol')
    sp400 = wiki_tickers('https://en.wikipedia.org/wiki/List_of_S%26P_400_companies', 'Symbol')
    sp600 = wiki_tickers('https://en.wikipedia.org/wiki/List_of_S%26P_600_companies', 'Symbol')
    uni = sorted(set(sp500 + sp400 + sp600))
    # drop class-B/odd tickers that yfinance can't resolve cleanly
    return [s for s in uni if s.isalpha() or '-' in s]

def main():
    uni = get_universe()
    print(f'S&P 1500 universe: {len(uni)} tickers')
    # batch download 3mo daily bars (price + volume)
    data = yf.download(uni, period='3mo', interval='1d', auto_adjust=True,
                       progress=False, group_by='ticker', threads=True)
    small = []; liquid = []
    for sym in uni:
        try:
            df = data[sym] if isinstance(data.columns, pd.MultiIndex) else data
            if df is None or df.empty or 'Close' not in df:
                continue
            close = float(df['Close'].dropna().iloc[-1])
            vol20 = df['Volume'].dropna().tail(20)
            if len(vol20) < 15:
                continue
            adv = float((vol20 * df['Close'].reindex(vol20.index)).mean()) / 1e6
            if 3.0 <= close <= 35.0 and adv >= 50.0:
                small.append((sym, round(close, 2), round(adv, 1)))
            if adv >= 500.0:
                liquid.append((sym, round(close, 2), round(adv, 1)))
        except Exception:
            continue
    small.sort(key=lambda x: x[2], reverse=True)
    liquid.sort(key=lambda x: x[2], reverse=True)
    import json
    with open('/tmp/universe_screen.json', 'w') as f:
        json.dump({'small': [s for s, _, _ in small], 'liquid': [s for s, _, _ in liquid]}, f)
    print(f'\nSMALL-TICKET ({len(small)}):')
    print(', '.join(s for s, _, _ in small))
    print(f'\nLIQUID ({len(liquid)}):')
    print(', '.join(s for s, _, _ in liquid))


if __name__ == '__main__':
    main()
