# SELF-AUDIT — Trading Code & Logic (skeptical, evidence-based)

**Date:** 2026-08-16 (Sun) · **VPS operator:** Hermes (build/deploy/operate)
**Scope:** trading code + logic ONLY (infra already handled by a prior pass).
**Method:** read the actual code, ran the full test suite, checked live/paper state
against ground truth (DynamoDB CONTROL/RECONCILE/POSITION + gateway port). No
self-congratulation — every claim below is `file:line`-evidenced.

**Verdict summary:** the execution/risk stack is materially sound. The "never
trade without a stop" property holds by construction (native bracket + refuse-
no-stop + reconciler verifies a stop rests on every open position). Two real
GAPs found (reconcile-detects-but-does-not-auto-halt; inert naked-order code in
the shelved bonds bot), one minor bug fixed (idempotency key burned on a
rejected no-stop entry), and one design gap needing an owner decision. No live
orders can be placed: gateway is paper-only on :4002, `LIVE=false`, no live
account id in any order path.

---

## 1. STOP-LOSS ENFORCEMENT — **PASS** (one minor fix applied)

**Is `exec_manager.submit_entry` the ONLY code path that places entries? YES.**

Exhaustive `placeOrder` grep across the repo (excluding venv/tests/.git):

| file:line | purpose | verdict |
|---|---|---|
| `hardening/exec_manager.py:211,230,231,234` | native bracket entry + stop (+ optional target) | sanctioned, stop-enforced |
| `hardening/exec_manager.py:254` | `submit_exit` market close | close, no stop needed |
| `hardening/exec_manager.py:264` | `_place_stop` (protective stop / re-rest) | sanctioned |
| `bot/control.py:186` | `flatten_ibkr` kill-switch market close | close, no stop needed |
| `bot/live_bondsfx.py:259,285` | raw short entry/cover | **DEAD CODE** — bot disarmed (`main()` returns at `:318-321`) |
| `bot/execution_test.py:30,36` | manual smoke-test naked round-trip | manual only, not scheduled |

The ONLY active ENTRY path is `ExecutionManager.submit_entry`, which is declared
the sole broker writer at `exec_manager.py:132`.

**Bracket is actually WIRED into every live bot (not just written):**
- `bot/live.py:352` → `exec_mgr.submit_entry(intent, con)`
- `bot/live_gc.py:372` → `exec_mgr.submit_entry(intent, con)`
- `bot/live_intraday.py:389` → `exec_mgr.submit_entry(intent, con, stop_tif='DAY')`
- All three construct `ExecutionManager` at `live.py:473`, `live_gc.py:487`,
  `live_intraday.py:540` and pass it into every `run_strategy`.

`submit_entry` → `_place_bracket` (`exec_manager.py:199`) submits a **market
parent with `transmit=False`** (`:212`) + a **stop child with `parentId`+OCA**
(`:219`, `:216-221`) that transmits the chain — so the stop is held broker-side
BEFORE the entry fills. No naked-position window by construction. Verified by
`tests/test_exec_manager.py:216 test_bracket_submits_parent_then_linked_stop`.

**If the bracket/stop is REJECTED — fail-closed, not naked:**
- `stop_price <= 0` → `REJECTED` before anything is sent (`exec_manager.py:167-174`).
- Parent definitively REJECTED → cancels any resting legs, returns `REJECTED`,
  bot writes no state (`exec_manager.py:180-184`; `live.py:360-362`).
- Fill TIMEOUT → `UNKNOWN` (never assumed rejected); the bracket stop is LEFT
  resting so a filled entry stays protected (`exec_manager.py:186-189`,
  `:359-362`). Bot writes no state; reconciler resolves.
- Residual (see GAP-1): if the **stop leg** were rejected while the parent still
  transmitted, the code does not explicitly detect that single corner — it
  relies on (a) IBKR bracket semantics (stop is the transmitting leg, so a stop
  rejection rejects the chain) and (b) the reconciler's stop-existence check
  (`reconciler.py:185-199` flags a missing stop on any open position within 45 s).

