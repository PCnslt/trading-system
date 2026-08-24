#!/usr/bin/env python3
"""Generate an Ed25519 keypair for the Robinhood Crypto Trading API.

Prints the base64 PUBLIC key (paste into Robinhood when creating the credential)
and the base64 PRIVATE key (the signing secret — store ONLY in SSM, never git/log).

Run:  ./venv/bin/python scripts/rh_crypto_keygen.py
"""
import base64

try:
    import nacl.signing
except ImportError:
    print("pynacl not installed. Run:  ./venv/bin/pip install pynacl")
    raise SystemExit(1)

sk = nacl.signing.SigningKey.generate()
public_b64 = base64.b64encode(sk.verify_key.encode()).decode()
private_b64 = base64.b64encode(sk.encode()).decode()

print("=" * 72)
print("Robinhood Crypto API — Ed25519 keypair")
print("=" * 72)
print()
print("PUBLIC key (paste into Robinhood when creating the credential):")
print(f"  {public_b64}")
print()
print("PRIVATE key (SECRET — send to the VPS operator for SSM; never share/git/log):")
print(f"  {private_b64}")
print()
print("Then create the credential at https://robinhood.com/account/crypto and send")
print("the resulting rh-api-<uuid> API key + this private key to the VPS operator.")
