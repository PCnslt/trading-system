# Task Completion Reports

> Canonical return-channel log. Every dispatched task appends here (newest at bottom, chronological).
> Machine-readable mirror: `REPORTS.json`. Pull path: `GET /reports` on :8645.

## 2026-08-16T12:00:25-04:00 — Return channel — VPS→laptop reporting (GET /reports pull endpoint)

- **Summary**: Built the PULL return channel: reporting/report.py (append_report → REPORTS.md + REPORTS.json, canonical), reporting/report_server.py (stdlib HTTP server :8645, HMAC-SHA256 auth reusing laptop-task webhook secret), trading-reports.service (enabled+running). Verified end-to-end: /health 200, /reports 401 w/o sig + 200 w/ valid HMAC, limit/since params, newest-first ordering.
- **Commits**: `a8be23eb86c9854b5acb0b2c28aa034baad3f13b`
- **Blockers**:
  - SG ingress for :8645 is NOT open: trading-vps-role lacks ec2:AuthorizeSecurityGroupIngress. Owner must run 'aws ec2 authorize-security-group-ingress' for tcp 8645 (laptop IP, mirrors 8644 rule) before the laptop can reach /reports over the public internet.

---

## 2026-08-16T12:10:04-04:00 — Gate-1 intraday validation: 6 futures candidates (ORB/MOM/VWAP/DONCH15/FADESHORT/KAMA)

- **Summary**: ALL 6 FAIL Gate-1 at realistic cost (3-tick slip/side + comm, walk-forward 60/40, ~1y IBKR 5-min bars). Pooled PF@slip3: ORB 0.97/-6.7kt, MOM 0.80/-94kt, VWAP 1.01/+1.5kt (noise over 6093 trades), DONCH15 0.99/-2.6kt, FADESHORT 0.95/-6.9kt, KAMA 0.70/-104kt. MOM+KAMA dead even at slip0 (negative gross). ORB/VWAP/DONCH15/FADESHORT hold only a thin gross edge wiped by >=2-tick slip. No candidate advances to paper-test.
- **Blockers**:
  - No viable intraday edge on 5-min bars at honest cost. Do NOT deploy intraday. Revisit with tick/level data or structural higher-TF edge (overnight trend/swing). Keep DCA+wheel+paper.

---

## 2026-08-16T12:14:14-04:00 — Recoverability + IaC hardening (git/docs only): recovery runbook + as-built CloudFormation + requirements.txt + hermes systemd

- **Summary**: Committed 85aca63 + pushed (4809427..85aca63), verified ahead=0/behind=0. (1) GIT: NO unpushed commits existed — laptop audit claim of '6 unpushed commits' was STALE (HEAD already == origin/main); 'git push origin main' returned Everything up-to-date before this commit. (2) requirements.txt: 90 packages frozen from ./venv. (3) infra/hermes-gateway.service: as-built USER systemd unit (already enabled + linger=yes on VPS, Restart=always, survives reboot) — NOT restarted per instruction. (4) docs/RECOVERY.md: full copy-paste runbook of the VERIFIED as-built system. (5) infra/cloudformation.yaml rewritten to as-built: native GWClient (no IBC), SG 22/8501/8644 (+8645 documented-not-open), 19 DDB tables auto-provision note, least-privilege IAM, full systemd+cron+EIP, SSM = documented target (file-based today). Honest corrections vs audit: gateway ALREADY had a systemd user unit; IAM has narrow ec2:DescribeSecurityGroups READ (verified ALLOWED) though ssm/cloudformation/ec2:DescribeInstances are DENIED.
- **Commits**: `85aca633f9eb039f7d235eb7d6674a5caaca7ee8`

---

## 2026-08-16T12:30:47-04:00 — Secrets → SSM: make the VPS consume /trading/* (SSM-first loader + wiring)

