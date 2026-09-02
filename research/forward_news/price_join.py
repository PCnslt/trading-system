"""Forward news — price join + prediction generation (pre-registered hypotheses).

Joins each news event to live/recent 5-min price (via IBKR) at observed_at,
computes pre-event return + news velocity, then generates an immutable
prediction BEFORE the outcome window. Outcome resolution is a separate later step.
"""
import json, time, boto3
from datetime import datetime, timezone
import pandas as pd
from ib_insync import IB, Stock, util
from dotenv import load_dotenv
load_dotenv()

B = 'trading-datalake-920641308584'
s3 = boto3.client('s3', region_name='us-east-1')

def load_jsonl(key):
    try:
        body = s3.get_object(Bucket=B, Key=key)['Body'].read().decode()
        return [json.loads(l) for l in body.splitlines() if l.strip()]
    except s3.exceptions.NoSuchKey:
        return []

def save_jsonl(key, records):
    s3.put_object(Bucket=B, Key=key,
                  Body='\n'.join(json.dumps(r, ensure_ascii=False) for r in records) + '\n')

def fetch_5min(ib, sym, n=80):
    c = Stock(sym, 'SMART', 'USD')
    ib.qualifyContracts(c)
    bars = ib.reqHistoricalData(c, '', '7 D', '5 mins', 'TRADES', useRTH=True, formatDate=2)
    df = util.df(bars)
    if df.empty:
        return None
    df['date'] = pd.to_datetime(df['date'], utc=True)
    return df.set_index('date').sort_index()

def pre_event_state(df, obs_ts):
    """Return pre-event returns at 5/15/30/60m as of obs_ts (only bars <= obs_ts)."""
    obs = pd.to_datetime(obs_ts, utc=True)
    hist = df[df.index <= obs]
    if len(hist) < 2:
        return None
    close = hist['close'].iloc[-1]
    def r(n):
        if len(hist) >= n + 1:
            return (close - hist['close'].iloc[-(n+1)]) / hist['close'].iloc[-(n+1)]
        return None
    return dict(close=close, r5=r(1), r15=r(3), r30=r(6), r60=r(12))

def generate_prediction(event, state, velocity):
    """Pre-registered v0 hypotheses. Returns direction + probability (naive, not optimized)."""
    r5 = state['r5'] if state else None
    v = velocity
    if r5 is None or v is None:
        return dict(direction=None, predicted_probability=None, confidence='LOW', reason='insufficient_state')
    # H1/H2: velocity -> continuation vs reversal (naive sign)
    # Keep it simple: signal = sign of short reaction; hi-vel -> continue, lo-vel -> revert
    direction = 'up' if r5 >= 0 else 'down'
    if v >= 3:   # high velocity -> continuation
        pass
    else:        # low velocity -> reversal
        direction = 'down' if direction == 'up' else 'up'
    return dict(direction=direction, predicted_probability=0.52, confidence='LOW',
                reason=f'r5={r5:.4f} vel={v}')

def run():
    events = load_jsonl('news/events/events.jsonl')
    existing = {p['signal_id'] for p in load_jsonl('news/predictions/predictions.jsonl')}
    # group by symbol, compute velocity (count in 60m window before each event)
    from collections import defaultdict
    bysym = defaultdict(list)
    for e in events:
        bysym[e['symbol']].append(e)
    new_preds = []
    ib = IB(); ib.connect('127.0.0.1', 4001, clientId=99, timeout=15)
    for sym, evs in bysym.items():
        try:
            df = fetch_5min(ib, sym)
        except Exception:
            df = None
        for e in evs:
            sid = e['event_id'] + '_pred'
            if sid in existing:
                continue
            state = pre_event_state(df, e['observed_at_utc']) if df is not None else None
            # velocity: number of events for this symbol in the 60m before this event
            velocity = sum(1 for o in evs if o['observed_at_utc'] < e['observed_at_utc'])
            p = generate_prediction(e, state, velocity)
            new_preds.append(dict(
                signal_id=sid, timestamp=e['observed_at_utc'], symbol=sym,
                headline=e['headline'][:80], model_version='forward-v0',
                feature_snapshot_hash='na', **p,
                realized_return_5m=None, realized_return_15m=None, realized_return_30m=None,
                realized_return_60m=None, max_favorable_excursion=None,
                max_adverse_excursion=None, outcome_timestamp=None, status='UNRESOLVED'))
        time.sleep(0.5)
    ib.disconnect()
    if new_preds:
        save_jsonl('news/predictions/predictions.jsonl',
                   load_jsonl('news/predictions/predictions.jsonl') + new_preds)
    print(f'generated {len(new_preds)} new predictions (total ledger now '
          f'{len(load_jsonl("news/predictions/predictions.jsonl"))})')

if __name__ == '__main__':
    run()