**Fix applied this audit:** `submit_entry` validated `stop_price <= 0` AFTER
`intents.accept()` burned the idempotency key, so a rejected no-stop entry
permanently blocked a corrected retry. Reordered to validate-first
(`exec_manager.py:167` before `:173`). New regression test
`test_rejected_no_stop_does_not_burn_idempotency_key` locks it in.

---

## 2. POSITION SIZING + LOSS CAPS — **PASS**

Traced one entry end-to-end (live.py, the swing lane):

1. **risk_pct (0.5–1%):** `bot/live.py` uses default `RiskConfig` `risk_pct=0.02`;
   `bot/live_intraday.py:82` sets `INTRA_RISK_PCT = 0.01` (1% — inside owner's
   0.5–1% band). Sizing = `risk_pct × budget / (stop_distance × point_value)`
   (`bot/risk.py:203-204`).
2. **Vol overlay (baa1551/83e0628):** `RiskConfig.vol_scale_enabled=True`,
   `vol_target_pct=0.02` (`bot/risk.py:41-42`); `position_size()` caps qty at
   `vol_budget / (realized_vol × price × point_value)` and returns **0 (reject)**
   if even one contract exceeds the vol budget (`bot/risk.py:208-215`). Wired in
   the live entry path at `live.py:343-346` (passes `realized_vol` + `price`),
   `live_gc.py:362-364`.
3. **$150 daily loss cap:** `RiskConfig.max_daily_loss_pct=0.02` × budget
   (`bot/risk.py:50`); for live.py budget `RISK_BUDGET=50000` → $1,000, for
   intraday `INTRA_RISK_BUDGET=25000` → $500. NOTE: the $150 figure from the
   laptop brief does not appear as a literal in the code — the actual cap is
   **budget × 2%** (`$50k→$1k`, `$25k→$500`). This is a *higher* daily-loss
   allowance than $150; flagging for owner awareness (see GAP-3). Halt is
   enforced in `RiskEngine.can_enter` (`bot/risk.py:167-168`) and re-evaluated on
   every `record_close` (`bot/risk.py:239-242`), persisted to the ledger so a
   crash/re-run cannot reset it (`bot/risk.py:130-138`, `risk_ledger.py:49-76`).
4. **Kill-switch:** `CONTROL/system` read fail-closed before any order
   (`live.py:422-430`); `KILLED` → flatten + halt (`live.py:431-438`);
   `PAUSED` → no new entries (`control_allows_entry`, `control.py:56-58`).

`RiskEngine.load` HALTS the run on an unreadable ledger (`live.py:450-454`,
`bot/risk.py:100-109`) — fail-closed, never a silently-reset budget.

---

## 3. PAPER/LIVE ISOLATION — **PASS**

- Live account id **U26949861 appears only in a diagram label**
  (`assets/architecture.html:200` "live U26949861 — OFF (Gate 5 pending)").
  It is used **nowhere** in any order/connect path (grep: zero code hits).
- Gateway listens on **:4002 only** (`ss -tlnp` — single listener, no :4001).
- `LIVE` env is unset → `os.getenv('LIVE','false')=='true'` = **False** in all
  four bots (`live.py:65`, `live_intraday.py:83`, `live_gc.py:84`,
  `live_bondsfx.py:75`). `.env` contains no LIVE/EXECUTION/ACCOUNT/PORT override.
- Double gate: `account_mode_ok` (`control.py:61-71`) REFUSES orders on any
  paper/live mismatch — called in all four bots (`live.py:417`,
  `live_intraday.py:474`, `live_gc.py:438`, `live_bondsfx.py:351`). Even a
  mis-pointed live gateway with `mode=PAPER` fails closed.

Ground truth today: `CONTROL/system = RUNNING`, `RECONCILE/system = MATCH`,
zero open `POSITION#` rows, zero `INTENT#` rows (no entries ever accepted yet).

