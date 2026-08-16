# Recovery Runbook — 24/7 Trading VPS (AS-BUILT)

> **Purpose:** complete, copy-paste rebuild + recovery instructions for the live
> trading VPS. This documents the **real running system** (verified 2026-08-16),
> NOT the stale `infra/cloudformation.yaml` IBC-era skeleton. The instance was built
> **manually** — no CloudFormation bootstrap ever ran (`/var/log/trading-bootstrap.log`
> is absent), so this runbook + the rewritten `infra/cloudformation.yaml` are the
> recovery artifacts.

---

## 1. Inventory (as-built, verified)

| Item | Value |
|---|---|
| OS / AMI | Ubuntu **24.04.4 LTS** (kernel `6.17.0-1019-aws`) |
| Instance | `t3.small` (2 vCPU / 1.9 GiB RAM), **us-east-1b**, id `i-00009f59dcb52f725` |
| Elastic IP | `52.7.95.127` |
| Root volume | 30 GB gp3 (`nvme0n1`), + **2 GB swapfile** |
| Hermes | v0.20.1, install dir `/home/ubuntu/.hermes/hermes-agent` |
| IB Gateway | **native GWClient 10.45** (build `10451` / "10.45.1j"), **IBC removed 8/14** |
| Account ID | `920641308584` |

---

## 2. IAM — `trading-vps-role` (instance role)

- Attached via instance profile; boto3 auto-fetches creds from instance metadata.
  **There are NO AWS keys on disk — do not set `AWS_EC2_METADATA_DISABLED=true`.**
- Effective permissions (probed 2026-08-16; **updated 2026-08-16** — role now
  has **AdministratorAccess**, granted from the laptop):
  - **ALLOWED:** `s3` (Head/List/Get/Put/Delete on the datalake bucket),
    `dynamodb` (full CRUD + `CreateTable` on trading tables),
    `ec2:DescribeSecurityGroups` (narrow read), `sts:GetCallerIdentity`,
    **`ssm:GetParameter`/`ssm:GetParameters`** — the VPS reads `/trading/*`
    secrets directly (verified `WithDecryption` works, 8/8 params).
  - **DENIED:** `ec2` write actions (incl. `ec2:AuthorizeSecurityGroupIngress`).
- Consequence: **the VPS cannot open port 8645 (reports) in its own security
  group.** The owner must do it from a machine with AWS creds (see §3).

---

## 3. Security group — `trading-system-sg` (`sg-0b981dd12552d33b9`)

VPC `vpc-0587e075606c52d68`. Ingress rules (verified):

| Port | Proto | Source | Purpose |
|---|---|---|---|
| 22 | tcp | `100.36.195.7/32` (laptop NAT IP) | SSH |
| 8501 | tcp | `0.0.0.0/0` | Streamlit dashboard |
| 8644 | tcp | `100.36.195.7/32` (laptop NAT IP) | Hermes webhook inbound |

**NOT open (intentional):**
- **8645** — return-channel `GET /reports` pull. Open it manually when needed:
  ```bash
  aws ec2 authorize-security-group-ingress --region us-east-1 \
    --group-id sg-0b981dd12552d33b9 \
    --ip-permissions IpProtocol=tcp,FromPort=8645,ToPort=8645,\
IpRanges='[{CidrIp=<LAPTOP_IP>/32,Description="Laptop return-channel pull"}]'
  ```
- **4002** — IB Gateway API. Deliberately never exposed externally.

> The laptop is behind NAT; when its IP changes, the `/32` rules for **22, 8644,
> and 8645** all break together and must be updated. (There are also four leftover
> `launch-wizard-*` SGs — 22/80/443 → 0.0.0.0/0 — that are NOT attached to this
> instance; ignore or delete them.)

---

## 4. Data lake

- **S3 bucket:** `trading-datalake-920641308584` (parquet/JSONL cold archive).
  Prefixes: `ibkr/equities|futures|crypto`, `futures-bars/`, `futures-ticks/`,
  `contracts/`, `sessions/`, `options/`, `yf/`, `crypto-hist/`, `macro/`,
  `news/`, `research/scan-results/`.
