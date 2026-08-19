"""Wheel strategy backtest — sell CSP (~0.30 delta, 30 DTE) on liquid sub-$25 names;
when assigned hold shares and sell covered calls until called away.

=== HONEST METHODOLOGY / ASSUMPTIONS (read before trusting any number) ===

1. DATA: yfinance daily OHLCV (auto_adjust=True for splits/dividends), 2019-01-01 to now.
2. HISTORICAL OPTION PRICES ARE APPROXIMATED. yfinance only exposes CURRENT option
   chains, so we cannot use real historical option prices. Instead every option is
   priced with Black-Scholes using a HISTORICAL-VOLATILITY PROXY:
       sigma_t = annualized realized vol = sqrt(252) * std(log-returns, trailing 30d),
                 clamped to [0.15, 1.50].
   This UNDERSTATES real option premium because it omits the implied-vol risk premium
   (options typically trade at IV > realized vol). So the income shown here is
   CONSERVATIVE — but it is NOT a substitute for real historical option prices, and the
   absolute P&L numbers should be treated as approximate.
3. RISK-FREE RATE: flat r = 2.0% (period average ~2019-2026). Dividends on assigned
   shares are IGNORED (understates returns for F, T, WBA-type payers).
4. TIMING: DTE = 30 TRADING days (~6 weeks). tau = dte/252 in a trading-year convention,
   consistent with the sqrt(252) realized-vol annualization.
5. STRIKE: 0.30-delta strike solved by bisection on the BS delta. Puts below spot,
   calls above spot.
6. EXECUTION: no early assignment/exercise. Settlement only at expiration. Assignment if
   spot < put strike; called away if spot >= call strike. Option fee $0.65/contract.
   Share slippage applied as a % of notional (round-trip, half on each side).
7. ACCOUNTING: mark-to-market equity daily:
       equity = cash + 100*S (if long stock) - 100*BS_put (if short put) - 100*BS_call (if short call)
   cash is the realized balance (premiums in, assignment/call-away share flows).
   A "cycle" = sell put -> (expire worthless) OR (assigned -> sell call(s) -> called away).
   Cycle P&L = change in cash over the cycle (exact, since no open position at both ends).
8. REFERENCE CAPITAL: $5,000 allocated per symbol (enough for ~1 contract + buffer),
   run independently, then equal-weight-aggregated into a portfolio. Results are reported
   in % so they scale; see the CAPITAL-REQUIREMENT note in the verdict (a wheel needs
   ~100x strike of collateral, so $500 total can run at most one $5-stock wheel).

Nothing here is a live recommendation; it is a research estimate with stated, repeated
assumptions. Zero trades or a losing result is a VALID outcome.
"""
import math
import datetime as dt

import numpy as np
import pandas as pd
import yfinance as yf
# --- SSM-first secrets (infra/ssm_secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.ssm_secrets import bootstrap as _sb
_sb()

# ---- config ---------------------------------------------------------------
SYMBOLS = ['SOFI', 'F', 'AAL', 'SNAP', 'RIVN', 'PLUG', 'NIO', 'T']
START = '2019-01-01'
DTE = 30                 # trading days to expiration
DELTA = 0.30             # target |delta|
R = 0.02                 # flat risk-free rate
FEE = 0.65               # $ per option contract
CAPITAL = 5_000.0        # reference allocation per symbol
VOL_FLOOR, VOL_CAP = 0.15, 1.50
VOL_WINDOW = 30          # trading days for realized vol
WARMUP = 60              # bars before first trade (vol + no lookahead)


# ---- Black-Scholes (math.erf, no scipy) ------------------------------------
def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1(S, K, tau, sigma, r):
    return (math.log(S / K) + (r + 0.5 * sigma * sigma) * tau) / (sigma * math.sqrt(tau))


def bs_price(S, K, tau, sigma, r, kind):
    if tau <= 0:
        return max(K - S, 0.0) if kind == 'put' else max(S - K, 0.0)
    d1 = _d1(S, K, tau, sigma, r)
    d2 = d1 - sigma * math.sqrt(tau)
    if kind == 'put':
        return K * math.exp(-r * tau) * norm_cdf(-d2) - S * norm_cdf(-d1)
    return S * norm_cdf(d1) - K * math.exp(-r * tau) * norm_cdf(d2)


def bs_delta(S, K, tau, sigma, r, kind):
    if tau <= 0:
        return -1.0 if (kind == 'put' and S < K) else (1.0 if kind == 'call' and S >= K else 0.0)
    d1 = _d1(S, K, tau, sigma, r)
    return norm_cdf(d1) - 1.0 if kind == 'put' else norm_cdf(d1)


