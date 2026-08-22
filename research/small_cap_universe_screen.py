#!/usr/bin/env python3
"""Screen for a liquid sub-$35 whole-share RSI2 universe (Robinhood live, $700).

Per docs/SMALL-CAPITAL-LIVE-PLAN.md §5: liquid names $5-$35, 20d avg $volume
>= ~$50M/day, with a price floor ($3) to avoid penny/illiquid names. Output is a
sorted candidate list to hardcode into bot/live_equities.py SMALL_CAP_STOCKS.
"""
import pandas as pd
import yfinance as yf

# Candidate pool: liquid names plausibly sub-$35 in Aug-2026, across sectors,
# seeded from the plan's representative table + broad liquid small/mid caps.
CANDIDATES = [
    # plan representatives
    'SNAP', 'NIO', 'F', 'AAL', 'KVUE', 'T', 'KHC', 'PFE', 'WBD', 'DOW',
    # telecom / media / consumer staples-discretionary
    'VZ', 'PARA', 'WBA', 'M', 'JWN', 'GPS', 'KSS', 'BBY', 'ROKU', 'SIRI',
    # airlines / autos / EV
    'GM', 'DAL', 'UAL', 'LUV', 'RIVN', 'LCID', 'HOG', 'CPRI',
    # energy / materials
    'MRO', 'OXY', 'HAL', 'APA', 'DVN', 'VALE', 'PBR', 'KMI', 'WMB', 'CLF',
    'X', 'AA', 'MOS', 'NEM', 'FCX',
    # financials / fintech
    'KEY', 'FITB', 'HBAN', 'RF', 'USB', 'SOFI', 'HOOD', 'COIN', 'LYFT', 'UBER',
    'RIOT', 'MARA', 'COF', 'SYF', 'ALLY',
    # health / pharma
    'VTRS', 'TEVA', 'CVS', 'MRK', 'BMY', 'GILD',
    # REITs / yield
    'AGNC', 'NLY', 'WPC', 'O', 'VICI', 'MPW',
    # industrials / misc
    'GE', 'BA', 'HON', 'MMM', 'CAT', 'DE', 'NSC',
    # tech / semi / growth
    'INTC', 'AMD', 'MU', 'PLTR', 'PYPL', 'QCOM', 'TXN', 'ADI',
    # staples / consumer
    'KO', 'PEP', 'PG', 'WMT', 'COST', 'MCD', 'SBUX', 'CMCSA',
]

def screen():
    rows = []
    # batch download 1mo of daily bars (price + volume) in one call
    data = yf.download(CANDIDATES, period='1mo', interval='1d', auto_adjust=True,
                       progress=False, group_by='ticker', threads=True)
    for sym in CANDIDATES:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                df = data[sym]
            else:
                df = data
            if df is None or df.empty or 'Close' not in df or 'Volume' not in df:
                continue
            close = float(df['Close'].dropna().iloc[-1])
            vol20 = df['Volume'].dropna().tail(20)
            if len(vol20) < 15:
                continue
            avg_dollar_vol = float((vol20 * df['Close'].reindex(vol20.index)).mean())
            rows.append({'sym': sym, 'close': close, 'avg_dollar_vol_m': avg_dollar_vol / 1e6})
        except Exception:
            continue
    rows.sort(key=lambda r: r['close'])
    print(f"{'SYM':6s} {'close':>8s} {'avg$vol(M)':>11s}  verdict")
    print('-' * 42)
    keep = []
    for r in rows:
        ok = (3.0 <= r['close'] <= 35.0) and (r['avg_dollar_vol_m'] >= 50.0)
        verdict = 'KEEP' if ok else 'skip'
        print(f"{r['sym']:6s} {r['close']:>8.2f} {r['avg_dollar_vol_m']:>11.1f}  {verdict}")
        if ok:
            keep.append(r['sym'])
    print('\nKEEP list (' + str(len(keep)) + '):')
    print(', '.join(keep))


if __name__ == '__main__':
    screen()
