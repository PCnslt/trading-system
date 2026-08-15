#!/usr/bin/env python3
"""Options-on-futures research scaffold — chain analysis + vol-surface gap map.

Reads the ALREADY-COLLECTED chain metadata (12 underlyings) and the underlying
futures daily bars to produce a chain-analysis summary. Does NOT (and cannot)
compute an IV/vol surface — that needs the paid options BARS/QUOTES subscription,
which is deliberately NOT requested until an options edge is actually worth
pursuing (see FUTURES_OPTIONS_PLAN.md).

Chain metadata (free, already flowing): options/<sym>/chains.json (strikes +
expiries via reqSecDefOptParams) + OPTCHAIN#<sym> (DynamoDB hot summary).
Underlying spot: S3 futures-bars/daily/<sym>/<latest>.json close (fallback
QUOTE#<sym> latest).

Outputs (paper-only, no orders):
  research/options_plan_results.json
  research/FUTURES_OPTIONS_PLAN.md
"""
import os
import sys
import json
import datetime as dt

import boto3
from dotenv import load_dotenv

REPO = os.environ.get('TRADING_REPO', os.path.expanduser('~/trading-system'))
load_dotenv(os.path.join(REPO, '.env'))
load_dotenv()

S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')

# The 12 liquid futures-options underlyings in the registry (options=True).
UNDERLYINGS = ['ES', 'NQ', 'CL', 'NG', 'GC', 'SI', 'HG', 'ZB', 'ZN', 'ZC', 'ZS', 'ZW']


def s3_get(key):
    s3 = boto3.client('s3', region_name=AWS_REGION)
    try:
        return json.loads(s3.get_object(Bucket=S3_BUCKET, Key=key)['Body'].read())
    except Exception:  # noqa: BLE001
        return None


def list_daily_dates(sym):
    s3 = boto3.client('s3', region_name=AWS_REGION)
    prefix = f'futures-bars/daily/{sym}/'
    dates = []
    for p in s3.get_paginator('list_objects_v2').paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for o in p.get('Contents', []):
            fname = o['Key'].rsplit('/', 1)[-1]
            if fname.endswith('.json'):
                dates.append(fname[:-5])
    return sorted(dates)


def underlying_spot(sym):
    """Latest futures daily close for `sym` (fallback: QUOTE# latest)."""
    dates = list_daily_dates(sym)
    if dates:
        bar = s3_get(f'futures-bars/daily/{sym}/{dates[-1]}.json')
        if bar and bar.get('close') is not None:
            return float(bar['close']), dates[-1]
    # fallback to hot QUOTE# (L1-live symbols only)
    try:
        from boto3.dynamodb.conditions import Key
        t = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
        r = t.query(KeyConditionExpression=Key('pk').eq(f'QUOTE#{sym}'),
                    ScanIndexForward=False, Limit=1)
        it = r.get('Items', [])
        if it and it[0].get('price') is not None:
            return float(it[0]['price']), 'quote'
    except Exception:  # noqa: BLE001
        pass
    return None, None


def moneyness_buckets(strikes, spot):
    """Count strikes within ±5%/±10%/±20% of spot (near-ATM coverage)."""
    if spot is None:
        return None
    return {
        'within_5pct': sum(1 for s in strikes if abs(s - spot) / spot <= 0.05),
        'within_10pct': sum(1 for s in strikes if abs(s - spot) / spot <= 0.10),
        'within_20pct': sum(1 for s in strikes if abs(s - spot) / spot <= 0.20),
        'atm_strike': min(strikes, key=lambda s: abs(s - spot)) if strikes else None,
    }


def main():
    rows = []
    for sym in UNDERLYINGS:
        chain = s3_get(f'options/{sym}/chains.json')
        if not chain:
            rows.append({'sym': sym, 'error': 'no chain metadata'})
            continue
        strikes = [s for s in chain.get('strikes', []) if s is not None]
        exps = chain.get('expirations', [])
        spot, spot_src = underlying_spot(sym)
        mb = moneyness_buckets(strikes, spot)
        rows.append({
            'sym': sym,
            'n_expiries': len(exps),
            'n_strikes': len(strikes),
            'strike_min': min(strikes) if strikes else None,
            'strike_max': max(strikes) if strikes else None,
            'expiry_min': exps[0] if exps else None,
            'expiry_max': exps[-1] if exps else None,
            'spot': spot, 'spot_src': spot_src,
            'moneyness': mb,
        })

    out = {
        'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'underlyings': rows,
    }
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, 'options_plan_results.json'), 'w') as fh:
        json.dump(out, fh, indent=2, default=str)
    with open(os.path.join(here, 'FUTURES_OPTIONS_PLAN.md'), 'w') as fh:
        fh.write(render_markdown(out))

    for r in rows:
        if 'error' in r:
            print(f"{r['sym']}: {r['error']}")
            continue
        mb = r['moneyness'] or {}
        print(f"{r['sym']}: {r['n_expiries']} exps, {r['n_strikes']} strikes "
              f"[{r['strike_min']}..{r['strike_max']}] spot={r['spot']} "
              f"±5%={mb.get('within_5pct')} ±10%={mb.get('within_10pct')} "
              f"ATM={mb.get('atm_strike')}")
    print('\nWrote options_plan_results.json + FUTURES_OPTIONS_PLAN.md')


