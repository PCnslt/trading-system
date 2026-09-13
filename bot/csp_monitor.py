#!/usr/bin/env python3
"""F CSP take-profit / defend monitor — READ-ONLY, self-verifying.

Runs daily after the CSP is placed. Reads the ACTUAL broker state
(get_option_positions = ground truth) and the plan from state/csp_plan.json:
  - if no open option position -> say so (filled/assigned/expired?)
  - live put mark vs entry credit (open P&L)
  - TAKE PROFIT when mark <= 50% of entry credit (buy-to-close)
  - DEFEND/ROLL when F drops near the strike
Reads strike/expiry/entry from the plan file (single source of truth). Silent
if no plan exists. Never places an order. Refreshes the token on init failure.
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from infra.robinhood import load_creds, mcp_call, mcp_notify, refresh, save_creds

ACCT = '515821577'
SYM = 'F'
PLAN_FILE = '/home/ubuntu/trading-system/state/csp_plan.json'

def text_data(r):
    try:
        if not r or 'content' not in r:
            return None
        return json.loads(r['content'][0]['text']).get('data')
    except Exception:
        return None

def init_session(tok):
    ok, _, sid = mcp_call('initialize', {'protocolVersion':'2024-11-05','capabilities':{},
                         'clientInfo':{'name':'hermes-csp-mon','version':'1'}}, tok)
    if ok:
        mcp_notify('notifications/initialized', {}, tok, sid)
        return True, sid
    return False, None

def main():
    if not os.path.exists(PLAN_FILE):
        return 0  # no plan yet — stay silent
    plan = json.load(open(PLAN_FILE))
    entry = float(plan.get('bid', 0.11))
    strike = float(plan.get('strike', 13.5))
    expiry = plan.get('expiry', '2026-09-18')
    tp_mark = float(plan.get('take_profit_mark', round(entry * 0.5, 2)))
    defend = float(plan.get('defend_price', round(strike * 1.03, 2)))

    creds = load_creds()
    if 'access_token' not in creds:
        print(f'[{time.strftime("%H:%M")}] CSP monitor: no token'); return 1
    tok = creds['access_token']
    ok, sid = init_session(tok)
    if not ok:
        okr, newtok, err = refresh(creds)
        if not okr:
            print(f'[{time.strftime("%H:%M")}] CSP monitor: init+refresh failed: {err[:120]}'); return 1
        save_creds({k: v for k, v in {'access_token': newtok.get('access_token'),
                   'refresh_token': newtok.get('refresh_token'), 'expires_in': newtok.get('expires_in'),
                   'expires_at': newtok.get('expires_at'), 'scope': newtok.get('scope'),
                   'token_json': json.dumps(newtok)}.items() if v is not None})
        tok = newtok['access_token']
        ok, sid = init_session(tok)
        if not ok:
            print(f'[{time.strftime("%H:%M")}] CSP monitor: init still failing'); return 1

    # 1. ground truth: do we actually hold an open option position?
    ok, r = mcp_call('tools/call', {'name':'get_option_positions',
                     'arguments':{'account_number': ACCT, 'nonzero': True}}, tok, sid)
    poslist = (text_data(r) or {}).get('positions', [])
    if not poslist:
        print(f'[{time.strftime("%H:%M")}] CSP F ${strike} @{expiry}: NO open option position — filled/assigned/expired? recheck')
        return 0
    # log the raw position fields (first time only) so we learn the real schema
    raw = json.dumps(poslist, default=str)[:400]
    print(f'[{time.strftime("%H:%M")}] positions ({len(poslist)}): {raw}')

    # 2. F price
    ok, r = mcp_call('tools/call', {'name':'get_equity_quotes',
                     'arguments':{'symbols':[SYM]}}, tok, sid)
    f = float(json.loads(r['content'][0]['text'])['data']['results'][0]['quote']['last_trade_price'])

    # 3. put mark
    ok, r = mcp_call('tools/call', {'name':'get_option_chains','arguments':{'underlying_symbol':SYM}}, tok, sid)
    cid = json.loads(r['content'][0]['text'])['data']['chains'][0]['id']
    ok, r = mcp_call('tools/call', {'name':'get_option_instruments','arguments':{'chain_id':cid,'type':'put','expiration_dates':expiry,'strike_price':f'{strike:.4f}'}}, tok, sid)
    inst = (text_data(r) or {}).get('instruments', [])
    if not inst:
        print(f'[{time.strftime("%H:%M")}] CSP F ${strike} @{expiry}: put gone (expired/assigned)'); return 0
    oid = inst[0]['id']
    ok, r = mcp_call('tools/call', {'name':'get_option_quotes','arguments':{'instrument_ids':[oid]}}, tok, sid)
    mark = float(json.loads(r['content'][0]['text'])['data']['results'][0]['quote']['mark_price'])

    pnl = entry - mark
    line = f'CSP F ${strike} @{expiry}: F={f:.2f} put mark={mark:.2f} (entry {entry:.2f}) P&L={pnl:+.2f}/contract'
    if mark <= tp_mark:
        line += f'  *** TAKE PROFIT (mark {mark} <= {tp_mark}) — buy-to-close now ***'
    elif f < defend:
        line += f'  *** DEFEND: F {f:.2f} below {defend} — roll or accept assignment ***'
    print(line)
    return 0

if __name__ == '__main__':
    sys.exit(main())
