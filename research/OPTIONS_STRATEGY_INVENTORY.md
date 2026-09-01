# Options Strategy Inventory & Research Library (scaffold)

Standing question: **Under what conditional information set does this option's payoff exceed its purchase price + execution costs?** (Not "do option buyers lose.")

## Strategy database (columns: outlook / vol / theta / L2-executable / single-option expressible / evidence status)

| strategy | outlook | vol | theta | L2 ($700) | single-option? | evidence |
|---|---|---|---|---|---|---|
| long call | bull | long | − | ✅ | ✅ | unconditional −EV (VRP) |
| long put | bear | long | − | ✅ | ✅ | unconditional −EV |
| bull call spread | bull | mixed | − | ❌ L3 | ✅ (debit) | untested |
| bear put spread | bear | mixed | − | ❌ L3 | ✅ (debit) | untested |
| bull put spread | bull | short | + | ❌ L3 | ❌ (credit) | VRP seller side |
| bear call spread | bear | short | + | ❌ L3 | ❌ (credit) | VRP seller side |
| long straddle | big move | long | − | ❌ L3 | ❌ (2 legs) | −EV unconditional |
| long strangle | big move | long | − | ❌ L3 | ❌ (2 legs) | −EV unconditional |
| iron condor | neutral | short | + | ❌ L3 | ❌ | VRP seller |
| calendar | neutral | mixed | mixed | ❌ L3 | ❌ | untested |
| diagonal | bias | mixed | mixed | ❌ L3 | ❌ | untested |
| butterfly | target | mixed | mixed | ❌ L3 | ❌ | untested |
| covered call | mild bull | short | + | ❌ (100 sh) | ❌ | VRP seller |
| protective put | hedge | long | − | ❌ (100 sh) | ✅ (put leg) | hedge, −EV |
| put-call parity arb | arb | 0 | 0 | ❌ | ❌ | needs shorting |

## NEW research priorities (mechanisms not yet tested — these are FEEDBACK/CONDITIONAL, not price/vol prediction)

1. **Dealer gamma regime** — options positioning → dealer hedging → underlying flow → price. Gamma-regime *changes* (not level) as a breakout signal.
2. **IV skew changes** — put/call skew transitions → future direction/vol.
3. **IV term-structure transitions** — front/back IV dislocation → realized-vol change.
4. **Vol-of-vol** — changes in vol-of-vol → future option returns.
5. **Gamma/theta convexity** — contracts where expected gamma payoff unusually large vs theta.
6. **Expiration/0DTE microstructure** — OpEx, gamma effects, post-expiration behavior.
7. **Retail-demand distortions** — contrarian filter on extreme retail OTM-call demand.
8. **Lottery avoidance** — filter out lottery-like underlyings (improve long-option expectancy).

## Library sources (to mine incrementally)
- OIC strategy quick-guide + full library + white papers + market data
- Cboe Options Institute (strategy courses, 0DTE, volatility, research library)
- Figlewski (NYU) — options/volatility teaching PDFs
- MIT OCW (Finance Theory, Investments — equity options pricing + empirical evidence)
- Damodaran (NYU) — option pricing, arbitrage, put-call parity, datasets
- Books: Hull, McMillan, Natenberg, Passarelli (via Open Library / lending)

## Research standard (10 stages — no skipping)
mechanism → published evidence → replication → OOS → 2023-26 modern → transaction costs → bid/ask → realistic option P&L → $700 simulation → paper trading.
