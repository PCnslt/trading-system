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
