# Trailing-Stop Verdict — Robinhood RSI(2) Lane

**Date:** 2026-08-25 · **Data:** IBKR broker daily bars (`s3 ibkr/equities/daily`),
383 usable symbols, 2007-06-07 → 2026-08-24 · **Costs:** 5 bps per side
**Script:** `research/trailing_variant_backtest.py`

## Verdict: DO NOT ENABLE TRAILING. Keep the fixed 2×ATR stop.

The owner asked for "a more intelligent trailing stop loss for Robinhood". It was
built (`bot/rh_trailing_smart.py`), backtested, and it **lost** — it is the worst
of the three variants. Reporting that straight rather than shipping it.

| variant | n | PF | win% | avg net/trade | median | t-stat | avg hold |
|---|---|---|---|---|---|---|---|
| **FIXED 2×ATR** (current live) | 11,760 | **1.110** | 62.9% | **+18.1 bp** | +85.4 bp | **+3.30** | 2.25 |
| NAIVE trail from entry (old disabled bot) | 11,928 | 1.004 | 60.2% | +0.6 bp | +72.4 bp | 0.13 | 2.06 |
| SMART armed ratchet (new) | 11,827 | 0.927 | 55.2% | **−11.8 bp** | +38.9 bp | **−2.64** | 2.14 |

Fixed is the only variant with statistically significant positive expectancy
(t = +3.30). NAIVE destroys the edge (t = 0.13, no edge left). SMART is
significantly **negative** (t = −2.64) — it would reliably lose money.

## Why every trailing variant loses — the mechanism

Look at the exit mix:

| variant | revert | stop | time | **gap_stop** |
|---|---|---|---|---|
| FIXED | 8,531 | 1,629 | 1,243 | **357** |
| NAIVE | 8,031 | 2,509 | 731 | **657** |
| SMART | 7,563 | 2,335 | 1,041 | **888** |

**Gap-through exits go 357 → 888 (2.5×).** Moving the stop up puts it inside the
overnight gap distribution. And this is where the Robinhood constraint measured
earlier the same day bites: **RH stops are RTH-only**, so a gap below the stop
does not fill at the stop — it fills at the open, arbitrarily worse. Every ratchet
upward converts a would-be winner into a gap loss.

Compounding the damage: revert exits fall 8,531 → 7,563. The trail is stealing
trades from the rule that actually makes the money (close > SMA5 / RSI2 > 70)
before the mean reversion completes. A 2.25-session hold has no room for a trail.

**A tighter stop is not more protection on this strategy — it is more exposure to
the one risk we cannot control (the overnight gap).**

## What ships instead

- `bot/rh_trailing_smart.py` stays in the repo but **DISABLED** (no cron, and it
  is a no-op at stage INITIAL anyway). Kept for the record and re-testable.
- The stop stays **fixed 2×ATR, set once at entry**, resting broker-side.
- Real risk control on this lane is **position sizing**, not stop tightness —
  $43.71 max risk on ~$700 across 9 positions.

## The part of the request that WAS valid and is now enforced

"At least the bot will make sure something is trading before applying stop loss."
That gap was real. `bot/rh_trailing_smart.py::verify_tradeable()` is now the hard
gate used before any stop action, and it is the pattern the other tools follow:

1. broker reports a **LONG** position for the symbol
2. `quantity >= 1` and **whole** (RH stops are whole-share only)
3. shares accounted for: `shares_available_for_sells + shares_held_for_sells >= quantity`
4. **orphan stops are CANCELLED** — a resting sell-stop with no position can
   SHORT the account if it triggers

Note `shares_held_for_sells == quantity` is *normal* once a stop rests: RH reserves
the shares, so `shares_available_for_sells` reads 0 and the app shows the position
as tied up in a pending order. That is a resting stop, not a sale.

## Caveat

The FIXED PF here (1.110) is not comparable to the 1.319 in earlier notes — different
universe, period and cost model. What is valid is the **relative** comparison: all
three variants ran on identical data through identical code, so the ranking and the
gap_stop mechanism are the finding, not the absolute PF level.

## Reproduce

```bash
./venv/bin/python research/trailing_variant_backtest.py --limit 400
```
Output: `research/trailing_variant_backtest.json`