- **DynamoDB — 19 tables, auto-provisioned by `bot/*.py` code** (`boto3 create_table`
  if-not-exists), so a rebuild re-creates them. Names (verified `ListTables`):

  ```
  activity_log          crypto_positions      crypto_signals
  equity_positions      forecaster_shadow     futures_positions
  futures_signals       options_paper         options_performance
  options_positions     options_signals       options_trades
  pipeline_log          predictions           stock_metadata
  stock_prices          stock_sentiment       stock_technicals
  trading-data
  ```

---

## 5. Secrets — SSM Parameter Store (SOURCE OF TRUTH) + gitignored file fallback

**AWS SSM Parameter Store (`/trading/*`, SecureString) is the SOURCE OF TRUTH.**
The VPS loads secrets SSM-first at process start via `infra/secrets.py`
(`bootstrap()` for the Python data collectors + bots; `--ibkr-shell` for
`ibgateway-login.sh`). The gitignored files below are kept as a **fallback
cache**: the loader degrades to them silently when SSM is unreachable or a key
is absent, so the bots never crash on an SSM hiccup. The role `trading-vps-role`
has AdministratorAccess (granted 2026-08-16), so the instance reads parameters
with **no AWS keys on disk**.

SSM → env mapping (`infra/secrets.py` `PARAM_TO_ENV`):

| SSM path | Env var | Fallback file |
|---|---|---|
| `/trading/ibkr/username` | `IBG_USERNAME` | `ibgateway-creds.env` |
| `/trading/ibkr/password` | `IBG_PASSWORD` | `ibgateway-creds.env` |
| `/trading/alphavantage/api_key` | `ALPHAVANTAGE_API_KEY` | `.env` |
| `/trading/binance_us/api_key` | `BINANCE_US_API_KEY` | `.env` |
| `/trading/binance_us/secret_key` | `BINANCE_US_SECRET_KEY` | `.env` |
| `/trading/fmp/api_key` | `FMP_API_KEY` | `.env` |
| `/trading/newsapi/api_key` | `NEWSAPI_ORG_API_KEY` | `.env` |
| `/trading/serper/api_key` | `SERPER_API_KEY` | `.env` |

Fallback cache files (gitignored — keep on rebuild for SSM-outage resilience):

| File | Contains (key names) | Notes |
|---|---|---|
| `/home/ubuntu/ibgateway-creds.env` | `IBG_USERNAME`, `IBG_PASSWORD` | IBKR **paper** acct `DUR193467`; mode 0600 |
| `/home/ubuntu/trading-system/.env` | `AWS_REGION`, `DYNAMODB_TABLE`, + the 6 API keys above | app/ingest API keys |
| `/home/ubuntu/.hermes/.env` | `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_HOME_CHANNEL`, `WEBHOOK_ENABLED`, `WEBHOOK_PORT`, `WEBHOOK_SECRET`, `IBKR_USERNAME`, `IBKR_PASSWORD`, … | Hermes gateway (Telegram + webhook + model routing) — NOT under `/trading/*`, separate concern |

`WEBHOOK_PORT=8644` and `WEBHOOK_SECRET` drive the inbound `laptop-task` webhook;
the same secret is reused by the reports server (`~/.hermes/webhook_subscriptions.json`).

---

## 6. IB Gateway — native (IBC removed)

- **Entry point:** `install4j.ibgateway.GWClient` (NOT `ibcalpha.ibc.IbcGateway`).
  Launcher wrapper: `/home/ubuntu/ibgateway-native-start.sh` (starts Xvfb `:99` +
  openbox, then the gateway). Login helper: `/home/ubuntu/ibgateway-login.sh`
  (types password, clicks "Paper Log In", auto-accepts disclaimer).
- **IBC backup:** `~/ibc-migration-backup_20260814_222739` (config.ini + start script).
- **Pin build / no auto-update:**
  `INSTALL4J_ADD_VM_PARAMS="-Dtwslaunch.autoupdate.serviceImpl=twslaunch.autoupdate.DummyAutoUpdateService"`.
- **Ports:** paper `4002` (live `4001`). `clientId` convention: 50=full backfill,
  70=live.py, 71=bonds(defunct), 72=live_intraday, 73=backfill_bars/contracts,
  74=tick recorder, 75=daily_collect, 76=reconcile daemon, 77=options_chains, 78=live_gc.

---

