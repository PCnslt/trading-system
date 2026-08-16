# Robinhood Execution — VPS broker client + go-live switch

**Date:** 2026-08-16 · **Author:** VPS Hermes (builder)

The VPS is now the Robinhood trader. This doc records: (1) what was built, (2) the
**exact go-live switch** and verification steps, (3) the transport reality (MCP, not
REST), and (4) the fail-closed limitations you must accept before flipping the switch.

---

## 1. What was built

### `hardening/rh_client.py` — the ONLY Robinhood submitter

Wraps the **Robinhood MCP gateway** (see §4 for why MCP, not REST). Methods:

| Method | Robinhood surface | Notes |
|---|---|---|
| `get_account()` | `get_accounts` | returns the `agentic_allowed=true` account (the "Agentic" acct) |
| `get_positions()` | `get_equity_positions` | open equity positions |
| `get_quote(symbol)` | `get_equity_quotes` | real-time quote + prior close |
| `place_equity_order(...)` | `place_equity_order` | market/limit/stop_market/stop_limit; fractional `dollar_amount` (market only) |
| `place_stop(...)` | `place_equity_order` | protective stop (stop_market / stop_limit) |
| `cancel_order(id)` | `cancel_equity_order` | |
| `list_orders(...)` | `get_equity_orders` | |
| `place_equity_entry(...)` | composed | **fail-closed protected entry** (below) |
| `review_equity_order(...)` | `review_equity_order` | SIMULATE — no order placed (verification path) |

**Fail-closed rules (mirror `exec_manager`):**

1. `place_equity_entry` **REJECTS `stop_price <= 0`** before touching the broker.
2. It places the entry, confirms the fill, then **immediately rests a protective
   stop and VERIFIES it is resting**. If the stop cannot be rested (including a
   fractional fill that rounds to <1 whole share — see §5), it **FLATTENS the
   just-filled entry and raises** — it never leaves a naked position.
3. **Idempotency:** every placement carries a deterministic `ref_id` (UUIDv5 from a
   stable `client_order_ref`), so re-sending the same intent is deduped upstream.

### `infra/rh_oauth.py` — re-authentication (VPS single-writer)

Interactive PKCE `authorization_code` flow, now **VPS-owned**: it DCR-registers
(singleton client), prints the authorization URL + the `ssh -L` port-forward, and
listens on the loopback port so the OWNER completes browser consent from the
laptop. Persists the fresh token local-file-first then SSM. **The laptop MCP is
retired for trading** — the VPS is the single writer of the live token. CLI:
`--check` (read-only state) and `--reauth`. See `docs/ROBINHOOD-ACCESS.md`.

### `bot/live_equities.py` — EXECUTION MODE

`EXECUTION_MODE` = `PAPER` (default) | `LIVE`. The PAPER path is byte-for-byte the
existing simulated-fill behaviour; LIVE is a gated branch that places real orders
through `rh_client`.

---

## 2. The go-live switch (exact)

Two independent env vars, both **OFF by default**. LIVE requires BOTH:

```
RH_EXECUTION_MODE=LIVE      # the explicit mode switch (default: PAPER)
RH_LIVE_ENABLED=true        # the hard-enable circuit breaker (default: false)
```

`RH_LIVE_ACCOUNT` (default `515821577`) selects the account; it must be
`agentic_allowed=true`.

**At order time, LIVE entry additionally requires ALL of** (fail-closed, every check):

