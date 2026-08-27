# Defect-Prevention Report: Robinhood Software Sell / Take-Profit Monitor

**Scope:** live ~$700 Robinhood account; fractional positions; no broker-side stop for
fractional shares; no bracket/OCO; no official API. The monitor polls quotes and submits
MARKET sell orders on take-profit (price ≥ target) or stop-loss (price ≤ threshold).

**Broker constraint worth stating up front:** Robinhood *“doesn’t currently support
bracket orders, Market-on-Close orders, or Market-on-Open orders,”* and the supported
types are market, limit, stop, stop-limit, and trailing-stop. [3] There is therefore no
broker-native take-profit/stop-loss pair to lean on — every exit is software-driven.

**Method:** every load-bearing claim below cites a URL that was actually fetched
(Aug 2026). Verbatim broker quotes are in “curly quotes.” Where a fact could not be
extracted from any fetched source, it is marked **NOT-EXTRACTED**.

---

## 1. FAILURE MODE → Double-selling / over-selling

**Failure:** the monitor restarts mid-order, a trigger fires twice, or a retry after a
network timeout is issued for a sell that actually filled — the position is sold twice
(or a second, unintended order is placed). On a ~$700 account a double sell can flip a
flat book into an unintended short-like over-exposure or at minimum sell a position the
operator still wanted.

**Broker reality (Robinhood):** the order-create path is async with no durable
broker-side idempotency, and the response can lack a stable order id/state. Robinhood's
own documentation confirms the share-reservation behavior you can exploit: a second sell
on the same shares is rejected while the first is pending — *“You may get a message
about ‘not enough shares’ if you already have an outstanding pending order for the
shares you want to sell with a new order. If you get this message, you’ll need to cancel
any outstanding orders before you can sell the shares.”* [13]

**Mitigations:**
- **Reconcile-before-act.** Before *any* sell, fetch the live position quantity *and*
  pending orders for the symbol from the broker. Only act if the position is open **and**
  no pending sell exists. This is the AWS pattern: *“the provisioning process has to
  perform a reconciliation to determine whether this workload is running or not”* — issued
  because *“Simply retrying the request could result in multiple workloads, which could
  have dire consequences.”* [18]
- **Client-side idempotency key per intent.** Generate a stable key per
  (position, trigger-instance), persist it durably *before* the network call, and never
  reuse it for a different intent. This mirrors Stripe's contract — *“The API supports
  idempotency for safely retrying requests without accidentally performing the same
  operation twice.”* [17] — and AWS's *“unique client request identifier”*
  (EC2 `ClientToken`) pattern. [18]
- **Durable journal/outbox.** Write `SELLING <symbol> <intent-id> <qty>` to an fsync'd
  append-only local journal *before* the sell call. On restart, replay the journal and
  reconcile each open entry against the broker before resuming. Never re-issue a sell
  merely because no broker order id was returned.
- **Cancel any duplicate pending sell as a recovery step.** Robinhood allows *“cancel any
  pending order”* [14]; if reconciliation ever surfaces a stale pending sell for a position
  that should be flat, cancel it rather than letting it fill.
- **Treat “not enough shares / insufficient” as success-of-sort.** This rejection means
  the shares are already reserved by another pending order — do **not** retry it; mark the
  intent as in-flight and reconcile. [13]
- **Close only on verified zero.** Transition to CLOSED only after the position is
  confirmed zero (see §2), never on “order submitted.”

**Sources:** [13][14][17][18]

---

## 2. FAILURE MODE → Partial fills and the 95% sell cap

**Failure:** a “sell everything” expressed in dollars leaves a residual because Robinhood
caps dollar-based sell *market* orders. Verbatim: *“If you place a dollar-based sell
market order, you may only sell up to 95% of your current position. We add the 5% buffer
in case of price fluctuation. You may convert to a share-based order to sell a specific
quantity or your entire position.”* [2] A dollar-based sell therefore cannot close the
position — a residual always remains unless you convert to shares.

**Mitigations:**
- **Sell by shares, not dollars, to close.** Read the exact current quantity (fractional
  positions round to the nearest penny and drift with dividends/reinvestments) and submit a
  **share-based** market sell for the full quantity — Robinhood explicitly permits a
  share-based order to sell *“your entire position.”* [2]
