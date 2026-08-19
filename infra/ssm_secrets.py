"""SSM-first secrets loader with .env / file fallback.

SOURCE OF TRUTH = AWS SSM Parameter Store (`/trading/*`, SecureString).
Fallback        = gitignored .env files, kept as a local cache so the bots keep
                  running through an SSM outage or a missing key.

Precedence (highest wins):
  1. Environment already set by the caller (never clobbered by .env)
  2. SSM Parameter Store (`/trading/*`, decrypted via WithDecryption)
  3. `.env` (repo root) — the fallback cache
  For IB Gateway login: `~/.ibgateway-creds.env` is the fallback cache instead.

Behaviour guarantees:
  * `bootstrap()` / `load_ssm()` NEVER raise on SSM failure. A timeout, network
    error, AccessDenied, or missing parameter degrades to the .env fallback and
    the process continues.
  * Short botocore timeouts (connect 3s / read 5s / 1 retry) so an SSM hang
    cannot stall a time-sensitive bot at startup.
  * Results are cached in-process; repeated calls do not re-hit SSM.

CLI (used by infra/ibgateway-login.sh):
  python3 infra/ssm_secrets.py --ibkr-shell   # `export IBG_USERNAME=...` lines (SSM→file)
  python3 infra/ssm_secrets.py --json         # full resolved dict as JSON
  python3 infra/ssm_secrets.py                # human-readable status
"""
import os

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ENV_FILE = os.path.join(_REPO_ROOT, ".env")
IBG_CREDS_FILE = os.path.expanduser("~/ibgateway-creds.env")

# SSM parameter path -> environment variable name. SSM is canonical.
PARAM_TO_ENV = {
    "/trading/ibkr/username": "IBG_USERNAME",
    "/trading/ibkr/password": "IBG_PASSWORD",
    "/trading/alphavantage/api_key": "ALPHAVANTAGE_API_KEY",
    "/trading/binance_us/api_key": "BINANCE_US_API_KEY",
    "/trading/binance_us/secret_key": "BINANCE_US_SECRET_KEY",
    "/trading/fmp/api_key": "FMP_API_KEY",
    "/trading/newsapi/api_key": "NEWSAPI_ORG_API_KEY",
    "/trading/serper/api_key": "SERPER_API_KEY",
    "/trading/robinhood/access_token": "RH_ACCESS_TOKEN",
    "/trading/robinhood/refresh_token": "RH_REFRESH_TOKEN",
    "/trading/robinhood/client_id": "RH_CLIENT_ID",
    "/trading/robinhood/client_name": "RH_CLIENT_NAME",
    "/trading/robinhood/expires_at": "RH_EXPIRES_AT",
    "/trading/robinhood/expires_in": "RH_EXPIRES_IN",
    "/trading/robinhood/scope": "RH_SCOPE",
    "/trading/robinhood/token_type": "RH_TOKEN_TYPE",
}

# Robinhood OAuth parameter names (SSM-only on this VPS — no .env fallback).
RH_PARAM_NAMES = [
    "/trading/robinhood/access_token",
    "/trading/robinhood/refresh_token",
    "/trading/robinhood/client_id",
    "/trading/robinhood/client_name",
    "/trading/robinhood/expires_at",
    "/trading/robinhood/expires_in",
    "/trading/robinhood/scope",
    "/trading/robinhood/token_type",
]
RH_ENV_VARS = (
    "RH_ACCESS_TOKEN", "RH_REFRESH_TOKEN", "RH_CLIENT_ID", "RH_CLIENT_NAME",
    "RH_EXPIRES_AT", "RH_EXPIRES_IN", "RH_SCOPE", "RH_TOKEN_TYPE",
)

_SSM_CACHE = None          # {env_var: value} once fetched successfully
_SSM_ATTEMPTED = False     # avoid re-hitting SSM on repeated calls


def _ssm_client(region=None):
    """Build a short-timeout SSM client (or None if boto3 is unavailable)."""
    try:
        import boto3
        from botocore.config import Config
    except Exception:
        return None
    cfg = Config(
        connect_timeout=3,
        read_timeout=5,
        retries={"max_attempts": 1},
    )
    region = region or os.getenv("AWS_REGION", "us-east-1")
    return boto3.client("ssm", region_name=region, config=cfg)


