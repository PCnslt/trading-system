#!/usr/bin/env python3
"""Kill-switch ledger + heartbeat (dead-man's switch).

A single source of truth for halting the live bots. The entry/exit lanes call
`is_killed()` before acting; `kill()`/`resume()` write an audited ledger entry so every
halt/override is recorded with {trigger, reason, operator, resume-condition}.
"""
import os, sys, time
import datetime as dt
from zoneinfo import ZoneInfo
import boto3

ET = ZoneInfo('America/New_York')
REGION = os.getenv('AWS_REGION', 'us-east-1')
TABLE = os.getenv('DYNAMO_TABLE', 'trading-data')

def _t():
    return boto3.resource('dynamodb', region_name=REGION).Table(TABLE)

def state():
    it = _t().get_item(Key={'pk': 'KILLSWITCH', 'sk': 'current'}).get('Item') or {}
    return it.get('state', 'ACTIVE'), it

def is_killed():
    s, _ = state()
    return s == 'KILLED'

def kill(reason, operator='auto'):
    ts = dt.datetime.now(ET).isoformat(timespec='seconds')
    _t().put_item(Item={'pk': 'KILLSWITCH', 'sk': 'current', 'state': 'KILLED',
                        'reason': reason, 'operator': operator, 'ts': ts})
    _t().put_item(Item={'pk': 'KILLSWITCH', 'sk': ts, 'action': 'KILL',
                        'reason': reason, 'operator': operator})
    return ts

def resume(reason, operator='auto'):
    ts = dt.datetime.now(ET).isoformat(timespec='seconds')
    _t().put_item(Item={'pk': 'KILLSWITCH', 'sk': 'current', 'state': 'ACTIVE',
                        'reason': reason, 'operator': operator, 'ts': ts})
    _t().put_item(Item={'pk': 'KILLSWITCH', 'sk': ts, 'action': 'RESUME',
                        'reason': reason, 'operator': operator})
    return ts

def heartbeat():
    _t().put_item(Item={'pk': 'HEARTBEAT', 'sk': 'latest',
                        'ts': int(time.time())})

def heartbeat_age_s():
    it = _t().get_item(Key={'pk': 'HEARTBEAT', 'sk': 'latest'}).get('Item') or {}
    ts = it.get('ts', 0)
    return int(time.time()) - int(ts)

if __name__ == '__main__':
    a = sys.argv[1] if len(sys.argv) > 1 else 'state'
    if a == 'state':
        s, it = state()
        print(f'{s}  {it.get("reason","")}  {it.get("ts","")}')
    elif a == 'kill':
        print(kill(' '.join(sys.argv[2:]) or 'manual'))
    elif a == 'resume':
        print(resume(' '.join(sys.argv[2:]) or 'manual'))
    elif a == 'beat':
        heartbeat(); print('heartbeat written')
    elif a == 'age':
        print(f'heartbeat age: {heartbeat_age_s()}s')
