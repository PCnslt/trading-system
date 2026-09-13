#!/usr/bin/env python3
"""Cross-sectional daily strategies on the FULL ~6551-symbol daily universe.

Three signals, computed at each month-end close and held for the next month
(close-to-close; `open` is NOT used):

  * 12-1 momentum  : close[t-21]/close[t-252] - 1   (skip the most recent month)
  * RSI2           : Wilder RSI(2) at month-end close
  * 1-month reversal: close[t]/close[t-21] - 1      (past 1-month return)

Evaluation (cross-sectional, per month-end, equal-weight cross-section):
  * rank IC          = Spearman(signal, next-month return) across names
  * top-decile excess = mean(next-month return of top-10% by signal) - cross-sectional mean
                        (this IS the market-adjusted excess)
  * bottom-decile excess = same for bottom-10%
  * cost-adjusted net = strategy long-decile excess minus round-trip turnover cost
                        at 5/10/20 bp per side (2 sides per replaced name)

Chronological walk-forward: IS = rebalances before 2021-01-01, OOS = 2021-01-01 on.
t-stats are computed on the MONTHLY series (one observation per rebalance = date-clustered).

DATA CLEANING (documented because the raw lake is dirty):
  * close <= 0 treated as missing (295 obs -> divide-by-zero / -inf artifact source).
  * Split / reverse-split gaps neutralized: any single-day |return| > 40% is set to 0
    before building the cumulative "adjusted" close (0.10% of daily returns, across 41%
    of symbols). All signals and forward returns are computed from this adjusted series.
  * Sub-$1 names excluded from every universe (they fabricate huge reversal returns --
    the first unfiltered run printed a +1015 bp/mo reversal excess on the full set).

SURVIVORSHIP (must be read as an UPPER BOUND): the lake holds TODAY's listed universe
(~6551 symbols) back-applied through 2006-2026. Delisted / acquired / bankrupt names are
absent and carry no delisting return (no -100%). Reversal / RSI2 dip-buy effects are the
MOST inflated; the liquid universe is the least distorted.

Research-only. No trading, no data purchase.
"""
from __future__ import annotations
import boto3, io, json, os, re, threading, time
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from concurrent.futures import ThreadPoolExecutor

BUCKET = "trading-datalake-920641308584"
PREFIX = "ibkr/equities/daily/"
REGION = "us-east-1"
OUT = "/home/ubuntu/trading-system/research/atomics/full_universe_results.json"

OOS_CUT = "2021-01-01"
MIN_NAMES = 30
BPS_SIDES = [5, 10, 20]
MAX_WORKERS = 32
SPLIT_THRESH = 0.40      # |daily return| above this = corporate-action gap -> zeroed
FWD_CLIP = (-0.99, 3.0)  # final safety clip on next-month return

_tls = threading.local()


def _s3():
    if not hasattr(_tls, "client"):
        _tls.client = boto3.client("s3", region_name=REGION)
    return _tls.client


def is_common(s):
    # exclude warrants/units/rights/preferred suffixes (from csr_liquidity.py)
    return not re.search(r'[-.][WURPS]A?B?$|[-.]U$|PR[ABCDEFG]?$|[-.]WS$|[-.]WT$', s)


def discover():
    keys = []
    pag = _s3().get_paginator("list_objects_v2")
    for page in pag.paginate(Bucket=BUCKET, Prefix=PREFIX):
        for o in page.get("Contents", []):
            if o["Key"].endswith(".parquet"):
                keys.append(o["Key"].split("/")[-1].split(".parquet")[0])
    return sorted(keys)


def load_one(sym):
    try:
        d = pd.read_parquet(
            io.BytesIO(_s3().get_object(Bucket=BUCKET, Key=f"{PREFIX}{sym}.parquet")["Body"].read()),
            columns=["date", "close", "volume"],
        )
    except Exception:
        return sym, None, None, None
    d["date"] = pd.to_datetime(d["date"])
    d = d.dropna(subset=["close"])
    d = d[d["close"] > 0]
    d = d.sort_values("date").drop_duplicates(subset="date", keep="last")
    return sym, d["date"].values.astype("datetime64[ns]"), \
        d["close"].values.astype(np.float32), d["volume"].values.astype(np.float32)