- **Verify-to-zero loop.** After a sell, poll order/position state until terminal. If
  residual > 0 (partial fill, or a cap leftover), issue one cleanup sell for the residual,
  bounded to N attempts; if the residual persists, **escalate to a human** rather than
  looping forever.
- **Expect dust.** Fractional shares are valued at ≥ $1 and rounded to the nearest penny,
  and dollar→share conversion uses the prevailing best price, so tiny residuals are normal.
  [1] Clean them up explicitly; do not assume zero.
- **Don't rely on the broker to clean delisting residuals.** Robinhood *may* cash out a
  fractional remainder on delisting — *“If a stock is delisted, Robinhood may sell any
  fractional portion of the OTC security”* [12] — but this is permissive, not guaranteed.

**Sources:** [2][1][12]

---

## 3. FAILURE MODE → Stale / erroneous quote triggering a false sell

**Failure:** a single bad print, a halted symbol, or a pre-market/extended-hours garbage
quote trips the stop and dumps a good position at a bad price. Robinhood itself notes the
displayed price is *“the last trade price on a Nasdaq exchange … which might not be the
best available price”* [2] and that extended-hours prices move *“much more than …
during regular market hours.”* [7] Trailing stops are documented to false-fire on noise —
*“short-term fluctuations in a stock’s price can trigger a trailing stop order”* [16] — and
the same noise sensitivity applies to any software price trigger.

**Mitigations:**
- **N consecutive confirming quotes.** Require 2–3 consecutive samples beyond the
  threshold (with sane max age) before triggering; a single tick never sells.
- **Sanity bounds vs reference.** Reject any quote that deviates more than X% from the
  last close / prior-session close / median of recent quotes as suspect; require it to be
  re-confirmed by subsequent quotes before acting.
- **Session gate.** Only fire market triggers during regular hours (see §7). Extended /
  pre-market / overnight quotes are thin and can be far from the true market. [7][2]
- **Halt / untradeable guard.** If the exchange has paused trading, do not submit a market
  sell — it will reject or queue. Robinhood lists *“The exchange has paused trading for
  it”* as a reason a security is untradeable [15], and the 24 Hour Market page describes
  Limit Up/Limit Down halts on exchanges and ATS price bands as the exchange-level
  controls that bound extreme moves. [8]
- **Use a consolidated/NBBO feed, not one venue's last print.** A single-venue bad print
  must not be able to trip the stop. Robinhood's own routing disclosure grounds this: the
  *“majority of our orders are filled at the National Best Bid and Offer (NBBO) or better,”*
  so NBBO is the correct reference frame for trigger decisions. [9]

**Sources:** [2][7][8][9][15][16]

---

## 4. FAILURE MODE → Sell failure handling (reject / no-fill)

**Failure:** the market sell is rejected (halt, insufficient shares, delisted symbol,
risk-check rejection, routing failure) or never fills; the monitor either gives up (no
protection) or retries forever (stuck, stale, and in a fast market it compounds the loss).

**Broker rejection/fill taxonomy (Robinhood):** rejections include *“Your order was routed
to a broker that can’t accept it … simply reenter the order,”* *“Your limit order is too
aggressive … risk checks,”* and *“if a stock undergoes a reverse split, we’re required to
cancel all open orders.”* [10] Non-fills include limited volume, market-open conditions
(NYSE opening auction can delay fills minutes after 9:30), and extended-hours illiquidity. [11]

**Mitigations:**
- **Classify errors** into *transient* (routing, throttle, timeout, temporary) vs
  *permanent* (insufficient shares = already sold/selling; delisted; halted; untradeable).
- **Transient → randomized exponential backoff + jitter.** SRE: *“Always use randomized
  exponential backoff when scheduling retries”* — jitter prevents synchronized retry
  storms. [20] AWS SDK *standard mode*: *“retries failed requests using exponential
  backoff with jitter.”* [19]
- **Bound retries — never retry forever.** SRE: *“Limit retries per request. Don’t retry a
  given request indefinitely … retry budget … if the retry budget is exceeded, don’t retry;
  just fail the request.”* [20] AWS SDK enforces this via a *retry quota* token bucket that
  *“fails fast instead of waiting through retries that are unlikely to succeed.”* [19]
