# Small-Capital LIVE Plan — Robinhood whole-share RSI2 ($700)

> **Date:** 2026-08-17 · **Author:** VPS Hermes (builder) · **Status:** PLAN — **no live orders placed.**
> Paper-forward first (unchanged). This doc answers *"what can $700 actually do live, today?"*

---

## 0. Context alignment (the correction this doc records)

**Capital is NOT a blocker.** The ~$700 in the Robinhood "Agentic" account
(`515821577`, `agentic_allowed=true`, `option_level_2`, `limited_margin`) is **live
capital, tradeable now** through `hardening/rh_client.py` (MCP gateway). The
fractional-stop limitation is **solved by whole-share sizing of small-ticket
liquid names** — not by declaring the lane blocked.

**Three things had to be true for "ENABLED", and all three now are:**

| What | Before | Now (verified 2026-08-17) |
|---|---|---|
| Capital | framed as blocker | ✅ **not a blocker** — ~$700 live in acct `515821577` |
| Fractional stop | framed as blocker | ✅ **solved** — whole-share small-ticket sizing (§2) |
| Transport | unverified | ✅ **fixed** — `notifications/initialized` was sent as an RPC (server rejected `unexpected id`); now sent as a proper MCP notification. Client reads acct + live quotes. |
| Token | dead (revoked) | ✅ **fresh** — re-authed 2026-08-16 21:58 ET, `expires_at` ≈ +7.8d, read verified |

**Still true (not blockers, just remaining work):**
- **No live order has been placed.** Paper-forward ≥30 days remains the owner standard before flipping LIVE.
- **Universe drift (new, data-driven):** the current universe ("top-50 S&P100 by
  20d $volume") is now almost entirely **>$35/share** (SPY $776, NVDA $225, AMD $514,
  MU $971 …). Only `T` (~$25) is sub-$35. Whole-share sizing at $700 therefore needs a
  **small-ticket liquid sub-universe** (§5). This is a *build task*, not a blocker.

---

## 1. The edge (unchanged, validated)

- **Entry:** Wilder RSI(2) < 5 **AND** close > SMA200 (per-name trend filter only).
- **Exit:** (1) 2×ATR(14) hard stop, whole-share; (2) 5-day time cap; (3) revert
  exit `close>SMA5 | RSI(2)>70`.
- **Validation:** OOS PF 1.47 walk-forward, **all 5 folds > 1.0**; ~1.36 @5bps.
- **Known weakness:** negative in single bear years (2008 PF 0.36, 2022 PF 0.81) →
  **bear-year warning flag on every signal**, satellite sizing, modest risk.
- **Index regime gate REJECTED** (validated: it hurt — 2022 0.81→0.21, no OOS lift).
  Do not re-add.

**Risk locks (unchanged, fail-closed in code):** 1% risk/trade · 5% capital/name
cap · $150/day realized-loss cap · stop mandatory (entry reversed if unprotected).

---

## 2. Whole-share sizing at $700 — the mechanics

The executability gate is **2×ATR per share ≤ 1% of capital ($7)**, *not* ticket
price. A name is whole-share-tradeable at $700 iff one share's stop distance
(2×ATR in $) costs ≤ $7 of risk. Position = `N = floor($7 / 2×ATR$)` shares, N ≥ 1.

**Grounded table (real closes + ATR(14), yfinance, 2026-08-17):**

| Ticket | Representative | close | 2×ATR % | 1-share risk (2×ATR$) | shares @ 1% risk | position $ | % of $700 |
|---|---|---|---|---|---|---|---|
| ~$5–10 | SNAP / NIO | $4.5–5.4 | 7–10% | $0.31–0.52 | 13–22 | $70–99 | 10–14% |
| ~$15 | F / AAL | $14.4–14.8 | 6–9% | $0.90–1.29 | 5–7 | $74–101 | 11–14% |
| ~$20–28 | KVUE / T / KHC / PFE / WBD | $19–28 | 4–6% | $0.88–1.54 | 4–7 | $102–168 | 15–24% |
| ~$31 | DOW | $31.1 | 7.2% | $2.24 | 3 | $93 | 13% |
| ~$48–88 | VZ / HPE / BAC / UBER / GM / KO | $48–88 | 3–11% | $2.09–6.25 | 1–3 | $59–193 | 8–28% |
| ~$100–140 | WMT / C | $115–139 | 4–5% | $5.01–6.44 | 1 | $115–139 | 16–20% |

**Names that FAIL the 1% gate (1 share already risks > $7) — excluded at $700:**
`INTC` ($102, 2×ATR 14% = $14.40) · `CSCO` ($111, $8.83) · `ORCL` ($150, $15.15) ·
`XOM` ($160, $7.29) · `PLTR`/`NVDA`/`TSLA`/`AMD`/`MU`/`GEV` (all ≥ $13.85/share risk).

