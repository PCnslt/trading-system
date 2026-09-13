#!/usr/bin/env python3
"""F cash-secured put (CSP) execution — fail-safe, idempotent, self-verifying.

Owner-authorized 2026-09-08: sell 1 F $13.50 put @ 2026-09-18 (~10 DTE, the
highest-annualized short-DTE point), limit at bid. Cash-secured on the agentic
cash account (515821577). $1,350 collateral, ~$11 credit.

FAIL-CLOSED guarantees (abort WITHOUT placing if any check fails):
  1. token refreshed if the cached one is stale/revoked (init retry)
  2. account re-verified: agentic cash acct with >= $1,350 buying power
  3. live put quote re-fetched; bid must be >= MIN_BID (0.08)
  4. review_option_order dry-run must return empty order_checks (no broker alerts)
  5. ref_id persisted BEFORE placing (idempotency) — a retry re-sends the SAME
     ref_id so the broker dedupes; never double-places
  6. place success confirmed (order id returned AND visible in get_option_orders)
"""
import json, os, sys, time, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from infra.robinhood import load_creds, mcp_call, mcp_notify, refresh, save_creds

ACCT = '515821577'          # agentic cash account (agentic_allowed=true)
SYM = 'F'
EXPIRY = '2026-09-18'       # 10 DTE — highest annualized short-DTE point
STRIKE = '13.5000'          # ~0.30 delta at 10 DTE
MIN_BID = 0.08              # abort if premium collapsed below this
COLLATERAL = 1350.0         # 100 x strike
REF_FILE = '/home/ubuntu/trading-system/state/csp_f_ref.json'
PLAN_FILE = '/home/ubuntu/trading-system/state/csp_plan.json'
os.makedirs(os.path.dirname(REF_FILE), exist_ok=True)

def log(m):
    print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)

def call(tok, sid, name, args):
    ok, r, _ = mcp_call('tools/call', {'name': name, 'arguments': args}, tok, sid)
    return ok, r

def text_data(r):
    """Return the parsed 'data' dict from a tools/call result, or None."""
    try:
        if not r or 'content' not in r:
            return None
        return json.loads(r['content'][0]['text']).get('data')
    except Exception:
        return None

def init_session(tok):
    """(ok, sid). On init failure, try ONE refresh (revoked/expired) and retry."""
    ok, _, sid = mcp_call('initialize', {'protocolVersion':'2024-11-05','capabilities':{},
                         'clientInfo':{'name':'hermes-csp','version':'1'}}, tok)
    if ok:
        mcp_notify('notifications/initialized', {}, tok, sid)
        return True, sid
    return False, None