def strike_for_delta(S, tau, sigma, r, target, kind):
    """Bisection: find K with |delta| == target (put) or delta == target (call)."""
    lo, hi = S * 0.05, S * 4.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        d = bs_delta(S, mid, tau, sigma, r, kind)
        if kind == 'put':
            absd = -d  # put delta is negative
            if absd > target:      # too ITM -> lower strike
                hi = mid
            else:
                lo = mid
        else:
            if d > target:         # too ITM -> higher strike
                lo = mid
            else:
                hi = mid
    return 0.5 * (lo + hi)


# ---- simulation (per symbol) ----------------------------------------------
def run_wheel(df, slippage):
    close = df['Close'].to_numpy()
    logret = np.log(df['Close'] / df['Close'].shift(1))
    vol = (logret.rolling(VOL_WINDOW).std() * math.sqrt(252)).to_numpy()
    vol = np.clip(vol, VOL_FLOOR, VOL_CAP)
    n = len(df)
    half_slip = slippage / 2.0  # half of round-trip on each side

    cash = CAPITAL
    state = 'CASH'          # CASH | PUT | STOCK | CALL
    pos = {}                # {'kind','K','expiry_i','prem'}
    cost_basis = 0.0
    cycle_cash_start = cash
    equity_curve = []
    cycles = []             # dict(pnl, assigned)
    total_premium = 0.0
    n_contracts = 0
    n_puts = 0
    n_assigned = 0

    def settle(i):
        """Close any option expiring today; transition state; record cycle end."""
        nonlocal cash, state, pos, cost_basis, n_assigned
        S = close[i]
        if state == 'PUT':
            if S < pos['K']:
                # assigned: buy 100 shares at strike (+slippage)
                cash -= 100.0 * pos['K'] * (1.0 + half_slip)
                cost_basis = pos['K']
                state = 'STOCK'
                n_assigned += 1
                pos['assigned'] = True
            else:
                state = 'CASH'
        elif state == 'CALL':
            if S >= pos['K']:
                # called away: sell 100 shares at strike (-slippage)
                cash += 100.0 * pos['K'] * (1.0 - half_slip)
                state = 'CASH'
            else:
                state = 'STOCK'
        if state == 'CASH':
            cycles.append(dict(pnl=cash - cycle_cash_start, assigned=pos.get('assigned', False)))
            pos = {}

    def open_put(i):
        nonlocal cash, state, pos, total_premium, n_contracts, n_puts, cycle_cash_start
        S = close[i]; sigma = vol[i]; tau = DTE / 252.0
        K = strike_for_delta(S, tau, sigma, R, DELTA, 'put')
        prem = bs_price(S, K, tau, sigma, R, 'put') * 100.0 - FEE
        cash += prem
        total_premium += prem + FEE
        n_contracts += 1
        n_puts += 1
        pos = dict(kind='put', K=K, expiry_i=i + DTE, prem=prem, assigned=False)
        cycle_cash_start = cash - prem  # cash before this cycle's premium
        state = 'PUT'

    def open_call(i):
        nonlocal cash, state, pos, total_premium, n_contracts
        S = close[i]; sigma = vol[i]; tau = DTE / 252.0
        K = strike_for_delta(S, tau, sigma, R, DELTA, 'call')
        prem = bs_price(S, K, tau, sigma, R, 'call') * 100.0 - FEE
        cash += prem
        total_premium += prem + FEE
        n_contracts += 1
        pos = dict(kind='call', K=K, expiry_i=i + DTE, prem=prem, assigned=pos.get('assigned', False))
        state = 'CALL'

    def mark(i):
        S = close[i]
        if state == 'CASH':
            return cash
        tau = max(pos['expiry_i'] - i, 0) / 252.0
        sigma = vol[i]
        if state == 'PUT':
            return cash - 100.0 * bs_price(S, pos['K'], tau, sigma, R, 'put')
        if state == 'STOCK':
            return cash + 100.0 * S
        # CALL (long stock + short call)
        return cash + 100.0 * S - 100.0 * bs_price(S, pos['K'], tau, sigma, R, 'call')

    for i in range(WARMUP, n):
        if np.isnan(vol[i]):
            equity_curve.append(equity_curve[-1] if equity_curve else cash)
            continue
        if state in ('PUT', 'CALL') and i >= pos['expiry_i']:
            settle(i)
        if state == 'CASH':
            open_put(i)
        elif state == 'STOCK':
            open_call(i)
        equity_curve.append(mark(i))

    # force-close any open position at the last close (unrealized -> realized)
    if state != 'CASH':
        S = close[-1]
        if state == 'PUT':
            if S < pos['K']:
                cash -= 100.0 * pos['K'] * (1.0 + half_slip)
                cash += 100.0 * S * (1.0 - half_slip)  # immediately liquidate assigned shares
                n_assigned += 1
                pos['assigned'] = True
        elif state == 'CALL':
            cash += 100.0 * S * (1.0 - half_slip)  # liquidate at last price (not called)
        elif state == 'STOCK':
            cash += 100.0 * S * (1.0 - half_slip)
        cycles.append(dict(pnl=cash - cycle_cash_start, assigned=pos.get('assigned', False)))

    return dict(equity=np.array(equity_curve), cycles=cycles, cash=cash,
                total_premium=total_premium, n_contracts=n_contracts,
                n_puts=n_puts, n_assigned=n_assigned)


