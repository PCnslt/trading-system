# Edge Sweep 2 — New Strategy Families (Carry · XSMOM · Vol-Overlay · Value)

Date: 2026-08-16 · Operator: VPS Hermes (builder) · Research-only, **paper-only, no live**.
Data: S3 `trading-datalake-920641308584` — yfinance continuous futures (16y),
IBKR CONTFUT continuous (56 syms, ~5y), IBKR per-contract chains (current chain),
IBKR equities daily (5,792 US stocks landed, 20y). Nothing touched live; gateway
not restarted.

## TL;DR

| Family | Full PF | OOS PF | maxDD | Sharpe | 3-tick / honest cost | Verdict |
|---|---|---|---|---|---|---|
| 1. Carry / term-structure | 1.01 | 1.13 (n=24) | −37.8% | 0.01 | dies @ 1 tick (0.97) | **NO-GO** (proxy + data gap) |
| 2a. XSMOM futures | 0.94 | 0.90 (n=120) | −56.8% | −0.08 | dies @ 1 tick (0.91) | **NO-GO** |
| 2b. XSMOM equities (L/S) | 0.47 | 1.09 (n=92) | −215% | −0.22 | dies @ 0 cost | **NO-GO** (short leg) |
| 3. Vol-targeting overlay | — | — | — | mixed | n/a (overlay) | **NO-GO** as Sharpe lift · HOLD as de-risker |
| 4. Value / 5y reversal | 0.90 | 0.79 (n=102) | −53.7% | −0.14 | dies @ 1 tick (0.88) | **NO-GO** |

**None of the four families is promotable.** This is consistent with the prior
sweep (`EDGE_SWEEP.md`): the futures complex is statistically flat or worse after
1.3 bp fees + 1–2 ticks of slippage, and long-short cross-sectional strategies
are fragile in modern (post-2000) markets. The one genuinely positive read —
**long-only 12m cross-sectional momentum in US equities** (PF 1.80, Sharpe 0.78) —
is a side-finding, not the long-short construct that was requested.

---

## 1. Commodity Carry / Term-Structure — **NO-GO** (and structurally under-tested)

**What was asked:** monthly, rank energy+metals+ags+rates by roll return
`(near − far)/near`, long top 20% / short bottom 20%, equal-weight, 1-month hold.

**What the data actually allows (honest):** the only per-contract data in S3 is
the **current forward chain** (`ibkr/futures/daily/<sym>/<expiry>.parquet`),
backfilled to each contract's own history. Expired contracts are **Error 200**
("No security definition") on paper, so I cannot reconstruct a *rolling* near-vs-far
term-structure series over 1979–2004 (or any multi-decade window). What I *can*
compute is a **fixed-calendar-spread** roll return — the two contracts in the
current chain with the longest overlapping history (e.g. CL Aug26↔Sep26, both 5y).
For most of that window both contracts are **far-dated**, so this measures the
far forward-curve slope, which is a **weak proxy** for the near-far carry premium
(the premium lives at the front of the curve). This is NOT the Quantpedia
"Term Structure Effect" — that study needs historical near+far prices.

**Result (proxy, ~5y, 12 symbols — energy CL NG HO RB QM QG, metals GC HG SI,**
**ags ZL ZM, rates ZQ; ZC ZS ZW ZO PL PA HE LE ZB ZN ZF ZT dropped for <3y depth):**

| | PF | Sharpe | Ann | maxDD | Net |
|---|---|---|---|---|---|
| Gross (slip 0) | 1.01 | 0.01 | −1.7% | −37.8% | −8.0% |
| Slip 1 / 2 / 3 | 0.97 / 0.94 / 0.90 | — | — | — | — |
| Walk-forward 40/20/40 | train 0.60 / val 2.33 / **OOS 1.13 (n=24)** | | | | |

**Verdict: NO-GO.** The proxy shows no edge (PF ≈ 1.0, negative net, dies at
1-tick slippage, train-PF 0.60). Two independent carry proxies now both fail —
the prior sweep's 12m-return-rank proxy was KILLed at OOS 0.85, and this
fixed-spread proxy is flat-to-negative.

