"""MEAN-REVERSION validation — bonds (ZB/ZN) + FX (6B/6A/6E/6J).

Dedicated validation of the ONE genuinely new lead from allmarkets_scan.py:
mean-reversion on rates/FX (ZB Bollinger OOS ~1.88, 6B ~1.78, 6A RSI 1.5-1.6).
That scan used 20-bar windows and only exit-at-mean / exit-at-70/30. Here we
stress the same edges with the exact rules the lead describes, swept across
lookback params to check robustness vs curve-fitting.

STRATEGIES (each LONG, SHORT, and BOTH):
  (a) Bollinger reversal — close crosses outside k*sigma band -> fade back to
      the rolling mean. Exit at the mean (mid band), or max-hold.
  (b) RSI reversal — RSI(n)<10 long / >90 short; exit when RSI(n) crosses 50,
      or max-hold. n=2 is the canonical "RSI(2)"; 10/20/30 = robustness variants.

LOOKBACK SWEEP (the fragility test):
  Bollinger band window  {10, 20, 30}
  RSI period            {2, 10, 20, 30}   (2 = the named RSI(2) strategy)

METHOD: walk-forward 60/40 (train/test). Cost 1.3 bps round-trip of notional
(0.00013), applied per completed trade — deliberately conservative for these
deep FX/rates books. 1x notional, no leverage. Max hold 10 days (mean-reversion
horizon on daily bars, longer than the 5-day index trend horizon).

VERDICT: a (strategy x direction) cell is "robust" if OOS PF >= 1.2 in a
majority of its VALID (market x lookback) cells (>=10 OOS trades) AND the
pooled OOS PF >= 1.2. Degenerate cells (period-10/20/30 RSI rarely reaches the
<10/>90 thresholds -> ~0 trades) are excluded from the majority count but kept
in the table. Fragile = edge concentrated in one market / one lookback / one
direction / one hold-period.

KNOWN FINDING (hold-period sensitivity): the allmarkets_scan lead (ZB Bollinger
long OOS 1.88, 6B 2.69) reproduces ONLY at MAX_HOLD=5. At MAX_HOLD=10 (this
scan) it collapses (ZB 1.07, 6B 1.43). The SHORT side (fade rallies/overbought)
is the hold-robust expression of the same range-bound bonds/FX thesis.

Results -> bot/meanrev_scan_results.json.
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# --- SSM-first secrets (infra/ssm_secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.ssm_secrets import bootstrap as _sb
_sb()
from data.s3_archive import archive_scan_results

COST = 0.00013        # 1.3 bps round-trip of notional (see docstring)
MAX_HOLD = 10         # time stop (days) for mean-reversion horizon
K = 2.0               # Bollinger sigma multiple
START = '2015-01-01'

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(HERE, 'meanrev_scan_results.json')

# 30yr, 10yr, GBP, AUD, EUR, JPY
TICKERS = ['ZB=F', 'ZN=F', '6B=F', '6A=F', '6E=F', '6J=F']
TICKER_NAME = {
    'ZB=F': 'ZB 30yr', 'ZN=F': 'ZN 10yr', '6B=F': 'GBP/USD',
    '6A=F': 'AUD/USD', '6E=F': 'EUR/USD', '6J=F': 'JPY/USD',
}
BOLL_LOOKBACKS = [10, 20, 30]
RSI_LOOKBACKS = [2, 10, 20, 30]
DIRECTIONS = ['long', 'short', 'both']


# ===== indicators =====
def rsi(close, n=2):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def bollinger(close, n=20, k=2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid, mid + k * sd, mid - k * sd


# ===== signal generators (bar-by-bar, no lookahead) =====
def sig_bollinger_mr(df, n=20, k=K, hold=MAX_HOLD, direction='both'):
    c = df['Close']
    mid, upper, lower = bollinger(c, n, k)
    long_ok = direction in ('long', 'both')
    short_ok = direction in ('short', 'both')
    pos = pd.Series(0.0, index=df.index)
    p, entry_i = 0, 0
    for i in range(len(df)):
        ci, mi, ui, li = c.iloc[i], mid.iloc[i], upper.iloc[i], lower.iloc[i]
        if np.isnan(mi):
            pos.iloc[i] = 0
            continue
        if p == 0:
            if long_ok and ci < li:
                p, entry_i = 1, i
            elif short_ok and ci > ui:
                p, entry_i = -1, i
        else:
            if i - entry_i >= hold:
                p = 0
            elif p == 1 and ci >= mi:   # fade back to the mean
                p = 0
            elif p == -1 and ci <= mi:
                p = 0
        pos.iloc[i] = p
    return pos


def sig_rsi_mr(df, n=2, lo=10.0, hi=90.0, hold=MAX_HOLD, direction='both'):
    c = df['Close']
    r = rsi(c, n)
    long_ok = direction in ('long', 'both')
    short_ok = direction in ('short', 'both')
    pos = pd.Series(0.0, index=df.index)
    p, entry_i = 0, 0
    for i in range(len(df)):
        ri = r.iloc[i]
        if p == 0:
            if long_ok and ri < lo:
                p, entry_i = 1, i
            elif short_ok and ri > hi:
                p, entry_i = -1, i
        else:
            if i - entry_i >= hold:
                p = 0
            elif p == 1 and ri >= 50:   # reversion done once RSI crosses 50
                p = 0
            elif p == -1 and ri <= 50:
                p = 0
        pos.iloc[i] = p
    return pos


# ===== trade extraction + metrics (identical to allmarkets_scan.py) =====
def extract_trades(pos, close, cost):
    trades = []
    p, entry_px, entry_i = 0, np.nan, None
    for i in range(len(pos)):
        pi = int(pos.iloc[i])
        ci = close.iloc[i]
        if p == 0 and pi != 0:
            p, entry_px, entry_i = pi, ci, i
        elif p != 0 and pi != p:
            trades.append({'ret': (ci / entry_px - 1) * p - cost, 'days': i - entry_i, 'dir': p})
            if pi == 0:
                p = 0
            else:
                p, entry_px, entry_i = pi, ci, i
    if p != 0:
        trades.append({'ret': (close.iloc[-1] / entry_px - 1) * p - cost,
                       'days': len(pos) - 1 - entry_i, 'dir': p})
    return trades


def close_to_close(pos, df, cost):
    close = df['Close']
    ret = close.pct_change().fillna(0.0)
    gross = pos.shift(1).fillna(0.0) * ret
    turnover = pos.diff().abs().fillna(0.0)
    net = (gross - (cost / 2) * turnover).fillna(0.0)
    return net, extract_trades(pos, close, cost)


def pf_from_trades(trades):
    if not trades:
        return 0.0
    rets = np.array([t['ret'] for t in trades])
    wins, losses = rets[rets > 0], rets[rets <= 0]
    if losses.size == 0:
        return float('inf') if wins.size else 0.0
    if losses.sum() == 0:
        return float('inf')
    return wins.sum() / abs(losses.sum())


def metrics(net, trades):
    equity = (1.0 + net).cumprod()
    n = len(net)
    cagr = equity.iloc[-1] ** (252.0 / n) - 1.0 if n else 0.0
    maxdd = (equity / equity.cummax() - 1.0).min()
    if not trades:
        return {'trades': 0, 'winrate': 0.0, 'pf': 0.0, 'cagr': cagr,
                'maxdd': maxdd, 'final': float(equity.iloc[-1])}
    rets = np.array([t['ret'] for t in trades])
    wins = rets[rets > 0]
    return {
        'trades': len(trades),
        'winrate': 100.0 * wins.size / len(trades),
        'pf': pf_from_trades(trades),
        'cagr': cagr,
        'maxdd': maxdd,
        'final': float(equity.iloc[-1]),
    }


def get_data(ticker):
    df = yf.download(ticker, start=START, interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=['Open', 'High', 'Low', 'Close'])


def run_one(df, sig, direction, lookback):
    pos = sig(df, n=lookback, direction=direction)
    return close_to_close(pos, df, COST)


def walk_forward(df, sig, direction, lookback):
    split = int(len(df) * 0.6)
    tr, te = df.iloc[:split], df.iloc[split:]
    m_in = metrics(*run_one(tr, sig, direction, lookback))
    m_out = metrics(*run_one(te, sig, direction, lookback))
    _, oos_trades = run_one(te, sig, direction, lookback)
    return m_in, m_out, oos_trades


def fmt_pf(pf):
    return ' inf' if pf == float('inf') else f'{pf:5.2f}'


def main():
    print("MEAN-REVERSION validation  (cost=%.5f = 1.3 bps/round-trip, max-hold %dd)" % (COST, MAX_HOLD))
    print("Universe: %s\n" % ', '.join(TICKERS))

    data, failed = {}, []
    for tk in TICKERS:
        try:
            df = get_data(tk)
            if df is None or len(df) < 260:
                failed.append((tk, 'insufficient data'))
            else:
                data[tk] = df
        except Exception as e:  # noqa: BLE001
            failed.append((tk, f'{type(e).__name__}: {e}'))
    if failed:
        print("SKIPPED:", failed, "\n")

    strategies = [('bollinger', sig_bollinger_mr, BOLL_LOOKBACKS, 'Bollinger'),
                  ('rsi', sig_rsi_mr, RSI_LOOKBACKS, 'RSI')]

    wf_rows = []                                   # per (strategy, direction, ticker, lookback)
    pooled = {}                                    # (strategy, direction, lookback) -> oos trades
    pooled_all = {}                                # (strategy, direction) -> oos trades (all lb+markets)
    for sname, sig, lookbacks, label in strategies:
        for direction in DIRECTIONS:
            for tk, df in data.items():
                for lb in lookbacks:
                    m_in, m_out, oos = walk_forward(df, sig, direction, lb)
                    wf_rows.append({
                        'strategy': sname, 'direction': direction, 'ticker': tk,
                        'lookback': lb, 'in_pf': m_in['pf'], 'in_trades': m_in['trades'],
                        'out_pf': m_out['pf'], 'out_trades': m_out['trades'],
                        'out_cagr': m_out['cagr'], 'out_maxdd': m_out['maxdd'],
                    })
                    pooled.setdefault((sname, direction, lb), []).extend(oos)
                    pooled_all.setdefault((sname, direction), []).extend(oos)

    # ===== report tables =====
    for sname, sig, lookbacks, label in strategies:
        print(f"=== {label} reversal (lookbacks={lookbacks}) — walk-forward 60/40 OOS ===")
        for lb in lookbacks:
            cells = []
            for direction in DIRECTIONS:
                tr = pooled[(sname, direction, lb)]
                cells.append(f"{direction} PF {fmt_pf(pf_from_trades(tr))} (n={len(tr)})")
            print(f"  lookback {lb:>2}:  " + "   ".join(cells))
        print()
        for direction in DIRECTIONS:
            print(f"  [{label} {direction}] per-ticker OOS PF across lookbacks (lb=PF(n)):")
            for tk in TICKERS:
                cells = []
                for lb in lookbacks:
                    r = next((x for x in wf_rows if x['strategy'] == sname
                              and x['direction'] == direction and x['ticker'] == tk
                              and x['lookback'] == lb), None)
                    cells.append(f"{lb}={fmt_pf(r['out_pf'])}({r['out_trades']})" if r else f"{lb}=--")
                print(f"    {TICKER_NAME[tk]:<10} " + "  ".join(cells))
            print()

    # ===== verdict =====
    print("=" * 72)
    print("VERDICT (robust = OOS PF >= 1.2 in a majority of VALID cells (>=10 OOS")
    print("        trades) AND pooled OOS PF >= 1.2):")
    print("=" * 72)
    verdicts = []
    for sname, sig, lookbacks, label in strategies:
        for direction in DIRECTIONS:
            cells = [r for r in wf_rows if r['strategy'] == sname and r['direction'] == direction]
            valid = [r for r in cells if r['out_trades'] >= 10]   # exclude degenerate (~0 trade) lookbacks
            n_ok = sum(1 for r in valid if r['out_pf'] >= 1.2)
            ptr = pooled_all[(sname, direction)]
            pooled_pf = pf_from_trades(ptr)
            robust = bool(len(valid) > 0 and n_ok > len(valid) / 2 and pooled_pf >= 1.2)
            verdicts.append((label, direction, n_ok, len(valid), len(cells),
                             pooled_pf, len(ptr), robust))
    for label, direction, n_ok, n_valid, n_cells, pooled_pf, nt, robust in verdicts:
        mark = 'ROBUST' if robust else 'fragile'
        print(f"  {label:<10} {direction:>5}  {n_ok:>2}/{n_valid:<2} valid cells OOS PF>=1.2 "
              f"(of {n_cells} cells)  pooled OOS PF {fmt_pf(pooled_pf)} (n={nt})  -> {mark}")

    payload = {
        'cost': COST, 'max_hold': MAX_HOLD, 'k': K,
        'tickers': TICKERS, 'failed': failed,
        'bollinger_lookbacks': BOLL_LOOKBACKS, 'rsi_lookbacks': RSI_LOOKBACKS,
        'directions': DIRECTIONS,
        'walk_forward': wf_rows,
        'verdicts': [{'strategy': s, 'direction': d, 'cells_ok': a, 'cells_valid': b,
                      'cells_total': c, 'pooled_oos_pf': p, 'n_trades': nt, 'robust': r}
                     for (s, d, a, b, c, p, nt, r) in verdicts],
    }
    with open(RESULTS_FILE, 'w') as f:
        json.dump(payload, f, indent=2, default=float)
    print(f"\nSaved results -> {RESULTS_FILE}")
    try:
        archive_scan_results('meanrev', payload)
    except Exception as e:
        print(f"S3 archive failed: {e}")


if __name__ == '__main__':
    main()