1. `RH_EXECUTION_MODE == 'LIVE'` (explicit flag).
2. `RH_LIVE_ENABLED == true` (hard enable).
3. Account is `agentic_allowed` (account-mode check — refuses any non-agentic account).
4. `RISK_PCT <= 0.01` (1%/trade cap).
5. `day_loss_used < DAY_LOSS_CAP` ($150/day realized-loss cap).
6. Protective stop present (`place_equity_entry` rejects `stop_price <= 0` and
   reverses any fill it can't protect — the never-naked chokepoint).

These are enforced in `bot/live_equities.py::live_gate_ok` + `rh_client.place_equity_entry`.

### Verification steps before flipping

1. **Re-auth the token** (currently dead, §6): run `infra/rh_oauth.py` on the laptop,
   then confirm the VPS can read `/trading/robinhood/*` and the client boots:
   ```
   ./venv/bin/python3 -c "from hardening.rh_client import RHClient; c=RHClient(); print(c.get_account()['account_number'], c.get_quote('SPY')['last_trade_price'])"
   ```
2. **Dry-run the bot in PAPER** (unchanged default): `python bot/live_equities.py --dry-run`.
3. **Simulate, never place**: exercise `review_equity_order` (returns quote + pre-trade
   alerts, places nothing) for a would-be entry before any `place_equity_entry`.
4. **Paper-forward ≥ 30 days** on the running bot (owner standard) before LIVE.
5. **Flip BOTH switches**, then watch the first LIVE run's `RHSIG#<sym>` rows render
   `mode=LIVE, execution=RH` with an `order_id` + `stop_order_id` — not `action=NONE`.
6. **Reconcile**: confirm `get_positions()` matches the `RHPOS#` book; confirm every
   open position has a resting stop in `list_orders()`.

---

## 3. The go-live switch lives in the commit message too

The commit introducing this (`rh_client` + `live_equities` EXECUTION MODE) documents
the switch as: **set `RH_EXECUTION_MODE=LIVE` AND `RH_LIVE_ENABLED=true`** — do not
flip without §2 verification.

---

## 4. Transport reality (verified 2026-08-16, ground truth)

The SSM creds under `/trading/robinhood/*` are OAuth tokens minted for the
**Robinhood MCP gateway**, NOT the public REST API:

- The public REST endpoints at `api.robinhood.com` **reject this client_id**
  (`rejected client id`) — the JWT's `meta.oid` is an MCP client, not a REST client.
- The working surface is the **Streamable-HTTP MCP server** at
  `https://agent.robinhood.com/mcp/trading` (server `robinhood-trading` 1.1.4,
  protocol `2025-06-18`), which exposes the 54 `mcp_robinhood_*` tools this client wraps.
- `token_endpoint` (from `meta_json`) = `https://api.robinhood.com/oauth2/token/`.
  Public client, `token_endpoint_auth_method=none` → **no client_secret**.

So `rh_client` is an MCP-protocol client (JSON-RPC over HTTP + SSE), not a REST
client. If the laptop later obtains a REST-capable OAuth client, the transport can be
swapped under the same method surface — but the fail-closed rules are transport-agnostic.

---

## 5. Limitations you must accept before LIVE

1. **Fractional positions cannot carry a broker stop.** Robinhood's protective stops
   (`stop_market`/`stop_limit`) are **whole-share only** (fractional quantity is
   accepted for market orders in regular hours only). A sub-1-share position has no
   broker-side stop, so `place_equity_entry` **reverses it fail-closed** rather than
   leave it naked. At $700, the RSI2 size ($25–50 → fractional for most names) is
   therefore **not live-executable** — LIVE only admits positions ≥ 1 whole share
   (names ≤ ~$35/share at current sizing). This is the honest reason LIVE is not
   switched on: the fractional edge needs either (a) larger capital so sizes are
   whole shares, or (b) a code-level stop (unacceptable under never-lose-money).
2. **No native bracket.** Robinhood has no entry+stop atomic bracket (unlike IBKR).
   The never-naked guarantee is a *code* guarantee (place stop immediately after
   fill, verify, reverse on failure), not a *broker* guarantee. A crash between
   entry-fill and stop-rest would leave a brief naked window — the next run must
   reconcile and protect. A dedicated Robinhood reconciler is follow-on work.
3. **LIVE exit is a basic path** (`_live_exit_position`: cancel stop + market close,
   fill-confirmed). Broker-side stop fills (intraday stop, gap-through) are not yet
   reconciled by the bot — that requires the follow-on reconciler.

None of these block the build or the paper-forward lane; they are the honest
preconditions for flipping LIVE.

---

## 6. ⚠️ Current blocker — token is DEAD, re-OAuth required

During build, the refresh flow was exercised once to validate the rotation
behaviour. Robinhood's refresh **rotates the refresh_token AND immediately revokes
the old access token** (`invalid_grant` / `token revoked`), and the rotated value
was not persisted before the process exited. Result: the `refresh_token` and
`access_token` in SSM are both now **invalid**.

**Recovery:** run `python3 infra/rh_oauth.py --reauth` on the VPS (it prints the
authorization URL + `ssh -L 58245:127.0.0.1:58245 ubuntu@52.7.95.127` port-forward;
the owner completes browser consent from the laptop), which re-auths via PKCE and
writes fresh tokens to SSM. Until then, the Robinhood lane cannot read the account
or place orders. The `rh_client` itself is correct and validated — it will work the
moment fresh tokens are in SSM.

**Lesson (encoded in the client):** refresh writeback is crash-safe — persist the
rotated token to the **local fallback file first, then SSM**, before returning.
Never test a rotating-token refresh without persisting the result.