**Honest flag (do not hide):** this is a *data-gap* NO-GO, not a clean "carry is
dead" finding. True term-structure carry remains **untested** because the
historical near+far contract data does not exist here. To test it properly we
need one of: (a) a paid multi-decade futures term-structure archive (e.g. Pinnacle
Data / CSI / Bloomberg), or (b) an IBKR entitlement that resolves *expired*
contracts. **Action: do not promote; acquire term-structure data before revisiting.**

---

## 2. Cross-Sectional Momentum

### 2a. Futures — **NO-GO**

Rank by trailing 12m return (skip most recent month), long top quintile / short
bottom quintile, monthly rebalance.

| Universe | Syms | Window | Full PF | Sharpe | Ann | maxDD | Slip 0→3 | OOS PF (n) |
|---|---|---|---|---|---|---|---|---|
| yfinance continuous | 13 | 2000→2026 (26y) | 0.94 | −0.08 | −2.3% | −56.8% | 0.94→0.86 | **0.90 (120)** |
| IBKR continuous | 32 | 2021→2026 (5y) | 1.08 | 0.09 | +0.4% | −20.4% | 1.08→0.98 | 1.27 (18) |

**Verdict: NO-GO.** The deep 26y yfinance read is negative and dies at 1-tick. The
wider 5y IBKR read looks mildly positive but is **unusable**: 18 OOS months (thin)
and **train-PF 0.58** — the strategy *lost* money over its first 40%, then
recouped in the tail. Direction agreement fails. Consistent with the prior
time-series momentum KILL (pooled 0.97).

### 2b. US equities — **NO-GO for long-short** (long-only leg is real)

2,191 liquid names (median $vol > $1M, price > $5, ≥5y history), 2006→2026.

| Construct | PF | Sharpe | Ann | maxDD | Note |
|---|---|---|---|---|---|
| Long-short, mean (raw) | 0.47 | −0.22 | −100% | −215% | a few short-squeeze outliers wipe it |
| Long-short, median (robust) | 1.27 | 0.29 | +1.9% | −23.4% | **before any borrow/short cost** |
| **Long-only, mean** | **1.80** | **0.78** | **+14.4%** | −50.8% | **the real edge** |
| Walk-forward (L/S mean) | train 0.94 / val 0.13 / OOS 1.09 | | | | |

**Verdict: NO-GO for long-short cross-sectional momentum.** The short leg destroys
it: (a) the losers are low-price, hard-to-borrow names prone to violent squeezes
(mean PF 0.47 vs median 1.27 — tail-driven), and (b) **survivorship bias** — the
universe is the current-listing snapshot, so delisted losers (the short leg's best
candidates) are missing, which *flatters* nothing and actually biases the short leg
negative. Median long-short is +1.9%/yr before costs; real short-side borrow fees
on these names run well above that → **negative net**. Long-short momentum is a
well-documented post-2000 casualty (momentum crashes 2009/2016/2018/2020), and
this 2006–26 sample reproduces it.