## 7. systemd — full set (as-built)

### System units (`/etc/systemd/system/`, root)

| Unit | Purpose | Restart |
|---|---|---|
| `ibgateway.service` | native GWClient headless (:4002) | `always`, 10s |
| `trading-dashboard.service` | Streamlit :8501 | `always`, 5s |
| `futures-tick-recorder.service` | L1 tick recorder (clientId 74) → S3 `futures-ticks` + `QUOTE#` | `on-failure` |
| `reconcile-daemon.service` | broker reconciliation (clientId 76, 45s) → `RECONCILE/system` | `on-failure` |
| `ibkr-backfill.service` | full-depth backfill (clientId 50) → S3 `ibkr/*` | `on-failure`, `MemoryMax=1200M Nice=10` |
| `trading-reports.service` | return-channel `GET /reports` :8645 | `always`, 5s |

### System timers (`/etc/systemd/system/`)

| Timer | Schedule | Action |
|---|---|---|
| `ibgateway-hang-watchdog.timer` | every 2 min (`OnUnitInactiveSec`) | port-4002 alive-but-socket-dead recovery |
| `ibgateway-weekly.timer` | Sun 09:00 ET | cold restart → **2FA re-login** |
| `ibkr-backfill-resume.timer` | every 10 min | gateway-aware backfill resume |
| `ibkr-1min-close.timer` | Sun 16:00 ET | stop 1-min backfill before live hours |
| `ibkr-1min-unpause.timer` | one-shot Sat 00:01 ET | clear `data/ibkr_1min_paused` |

### User unit (`~/.config/systemd/user/`, ubuntu) — survives reboot via linger

| Unit | Purpose | Restart |
|---|---|---|
| `hermes-gateway.service` | Hermes gateway: webhook :8644 + Telegram + Hermes cron | `always`, 5s |

Installed by `hermes gateway install`; **requires `loginctl enable-linger ubuntu`**
(verified `Linger=yes`). The committed copy is `infra/hermes-gateway.service`.

---

## 8. Cron — two layers (never double-schedule a bot)

### System crontab — data ingestion only (silent, logs to `data/*.log`)
`CRON_TZ=America/New_York`. Install: `crontab infra/crontab.txt`. Jobs:

```
*/10 * * * *   data/crypto_tick.py
0 17  * * *   data/ingest.py
*/30 * * * *   data/market_research.py
45 17 * * *   data/options_chains.py
0 18  * * *   data/fred_collect.py
15 18 * * *   data/fmp_ingest.py
30 18 * * *   data/yf_collect.py
45 18 * * *   data/newsapi_ingest.py
20 19 * * *   data/daily_collect.py
```

### Hermes cron (`~/.hermes/cron/jobs.json`) — bot execution + monitoring
12 jobs (managed by the Hermes gateway process; `no_agent` script jobs run
`~/.hermes/scripts/*.sh`):

| Job | Expr (UTC-annotated) | Deliver | State |
|---|---|---|---|
| Daily trading summary | `45 23` | telegram | ON |
| IB Gateway health watchdog | `*/30` | telegram | ON |
| Broker reconcile watchdog | `*/5` | telegram | ON |
| Paper signals — index futures | `0 23` | telegram | ON |
| Paper signals — equities | `15 23` | telegram | ON |
| Paper signals — intraday MES | `*/15 13-20 * * 1-5` | local | ON |
| Paper signals — crypto | `*/30` | local | ON |
| Paper execution — gold momentum | `10 23` | telegram | ON |
| Paper fwd — crypto Donch200 | `*/30` | local | ON |
| Paper signals — bonds | `5 23` | telegram | ⛔ paused |
| Weekly strategy scan + refine | `0 18 * * 0` | telegram | ⛔ paused |
| IBGW 04:00 restart token re-login (one-shot) | once | — | done/off |

> **TZ nuance:** the Hermes gateway caches its timezone at startup and does NOT pick
> up a live `timedatectl set-timezone` change. The cron exprs above are **left in UTC**
> (`0 23` = 19:00 ET) to match the currently-running gateway. After a
> `systemctl --user restart hermes-gateway` (which reads `timezone: America/New_York`),
> re-express them to ET (23:xx→19:xx, 18:00→14:00, intraday 13-20→09-16). The intraday
> bot's *code* already self-gates on ET.

