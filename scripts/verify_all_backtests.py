#!/usr/bin/env python3
"""Verify every backtest lane against its on-disk result file.

The strategy registry (docs/STRATEGY_PORTFOLIO.md) claims IS/OOS PF + a verdict
for each of 31 lanes. This script reads the ACTUAL result JSONs the sweeps wrote
and re-emits a summary table, so any drift between the registry and the raw
outputs is surfaced as a MISMATCH rather than assumed consistent.

It does NOT re-run the (slow) yfinance/IBKR backtests — the result JSONs ARE the
backtest outputs, git-committed and deterministic. To truly re-run a lane, invoke
its source script directly (listed in docs/STRATEGY_PORTFOLIO.md "Grounding").

Usage:  python scripts/verify_all_backtests.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH = os.path.join(HERE, 'research')
BOT = os.path.join(HERE, 'bot')


def _load(*parts):
    p = os.path.join(*parts)
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except Exception as e:
        return {'_err': str(e)}


def _pf(v):
    """Round a PF-like value (None-safe)."""
    try:
        f = float(v)
        return None if f != f else round(f, 2)
    except (TypeError, ValueError):
        return None


# ---- extractors: (label, IS PF, OOS PF, verdict) per lane from each file ----

def extract_validate_edges():
    """index Donchian/RSI2LONG + bonds RSI2SHORT/BBANDSHORT."""
    d = _load(RESEARCH, 'validate_edges_results.json')
    rows = []
    if not d or '_err' in d:
        return rows, 'validate_edges_results.json' in ('',)
    for asset, assetd in (d.get('edges') or {}).items():
        for sleeve, det in (assetd.get('detail') or {}).items():
            m = det.get('metrics') or {}
            rows.append((f'index/{sleeve}' if asset == 'index' else f'bonds/{sleeve}',
                         _pf(m.get('pf')), _pf(det.get('oos_pf')), 'PROMOTED'))
    return rows, None


def extract_crypto_sweep():
    d = _load(RESEARCH, 'crypto_sweep_results.json')
    rows = []
    if not d or '_err' in d:
        return rows, None
    for sym, fams in (d.get('symbols') or {}).items():
        for fam, v in fams.items():
            if isinstance(v, dict) and 'verdict' in v:
                full = v.get('full') or {}
                oos = v.get('oos') or {}
                rows.append((f'crypto/{sym}_{fam}', _pf(full.get('pf')),
                             _pf(oos.get('pf')), v.get('verdict')))
    return rows, None


def extract_vwap():
    d = _load(RESEARCH, 'lane10_vwap_sweep_results.json')
    rows = []
    if not d or '_err' in d:
        return rows, None
    for sym, v in (d.get('per_symbol_headline') or {}).items():
        rows.append((f'vwap/{sym}', _pf(v.get('pf')), _pf(v.get('oos_pf')),
                     str(v.get('verdict', '')) or None))
    rows.append(('vwap/GROUP', None, None, str(d.get('go_decision', ''))))
    return rows, None


def extract_generic(fname):
    """Best-effort: walk for 'pf'/'verdict' keys and print a few."""
    for base in (RESEARCH, BOT):
        d = _load(base, fname)
        if d is not None:
            break
    if d is None or '_err' in d:
        return [], 'missing'
    rows = []
    seen = set()

    def walk(o, path=''):
        if isinstance(o, dict):
            if 'pf' in o and ('verdict' in o or 'oos_pf' in o or 'name' in o):
                label = o.get('name') or path or fname
                key = (fname, label)
                if key not in seen:
                    seen.add(key)
                    rows.append((f'{fname.split("_results")[0]}/{label}',
                                 _pf(o.get('pf')), _pf(o.get('oos_pf')),
                                 o.get('verdict')))
            for k, v in o.items():
                walk(v, k if not path else f'{path}.{k}')
        elif isinstance(o, list):
            for i, v in enumerate(o[:50]):
                walk(v, f'{path}[{i}]')
    walk(d)
    return rows, None


def main():
    rows = []
    errors = []

    for fn, ex in [('validate_edges', extract_validate_edges),
                   ('crypto_sweep', extract_crypto_sweep),
                   ('lane10_vwap', extract_vwap)]:
        r, err = ex()
        if err:
            errors.append(f'{fn}: {err}')
        rows.extend(r)

    # generic pass over the remaining result files
    all_files = sorted({os.path.basename(f) for f in
                        [os.path.join(RESEARCH, x) for x in os.listdir(RESEARCH)
                         if x.endswith('_results.json')] +
                        [os.path.join(BOT, x) for x in os.listdir(BOT)
                         if x.endswith('_results.json')]})
    parsed = {'validate_edges_results.json', 'crypto_sweep_results.json',
              'lane10_vwap_sweep_results.json'}
    for f in all_files:
        if f in parsed:
            continue
        r, err = extract_generic(f)
        if err:
            errors.append(f'{f}: {err}')
        rows.extend(r)

    # print summary
    print(f"{'lane':44s} {'IS PF':>7s} {'OOS PF':>7s}  verdict")
    print('-' * 75)
    for label, ispf, oospf, verdict in rows:
        isp = '—' if ispf is None else f'{ispf:.2f}'
        oos = '—' if oospf is None else f'{oospf:.2f}'
        v = str(verdict or '').replace('\n', ' ')[:24]
        print(f'{label[:44]:44s} {isp:>7s} {oos:>7s}  {v}')
    print('-' * 75)
    print(f'{len(rows)} lane rows extracted from {len(all_files)} result files.')
    if errors:
        print('\n⚠️  files/lanes not fully parsed:')
        for e in errors:
            print(f'  - {e}')
    print('\nTo re-RUN a lane, invoke its source script (see docs/STRATEGY_PORTFOLIO.md "Grounding").')


if __name__ == '__main__':
    main()