def stat(vals):
    v = np.asarray(vals, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return None
    n = len(v)
    t = float(v.mean() / (v.std(ddof=1) / np.sqrt(n))) if (n > 1 and v.std(ddof=1) > 0) else float("nan")
    return {"mean": float(v.mean()), "median": float(np.median(v)),
            "tstat": t, "n": int(n)}


def compute(sig, fwd, valid_mask, reb_dates, min_names=MIN_NAMES):
    """sig/fwd: [M,N]; valid_mask: [M,N] bool. Returns per-month records."""
    records = []
    prev_top = prev_bot = None
    for k in range(len(reb_dates)):
        m = valid_mask[k] & ~np.isnan(sig[k]) & ~np.isnan(fwd[k])
        if m.sum() < min_names:
            prev_top = prev_bot = None
            continue
        s = sig[k][m]
        f = fwd[k][m]
        ic = float(spearmanr(s, f).statistic)
        th_hi = np.quantile(s, 0.9)
        th_lo = np.quantile(s, 0.1)
        top = s >= th_hi
        bot = s <= th_lo
        xm = float(f.mean())
        idxs = np.where(m)[0]
        top_set = set(idxs[np.where(top)[0]].tolist())
        bot_set = set(idxs[np.where(bot)[0]].tolist())
        tt = 1.0 - len(top_set & prev_top) / len(top_set) if prev_top is not None else 1.0
        tb = 1.0 - len(bot_set & prev_bot) / len(bot_set) if prev_bot is not None else 1.0
        prev_top, prev_bot = top_set, bot_set
        records.append({
            "date": str(reb_dates[k].date()),
            "ic": ic,
            "top_excess": float(f[top].mean() - xm),
            "bot_excess": float(f[bot].mean() - xm),
            "turnover_top": tt,
            "turnover_bot": tb,
            "n_names": int(m.sum()),
        })
    return records


def aggregate(records):
    d = pd.DataFrame(records)
    if d.empty:
        return None
    out = {}
    for pname, sub in [("full", d), ("is", d[d.date < OOS_CUT]), ("oos", d[d.date >= OOS_CUT])]:
        if sub.empty:
            continue
        b = {
            "rank_ic": stat(sub.ic.to_numpy()),
            "top_decile_excess_bp": stat(sub.top_excess.to_numpy() * 1e4),
            "bottom_decile_excess_bp": stat(sub.bot_excess.to_numpy() * 1e4),
            "mean_n_names_per_month": float(sub.n_names.mean()),
            "mean_turnover_top": float(sub.turnover_top.mean()),
            "mean_turnover_bot": float(sub.turnover_bot.mean()),
            "n_months": int(len(sub)),
        }
        for bps in BPS_SIDES:
            cost_frac = 2.0 * bps * 1e-4  # round-trip per unit turnover, as a fraction
            net_top = (sub.top_excess.to_numpy() - cost_frac * sub.turnover_top.to_numpy()) * 1e4
            net_bot = (sub.bot_excess.to_numpy() - cost_frac * sub.turnover_bot.to_numpy()) * 1e4
            b[f"net_top_bp_{bps}bps_side"] = stat(net_top)
            b[f"net_bot_bp_{bps}bps_side"] = stat(net_bot)
        out[pname] = b
    yy = d.copy()
    yy["year"] = pd.to_datetime(yy["date"]).dt.year
    out["per_year_rank_ic"] = {
        str(y): {"ic_mean": float(g.ic.mean()), "n_months": int(len(g))}
        for y, g in yy.groupby("year")
    }
    return out


def main():
    t0 = time.time()
    syms = discover()
    print(f"[full-universe] discovered {len(syms)} symbols", flush=True)

    CACHE_C = "/tmp/full_universe_close.parquet"
    CACHE_V = "/tmp/full_universe_vol.parquet"
    if os.path.exists(CACHE_C) and os.path.exists(CACHE_V):
        print("[full-universe] loading cached panel", flush=True)
        Cdf = pd.read_parquet(CACHE_C)
        Vdf = pd.read_parquet(CACHE_V)
        loaded = Cdf.shape[1]
    else:
        close_dict, vol_dict = {}, {}
        loaded = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            for sym, dates, closes, vols in ex.map(load_one, syms):
                if closes is None or len(closes) == 0:
                    continue
                idx = pd.DatetimeIndex(dates)
                close_dict[sym] = pd.Series(closes, index=idx)
                vol_dict[sym] = pd.Series(vols, index=idx)
                loaded += 1
        print(f"[full-universe] loaded {loaded} symbols in {time.time()-t0:.0f}s", flush=True)
        Cdf = pd.DataFrame(close_dict).sort_index()
        Vdf = pd.DataFrame(vol_dict).sort_index()
        del close_dict, vol_dict
        Cdf.to_parquet(CACHE_C)
        Vdf.to_parquet(CACHE_V)
        print("[full-universe] cached panel to /tmp", flush=True)

    syms_loaded = list(Cdf.columns)
    N = len(syms_loaded)
    T = Cdf.shape[0]
    dates = Cdf.index
    Cv = np.array(Cdf.to_numpy(np.float32), copy=True)
    Vv = np.array(Vdf.to_numpy(np.float32), copy=True)
    del Cdf, Vdf
    Cv[Cv <= 0] = np.nan
    has_data = ~np.isnan(Cv)  # [T, N] — where the symbol actually has a tradeable close
    print(f"[full-universe] panel {T} days x {N} symbols, {dates[0].date()} .. {dates[-1].date()}", flush=True)

    common_col_mask = np.array([is_common(s) for s in syms_loaded], dtype=bool)
    n_common = int(common_col_mask.sum())
    print(f"[full-universe] common-equity (ex warrants/units/rights/pref): {n_common} of {N}", flush=True)

    # ---- split-cleaned adjusted close (cumprod of clipped daily returns) ----
    R = Cv[1:] / Cv[:-1] - 1.0
    R = np.where(np.abs(R) > SPLIT_THRESH, 0.0, R)   # neutralize corporate-action gaps
    R = np.where(np.isnan(R), 0.0, R)                # missing day -> no return (no NaN propagation)
    adj = np.empty((T, N), np.float64)
    adj[0] = 1.0
    adj[1:] = np.cumprod(1.0 + R, axis=0)
    del R
    print(f"[full-universe] split-cleaned adjusted close built in {time.time()-t0:.0f}s", flush=True)

    # ---- Wilder RSI(2) on the adjusted series (numpy recursion, alpha=1/2) ----
    adj32 = adj.astype(np.float32)
    delta = np.diff(adj32, axis=0).astype(np.float32)      # [T-1, N]
    ag = np.full((T, N), np.nan, np.float32)
    al = np.full((T, N), np.nan, np.float32)
    g0 = np.clip(delta[0], 0, None); l0 = np.clip(-delta[0], 0, None)
    g1 = np.clip(delta[1], 0, None); l1 = np.clip(-delta[1], 0, None)
    ag[2] = (g0 + g1) * 0.5
    al[2] = (l0 + l1) * 0.5
    for t in range(3, T):
        g = np.clip(delta[t - 1], 0, None)
        l = np.clip(-delta[t - 1], 0, None)
        ag[t] = ag[t - 1] * 0.5 + g * 0.5
        al[t] = al[t - 1] * 0.5 + l * 0.5
    del delta, adj32
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ag / al
        rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = np.where((al == 0) & (ag > 0), 100.0, rsi)
    rsi = np.where((ag == 0) & (al == 0), 50.0, rsi)
    del ag, al
    print(f"[full-universe] RSI2 computed in {time.time()-t0:.0f}s", flush=True)

    # ---- rebalance grid (month-end closes) ----
    month = dates.to_period("M")
    month_end_mask = np.asarray(~month.duplicated(keep="last"))
    reb_pos = np.where(month_end_mask)[0]
    M = len(reb_pos) - 1  # rebalances that have a forward month
    reb_dates = dates[reb_pos[:-1]]
    print(f"[full-universe] {M} rebalances, {reb_dates[0].date()} .. {reb_dates[-1].date()}", flush=True)

    mom = np.full((M, N), np.nan, np.float32)
    rev = np.full((M, N), np.nan, np.float32)
    rsi2 = np.full((M, N), np.nan, np.float32)
    fwd = np.full((M, N), np.nan, np.float32)
    price = np.full((M, N), np.nan, np.float32)
    liq = np.full((M, N), np.nan, np.float32)

    hd_p = has_data[reb_pos[:-1]]      # has data at rebalance
    hd_pn = has_data[reb_pos[1:]]      # has data at next rebalance (forward month exists)

    for k in range(M):
        p = reb_pos[k]
        pn = reb_pos[k + 1]
        fwd[k] = np.clip(adj[pn] / adj[p] - 1.0, *FWD_CLIP)
        fwd[k][~(hd_p[k] & hd_pn[k])] = np.nan
        price[k] = Cv[p]
        rsi2[k] = rsi[p]
        rsi2[k][~hd_p[k]] = np.nan
        if p - 21 >= 0:
            rev[k] = adj[p] / adj[p - 21] - 1.0
            rev[k][~has_data[p - 21]] = np.nan
        if p - 252 >= 0:
            mom[k] = adj[p - 21] / adj[p - 252] - 1.0
            mom[k][~has_data[p - 252]] = np.nan
        lo = max(0, p - 20)
        dv = Cv[lo:p + 1] * Vv[lo:p + 1]
        liq[k] = np.nanmedian(dv, axis=0)
    del Cv, Vv, rsi, adj, has_data
    print(f"[full-universe] signals built in {time.time()-t0:.0f}s", flush=True)

    # ---- universes (valid_mask over [M, N]) ----
    px_ge_1 = (price >= 1.0)
    base_full = px_ge_1                        # every symbol, but sub-$1 excluded
    base_common = np.tile(common_col_mask, (M, 1)) & px_ge_1
    liquid = np.tile(common_col_mask, (M, 1)) & (price >= 5.0) & (liq >= 1e6)

    signals = {
        "momentum_12_1": (mom, "long TOP decile (highest 12-1 momentum)", "top"),
        "rsi2": (rsi2, "long BOTTOM decile (most oversold = classic Connors RSI2 long)", "bottom"),
        "reversal_1m": (-rev, "signal = -1m_return; long TOP decile = biggest 1-month losers", "top"),
    }

    universes = {
        "full_px_ge_1": (base_full, "all symbols with month-end close >= $1 (sub-$1 excluded)"),
        "common_equity_px_ge_1": (base_common, "common equity (ex warrants/units/rights/pref) AND close >= $1"),
        "liquid": (liquid, "common AND close >= $5 AND trailing-21d median dollar-vol >= $1M"),
    }

    ew = []
    for k in range(M):
        m = base_full[k] & ~np.isnan(fwd[k])
        if m.sum() >= MIN_NAMES:
            ew.append(float(fwd[k][m].mean()))
    ew = np.array(ew) * 1e4

    results = {}
    for uname, (umask, udesc) in universes.items():
        results[uname] = {"description": udesc}
        for sname, (smat, sdesc, long_side) in signals.items():
            recs = compute(smat, fwd, umask, reb_dates)
            agg = aggregate(recs)
            if agg is not None:
                agg["strategy_long_side"] = long_side
                agg["strategy_description"] = sdesc
            results[uname][sname] = agg
            if agg is not None:
                o = agg.get("oos", {})
                side = agg.get("strategy_long_side", "?")
                net_key = f"net_{'top' if side == 'top' else 'bot'}_bp_10bps_side"
                net10 = agg["full"].get(net_key, {})
                net10_oos = o.get(net_key, {})
                print(f"[{uname:>20} | {sname:>16}] IC full={agg['full']['rank_ic']['mean']:+.4f} "
                      f"OOS={o.get('rank_ic', {}).get('mean', float('nan')):+.4f} | "
                      f"{side}-decile XS full={agg['full'][side+'_decile_excess_bp']['mean']:+.1f}bp "
                      f"OOS={o.get(side+'_decile_excess_bp', {}).get('mean', float('nan')):+.1f}bp | "
                      f"net10 full={net10.get('mean', float('nan')):+.1f}bp "
                      f"OOS={net10_oos.get('mean', float('nan')):+.1f}bp", flush=True)

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "headline_survivorship_disclosure": (
            "CURRENT-UNIVERSE-ONLY UPPER BOUND. The S3 daily lake holds ~6551 symbols that are "
            "TODAY's listed survivors back-applied through 2006-2026. Delisted/acquired/bankrupt "
            "names are absent and carry no delisting return (no -100%). Reversal and RSI2 dip-buy "
            "results are the MOST inflated (the names that kept falling to zero are missing); the "
            "liquid universe is the least distorted. Treat every number below as an upper bound on "
            "the true tradeable edge, and the liquid column as the closest to reality."
        ),
        "data_cleaning_disclosure": (
            "1) close<=0 dropped (295 obs); 2) split/reverse-split gaps neutralized by zeroing "
            "single-day |return|>40% (0.10% of daily returns, across 41% of symbols) before the "
            "cumulative adjusted close; all signals + forward returns use this adjusted series; "
            "3) sub-$1 names excluded from every universe (the unfiltered run printed a +1015 bp/mo "
            "reversal excess on the full set -- an illiquidity artifact, not alpha)."
        ),
        "methodology": {
            "data": "ibkr/equities/daily/{SYMBOL}.parquet, close+volume only (open NOT used)",
            "rebalance": "month-end close, hold to next month-end close (close-to-close)",
            "signals": {
                "momentum_12_1": "close[t-21]/close[t-252]-1 (skip most recent month)",
                "rsi2": "Wilder RSI(2) at month-end",
                "reversal_1m": "-(close[t]/close[t-21]-1), long biggest 1-month losers",
            },
            "market_adjustment": "top/bottom-decile mean next-month return minus equal-weight cross-sectional mean (same month)",
            "rank_ic": "Spearman(signal, next-month return) per month; t-stat on monthly IC series (date-clustered)",
            "walk_forward": f"chronological split, IS = rebalances < {OOS_CUT}, OOS >= {OOS_CUT}",
            "cost_model": "round-trip = 2 * bps_side * turnover_fraction; turnover = fraction of decile names replaced month-over-month; first month = full establishment (turnover=1)",
            "min_names_per_rebalance": MIN_NAMES,
            "split_neutralization_threshold_daily_ret": SPLIT_THRESH,
            "forward_return_clip": list(FWD_CLIP),
            "universes": {k: v[1] for k, v in universes.items()},
        },
        "data": {
            "n_symbols_discovered": len(syms),
            "n_symbols_loaded": loaded,
            "n_common_equity": n_common,
            "n_days": T,
            "date_range": [str(dates[0].date()), str(dates[-1].date())],
            "n_rebalances": M,
            "rebalance_range": [str(reb_dates[0].date()), str(reb_dates[-1].date())],
            "oos_cut": OOS_CUT,
            "n_oos_months": int((reb_dates >= pd.Timestamp(OOS_CUT)).sum()),
        },
        "equal_weight_cross_section_drift_bp_per_month": stat(ew),
        "results": results,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    print(f"\n[done] wrote {OUT} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
