#!/usr/bin/env python3
"""Read/write state for the independent catalyst-triage agent.

The gap scanner persists candidates+headlines to GAPSCAN#<date>. The triage agent
(a separate cron) classifies each and writes GAPTRIAGE#<sym>. The paper forward-test
reads those verdicts. This module is the only thing that touches the triage tables.
"""
import json, os, sys, time
import datetime as dt

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()
import boto3

TABLE = os.getenv('DDB_TABLE', 'trading-data')
REGION = os.getenv('AWS_REGION', 'us-east-1')


def _t():
    return boto3.resource('dynamodb', region_name=REGION).Table(TABLE)


def read():
    tbl = _t()
    today = dt.date.today().isoformat()
    item = tbl.get_item(Key={'pk': f'GAPSCAN#{today}', 'sk': 'candidates'}).get('Item')
    if not item:
        print('NO_CANDIDATES')
        return
    for c in json.loads(item.get('top', '[]')):
        print(f"{c['sym']}|gap{c['gap_pct']}%|${c['dv_m']}M")
        for h in c.get('headlines', []):
            print(f"  - {h}")


def write(sym, verdict, reason):
    tbl = _t()
    tbl.put_item(Item={
        'pk': f'GAPTRIAGE#{sym.upper()}',
        'sk': dt.date.today().isoformat(),
        'verdict': verdict, 'reason': reason, 'ts': int(time.time()),
    })
    print(f'wrote GAPTRIAGE#{sym.upper()} = {verdict}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('usage: triage_io.py read | write SYM VERDICT reason...')
        sys.exit(1)
    if sys.argv[1] == 'read':
        read()
    elif sys.argv[1] == 'write' and len(sys.argv) >= 4:
        write(sys.argv[2], sys.argv[3], ' '.join(sys.argv[4:]))
    else:
        print('usage: triage_io.py read | write SYM VERDICT reason...')
        sys.exit(1)
