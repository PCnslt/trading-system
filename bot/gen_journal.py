#!/usr/bin/env python3
"""Generate a human-readable trading journal from broker-truth (DynamoDB RHTRADE/RHPOS).

Written to research/TRADING_JOURNAL.md (committed + pushed so the owner can read it
any time) and printed. This is the single source of truth for the account's track
record: every closed round-trip with entry/exit/P&L, plus the currently-open
positions and their take-profit / stop levels.
"""
import os, sys, time
import datetime as dt
from zoneinfo import ZoneInfo
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()
import boto3

NY = ZoneInfo('America/New_York')
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
REGION = os.getenv('AWS_REGION', 'us-east-1')
t = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)


def scan(prefix):
    items, lek = [], None
    while True:
        kw = dict(FilterExpression='begins_with(pk,:p)',
                  ExpressionAttributeValues={':p': prefix})
        if lek:
            kw['ExclusiveStartKey'] = lek
        r = t.scan(**kw)
        items += r.get('Items', [])
        lek = r.get('LastEvaluatedKey')
        if not lek:
            break
    return items


def f(x, nd=4):
    try:
        return round(float(x), nd)
    except Exception:
        return None


now = dt.datetime.now(NY)

trades = scan('RHTRADE#')
closed = sorted([i for i in trades], key=lambda x: x.get('ts', 0))
realized = 0.0
lines = []
lines.append('# Trading Journal — Robinhood LIVE (account 515821577)')
lines.append('')
lines.append(f'Generated: {now.strftime("%Y-%m-%d %H:%M %Z")}')
lines.append('')
lines.append('## Closed trades (realized P&L)')
lines.append('')
lines.append('| symbol | entry date | exit date | entry | exit | qty | P&L $ | reason |')
lines.append('|---|---|---|---|---|---|---|---|')
for i in closed:
    sym = i['pk'].split('#', 1)[1]
    pnl = f(i.get('pnl_usd'))
    if pnl is not None:
        realized += pnl
    lines.append(f"| {sym} | {i.get('entry_date','')} | {i.get('exit_date','')} "
                 f"| {f(i.get('entry_price'))} | {f(i.get('exit_price'))} "
                 f"| {i.get('size_shares','')} | {pnl if pnl is not None else ''} "
                 f"| {i.get('exit_reason','')} |")
lines.append('')
lines.append(f'**Total realized P&L: ${realized:+.2f}**')
lines.append('')

# open positions
pos = [i for i in scan('RHPOS#') if i.get('sk') == 'current'
       and i.get('status') in ('OPEN', 'PENDING')]
lines.append('## Open positions')
lines.append('')
if pos:
    lines.append('| symbol | entry | size | stop (2xATR) | take-profit (+2ATR arm) |')
    lines.append('|---|---|---|---|---|')
    for p in pos:
        sym = p['pk'].split('#', 1)[1]
        ep = f(p.get('entry_price'))
        atr = f(p.get('atr'))
        stop = f(p.get('stop_price'))
        tp = f(ep + 2 * atr) if ep and atr else None
        lines.append(f"| {sym} | {ep} | {p.get('size_shares','')} | {stop} | {tp} |")
else:
    lines.append('(none)')
lines.append('')
lines.append('## Notes')
lines.append('')
lines.append('- Stop = 2xATR (broker stop where whole-share; synthetic via sell-monitor for fractional).')
lines.append('- Take-profit = trailing lock that arms at +2xATR, then trails at peak - 2xATR.')
lines.append('- Source of truth = Robinhood broker, reconciled to this journal by rh_order_verifier.')

out = '\n'.join(lines) + '\n'
path = os.path.join(_ROOT, 'research', 'TRADING_JOURNAL.md')
with open(path, 'w') as fh:
    fh.write(out)
print(out)
print(f'---\njournal written to {path}')
