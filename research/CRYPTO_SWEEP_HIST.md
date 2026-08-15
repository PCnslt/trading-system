# Crypto Edge Sweep — momentum + mean-reversion (PAPER/RESEARCH ONLY)

> Generated 2026-08-15T00:59:39.869870+00:00 · Binance.US daily candles (S3 `crypto-hist/`). Owner **distrusts crypto** — nothing here is live; survivors are paper-signal candidates only.

## Method (honest fills + never-lose-money)

- **Fee:** 10.0 bps/side (Binance.US standard spot 0.1% maker/taker, verified 2026-08-15).

- **Slippage stress:** 0, 10, 20 bps/side.

- **Stop:** 2×ATR14 hard protective stop on EVERY position (gap-aware intraday fill). No unprotected position.

- **Walk-forward:** 40/20/40 by entry date; OOS = last 40%.


## Promote / shelve / reject

| Symbol | Strategy | n | PF | Win | MaxDD | OOS PF (n) | PF@20bps | Verdict |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | momentum_long | 94 | 1.17 | 46% | -32.1% | 1.01 (38) | 1.01 | **shelve** |
| BTCUSDT | momentum_short | 55 | 1.10 | 40% | -56.6% | 1.02 (22) | 0.97 | **reject** |
| BTCUSDT | meanrev_rsi2_long | 144 | 1.06 | 59% | -66.7% | 1.09 (58) | 0.90 | **reject** |
| ETHUSDT | momentum_long | 86 | 1.35 | 50% | -36.3% | 0.98 (35) | 1.22 | **reject** |
| ETHUSDT | momentum_short | 52 | 0.79 | 42% | -66.5% | 1.75 (21) | 0.71 | **reject** |
| ETHUSDT | meanrev_rsi2_long | 139 | 1.21 | 63% | -49.4% | 1.06 (56) | 1.07 | **shelve** |
| SOLUSDT | momentum_long | 66 | 2.30 | 56% | -45.3% | 1.88 (27) | 2.13 | **shelve** |
| SOLUSDT | momentum_short | 55 | 1.07 | 51% | -73.2% | 0.63 (22) | 0.99 | **reject** |
| SOLUSDT | meanrev_rsi2_long | 119 | 0.90 | 54% | -72.2% | 1.40 (48) | 0.80 | **reject** |
| XRPUSDT | momentum_long | 35 | 3.23 | 49% | -22.6% | 3.47 (14) | 2.96 | **shelve** |
| XRPUSDT | momentum_short | 37 | 0.83 | 43% | -59.7% | 1.44 (15) | 0.72 | **reject** |
| XRPUSDT | meanrev_rsi2_long | 92 | 0.68 | 51% | -72.8% | 1.03 (37) | 0.58 | **reject** |
| LTCUSDT | momentum_long | 69 | 0.97 | 41% | -59.3% | 0.57 (28) | 0.88 | **reject** |
| LTCUSDT | momentum_short | 55 | 0.89 | 44% | -48.8% | 1.01 (22) | 0.79 | **reject** |
| LTCUSDT | meanrev_rsi2_long | 141 | 1.04 | 60% | -85.5% | 1.56 (57) | 0.93 | **reject** |
| ADAUSDT | momentum_long | 71 | 1.57 | 51% | -53.6% | 1.82 (29) | 1.45 | **shelve** |
| ADAUSDT | momentum_short | 68 | 0.81 | 46% | -63.8% | 0.88 (28) | 0.72 | **reject** |
| ADAUSDT | meanrev_rsi2_long | 157 | 1.01 | 54% | -76.0% | 1.03 (63) | 0.91 | **reject** |

## Promotion bar (owner spec, adapted to crypto bps)

- **PROMOTE:** full PF>1.5 AND OOS PF>1.3 AND PF@20bps≥1.0 AND OOS n≥30.

- **reject:** OOS PF<1.0 OR PF@10bps<1.0 OR full PF≤1.0.

- **shelve:** everything in between (optionality preserved, not deleted).


## Next step

- Survivors (if any) → `research/crypto_paper.py` logs paper signals to DynamoDB (`SIGNAL#CRYPTO_*`), **no orders, no cron** until the owner re-engages crypto.
