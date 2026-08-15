# Options Lane — plan (what is possible now vs what needs a subscription)

> Generated 2026-08-15T01:00:57.573867+00:00. Futures-options are PAPER/RESEARCH only. Equity-options research lives on the LAPTOP (Robinhood MCP, Option Level 2).

## What is collected NOW (free, already flowing)

- **Chain metadata** for 12 liquid futures-options underlyings: `options/<sym>/chains.json` (full strike + expiry axes via `reqSecDefOptParams`) + `OPTCHAIN#<sym>` (DynamoDB hot summary).

- **Underlying futures bars** (`futures-bars/daily/<sym>/`) for spot/ATM context.


## Chain analysis (scaffold)

| Sym | Exps | Strikes | Strike range | Expiry range | Spot | ±5% | ±10% | ATM strike |
|---|---|---|---|---|---|---|---|---|
| ES | 24 | 504 | 100.0–12000.0 | 20260817–20260918 | 7802.5 | 156 | 255 | 7800.0 |
| NQ | 16 | 556 | 5000.0–43000.0 | 20260817–20260918 | 30154.0 | 306 | 407 | 30150.0 |
| CL | 1 | 451 | 2.5–400.0 | 20260817–20260817 | 82.4 | 17 | 33 | 82.5 |
| NG | 8 | 236 | 0.05–19.25 | 20260817–20260826 | 2.715 | 6 | 11 | 2.7 |
| GC | 22 | 684 | 500.0–13000.0 | 20260817–20260924 | 4373.9 | 87 | 175 | 4375.0 |
| SI | 8 | 557 | 21.0–350.0 | 20260817–20260826 | 64.825 | 78 | 155 | 64.8 |
| HG | 8 | 224 | 0.75–9.75 | 20260817–20260826 | 6.589 | 66 | 130 | 6.59 |
| ZB | 5 | 138 | 50.0–300.0 | 20260817–20260821 | 108.90625 | 22 | 43 | 109.0 |
| ZN | 5 | 214 | 83.0–138.5 | 20260817–20260821 | 108.59375 | 44 | 87 | 108.5 |
| ZC | 5 | 140 | 220.0–1000.0 | 20260817–20260821 | 459.25 | 46 | 77 | 459.0 |
| ZS | 5 | 195 | 540.0–3000.0 | 20260817–20260821 | 1176.25 | 59 | 103 | 1176.0 |
| ZW | 5 | 176 | 280.0–3000.0 | 20260817–20260821 | 674.0 | 40 | 68 | 674.0 |

## Vol-surface / greeks: NOT computable today (honest gap)

- We have the chain SKELETON (strikes × expiries), not option PRICES. An IV/vol surface, greeks, skew/term-structure, and any options backtest require **historical option BARS + real-time option quotes** — a **separate paid IBKR subscription**, NOT in the CME Group L1 bundle. `options_chains.py` does not and cannot request them.

- **Decision: do NOT request the bars subscription yet.** Per the data-integrity standing rule, we only pay when an options edge is actually worth pursuing. Chain analysis can screen for *structure* (liquid strikes near ATM, expiry ladder length) but cannot validate a P&L edge without prices.


## What needs a subscription (flag, do NOT buy yet)

| Subscription | Unlocks | Needed for | Status |
|---|---|---|---|
| Historical options bars | vol surface, IV history, options backtests | any vol/skew/term-structure or options-selling edge | NOT requested |
| Real-time option quotes | live greeks, IV, order-flow | intraday options execution | NOT requested |
| L2 market depth | order book / flow | depth-based options edges | NOT requested |

## Equity-options (laptop, Robinhood MCP Option Level 2)

- The laptop Hermes owns equity-options research + order placement (RH L2: CSP→CC wheel). The VPS has NO Robinhood access. Any equity-options edge is validated on the laptop side.

- If a **futures-options** edge candidate emerges from chain analysis (e.g. a persistent term-structure or strike-density pattern worth pricing), flag it — it is exactly the case that would justify the paid bars subscription. Until then: no purchase.


## Next steps

- Re-run `options_plan.py` weekly (after `options_chains.py` refreshes) to track expiry-ladder and ATM-coverage drift.

- No options edge → no subscription. This file is the standing evidence for that decision.