- **Escalate to a human when:** the retry budget is exhausted; the rejection is permanent;
  the symbol is halted/delisted; or the position has moved further against the operator and
  a manual limit/close or support contact is needed. For delisted/OTC names there is *no
  NBBO* and you *“may be able to close your position”* but at unknown prices — human
  judgment required. [12]
- **On “not enough shares,” stop retrying** — that is the broker telling you the position
  is already being sold; reconcile instead (§1). [13]

**Sources:** [10][11][19][20][12][13]

---

## 5. FAILURE MODE → Process-death / watchdog (protection silently disappears)

**Failure:** the monitor process dies (OOM, exception, kill, host reboot) and the stop-loss
simply stops existing. A software stop that is not running is no stop at all.

**Mitigations:**
- **systemd `Restart=always`** so the service restarts whenever it exits, is killed, or
  times out. man page: *“Restart= Configures whether the service shall be restarted when
  the service process exits, is killed, or a timeout is reached … Takes one of no,
  on-success, on-failure, on-abnormal, on-watchdog, on-abort, or always.”* [21]
- **`RestartSec=` + `RestartSteps=`** for exponential restart backoff (avoid restart
  storms): *“RestartSteps= Configures the number of exponential steps … values between 3
  and 5 are good choices when exponential backoff is desired.”* [21]
- **`WatchdogSec=` + `sd_notify(WATCHDOG=1)`** to catch *hung* processes, not just dead
  ones: *“The watchdog is activated when the start-up is completed. The service must call
  sd_notify(3) regularly with ‘WATCHDOG=1’ … If the time between two such calls is larger
  than the configured time, then the service is placed in a failed state…”* [21]
- **Independent dead-man's-switch (mandatory, separate failure domain).** A second,
  independent mechanism (separate cron/systemd unit, ideally another machine or a
  cloud-hosted ping) checks that (a) the monitor is alive and (b) its heartbeat file is
  fresh. If not, it alerts the operator (email/push). Self-healing restarts are **not** a
  substitute for this: if the box/process is down, only an outside observer notices.
- **Persist state to disk** so a restart resumes cleanly (feeds §1 journal and §6 state
  machine) rather than re-deciding from scratch.

**Sources:** [21]

---

## 6. FAILURE MODE → Race conditions (position read while a sell is in flight)

**Failure:** the monitor reads a stale position list and sells a position that another lane
(or a broker stop, or its own earlier sell) already sold, or issues two concurrent sells.

**Mitigations:**
- **Single writer.** Exactly one process may submit sells. Enforce with a singleton lock /
  systemd single instance; if multiple lanes exist, they share one writer or serialize on a
  lock.
- **Per-position state machine: `OPEN → SELLING → VERIFYING → CLOSED`.** Never submit a
  sell for a position not in `OPEN`. Persist each transition durably (journal) before and
  after the network action.
- **Reconcile-before-act.** Re-read live broker state (position qty + pending orders) at
  every decision point; don't trust local cache. This is the AWS reconciliation pattern. [18]
- **Single-flight per symbol.** Don't issue two concurrent sells for the same symbol from
  within the monitor.
- **Idempotent no-op on stale triggers.** A trigger for a position already `SELLING`/
  `VERIFYING`/`CLOSED` is a no-op (AWS's *late arriving requests* concern: an old event
  must not re-open a closed action). [18]
- **Broker as backstop, not primary.** If a race slips through, Robinhood's share
  reservation rejects the second sell with “not enough shares” [13] — rely on the state
  machine as the primary control and treat the broker rejection as a backstop only.

**Sources:** [18][13]

---

## 7. FAILURE MODE → Market-hours edges (wrong order type per session)

**Failure:** the monitor submits a market sell outside regular hours expecting an immediate
fill. It does not get one — it gets queued to the next open, which silently reintroduces
the gap risk the stop was meant to bound.

**Broker facts:**
- Regular market hours: **9:30 AM–4 PM ET.** [7]
- *“Our venues don’t support market orders during extended-hours trading. If your market
  order is placed outside of regular market hours, the order will be queued for the start
  of regular market hours on the next trading day.”* [2]
- Order-type-per-session table: dollar-based **and** share-based sell orders default to
  **Market during market hours** and **Limit during extended hours** (OTC stays Limit in
  all sessions). [2]