---

## 4. ERROR HANDLING — **PASS** (one latent corner, see GAP-1)

| case | behaviour | verdict |
|---|---|---|
| Gateway death mid-order | bracket parent is `transmit=False` → nothing transmits until the stop leg; death before the stop → parent never active (no fill). Death after → stop rests broker-side | fail-closed by construction |
| Fill-confirmation timeout | `_confirm` returns `UNKNOWN` (never `REJECTED`), stop left resting, no state written | fail-closed (`exec_manager.py:359-362`) |
| Partial fill | `_confirm` reports `PARTIAL`; `submit_entry` re-rests a stop sized to the FILLED qty (`exec_manager.py:188-194`); bots write actual qty (`live.py:363-365`) | fail-closed |
| Duplicate submission / clientId reuse | `IntentStore.accept` conditional `attribute_not_exists(pk)` → one signal_id → at most one order (`exec_manager.py:96-107`, `_conditional_put` `:35-51`) | idempotent |
| Order not confirmed | no state written; reconciler flags unaccounted fill within 45 s (`reconciler.py:241-248`) | fail-closed |

`submit_exit` cancels the stop FIRST then closes (`exec_manager.py:250-255`,
`live.py:274-280`) so stop-fill and exit-fill cannot race.

---

## 5. RECONCILIATION + KILL-SWITCH — **GAP (owner decision recommended)**

Trace: `reconcile_daemon.py` (clientId 76, 45 s) runs `reconcile()` and writes
`RECONCILE/system` (`reconcile_daemon.py:82-91`). **It never mutates
`CONTROL/system` and never places orders** — that is deliberate
(`reconcile_daemon.py:13-14`).

- The **kill-switch** (`CONTROL/system`) is read by every bot at run start,
  fail-closed (`live.py:422-430`, `live_gc.py:444-451`,
  `live_intraday.py:482-489`).
- On `MISMATCH` the daemon prints `CRITICAL` (`reconcile_daemon.py:86`) and the
  `reconcile_watchdog.sh` Hermes cron (every 5 min) alerts Telegram via
  `bot/reconcile_health.py:39-40`. **It does NOT flip CONTROL=KILLED/PAUSED and
  does NOT re-rest a missing stop.**
- Each bot independently reconciles at run start and HALTS on non-MATCH
  (`live.py:466-470`, `live_gc.py:480-484`, `live_intraday.py:533-537`).

**GAP:** a detected `MISMATCH` (e.g. orphaned/missing stop = unprotected
position) triggers an alert + the next bot run halts, but does **not** auto-pause
the system or auto-heal. Between detection (≤45 s) and the next bot run (≤15 min
intraday, ≤24 h daily) an unprotected position sits waiting on a human. This is
the single most material item vs the "must not lose money" objective. It is
currently paper-only, so no real capital is at risk. **Owner decision:** should
the daemon (or `reconcile_health.py`) flip `CONTROL=PAUSED` on a sustained
non-MATCH? I did NOT change this unilaterally — auto-killing on a transient
gateway blip (reconcile `UNKNOWN`) would halt the whole system.

---

## 6. CONCURRENCY — **PASS**

clientId map (grep `clientId`/`CLIENT_ID` across repo) — **no overlaps**:

`50` backfill · `70` live.py · `71` live_bondsfx (disarmed) · `72` live_intraday
· `73` backfill_bars/futures_contracts · `74` tick_recorder · `75` daily_collect
· `76` reconcile_daemon · `77` options_chains · `78` live_gc · `90`
backfill_futures_bars · `91` probe_gateway.

- The past 23:00/23:05 collision (70/71/72) is gone: `paper_bonds.sh`
  (`230216077ed8`) is **disabled** in Hermes cron; only live.py(70)@23:00 and
  live_gc(78)@23:10 place orders, distinct ids, distinct symbols.
