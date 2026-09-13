# RESTART — how to bring this system back up

For a fresh agent/bot (or a human) resuming this repo after the VPS was taken down.

## TL;DR

This is a 24/7 multi-market trading system (futures → equities → options → crypto)
orchestrated by Hermes on an AWS VPS. **All CODE is in this repo. All SECRETS are in
AWS SSM. All DATA is in S3 + DynamoDB.** Those last two live in AWS, not in git —
recover them by pointing a machine with AWS access at the same account.

## Current honest state (2026-09-10)

- **No live trades; capital 100% cash.** Zero deployable edges at the current
  configuration (~$1.8k agent-tradeable, L2 cash, sub-$50, long-only).
- **~55 strategies tested and falsified** (directional, momentum, mean-reversion,
  arbitrage, crypto, options, macro, fundamental). See `research/RESEARCH_VERDICT_LEDGER.md`.
- **The one statistically-real edge** = index VRP (SPY bull-put spread, t=13.9 vs
  placebo) — but it's L3 + margin gated, and the owner can apply for L3 **March 2027**.
- **Crypto directional is closed** (momentum + reversal both proven survivorship/lookahead
  artifacts). Real crypto edges (funding rate / basis / vol) need derivatives = blocked.
- What's still *alive* is the **data pipeline** (pre-market bars, order-book/OBI,
  crypto klines) — forward-only data that can't be fooled by hindsight.

## Bring-up steps

```bash
# 1. clone
git clone git@github.com:PCnslt/trading-system.git
cd trading-system

# 2. Python 3.11 venv (3.13 breaks native numpy) + deps
python3.11 -m venv venv
./venv/bin/pip install -r requirements.txt

# 3. AWS access (secrets + data lake live here)
#    Option A: attach an IAM instance role (ssm:GetParameter, s3:*, dynamodb:*)
#    Option B: export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION=us-east-1

# 4. verify secrets resolve (SSM-first, .env is only a fallback cache)
./venv/bin/python infra/ssm_secrets.py        # prints <SET>/<EMPTY> per param
```

## What's NOT in this repo (and where it lives)

| Thing | Location |
|---|---|
| Secrets (RH OAuth, IBKR login, Binance.US keys, API keys) | AWS SSM Parameter Store `/trading/*` (SecureString) |
| `.env` fallback cache | VPS only, gitignored (`.env.example` is the committed template) |
| Market data | S3 `trading-datalake-920641308584` + DynamoDB `trading-data` (us-east-1) |
| IB Gateway login creds | SSM `/trading/ibkr/*`, fallback `~/ibgateway-creds.env` |

SSM paths → env-var mapping is explicit in `infra/ssm_secrets.py::PARAM_TO_ENV`.
Never hardcode a secret in the repo; never commit `.env`.

## Brokers

- **IBKR**: gateway at `127.0.0.1`, live port 4001, paper 4002. Soft-token auto-relogin;
  throttles → `sudo systemctl restart ibgateway-live`. Ops: `docs/IBGATEWAY-LIVE-OPS.md`.
- **Robinhood**: hosted MCP + SSM OAuth. **Single-writer token discipline** — only this
  VPS rotates the token; re-auth via `infra/rh_oauth.py --reauth`. Live client gated
  behind `RH_EXECUTION_MODE=LIVE` + `RH_LIVE_ENABLED=true`. Ops: `docs/ROBINHOOD-LIVE.md`.
- **Binance.US**: REST API, key+secret in SSM `/trading/binance_us/*`. Data only.

## Entry points (cron/scheduler)

Orchestration is Hermes cron jobs (`hermes cron list`). Key script wrappers live in
`~/.hermes/scripts/*.sh`. Data collectors to resume:

- `data/ibkr_premarket_backfill.py` — pre-market bars, whole universe, resumable
  (manifest `data/ibkr_premarket_manifest.json`).
- `data/crypto_klines.py` + `data/crypto_live.py` — crypto klines/book/account.
- `research/obi_collector.py` — full-universe order-flow imbalance (forward-only).

## Do NOT

- Do NOT enable any live execution until an edge survives the adversarial gates in
  `trading-backtest-validation` skill (placebo, liquidity filter, point-in-time
  lookahead, chronological OOS, real cost stress). Point-in-time filtering is the
  difference between a fake t=7 and a real t=1 — see `research/atomics/crypto_reversal_ptliquid.py`.
- Do NOT re-propose anything in `research/RESEARCH_VERDICT_LEDGER.md` without new evidence.

## Deeper docs

`docs/PROJECT-STATE.md` · `docs/RECOVERY.md` · `docs/DATA-CATALOG.md` ·
`docs/STRATEGY_PORTFOLIO.md` · `docs/SERVICES.md` · `docs/ROBINHOOD-LIVE.md` ·
`docs/IBGATEWAY-LIVE-OPS.md` · `docs/COMMUNICATION.md`
