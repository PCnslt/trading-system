"""Live bot logs — tail the latest cron-output file for each trading bot.

Maps Hermes cron job ids -> friendly bot names by reading ~/.hermes/cron/jobs.json
(script name is the stable key), then tails the newest `*.md` output per job.
Read-only — never writes to cron output or broker state.
"""
import os
import json
import glob

import streamlit as st

CRON_OUTPUT = os.path.expanduser('~/.hermes/cron/output')

# script filename (in ~/.hermes/scripts/) -> friendly label. Kept in run-order.
_SCRIPT_LABELS = {
    'paper_intraday.sh':        ('Intraday MES',     'FADESHORT + DONCH15 — every 15m RTH'),
    'paper_index_futures.sh':   ('Index EOD',        'live.py Donchian + RSI2 — 19:00 ET'),
    'paper_gc_exec.sh':         ('Gold momentum',    'live_gc.py Donchian L/S — 19:10 ET'),
    'paper_equity_signals.sh':  ('Equities signals', '19:15 ET'),
    'paper_rh_equities.sh':     ('RH equities RSI2', '19:20 ET'),
    'paper_crypto_signals.sh':  ('Crypto signals',   'every 30m'),
    'paper_crypto_paper.sh':    ('Crypto Donch200',  'every 30m'),
    'paper_bonds.sh':           ('Bonds (shelved)',  'paused'),
}


def _load_job_map():
    """job_id -> (label, blurb) by resolving script name in jobs.json."""
    try:
        with open(os.path.expanduser('~/.hermes/cron/jobs.json')) as f:
            d = json.load(f)
        jobs = d if isinstance(d, list) else d.get('jobs', d)
    except Exception:
        return {}
    mapping = {}
    for j in (jobs if isinstance(jobs, list) else jobs.values()):
        if not isinstance(j, dict):
            continue
        sc = (j.get('script') or '').split('/')[-1]
        if sc in _SCRIPT_LABELS:
            mapping[j.get('id') or j.get('job_id')] = _SCRIPT_LABELS[sc]
    return mapping


@st.cache_data(ttl=30, show_spinner=False)
def bot_log(job_id, n_lines=120):
    """(run_ts, tail_text) for the latest cron output file of a job; (None,None) if absent."""
    d = os.path.join(CRON_OUTPUT, job_id)
    if not os.path.isdir(d):
        return None, None
    files = sorted(glob.glob(os.path.join(d, '*.md')))
    if not files:
        return None, None
    path = files[-1]
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except Exception:
        return None, None
    ts = os.path.basename(path).removesuffix('.md')
    return ts, ''.join(lines[-n_lines:])


def all_bots():
    """[(label, blurb, job_id, run_ts, tail)] for every known trading bot."""
    mapping = _load_job_map()
    out = []
    for job_id, (label, blurb) in mapping.items():
        ts, tail = bot_log(job_id)
        out.append({'label': label, 'blurb': blurb, 'job_id': job_id,
                    'run_ts': ts, 'tail': tail})
    return out