- Extended hours: **7–9:30 AM and 4–8 PM ET** generally, but **fractional shares only
  7–9:30 AM and 4–7:30 PM ET.** [7]
- Overnight / 24 Hour Market: **whole-share, limit orders only.** [8]
- Stop/stop-limit/trailing triggers convert to a market order and execute **“during market
  hours only.”** [5]

**Mitigations:**
- **Session-aware order routing.** Regular hours (9:30–16:00 ET): market (or marketable
  limit) sell. Extended hours: limit order only (and for fractional, only inside 7–9:30 /
  4–7:30) — see the limit-order mechanics. [4] Overnight: whole-share limit only, or defer
  to next open.
- **Never fire a market sell outside regular hours expecting immediate execution** — it
  queues to next open. Either use a limit order for that session or explicitly stand down
  and resume at open (having pre-accepted the gap risk via sizing, §8). [2]
- **Gate triggers on the session clock** and confirm the symbol is actually trading (not
  halted, and past any delayed opening — NYSE opening auction can delay fills for minutes
  after 9:30). [11][15]
- **Note (NOT-EXTRACTED):** no fetched Robinhood page states whether stop / stop-limit /
  trailing orders accept *fractional* quantities; the docs describe share-based stops only.
  Do **not** design around fractional broker-side stops — verify in-app if it becomes
  load-bearing. [5][6][16]

**Sources:** [2][4][5][7][8][11][15]

---

## 8. FAILURE MODE → Gap-through reality (stop can't catch an overnight gap)

**Failure:** a software stop is only as fast as the market is open. An overnight gap opens
below the threshold and the fill happens at the open, not at the stop price. The broker's
own stop-order docs admit this: *“when the stop price is triggered, at market open or
during periods of market volatility, the trade may execute at a price far away from the
stop price”* and *“The stop price does not guarantee execution price.”* [5] For a delisted
name there is *no NBBO* and you may only be able to close at an unknown OTC price. [12]

**Operator's measured worst cases:** sub-$50 overnight gap p1 ≈ −21% (after a −5% day);
worst delisting gaps −72% to −99%. At those magnitudes, a position that is a meaningful
fraction of a ~$700 account can be nearly or fully wiped in one gap — no software stop
prevents that.

**Mitigations:**
- **Size so the worst-case gap is survivable.** The only control that bounds gap-through
  loss is position size: `position_value × worst_gap_fraction ≤ acceptable_absolute_loss`.
  With −72%..−99% delisting gaps, each single-name position must be sized so a −99% gap is
  a tolerable dollar loss, and the book must be diversified so no single name can zero the
  account.
- **Fractional/conservative Kelly sizing.** *“Gamblers would use less than full Kelly in
  order to reduce the chance of ruin, reduce volatility, and account for model error”* and
  *“betting an amount larger than the Kelly amount increases the risk of ruin.”* [22] Treat
  model error on gap distribution as an explicit input.
- **Reframe the stop's role.** The software stop limits *open-hours slippage*, not maximum
  loss. The true loss bound is the gap, and only sizing controls it.
- **Pre-open limit orders when a gap is anticipated.** If overnight news points to a
  gap-down open, place a limit sell before the open rather than waiting for a market-order
  trigger at the open.

**Sources:** [5][12][22]

---

## Hard-requirements checklist (the monitor is NOT defect-free unless ALL hold)

**Idempotency & no-over-sell**
1. Reconcile-before-act: read live position qty + pending orders immediately before every sell; never act on cached state.
2. Durable per-intent idempotency key persisted (fsync) *before* the sell call; never reused across intents.
3. Durable journal/outbox written before every sell; replayed + reconciled on every restart.
4. “Not enough shares / insufficient” is treated as already-selling, never retried.
5. CLOSED is set only after position verified zero (never on “submitted”).

**Correct order construction**
6. Sell full position by **shares**, not dollars (dollar sells are capped at 95%).
7. Verify-to-zero loop with bounded residual cleanup; escalate to human on persistent residual.

**Quote sanity**
8. N≥2 consecutive confirming quotes beyond threshold before triggering; single tick never sells.
9. Sanity bounds vs last close/reference; suspect quotes require re-confirmation.
10. Halt / untradeable guard: never market-sell a paused or delisted symbol.