- Idempotency: `signal_id` is a deterministic md5 over (scope,tag,symbol,action,
  side,bar_time,order_type) (`exec_manager.py:73-77`); `IntentStore` conditional
  write makes double-ordering impossible at the broker (`exec_manager.py:96-107`).
- Intraday double-entry additionally blocked by position state
  (`_read_state`/`_other_open`, `live_intraday.py:262-276`, `:367-370`) and the
  cross-bot stand-down when the daily bot holds MES (`live_intraday.py:284-290`,
  `:501-505`).

Minor note: `bot/execution_test.py` uses clientId **77**, same as
`data/options_chains.py` — but execution_test is manual-only and options_chains
is read-only at 17:45 ET, so no practical collision.

---

## 7. TIMEZONE — **PASS** (one latent edge case, not live-triggered)

- RTH gating + EOD flatten use `ZoneInfo('America/New_York')`
  (`live_intraday.py:90-94`), `tick_recorder.py:62` — DST-aware. ✓
- System TZ = `America/New_York` (`timedatectl`). ✓
- Daily bots (`live.py:389`, `live_gc.py:412`) use `dt.date.today()` (= ET) for
  RUN#/SIGNAL#/TRADE#/POSITION date keys; they run 19:00/19:10 ET, where ET date
  == UTC date, so no boundary issue.
- Risk ledger day is deliberately UTC (`bot/risk.py:92`), a documented storage
  convention; bots run in the window where UTC date == ET date.
- Hermes-cron exprs are still UTC (`0 23`=19:00 ET etc.) because the gateway
  process caches its TZ at startup — documented in `infra/crontab.txt` and the
  trading-bot-operations skill. Bots' internal `ZoneInfo` gating is unaffected.

Latent edge case (low severity, not live): `reconcile(..., today_iso=<ET date>)`
compares broker fill times in **UTC** against the ET date
(`reconciler.py:230-238`, `:258`). Between 20:00–24:00 ET the UTC date is one
day ahead of ET, so an "unaccounted fill" could be mis-bucketed if a bot ever
ran then. None of the current bots run in that window.

---

## 8. TESTS — **PASS** (coverage is real, not shallow)

`./venv/bin/python -m pytest` → **159 passed, 0 failed** (was 158; +1 new test
this audit). The risk paths are genuinely exercised, not stubbed around:

- Stop enforcement: `test_submit_entry_rejects_no_stop`,
  `test_bracket_submits_parent_then_linked_stop`,
  `test_bracket_keeps_stop_resting_on_unknown_fill`,
  `test_bracket_partial_fill_resizes_stop_to_filled_qty`,
  `test_trail_stop_tightens_long` / `_short`, ref-tagging tests
  (`test_exec_manager.py`).
- Sizing/vol overlay: `test_position_size_vol_overlay_caps_qty`,
  `_rejects_when_vol_too_high`, `_never_increases`, wide-stop→0 (`test_risk.py`).
- Reconcile stop-existence: `test_reconcile_mismatch_missing_stop`,
  `_orphan_stop`, GC bidirectional `UNKNOWN`-on-missing-side (`test_reconciler.py`).
- Kill/account guards + flatten ack semantics (`test_control.py`,
  `test_invariants.py`).

`conftest.py:11-61` provides an in-memory DynamoDB double with a real
conditional-write conflict, so the idempotency path is tested against a faithful
double rather than a no-op.

One gap: there is no test for "stop leg rejected while parent transmits" (the
corner in GAP-1). Adding one requires an IBKR bracket-semantics double that
models child-rejection → parent-transmit; left as a note.

---

## 9. STRATEGY SOUNDNESS — **PASS** (no unvalidated strategy places orders)

