#!/usr/bin/env python3
"""TRAILING-STOP VALIDATION — fixed vs intelligent-trailing for the two index-LONG edges.

Owner gate (dispatch 1786801098609):
  - Donchian chandelier 3*ATR (vs fixed 2*ATR) and RSI2 ATR-ratchet (vs fixed 2*ATR).
  - SHIP  if trailing LOWERS maxDD AND holds OOS PF >= ~1.4 @2-tick.
  - REVERT if trailing HURTS (PF drops). Never silently keep a worse edge.

Exact trail rules under test (mirror bot/live.py):
  DONCHIAN chandelier: initial stop = entry - 2*ATR(14); each daily eval trail to
    (highest CLOSE since entry) - 3*ATR, only upward (tighten-only).
  RSI2 ATR-ratchet:     initial stop = entry - 2*ATR; at close >= entry + 1*ATR
    -> breakeven (entry); at close >= entry + 2*ATR -> trail (highest close since
    entry) - 2*ATR, only upward. RSI(2)>70 stays the PRIMARY exit (backstop only).

Honest fill model (same as validate_edges.py):
  - entry at signal-bar close + adverse slippage.
  - GTC stop intraday + gap-aware (open<stop -> fill at open; else low<=stop -> stop).
  - close-based exits (time / signal / breakout) at close + slippage.
  - one entry OR exit per bar.
Cost: fee 1.3bp round-trip; slippage 0/1/2/3 ticks per side.
"""
import os
import sys
import json

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_edges import (wilder_atr, rsi, FEE_BPS, SLIP_TICKS, SPECS,
                            load_yfinance, metrics, pf_of, trade_record)

EDGE_INSTRUMENTS = ['ES=F', 'NQ=F', 'YM=F']
LOOKBACK = 20
MAX_HOLD = 5
STOP_ATR = 2.0
CHAND_ATR = 3.0          # Donchian chandelier trail distance
RATCHET_BREAKEVEN = 1.0  # RSI2 breakeven trigger (entry + 1*ATR)
RATCHET_TRAIL = 2.0      # RSI2 trail distance (peak - 2*ATR)
RSI2_LO = 10.0
RSI2_HI = 70.0


def run_donchian(df, trail=False, mult=50.0, tick=0.25, fee_bps=FEE_BPS, slip=0):
    """LONG Donchian breakout. Fixed 2*ATR stop, or chandelier 3*ATR trail."""
    c, h, l, o = df['Close'], df['High'], df['Low'], df['Open']
    atr = wilder_atr(h, l, c)
    don_hi = h.rolling(LOOKBACK).max().shift(1)
    don_lo = l.rolling(LOOKBACK).min().shift(1)
    warmup = LOOKBACK + 2
    trades, eq = [], []
    pos, entry_px, entry_i, stop = 0, 0.0, 0, 0.0
    cash = 0.0
    for i in range(warmup, len(df)):
        oi, ci, bar_h, bar_l = o.iloc[i], c.iloc[i], h.iloc[i], l.iloc[i]
        if pos == 0:
            if not np.isnan(don_hi.iloc[i]) and ci > don_hi.iloc[i]:
                entry_px, entry_i = ci + slip * tick, i
                stop = ci - STOP_ATR * atr.iloc[i]
                pos = 1
        else:
            held = i - entry_i
            mae = (l.iloc[entry_i:i + 1].min() - entry_px)
            mfe = (h.iloc[entry_i:i + 1].max() - entry_px)
            exit_px = reason = None
            if oi < stop:                              # gap through stop
                exit_px, reason = oi - slip * tick, 'stop_gap'
            elif bar_l <= stop:                        # intraday stop hit
                exit_px, reason = stop - slip * tick, 'stop'
            if exit_px is None and held >= MAX_HOLD:
                exit_px, reason = ci - slip * tick, 'time'
            if exit_px is None and not np.isnan(don_lo.iloc[i]) and ci < don_lo.iloc[i]:
                exit_px, reason = ci - slip * tick, 'breakout'
            if exit_px is not None:
                fee = fee_bps * entry_px * mult
                trades.append(trade_record(entry_px, entry_i, exit_px, i, 1,
                                           reason, mult, fee, mae, mfe))
                cash += trades[-1]['pnl']
                pos = 0
            elif trail:
                # chandelier: tighten at close (applies from next bar)
                peak = c.iloc[entry_i:i + 1].max()
                cand = peak - CHAND_ATR * atr.iloc[i]
                if cand > stop:
                    stop = cand
        eq.append(cash + (ci - entry_px) * mult if pos == 1 else cash)
    return trades, pd.Series(eq, index=df.index[warmup:])


