"""Config loader for the data engine.

Single source of truth = `data_engine/registry.json`. This module loads it and
resolves env-driven overrides (S3 bucket/region) so the engine can run in-place
today and be split into its own repo later with zero code change.

Env resolution (splittable): the engine reads AWS/S3 config from, in order of
precedence:
  1. `DATA_ENGINE_ENV_FILE` (explicit .env path) if set
  2. `<repo_root>/.env` (the trading system's .env, found one dir up)
  3. process environment (AWS_REGION / S3_BUCKET)

It never imports from `data/`, `bot/`, or `hardening/` — no trading coupling.
"""
import json
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
_REGISTRY_PATH = os.path.join(_THIS_DIR, "registry.json")

# Local cache/state lives INSIDE data_engine/ so the whole package is portable.
CACHE_DIR = os.path.join(_THIS_DIR, "cache")
STATE_DIR = os.path.join(_THIS_DIR, "state")


def _load_env():
    """Best-effort .env load; returns nothing (env may already be set)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_file = os.getenv("DATA_ENGINE_ENV_FILE")
    candidates = [env_file, os.path.join(_REPO_ROOT, ".env"),
                  os.path.join(_THIS_DIR, ".env")]
    for c in candidates:
        if c and os.path.isfile(c):
            load_dotenv(c, override=False)
            return


_load_env()


def _registry():
    with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


REGISTRY = _registry()


def bucket():
    return os.getenv("S3_BUCKET") or REGISTRY["s3"]["bucket"]


def region():
    return os.getenv("AWS_REGION") or REGISTRY["s3"]["region"]


def prefix(kind):
    """Template string for a key kind ('daily' / 'intraday')."""
    return REGISTRY["prefixes"][kind]


def intervals():
    return REGISTRY["intervals"]


def depth():
    return REGISTRY["depth"]


def universe_cfg():
    return REGISTRY["universe"]


def liquid_cfg():
    return REGISTRY["liquid"]


def pacing():
    return REGISTRY["pacing"]


def schedule():
    return REGISTRY["schedule"]


def local_path(rel):
    """Resolve a registry-relative cache/state path to an absolute path."""
    # registry cache_file paths are written as "data_engine/cache/..." (repo-relative).
    if rel.startswith("data_engine/"):
        rel = rel[len("data_engine/"):]
    return os.path.join(_THIS_DIR, rel)


def ensure_dirs():
    for d in (CACHE_DIR, STATE_DIR):
        os.makedirs(d, exist_ok=True)
    return CACHE_DIR, STATE_DIR


def acquire_lock(name):
    """Exclusive advisory lock so two engine runs never overlap (serialize).

    Returns (fd, path) on success, or (None, path) if another instance holds it.
    Caller should exit cleanly on (None, path).
    """
    import fcntl
    ensure_dirs()
    path = os.path.join(STATE_DIR, f"{name}.lock")
    fd = open(path, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd, path
    except BlockingIOError:
        fd.close()
        return None, path
