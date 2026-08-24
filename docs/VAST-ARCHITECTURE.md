# Vast Architecture — Round-the-Clock Multi-Strategy Execution

**Date:** 2026-08-24 · **Status:** Phase 1 shipped; Phases 2–4 designed.
**Goal:** manage every US stock (~6,000), test *all* strategies against *all* names, run 24/7 in parallel, at the lowest defensible cost — while never breaking the validated edges already live.

## Design principles

1. **Paper-first, promote-on-proof** — every strategy × universe slice runs on paper; a signal only goes live once it holds PF ≥ 1.3 OOS *and* survives 2× cost (the never-lose discipline). Live stays hard-capped (5 positions / $50 day).
2. **Batch everything** — data fetch, DynamoDB writes, signal computation. The cost driver at 6,000 names is API-call count, not compute.
3. **Free/keyless data first** — yfinance, IBKR (paper), FRED, Wikipedia S&P constituents, Nasdaq listings. Vendors only when a signal *needs* it.
4. **One source of truth** — S3 lake (prices) + DynamoDB (signals/positions/trades). Reconciler cross-checks broker vs internal every 47s.

## Layered architecture

```
┌─ Universe layer   data_engine/universe.py — ~6,000 US common stocks (Nasdaq
│                    listing), liquidity-ranked (dollar-volume), survivorship-
│                    aware history. Broad (1,459) = tradeable; full (6,000) = research.
├─ Strategy layer   pluggable strategy registry — each strategy = (signal, entry,
│                    exit, backtest). Current: RSI2, REV2, VWAP-2σ, Donchian,
│                    crypto MOM20. Future: add without touching execution.
├─ Signal engine    batched/vectorized signal computation across names × strategies,
│                    chunked to bound RAM (t3.small). Writes via batch_writer.
├─ Backtest/val     honest fills (≥5bps / ≥1tick), IS/OOS split, 2×-cost stress,
│                    promote survivors to paper → live.
├─ Execution layer  portfolio manager + never-lose: broker-side stop on every entry,
│                    reconciler, kill-switch (CONTROL), earnings guard, day-loss cap.
├─ Scheduler        round-the-clock (below).
└─ Monitoring       reconciler (47s), health watchdog (5m), dashboard, reports.
```

## Round-the-clock scheduler (parallel)

| Asset | Session | Cadence | Status |
|---|---|---|---|
| Crypto (BTC/ETH/XRP) | 24/7 | 30-min MOM20 | ✅ live-paper |
| Futures | globex + RTH | daily EOD + 15-min VWAP + 15-min fade/donch | ✅ RTH; globex = Phase 3 |
| Equities | RTH close→open | daily 19:20 (RH) + 09:30 (IBKR) | ✅ live |
| Equities | overnight MOC | the +10.7bp close-entry refinement | Phase 3 |
| Research/backtest | 24/7 | subagent edge-hunts + weekly scan | ✅ |

## Cost model (target: < ~$15/mo AWS + free data)

- **DynamoDB on-demand** `trading-data` (2.7 MB, 0 throttle): batch writes cut call count 25×; at 6,000 names the daily write bill stays sub-cent.
- **EC2 t3.small** ($~13/mo): batch fetch + chunked processing keeps RAM flat; upgrade to t3.medium only if the full 6,000-name signal sweep needs it.
- **S3**: ~GBs of bars, pennies/month.
- **Data**: yfinance (free, rate-limited — batch + fallback), IBKR paper (free), FRED/CBOE/Wikipedia/Nasdaq (free). No paid vendor until a signal justifies it.

## Phased plan

- **Phase 1 — batch fetch + batch writes + 1,459-name universe** ✅ *shipped (this commit)*. `fetch_batch()` (1 call), `flush_writes()` (batch_writer), dynamic universe loader (S&P 1500, adv≥$10M, price>$2) with STOCKS fallback.
- **Phase 2 — strategy registry + unified signal engine**: refactor `live_equities.py`'s RSI2 loop into a strategy-agnostic engine (signal per strategy × name, batched, chunked); add REV2/VWAP/Donchian as pluggable strategies on equities. Test all strategies on the 1,459 universe.
- **Phase 3 — round-the-clock**: extend futures to globex; add the overnight-MOC equity lane (the +10.7bp close-entry finding); wire the spot-VIX fear-gauge (z≥1.5 → long S&P 5–10d) as a low-frequency timing sleeve.
- **Phase 4 — full universe (~6,000) + auto-promotion**: run the signal sweep over the full universe nightly; auto-promote strategy × name pairs that clear the validation bar to paper, then (after a forward-test window) to live under the caps.

## Safety invariants (must hold across every phase)

`--dry-run` never orders · `--force` requires `--dry-run` · earnings guard intact · position cap intact · reconciler still reconciles · kill-switch read before any entry · LIVE stays on the sub-$35 whole-share subset until owner widens it.

## Non-goals

Not chasing new signal sources (alt-data / VIX-slope / reversal variants all NO-GO — lanes 36–44). This is *execution scale* on the validated mean-reversion + momentum family, not a new alpha hunt.