def run_rsi2_long(df, trail=False, mult=50.0, tick=0.25, fee_bps=FEE_BPS, slip=0):
    """LONG RSI(2) buy-dip WITH a 2*ATR hard stop (fixed or ratchet-trailed).

    RSI(2)>70 is the PRIMARY exit; the stop/trail is the backstop.
    """
    c, h, l, o = df['Close'], df['High'], df['Low'], df['Open']
    atr = wilder_atr(h, l, c)
    r2 = rsi(c, 2)
    warmup = 15
    trades, eq = [], []
    pos, entry_px, entry_i, stop, entry_atr = 0, 0.0, 0, 0.0, 0.0
    cash = 0.0
    for i in range(warmup, len(df)):
        oi, ci, bar_h, bar_l = o.iloc[i], c.iloc[i], h.iloc[i], l.iloc[i]
        if pos == 0:
            if r2.iloc[i] < RSI2_LO:
                entry_px, entry_i = ci + slip * tick, i
                entry_atr = atr.iloc[i]
                stop = ci - STOP_ATR * entry_atr
                pos = 1
        else:
            held = i - entry_i
            mae = (l.iloc[entry_i:i + 1].min() - entry_px)
            mfe = (h.iloc[entry_i:i + 1].max() - entry_px)
            exit_px = reason = None
            if oi < stop:                              # gap through stop
                exit_px, reason = oi - slip * tick, 'stop_gap'
            elif bar_l <= stop:                        # intraday stop hit
                exit_px, reason = stop - slip * tick, 'stop'
            if exit_px is None and held >= MAX_HOLD:
                exit_px, reason = ci - slip * tick, 'time'
            if exit_px is None and r2.iloc[i] > RSI2_HI:
                exit_px, reason = ci - slip * tick, 'signal'
            if exit_px is not None:
                fee = fee_bps * entry_px * mult
                trades.append(trade_record(entry_px, entry_i, exit_px, i, 1,
                                           reason, mult, fee, mae, mfe))
                cash += trades[-1]['pnl']
                pos = 0
            elif trail:
                # ATR ratchet at close (applies from next bar)
                cand = None
                if ci >= entry_px + RATCHET_BREAKEVEN * entry_atr:
                    cand = entry_px                        # breakeven
                if ci >= entry_px + RATCHET_TRAIL * entry_atr:
                    peak = c.iloc[entry_i:i + 1].max()
                    cand = peak - RATCHET_TRAIL * atr.iloc[i]
                if cand is not None and cand > stop:
                    stop = cand
        eq.append(cash + (ci - entry_px) * mult if pos == 1 else cash)
    return trades, pd.Series(eq, index=df.index[warmup:])


RUNNERS = {'DONCHIAN': run_donchian, 'RSI2': run_rsi2_long}


def oos_pf(trades, n, warmup=25):
    """Last-40% OOS profit factor (trades bucketed by entry index)."""
    oos_start = warmup + int((n - warmup) * 0.6)
    oos = [t for t in trades if t['entry_i'] >= oos_start]
    return pf_of(oos)


def compare_one(df, strategy, tk):
    mult, tick = SPECS[tk][1], SPECS[tk][2]
    n = len(df)
    out = {'ticker': tk}
    for mode, kw in (('fixed', {}), ('trail', {'trail': True})):
        d = {}
        # full-sample baseline (0 slip, 1.3bp) -> metrics incl maxDD
        trades, eq = RUNNERS[strategy](df, mult=mult, tick=tick, **kw)
        m = metrics(trades, eq, n / 252.0)
        d['trades'] = m['trades']
        d['pf'] = m['pf']
        d['maxdd'] = m['maxdd']
        d['net'] = m['net']
        d['winrate'] = m['winrate']
        # pooled OOS (last 40%)
        opf, on = oos_pf(trades, n)
        d['oos_pf'] = opf
        d['oos_trades'] = on
        # @2-tick cost stress (full sample)
        t2, _ = RUNNERS[strategy](df, mult=mult, tick=tick, fee_bps=FEE_BPS, slip=2, **kw)
        m2 = metrics(t2, _, n / 252.0)
        d['pf_2tick'] = m2['pf']
        d['maxdd_2tick'] = m2['maxdd']
        # @2-tick OOS PF (the gate metric)
        opf2, on2 = oos_pf(t2, n)
        d['oos_pf_2tick'] = opf2
        d['oos_trades_2tick'] = on2
        out[mode] = d
    return out