- **Summary**: Created infra/secrets.py: boto3 SSM get_parameters(WithDecryption) over /trading/*, overlays os.environ (SSM wins), falls back to .env / ~/ibgateway-creds.env; short botocore timeouts + in-process cache; NEVER raises on SSM outage. Wired bootstrap() into all 37 data/ + bot/ entry points (SSM-first, .env fallback) and --ibkr-shell into ibgateway-login.sh (both repo + /home/ubuntu deployed copies, kept in sync). Updated docs/RECOVERY.md (IAM §2, Secrets §5, rebuild §9, §11) + infra/cloudformation.yaml (SSM = source of truth, .env = fallback cache, least-privilege ssm read grant scoped to /trading/*). .env + ibgateway-creds.env KEPT as fallback cache (not deleted). VERIFIED from VPS: 8/8 /trading/* params decryptable — ibkr/username(12), ibkr/password(10), alphavantage/api_key(15), binance_us/api_key(64)+secret_key(64), fmp/api_key(32), newsapi/api_key(32), serper/api_key(40). WithDecryption fetch of /trading/ibkr/username + /trading/fmp/api_key confirmed. Fallback tested: SSM-down simulation → bootstrap() degrades to .env (6 API keys) + ibgateway-creds.env (IBG creds), no crash. 158/158 tests pass. Also commits the 2 prior uncommitted reports (intraday Gate-1 + recovery-hardening) that were sitting in the working tree.
- **Commits**: `4741449c20828e16942085f0ac37fb95c1dc8de0`
- **Blockers**:
  - Live role trading-vps-role now carries AdministratorAccess (granted by laptop) — broad. Consider narrowing to least-privilege (ssm read scoped to /trading/*) once migration is stable.

---

## 2026-08-16T12:45:18-04:00 — NOOP dispatch-channel HMAC verification

- **Summary**: Received laptop-task webhook with valid HMAC; dispatch channel confirmed working end-to-end. No action required.

---

## 2026-08-16T12:49:37-04:00 — IAC sync: import live CloudFormation stack 'trading-system' into repo

- **Summary**: Captured authoritative template -> infra/cloudformation-stack.yaml (6 imported resources: role trading-vps-role, instance-profile trading-vps-profile, SG sg-0b981dd12552d33b9, instance i-00009f59dcb52f725, EIP 52.7.95.127/eipalloc-02c0ee26388774a5b, association eipassoc-048b2eb45a688becb; DeletionPolicy+UpdateReplacePolicy Retain on all). Added CloudFormation section to docs/RECOVERY.md + fixed stale preamble. Verified drift = SecurityGroup GroupDescription ONLY (template 'Trading VPS - SSH, dashboard, webhook, reports' vs live 'Trading system VPS'). Note: aws CLI not installed on VPS — used boto3 get_template (identical output); template Description carries a literal '?' from the laptop import (cosmetic, captured verbatim).
- **Commits**: `76aa3b7ad87d3e077cadc5b23d39636039d59869`

---

## 2026-08-16T13:10:00-04:00 — Stop IBKR 1-min backfill at weekend; confirm equities-daily COMPLETE (ground truth)

- **Summary**: Equities-daily backfill genuinely COMPLETE (done=1536, written=1450, gapped=86, failed=0) — flag data/ibkr_daily.COMPLETE touched at 13:07 EDT. Watcher detected phase-4 (futures-1min header) and touched flag, but its 'systemctl stop' ran WITHOUT sudo and FAILED silently while printing 'STOPPED' — service kept running into the 1-min phase. Manually stopped via sudo -n (now inactive). 1-min phase wrote ZERO bars before stop (only connected + banner), so no partial/contaminated data. Pause flag data/ibkr_1min_paused present → gateway_resume.sh gate (line 31) verified to hold service down; unpause-timer clears flag Sat 2026-08-22 00:01 ET, then 1-min resumes next weekend window. FIXED watcher to sudo -n systemctl stop + fail loudly (exit 1) instead of false STOPPED.
- **Commits**: `91f7d0568d81fbcf30b87073ca61d7779537fd04`

---

## 2026-08-16T13:10:05-04:00 — Rigorous self-audit of trading code & logic (10 items, owner skeptical)

- **Summary**: STOP-ENFORCEMENT PASS (bracket wired in live.py/live_gc.py/live_intraday.py; refuse-no-stop fail-closed). SIZING/LOSS-CAPS PASS (vol overlay + risk_pct + 2%*budget daily halt + kill-switch, end-to-end traced). PAPER/LIVE ISOLATION PASS (gateway :4002 only, LIVE=false, U26949861 never used for orders, account_mode_ok double-gate). ERROR HANDLING PASS (bracket transmit=False = fail-closed on gateway death; UNKNOWN-on-timeout never naked; idempotent conditional write). CONCURRENCY PASS (clientIds 50-91 no overlap; 23:00/23:05 collision gone). TIMEZONE PASS (ZoneInfo America/New_York RTH/EOD; one latent 20-24h ET edge not live-triggered). TESTS 159/159 pass, cover stop/sizing/bracket paths. STRATEGY: only validated edges place paper orders; intraday+crypto signal-only; bonds disarmed. Fixed: submit_entry validate-stop-before-accept + regression test. GAPS needing owner: (1) reconcile detects missing/orphaned stop but does not auto-halt CONTROL or re-rest stop; (2) live_bondsfx.py dead code has raw no-stop shorts (inert, disarmed); (3) $150 cap is actually 2%*budget=$1k/$500 not literal $150; (4) execution_test.py naked manual round-trip.
- **Commits**: `c56486928bcce5e944f9d5a11a151a51e05d8c72`
- **Blockers**:
  - GAP-1: reconcile_daemon detects MISMATCH but does NOT auto-flip CONTROL=PAUSED or re-rest a missing stop — enforcement is next-bot-run + Telegram alert. Owner decision required (auto-kill on transient UNKNOWN would halt whole system).
  - GAP-2: bot/live_bondsfx.py:259,285 raw no-stop shorts + no exec_manager (INERT, main() is no-op) — must refactor onto exec_manager before any re-enable.
  - GAP-3: '$150 daily loss cap' is not literal in code — enforced cap is max_daily_loss_pct(2%)*budget = $1,000 (live) / $500 (intraday). Confirm or lower.

---

## 2026-08-16T13:15:45-04:00 — Risk-param drift fix (2%->1%) + architecture diagram refresh (laptop audit)

- **Summary**: risk_pct default 0.02->0.01; vol_target_pct 0.02->0.01 (co-equal). pytest: 159 passed, 0 regressions. py_compile OK on live/live_gc/live_intraday/live_bondsfx/risk. git ahead=0/behind=0. architecture.html: 7 text edits (SSM /trading/* secrets, Return-channel GET /reports :8645, live_gc.py, native BRACKET orders, 1% risk/trade + 1% vol overlay, CloudFormation 'trading-system' Retain, SG 22/8644/8645 self-heal) - verified present + parses for st.components.v1.html. CORRECTIONS to laptop audit: (1) INTRA_RISK_PCT=0.01 is NOT dead code - it IS wired at live_intraday.py:513, so live_intraday already traded at 1%; (2) live_bondsfx.py also inherited 2% (missed by laptop) - now 1% via default. max_daily_loss_pct left 2% (pending owner). CRITICAL consequence: at 1% the current paper sleeves reject ALL entries - at 2% MES-RSI2=1ct + GC=1ct (MES-Donchian/MNQ already size=0); at 1% every lane size=0. Sleeve-vs-instrument decision for owner (SELF_REVIEW §5.1).
- **Commits**: `827a66b` `1088f50`
- **Blockers**:
  - max_daily_loss_pct still 2% of budget - confirm exact daily-loss cap with owner ($150 prior vs %-of-budget).
  - At 1% risk/trade, the 50k index + 1.5M gold paper sleeves size=0 for all instruments - owner must decide: raise sleeves / MES-only / MGC micro, or keep 2% as explicit paper-only override.

---

## 2026-08-16T13:28:04-04:00 — GAP-FIXES (SELF_AUDIT): close GAP-1/2/4 unprotected-position windows

- **Summary**: Applied the three GAP fixes from research/SELF_AUDIT.md. GAP-1: reconcile_daemon.py now tracks a persisted MISMATCH streak and flips CONTROL/system to PAUSED after 2 consecutive 45s MISMATCH cycles (~90s), closing the unprotected-position window between detection and the next bot run (up to 15min intraday / 24h daily); UNKNOWN gateway blips never pause; PAUSED (not KILLED) so existing positions still manage to exit. Added tests/test_auto_pause.py (6 tests) locking the 2-cycle threshold. GAP-2: stripped the naked ib.placeOrder market-short/cover (no protective stop) from live_bondsfx.py, replaced with a fail-closed _order_path_removed() guard that raises and routes any re-enable through hardening.exec_manager; signal/backtest logic kept. GAP-4: execution_test.py now refuses to run (exit 2) without an explicit --i-know flag. Verified: 165 tests pass, guards exercised at runtime, reconcile-daemon restarted and live (RECONCILE/system now carries mismatch_streak).
- **Commits**: `ca67818`
- **Blockers**:
  - GAP-3 remains open: owner 150-USD daily loss cap is not a literal in code; enforced cap is 2% x budget (1k live / 500 intraday). Owner decision needed — out of scope for this task.

---

## 2026-08-16T13:28:58-04:00 — RSI2 entry: test + adopt Connors 200d-SMA trend filter (ES/NQ backtest)

- **Summary**: RSI2 entry refinement: current RSI(2)<10 (no filter) vs Connors ORIGINAL (RSI(2)<10 AND close>200d SMA) on ES/NQ daily 2010-2026, 3-tick+1.3bp comm, same 40/20/40 + 3-fold walk-forward as validate_edges. DECISION: ADOPT (added 200d-SMA filter to live.py rsi2_entry; 165/165 tests pass).
Numbers (3-tick cost, single contract):
  ES  no-filter: OOS PF 2.57, maxDD -$44.2k (-155% rel), trough -$15.6k, worst -$16.7k, streak 3, win 70% (n=199).
  ES  filtered:  OOS PF 2.47, maxDD -$23.4k (-86% rel),  trough +$3.8k, worst -$11.2k, streak 3, win 70% (n=142).
  NQ  no-filter: OOS PF 2.24, maxDD -$35.6k (-77% rel), trough +$10.9k, worst -$17.9k, streak 7, win 66% (n=194).
  NQ  filtered:  OOS PF 2.33, maxDD -$48.2k (-68% rel), trough +$22.9k, worst -$17.6k, streak 4, win 68% (n=143).
Rule check (>= comparable OOS PF AND lower maxDD):
  - OOS PF comparable/better both: ES 2.47 vs 2.57 (~noise), NQ 2.33 vs 2.24 (better); pooled 3-tick PF 2.04 vs 1.88 (better).
  - Drawdown LOWER on the meaningful measure: relative DD% ES 86 vs 155, NQ 68 vs 77; absolute trough higher both; worst trade <=; losing streak <=.
  - NQ raw-$ maxDD is HIGHER (-$48k vs -$35k) but this is a COMPOUNDING artifact, not worse DD: filtered peaked higher ($71k vs $46k @ 2021-11-29, gate kept it in the bull) so peak->trough $ distance is larger even though its trough ($22.9k) is HIGHER than no-filter's ($10.9k); same peak/trough dates (2021-11-29 -> 2024-01-04). Relative DD is lower (68% vs 77%).
  - Mechanism = Connors' intent: gate blocks sub-200d-SMA knife-catches; it removed the COVID 2020-03-09 crash entries (worst trades) on both symbols. No-filter ES went NEGATIVE cumulative (-$15.6k) at the COVID bottom while filtered stayed positive (+$3.8k).
live.py change: rsi2_entry requires close>200d SMA (fail-closed on NaN), compute() returns sma200, signal logs sma200, label updated. Artifacts: research/rsi2_sma200_compare.py + _results.json + _diag.py.

---

## 2026-08-16T13:50:49-04:00 — PREP MGC (micro gold) — make validated gold edge tradable at ~$900 via env config

- **Summary**: live_gc.py now env-drives the contract: GC_CONTRACT (default GC), GC_EXCHANGE (default COMEX), GC_POINT_VALUE (default 100.0; MGC -> 10.0). New pure seam resolve_contract_config() resolves (contract, exchange, point_value) from env/args; SYMBOL=GC_CONTRACT so DynamoDB tags (POSITION#/SIGNAL#/TRADE#), flatten, venue string, and front_month_for() all follow the contract. front_month_for(MGC) confirmed == 202608 (same COMEX metals Feb/Apr/Jun/Aug/Oct/Dec cycle as GC). Full GC stays the paper default; MGC is opt-in via GC_CONTRACT=MGC + GC_RISK_BUDGET=<real account>. No paper-config change, no orders placed, LIVE untouched. Tests: 6 added (MGC point value 10.0 vs GC 100.0, GC_POINT_VALUE env override, per-point realized_pnl scaling 1/10, stop-distance dollar risk ~$2.28k vs ~$22.8k). Full suite 171 passed.
- **Commits**: `04c0d8f`

---

## 2026-08-16T14:00:43-04:00 — Validate Connors RSI(2) stock mean-reversion for Robinhood lane (validation only, no live orders)

- **Summary**: Rigorous non-data-mined validation on fixed liquidity-ranked universe (top-50 S&P100 by avg dollar volume, yfinance split+div-adjusted 1962-2026). Honest fills: next-open entry, intraday-GTC 2xATR stop, 5-day time stop, revert exit; cost 0/5/10bps per side; walk-forward OOS with train-only threshold selection. RESULT: edge is REAL and cost-surviving — PF 1.54 full / 1.47 OOS at thr=2 (67.5% win, 2-day hold), 1.44 @5bps, 1.35 @10bps, OOS decay only -4.7%. Threshold selection stable (always thr=2, no data-mining). NOT a 2023-25 bull artifact (weakest in bears: 2008 PF 0.36, 2022 0.81) and NOT mega-cap concentrated (40/50 names PF>1). Trailing 1xATR ratchet FAILS vs fixed stop (PF 1.44->1.39, win 66->59%, stop-outs double). Drawdown-first caveats: worst trade -37.9% (BKNG 9/11 gap-through), 18-trade losing streak, compounded portfolio maxDD ~-58% to -69%. VERDICT: PROMOTE thr=2 + fixed stop as sized-down satellite w/ regime guard, NOT a capital-preservation core.
- **Commits**: `2bd2ea0`
- **Blockers**:
  - For capital-preservation directive: (1) bear-market decay (2008/2022 negative) -> evaluate index-level regime gate (SPX>SMA200) before entry, measure not assume; (2) gap-through tail risk -> cap position size $25-50/trade on ~$700.

---

## 2026-08-16T14:08:48-04:00 — SQS VPS→laptop channel + full system sweep (laptop-task)

- **Summary**: PASS — both workstreams complete. (A) Direct VPS→laptop channel: FIFO queue vps-to-laptop.fifo created (queue policy: VPS role SendMessage + account-root Receive/Delete; scoped inline IAM policy sqs-publish-vps-to-laptop). append_report() now mirrors every report to SQS (MessageDeduplicationId=sha256(ts|task)). infra/laptop_inbox.py = laptop long-poll (20s) subscriber, dedupe by message_id/MessageId, never crash-loops, plain venv loop. docs/COMMUNICATION.md covers schema/start/IAM + why SQS over IoT Core MQTT / API Gateway WS. Verified end-to-end: VPS publish → laptop_inbox --once received + deduped (2nd run=0 msgs). (B) Full sweep GREEN: tests 171 passed; systemd ibgateway/dashboard/tick-recorder/reconcile-daemon/reports active+enabled, backfill+watchdogs timer-driven (5 timers active); git pushed ahead=0/behind=0, author PCnslt; paper CONTROL=RUNNING, RECONCILE=MATCH (streak 0), gateway :4002 LISTENING, LIVE=false; risk_pct=0.01 + vol_target_pct=0.01 landed in bot/risk.py, bot/*.py py_compile clean; architecture diagram renders (assets/architecture.html via dashboard Architecture tab, HTTP 200).
- **Commits**: `01f4cbb`

---

## 2026-08-16T14:09:29-04:00 — Small-capital sweep + Robinhood RSI2 lane spec (research only, no orders)

- **Summary**: Wrote research/ROBINHOOD_LANE_PLAN.md (exact RSI(2)-dip fractional-share spec: top-50 S&P100 + 10 ETF universe, RSI(2)<5 + close>SMA200 entry, 2xATR hard stop + 5d cap + revert exit, trailing stop REJECTED, + Donchian(200d) ETF variant) and research/SMALL_CAPITAL_OPPORTUNITIES.md (drawdown-first ranking). New backtests this pass: RSI2 on 50 large-caps (OOS PF 1.47, all 5 folds >1.0, but single bear years 2008 PF 0.36 / 2022 0.81 -> satellite w/ index regime gate, NOT a core); gap fade PF 1.34->1.26 (dominated by RSI2); 5d momentum 1.20->1.07 (no-go); individual Donchian 1.18->1.04 (weak); pairs 1.29->1.14 (needs shorting, no-go); options credit spreads (synthetic BS, IV=realized) PF 1.04 breakeven with -87%-of-margin worst trade -> no-go unless a 15% vol premium exists on indices (data-gapped). Seasonal commodities confirmed PF 1.20/1.23 but needs full-size futures monthly overnight -> ~$5-10k IBKR post-deposit.
- **Commits**: `e629c0a` `ca3bbce`
- **Blockers**:
  - Options: no historical options bars in S3 (only futures chain metadata) -> cannot verify any credit-spread vol-premium edge; needs paid options archive.
  - RSI2 bear-market decay (2008/2022 negative): index-level SPX>SMA200 entry gate recommended but NOT yet validated.
  - Seasonal commodities: monthly overnight hold needs full-size futures margin (~$3-12k) or MGC ~$2k; violates $750 overnight cap at $500 IBKR -> post-deposit (~$5-10k).
  - Carry/term-structure: expired contracts = Error 200 on paper -> untestable without paid near/far archive.

---

## 2026-08-16T14:29:33-04:00 — BUILD: strategy portfolio registry (docs/STRATEGY_PORTFOLIO.md)

- **Summary**: docs/STRATEGY_PORTFOLIO.md created as the single living ADDITIVE registry (31 lanes, nothing removed). Status counts: LIVE-PAPER=3, LIVE-READY=1, PARKED-PENDING=1, NO-GO-WITH-REASON=21, RESEARCHING=5.

LIVE-PAPER (3): index Donchian+RSI2 (MES/MNQ, Gate 5 0/10), gold Donchian+TSMOM (GC/MGC, paper-EXEC), crypto Donchian-20+200d (BTC/ETH, signal-only).
LIVE-READY (1): RSI2 buy-the-dip (Robinhood equities, OOS PF 1.47) — blocked on 30-day paper-forward + SPX>SMA200 index regime gate.
PARKED-PENDING (1): seasonal commodities (IS 1.20/OOS 1.23) — blocked on funding IBKR to 5-10k for full-size futures margin.
NO-GO-WITH-REASON (21): 5d momentum, single-name Donchian, pairs/stat-arb (-> shorting enabled), options credit spreads (-> paid options archive), gap fade (redundant w/ RSI2), bonds fade-SHORT, BBAND_INDEX_LONG, CSP-CC wheel, carry, XSMOM futures, XSMOM equities L/S, value/5y reversal, vol overlay, ORB, MOM, DONCH15, FADESHORT, KAMA, 5-day reversal, golden cross, Bollinger lower-band.
RESEARCHING (5): intraday VWAP (HOLD), 200d MA trend, 12m XSMOM long-only, forex spot, futures-options scaffold.

Every NO-GO row records its reason + precise re-activation trigger. Registry updated in the same commit as every future sweep (binding maintenance rule).
- **Commits**: `1d16933`

---

## 2026-08-16T14:36:42-04:00 — BUILD: Robinhood equities RSI2 paper bot + index regime-gate validation

- **Summary**: Part 1 — index regime gate (SPY>SMA200) VALIDATED and REJECTED. Walk-forward OOS PF unchanged (1.47 -> 1.47 @0bps; 1.36 -> 1.35 @5bps) but net return -21% (1321 -> 1143 trades) AND bear-year decay NOT removed: 2022 PF WORSE 0.81 -> 0.21 (thr5) / 0.46 (thr2); 2020/2018/2025/2011 also worse; 2008 only 'fixed' by shrinking to ~0 trades. Gate is a lagging MA that keeps early-breakdown losers and filters bottoming winners. Deploy = per-name close>SMA200 only + satellite sizing + bear-year warning flag on every signal. Full report: research/REGIME_GATE_VALIDATION.md.

Part 2 — bot/live_equities.py (PAPER ONLY, execution=NONE, NO Robinhood creds on VPS). Universe = 10 ETFs + top-50 S&P100 (liquidity-ranked, refresh monthly). Entry RSI(2)<5 AND close>SMA200. Exit 2xATR intraday GTC stop / 5-day cap / revert (close>SMA5 | RSI2>70). Risk 1%/trade (5% capital cap), $150/day loss cap (paper = tracked + enforced on new entries). Simulated next-open fills + gap-aware stop + paper book + realized P&L.

LAPTOP READ-PATH (DynamoDB trading-data, us-east-1):
  RHSIG#<sym>/<date>         today's actionable signal (action=ENTER/EXIT; ENTER carries entry=next_open, stop_price, size_usd, rsi2, sma200, atr14, regime, bear_warning)
  RHPOS#<sym>/current        current paper position (PENDING/OPEN/CLOSED)
  RHTRADE#<sym>/<entry_date> round-trip history (forward-test P&L)
  RHLEDGER#<date>/summary    daily realized P&L + $150 loss-cap status
  S3 research/scan-results/rh-equities/<Y>/<m>/<d>/<ts>.json (daily snapshot)

Cron: Hermes job 'Paper signals - Robinhood equities RSI2' @ 20 23 * * * UTC (19:20 ET), script ~/.hermes/scripts/paper_rh_equities.sh, deliver=telegram.
- **Commits**: `1b498e5`

---

## 2026-08-16T15:12:59-04:00 — Build Robinhood broker client (hardening/rh_client.py) + LIVE execution mode in live_equities.py

- **Summary**: Built the VPS Robinhood trader. FILE PATHS: hardening/rh_client.py (the only submitter: SSM cred load, refresh_token rotation writeback, MCP transport, get_account/get_positions/get_quote/place_equity_order/place_stop/cancel_order/list_orders + fail-closed place_equity_entry), infra/rh_oauth.py (PKCE re-auth recovery), bot/live_equities.py (EXECUTION MODE, PAPER default), docs/ROBINHOOD_EXECUTION.md, tests/test_rh_client.py (10 tests), infra/secrets.py (fixed 10-name get_parameters chunking), hardening/__init__.py. GO-LIVE SWITCH: set BOTH RH_EXECUTION_MODE=LIVE AND RH_LIVE_ENABLED=true (both default OFF); at order time LIVE also requires agentic_allowed account + RISK_PCT <=0.01 + $150/day cap + protective stop (stop_price>0, never naked). NO live order placed; paper-forward unchanged. 181 tests pass. SSM READ CONFIRMED: IAM role reads all 11 /trading/robinhood/* SecureString params. TRANSPORT REALITY: these creds authenticate the Robinhood MCP gateway (agent.robinhood.com/mcp/trading), NOT the public REST API (which rejects this client_id).
- **Commits**: `77fbb1e`
- **Blockers**:
  - TOKEN DEAD — during validation the refresh_token was rotated and the rotated value was not persisted before exit; Robinhood revoked BOTH old tokens. Run infra/rh_oauth.py on the laptop (browser + Robinhood login) to re-authenticate.
  - Fractional positions (<1 whole share) cannot carry a Robinhood broker stop (stops are whole-share only) — place_equity_entry reverses them fail-closed, so the fractional RSI2 edge is NOT live-executable at $700; needs whole-share sizing or more capital.
  - CONCURRENT-AGENT COLLISION: another dispatch is building a parallel Robinhood client (bot/rh_client.py, infra/robinhood.py) + broker-access audit + IBKR live gateway. I left their untracked files untouched and did not stage them.

---

## 2026-08-16T15:29:36-04:00 — Broker accessibility audit + enable (Robinhood, IBKR paper/live)

- **Summary**: ACCESSIBILITY MATRIX (read-only, no live orders): Robinhood live = BLOCKED (SSM access_token revoked: MCP 401 token revoked; refresh_token grant = invalid_grant -> needs fresh OAuth browser+2FA on laptop). IBKR paper = OK (DUR193467 visible, 1M sim equity, futures MES/ES + equity AAPL + option SPY all qualify, whatIf accepted; equities market data DELAYED Error 10089, futures L1 live-when-open). IBKR live = BLOCKED (a) IBKR disallows 2 concurrent sessions per username (official TWS API), (b) live first-login requires IB Key 2FA; needs an ADDITIONAL username in Account Management + phone 2FA approval). ENABLED: SSM token refresh/persist path (PutParameter verified), Robinhood audit module + matrix builder + SQS publish (infra/robinhood.py, infra/broker_access_audit.py), live-gateway systemd unit + launcher + Jts-live settings (tradingMode=l). NOTE: a concurrent sibling task (commit 77fbb1e) built the Robinhood execution client (hardening/rh_client.py, bot/rh_client.py, infra/rh_oauth.py) and launched the live gateway instance in parallel; its live-gateway files are still uncommitted in-tree.
- **Commits**: `d33c22f`
- **Blockers**:
  - Robinhood: re-auth owner-gated (laptop browser OAuth + 2FA) — run infra/rh_oauth.py on laptop, or re-sync current laptop tokens to SSM /trading/robinhood/*.
  - IBKR live: owner creates ADDITIONAL username (Account Management) for U26949861, then first live login + IB Key 2FA.

---

## 2026-08-16T15:30:53-04:00 — Enable LIVE trading capability on BOTH brokers (IBKR + Robinhood) — paper stays default

- **Summary**: Wired LIVE on both brokers; PAPER remains the operating default. No live order placed.

IBKR: second live GWClient on DISPLAY=:100 + isolated settings dir /home/ubuntu/Jts-live (jts.ini tradingMode=l), relocated via -DjtsConfigDir override — VERIFIED: launcher.log logs settings dir /home/ubuntu/Jts-live, paper :4002 untouched throughout. systemd ibgateway-live.service is DISABLED. Live API port = 4001 default (paper = 4002). CRITICAL: login-screen Trading Mode dropdown DEFAULTS to Paper and is NOT driven by jts.ini (l and live both still show Paper) — must switch to Live Trading at first login, then verify managedAccounts()==['U26949861']. Full steps: docs/IBGATEWAY-LIVE-OPS.md.

Robinhood: canonical client = hardening/rh_client.py (commit 77fbb1e, 10 tests) wired into bot/live_equities.py. Live flags = RH_EXECUTION_MODE=LIVE AND RH_LIVE_ENABLED=true (both default OFF; RH_LIVE_ACCOUNT=515821577). SSM OAuth token is REVOKED (rotated refresh not persisted) -> laptop re-auth via infra/rh_oauth.py. docs/ROBINHOOD-LIVE.md.
- **Commits**: `a5656b7`
- **Blockers**:
  - USER: fund U26949861 (IBKR live) — gateway is wired but cannot trade until funded.
  - USER: enable live futures + options trading permissions AND CME L1 (real-time) market data on U26949861.
  - USER: IBKR live 2FA first login — approve IB Key push; switch Trading Mode to Live first, then verify managedAccounts()==['U26949861'].
  - USER: Robinhood re-auth — SSM /trading/robinhood/* token REVOKED; run infra/rh_oauth.py on the laptop to re-authenticate.

---

## 2026-08-16T18:42:16-04:00 — Robinhood single-writer token architecture + empirical fractional-stop check (defect fix)

- **Summary**: DCR client_id: LtLiNmbs...r8xW (full id in SSM, redacted here). NOTE: DCR returns a SINGLETON well-known client_id — Robinhood hosted MCP has ONE shared OAuth client; a separate per-process VPS client_id CANNOT be registered (verified by 2x DCR POSTs with different names/ports -> same client_id). Fix is therefore SINGLE-WRITER discipline, not credential separation: ONLY the VPS holds/rotates the live token; laptop MCP retired for trading (may only READ SSM to confirm).

OWNER RE-AUTH STEPS (token is currently REVOKED — MCP 401 "token revoked"):
  1. VPS:    python3 infra/rh_oauth.py --reauth
  2. Laptop: ssh -L 58245:127.0.0.1:58245 ubuntu@52.7.95.127
  3. Laptop browser: open the printed https://robinhood.com/oauth?... URL, log in + 2FA.
     The script catches the redirect on the VPS loopback and persists local-file-first then SSM.

FRACTIONAL-STOP VERIFICATION: BLOCKED. Helper check_fractional_stop() (review_equity_order simulate path, NO order placed) built + unit-tested (accept/reject paths), but the live check cannot run until re-auth. After re-auth run: python3 infra/rh_check_fractional_stop.py --symbol SPY. This settles whole-share-vs-fractional with data, not assumption.

Also: expires_at now stored as plain number string (was repr(float)); refresh() gained a race guard (no double-rotation when two threads race a 401). No live orders placed. Live IBKR gateway stayed DISABLED. Paper remains default. 184 tests pass.
- **Commits**: `b783a545850f83a944d21ee7e23f05d2680ae6b6`
- **Blockers**:
  - Robinhood token is REVOKED — owner must run infra/rh_oauth.py --reauth (browser consent) before the equities lane can read the account or the fractional-stop check can run.

---

## 2026-08-16T22:12:35-04:00 — Context alignment: small-capital live trading ENABLED via Robinhood whole-share small-ticket RSI2

- **Summary**: Capital is NOT a blocker. Robinhood acct 515821577 (agentic_allowed, ~$700) is the LIVE small-capital lane via whole-share small-ticket RSI2. Fixed a real transport bug: notifications/initialized was sent as an RPC (with id) and the MCP gateway rejected every call ("unexpected id"); now sent as a proper fire-and-forget notification (_McpTransport.notify). Read path verified live (get_account=515821577 agentic_allowed=true, get_quote SPY=776.31). Token fresh (re-authed 2026-08-16 21:58 ET). New docs/SMALL-CAPITAL-LIVE-PLAN.md: grounded whole-share sizing table (real 2026-08 closes+ATR14), 5-15 concurrent positions, $150/day cap mechanics, satellite(5%-cap)-vs-$150-ticket decision, and a new data-driven finding: the top-50 S&P100 universe has drifted almost entirely >$35 (SPY~$776), so $700 whole-share needs a small-ticket liquid sub-universe. No live orders placed (paper-forward first). Tests 13/13 green.
- **Commits**: `000dfba`
- **Blockers**:
  - Owner decision pending: keep 5%-cap satellite sizing (recommended) vs authorize >5% concentration to reach $100-150 tickets (see plan §4).
  - Build task (not blocker): add small-ticket liquid sub-universe ($5-35, 20d $vol) to live_equities.py universe.
  - Paper-forward >=30 days before flipping RH_EXECUTION_MODE=LIVE.

---

## 2026-08-16T22:31:00-04:00 — Robinhood small-capital alignment: memory note + $700 live plan + real balance

- **Summary**: Memory note saved (auto-load trading skills at session start; corrected vps-trading-operations -> trading-system-ops). Real RH balance via single-writer rh_client get_portfolio: buying power $675, cash $675, total $700.06, pending deposits $700, positions SPY 0.016 + QQQ 0.017 (DCA ~$25). Wrote docs/ROBINHOOD-LIVE-PLAN.md (whole-share sizing table, max concurrent = 20 hard ceiling / 5-15 recommended, worked F example w/ real ATR 2x=$0.89). PROJECT-STATE + STRATEGY_PORTFOLIO: RH RSI2 = ACTIVE LIVE-READY (enabled, not blocked); Gate 5 session 1/10 starts Mon 2026-08-17. FIXED infra/robinhood.py audit (MCP returns SSE-framed responses -> naive json.loads threw parse_error -> false BLOCKED; added notifications/initialized) + broker_access_audit render_table dict crash; accessibility matrix now shows Robinhood OK. No live orders placed.
- **Commits**: `b8e72d9`
- **Blockers**:
  - Owner decision pending: satellite (5% cap, recommended) vs concentrated ($10-150 tickets) - see plan §2
  - $700 pending deposit still settling - re-pull and re-size against actual buying power before first live order
  - Build small-ticket liquid sub-universe ($5-35, 20d $vol) - current universe drifted >$35
  - Paper-forward >=30 days before flipping RH_EXECUTION_MODE=LIVE

---

## 2026-08-17T13:40:24-04:00 — Dashboard overhaul — added Trading tab (candlestick charts + live bot logs)

- **Summary**: Rebuilt dashboard to show real day-trading, not just project progress. New "Trading" tab (first): (1) altair candlestick charts with the exact indicators the bots compute — intraday MES DONCH15 (20-bar Donchian channel) + FADESHORT (Bollinger 20/2 + RSI2), daily MES/MNQ (20d Donchian + 200d SMA + RSI2), GC (Donchian + 3-ATR chandelier ref); (2) live bot logs tailing each bot cron output; (3) live signal state per strategy. New modules dashboard/charts.py + logs.py + trading_view.py. Verified: py_compile OK, AppTest 0 exceptions, altair specs resolve, service restarted HTTP 200.
- **Commits**: `ae0f4c9`

---

## 2026-08-17T16:27:48-04:00 — Health check -> found + fixed critical reconciler scan-pagination bug (system had auto-paused)

- **Summary**: User asked how the system was doing. Ground-truth check found RECONCILE MISMATCH "unaccounted fills: MES" + CONTROL auto-PAUSED (fail-closed, correct). Broker was FLAT (0 positions, no capital at risk) but had one today-fill (SLD 1 MES @7798.75 = morning manual flatten of orphaned long). Root cause: reconciler _scan_positions/_internal_traded_today did a single table.scan() (one 1MB page) on a 2.3MB table, silently missing TRADE#/POSITION# rows on later pages -> false "unaccounted fills". Fixed with paginated _scan_prefix() helper (loops LastEvaluatedKey). 184 tests pass; reconcile flips MATCH (streak 0); CONTROL resumed RUNNING after restarting reconcile-daemon to load the fix. Also paginated the same bug in live_equities.load_book + status_report.report_positions. Commits 65430ee (reconciler) + 064b135 (live_equities/status_report).
- **Commits**: `65430ee`

---

## 2026-08-17T16:44:33-04:00 — Full codebase review: fixed rh_client fail-closed gaps + scan pagination (dashboard) + CFN drift

- **Summary**: Systematic defect review across hardening/ bot/ data_engine/ dashboard/ infra/. Already fixed this session: reconciler scan pagination (65430ee) + live_equities/status_report (064b135). New findings: (1) rh_client._flatten placed the emergency reversal with NO size (quantity=None, dollar_amount=None) -> would be rejected -> naked position; also a 1.x-share fill left the fraction unprotected. Fixed both (flatten requires size; any non-whole fill reversed). (2) dashboard app.py/pulse.py single-page scans (same pagination bug class) -> added _scan_all(). (3) session_calendar deprecated utcnow(). (4) CFN drift: cloudformation-stack.yaml SG GroupDescription mismatched live ("Trading system VPS") -> synced; recovery template profile name -> trading-vps-profile. 184 tests pass, AppTest 0 exceptions, dashboard HTTP 200. Commits d0187e4 03e6c3c 8cd20eb. Verified clean files: exec_manager, risk, risk_ledger, control, reconciler, rh_client token lifecycle, s3store (paginator), tick_recorder.
- **Commits**: `d0187e4`

---

## 2026-08-17T19:45:56-04:00 — Daily trading-system status summary (cron)

- **Summary**: Gateway active (4002 LISTEN). Positions: none (all flat). Intraday MES_FADESHORT + MES_DONCH15: signal=NONE pos=0, no trades today. Data: IBKR intraday bars ok (2026-08-17), equity ingest AAPL 2026-08-14 (weekend), crypto QUOTE#BTCUSDT ~25h old, reconcile MATCH. No IBKR login errors.

---

## 2026-08-17T22:18:57-04:00 — Execution mandate RETRY — forward-test all paper lanes (fix signal-only), RH micro-live prep, IBKR Gate 5 + $500 live option

- **Summary**: PART 1 — Forward test: 3 'signal-only' root causes found & fixed (no real-money orders).
(a) Equities RSI2 (live_equities.py): the simulated next-open fill was never persisted — a PENDING position filled in-memory only and stayed PENDING forever, so the round-trip journal RHTRADE# never got an entry (0 round trips ever). FIXED: persist OPEN on fill + fill only on a later bar. VERIFIED live: AVGO advanced PENDING->OPEN (entry 397.08, stop 363.84 = 2xATR); AMZN correctly stays PENDING (fills tomorrow).
(b) Gold (live_gc.py): fired LONG today (Donchian close 4467.7 > 20d-high 4445.0 AND TSMOM 12m +33.9%) but wrote NO fill — full GC ($100/pt) at 1% risk needs a ~$2.3M sleeve (3-ATR stop ~$23k/ctr) so size=0. FIXED: forward-test now on MGC micro ($10/pt, GC_CONTRACT=MGC, $250k sleeve) -> 1 contract (~$2.3k stop risk = 0.9%). Reconciler TRACKED_TAGS now includes MGC_DONCHIAN/MGC_TSMOM. MGC 202608 COMEX resolves (multiplier 10, verified).
(c) Index (live.py): flat today (no signal — healthy), but 1% risk @ $50k sleeve returned size=0 for EVERY MES/MNQ lane (MES Donchian 3-ATR ~$1.2k, MNQ 3-ATR ~$3.3k/ctr). FIXED: paper sleeve $50k->$350k -> MES Donchian 2 / RSI2 4 / MNQ 1 each (sizing math verified).
All 184 tests green (fixed one UTC-vs-ET date-literal flake in test_risk_ledger).

PART 2 — RH micro-live: 'tests fine' (>=1 clean simulated fill -> protective-exit -> P&L entry tonight, zero errors) = NOT met. Fill bug fixed + verified (AVGO fill correct), but no position completed a full round trip tonight (AVGO holding, AMZN pending — RSI2 dip-buyer is a rare-event strategy holding up to 5 days). Recommendation: DO NOT flip live tomorrow; continue paper-forward until >=1 clean round trip completes. Prepared (DRAFT, NOT activated): RH_EXECUTION_MODE=LIVE + RH_LIVE_ENABLED=true, $50-100 capital, 1-2 whole-share positions, hard protective stop on every entry, 1% risk, $150/day cap. First candidate symbols (sub-$35, 2xATR <= $7/share): F (~$14), AAL (~$15), T/KHC/PFE/WBD (~$25), KVUE/DOW (~$28-31), SNAP/NIO (~$5-10).

PART 3 — IBKR money:
(a) Gate 5 session 1/10 (2026-08-17): index flat (no signal), intraday flat; the one intraday halt ('unaccounted fills: MES') traces to the ~13:37 manual flatten of an orphaned long (documented 16:27 report; reconciler pagination fix 65430ee already resolved; RECONCILE=MATCH streak 0). 0 new execution defects. Actual simulated fill + P&L = NONE (no signal fired).
(b) $500 live option: M6E (micro EUR/USD) resolves on paper (12,500 EUR, $1.25/pip, multiplier verified) but 2-ATR stop = 100 pips = $125/contract = 25% of $500 -> REJECT (min position = 1 contract = 25% risk, cannot meet 1% rule; ~$300 margin is secondary). RECOMMEND whole-share equities RSI2 (same edge as the RH lane) on IBKR: 1 share of a sub-$35 name with 2xATR <= $7 meets 1% risk. Go-live: (1) build sub-universe, (2) review_equity_order simulate on a real $15 name, (3) paper-forward >=30d, (4) flip LIVE + reconcile vs get_positions.

No real-money orders placed tonight. All fills are IBKR-paper or simulated.
- **Commits**: `95e6a2a`
- **Blockers**:
  - RH 'tests fine' NOT met (no complete round trip tonight) — do NOT flip live tomorrow; continue paper-forward
  - $700 RH deposit still settling — re-pull buying power before first live order
  - Small-ticket liquid sub-universe ($5-35, 20d $vol >= ~$50M/day) still needs building (only T sub-$35 today)
  - Owner still must decide satellite (5% cap, recommended) vs concentrated ($10-150 tickets)
  - M6E margin ~$300 is approximate (verify exact at go-live); M6E rejected on risk regardless

---

## 2026-08-17T23:06:33-04:00 — Lane 10 (Intraday VWAP) + Lane 24 (KAMA) validation — intraday + 1/2/3-day swing horizon

- **Summary**: VALIDATION ONLY (no live/exec). Both verdicts NO-GO-WITH-REASON. LANE 10 VWAP 2-sigma: definitive sweep VWAP_K {1.5,2,2.5} x high-volume filter. Volume filter unlocks the EQUITY-INDEX sleeve (S&P/Nasdaq/Dow/Russell group OOS PF 1.11-1.38 @1t, stable across K), but Metals 0.94 / Energy 0.97 fail in every combo -> NO-GO cross-asset (the 4 'positive groups' are one correlated bet, not >=2 independent asset classes). Re-activate: deeper 1-min archive (24mo) + cross-source on the equity-index sleeve, then paper-forward MES/MNQ sleeve only. LANE 24 KAMA crossover daily re-test: at the owner's 2-3d hold horizon it is net-negative after costs (OOS PF 0.75-1.16 @5bps; <1.1 @10bps everywhere). Pure (untimed) crossover OOS 1.3-1.7 is a bull-regime buy-and-hold proxy (IS PF <1.0) with maxDD -12..-61% -> NO-GO confirmed, no realistic re-activation trigger. All outputs persisted to S3 research/ + research/LANE10_VWAP_SWEEP.md / LANE24_KAMA_DAILY.md.
- **Commits**: `dd31be3` `71a6047`
- **Blockers**:
  - Lane 10 re-activation: deeper 1-min archive + cross-source + paper-forward MES/MNQ equity-index sleeve only.
  - Lane 24: no realistic trigger (2-3d hold net-negative; untimed cross contradicts capital-preservation).

---

## 2026-08-18T00:46:12-04:00 — Order-flow/microstructure lane + VWAP equity-index sleeve (Lane 10 re-activation)

- **Summary**: Phases 1-4 built, serialized (git+S3+DynamoDB), 239 tests green. P1: VWAP sleeve re-activated (bot/live_vwap.py, MES/MNQ, VWAP_EXECUTION=PAPER real fills, VWAP_K=2.0 + high-volume filter, 2xATR native-bracket stop, round-trip journal, MES_VWAP/MNQ_VWAP in TRACKED_TAGS); 1-min backfill refreshed via --1m-only (30d entitlement cap - 24mo not achievable from any source). P2: orderbook collector (IBKR MES/MNQ L1-only [L2 Error 354 not entitled] + RH get_equity_price_book L2 for 15 small-ticket names) + tick_recorder kind tag (trade/quote). P3: footprint engine (bid-ask delta, absorption, volume profile POC/VAH/VAL, orderbook imbalance, spread) -> MICRO# rows. P4: Creamer auction generator (MNQ 5-min, first 90min NY open, 20k participation floor, multi-day 1h structure) -> AUCTION#, exec=NONE. VWAP paper fills: 0 (armed, first RTH session pending). Order-flow signals: 0 setups / 8 sessions.
- **Commits**: `cd3ddf1` `9da241b` `674d4c5` `dd29f07` `4d10195`
- **Blockers**:
  - IBKR paper has no L2 depth (Error 354) - MES/MNQ orderbook is L1 top-of-book only; L2 is a separate paid package.
  - 24-month 1-min archive NOT achievable (IBKR 1m ~30d, yf ~7d) - Lane 10 re-validation trigger (1) blocked on entitlement, not code.
  - Order-flow auction: 0 setups/8 sessions - golden-pocket-outside-value + price-in-pocket is rare; needs swing-selection tuning + orderbook data (needs-more-data, not a bug).

---

## 2026-08-18T00:50:42-04:00 — Repo hygiene/alignment: verify build session pushed, no leftovers, tests green

- **Summary**: Build session 20260818_041111 (delivery 1787026271420) ended 04:47:57 and had ALREADY committed+pusushed all order-flow work (VWAP sleeve, orderbook collector, footprint engine, KAMA/VWAP validation, auction signals). The 3 formerly-untracked files (bot/auction_signals.py, data/auction.py, tests/test_auction.py) are now tracked. No leftover artifacts to commit: HEAD==origin/main (0 unpushed), 0 untracked. Tests: 239 passed (>=210). Repo fully aligned.
- **Commits**: `252781c`

---

## 2026-08-18T02:09:45-04:00 — Operational: daemonize + start the 5 forward-test bots (systemd, PAPER-only)

- **Summary**: All 5 forward-test bots daemonized as systemd services (PAPER-only) and RUNNING.

is-active: live-index=active, live-gold=active, live-vwap=active, live-equities=active, orderbook-collector=active (NRestarts=0 all).

Running processes: 4x infra/bot_loop.py wrappers (live.py idx, live_gc.py, live_vwap.py, live_equities.py) + 1x bot/orderbook_collector.py. clientIds 70/78/79/80; live_equities has no IBKR clientId.

FRESH DATA (Aug 18 2026) landing — was stale since June 12: RUN#live, RUN#live_gc, RUN#live_equities, SIGNAL#MES_DONCHIAN/RSI2 + MNQ_DONCHIAN/RSI2 (all NONE=flat, healthy), SIGNAL#MGC_DONCHIAN + MGC_TSMOM (LONG), RHLEDGER#2026-08-18 (realized -\/usr/bin/bash.36, 1 exit) — all sk=2026-08-18. MAX ts=1787033185 = 2026-08-18T02:06:25-04:00 (today). RECONCILE=MATCH streak=0.

Bots failed to start: NONE.

Notes: (1) live_gc bootstrap run at 02:00 ET attempted MGC entry that timed out (thin overnight COMEX liquidity, exec-mgr 8s fill-confirm) -> fail-closed, no state written, account verified flat (no open orders/positions); signal still recorded. Normal 19:10 ET schedule going forward. (2) live_vwap + orderbook_collector are RTH-gated (09:30-16:00 ET) — running but write nothing until the open (expected, not a blocker). (3) 3 Hermes cron jobs paused (index futures, gold momentum, RH equities RSI2) to avoid double-fire; equity_signals, intraday MES, crypto + monitors stay on cron. (4) orderbook_collector RH_ENABLED=false (no Robinhood connection, per PAPER-only directive).
- **Commits**: `7bea50c`
- **Blockers**:
  - live_vwap + orderbook_collector will start writing at RTH open 09:30 ET (Aug 18) — verify ORDERBOOK#/VWAP SIGNAL# then. live_gc MGC entry timed out on the 02:00 bootstrap run; re-check at 19:10 ET that the fill confirms.

---

## 2026-08-18T13:44:30-04:00 — VPS daily: observability fix + RSI2/Donchian robustness + trading status

- **Summary**: TRADING: all PAPER, healthy. RECONCILE MATCH, CONTROL RUNNING, 9 services active, 239 tests pass. Broker flat: 0 positions, 0 trades today, $0 realized paper P&L (no strategy has completed a round-trip yet). Gate 5 = 2/10 sessions.

CODE + DEFECTS FIXED:
1. Schema migration (A): live_intraday.py date->ts, all 3 intraday writers now consistent (aa8fb5b).
2. Dashboard observability: new Data-health panel (SOURCE -> last-observed -> AGE -> STATE from ground truth, never assumed); marked 7 frozen data-lake jobs; fixed false news-active status + stale futures-ticks warning (c60dee5).
3. Documented authoritative daily-loss-limit: futures = 2% x sleeve, RH = flat $150 (139c52f).

RESEARCH (26y sample 2000-2026, honest fills):
4. RSI2-long: PF 1.92 but left-tail (skew -0.89, payoff 0.80); 2018 = PF 0.33 is the maxDD source; no stop -> -$30k worst MAE. Robust to 5-tick slippage + 1-2 bar late fills (d95267d).
5. Donchian-long: PF 1.34 ES / 1.56 NQ, bounded tail (2xATR stop), regime-dependent (11 losing years); 2xATR suboptimal (4xATR = 1.59) (18d3aa5).
6. KEY: RSI2 + Donchian are independent (corr -0.001) and complementary (RSI2 wins 2008, Donchian wins 2018). Combined 1+1 portfolio PF 1.66, maxDD -$33.9k (21% better than RSI2 alone), eliminates all losing years except 2007 and 2018.

FACT-CHECK CORRECTIONS: news sentiment PAUSED (frozen 08-16, not active); 4 systemd bots not 6; live_intraday.py NOT redundant (retracted) — still sole FADESHORT/DONCH15 producer; crypto scheduler healthy (fires every 30m).

NO strategy-logic changes — research + display + docs only.
- **Commits**: `aa8fb5b` `c60dee5` `139c52f` `d95267d` `18d3aa5`
- **Blockers**:
  - No blockers — paper trading healthy; Gate 5 only 2/10, no live track record yet
  - Next candidates: gold (MGC) robustness pass, then IAM least-privilege migration (pre-live)

---

## 2026-08-18T16:43:41-04:00 — Crypto paper-execution built + futures off-hours fix + live-readiness audit

- **Summary**: Enabled 24/7 crypto paper-EXECUTION (was signal-only). New bot/crypto_exec.py runs every 30 min (Hermes cron b3e62651e8fc): Donchian-20+200d-SMA long-only BTC/ETH, simulated fills (5bps slip + 10bps taker fee) + paper P&L ledger (POSITION#/TRADE#/RISK#). PAPER only, no Binance account.

Fixed futures off-hours bug: infra/bot_loop.py --daily bots no longer fire immediately on off-hours restart (gold had fired spurious UNKNOWN entries at 02:07 ET deploy-time). Now sleep to scheduled time unless within a 10-min catch-up window. Restarted live-index/gold/equities — verified "off-schedule start, sleeping to 19:00/19:10/19:20".

LIVE-READINESS BLOCKERS (owner-gated, remaining):
1. Gate 5 = 1/10 RTH sessions (session 2 in flight today).
2. IBKR live $500 < MES/MGC/MNQ margins (~$1.3k-2k) — needs funding + 2FA on first login.
3. RH Agentic flags OFF (RH_EXECUTION_MODE=PAPER, RH_LIVE_ENABLED=false) — RH lane needs paper-forward >=30 days before live.

Commit: c2a7a8a.
- **Commits**: `c2a7a8a`
- **Blockers**:
  - Crypto now paper-trades 24/7 but has NO validated edge (buy-and-hold proxy) — building a track record, not expecting profit
  - To go live: fund IBKR live >= $1.5k + owner 2FA; keep RH flags OFF until Gate 5 + 30-day RH paper-forward complete

---

## 2026-08-18T18:52:46-04:00 — Crypto lane upgraded to best option (pure momentum) after web+internal research

- **Summary**: Researched best crypto strategy (web + internal sweep). Finding: momentum/trend-following is the ONLY crypto family that survives realistic cost (mean-reversion dies), and the real edge is concentrated in ALTS (SOL 2.30 / XRP 3.23 / ADA 1.57 OOS PF), NOT BTC/ETH (1.17 / 1.35). The prior Donch200 "2.35 PF" was a buy-and-hold proxy — its 200d-SMA filter = "long during every bull".

Updated crypto paper-execution (b9febc8): dropped the 200d-SMA crutch, now pure Donchian-20 channel momentum (entry close > 20d-high, exit close < 20d-low or 2xATR stop), universe expanded to BTC/ETH/SOL/XRP. SOL/XRP are forward-collecting candles (~4 days) and auto-start signaling once they reach 20+ bars. BTC/ETH trade now.

Honest caveat: even the best crypto momentum is marginal on BTC/ETH — the lane builds a track record, not expected profit.
- **Commits**: `b9febc8`
- **Blockers**:
  - SOL/XRP momentum needs ~20 more days of forward-collected candles before they can signal
  - No validated crypto edge on BTC/ETH (momentum PF 1.17, marginal) — keep crypto LOWEST live-priority

---

## 2026-08-18T20:11:23-04:00 — Staleness defect fixed + Gate-5-acceleration directive triaged

- **Summary**: FIXED the staleness defect (root cause + code + state):
- Root cause: daily bots called mark_ran_today() at run START, so the 02:02 ET deploy-time run stamped RUN# with stale intraday data and the 19:00 EOD run was skipped. 
- Fix: bot/control.py data_finalized() guard (ET >= 17:00 = close finalized); live.py/live_gc.py/live_equities.py now skip before 17:00 ET (no RUN#, no signal). Defense-in-depth on top of the earlier bot_loop off-hours fix. Commit 5277bc7.
- Cleared today stale RUN# + 8 stale 02:xx daily signals.

TRIAGED the Gate-5-acceleration directive (took inspiration, did NOT blindly follow):
- DONE: crypto spec drift (STRATEGY_PORTFOLIO.md Donch200 -> MOM20) + scripts/verify_all_backtests.py (reproduces IS/OOS PF + verdicts from committed result JSONs).
- SUPPORT: event-driven Gate 5 (error-free cycles, not calendar days) + Gate 5A infra / 5B alpha split.
- PUSH BACK: "fast-track to micro-live" bypasses the plumbing proof — contradicts the capital-preservation directive. Keep paper for plumbing; micro-live is the execution-quality test (Gate 7), already planned.
- ALREADY EXISTS (just different thresholds): daily loss cap, consec-loss brake (6, could tighten to 4), data-staleness guard (120s, could tighten to 15s for API).
- **Commits**: `5277bc7`
- **Blockers**:
  - Forward-test still 0 completed round-trips; first clean EOD run is tomorrow 19:00 ET
  - Gate 5 reframe decision is the owners call — event-driven vs 10-day, do not rush to live

---

## 2026-08-19T09:26:23-04:00 — Gateway recovery + auto-recovery watchdog + cron cleanup (15→9 jobs)

- **Summary**: Session 2026-08-19 (VPS ops) — gateway recovery, auto-recovery watchdog, cron cleanup.

1. GATEWAY OUTAGE RECOVERED — IBKR paper gateway hung on its midnight daily auto-restart (login screen, port 4002 down 00:00→04:55 ET). OCR-verified PAPER mode, re-ran ibgateway-login.sh, confirmed DUR193467 (NetLiq $1.0M), reconcile back to MATCH.

2. AUTO-RECOVERY WATCHDOG — enhanced infra/ibgateway-hang-watchdog.sh with a new rung: after a restart fails to restore 4002, fire the login helper DETACHED (systemd-run as ubuntu), OCR-guarded to confirm the SIMULATED TRADING banner before typing creds (structurally cannot reach live U26949861). Paper needs no 2FA, so the daily-restart hang now self-heals in ~10 min (was ~5h manual). Commit 2400f28.

3. CRON CLEANUP (15→9 jobs) — removed 6 dead jobs: index/gold/RH-equities (exact systemd duplicates of live-index/live-gold/live-equities), bonds (live_bondsfx.py shelved/disarmed), IBGW one-shot (done), crypto Donch200 (superseded). KEPT equity_signals.py cron (broad research scanner, distinct from live_equities.py execution lane). Commit aa4424c.

4. CRYPTO DONCH200 RETIRED — crypto_paper.py (Donch200 signal-only) was superseded by crypto_exec.py (MOM20) in b9febc8 but its cron kept writing stale SIGNAL#*_DONCH200. Removed cron+script; kept crypto_paper.py as helper module (crypto_exec.py imports live_price/load_yf/merge_live/wilder_atr). Verified import intact. Commit 6bb6162.

5. DASHBOARD + DOCS SYNC — schedule table now shows systemd daily bots (was 'Hermes cron'), added live_equities 19:20 row, GC→MGC label, removed stale script labels in logs.py, corrected RECOVERY.md cron table.

6. SKILLS UPDATED — ibkr-gateway-operations (auto-login rung documented), trading-system-ops (new pitfall: retire superseded lanes in the same commit).

TRADING STATUS: flat, $0 P&L, 0 paper trades today (TRADE# today=0, POSITION# 0). Gate 5 still 2/10 RTH sessions, $0 realized round-trips. RTH session opened 09:30 ET today; first clean EOD run tonight 19:00 ET (after yesterday's staleness fix).

BLOCKERS (unchanged): IBKR live U26949861 $500 below MES/MGC/MNQ margin (needs ~$1.5k+ funding + 2FA); Robinhood live flags off; Gate 5 time-based (2/10 sessions).
- **Commits**: `2400f28` `aa4424c` `6bb6162`

---

## 2026-08-19T11:27:38-04:00 — Fix: reconciler crashed on fractional crypto positions (first MOM20 paper trades)

- **Summary**: Bug fix: reconciler crashed on fractional crypto positions (first crypto paper trades exposed it).

WHAT HAPPENED — crypto_exec.py (MOM20) entered its FIRST paper trades at ~11:00 ET today on the up-move: BTCUSDT_MOM20 LONG 0.039992 @ $65,994 (stop $63,494) + ETHUSDT_MOM20 LONG 1.094102 @ $1,972 (stop $1,881). It wrote POSITION# rows with FRACTIONAL 'pos' (crypto is fractional, futures are integer).

THE BUG — the reconciler's _scan_positions() did int('0.039992') on EVERY POSITION# row -> ValueError -> whole reconcile returned UNKNOWN -> health monitor alerted "RECONCILE UNKNOWN: invalid literal for int()".

THE FIX — filter _scan_positions() to TRACKED_TAGS (futures only; crypto is simulated with no IBKR broker counterpart, so it must be ignored). Also float() in status_report.py + dashboard/app.py, fractional rendering in pulse.py. Regression test added.

VERIFIED — 240 tests pass (was 239), RECONCILE back to MATCH, reconcile-daemon restarted. Commit 3453aba.

CURRENT STATUS — first forward-test activity: 2 crypto paper positions OPEN (BTC + ETH MOM20). Futures flat. Control RUNNING, gateway up.
- **Commits**: `3453aba`

---

## 2026-08-19T12:05:17-04:00 — Trailing-stop study: crypto MOM20 -> chandelier; data says trailing helps trend, hurts mean-rev/TSMOM

- **Summary**: Trailing-stop study complete — data-driven verdict per strategy family.

APPLIED: crypto MOM20 upgraded from fixed 2xATR stop to chandelier 3xATR trailing stop (best price since entry - 3*ATR, ratchets up only, persisted each 30-min cycle). Existing BTC/ETH paper positions auto-upgraded (BTC stop 63494->64387, ETH 1881->1929). Commit 9cb9ee8.

BACKTEST VERDICT (26y ES/NQ/YM from trailing_stop_results.json + new TSMOM test):
- Donchian (trend): chandelier 3xATR HELPS — ES PF 1.47->1.68 + maxDD -21k->-19k; NQ PF 1.69->1.77 + maxDD -42k->-32k. (YM exception: chandelier hurt.) Already applied to index/gold.
- RSI2 (mean-reversion): trailing HURTS — 2xATR trail collapses win% 69%->47%, maxDD -22k->-28k (ES). KEEP fixed 2xATR.
- TSMOM (12m momentum, gold): chandelier DESTROYS it — PF 1.81->0.60, net +$75k->-$33k. KEEP fixed 3xATR floor. Commit 5ff4b40.
- Intraday VWAP/FADE/DONCH15: keep 2xATR + EOD flatten (no overnight hold).

RULE going forward: trend-following = chandelier 3xATR trail; mean-reversion/momentum-flip = fixed stop + signal exit. 240 tests pass.
- **Commits**: `9cb9ee8` `5ff4b40`

---

## 2026-08-19T12:35:27-04:00 — Adaptive-stop engine built + backtested; applied RSI2 breakeven-lock (the one clear win)

- **Summary**: Adaptive-stop engine built, backtested, and the one clear win applied.

PHASE C — bot/adaptive_stop.py: shared regime-adaptive stop engine. Three signals per bar: volatility-regime ratio (VR = ATR/100d-median), Kaufman efficiency ratio (ER = trend vs noise), and staged profit-lock (breakeven -> trail -> Parabolic acceleration). Edge-type router: trend=adaptive-trail, meanrev=breakeven-lock ONLY (no trail), momentum=volatility-scaling.

PHASE A — research/adaptive_stop_study.py: 26y ES/NQ + gold + BTC/ETH, fixed vs chandelier vs adaptive, drawdown-first. Honest fills (gap-aware stops, slippage, fee). Results:
- RSI2 (mean-rev): adaptive/breakeven WINS — ES PF 1.63->1.72 + maxDD -33k->-25k; NQ PF 1.45->1.54. (The 'intelligent' fix for mean-rev is a breakeven LOCK, not a trail.)
- Donchian (trend): chandelier still best — adaptive over-tightens ES (PF 1.57->1.46). KEEP chandelier.
- TSMOM (12m momentum): ALL stops negative since 2010 (adaptive worst, PF 0.47). KEEP fixed 3xATR floor. NOTE: TSMOM-on-gold is a losing strategy post-2010.
- Crypto MOM20: adaptive helps BTC (PF 1.00->1.12, DD -20.7k->-17.8k), neutral ETH. Keep chandelier (already applied).

PHASE B — applied the one clear win: RSI2 breakeven-lock in live.py (rsi2_trail: raise stop to entry once +1*ATR in profit, ratchet-only). Donchian keeps chandelier, TSMOM keeps fixed, crypto keeps chandelier — data says adaptive doesn't beat them there.

240 tests pass. Commits: 9cb9ee8 (crypto chandelier), 5ff4b40 (TSMOM test), 5519d9c (engine + backtest + RSI2 apply).
- **Commits**: `5519d9c`

---

## 2026-08-19T12:55:33-04:00 — Non-blocking full-system defect sweep + fixes + full trading report

- **Summary**: FULL NON-BLOCKING SWEEP (nothing restarted, trading never halted). HEALTHY: 12/12 systemd units active (ibgateway-live DISABLED by design); gateway 4002 UP + reconcile MATCH (fix holding since 11:25); 240 tests pass; compile clean; CONTROL=RUNNING flatten=false. DATA CURRENT: daily bars->08-18, intraday 5min/15min->08-19, ticks live (QUOTE# fresh 12:51 ET), 9 cron jobs all ok, no systemd/Hermes double-fire. POSITIONS: BTCUSDT_MOM20 LONG 0.039992 @65994 (stop 64526, chandelier peak 68828) + ETHUSDT_MOM20 LONG 1.094102 @1972 (stop 1935.58, peak 2098) both in profit vs entry; futures flat; $0 realized. DEFECTS: (1) FIXED f654811 control_probe.py bare scan() dropped page-2+ rows (missed ETH). (2) DOCUMENTED-ONLY: 08-18 EOD was poisoned by the 02:02 ET off-hours deploy (pre-fix code stamped RUN# -> 19:00 EOD runs skipped by dedupe guard; gold fired 2 ENTRY-UNKNOWN off-hours). Already fixed by 5277bc7 (data_finalized guard + catch-up window + mark-ran-after-eval, verified in live.py/live_gc.py/live_equities.py); 08-18 data now stale, not re-runnable. FALSE ALARMS CAUGHT: tick-recorder '48h gap' was my own single-page S3 list bug (recorder healthy); 1m/1h bar 'gap' = backfill barsizes (live intraday uses 5min/15min, current). S3 list_objects_v2 single-page pitfall added to trading-system-ops skill.
- **Commits**: `f654811`

---

## 2026-08-19T13:00:27-04:00 — 08-18 EOD deep-dive + advance Gate-5 milestone

- **Summary**: RECONSTRUCTED 08-18 (deterministic replay of live.py compute() on finalized yfinance close): the lost EOD day had a REAL RSI(2)<10 buy-the-dip LONG on BOTH MES and MNQ (ES close 7714.0 RSI2 9.8 > SMA200 7110; NQ 29586.0 RSI2 9.8). The 02:02 off-hours run had read a PARTIAL Globex bar (close 7737.5 / RSI2 13.4) -> classified flat, then 19:00 EOD was dedupe-skipped. Net: 1 RSI2 LONG entry (2 contracts) lost to the operational bug (already fixed 5277bc7). NOT backfilled (would falsify forward-test). GATE5: 08-18 recorded as VOIDED session (data-integrity defect, not execution defect); counter = 1 valid/10. Session 2 = tonight 08-19, armed clean (no stale RUN# marker, fix live). HEADS-UP: MNQ forming 08-19 bar still RSI2 9.8 (dip live) -> tonight may fire MNQ RSI2 LONG if NQ stays weak through 16:00 close; ES already bounced (RSI2 44). docs/GATE5_LOG.md updated with reconstruction table.
- **Commits**: `34a5c38`

---

## 2026-08-19T13:40:31-04:00 — Double-effort: make missed/failed signals structurally impossible across markets

- **Summary**: AUDIT of every lane for the 'miss a signal' failure class. FIXED 3 things: (1) live.py + live_gc.py STILL had mark_ran_today BEFORE the data fetch+eval (only live_equities was correct) — extracted a pure evaluate_signal() (no IBKR) that logs SIGNAL# for every strategy, moved mark_ran AFTER it, so a crash before eval leaves no RUN# marker and a same-day retry re-evaluates (the 08-18 class now impossible). (2) BUILT infra/missed_signal_check.py — post-EOD deterministic replay of the finalized close vs logged SIGNAL# for index (Donchian+RSI2) + gold (Donchian+TSMOM); alerts on missed/spurious/missing. Validated: reproduces the 08-18 RSI2 LONG exactly. Cron 23:35 UTC Mon-Fri no_agent->Telegram (job 35c8fac5d2bc). (3) FOUND+fixed a latent landmine: infra/secrets.py shadowed stdlib secrets, breaking 'import numpy.random' (ImportError: cannot import name randbits -> also breaks pandas) for any script run as 'python infra/x.py'. Renamed to infra/ssm_secrets.py + updated 42 importers + 2 repo + 2 deployed ibgateway*.sh. Bots were unaffected (they namespace it). 240 tests pass, compile clean, detector runs silent (healthy). crypto/vwap/intraday lanes are state-based/re-RTH so no mark_ran risk. Skills patched (shadow severity + mark-after-eval).
- **Commits**: `d7ec6d8` `44eb3cb` `f654811`

---

## 2026-08-19T18:38:39-04:00 — Deploy RSI2PT A/B take-profit variant + sync all docs/diagram/CFN + defect check

- **Summary**: Implemented the evidence-backed 'take profits frequently' move as an A/B variant. live.py: new RSI2PT strategy (same RSI2<10 entry, exits at a broker-side +0.5% limit target via the native bracket the exec_mgr already supported) running alongside RSI2 (RSI2>70/5d exit) to forward-test which exit wins. Added _last_fill_price() so an intraday target fill is attributed at the TARGET price (not mis-recorded as a stop fill). reconciler TRACKED_TAGS + VWAP OTHER_BOT_TAGS updated with MES/MNQ_RSI2PT. Synced: assets/architecture.html (RSI2PT + MGC + crypto_exec fixes), dashboard/app.py (schedule + ASCII diagram), docs/STRATEGY_PORTFOLIO.md lane 2, docs/PROJECT-STATE.md. CloudFormation: NO change (RSI2PT is a strategy tag, not a new resource — verified no strategy refs in the stack). DEFECT CHECK: 240 tests pass, all changed files compile, manual verification of STRATEGIES wiring + _last_fill_price attribution + reconciler/VWAP tags all pass. Research basis: 26y RSI2PT = 89% win PF 1.92 (vs baseline 72%/1.83, mixed DD); OR-fade + time-of-day seasonality FAIL honest costs (intraday premium is MR, per Lou-Polk-Skouras).
- **Commits**: `2c8e141`

---

## 2026-08-19T19:48:13-04:00 — Daily status summary (cron)

- **Summary**: Gateway active (port 4002 LISTENING); reconcile MATCH (0m ago); IBKR intraday bars archived today; no login errors. Intraday flat (MES FADESHORT/DONCH15 signal=NONE, pos=0). Index/gold futures flat. 2 crypto MOM20 paper positions (simulated): ETH LONG 1.094 @ 1972 (trail stop 2087, peak 2284, locked profit), BTC LONG 0.040 @ 65994 (stop 65406, ~flat).

---

## 2026-08-19T20:07:03-04:00 — Short-horizon edge build+validate, then deploy REV2 reversal lane

- **Summary**: Built+validated the 2-3 day short-horizon candidates (next-action #3). Donchian 2/3/5d short-lookback = NO-GO (breakeven long-only, losing long-short; confirms overnight-vs-intraday momentum). 2-day reversal LONG-only = PROMOTE (ES/NQ/YM PF 1.54/1.62/1.26 @1t, OOS 1.19-1.70, win 71-76%, hold 3.4d, survives 3-tick, corr vs RSI2 +0.07-0.14 = independent). Deployed REV2 into live.py as a 4th index lane (2d drop >1xATR entry, 2xATR stop, revert/3d exit); exit interface now passes entry_px; reconciler TRACKED_TAGS + VWAP OTHER_BOT_TAGS updated; docs/diagram/dashboard synced. 240 tests pass, compile clean, manual dry-run verified. Picks up automatically next 19:00 ET run.
- **Commits**: `REV2 lane commit (live.py + cross-cutting sync)`
- **Blockers**:
  - forward-test REV2 on MES/MNQ paper alongside RSI2; watch grind-regime years (2001-02/2012/2018/2022)

---

## 2026-08-20T19:47:02-04:00 — Daily trading-system status summary (cron)

- **Summary**: IB Gateway active (port 4002 listening). OPEN PAPER POSITIONS: 2 crypto MOM20 longs only (BTC 0.039992 @ 65994.42, ETH 1.094102 @ 1972.19) — no futures/index positions open. INTRADAY: MES_FADESHORT NONE, MES_DONCH15 SHORT @ 7667.5 but pos=0 (flat, signal logged no fill), last tick ~4h ago. DATA HEALTH: IBKR intraday bars ok (2026-08-20), broker reconcile ok 0m ago; equity OHLCV#AAPL 4d stale + crypto QUOTE#BTCUSDT 4d (both frozen/cosmetic). IBKR login errors: none.

---

## 2026-08-21T09:08:47-04:00 — DCA STOP + RH live/intraday status

- **Summary**: Owner directive: no set-and-hold, wants more intraday. (1) Removed dormant bot/dca.py (plan-only, never scheduled, no order placement) — commit 479a9b9. (2) ACTION FOR LAPTOP: STOP the weekly $25 SPY/QQQ fractional DCA buy (it's laptop-side; VPS has no such execution). (3) RH live (~$700) runs RSI2 buy-the-dip only; no live fills yet (first live run 19:20 ET tonight). (4) Cleared 6 stale paper RHPOS# positions that would have blocked the first live run. (5) Reconciler MISMATCH (my GTC-test fills) resolved → MATCH, CONTROL RUNNING.
- **Commits**: `479a9b9`
- **Blockers**:
  - LAPTOP: stop weekly $25 SPY/QQQ DCA. IBKR live U26949861 unfunded (MES margin ~$1.3k) — needed before VWAP futures can go live.

---

## 2026-08-21T19:46:12-04:00 — Daily trading-system status summary

- **Summary**: Gateway active (port 4002 listening); open paper positions: BTCUSDT_MOM20 LONG 0.039992, ETHUSDT_MOM20 LONG 1.094102 (crypto simulated); intraday MES FADESHORT/DONCH15 both signal=NONE pos=0 (no trades today); data health: IBKR intraday bars ok (08-21), reconcile MATCH, equity OHLCV# + crypto ticker stale 5d (frozen lanes, cosmetic); IBKR login log clean.

---

## 2026-08-22T19:48:06-04:00 — Daily trading-system status summary (cron)

- **Summary**: IB Gateway (paper) service active but API port 4002 NOT listening — soft-token re-auth failed after 00:06 restart, stuck at login; reconcile-daemon cannot connect (Errno 111). Open paper positions: crypto MOM20 only (BTCUSDT LONG 0.04 @ 65994, ETHUSDT LONG 1.094 @ 1972); no futures positions. Intraday MES_FADESHORT/MES_DONCH15 signal=NONE pos=0 (Fri close, ~28h). Data: IBKR intraday bars ok (last 08-21); equity ingest stale (AAPL 08-14); crypto ticker QUOTE#BTCUSDT stale ~6d. No login errors in logs (IBC retired, native launcher).
- **Blockers**:
  - Paper IB Gateway stuck at login (port 4002 down since 00:06 Sat) — needs Sunday 2FA re-auth; equity/crypto ingest ~6d stale.

---

## 2026-08-24T12:12:45-04:00 — Robinhood leverage + crypto fractional trading (RH + IBKR) — owner 'do all'

- **Summary**: 1) RH research lane LIVE: earnings calendar + screener presets → DynamoDB RESEARCH#/S3, cron 17:15 ET. 2) RH Crypto API client built (Ed25519 signing, fractional + XRP + native stop_loss), fail-closed pending owner keys. 3) IBKR crypto lane built (MOM20 fractional cashQty, software chandelier stop) + reconciler CRYPTO exclusion — DORMANT: PAXOS crypto is live-only, paper orders don't fill. 4) XRP added to blue-chip universe (BTC/ETH/XRP). 253 tests pass.
- **Commits**: `d94f0c6` `7c300d2` `ec02623` `b99cc53`
- **Blockers**:
  - RH crypto: owner create API key + Ed25519 keypair at robinhood.com/account/crypto, store in SSM /trading/robinhood-crypto/*
  - IBKR crypto: needs LIVE account (U26949861) funded + crypto trading enabled — PAXOS paper does not fill

---

## 2026-08-24T17:06:51-04:00 — Build persistent autonomous bots: trade-info, research, backtesting, strategy-research (run constantly/in parallel)

- **Summary**: Built 4 autonomous Hermes cron jobs running in parallel: (1) Trade & position watch — event-driven via infra/trade_watch_state.py byte-stable fingerprint (monitor_script), LLM fires ONLY on state change (new trade/position/reconcile/service flip) every 10min, read-only; (2) Market research & trade info — LLM 3x/day (09:00/12:00/16:00 ET) reads live book + regime/news/catalysts; (3) Backtest queue worker — LLM 2x/day pops ~/.hermes/state/backtest_queue.json, honest backtests, additive STRATEGY_PORTFOLIO lanes, commits; (4) Strategy research — LLM daily literature scan feeding the queue. Queue seeded with 2 confirmed-but-unbuilt ideas (spot-VIX level contrarian z>=2 +0.78%/5d; overnight MOC close-entry +10.7bp/trade). All deliver to Telegram. Also audited gaps: collectors/reconciler/watchdogs already 24/7 via systemd+cron.
- **Commits**: `66c0b5b`
- **Blockers**:
  - Hit + diagnosed a Hermes cron lifecycle-guard false positive (parenthesized ~/trading-system path → blocked job creation); fixed prompts, recorded pitfall in trading-bot-operations skill. All 4 jobs created green.