def load_ssm(names=None, region=None):
    """Fetch /trading/* params from SSM (WithDecryption) -> {env_var: value}.

    Returns {} on ANY failure (unreachable, timeout, AccessDenied, missing keys).
    Never raises.
    """
    global _SSM_CACHE, _SSM_ATTEMPTED
    if _SSM_ATTEMPTED:
        return dict(_SSM_CACHE or {})
    _SSM_ATTEMPTED = True

    if names is None:
        names = list(PARAM_TO_ENV)
    if not names:
        _SSM_CACHE = {}
        return {}

    client = _ssm_client(region)
    if client is None:
        _SSM_CACHE = {}
        return {}

    try:
        out = {}
        # get_parameters caps at 10 names per call — chunk to stay under the limit
        # (PARAM_TO_ENV grew past 10 when the Robinhood OAuth params were added).
        names_list = list(names)
        for i in range(0, len(names_list), 10):
            chunk = names_list[i:i + 10]
            resp = client.get_parameters(Names=chunk, WithDecryption=True)
            for p in resp.get("Parameters", []):
                env = PARAM_TO_ENV.get(p["Name"])
                if env and p.get("Value"):
                    out[env] = p["Value"]
    except Exception as e:  # noqa: BLE001 — fall back, never crash the bots
        print(f"[secrets] SSM unavailable ({e!r}); using .env fallback", flush=True)
        _SSM_CACHE = {}
        return {}

    _SSM_CACHE = out
    return dict(out)


def _load_dotenv_file(path, override=False):
    """Best-effort dotenv load; no-op if dotenv or the file is unavailable."""
    if not path or not os.path.isfile(path):
        return
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(path, override=override)


def bootstrap(env_file=None, names=None):
    """SSM-first overlay onto the process environment.

    1. Load `.env` as the fallback base (does NOT override already-set vars).
    2. Overlay every /trading/* param decryptable from SSM (SSM wins).
    Returns {env_var: value} of the resolved secrets. Never raises.
    """
    _load_dotenv_file(env_file or DEFAULT_ENV_FILE, override=False)
    for k, v in load_ssm(names=names).items():
        os.environ[k] = v
    return {env: os.environ.get(env) for env in PARAM_TO_ENV.values()}


def _parse_env_file(path):
    """Minimal KEY=VALUE parser (no dotenv dependency) for the fallback cache."""
    out = {}
    if not path or not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    out[k] = v
    except OSError:
        pass
    return out


def ibkr_creds():
    """IB Gateway login creds: SSM first, `~/ibgateway-creds.env` fallback.

    Returns {"IBG_USERNAME": ..., "IBG_PASSWORD": ...} (empty strings if none).
    """
    ssm = load_ssm(names=["/trading/ibkr/username", "/trading/ibkr/password"])
    username = ssm.get("IBG_USERNAME", "")
    password = ssm.get("IBG_PASSWORD", "")
    if not username or not password:
        fallback = _parse_env_file(IBG_CREDS_FILE)
        username = username or fallback.get("IBG_USERNAME", "")
        password = password or fallback.get("IBG_PASSWORD", "")
    return {"IBG_USERNAME": username, "IBG_PASSWORD": password}


def robinhood_oauth():
    """Robinhood OAuth client creds: SSM-only (no .env fallback on this VPS).

    Returns {RH_ACCESS_TOKEN, RH_REFRESH_TOKEN, RH_CLIENT_ID, ...} with empty
    strings for anything missing. Never raises (an SSM hiccup degrades to empty
    creds and the caller surfaces a clear auth error).
    """
    ssm = load_ssm(names=RH_PARAM_NAMES)
    return {env: ssm.get(env, "") for env in RH_ENV_VARS}


def _shell_quote(v):
    return "'" + v.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    import json
    import sys

    if "--ibkr-shell" in sys.argv:
        for k, v in ibkr_creds().items():
            print(f"export {k}={_shell_quote(v)}")
    elif "--json" in sys.argv:
        print(json.dumps(bootstrap()))
    else:
        resolved = bootstrap()
        ssm = _SSM_CACHE or {}
        print("=== SSM secrets loader (source of truth: /trading/*, SecureString) ===")
        print(f"repo .env fallback : {DEFAULT_ENV_FILE}")
        print(f"ibgw fallback file : {IBG_CREDS_FILE}")
        for env, val in resolved.items():
            src = "SSM" if env in ssm else (".env/file" if val else "MISSING")
            print(f"  {env:<22} -> {'<SET>' if val else '<EMPTY>'}  [{src}]")
        print(f"SSM params resolved: {len(ssm)}/{len(PARAM_TO_ENV)}")