---

## 9. Rebuild order (exact)

```bash
# 0. Launch EC2: Ubuntu 24.04 LTS AMI, t3.small, us-east-1b, 30 GB gp3,
#    attach instance profile trading-vps-role, EIP 52.7.95.127, SG trading-system-sg.

# 1. Base packages + swap
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  openjdk-17-jre-headless xvfb openbox xdotool imagemagick tesseract-ocr \
  unzip git python3-venv python3-pip curl streamlit
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile \
  && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 2. Clone repo + venv
git clone git@github.com:PCnslt/trading-system.git /home/ubuntu/trading-system
cd /home/ubuntu/trading-system
python3 -m venv venv
./venv/bin/pip install -U pip
./venv/bin/pip install -r requirements.txt        # 90 packages (frozen 2026-08-16)

# 3. Secrets are SSM-FIRST (source of truth /trading/*, SecureString) — the
#    instance role reads them directly (NO restore needed). Still restore the
#    fallback cache files from the laptop backup for SSM-outage resilience:
#    /home/ubuntu/ibgateway-creds.env   (mode 600)
#    /home/ubuntu/trading-system/.env
#    /home/ubuntu/.hermes/.env          (after Hermes install in step 8)

# 4. IB Gateway (native, no IBC) — see docs/IBGATEWAY-NATIVE-OPS.md
#    install standalone, then /home/ubuntu/ibgateway-native-start.sh
sudo systemctl enable --now ibgateway     # approve 2FA push on phone
ss -tln | grep 4002                        # verify listening

# 5. Collectors + reconciliation
sudo systemctl enable --now futures-tick-recorder
sudo systemctl enable --now reconcile-daemon
sudo systemctl enable --now ibkr-backfill-resume.timer

# 6. Dashboard + reports
sudo systemctl enable --now trading-dashboard       # :8501
sudo systemctl enable --now trading-reports         # :8645

# 7. Hermes + gateway (webhook :8644 + Telegram + cron)
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes gateway install
loginctl enable-linger ubuntu
systemctl --user enable --now hermes-gateway
# restore ~/.hermes/.env + ~/.hermes/cron/jobs.json + webhook_subscriptions.json

# 8. System cron (ingestion)
crontab /home/ubuntu/trading-system/infra/crontab.txt
```

**DynamoDB tables are NOT created by hand** — each `bot/*.py` calls `create_table`
if-not-exists on first run, so starting the bots re-provisions all 19 tables.

---

## 10. Weekly 2FA + watchdogs

- **Weekly 2FA (Sun 09:00 ET):** `ibgateway-weekly.timer` → `systemctl restart
  ibgateway` + `ibgateway-login.sh` types the password; the owner approves the IB
  Key push on the phone. After login, clear BOTH dialogs (a `Warning` paper-disclaimer
  window with an "I understand and accept" button, and a `Pending Tasks` window via
  Tab+Return) — verify `ib.connect(...)` returns `managedAccounts()==['DUR193467']`.
- **Port-4002 hang watchdog:** every 2 min, `ibgateway-hang-watchdog.sh` checks
  `ss -ltn | grep :4002`; on >3 min hang it restarts the gateway ONCE, resumes the
  backfill, then Telegram-alerts and stops (never loops / never spams 2FA).
- **1-min backfill pause/unpause:** `ibkr-1min-close.timer` (Sun 16:00 ET) stops the
  backfill before live hours; `ibkr-1min-unpause.timer` clears the pause flag next Sat.

---

## 11. What is NOT recoverable automatically

- **Secrets** — SSM Parameter Store (`/trading/*`) is the live source of truth;
  the gitignored fallback files (ibgateway-creds.env, `.env`, `~/.hermes/.env`)
  are only a cache. If BOTH SSM and the files are lost, the laptop backup is the
  last copy.
- **IB Gateway encrypted soft-token** (`autorestart file`) — a fresh build needs a
  full login + 2FA (owner's phone), never silently.
- **~/.hermes/cron/jobs.json** — restore from laptop backup or re-create via the
  Hermes UI; it is not in git.
- **~/.hermes/webhook_subscriptions.json** — contains the shared HMAC secret; if lost,
  rotate the webhook secret on both sides.
