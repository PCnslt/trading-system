"""Single source of truth for the futures symbol universe (config-driven registry).

Every collector — contract resolver, session calendar, historical backfill,
daily delta, L1 tick recorder, options-chain metadata — derives its symbols from
`FUTURES` here. **Adding a symbol = edit this one list** (optionally set its
contract months / options flag). No code edits elsewhere.

Fields per row:
  sym          IBKR root symbol
  exchange     listing exchange (CME / CBOT / NYMEX / COMEX)
  asset_class  index | rates | energy | metals | ags | fx
  months       valid contract months, ascending (front-month resolution +
               rollover-schedule derivation). Default quarterly (3,6,9,12).
  options      True = liquid futures-options underlying (reqSecDefOptParams).

Subscription coverage is HONEST. The paper account DUR193467's "CME Group"
bundle covers top-of-book L1 + historical bars for CME / CBOT / COMEX / NYMEX,
but a few symbols in the full universe do NOT resolve (verified 2026-08-14 via
reqContractDetails). They are kept in this list (so the registry stays the full
universe) and the collectors skip them with an "EMPTY chain" log — never
fabricate bars. Known gaps:
  - FX majors 6E/6J/6B/6A/6C/6S/6N -> "No security definition found" (only 6M
    resolves). Likely a separate CME FX-futures entitlement.
  - Micro silver has no separate root: it is the SI chain's tradingClass 'SIL'
    (multiplier 1000 vs full SI 5000) — accessed via the SI chain, not a 'SIL'
    symbol.

Exports (for backward-compat with existing callers):
  FUTURES            list of dicts (canonical)
  SYMBOLS            list of (sym, exchange) tuples (matches old shape)
  MONTHS             {sym: months tuple}
  ASSET_CLASSES      {sym: asset_class}
  OPTION_UNDERLYINGS [sym, ...] (options=True)
"""

DEFAULT_MONTHS = (3, 6, 9, 12)           # quarterly H/M/U/Z
_MONTHLY = tuple(range(1, 13))            # 1..12

