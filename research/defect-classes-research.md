# Un-fixed Defect Classes — Automated Retail-Broker Trading System

Scope: defect classes the operator has **not** already documented/fixed (their
`live-execution-integrity` skill already covers: empty order id/state, stop
modeled as `type='market'`+`stop_price`+`confirmed`, `average_price=None`,
unreliable `previous_close`, fractional=market-only + whole-share stops, resting
stop reserves shares, 95% dollar-sell cap, double-sell idempotency, orphan
sweeps, RTH-only stops, stale archives, live-size-off-paper-capital, etc.).
These are deliberately excluded here.

Profile assumed: **$700 fractional, long-only, ~5–10 positions, intraday, retail
(Robinhood-class) API + REST live quotes.**

---

## 1. API reliability — read-after-write / eventual consistency (double-submit)

- **Failure mode:** a place-order POST succeeds at the broker, but an immediate
  `GET /orders` or `GET /positions` returns a snapshot that does not yet reflect
  it (or reflects it with a stale/absent state). The bot concludes "the order
  didn't happen" and either (a) re-submits → **double fill**, or (b) fails
  "closed" and later discovers a position it never booked.
- **Symptom:** order present in broker history/executions but absent from the
  first poll; two fills for one signal; P&L/log says "no order" while a position
  exists.
- **Mitigation:** attach a client-supplied **idempotency key** to every order
  submit and reuse it verbatim across retries so the broker dedupes re-submits;
  treat a read-after-write staleness window as a *normal* state to poll through,
  never as a signal to re-submit; make the streaming fill/execution channel (not
  a REST snapshot) the source of truth for "did it fill."
