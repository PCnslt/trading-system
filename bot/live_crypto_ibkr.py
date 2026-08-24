"""Live crypto (BTC/ETH) momentum bot — IBKR PAPER execution (MOM20, blue-chip).

Same MOM20 Donchian-20 breakout edge as bot/crypto_exec.py (Binance-simulated),
but executes REAL IBKR paper crypto orders (Crypto contracts via PAXOS,
fractional qty) so the actual IBKR order path is exercised end-to-end.

IBKR crypto is MARKET/LIMIT only — there is NO native stop order on PAXOS — so
the never-lose-money protective stop is a SOFTWARE chandelier trail managed by
this bot each cycle (owner-approved pattern for platforms without native
trailing; see docs/CRYPTO-TRADING-RESEARCH.md). The reconciler EXCLUDES crypto
(secType=CRYPTO) for the same reason.

Blue-chip only: BTC + ETH. IBKR PAXOS does NOT list XRP (verified 2026-08-24),
so XRP trades on Robinhood only (infra/rh_crypto.py).

VALIDATION (2026-08-24, live probe): IBKR crypto orders require ``cashQty`` (USD
amount), NOT ``totalQuantity`` — a totalQuantity order is rejected with Error
10289 "You must set Cash Quantity". BUT on the PAPER account (DUR193467), crypto
orders sit ``PendingSubmit`` forever (no fill, no error): PAXOS crypto is
LIVE-ONLY and paper does not simulate it. So this lane is CORRECT but cannot
execute until the LIVE IBKR account (U26949861) is funded + crypto trading
enabled. The reconciler excludes secType=CRYPTO for the same reason (fractional
qty + software stop, no native stop).

Signal:   close > prior 20-day high  -> LONG  (fresh-high breakout, daily bar)
Exit:     chandelier trail = peak - 3*ATR (ratcheted up), OR close < 20d low.

Ledger (tags DISTINCT from the Binance lane):
  SIGNAL#<sym>_MOM20IBKR / POSITION#<sym>_MOM20IBKR / TRADE#<sym>_MOM20IBKR
  RISK#<date>/crypto_ibkr

Paper only. clientId 82. Run every 30 min (daily signal + intraday software-stop
monitoring):  ./venv/bin/python -u bot/live_crypto_ibkr.py [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time

import boto3
import pandas as pd
from dotenv import load_dotenv
from ib_insync import IB, Crypto, MarketOrder

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
load_dotenv(os.path.join(_ROOT, ".env"))

from bot.crypto_paper import live_price, load_yf, merge_live, wilder_atr  # noqa: E402
from bot.crypto_exec import analyze_momentum  # noqa: E402
from control import get_control, control_state, control_allows_entry, ControlUnavailable  # noqa: E402

IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", "4002"))
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET = os.getenv("S3_BUCKET", "trading-datalake-920641308584")
DYNAMO_TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")
CLIENT_ID = 82   # 70/72/73/74/75/76/77/78/79/80/81 taken
BOT_KEY = "live_crypto_ibkr"
LIVE = os.getenv("LIVE", "false").lower() == "true"   # always false (paper lane)

PAPER_CAPITAL = float(os.getenv("CRYPTO_IBKR_PAPER_CAPITAL", "10000"))
RISK_PCT = 0.01
FEE_BPS = 0.001          # 10 bps round-trip taker fee (honest cost on P&L)
FAMILY = "MOM20IBKR"
MIN_BARS = 25

UNIVERSE = [
    {"yf": "BTC-USD", "binance": "BTCUSDT", "ibkr": "BTC"},
    {"yf": "ETH-USD", "binance": "ETHUSDT", "ibkr": "ETH"},
]


def _s(v):
    try:
        f = float(v)
        return "" if f != f else str(round(f, 8))
    except (TypeError, ValueError):
        return str(v)


def _f(v, default=0.0):
    try:
        f = float(v)
        return default if f != f else f
    except (TypeError, ValueError):
        return default


def size_qty(entry_px, stop_px):
    risk_usd = PAPER_CAPITAL * RISK_PCT
    stop_dist = entry_px - stop_px
    if stop_dist <= 0:
        return 0.0
    qty = risk_usd / stop_dist
    max_qty = PAPER_CAPITAL / entry_px
    return min(qty, max_qty)


def _ibkr_contract(sym: str):
    return Crypto(sym, "PAXOS", "USD")


def _place(ib: IB, contract, side: str, qty: float):
    """Place a market order and wait up to ~20s for a fill. Returns avg fill px."""
    order = MarketOrder(side.upper(), max(qty, 1e-8), tif="GTC")
    trade = ib.placeOrder(contract, order)
    for _ in range(40):
        ib.sleep(0.5)
        st = trade.orderStatus.status
        if st in ("Filled", "Cancelled", "Inactive"):
            break
    if trade.orderStatus.status != "Filled":
        raise RuntimeError(f"crypto {side} not filled (status={trade.orderStatus.status})")
    return float(trade.orderStatus.avgFillPrice)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(DYNAMO_TABLE)
    s3 = boto3.client("s3", region_name=AWS_REGION)
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    now_ts = int(time.time())

    # control plane (fail-closed) — only gate ENTRIES; a holding position still exits.
    ctrl = {}
    try:
        ctrl = get_control(table)
    except ControlUnavailable:
        print(f"[{today}] control unavailable — no entries this cycle")
    allow_entry = control_allows_entry(ctrl)

    # connect IBKR (paper). Signal is computed from yfinance/Binance so we still
    # know it if the gateway is down, but orders obviously need the connection.
    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=10)
    except Exception as e:
        print(f"[{today}] IBKR connect failed: {e} — signal-only, no orders")
        ib = None

    for u in UNIVERSE:
        sym, tag = u["ibkr"], f"{u['ibkr']}_{FAMILY}"
        try:
            px = live_price(u["binance"])
        except Exception as e:
            print(f"  [{sym}] live price failed: {e!r} — skip")
            continue
        df = merge_live(load_yf(s3, u["yf"]), px)
        if df is None or len(df) < MIN_BARS:
            print(f"  [{sym}] insufficient history — skip")
            continue
        signal, reason, extra = analyze_momentum(df)
        atr = _f(extra.get("atr"))
        state = table.get_item(Key={"pk": f"POSITION#{tag}", "sk": "current"}).get("Item", {})
        pos = _f(state.get("pos"))
        entry = _f(state.get("entry"))
        stop = _f(state.get("stop"))
        peak = _f(state.get("peak")) or entry

        if pos <= 0:
            if signal == "LONG" and allow_entry:
                entry_px = px * 1.0
                stop_px = px - 3.0 * atr
                qty = size_qty(entry_px, stop_px)
                if qty <= 0:
                    print(f"  [{sym}] LONG but size=0 — skip")
                    continue
                if args.dry_run or ib is None:
                    print(f"  [dry] {tag} BUY {qty:.6f} @ {entry_px:.2f} stop {stop_px:.2f}")
                    if args.dry_run:
                        continue
                else:
                    try:
                        fill_px = _place(ib, _ibkr_contract(sym), "BUY", qty)
                    except Exception as e:
                        print(f"  [{sym}] IBKR buy failed: {e!r} — skip")
                        continue
                    entry_px = fill_px
                    stop_px = entry_px - 3.0 * atr
                    table.put_item(Item={"pk": f"POSITION#{tag}", "sk": "current",
                                         "pos": _s(qty), "side": "LONG", "entry": _s(entry_px),
                                         "stop": _s(stop_px), "peak": _s(entry_px),
                                         "entry_ts": now_ts, "session_date": today,
                                         "strategy": FAMILY, "ts": now_ts})
                    table.put_item(Item={"pk": f"TRADE#{tag}", "sk": str(now_ts),
                                         "side": "BUY", "qty": _s(qty), "px": _s(entry_px),
                                         "pnl": "0", "reason": "breakout", "strategy": FAMILY,
                                         "venue": "IBKR-PAXOS (paper)", "mode": "PAPER-EXEC",
                                         "ts": now_ts})
                print(f"  [{sym}] ENTER LONG {qty:.6f} @ {entry_px:.2f} stop {stop_px:.2f} — {reason}")
            else:
                print(f"  [{sym}] flat — {reason[:60]}")
        else:
            # software chandelier trail (ratchet peak up, stop up)
            peak = max(peak, px)
            if atr > 0:
                trail = peak - 3.0 * atr
                if trail > stop:
                    stop = trail
            exit_px, exit_reason = None, None
            if px <= stop:
                exit_px, exit_reason = px, "chandelier"
            elif signal == "BREAKDOWN":
                exit_px, exit_reason = px, "breakdown"
            if exit_px is not None:
                if args.dry_run or ib is None:
                    print(f"  [dry] {tag} SELL {pos:.6f} @ {exit_px:.2f} ({exit_reason})")
                    if args.dry_run:
                        continue
                else:
                    try:
                        fill_px = _place(ib, _ibkr_contract(sym), "SELL", pos)
                    except Exception as e:
                        print(f"  [{sym}] IBKR sell failed: {e!r} — retry next cycle")
                        continue
                    exit_px = fill_px
                gross = (exit_px - entry) * pos
                fee = (entry + exit_px) * pos * (FEE_BPS / 2)
                pnl = gross - fee
                table.put_item(Item={"pk": f"TRADE#{tag}", "sk": str(now_ts),
                                     "side": "SELL", "qty": _s(pos), "px": _s(exit_px),
                                     "pnl": _s(pnl), "reason": exit_reason, "strategy": FAMILY,
                                     "venue": "IBKR-PAXOS (paper)", "mode": "PAPER-EXEC",
                                     "ts": now_ts})
                table.delete_item(Key={"pk": f"POSITION#{tag}", "sk": "current"})
                rr = table.get_item(Key={"pk": f"RISK#{today}", "sk": "crypto_ibkr"}).get("Item", {})
                table.put_item(Item={"pk": f"RISK#{today}", "sk": "crypto_ibkr",
                                     "realized_pnl": _s(_f(rr.get("realized_pnl")) + pnl),
                                     "trades": int(rr.get("trades", 0)) + 1,
                                     "strategy": FAMILY, "ts": now_ts})
                print(f"  [{sym}] EXIT ({exit_reason}) {pos:.6f} @ {exit_px:.2f} pnl {pnl:.2f}")
            else:
                table.put_item(Item={"pk": f"POSITION#{tag}", "sk": "current",
                                     "pos": _s(pos), "side": "LONG", "entry": _s(entry),
                                     "stop": _s(stop), "peak": _s(peak),
                                     "entry_ts": state.get("entry_ts"),
                                     "session_date": state.get("session_date"),
                                     "strategy": FAMILY, "ts": now_ts})
                print(f"  [{sym}] holding {pos:.6f} @ {entry:.2f} (trail {stop:.2f}, px {px:.2f})")

    if ib is not None:
        ib.disconnect()
    print("\nlive_crypto_ibkr done.")


if __name__ == "__main__":
    main()