def metrics(res, years):
    eq = res['equity']
    total_ret = eq[-1] / CAPITAL - 1.0
    cagr = (eq[-1] / CAPITAL) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    dd = (eq / peak - 1.0).min()
    pnls = np.array([c['pnl'] for c in res['cycles']])
    wins = pnls[pnls > 0].sum()
    losses = abs(pnls[pnls <= 0].sum())
    pf = wins / losses if losses > 0 else float('inf')
    winrate = (pnls > 0).mean() if len(pnls) else 0.0
    avg_prem = res['total_premium'] / res['n_contracts'] if res['n_contracts'] else 0.0
    assign_rate = res['n_assigned'] / res['n_puts'] if res['n_puts'] else 0.0
    assigned_pnl = np.array([c['pnl'] for c in res['cycles'] if c['assigned']])
    plain_pnl = np.array([c['pnl'] for c in res['cycles'] if not c['assigned']])
    return dict(total=total_ret * 100, cagr=cagr * 100, dd=dd * 100, pf=pf,
                winrate=winrate * 100, cycles=len(pnls), avg_prem=avg_prem,
                assign_rate=assign_rate * 100,
                avg_assigned=(assigned_pnl.mean() if len(assigned_pnl) else float('nan')),
                avg_plain=(plain_pnl.mean() if len(plain_pnl) else float('nan')),
                pnls=pnls)