- **Source:** Stripe — *Idempotent requests* (https://stripe.com/docs/api/idempotent_requests);
  AWS Builders' Library — *Making retries safe with idempotent APIs*
  (https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/).
- **Relevance:** the operator's entry path solved the *creation-response* gap but
  idempotency keys are only implemented on the sell-monitor; a general
  entry-side key is the standard defense against the re-submit double-fill.

## 2. API reliability — rate limits / 429 (ambiguous dropped orders)

- **Failure mode:** a burst of universe-wide reads (quotes, positions, orders)
  or rapid entry placement trips the broker's rate limit. A **429 on an order
  POST is ambiguous** — the request may or may not have been accepted — and a
  naive retry can either duplicate the order or worsen the throttle.
- **Symptom:** HTTP 429/`Too many requests` in logs at open; some symbols'
  quotes silently skipped; an entry order that "failed" but later filled.
- **Mitigation:** honor `Retry-After`; use exponential backoff **with jitter**
  and a client-side token bucket/pacing gate; never blindly retry a POST without
  an idempotency key; separate reads from order-submit paths so a quote burst
  cannot starve the execution lane.
- **Source:** AWS Builders' Library — *Timeouts, retries, and backoff with
  jitter* (https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/);
  Alpaca — *Rate Limits* (https://docs.alpaca.markets/docs/rate-limits).

## 3. API reliability — WebSocket vs REST divergence / silent stream gap

- **Failure mode:** live data arrives on a streaming/WebSocket channel while
  other logic reads REST snapshots; the two diverge (stream is real-time, REST
  is delayed/batched), or the stream drops silently and the bot keeps trading on
  a **stale last-tick** with no error.
- **Symptom:** quote frozen at an old price for many seconds/minutes with no
  exception; REST-vs-stream price disagreement; an entry sized/triggered off a
  quote that no longer matches the market.
- **Mitigation:** stamp every quote with a receive timestamp and refuse to act
  when it exceeds a freshness threshold (STALE_MAX_S); heartbeat + reconnect with
  gap detection on the socket; define ONE authoritative price source per
  decision and reconcile the others against it.
- **Source:** Alpaca — *About Market Data API* (stream vs REST, real-time vs
  delayed, WebSocket) (https://docs.alpaca.markets/docs/about-market-data-api).
- **Relevance:** the intraday monitor and sell-monitor poll live quotes; a
  silent stream/poll gap converts a stale quote into a wrong exit decision.

## 4. Order lifecycle — partial fills

- **Failure mode:** a market (or fractional dollar) order partially fills; the
  code treats any state other than `filled` as failure and either cancels the
  remainder or books a **full-size** position/stop against a partial quantity.
- **Symptom:** order status `partially_filled`; `filled_qty < intended qty`;
  stop sized for 7 shares placed on a 3-share fill (over/under-protection);
  leftover quantity quietly rests or is cancelled.
- **Mitigation:** track `filled_qty` / `cumulative_quantity` (not just status);
  poll to a terminal state; place the protective stop on the **actual filled
  quantity**; explicitly cancel any remainder and verify; write the book from
  real filled qty, not intended qty.
- **Source:** Alpaca — *Working with /orders* (order lifecycle, statuses incl.
  `partially_filled`, replace/cancel)
  (https://docs.alpaca.markets/docs/working-with-orders).
- **Relevance:** fractional dollar buys in illiquid sub-$50 names are exactly
  where partial fills happen; the operator's fill-confirm logic assumes
  all-or-nothing.

## 5. Order lifecycle — cancel/replace intermediate states (double-order or naked window)

- **Failure mode:** tightening/moving a stop is "cancel old + place new," two
  non-atomic REST calls. Between them the position is **naked**; if the new
  order is placed *before* the cancel completes it may be **rejected**
  (shares still reserved) or, worse, both orders can briefly live → double
  exposure. The cancel itself can land on an order already locked in-flight
  (`pending_cancel`/`pending_replace` intermediate states).
- **Symptom:** order stuck in `pending_cancel`/`pending_replace`; a replace
  rejected with "insufficient shares" / "duplicate order"; two resting stops for
  one symbol; a window where `is_stop_resting()` is False.
- **Mitigation:** prefer the broker's **atomic replace/modify** endpoint where
  available; otherwise cancel → poll to confirm cancelled → then place, and
  treat `pending_cancel` as "still live, do not place"; re-arm on any failure;
  assert at most one protective order per side before and after.
- **Source:** Alpaca — *Working with /orders* (Replace semantics + intermediate
  statuses) (https://docs.alpaca.markets/docs/working-with-orders).

## 6. Order lifecycle — execution price vs quote (slippage / price improvement)

- **Failure mode:** the bot sizes and books P&L off a quote or the order's
  limit, but the **actual fill price** differs (market orders slip; limit orders
  may get *price improvement*). The recorded entry/exit price is wrong, so
  stop distances and P&L are computed against a phantom price.
- **Symptom:** realized P&L disagrees with broker statement; a sell filled above
  the bid read as "anomaly"; entry_price that is neither the limit nor the last
  quote.
- **Mitigation:** read the **execution/fill price** from the fill report
  (executions[]), never from the order's limit or the sizing quote; measure
  implementation shortfall (fill vs arrival quote) and log it; account for
  price improvement when projecting fills.
- **Source:** Investor.gov glossary — *Best Execution* (duty of best execution &
  price improvement) (https://www.investor.gov/introduction-investing/investing-basics/glossary/best-execution).
- **Relevance:** at $700 with ~$70–140 notional orders, even a 1–2¢ slip is a
  large fraction of the edge; P&L must key on real fills.

## 7. Order lifecycle — clock skew between client and venue

- **Failure mode:** session gates (`in RTH?`, "market open/closed") and
  time-in-force decisions are computed from the **local VPS clock**. If it
  drifts (no NTP, or a VM clock step), the bot places orders in the wrong
  session, misfires `DAY`-vs-`GTC` logic, or trades a halted/pre-open market.
- **Symptom:** orders rejected as "outside trading hours" during RTH; a "day"
  stop silently expiring at the venue's close while the bot thinks it rests;
  entry fired at 09:29:59 vs 09:32.
- **Mitigation:** run `chrony`/NTP with continuous sync; use the **venue's
  market clock** (broker `is_open` / `next_open` / `next_close` timestamps) for
  session and TIF decisions rather than a local wall-clock; log the clock offset
  when detected.
- **Source:** chrony project (NTP time sync) (https://chrony-project.org/).
- **Relevance:** the operator's session logic uses `zoneinfo` on local time; a
  drifted VPS clock would corrupt every `_in_rth()` gate and the tradability
  filter.

## 8. Monitoring — no external dead-man's switch (silence ≠ success)

- **Failure mode:** local watchdogs (systemd `WatchdogSec`, the bot's own
  heartbeat) die **with the host** or with the scheduler. A whole-VPS outage, a
  crashed cron/systemd/Hermes-gateway, or a network partition produces **silence
  — no error, no alert** — and silence is misread as "ran flat, all healthy."
  A related variant: the heartbeat is emitted from a *background thread*, so a
  deadlocked main trading loop still reports healthy (liveness ≠ safety).
- **Symptom:** no reports/alerts for hours/days with no error anywhere; last
  dashboard state still shows "healthy"; positions silently unmanaged.
- **Mitigation:** an **external/second-party watchdog** (separate host or a
  ping-out service) that alarms on the *absence* of the bot's heartbeat within a
  window; ping from the **critical path** only (not a helper thread); alert on
  "no heartbeat" independently of any in-band success signal.
- **Source:** Google SRE Book — *Monitoring Distributed Systems* (alerting on
  absence of signal; monitor-the-monitor)
  (https://sre.google/sre-book/monitoring-distributed-systems/).

## 9. Market data — split / dividend adjustment mismatches

- **Failure mode:** a split or dividend changes the price series (or the
  position itself); indicators computed on **unadjusted** data fire false
  signals, or a stop/entry anchor sits at a pre-split price. Fractional holders
  receive fractional dividends / split-adjusted shares the bot may not book.
- **Symptom:** a one-day −50%/−25% "crash" in the bars that is really a 2:1
  split; stop price that is nonsense post-split; position qty changed with no
  corresponding bot action.
- **Mitigation:** compute indicators on **split/dividend-adjusted** data but
  execute and book at **raw** prices; subscribe to a corporate-actions feed and
  re-derive entry/stop/qty on the ex-date; detect "sudden large gap" as a
  corporate-action trigger, not a signal.
- **Source:** Alpaca — *Corporate Actions* (splits, dividends)
  (https://docs.alpaca.markets/docs/corporate-actions).

## 10. Market data — symbol changes / ticker mapping + delisting/merger liquidation

- **Failure mode:** a name is renamed (ticker change), merges, or is acquired;
  the universe file keeps the stale symbol → API returns no data (or the wrong
  security), or a held position is **force-liquidated / converted to cash**
  without a bot decision, leaving a phantom book row or a stop on a dead ticker.
- **Symptom:** persistent "no data"/null for one symbol while peers work; a
  position's qty suddenly 0 with an unexplained cash credit; an order rejected
  for "unknown symbol"; a stop resting on a delisted ticker.
- **Mitigation:** resolve symbols to a stable identifier (CUSIP/FIGI) and
  refresh the mapping daily from a corporate-actions feed; treat "no data +
  formerly valid" as a symbol-change/de-listing event to investigate, not as a
  flat/quiet symbol; exit or convert before the effective date.
- **Source:** Alpaca — *Corporate Actions* (symbol change, merger, acquisition,
  de-listing events) (https://docs.alpaca.markets/docs/corporate-actions).

## 11. Market data — trading halts / LULD / market-wide circuit breakers

- **Failure mode:** a stock enters a regulatory/news halt or a Limit Up-Limit
  Down (LULD) band, or the whole market trips a circuit breaker. Quotes freeze,
  orders can't fill, and a market/stop order either rejects or fills at a wild
  price on resumption (gap).
- **Symptom:** quotes frozen during a halt; order `queued`/`rejected` with a
  halt reason; a stop that "should have" filled did not, then the position gapped
  far past it at resumption.
- **Mitigation:** surface halt status (from the market-data stream/status
  endpoint) and **stand down** from halted names; never enter a name under an
  active halt; treat resumption after a halt as a gap event for stop
  expectations; be aware LULD pauses individual names ~5 min and market-wide
  breakers halt everything at threshold moves.
- **Source:** Investor.gov glossary — *Trading Halts*
  (https://www.investor.gov/introduction-investing/investing-basics/glossary/trading-halts)
  and *Circuit Breakers*
  (https://www.investor.gov/introduction-investing/investing-basics/glossary/circuit-breakers).

## 12. Accounting — T+1 settlement / unsettled funds → good-faith violation / free-riding

- **Failure mode:** on a **cash** account, proceeds from a sale are unsettled
  until **T+1** (settlement date). Buying with unsettled proceeds and then
  selling that purchase *before* the original proceeds settle is a **good-faith
  violation** (GFV) or free-riding; the broker restricts the account (typically
  90 days limited to settled-cash trading).
- **Symptom:** intraday round-trips on a cash account; broker warns of GFV /
  free-ride; account flipped to "settled funds only"; a buy rejected for
  insufficient *settled* cash despite positive equity.
- **Mitigation:** size and gate on **settled** buying power, not total equity;
  read the broker's `buying_power`/`cash`/`settled` fields rather than computing
  them; don't sell a position bought with unsettled funds before the funding
  trade settles; hold overnight to avoid intraday round-trips on a cash account.
- **Source:** SEC — *T+1 settlement cycle final rule*, press release 2023-29
  (https://www.sec.gov/news/press-release/2023-29); Robinhood — *Settlement and
  buying power* (https://robinhood.com/us/en/support/articles/settlement-and-buying-power/)
  and *Day-trade calls / GFV*
  (https://robinhood.com/us/en/support/articles/day-trade-calls/).
- **Relevance:** highest-priority item for a **$700 intraday** account — a few
  same-day round-trips can lock the account out of buying for 90 days.

## 13. Accounting — Pattern Day Trader (PDT) flag

- **Failure mode:** 4+ **day trades** in a rolling 5-business-day window flags
  the account as a Pattern Day Trader; with equity < **$25,000** the account is
  restricted from further day trading (typically a 90-day close-out/equity
  requirement).
- **Symptom:** broker surfaces a PDT warning / day-trade counter; an intraday
  entry rejected with a PDT message; the strategy's intraday in-and-out cadence
  trips the counter without the bot tracking it.
- **Mitigation:** count day trades in the bot (rolling 5-day window) and stop at
  the threshold (≤3); read the broker's own day-trade counter as ground truth;
  for a sub-$25k account prefer holding overnight (the operator's model already
  holds ~2–5 days) and gate any true intraday exit.
- **Source:** FINRA — *Frequent Intraday Trading: Understanding the Basics*
  (https://www.finra.org/investors/learn-to-invest/advanced-investing/day-trading-margin-requirements-know-rules);
  Robinhood — *Pattern day trade protection*
  (https://robinhood.com/us/en/support/articles/pattern-day-trade-protection/).
- **Relevance:** a $700 account is far under $25k, so PDT is a hard
  account-lockout risk for any intraday exit path.

## 14. Accounting — wash-sale tax lots (P&L vs tax P&L divergence)

- **Failure mode:** the strategy realizes a loss and repurchases the same (or
  substantially identical) security within 30 days (before/after) → the loss is
  **disallowed** and rolled into the replacement shares' cost basis. A P&L
  dashboard that reports realized losses naively **overstates** tax-recognized
  losses, and automated tax-lot selection picks the wrong lot.
- **Symptom:** strategy books a realized loss that the 1099 later disallows;
  cost basis on a repurchased lot is higher than the actual fill; year-end
  tax-reconciliation diverges from the trading ledger.
- **Mitigation:** track **tax lots** (not just average cost) and identify wash
  sales (defer disallowed loss, adjust the replacement lot's basis); report
  P&L as *economic* vs *tax* separately; prefer specific-lot or documented
  default lot selection.
- **Source:** IRS — *Publication 550, Investment Income and Expenses* (wash
  sales) (https://www.irs.gov/publications/p550).

## 15. Accounting — cash-vs-margin buying power / maintenance margin

- **Failure mode:** the bot sizes off a broker field that *includes margin or
  unsettled funds* (e.g. "day-trading buying power" or total "buying power") and
  thus over-deploys; or the account is margin and a drawdown triggers a
  **maintenance margin call / forced liquidation** at the worst time.
- **Symptom:** positions sum to >100% of actual cash; a margin-call notification;
  broker force-sells a position mid-hold; "buying power" ≠ available cash and
  nobody noticed which field was read.
- **Mitigation:** define an explicit funding basis (settled cash vs margin) and
  read the **specific** field that implements it (`cash`, `settled_cash`,
  `buying_power`, `maintenance_margin`); size so the max concurrent loss cannot
  breach maintenance margin; alert when margin-available approaches the
  deployed amount.
- **Source:** FINRA — *Purchasing on Margin*
  (https://www.finra.org/investors/learn-to-invest/advanced-investing/purchasing-margin);
  Robinhood — *Settlement and buying power*
  (https://robinhood.com/us/en/support/articles/settlement-and-buying-power/).
- **Relevance:** the operator already found "size off paper capital" and "count
  the broker not the book"; reading the *wrong buying-power field* is the
  un-fixed cousin that silently over-levers a small account.

---

### Priority for this account ($700 fractional, long-only, 5–10 positions, intraday)

1. **#12 T+1 / GFV** and **#13 PDT** — account-lockout risks, highest impact.
2. **#4 partial fills**, **#1 idempotency/double-submit**, **#2 rate limits** —
   correctness of every entry on a small account.
3. **#8 dead-man's switch**, **#3 stale-quote gate** — silent failures that
   erase all the above fixes.
4. **#9/#10/#11 corporate actions & halts** — per-name data integrity.
5. **#14/#15 wash-sale & margin** — year-end accounting and over-leverage.

Sources marked 200 above were fetched and title-verified during research;
`sec.gov` URLs are real (press release 2023-29 archived 2023-02-15) but
rate-limit direct fetches with a 403.
