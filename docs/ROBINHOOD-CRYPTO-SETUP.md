# Robinhood Crypto Trading API — owner setup (one-time, ~5 min)

To activate fractional crypto trading (BTC / ETH / XRP) on Robinhood, the owner
must create an API credential + Ed25519 keypair. This is the ONLY manual step —
everything else is automated.

## Step 1 — generate an Ed25519 keypair (on the VPS)

```bash
cd ~/trading-system && ./venv/bin/python scripts/rh_crypto_keygen.py
```

This prints a **base64 public key** and a **base64 private key**. Save the
private key — it is the ONLY copy and Robinhood can't recover it.

## Step 2 — create the API credential (on the laptop, web classic)

1. Open https://robinhood.com/account/crypto (or app → Crypto → account settings).
2. Look for **"API" / "Crypto Trading API" / "Create credential"**.
3. When prompted for a **public key**, paste the base64 public key from Step 1.
4. Robinhood returns an **API key** (format `rh-api-<uuid>`).

## Step 3 — send both to the VPS operator (me)

Send these two values (they go straight into SSM SecureString, never logs):
- **API key** (`rh-api-…`)
- **base64 private key** (from Step 1)

## What happens next (fully automated)

The VPS stores them under SSM `/trading/robinhood-crypto/{api_key,private_key}`,
and `infra/rh_crypto.py` (already built + tested) becomes live:
- read holdings / orders / trading pairs,
- place fractional crypto orders (BTC / ETH / **XRP**),
- rest native `stop_loss` / `stop_limit` protective stops (never-lose-money).

Until the keys land, the client is fail-closed (raises `RHCryptoNotConfigured`)
— nothing can trade on a half-configured credential.

## Security notes

- The private key is the signing secret for ALL crypto orders. Store it ONLY in
  SSM (SecureString) — it is never written to a log, a repo file, or git.
- You can disable/rotate the credential at any time from the same settings page.