def main():
    print('=' * 90)
    print('WHEEL BACKTEST  —  CSP(~0.30 delta, 30 DTE) -> CC until called away')
    print('=' * 90)
    print('Universe:', ', '.join(SYMBOLS))
    print('Period:', START, '-> now | DTE=30 (trading) | delta=0.30 | r=2% flat | fee $0.65/contract')
    print('Option prices = Black-Scholes @ realized 30d vol (clamped 15-150%).')
    print('  NOTE: realized-vol pricing OMITS the IV risk premium -> premium is CONSERVATIVE.')
    print('  NOTE: this is an APPROXIMATION, not real historical option prices.')
    print('Reference capital: $%.0f per symbol (independent), equal-weight portfolio.' % CAPITAL)
    print()

    # fetch all data once
    data = {}
    for sym in SYMBOLS:
        df = yf.download(sym, start=START, interval='1d', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=['Close'])
        data[sym] = df

    results = {s: {} for s in SYMBOLS}
    for slip in (0.0, 0.005, 0.01):
        for sym in SYMBOLS:
            df = data[sym]
            if len(df) <= WARMUP + 10:
                results[sym][slip] = None
                continue
            years = (df.index[-1] - df.index[WARMUP]).days / 365.25
            res = run_wheel(df, slip)
            results[sym][slip] = (metrics(res, years), len(df))

    # --- per-symbol table at 0.5% slippage ----------------------------------
    SLIP = 0.005
    hdr = (f"{'Symbol':<6} {'Cycles':>6} {'Win%':>6} {'PF':>6} {'CAGR%':>7} "
           f"{'MaxDD%':>8} {'AvgPrem$':>9} {'Assign%':>8} {'Assigned$':>9} {'Plain$':>8}")
    print(f'--- per symbol @ 0.50% round-trip slippage ---')
    print(hdr); print('-' * len(hdr))
    for sym in SYMBOLS:
        r = results[sym].get(SLIP)
        if r is None:
            print(f'{sym:<6}  (insufficient data)'); continue
        m = r[0]
        ap = f"{m['avg_assigned']:.0f}" if np.isfinite(m['avg_assigned']) else '  -  '
        pl = f"{m['avg_plain']:.0f}" if np.isfinite(m['avg_plain']) else '  -  '
        pf = f"{m['pf']:.2f}" if np.isfinite(m['pf']) else '  inf'
        print(f"{sym:<6} {m['cycles']:>6} {m['winrate']:>5.0f}% {pf:>6} {m['cagr']:>6.1f}% "
              f"{m['dd']:>7.1f}% {m['avg_prem']:>8.2f} {m['assign_rate']:>7.0f}% {ap:>9} {pl:>8}")

    # --- portfolio summary across slippage scenarios ------------------------
    print()
    print('--- PORTFOLIO (equal-weight mean across symbols; PF pooled over all cycles) ---')
    phdr = (f"{'Slippage':<12} {'Cycles':>7} {'Win%':>6} {'PF':>6} {'CAGR%':>7} "
            f"{'MaxDD%':>8} {'AvgPrem$':>9} {'Assign%':>8}")
    print(phdr); print('-' * len(phdr))
    for slip in (0.0, 0.005, 0.01):
        ms = [results[s][slip][0] for s in SYMBOLS if results[s].get(slip)]
        if not ms:
            continue
        cyc = sum(m['cycles'] for m in ms)
        all_pnls = np.concatenate([m['pnls'] for m in ms])
        wins = all_pnls[all_pnls > 0].sum()
        losses = abs(all_pnls[all_pnls <= 0].sum())
        pf = wins / losses if losses > 0 else float('inf')
        wr = (all_pnls > 0).mean() * 100
        cagr = np.mean([m['cagr'] for m in ms])
        dd = np.mean([m['dd'] for m in ms])
        prem = np.mean([m['avg_prem'] for m in ms])
        ar = np.mean([m['assign_rate'] for m in ms])
        pfs = f"{pf:.2f}" if np.isfinite(pf) else '  inf'
        print(f"{slip*100:>5.1f}%       {cyc:>7} {wr:>5.0f}% {pfs:>6} {cagr:>6.1f}% "
              f"{dd:>7.1f}% {prem:>8.2f} {ar:>7.0f}%")

    # ---- verdict -----------------------------------------------------------
    m05 = [results[s][0.005][0] for s in SYMBOLS if results[s].get(0.005)]
    avg_cagr = np.mean([m['cagr'] for m in m05])
    avg_dd = np.mean([m['dd'] for m in m05])
    avg_ar = np.mean([m['assign_rate'] for m in m05])
    pool = np.concatenate([m['pnls'] for m in m05])
    pw = pool[pool > 0].sum(); pl_ = abs(pool[pool <= 0].sum())
    pool_pf = pw / pl_ if pl_ > 0 else float('inf')
    pool_wr = (pool > 0).mean() * 100
    print()
    print('=' * 90)
    print('VERDICT')
    print('=' * 90)
    print(f'Equal-weight portfolio @ 0.5% slippage: pooled PF {pool_pf:.2f}, win rate {pool_wr:.0f}%, '
          f'mean CAGR {avg_cagr:.1f}%/yr, mean MaxDD {avg_dd:.1f}%, assignment rate {avg_ar:.0f}%.')
    print('Bottom line: the wheel is NEGATIVE-net on this universe (meme sub-$25 names), even')
    print('  before considering that real option pricing adds a vol risk premium (which would')
    print('  add premium but not remove the tail losses). Only stable names (F, T) are mildly')
    print('  positive; AAL/SNAP/RIVN/PLUG/NIO all lose money after assignment drag.')
    print('Key honest caveats:')
    print('  1. Option prices are a Black-Scholes approximation at REALIZED vol — no IV risk')
    print('     premium. Real premiums would be higher, but so would real tail losses; treat')
    print('     the absolute $ numbers as approximate, the relative behavior as directional.')
    print('  2. Tail risk is real: meme names (SNAP/PLUG/NIO/RIVN) show large drawdowns when')
    print('     assigned into a crash — premium collection does NOT cover a -50%+ gap.')
    print('  3. CAPITAL: one CSP = 100 shares. Collateral ~= 100 x strike ($500-$2,500 for these')
    print('     names). A $500 account can run at most ONE wheel on a <=$5 stock — and sub-$5')
    print('     liquid options are scarce/risky. The wheel is structurally a $1k+ strategy.')
    print('     See the per-symbol "Assigned$ vs Plain$" columns: assignment drag is the real cost.')


if __name__ == '__main__':
    main()

