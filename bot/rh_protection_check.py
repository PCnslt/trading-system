import os, sys
_ROOT = '/home/ubuntu/trading-system'
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()
from hardening.rh_client import RHClient

RESTING = ('confirmed', 'queued', 'unconfirmed', 'partially_filled')


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


rh = RHClient()
acct = rh._resolve_account()
pos = [p for p in rh.get_positions(acct) if float(p.get('quantity') or 0) > 0]
orders = rh.list_orders(acct)
stops = {}
for o in orders:
    if is_resting_stop(o):
        stops.setdefault(o['symbol'], []).append(o)

print(f'{"sym":7}{"qty":>5}{"entry":>9}{"stop":>9}{"risk$":>8}  state')
total_exp = total_risk = 0.0
naked = []
for p in sorted(pos, key=lambda x: x['symbol']):
    s = p['symbol']
    q = int(float(p['quantity']))
    e = float(p.get('average_buy_price') or 0)
    total_exp += q * e
    st = stops.get(s)
    if not st:
        naked.append(s)
        print(f'{s:7}{q:>5}{e:>9.2f}{"NONE":>9}{"":>8}  *** NAKED ***')
        continue
    sp = float(st[0]['stop_price'])
    risk = (e - sp) * q
    total_risk += risk
    print(f'{s:7}{q:>5}{e:>9.2f}{sp:>9.2f}{risk:>8.2f}  {st[0]["state"]}')

print(f'\npositions={len(pos)}  exposure=${total_exp:,.2f}  max risk if all stops hit=${total_risk:,.2f}')
print('*** ALL PROTECTED ***' if not naked else f'*** STILL NAKED: {naked} ***')