def main():
    print("TRAILING-STOP VALIDATION — fixed vs trailing (index-LONG)")
    print(f"fee={FEE_BPS:.5f} (1.3bp), slippage 0/2 ticks/side; OOS = last 40%")
    print("=" * 110)

    dfs = {}
    for tk in EDGE_INSTRUMENTS:
        try:
            df = load_yfinance(tk)
            if df is not None and len(df) > 260:
                dfs[tk] = df
            else:
                print(f"SKIP {tk}: insufficient data")
        except Exception as e:  # noqa: BLE001
            print(f"SKIP {tk}: {type(e).__name__}: {e}")

    report = {'fee_bps': FEE_BPS, 'strategies': {}}
    for strategy in ('DONCHIAN', 'RSI2'):
        print(f"\n[{strategy}]\n" + "-" * 110)
        hdr = (f"{'ticker':6} | {'mode':6} | {'trades':>6} {'win%':>5} {'PF':>6} "
               f"{'maxDD$':>11} {'net$':>11} | {'OOS PF':>7} {'OOS n':>6} | "
               f"{'PF@2t':>6} {'OOS@2t':>7}")
        print(hdr)
        strat_report = {}
        for tk in EDGE_INSTRUMENTS:
            if tk not in dfs:
                continue
            row = compare_one(dfs[tk], strategy, tk)
            strat_report[tk] = row
            for mode in ('fixed', 'trail'):
                d = row[mode]
                print(f"{tk:6} | {mode:6} | {d['trades']:>6} {d['winrate']:>5.0f} "
                      f"{d['pf']:>6.2f} {d['maxdd']:>11,.0f} {d['net']:>11,.0f} | "
                      f"{d['oos_pf']:>7.2f} {d['oos_trades']:>6} | "
                      f"{d['pf_2tick']:>6.2f} {d['oos_pf_2tick']:>7.2f}")
        report['strategies'][strategy] = strat_report

    # gate verdict
    print("\n" + "=" * 110)
    print("GATE VERDICT")
    print("=" * 110)
    for strategy in ('DONCHIAN', 'RSI2'):
        print(f"\n[{strategy}]  ship if: maxDD LOWERED (trail vs fixed) AND OOS PF @2tick >= 1.4")
        for tk in EDGE_INSTRUMENTS:
            if tk not in dfs:
                continue
            f, t = report['strategies'][strategy][tk]['fixed'], report['strategies'][strategy][tk]['trail']
            dd_ok = t['maxdd'] > f['maxdd']  # maxdd is <= 0; higher (less negative) = lower drawdown
            pf_ok = t['oos_pf_2tick'] >= 1.4 and t['pf_2tick'] >= 1.0
            hurt = t['pf'] < f['pf'] - 0.02 or t['oos_pf_2tick'] < f['oos_pf_2tick'] - 0.02
            verdict = 'SHIP' if (dd_ok and pf_ok) else ('REVERT (hurts)' if hurt else 'HOLD/marginal')
            print(f"  {tk:6}: maxDD {f['maxdd']:>11,.0f} -> {t['maxdd']:>11,.0f} "
                  f"({'LOWERED' if dd_ok else 'worse'}) | OOS@2t {f['oos_pf_2tick']:.2f} -> "
                  f"{t['oos_pf_2tick']:.2f} | PF {f['pf']:.2f} -> {t['pf']:.2f}  => {verdict}")

    outfile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'trailing_stop_validation_results.json')
    with open(outfile, 'w') as f:
        json.dump(report, f, indent=2, default=float)
    print(f"\nSaved -> {outfile}")
    try:
        from data.s3_archive import archive_scan_results
        archive_scan_results('trailing-stop-validation', report)
        print("Archived to S3 research/scan-results/trailing-stop-validation/")
    except Exception as e:  # noqa: BLE001
        print(f"S3 archive failed: {e}")


if __name__ == '__main__':
    main()