**Failure & escalation**
11. Error classification (transient vs permanent) with distinct handling.
12. Randomized exponential backoff + jitter for transient retries.
13. Bounded retries (retry budget/quota); on exhaustion, fail the request and **alert a human**.
14. Human escalation for: retry budget exhausted, permanent rejection, halt/delist, urgent stop-loss slippage.

**Liveness**
15. systemd `Restart=always` + `RestartSec`/`RestartSteps` exponential restart backoff.
16. `WatchdogSec` + `sd_notify(WATCHDOG=1)` heartbeat (catches hung processes).
17. Independent dead-man's-switch (separate failure domain) that alerts the operator when the monitor is down or stale.

**Concurrency**
18. Single writer (exactly one process may submit sells).
19. Per-position state machine `OPEN → SELLING → VERIFYING → CLOSED`, transitions persisted; sells only from `OPEN`.
20. Single-flight per symbol; stale triggers on non-OPEN positions are no-ops.

**Sessions & gaps**
21. Session-aware routing: market sell in 9:30–16:00 ET only; limit order in extended hours (fractional 7–9:30 / 4–7:30); whole-share limit overnight, else stand down.
22. Never fire a market sell outside regular hours expecting an immediate fill (it queues to next open).
23. Position size set so a worst-case (−72%..−99%) gap is a survivable absolute loss; diversification so no single name can zero the account.

---

## Sources

[1] Robinhood — Fractional shares — https://robinhood.com/us/en/support/articles/fractional-shares/
[2] Robinhood — Market order update — https://robinhood.com/us/en/support/articles/market-order-update/
[3] Robinhood — Order types — https://robinhood.com/us/en/support/articles/order-types/
[4] Robinhood — Limit order — https://robinhood.com/us/en/support/articles/limit-order/
[5] Robinhood — Stop order — https://robinhood.com/us/en/support/articles/stop-order/
[6] Robinhood — Stop limit order — https://robinhood.com/us/en/support/articles/stop-limit-order/
[7] Robinhood — Extended-hours trading — https://robinhood.com/us/en/support/articles/extendedhours-trading/
[8] Robinhood — 24 Hour Market — https://robinhood.com/us/en/support/articles/24hour-market/
[9] Robinhood — Stock, ETF, and options order routing — https://robinhood.com/us/en/support/articles/stock-order-routing/
[10] Robinhood — Why was my order rejected — https://robinhood.com/us/en/support/articles/why-was-my-order-rejected/
[11] Robinhood — Why hasn't my order been filled — https://robinhood.com/us/en/support/articles/why-hasnt-my-order-been-filled/
[12] Robinhood — What if a stock is delisted — https://robinhood.com/us/en/support/articles/what-if-a-stock-is-delisted/
[13] Robinhood — Not enough shares error — https://robinhood.com/us/en/support/articles/not-enough-shares-error/
[14] Robinhood — Cancel or replace an order — https://robinhood.com/us/en/support/articles/cancel-a-pending-order/
[15] Robinhood — What's an untradeable stock — https://robinhood.com/us/en/support/articles/whats-an-untradable-stock/
[16] Robinhood — Trailing stop order — https://robinhood.com/us/en/support/articles/trailing-stop-order/
[17] Stripe — Idempotent requests — https://docs.stripe.com/api/idempotent_requests
[18] AWS Builders Library — Making retries safe with idempotent APIs — https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/
[19] AWS SDK Reference — Retry behavior (exponential backoff with jitter, retry quota) — https://docs.aws.amazon.com/sdkref/latest/guide/feature-retry-behavior.html
[20] Google SRE Book — Addressing Cascading Failures — https://sre.google/sre-book/addressing-cascading-failures/
[21] systemd.service(5) — https://man7.org/linux/man-pages/man5/systemd.service.5.html
[22] Wikipedia — Kelly criterion — https://en.wikipedia.org/wiki/Kelly_criterion

**NOT-EXTRACTED (flagged, not invented):**
- Whether stop / stop-limit / trailing-stop orders accept **fractional** quantities — no
  fetched Robinhood page states it; docs describe share-based stops only (silent, not
  affirmative).
- A definitive Robinhood statement that no official *retail equity* trading API exists —
  docs.robinhood.com is a JS shell I could not extract; this is treated as the operator's
  stated premise, not a sourced claim.