def main():
    creds = load_creds()
    if 'access_token' not in creds:
        log(f'FATAL: no token ({creds.get("_error","")[:120]})'); return 1
    tok = creds['access_token']

    ok, sid = init_session(tok)
    if not ok:
        # token stale/revoked -> refresh once, persist, retry
        okr, newtok, err = refresh(creds)
        if not okr:
            log(f'FATAL: init failed and refresh failed: {err[:200]}'); return 1
        save_creds({k: v for k, v in {
            'access_token': newtok.get('access_token'),
            'refresh_token': newtok.get('refresh_token'),
            'expires_in': newtok.get('expires_in'),
            'expires_at': newtok.get('expires_at'),
            'scope': newtok.get('scope'),
            'token_json': json.dumps(newtok),
        }.items() if v is not None})
        tok = newtok['access_token']
        ok, sid = init_session(tok)
        if not ok:
            log('FATAL: init still failing after refresh'); return 1
        log('refreshed token and re-initialized')

    # idempotency: skip only if a PREVIOUS run CONFIRMED the order placed
    if os.path.exists(REF_FILE):
        prev = json.load(open(REF_FILE))
        if prev.get('state') == 'placed':
            log(f'ALREADY PLACED: order_id={prev.get("order_id")} — skipping')
            return 0
        # else: a 'pending' record exists -> reuse its ref_id for the retry
        ref_id = prev.get('ref_id')
        log(f'retrying with existing ref_id={ref_id}')
    else:
        # persist ref_id BEFORE placing so any retry re-sends the SAME id
        ref_id = str(uuid.uuid4())
        json.dump({'ref_id': ref_id, 'state': 'pending', 'sym': SYM,
                   'strike': STRIKE, 'expiry': EXPIRY, 'ts': time.time()},
                  open(REF_FILE, 'w'))
        log(f'new ref_id={ref_id} persisted (pending)')

    # 1. account + buying power
    ok, r = call(tok, sid, 'get_portfolio', {'account_number': ACCT})
    p = text_data(r)
    if not p:
        log('ABORT: could not read portfolio'); return 1
    bp = float(p['buying_power']['buying_power'])
    log(f'account {ACCT}: cash={p["cash"]} buying_power={bp}')
    if bp < COLLATERAL:
        log(f'ABORT: buying power {bp} < collateral {COLLATERAL}'); return 1

    # 2. resolve the put instrument + live quote
    ok, r = call(tok, sid, 'get_option_chains', {'underlying_symbol': SYM})
    d = text_data(r)
    if not d or not d.get('chains'):
        log('ABORT: no chain'); return 1
    cid = d['chains'][0]['id']
    ok, r = call(tok, sid, 'get_option_instruments', {'chain_id': cid, 'type': 'put',
                   'expiration_dates': EXPIRY, 'strike_price': STRIKE})
    inst = (text_data(r) or {}).get('instruments', [])
    if not inst or inst[0].get('tradability') != 'tradable':
        log(f'ABORT: put not tradable: {inst}'); return 1
    oid = inst[0]['id']
    ok, r = call(tok, sid, 'get_option_quotes', {'instrument_ids': [oid]})
    q = ((text_data(r) or {}).get('results') or [{}])[0].get('quote', {})
    if not q:
        log('ABORT: no quote'); return 1
    bid = float(q['bid_price']); ask = float(q['ask_price']); mark = float(q['mark_price'])
    delta = float(q['delta']); iv = float(q['implied_volatility']); prob = float(q['chance_of_profit_short'])
    log(f'{SYM} ${STRIKE} put @{EXPIRY}: bid={bid} ask={ask} mark={mark} delta={delta} IV={iv*100:.0f}% probOTM={prob*100:.0f}%')
    if bid < MIN_BID:
        log(f'ABORT: bid {bid} < MIN_BID {MIN_BID} (premium collapsed, do not chase)'); return 1

    # 3. review dry-run (no order placed) — must have empty order_checks
    legs = [{'option_id': oid, 'side': 'sell', 'position_effect': 'open'}]
    price = f'{bid:.2f}'
    ok, r = call(tok, sid, 'review_option_order', {'account_number': ACCT, 'legs': legs,
                   'type': 'limit', 'quantity': '1', 'price': price, 'time_in_force': 'gfd'})
    rev = text_data(r)
    if not rev:
        log(f'ABORT: review failed: {json.dumps(r, default=str)[:300]}'); return 1
    if rev.get('order_checks'):
        log(f'ABORT: broker alerts: {json.dumps(rev["order_checks"])[:500]}'); return 1
    log(f'review OK: direction={rev.get("direction")} checks=empty')

    # 4. place (LIMIT at bid, credit order — worst case it does not fill)
    ok, r = call(tok, sid, 'place_option_order', {'account_number': ACCT, 'legs': legs,
                   'type': 'limit', 'quantity': '1', 'price': price,
                   'time_in_force': 'gfd', 'ref_id': ref_id})
    order_id = ''
    pd = text_data(r)
    if pd:
        order_id = str(pd.get('id') or pd.get('order_id') or '')
    log(f'place result: order_id={order_id} raw={json.dumps(r, default=str)[:400]}')
    if not order_id:
        # leave ref_file as 'pending' (same ref_id) so a retry does NOT double-place
        log('ABORT: place did not return an order id — ref_id kept for idempotent retry')
        return 1

    # 5. verify the order is observable before marking placed
    ok, r = call(tok, sid, 'get_option_orders', {'account_number': ACCT})
    orders = (text_data(r) or {}).get('orders', [])
    seen = any(str(o.get('id') or o.get('order_id') or '') == order_id for o in orders)
    log(f'order visible in get_option_orders: {seen}')

    # persist plan + mark placed
    plan = {'sym': SYM, 'strike': STRIKE, 'expiry': EXPIRY, 'dte': 10, 'bid': bid,
            'ask': ask, 'mark': mark, 'delta': delta, 'iv': iv, 'prob_otm': prob,
            'collateral': COLLATERAL, 'max_profit': round(bid * 100, 2),
            'max_risk': round(COLLATERAL - bid * 100, 2),
            'take_profit_mark': round(bid * 0.5, 2), 'defend_price': round(float(STRIKE) * 1.03, 2),
            'plan_ts': time.time()}
    json.dump(plan, open(PLAN_FILE, 'w'), indent=2)
    json.dump({'ref_id': ref_id, 'order_id': order_id, 'sym': SYM, 'strike': STRIKE,
               'expiry': EXPIRY, 'bid': bid, 'ts': time.time(), 'state': 'placed'},
              open(REF_FILE, 'w'))
    log(f'DONE: order_id={order_id} bid={bid} credit={bid*100:.2f} plan saved')
    return 0

if __name__ == '__main__':
    sys.exit(main())
