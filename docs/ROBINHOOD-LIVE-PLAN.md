# Robinhood LIVE Plan — $700 small-capital (whole-share small-ticket RSI2)

> **Date:** 2026-08-17 · **Author:** VPS Hermes (builder) · **Status:** LIVE-READY — **no live orders placed.**
> Canonical pre-go-live plan. Deeper sizing analysis + the satellite-vs-concentration decision live in
> [`SMALL-CAPITAL-LIVE-PLAN.md`](SMALL-CAPITAL-LIVE-PLAN.md); execution spec in [`ROBINHOOD_EXECUTION.md`](ROBINHOOD_EXECUTION.md).

---

## 1. Live account — verified 2026-08-16 (read-only, no orders)

Pulled fresh via the single-writer `hardening/rh_client.py` → Robinhood MCP gateway.

| Field | Value |
|---|---|
| Account | `515821577` ("Agentic", `agentic_allowed=true`, `option_level_2`, `limited_margin`) |
| **Total value** | **$700.06** |
| **Cash** | **$675.00** |
| **Buying power** | **$675.00** (unleveraged $675.00) |
| Pending deposits | **$700.00** ⚠️ a deposit is still settling — effective capital may grow once settled |
| Equity positions | SPY `0.016097` @ $776.54 · QQQ `0.017134` @ $729.54 (≈ **$25.06** = the DCA base layer) |
| Options / crypto / futures | $0 |

**Key read:** spendable capital today is **$675 buying power**, not $700. The $700
pending deposit means the account may be ~$1,400 once it settles — **re-pull and
re-size against actual buying power before the first live order**, never the "$700"
label.

## 2. Position-sizing table (whole-share, 1% risk, 2×ATR stop)

Executability gate: **one share's 2×ATR distance ≤ 1% of capital ($6.75)**.
`shares = floor($6.75 / 2×ATR$)`, min 1. Grounded with real closes + ATR(14)
(Robinhood technical-indicators tool, 2026-08-14 close; F/T quoted live).

| Ticket | Representative | close | 2×ATR (real) | 1-share risk | shares @ 1% | position $ | % of $675 |
|---|---|---|---|---|---|---|---|
| ~$5–10 | SNAP / NIO | $4.5–5.4 | $0.31–0.52 | $0.31–0.52 | 13–21 | $70–99 | 10–15% |
| ~$14 | **F** | $14.37 | $0.89 | $0.89 | **7** | **$100.59** | **15%** |
| ~$15 | AAL | $14.8 | $0.90–1.29 | $0.90–1.29 | 5–7 | $74–101 | 11–15% |
| ~$25 | **T** / KHC / PFE / WBD | $24.89 | $1.29 | $1.29 | **5** | **$124.45** | **18%** |
| ~$28–31 | KVUE / DOW | $28–31 | $1.3–2.2 | $1.3–2.2 | 3–5 | $93–155 | 14–23% |
| ~$48–88 | VZ / HPE / BAC / UBER / KO | $48–88 | $2.09–6.25 | $2.09–6.25 | 1–3 | $59–193 | 9–29% |

**Excluded at $675 (1 share already risks > $6.75):** INTC, CSCO, ORCL, XOM, PLTR,
NVDA, TSLA, AMD, MU, GEV.

> ⚠️ **1% risk and the 5% name cap conflict at $700.** 1%-risk sizing forces
> $59–$193 notional (8–29% of the book) per position. The 5% cap ($33.75) instead
> limits a position to **2 shares of F / 1 share of T** (true satellite). The
> recommended shape is the **5% cap** (satellite); the 1%-risk-only shape is
> concentrated and a single gap-through can take 15–29% of the book. **Owner must
> pick satellite (5% cap, recommended) vs concentrated ($10–$150 tickets) before
> any live order** — see `SMALL-CAPITAL-LIVE-PLAN.md` §4.

## 3. Max concurrent positions

| Bound | Value |
|---|---|
| 5% capital cap ($33.75/name) | $675 ÷ $33.75 = **20** |
| Code ceiling `MAX_POSITIONS` | **20** |
| 1% risk + $150/day cap (pure stop-outs $6.75–7 each) | ~21 to trip the cap — not the binding bound |
| Signal scarcity (RSI(2)<5 fires 0–3 names/day) | a handful in practice |

**Answer: hard ceiling = 20 concurrent positions** (5% cap and `MAX_POSITIONS` both
bind at 20); **recommended operating envelope = 5–15** sub-$35 names of $14–$35 each.

## 4. Worked example — Ford (F)

> Real quote + ATR(14) pulled 2026-08-16 via the Robinhood MCP (no order placed).

1. **Signal:** F dips on a washout day — RSI(2) < 5 **and** close > SMA200 (uptrend intact).
2. **Entry:** market buy ~$14.37 (last close 2026-08-14; ask $14.36).
3. **2×ATR(14)** = 2 × $0.4474 = **$0.89/share**.
4. **Protective stop (broker-side, whole-share, GTC):** $14.37 − $0.89 = **$13.47** (stop_market).
5. **Sizing — satellite (5% cap, recommended):** $33.75 ÷ $14.37 = **2 shares** → $28.74 notional (4.3%), risk $1.78 (0.26%).
   **Sizing — 1% risk only:** $6.75 ÷ $0.89 = **7 shares** → $100.59 notional (15%), risk $6.23 (0.92%).
6. **Exits:** (1) hard stop $13.47; (2) 5-day time cap; (3) revert exit `close>SMA5 | RSI(2)>70`.

## 5. Go-live checklist (do NOT place live orders yet)

1. ✅ Transport + fresh token verified; read path works (this doc §1).
2. ⬜ Owner resolves satellite (5% cap) vs concentrated (§2, `SMALL-CAPITAL-LIVE-PLAN.md` §4).
3. ⬜ Build the small-ticket liquid sub-universe ($5–35, 20d $vol ≥ ~$50M/day) — `live_equities.py` universe has drifted almost entirely >$35.
4. ⬜ `review_equity_order` (simulate) on a real ~$15 name → confirm a 1-share stop rests.
5. ⬜ Paper-forward ≥30 days on the sub-universe, judged drawdown-first.
6. ⬜ Then flip `RH_EXECUTION_MODE=LIVE` + `RH_LIVE_ENABLED=true`; watch the first LIVE `RHSIG#` row carry `mode=LIVE` + `order_id` + `stop_order_id`, reconcile vs `get_positions()`.
