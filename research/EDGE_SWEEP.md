# Futures Edge Sweep (Lane A) — Energy / Metals / Ags / FX

Date: 2026-08-15 · Source: yfinance continuous (PRIMARY, 2010→2026, ~16y) × IBKR
futures-bars (CONFIRMATION, ~1.5–5y). Research-only; no orders.

## Scope

Swept **momentum** (Donchian 20d breakout both directions, 2·ATR GTC stop; TSMOM =
sign of 12m return, monthly rebalance), **mean-reversion** (RSI(2) long/short,
Bollinger(20,2σ) long/short), **carry** (cross-sectional monthly: rank by 12m
return, long low-momentum third / short high-momentum third — a term-structure
**proxy**, see caveats), and **seasonal** (expanding month-of-year return, long if
historically positive else short, hold the full month).

Universe: energy CL NG RB HO · metals GC SI HG PL PA · ags ZC ZW ZS ZM ZL ZO HE LE ·
FX 6E 6B 6A 6C 6S (+6M, present in both sources). Index/rates intentionally skipped
(covered in `validate_edges.py`).

Fill model (Gate-1 honest fills): entry at signal-bar **close + adverse slippage**;
stop-based strategies use **intraday-GTC** stops (gap-through → open fill, else
stop fill, +slip); close/time exits fill at close +slip; one entry/exit per bar.
Cost model: fee 1.3 bps round-trip of notional (0 bps as ideal ref) × slippage
0/1/2/3 ticks per side. OOS = last 40% of trades by entry date.

## Per-family summary