FUTURES = [
    # --- CME equity index (quarterly) ---
    dict(sym='ES',  exchange='CME',  asset_class='index',  months=(3, 6, 9, 12), options=True),
    dict(sym='NQ',  exchange='CME',  asset_class='index',  months=(3, 6, 9, 12), options=True),
    dict(sym='MES', exchange='CME',  asset_class='index',  months=(3, 6, 9, 12), options=False),
    dict(sym='MNQ', exchange='CME',  asset_class='index',  months=(3, 6, 9, 12), options=False),
    dict(sym='RTY', exchange='CME',  asset_class='index',  months=(3, 6, 9, 12), options=False),
    dict(sym='YM',  exchange='CBOT', asset_class='index',  months=(3, 6, 9, 12), options=False),
    dict(sym='M2K', exchange='CME',  asset_class='index',  months=(3, 6, 9, 12), options=False),
    dict(sym='MYM', exchange='CBOT', asset_class='index',  months=(3, 6, 9, 12), options=False),

    # --- CBOT rates (quarterly) ---
    dict(sym='ZB', exchange='CBOT', asset_class='rates', months=(3, 6, 9, 12), options=True),
    dict(sym='ZN', exchange='CBOT', asset_class='rates', months=(3, 6, 9, 12), options=True),
    dict(sym='ZF', exchange='CBOT', asset_class='rates', months=(3, 6, 9, 12), options=False),
    dict(sym='ZT', exchange='CBOT', asset_class='rates', months=(3, 6, 9, 12), options=False),
    dict(sym='UB', exchange='CBOT', asset_class='rates', months=(3, 6, 9, 12), options=False),
    dict(sym='TN', exchange='CBOT', asset_class='rates', months=(3, 6, 9, 12), options=False),

    # --- NYMEX energy (monthly) ---
    dict(sym='CL', exchange='NYMEX', asset_class='energy', months=_MONTHLY, options=True),
    dict(sym='NG', exchange='NYMEX', asset_class='energy', months=_MONTHLY, options=True),
    dict(sym='RB', exchange='NYMEX', asset_class='energy', months=_MONTHLY, options=False),
    dict(sym='HO', exchange='NYMEX', asset_class='energy', months=_MONTHLY, options=False),
    dict(sym='QM', exchange='NYMEX', asset_class='energy', months=_MONTHLY, options=False),
    dict(sym='QG', exchange='NYMEX', asset_class='energy', months=_MONTHLY, options=False),

    # --- COMEX / NYMEX metals ---
    dict(sym='GC',  exchange='COMEX', asset_class='metals', months=(2, 4, 6, 8, 10, 12), options=True),
    dict(sym='SI',  exchange='COMEX', asset_class='metals', months=(1, 3, 5, 7, 9, 12), options=True),
    dict(sym='HG',  exchange='COMEX', asset_class='metals', months=_MONTHLY, options=True),
    dict(sym='PL',  exchange='NYMEX', asset_class='metals', months=(1, 4, 7, 10), options=False),
    dict(sym='PA',  exchange='NYMEX', asset_class='metals', months=(3, 6, 9, 12), options=False),
    dict(sym='MGC', exchange='COMEX', asset_class='metals', months=(2, 4, 6, 8, 10, 12), options=False),
    # NOTE: micro silver (1000 oz) has NO separate root — it is the SI chain's
    # tradingClass 'SIL' (multiplier 1000 vs full SI 5000). Access via SI chain.

    # --- CBOT / CME ags ---
    dict(sym='ZC', exchange='CBOT', asset_class='ags', months=(3, 5, 7, 9, 12), options=True),
    dict(sym='ZW', exchange='CBOT', asset_class='ags', months=(3, 5, 7, 9, 12), options=True),
    dict(sym='ZS', exchange='CBOT', asset_class='ags', months=(1, 3, 5, 7, 8, 9, 11), options=True),
    dict(sym='ZM', exchange='CBOT', asset_class='ags', months=(1, 3, 5, 7, 8, 9, 10, 12), options=False),
    dict(sym='ZL', exchange='CBOT', asset_class='ags', months=(1, 3, 5, 7, 8, 9, 10, 12), options=False),
    dict(sym='ZO', exchange='CBOT', asset_class='ags', months=(3, 5, 7, 9, 12), options=False),
    dict(sym='HE', exchange='CME',  asset_class='ags', months=(2, 4, 5, 6, 7, 8, 10, 12), options=False),
    dict(sym='LE', exchange='CME',  asset_class='ags', months=(2, 4, 6, 8, 10, 12), options=False),

    # --- CME FX (quarterly; only 6M resolves on the paper account) ---
    dict(sym='6E', exchange='CME', asset_class='fx', months=(3, 6, 9, 12), options=True),   # GAP
    dict(sym='6J', exchange='CME', asset_class='fx', months=(3, 6, 9, 12), options=False),  # GAP
    dict(sym='6B', exchange='CME', asset_class='fx', months=(3, 6, 9, 12), options=False),  # GAP
    dict(sym='6A', exchange='CME', asset_class='fx', months=(3, 6, 9, 12), options=False),  # GAP
    dict(sym='6C', exchange='CME', asset_class='fx', months=(3, 6, 9, 12), options=False),  # GAP
    dict(sym='6S', exchange='CME', asset_class='fx', months=(3, 6, 9, 12), options=False),  # GAP
    dict(sym='6N', exchange='CME', asset_class='fx', months=(3, 6, 9, 12), options=False),  # GAP
    dict(sym='6M', exchange='CME', asset_class='fx', months=(3, 6, 9, 12), options=False),
]

# --- derived exports (single source -> everything else) ---
SYMBOLS = [(d['sym'], d['exchange']) for d in FUTURES]
MONTHS = {d['sym']: d['months'] for d in FUTURES}
ASSET_CLASSES = {d['sym']: d['asset_class'] for d in FUTURES}
OPTION_UNDERLYINGS = [d['sym'] for d in FUTURES if d.get('options')]

# Gapped FX majors (no security definition on paper — separate CME FX-futures
# entitlement). Only 6M resolves.
GAPPED_FX = {'6E', '6J', '6B', '6A', '6C', '6S', '6N'}

# Live L1 (reqMktData) entitlement on paper DUR193467 = CME + CBOT listings only.
# NYMEX energy (CL/NG/RB/HO/QM/QG) + COMEX/NYMEX metals (GC/SI/HG/PL/PA/MGC)
# return Error 354 "market data not subscribed" (delayed only) on paper — even
# though historical BARS (reqHistoricalData) work for them. The L1 tick recorder
# must NOT record those delayed ticks as real-time. FX majors don't resolve.
L1_LIVE = {d['sym'] for d in FUTURES
           if d['exchange'] in ('CME', 'CBOT') and d['sym'] not in GAPPED_FX}


def front_month_for(sym, now=None):
    """Nearest valid contract month (YYYYMM) for `sym` using its registry months.

    Correct for quarterly (index/rates/fx) and specific cycles (metals/ags),
    but NOT the exact roll for monthly contracts (energy/HG) — for those prefer
    `bot.futures_contracts.resolve_front` (reqContractDetails picks the true
    active front). This is a documented approximation only.
    """
    import datetime as dt
    now = now or dt.date.today()
    months = MONTHS.get(sym, DEFAULT_MONTHS)
    for m in months:
        if now.month <= m:
            return f"{now.year}{m:02d}"
    return f"{now.year + 1}{months[0]:02d}"
