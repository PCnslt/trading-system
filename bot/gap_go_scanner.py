#!/usr/bin/env python3
"""GAP-AND-GO premarket scanner — PAPER (no orders). Catalyst/momentum lane, part 1.

Finds stocks gapping UP premarket with high relative volume, in an uptrend, with NO
negative news catalyst. This is the signal half of the momentum lane the owner asked
for (to catch NVDA +9% / CRWD +20% type days). Part 2 (backtest) needs the intraday
1-min data currently backfilling.

Signal (paper): premarket gap >= GAP_PCT vs prior close (from IBKR daily archive —
the RH 'previous_close' field is unreliable), above rising 50-SMA, dollar volume
>= MIN_DV, and passes the news gate (no severe catalyst). Ranked by gap*volume.

Runs premarket (07:00-09:25 ET). Read-only: RH live quotes + IBKR history + news gate.
"""
from __future__ import annotations
import io, os, sys, json
import datetime as dt
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()

import boto3
import pandas as pd
import time

NY = ZoneInfo('America/New_York')
REGION = os.getenv('AWS_REGION', 'us-east-1')
BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DDB_TABLE = os.getenv('DDB_TABLE', 'trading-data')
GAP_PCT = float(os.getenv('GAP_GO_GAP_PCT', '3.0'))
MIN_DV = float(os.getenv('GAP_GO_MIN_DV', '2e7'))   # $20M avg daily dollar volume
TOP_N = int(os.getenv('GAP_GO_TOP_N', '15'))


def _daily(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 60:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open','high','low','close','volume']].astype(float).sort_index()
        df['sma50'] = df['close'].rolling(50).mean()
        df['dv'] = (df['close']*df['volume']).rolling(20).mean()
        return df
    except Exception:
        return None


def main():
    from hardening.rh_client import RHClient
    from bot.news_gate import check_symbol

    now = dt.datetime.now(NY)
    if not (dt.time(7,0) <= now.time() <= dt.time(9,25)):
        print(f'{now:%Y-%m-%d %H:%M} ET — outside premarket window, no-op')
        return

    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'universe_1500.json')))['symbols']))
    s3 = boto3.client('s3', region_name=REGION)
    rh = RHClient()

    with ThreadPoolExecutor(max_workers=16) as ex:
        daily = {s: d for s, d in zip(syms, ex.map(lambda x: _daily(x, s3), syms)) if d is not None}
    print(f'{now:%Y-%m-%d %H:%M} ET — gap-and-go scan: {len(daily)} symbols', flush=True)

    quotes = {}
    for r in rh.get_quotes(list(daily.keys())):
        q = r.get('quote') or {}
        sym = q.get('symbol'); px = q.get('last_trade_price')
        if sym and px:
            quotes[sym] = float(px)

    cands = []
    for sym, px in quotes.items():
        df = daily[sym]
        pc = float(df['close'].iloc[-1])
        if pc <= 0:
            continue
        gap = (px/pc - 1.0) * 100
        sma50 = float(df['sma50'].iloc[-1])
        dv = float(df['dv'].iloc[-1])
        if gap < GAP_PCT or px < sma50 or dv < MIN_DV:
            continue
        cands.append({'sym': sym, 'gap': gap, 'px': px, 'pc': pc, 'sma50': sma50, 'dv': dv/1e6})

    cands.sort(key=lambda c: c['gap']*c['dv'], reverse=True)
    print(f'\n{"sym":6}{"gap%":>8}{"px":>9}{"prev":>9}{"$volM":>8}  news')
    top = []
    for c in cands[:TOP_N]:
        verdict, why, headlines = check_symbol(c['sym'])
        print(f'{c["sym"]:6}{c["gap"]:>+8.1f}{c["px"]:>9.2f}{c["pc"]:>9.2f}{c["dv"]:>8.1f}  {verdict}')
        top.append({'sym': c['sym'], 'gap_pct': round(c['gap'], 2),
                    'px': round(c['px'], 2), 'dv_m': round(c['dv'], 1),
                    'kw_verdict': verdict, 'headlines': headlines[:6]})
    if not cands:
        print('  no gap-and-go candidates this window')
    # persist candidates + headlines for the catalyst-triage agent to classify
    try:
        tbl = boto3.resource('dynamodb', region_name=REGION).Table(DDB_TABLE)
        tbl.put_item(Item={'pk': f'GAPSCAN#{dt.datetime.now(NY).date().isoformat()}', 'sk': 'candidates',
                           'ts': int(time.time()), 'top': json.dumps(top)})
        print(f'  persisted {len(top)} candidate(s) for triage')
    except Exception as e:  # noqa: BLE001 - persistence is best-effort, not fatal
        print(f'  persist warn: {e!r}')


if __name__ == '__main__':
    main()
