import os, sys
_ROOT = '/home/ubuntu/trading-system'
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()
import boto3
from hardening.rh_client import RHClient

RESTING = ('confirmed', 'queued', 'unconfirmed', 'partially_filled')
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
REGION = os.getenv('AWS_REGION', 'us-east-1')


def is_resting_stop(o):
    """A Robinhood protective stop: stop_price set, sell side, not yet terminal.

    NOTE: RH returns type='market' with a stop_price + trigger='stop' for a
    stop-market order — it does NOT return type='stop_market'. And a resting
    order's state is 'confirmed', never 'open'. Filtering on type/'open' finds
    NOTHING, which is exactly why the bot could not see its own stops.
    """
    return (o.get('side') == 'sell'
            and o.get('stop_price') not in (None, '', '0', '0.000000')
            and (o.get('state') or '').lower() in RESTING)


def monitor_managed_symbols():
    """{SYM} whose protection is the software sell-monitor, NOT a broker stop.

    Fractional positions cannot carry a Robinhood stop (whole-share only), so they
    are written to the book with monitor_stop=1 and protected by rh_sell_monitor.py
    running every 5 min. A broker-side stop would be IMPOSSIBLE for these — flagging
    them 'naked' is a false alarm.
    """
    t = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)
    out = set()
    lek = None
    while True:
        kw = dict(FilterExpression='begins_with(pk, :p)',
                  ExpressionAttributeValues={':p': 'RHPOS#'})
        if lek:
            kw['ExclusiveStartKey'] = lek
        resp = t.scan(**kw)
        for it in resp.get('Items', []):
            if it.get('sk') == 'current' and it.get('status') == 'OPEN' \
                    and (it.get('monitor_stop') == '1' or it.get('fractional') == '1'):
                out.add(it['pk'].split('#', 1)[1])
        lek = resp.get('LastEvaluatedKey')
        if not lek:
            break
    return out


rh = RHClient()
acct = rh._resolve_account()
pos = [p for p in rh.get_positions(acct) if float(p.get('quantity') or 0) > 0]
orders = rh.list_orders(acct)
stops = {}
for o in orders:
    if is_resting_stop(o):
        stops.setdefault(o['symbol'], []).append(o)
monitored = monitor_managed_symbols()

print(f'{"sym":7}{"qty":>9}{"entry":>9}{"stop":>9}{"risk$":>8}  protection')
total_exp = total_risk = 0.0
naked = []
for p in sorted(pos, key=lambda x: x['symbol']):
    s = p['symbol']
    q = float(p['quantity'])
    e = float(p.get('average_buy_price') or p.get('average_price') or 0)
    if e == 0:
        # fall back to the book entry price for fractional fills
        t = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)
        row = t.get_item(Key={'pk': f'RHPOS#{s}', 'sk': 'current'}).get('Item') or {}
        e = float(row.get('entry_price') or 0)
    total_exp += q * e
    st = stops.get(s)
    if st:
        sp = float(st[0]['stop_price'])
        risk = (e - sp) * q
        total_risk += risk
        print(f'{s:7}{q:>9.4f}{e:>9.2f}{sp:>9.2f}{risk:>8.2f}  broker-stop {st[0]["state"]}')
    elif s in monitored:
        print(f'{s:7}{q:>9.4f}{e:>9.2f}{"monitor":>9}{"":>8}  MONITOR (sell-monitor)')
    else:
        naked.append(s)
        print(f'{s:7}{q:>9.4f}{e:>9.2f}{"NONE":>9}{"":>8}  *** NAKED ***')

print(f'\npositions={len(pos)}  exposure=${total_exp:,.2f}  broker-stop risk=${total_risk:,.2f}')
print('*** ALL PROTECTED ***' if not naked else f'*** STILL NAKED: {naked} ***')
