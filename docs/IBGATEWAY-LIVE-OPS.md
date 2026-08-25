# IB Gateway LIVE — configuration & activation (U26949861)

Second IB Gateway instance for LIVE trading, isolated from the paper gateway.
**PAPER remains the operating default.** The live unit is DISABLED and has never
logged in — no live order can be placed until the owner completes activation.

## What was built (2026-08-16)

| Piece | Value |
|---|---|
| Settings dir | `/home/ubuntu/Jts-live/` (jts.ini `tradingMode=l`) |
| Relocation mechanism | `-DjtsConfigDir=/home/ubuntu/Jts-live` via `INSTALL4J_ADD_VM_PARAMS` (last `-D` wins — **verified**: launcher.log logs `settings dir: '/home/ubuntu/Jts-live'`) |
| Display | `:100` (own Xvfb + openbox, isolated from paper's `:99`) |
| Launcher | `infra/ibgateway-live-start.sh` (installed at `/home/ubuntu/ibgateway-live-start.sh`) |
| Login helper | `infra/ibgateway-live-login.sh` (types creds, submits) |
| systemd unit | `ibgateway-live.service` — **disabled** (`systemctl is-enabled` → disabled, `Active: inactive`) |
| Live account | U26949861 (same login `mushfiqrhmn1` + SSM `/trading/ibkr/password` as paper) |
| Paper (unchanged) | `:4002`, `Jts/`, DISPLAY `:99`, account DUR193467 |

The API socket port for the live gateway is the **IB Gateway live default 4001**
(distinct from paper 4002). It binds only AFTER a successful login. If a
non-default port is preferred, set it explicitly at activation (Configure →
Settings → API → Socket port), then update the `IBKR_PORT` used by any live bot.

## Why a second gateway (not a paper↔live flip)

A flip on the single `:4002` gateway would leave paper bots pointed at a live
session — a paper bot firing after a flip would place a LIVE order. The second
instance removes that failure mode: the **port is the safety boundary**. A bot
pointed at `:4002` can never reach live (`:4001`/`:4003`), and vice versa.

## Activation steps (USER-ONLY blockers in order)

1. **Fund + permission U26949861** (IBKR Client Portal): enable live futures +
   options trading permissions and **CME L1 (real-time) market data** on the
   live account. Until then the live gateway can't trade the futures edge.
2. **Start the live gateway** (fresh config → sits at the login screen, binds
   nothing): `sudo -n systemctl start ibgateway-live`
3. **Switch "Trading Mode" → "Live Trading"** on the login screen. ⚠️ The
   dropdown **defaults to "Paper Trading"** on a fresh config dir and is **not**
   driven by `jts.ini tradingMode` (verified empirically — both `l` and `live`
   still show "Paper Trading"). If left on Paper, the gateway logs into a SECOND
   paper session, not live. (The login helper's xdotool clicks do not flip this
   Swing combo-box in headless mode — do it manually or via OCR-guided click at
   activation.)
4. **First login + 2FA**: `DISPLAY=:100 /home/ubuntu/ibgateway-live-login.sh`
   types the username/password; approve the **IB Key push** on the phone. First
   live login always requires 2FA (subsequent daily auto-restarts reuse the soft
   token).
5. **VERIFY (fail-safe — mandatory):** from the repo venv
   `./venv/bin/python -c "from ib_insync import IB; ib=IB(); ib.connect('127.0.0.1',4001,clientId=98); print(ib.managedAccounts()); ib.disconnect()"`
   must print `['U26949861']` — **NOT** `['DUR193467']`. If it returns the paper
   account, the Trading-Mode switch failed: STOP and redo steps 2–4.
6. **Only then** wire a live-capable bot: set `LIVE=true` and `IBKR_PORT=4001`
   (or the chosen live port) on the specific bot, and keep `CONTROL/system`
   RUNNING. No bot points at the live port until this step.

## Rollback / safety

- Stop live without touching paper: `sudo -n systemctl stop ibgateway-live`
- Paper is fully independent (`:4002`, `Jts/`, `:99`); killing the live unit or
  its `:100` display never affects paper.
- t3.small is memory-tight (1.9 GB): do **not** run paper + live gateways
  simultaneously long-term. Run one at a time (stop paper before a sustained
  live session) or upgrade to t3.medium before going live.
- ⚠️ **Same-username session caution (unverified):** paper and live share ONE
  login (`mushfiqrhmn1`). A concurrent audit reported IBKR may restrict
  simultaneous paper + live sessions under one username (a live login could kick
  the paper session). Not confirmed against a live login (2FA-gated), but the
  safe path is the same: **stop the paper gateway before the first live login**
  and run one at a time until confirmed otherwise.

## Verified vs. not-yet-verified

- ✅ `-DjtsConfigDir` relocation works (launcher.log `settings dir: '/home/ubuntu/Jts-live'`).
- ✅ Paper gateway untouched throughout (4002 up the whole time).
- ✅ Live gateway sits unauthenticated at the login screen (no API port bound).
- ⚠️ Live login button coordinate / exact "Live Trading" combo-box click is
  **unverified** (needs the owner's first live 2FA login to confirm).
- ⚠️ Live API port not yet observed binding (requires login); expected 4001.

Reference: the live jts.ini is committed as `infra/jts-live.ini` (CRLF runtime
copy at `/home/ubuntu/Jts-live/jts.ini`). The paper native launcher was also
committed (`infra/ibgateway-native-start.sh`) to close a prior IaC gap.

---

## 2026-08-25 — live login identity, and why orders are still blocked

### Finding 1: `~/ibc-live/config.ini` had DRIFTED to the paper username
`ibgateway-live-start-ibc.sh` documents the intended split:

```
#   username mushfiqrhmn1-live  <-- IBKR forbids 2 concurrent sessions per username
```

but the live config actually contained `IbLoginId=mushfiqrhmn1` (the PAPER login) with
`TradingMode=live`. So the "live" gateway was authenticating as the paper username and
landing on a live account attached to it — **U26949861** — which is the freshly-created
account that demands e-mail-token verification. **Check this file before trusting which
account you are on.**

### Finding 2: `mushfiqrhmn1-live` is NOT an activated login — do NOT switch to it
SSM holds both identities:

| param | value |
|---|---|
| `/trading/ibkr/username` | `mushfiqrhmn1` (10-char pw) |
| `/trading/ibkr-live/username` | `mushfiqrhmn1-live` (15-char pw) |

Switching the live config to `mushfiqrhmn1-live` + its SSM password produced
**"Unrecognized Username or Password"** on login attempt 1 (2026-08-25 18:36 ET).
The credentials were staged for an account that was never activated — which is what the
old note *"restore paper when mushfiqrhmn1-live activates"* actually meant. Config was
restored from `config.ini.bak.<epoch>` immediately.

**Lockout discipline:** stop the service after the FIRST failure. A prior incident hit
106 failed logins in ~7 minutes and risked an IBKR username lockout; that is why the
launcher has a `LOGIN_FAILED.lock` circuit breaker. This event was stopped at **1
attempt**.

### Finding 3: gateway 2FA and order permission are DIFFERENT gates
Restarting the live gateway opens a **Second Factor Authentication** dialog:

> "Open the IBKR notification on your phone — IBKR sent you a notification to your phone.
>  Tap the IBKR notification to complete two-factor authentication"

Only the owner can tap it. Once tapped, `IBC: Login has completed`, port 4001 listens and
**historical data reads work** (verified: F 5 daily bars, last 2026-08-25 close 13.95).

That does **NOT** unblock trading. Order placement still returns:

```
Error 201: Order rejected - reason: BEFORE WE CAN ACCEPT YOUR ORDER IN THIS SECURITY,
PLEASE LOGIN TO CLIENT PORTAL AND VERIFY USING THE TOKEN WE EMAILED TO YOU.
```

Re-verified AFTER a successful 2FA login (whatIf BUY on BB and FNB, both rejected, empty
margin fields). **Gateway 2FA != Client Portal token verification.** The latter is a
one-time account-level gate the owner must clear at portal.interactivebrokers.com using
the e-mailed token. Until then the IBKR equity lane can read data but cannot trade, and
`exec_manager._confirm()` now surfaces `BROKER SAYS: <reason>` so this never again shows
up as a bare "ENTRY UNKNOWN (timeout)".

### Recovery recipe
```bash
grep -nE '^IbLoginId|^TradingMode' ~/ibc-live/config.ini   # expect mushfiqrhmn1 / live
ls ~/ibc-live/LOGIN_FAILED.lock                            # must NOT exist
sudo systemctl restart ibgateway-live.service
# owner taps the phone notification, then:
ss -tlnp | grep :4001                                      # LISTEN = logged in
DISPLAY=:100 scrot -o /tmp/gw.png && tesseract /tmp/gw.png -   # read any stuck dialog
```