**Side-finding worth flagging (not this task's ask):** *long-only* 12m
cross-sectional momentum is robust here — PF 1.80, Sharpe 0.78, ann +14.4%,
survives 40/20/40 (train 0.94 / OOS 1.09 on the L/S; the long leg alone is the
contributor). That's a real, if well-known, long-only equity edge — distinct from
the existing RSI2-dip (mean-reversion) champion — and could be a candidate for a
separate paper lane. Not promoted here because the request was the long-short
construct.

---

## 3. Volatility-Targeting Overlay — **NO-GO** as Sharpe lift · **HOLD** as de-risker

1/realized-vol (20d) position scaling applied to the existing Donchian + RSI2
edges, return-space comparison (scale-invariant). Target vols 10/20/30%.

| Sleeve | Base Sharpe | Overlay Sharpe (10/20/30%) | Base maxDD | Overlay maxDD @ 10% |
|---|---|---|---|---|
| ES Donchian | 0.31 | 0.25 / 0.26 / 0.29 | −29.8% | −20.3% |
| ES RSI2 | 0.63 | 0.73 / 0.72 / 0.73 | −27.2% | −17.0% |
| GC Donchian | 0.50 | 0.56 / 0.58 / 0.58 | −20.7% | −15.9% |
| GC RSI2 | 0.20 | 0.16 / 0.16 / 0.15 | −21.3% | −20.4% |

**Verdict: NO-GO as a Sharpe-improvement overlay** — it is not a uniform win.
Sharpe *improves* on ES-RSI2 (0.63→0.73) and GC-Donchian (0.50→0.58) but is flat
or *worse* on ES-Donchian and GC-RSI2. The mechanism is mechanical, not an edge:
- **Targeting *above* natural vol = leverage** → more return, more drawdown, no
  Sharpe gain (e.g. maxDD worsens to −41%…−54% at 30%).
- **Targeting *below* natural vol = de-risking** → meaningfully lower maxDD
  (RSI2 ES −27%→−17%, Donchian ES −30%→−20%, GC Donchian −21%→−16%) but at the
  cost of lower absolute return.

**Recommendation:** do not adopt as a Sharpe edge. It *is* a legitimate
risk-management dial — if the goal is maxDD reduction, run the promoted edges at a
**de-levered vol target (~10%)**; if the goal is return, it adds nothing over
sizing by hand. Keep as a tool, not a promotion.

---

## 4. Value / Long-Term Reversal (futures) — **NO-GO**

Value = spot vs rolling 5y mean, long cheap / short rich. 14 futures, 2000→2026
(5y warmup → ~21y usable).

| Construct | Full PF | Sharpe | Ann | maxDD | Slip 0→3 | OOS PF (n) |
|---|---|---|---|---|---|---|
| Cross-sectional (rank cheap/rich) | 0.90 | −0.14 | −2.7% | −53.7% | 0.90→0.83 | **0.79 (102)** |
| Time-series (per-symbol sign) | 0.83 | −0.25 | −3.0% | −63.0% | 0.82→0.73 | 0.99 (125) |

**Verdict: NO-GO.** Both the cross-sectional (Asness-Moskowitz-Pedersen style) and
time-series value constructions are negative net, die at 1-tick, and the
cross-sectional OOS is 0.79. Value in this 14-name futures universe does not pay —
consistent with the broader finding that the futures complex is flat after costs.
(The AMP value premium is documented on a much wider, longer cross-section than
14 commodities; not reproducible with the data on hand.)

---

## Promote bar used (repo standard)

- **promote**: OOS PF ≥ 1.2 **and** honest-cost (3-tick / net-of-cost) PF ≥ 1.0
  **and** OOS n ≥ 30 **and** Sharpe > 0.
- **kill**: OOS PF < 1.0 **or** dies at 1-tick (or net-of-cost) **or** OOS n < 30.
- **hold**: otherwise.

## Bottom line

All four new families are **NO-GO for paper promotion**:

- **Carry** — no edge in the proxy *and* the true term-structure premium is
  untested (missing historical near/far data). Data gap, not a clean kill.
- **Cross-sectional momentum (futures)** — negative on the deep 26y read; the 5y
  wide read is thin + train-negative. Dead.
- **Cross-sectional momentum (equities, long-short)** — the short leg destroys it
  (squeezes + survivorship + omitted borrow costs). Long-short momentum is a
  post-2000 casualty. (Long-only leg is real → separate flag.)
- **Vol overlay** — not a Sharpe edge; only useful as a de-levered risk dial.
- **Value / 5y reversal** — negative both constructions.

The actionable leftovers are: (1) acquire a real futures term-structure archive
before ever judging carry, and (2) consider *long-only* 12m equity momentum as its
own paper-signal lane (not part of this request). No changes to live trading; no
gateway restart.