def render_markdown(out):
    L = []
    L.append('# Options Lane — plan (what is possible now vs what needs a subscription)\n')
    L.append(f'> Generated {out["generated_at"]}. Futures-options are PAPER/RESEARCH only. '
             f'Equity-options research lives on the LAPTOP (Robinhood MCP, Option Level 2).\n')
    L.append('## What is collected NOW (free, already flowing)\n')
    L.append('- **Chain metadata** for 12 liquid futures-options underlyings: '
             '`options/<sym>/chains.json` (full strike + expiry axes via '
             '`reqSecDefOptParams`) + `OPTCHAIN#<sym>` (DynamoDB hot summary).\n')
    L.append('- **Underlying futures bars** (`futures-bars/daily/<sym>/`) for spot/ATM context.\n')
    L.append('\n## Chain analysis (scaffold)\n')
    L.append('| Sym | Exps | Strikes | Strike range | Expiry range | Spot | ±5% | ±10% | ATM strike |')
    L.append('|---|---|---|---|---|---|---|---|---|')
    for r in out['underlyings']:
        if 'error' in r:
            L.append(f"| {r['sym']} | — | — | — | — | — | — | — | {r['error']} |")
            continue
        mb = r['moneyness'] or {}
        L.append(f"| {r['sym']} | {r['n_expiries']} | {r['n_strikes']} | "
                 f"{r['strike_min']}–{r['strike_max']} | {r['expiry_min']}–{r['expiry_max']} | "
                 f"{r['spot'] if r['spot'] is not None else '—'} | "
                 f"{mb.get('within_5pct', '—')} | {mb.get('within_10pct', '—')} | "
                 f"{mb.get('atm_strike', '—')} |")
    L.append('\n## Vol-surface / greeks: NOT computable today (honest gap)\n')
    L.append('- We have the chain SKELETON (strikes × expiries), not option PRICES. An IV/vol '
             'surface, greeks, skew/term-structure, and any options backtest require **historical '
             'option BARS + real-time option quotes** — a **separate paid IBKR subscription**, NOT '
             'in the CME Group L1 bundle. `options_chains.py` does not and cannot request them.\n')
    L.append('- **Decision: do NOT request the bars subscription yet.** Per the data-integrity '
             'standing rule, we only pay when an options edge is actually worth pursuing. Chain '
             'analysis can screen for *structure* (liquid strikes near ATM, expiry ladder length) '
             'but cannot validate a P&L edge without prices.\n')
    L.append('\n## What needs a subscription (flag, do NOT buy yet)\n')
    L.append('| Subscription | Unlocks | Needed for | Status |')
    L.append('|---|---|---|---|')
    L.append('| Historical options bars | vol surface, IV history, options backtests | '
             'any vol/skew/term-structure or options-selling edge | NOT requested |')
    L.append('| Real-time option quotes | live greeks, IV, order-flow | intraday options execution | NOT requested |')
    L.append('| L2 market depth | order book / flow | depth-based options edges | NOT requested |')
    L.append('\n## Equity-options (laptop, Robinhood MCP Option Level 2)\n')
    L.append('- The laptop Hermes owns equity-options research + order placement (RH L2: CSP→CC wheel). '
             'The VPS has NO Robinhood access. Any equity-options edge is validated on the laptop side.\n')
    L.append('- If a **futures-options** edge candidate emerges from chain analysis (e.g. a persistent '
             'term-structure or strike-density pattern worth pricing), flag it — it is exactly the '
             'case that would justify the paid bars subscription. Until then: no purchase.\n')
    L.append('\n## Next steps\n')
    L.append('- Re-run `options_plan.py` weekly (after `options_chains.py` refreshes) to track expiry-ladder '
             'and ATM-coverage drift.\n')
    L.append('- No options edge → no subscription. This file is the standing evidence for that decision.\n')
    return '\n'.join(L)


if __name__ == '__main__':
    main()