| strategy | lane | validation | orders? |
|---|---|---|---|
| MES/MNQ Donchian (chandelier 3·ATR) | live.py | OOS PF 2.08/2.14 | paper ✓ |
| MES/MNQ RSI2 (fixed 2·ATR) | live.py | OOS PF 2.69/2.21/1.79 | paper ✓ |
| GC Donchian L/S (chandelier) | live_gc.py | full 1.45 / OOS 1.81 / 3-tick 1.42 | paper ✓ |
| GC TSMOM (fixed 3·ATR) | live_gc.py | 1.37/1.73/1.99 / 3-tick 1.35 | paper ✓ |
| MES FADESHORT + DONCH15 | live_intraday.py | **Gate-1 = NO cost-surviving edge** | **SIGNAL-ONLY** (`INTRA_EXECUTION=NONE`) |
| ZB/ZN RSI2SHORT/BBANDSHORT | live_bondsfx.py | dies at 1-tick slippage | **DISARMED** (no-op `main()`) |
| crypto (MOM/MR/Donch200) | crypto_paper/signals | candidates/signal-only | signal-only |
| equities (mom/mr) | equity_signals.py | candidates | signal-only |

The only strategies that can place orders (live.py + live_gc.py) are the
**validated** ones. The unvalidated/losing intraday DONCH15 (long PF 0.08/18)
runs **signal-only** — it cannot lose money, only collect data. Flag: it must
never be promoted without a fresh Gate-1 pass. Crypto stays signal-only (owner
distrust). No running strategy has a validated OOS PF < 1.0 with live orders.

---

## 10. UNCOMMITTED / UNPUSHED — **CLEAN** (now committed + pushed)

`git fetch` → `origin/main..HEAD` = **0 commits**; working tree was clean at
audit start. Author config verified `PCnslt <info@pcnslt.com>`. This audit's
changes are committed + pushed below.

---

## FIXES APPLIED (this audit)

- **exec_manager.py** — validate `stop_price <= 0` BEFORE the idempotency accept
  (a rejected no-stop entry no longer burns its signal_id).
- **tests/test_exec_manager.py** — regression test
  `test_rejected_no_stop_does_not_burn_idempotency_key`.

## GAPS / BLOCKERS (need owner input — NOT auto-fixed)

- **GAP-1 (highest):** reconcile detects a missing/orphaned stop but does not
  auto-halt (`CONTROL=PAUSED`) or auto-re-rest the stop. Enforcement = next bot
  run + Telegram alert. Recommendation: on a **sustained** non-MATCH (e.g. 2+
  consecutive 45 s cycles), flip `CONTROL=PAUSED`. Owner decision needed
  (auto-kill on transient `UNKNOWN` would halt the whole system).
- **GAP-2 (inert):** `bot/live_bondsfx.py:259,285` places raw market shorts with
  **no protective stop** (`has_stop_order: False` in its strategy table) and no
  `exec_manager`. Currently harmless — `main()` is a no-op (`:318-321`) — but it
  is a landmine if ever re-enabled. Must be refactored onto `exec_manager`
  (bracket + stop) before ANY re-enable.
- **GAP-3 (clarify):** the owner's "$150 daily loss cap" is not a literal in the
  code. The enforced cap is `max_daily_loss_pct(2%) × budget` = **$1,000** (live.py
  $50k) / **$500** (intraday $25k). If $150 is the intended hard number, budgets
  or `max_daily_loss_pct` must be lowered.
- **GAP-4 (housekeeping):** `bot/execution_test.py` places a naked BUY→SELL
  round-trip (manual smoke test, not scheduled). Fine as a manual tool, but it
  bypasses the stop path; consider gating it behind an explicit `--i-know` flag
  or removing it.

## GROUND TRUTH (verified live)

`CONTROL/system=RUNNING`, `RECONCILE/system=MATCH ({} positions)`, 0 open
`POSITION#`, 0 `INTENT#` (no entry ever accepted), gateway on `:4002` only,
`LIVE=false`, system TZ `America/New_York`. 12 crypto SIGNAL rows today all
`execution=NONE`. System is flat, paper-only, fail-closed.