Pooled across all symbols & sub-strategies, yfinance slip=1 @ 1.3bp (raw $, 1 contract
each — see caveat #7 on contract-size mixing). OOS = last 40% by entry.

| Family | Full PF | Winrate | MaxDD ($) | Net ($) | OOS PF | OOS n | PF @ slip 0→3 | Verdict |
|---|---|---|---|---|---|---|---|---|
| Momentum (Donchian + TSMOM) | 0.97 | 48% | −859k | −433k | 0.97 | 4452 | 0.98 → 0.94 | **KILL** |
| Mean-reversion (RSI2 + BBand) | 0.99 | 57% | −418k | −163k | 1.02 | 6310 | 1.01 → 0.94 | **HOLD** |
| Carry (cross-sectional proxy) | 1.01 | 51% | −664k | +18k | 0.85 | 80 | 1.03 → 0.97 | **KILL** |
| Seasonal (month-of-year) | 1.18 | 52% | −162k | **+934k** | 1.19 | 1840 | 1.19 → 1.16 | **HOLD** ⭐ |

Seasonal, **commodities only** (energy+metals+ags, FX excluded): full PF **1.20**,
OOS PF **1.23** (n=1360) — FX dilutes the effect (6M 0.80, 6E 0.97, 6A 0.80).

Fee sensitivity is minor everywhere (0 vs 1.3bp moves PF < 0.02); **slippage is the
binding cost**, and low-frequency strategies (seasonal, monthly TSMOM) are nearly
slippage-immune (see top-candidate grid below).

## Verdicts

| Family | Verdict | Why |
|---|---|---|
| Momentum | **KILL** (family) | Pooled PF 0.97 / OOS 0.97, net **negative**. Only gold survives — promoted separately. |
| Mean-reversion | **HOLD** | Breakeven overall (0.99/1.02). Real pockets (BBand/RSI2 on CL·PL·SI·LE·ZO·ZM) but thin OOS n (30–50) and ~40% cross-source flips. |
| Carry | **KILL** | OOS PF 0.85 < 1.0, net → negative at ≥2 ticks, ret/DD ≈ 0.03. Proxy only (no term structure in S3). |
| Seasonal | **HOLD** (→ promote pending confirmation) | Best family: 1.18/1.19 (commodity-only 1.20/1.23), cost-stable through 3 ticks, n large. **Cannot be cross-validated on ~3y IBKR bars** (needs ≥5y warmup). |

Promote/kill bar used (repo standard): promote = OOS PF ≥ 1.2 **and** 2-tick PF ≥ 1.0
**and** OOS n ≥ 30 **and** cross-source direction agreement; kill = OOS PF < 1.0 or
1-tick PF < 1.0 or OOS n < 30; else hold.

## Top candidates (cross-source AGREE, OOS PF > 1.2, survives 3 ticks)

PF = full-sample @ 1-tick slip; IB = IBKR ~3y confirmation PF (n). "AGREE" = same
direction on both sources.

| Strategy | Sym | PF | OOS PF (n) | IB PF (n) | 3-tick PF | Notes |
|---|---|---|---|---|---|---|
| Donchian long/short | **GC** gold | 1.45 | 1.81 (114) | 1.31 (105) | 1.42 | intraday-GTC stop 1.45 **vs** close-stop 1.23 |
| TSMOM | **GC** gold | 1.37 | 1.73 (79) | 1.99 (48) | 1.35 | only momentum sig that agrees on both sources |
| BBand long | **CL** crude | 1.52 | 2.69 (39) | 2.16 (31) | 1.48 | strong but OOS n=39 |
| BBand short | **PL** platinum | 1.60 | 2.11 (47) | 3.01 (21) | 1.57 | IB thin (21) |
| BBand short | **SI** silver | 1.58 | 2.14 (51) | 2.62 (22) | 1.53 | IB thin (22) |
| RSI2 short | **ZM** soybean meal | 1.51 | 1.63 (97) | 1.64 (39) | 1.40 | best n in mean-rev |
| RSI2 short | **PL** platinum | 1.29 | 1.75 (101) | 1.57 (46) | 1.25 | solid n both sides |
| BBand long | **LE** cattle | 1.52 | 2.62 (31) | 3.01 (13) | 1.44 | IB very thin (13) |
| TSMOM | **HG** copper | 1.10 | 1.31 (79) | 1.25 (47) | 1.07 | moderate |
| Seasonal (no IB confirm) | HE·GC·PL·ZC·ZS | 1.6–2.1 | 1.6–2.5 | — | 1.5–2.1 | best family but unconfirmable |

**Single strongest, best-confirmed edge: gold momentum (GC, Donchian + TSMOM).**
Both sub-strategies independently survive full-sample, OOS, and the ~3y IBKR
confirmation on the same (long) direction, and hold PF ≥ 1.35 at 3-tick slippage.

## Honest caveats

1. **Direction disagreement is common and regime-dependent.** Donchian momentum flips
   sign on IBKR for CL (yf 1.28 long vs IB 0.82 short), NG (0.85 vs 1.55), RB, SI, ZL,
   ZS — 6/18 symbols disagree (Donchian) and ~4/18 for TSMOM. The 2021–26 IBKR window
   is a different (post-COVID, high-vol) regime than 2010–26; a "16y edge" that flips on
   the recent 5y is not robust. Gold is the lone exception (sustained bull in both
   windows).
2. **Seasonal is the best family but structurally unconfirmable here.** Its expanding
   signal needs ≥5y of same-month history; the ~3y IBKR bars fire **0 trades** at
   min_years=5. A forced min_years=2 read is directionally positive for GC/ZC/HE/ZS/CL
   but thin (n=3–36) and negative for PL/SI/HG — not a valid confirmation. Promote only
   after a second long-history source (or >5y of IBKR bars).
3. **Carry is a proxy, not true carry.** True term-structure/roll yield needs two
   contracts per market; only a single continuous series is in S3, so I used 12m-return
   rank (a momentum-inverse). It fails OOS anyway → KILL, and genuine carry remains
   untested.
4. **FX is thin and only half-confirmable.** 6E/6B/6A/6C/6S have no IBKR bars in S3
   (yfinance only). The single IBKR FX symbol is 6M (~15 months, n=3–25 trades), which
   is a *different* pair, so FX "direction agreement" is not a clean test. FX showed no
   family-level edge (all sub-strategies pooled ≈ 0.8–1.0).
5. **Close-to-close vs intraday-GTC stop**: for Donchian the intraday-GTC model is the
   *higher* PF on GC/SI/PL (1.45 vs 1.23 on gold) — the usual "close-to-close overstates"
   is not universal for trend stops. Both are reported; intraday-GTC is the honest number.
6. **Mean-reversion pockets are thin.** BBand OOS n ≈ 30–50 even on 16y (signal is rare);
   several pass the bar but at n near the thin-sample floor — read PF **and** n.
7. **Raw-$ pooling mixes contract sizes** (CL $1000/pt vs GC $100/pt vs ZC $50/pt), so
   family pooled maxDD/net are dominated by large-mult contracts. Per-symbol PF is
   scale-invariant and is the more reliable read; use the per-symbol table.
8. **Notional-normalized risk was not modeled** — per-contract $ P&L ≠ equal-risk; a
   single CL contract risks far more than a ZC contract. Promoted candidates still need
   a position-sizing pass before paper.

## Bottom line

No blanket edge in momentum, mean-reversion, or carry at the family level — only
**gold momentum** (promote) and **commodity seasonality** (hold→promote pending a
second long-history confirmation) survive honest fills + cost stress + OOS. The rest
of the futures complex is, after 1.3bp fees and 1–2 ticks of slippage, statistically
flat or worse.