> **Key truth:** at $700, a 1%-risk whole-share position is inherently
> **$59–$193 notional (8–28% of the book)** — because 1% risk on a single name with a
> 2×ATR stop forces a large notional. The 5% cap ($35) is what keeps it *satellite*;
> it only fits **sub-$35 names** (the top three rows). That tension is §4.

---

## 3. Max concurrent positions

Three independent bounds:

1. **Capital:** $700 ÷ avg position $ → **~4–12 positions** (ticket-dependent).
2. **Code:** `MAX_POSITIONS = 20` (hard ceiling, never the binding one at $700).
3. **Signal scarcity (the real binding bound):** `RSI(2)<5 AND close>SMA200` fires on
   **0–3 names/day** across the universe — the lane is a rare-event dip-buyer, not a
   book-filler. In practice you hold a *handful*, not 15.

**Recommended operating envelope: 5–15 concurrent, sub-$35 names, $14–$35 each**
(matches the owner's estimate, keeps every position satellite-sized).

---

## 4. The one honest decision: satellite (5% cap) vs "$10–$150 tickets"

The owner's "$10–$150 ticket" range spans two different risk shapes at $700:

| | **A — Satellite (RECOMMENDED)** | **B — Concentrated ("$10–$150 tickets")** |
|---|---|---|
| Cap | 5% capital/name ($35) — current code, zero changes | risk-only (1%, no 5% cap) |
| Names | sub-$35 only (F, AAL, KVUE, T, KHC, PFE, WBD, DOW, NIO, SNAP…) | $10–$150 (adds VZ, HPE, BAC, UBER, GM, KO, WMT, C) |
| Position | 1–3 shares = $14–$35 | 1–7 shares = $59–$193 |
| Concentration | ≤5% per name (true satellite) | **8–28% per name** (a single $150 name = 21% of the book) |
| Concurrent | ~5–15 | ~4–7 |
| Verdict | ✅ aligns with capital-preservation objective | ⚠️ a single-name gap-through could take 20%+ of the book |

**Recommendation:** stay on **A** (5% cap). It is the only shape consistent with the
2026-08-16 directive ("system must not lose money", drawdown-first, satellite sizing).
The "$150 ticket" case is really a *capital-scale* statement — to hold a $150 name at
≤5% concentration you need ≥$3,000, not $700. At $700 the honest small-capital live
lane is **whole shares of liquid sub-$35 names, 5–15 concurrent**.

**Owner decision needed (no code changes until resolved):** keep the 5% cap (A), or
explicitly authorize per-name concentration >5% to reach $100–$150 tickets (B)?

---

## 5. Universe gap → build task (not a blocker)

The current `bot/live_equities.py` universe (`STOCKS` = top-50 S&P100 by 20d $volume)
has drifted so far upmarket that only `T` is sub-$35. **To trade whole-share small-ticket
at $700, add a small-ticket liquid sub-universe** — e.g. liquid names $5–$35 screened by
20d avg $volume (≥ ~$50M/day) and a minimum price/quality floor, refreshed monthly (same
rule discipline as today's top-50). The ETFs stay **fractional-only** at $700 (SPY $776
= 1 share > whole book) — they remain paper/DCA, out of the whole-share live lane.

**Before ANY live order, the build list is:**
1. Small-ticket liquid sub-universe (above).
2. `place_equity_entry` whole-share path already works (verified); confirm 1-share
   stop rests on a real $15 name via `review_equity_order` (simulate) → then one paper
   round-trip.
3. Robinhood reconciler (broker-side stop fills not yet reconciled — follow-on, see
   `docs/ROBINHOOD_EXECUTION.md` §5).
4. Paper-forward ≥30 days on the sub-universe, judged drawdown-first.

---

## 6. Daily-loss cap — enforcement mechanics

- **$150/day realized-loss cap** (`RH_DAY_LOSS_CAP`), enforced as a **throttle on new
  entries**: once `day_loss_used ≥ $150`, `live_gate_ok` refuses every new entry until
  the next session (restart-safe via the persistent ledger, not the in-run counter).
- At 1% risk/trade a full stop-out costs **$7**. Pure stop-outs cannot breach $150:
  worst single day = ~5 positions × $7 = **$35** (satellite A) up to ~15 × $7 = **$105**.
- The only way to breach $150 is **gap-throughs** (open below stop, realizing > 2×ATR)
  or a fat-finger — which is exactly what the cap exists to brake. A single gap-through
  on a concentrated (B) position is why §4 matters.

---

## 7. Rollout (unchanged — do NOT place live orders yet)

1. **Now (done):** transport fix + fresh token verified; this plan.
2. **Paper-forward ≥30 days** on the running bot (drawdown-first evaluation).
3. **Sub-universe build** (§5) + `review_equity_order` simulate on a real $15 name.
4. **Then, and only then:** flip `RH_EXECUTION_MODE=LIVE` + `RH_LIVE_ENABLED=true`,
   watch the first LIVE `RHSIG#` row carry `mode=LIVE, execution=RH` with an
   `order_id` + `stop_order_id`, and reconcile against `get_positions()`.
