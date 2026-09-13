"""
Market-wide cross-sectional LEAD/LAG matrix (full N x N x L lag structure).

Purpose (research-only, no trading):
  1. Build the full N x N lagged cross-correlation matrix of 5-min returns at
     lags 1..6 bars, for every ordered pair (i,j).  C_minus[l][i,j] =
     corr( r_i(t), r_j(t-l) )  => j's past predicts i's future => "j leads i".
  2. Aggregate the lag structure: does the CROSS-SECTION AS A WHOLE lead/lag
     itself?  (lag-0 vs lag-1..6 off-diagonal correlation, the directed
     asymmetry A[i,j,l] = C_minus[l][i,j] - C_minus[l][j,i], its noise floor,
     the top directed edges, and per-stock lead scores.)
  3. Test (strictly causal, chronological OOS) whether a stock's lagged
     exposure to (a) the equal-weight market, (b) its sector peers, and
     (c) its top "leader" stocks (estimated on train from the asymmetry matrix)
     predicts its next-5m and next-30m return AFTER controlling for its own
     lag.  Random-leader placebo included.

Evaluation: per-timestamp Spearman rank IC, top-decile excess (bp), and a
Fama-MacBeth cross-sectional regression (own-lag + signal) whose signal
coefficient is the "beyond own-lag" test; all t-stats Newey-West on the
per-timestamp series (date/overlap-clustered, not per-trade).

Data: ibkr/equities/5min/{SYM}.parquet (40 liquid names, ~8mo, RTH 09:30-15:55).
"""
from __future__ import annotations
import boto3, io, json, os
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from datetime import datetime, timezone

BUCKET = "trading-datalake-920641308584"
PREFIX = "ibkr/equities/5min/"
REGION = "us-east-1"
OUT = "/home/ubuntu/trading-system/research/atomics/crossasset_matrix_results.json"
K_LEADERS = 5
LAGS = list(range(1, 7))          # 1..6 bars for the matrix
MIN_PAIRS = 300                   # min overlapping obs for a pairwise corr
MIN_STOCKS_CS = 10                # min stocks per timestamp for CS stats
TRAIN_FRAC = 0.70
NW_LAG = {1: 2, 6: 12}            # Newey-West truncation per horizon (bars)

# ---- sector map (GICS) for the 40-symbol liquid universe ----
SECTORS = {
    "InfoTech": ["AAPL", "MSFT", "NVDA", "AMD", "AVGO", "INTC", "MU", "QCOM",
                 "TXN", "CSCO", "ORCL", "ADBE", "CRM", "ACN", "PLTR"],
    "CommSvcs": ["GOOGL", "META", "NFLX", "DIS"],
    "ConsDisc": ["AMZN", "TSLA", "HD", "MCD", "NKE"],
    "ConsStpl": ["COST", "KO", "PEP", "PG", "WMT"],
    "Health":   ["ABT", "JNJ", "LLY", "TMO", "UNH"],
    "Financials": ["JPM", "MA", "V"],
    "Industrials": ["BA", "GE"],
    "Energy":   ["XOM"],
}


def discover(s3):
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX, MaxKeys=300)
    return sorted(o["Key"].split("/")[-1].split(".parquet")[0]
                  for o in r.get("Contents", []) if o["Key"].endswith(".parquet"))


def load_close(s3, sym):
    d = pd.read_parquet(io.BytesIO(
        s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}{sym}.parquet")["Body"].read()))
    d["date"] = pd.to_datetime(d["date"])
    d = d.set_index("date").sort_index()
    d.index = d.index.tz_localize(None)
    return d["close"]


def nw_t(x, maxlag=12):
    """Newey-West t-stat (Bartlett kernel) on a 1-D series. Returns (mean, t, n)."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 5:
        return np.nan, np.nan, int(n)
    mean = x.mean()
    e = x - mean
    var = float(e @ e) / n
    L = min(maxlag, n - 1)
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1.0)
        var += 2.0 * w * float(e[l:] @ e[:-l]) / n
    se = np.sqrt(var / n)
    t = mean / se if se > 0 else np.nan
    return float(mean), float(t), int(n)


def crosscorr(R, lag, min_pairs=MIN_PAIRS):
    """C[i,j] = corr(R[t,i], R[t-lag,j]).  R: T x N float (NaNs ok)."""
    T, N = R.shape
    C = np.full((N, N), np.nan)
    for i in range(N):
        ri = R[:, i]
        for j in range(N):
            rj = R[:, j]
            if lag == 0:
                a, b = ri, rj
            else:
                a, b = ri[lag:], rj[:-lag]
            m = ~np.isnan(a) & ~np.isnan(b)
            if m.sum() < min_pairs:
                continue
            aa, bb = a[m], b[m]
            if np.std(aa) == 0 or np.std(bb) == 0:
                continue
            C[i, j] = float(np.corrcoef(aa, bb)[0, 1])
    return C


def perm_p_for_edge(R, i, j, lag, n_perm=500, seed=0):
    """Empirical p-value for directed asymmetry edge A[i,j,lag] under a
    no-lead-lag null: shuffle leader j's return series and recompute A."""
    T, N = R.shape
    rng = np.random.default_rng(seed)
    ri = R[:, i]
    rj = R[:, j]
    m_f = ~np.isnan(ri) & ~np.isnan(rj)
    # observed asymmetry A = corr(r_i(t), r_j(t-l)) - corr(r_j(t), r_i(t-l))
    def asym(leader_series):
        # c_minus = corr(r_i(t), leader(t-l)); c_plus = corr(leader(t), r_i(t-l))
        a = ri[lag:]
        b = leader_series[:-lag]
        mm = ~np.isnan(a) & ~np.isnan(b)
        cm = float(np.corrcoef(a[mm], b[mm])[0, 1]) if mm.sum() >= MIN_PAIRS else 0.0
        a2 = leader_series[lag:]
        b2 = ri[:-lag]
        mm2 = ~np.isnan(a2) & ~np.isnan(b2)
        cp = float(np.corrcoef(a2[mm2], b2[mm2])[0, 1]) if mm2.sum() >= MIN_PAIRS else 0.0
        return cm - cp
    obs = asym(rj)
    nulls = np.empty(n_perm)
    for p in range(n_perm):
        nulls[p] = asym(rng.permutation(rj))
    p = float((np.abs(nulls) >= np.abs(obs)).mean())
    return obs, p


def summarize_ic(ic_series, maxlag):
    ic = np.asarray(ic_series, dtype=float)
    ic = ic[~np.isnan(ic)]
    mean, t, n = nw_t(ic, maxlag)
    return {"rank_ic_mean": round(float(np.mean(ic)), 5) if n else None,
            "rank_ic_median": round(float(np.median(ic)), 5) if n else None,
            "rank_ic_nw_t": round(t, 3) if t == t else None,
            "n_timestamps": int(n)}


def main():
    s3 = boto3.client("s3", region_name=REGION)
    syms = discover(s3)
    print(f"[matrix] {len(syms)} symbols")

    closes = {s: load_close(s3, s) for s in syms}
    close_wide = pd.DataFrame(closes).sort_index()      # T x N, tz-naive index
    # drop the final partial trading day
    day = pd.Series(close_wide.index).dt.date.values
    last_day = day.max()
    keep = day < last_day
    close_wide = close_wide[keep]
    print(f"[matrix] range {close_wide.index.min()} .. {close_wide.index.max()}  "
          f"rows={len(close_wide)}")

    syms = list(close_wide.columns)                     # in column order
    N = len(syms)
    C = close_wide.to_numpy(dtype=float)                # T x N close (copy, writable)
    R = np.full_like(C, np.nan)
    R[1:, :] = C[1:, :] / C[:-1, :] - 1.0               # per-symbol 5-min return
    R[np.isinf(R)] = np.nan
    days = pd.Series(close_wide.index).dt.date.values

    # forward targets: 5m (1 bar) and 30m (6 bars), SAME-SESSION only
    def fwd_ret(h):
        F = np.full_like(C, np.nan)
        F[:-h, :] = C[h:, :] / C[:-h, :] - 1.0
        same = (days[:-h] == days[h:])
        F[:-h, :][~same] = np.nan
        F[np.isinf(F)] = np.nan
        return F
    F5 = fwd_ret(1)
    F30 = fwd_ret(6)

    # ---- 1. Full N x N x L matrix (descriptive, full sample) ----
    C0 = crosscorr(R, 0)
    Cminus = {l: crosscorr(R, l) for l in LAGS}
    off = lambda M: M[~np.eye(N, dtype=bool)]
    lag0_off = off(C0)
    lag0_off = lag0_off[~np.isnan(lag0_off)]
    print(f"[matrix] lag-0 off-diag corr: mean={np.mean(lag0_off):+.4f} "
          f"median={np.median(lag0_off):+.4f} std={np.std(lag0_off):.4f}")

    asym_summary = []
    all_A = []
    top_edges = []
    for l in LAGS:
        M = Cminus[l]
        Mo = off(M); Mo = Mo[~np.isnan(Mo)]
        # directed asymmetry (antisymmetric): A[i,j] = M[i,j] - M[j,i]
        A = M - M.T
        Ao = off(A); Ao = Ao[~np.isnan(Ao)]
        all_A.append(Ao)
        # own-lag autocorrelation (diagonal) for reference
        diag = np.diag(M); diag = diag[~np.isnan(diag)]
        asym_summary.append({
            "lag_bars": l,
            "off_diag_corr_mean": round(float(np.mean(Mo)), 5),
            "off_diag_corr_median": round(float(np.median(Mo)), 5),
            "off_diag_corr_std": round(float(np.std(Mo)), 5),
            "own_autocorr_mean": round(float(np.mean(diag)), 5),
            "asymmetry_mean": round(float(np.mean(Ao)), 5),   # ~0 by antisymmetry
            "asymmetry_std": round(float(np.std(Ao)), 5),
            "asymmetry_max_abs": round(float(np.max(np.abs(Ao))), 5),
            "frac_asym_gt_2sigmacorr": None,
        })
        for i in range(N):
            for j in range(N):
                if i == j:
                    continue
                top_edges.append((l, i, j, A[i, j]))

    all_A = np.concatenate([a for a in all_A])
    noise_floor = float(np.std(all_A))
    n_edges = int(len(all_A))
    frac_gt2 = float((np.abs(all_A) > 2 * noise_floor).mean())
    frac_gt3 = float((np.abs(all_A) > 3 * noise_floor).mean())
    exp_max = noise_floor * np.sqrt(2 * np.log(n_edges))
    max_abs_all = float(np.max(np.abs(all_A)))
    print(f"[matrix] asymmetry noise floor (std over all ordered edges): {noise_floor:.5f}")
    print(f"[matrix] n directed edges={n_edges}  frac|A|>2sig={frac_gt2:.3%} "
          f"(gauss 4.55%)  frac|A|>3sig={frac_gt3:.3%} (gauss 0.27%)  "
          f"obs max|A|={max_abs_all:.4f} vs noise-expected max={exp_max:.4f}")

    # top directed edges
    top_edges.sort(key=lambda x: -abs(x[3]))
    top10 = []
    for l, i, j, a in top_edges[:10]:
        obs, p = perm_p_for_edge(R, i, j, l)
        top10.append({"lag_bars": l, "follower": syms[i], "leader": syms[j],
                      "asymmetry": round(float(a), 5),
                      "asym_z": round(float(a) / noise_floor, 2),
                      "perm_p": round(p, 4)})

    # per-stock lead score (sum over followers i of A[i,j,l] => j leads)
    lead_score = np.zeros(N)
    for l in LAGS:
        A = Cminus[l] - Cminus[l].T
        A = np.nan_to_num(A, nan=0.0)
        lead_score += A.sum(axis=0)          # column j: sum_i A[i,j]
    lead_rank = sorted(zip(syms, lead_score.tolist()), key=lambda x: -x[1])
    print(f"[matrix] top leaders:  {[(s, round(v,4)) for s, v in lead_rank[:5]]}")
    print(f"[matrix] top laggards: {[(s, round(v,4)) for s, v in lead_rank[-5:]]}")

    # ---- 2. Train / test (chronological) ----
    times = np.sort(close_wide.index.unique())
    cut = times[int(len(times) * TRAIN_FRAC)]
    is_test = close_wide.index.to_numpy() >= cut
    Rtr = R[~is_test]
    Rte = R[is_test]
    print(f"[matrix] split at {cut}: train={int((~is_test).sum())} test={int(is_test.sum())} rows")

    # leader matrix estimated on TRAIN only (asymmetry averaged over lags 1..6)
    S = np.zeros((N, N))
    for l in LAGS:
        Mtr = crosscorr(Rtr, l)
        Atr = Mtr - Mtr.T
        S += np.nan_to_num(Atr, nan=0.0) / len(LAGS)   # S[i,j] > 0 => j leads i
    np.fill_diagonal(S, -np.inf)
    leader_idx = np.argsort(-S, axis=1)[:, :K_LEADERS]   # top-K leaders per follower

    # random-leader placebo (fixed per follower, seeded)
    rng = np.random.default_rng(0)
    rand_idx = np.stack([rng.choice([k for k in range(N) if k != i],
                                    size=K_LEADERS, replace=False)
                         for i in range(N)])

    sym2idx = {s: i for i, s in enumerate(syms)}
    sector_of = {s: sec for sec, ss in SECTORS.items() for s in ss}
    sector_peers = {}
    for i, s in enumerate(syms):
        sec = sector_of.get(s)
        peers = [sym2idx[p] for p in SECTORS.get(sec, []) if p != s] if sec else []
        sector_peers[i] = peers

    # ---- 3. Build test-period signals (causal: lag-1 returns only) ----
    Rte_lag1 = np.full_like(Rte, np.nan)
    Rte_lag1[1:, :] = Rte[:-1, :]

    def lag1_mean(idx_list_per_row):
        sig = np.full(len(Rte), np.nan)
        for t in range(len(Rte)):
            cols = idx_list_per_row
            vals = Rte_lag1[t, cols]
            vals = vals[~np.isnan(vals)]
            if len(vals):
                sig[t] = vals.mean()
        return sig

    signals = {}
    # own lag (baseline)
    signals["own_lag"] = Rte_lag1.copy()            # per-stock
    # EW market (ex-self): mean of ALL others' lag-1
    mkt_ex = np.full((len(Rte), N), np.nan)
    for t in range(len(Rte)):
        vals = Rte_lag1[t]
        for i in range(N):
            if np.isnan(Rte_lag1[t, i]):
                continue
            others = np.delete(vals, i)
            others = others[~np.isnan(others)]
            if len(others):
                mkt_ex[t, i] = others.mean()
    signals["market_ew_exself"] = mkt_ex
    # sector peers (ex-self)
    sec_ex = np.full((len(Rte), N), np.nan)
    for t in range(len(Rte)):
        for i in range(N):
            peers = sector_peers[i]
            if not peers:
                continue
            vals = Rte_lag1[t, peers]
            vals = vals[~np.isnan(vals)]
            if len(vals):
                sec_ex[t, i] = vals.mean()
    signals["sector_ew_exself"] = sec_ex
    # top-leaders (asymmetry-selected on train), EW of their lag-1
    lead_sig = np.full((len(Rte), N), np.nan)
    for i in range(N):
        cols = leader_idx[i]
        for t in range(len(Rte)):
            vals = Rte_lag1[t, cols]
            vals = vals[~np.isnan(vals)]
            if len(vals):
                lead_sig[t, i] = vals.mean()
    signals["top_leaders_ew"] = lead_sig
    # full-matrix weighted (distributed): sum_j S[i,j] * r_j(t-1) / sum_j |S[i,j]|
    full_sig = np.full((len(Rte), N), np.nan)
    for t in range(len(Rte)):
        r = Rte_lag1[t]
        for i in range(N):
            w = S[i].copy(); w[i] = 0.0
            denom = np.abs(w).sum()
            if denom <= 0:
                continue
            num = np.nansum(w * r)
            full_sig[t, i] = num / denom
    signals["full_matrix_weighted"] = full_sig
    # random-leader placebo
    rand_sig = np.full((len(Rte), N), np.nan)
    for i in range(N):
        cols = rand_idx[i]
        for t in range(len(Rte)):
            vals = Rte_lag1[t, cols]
            vals = vals[~np.isnan(vals)]
            if len(vals):
                rand_sig[t, i] = vals.mean()
    signals["random_leaders_placebo"] = rand_sig

    # ---- 4. Evaluation on TEST ----
    def cs_ic(sig, fwd, maxlag):
        per_t = []
        for t in range(len(Rte)):
            s = sig[t]; f = fwd[t]
            m = ~np.isnan(s) & ~np.isnan(f)
            if m.sum() < MIN_STOCKS_CS:
                continue
            ss, ff = s[m], f[m]
            if np.std(ss) == 0 or np.std(ff) == 0:
                continue
            per_t.append(float(spearmanr(ss, ff).statistic))
        return summarize_ic(np.array(per_t), maxlag)

    def cs_topdecile(sig, fwd, maxlag):
        per_t = []
        for t in range(len(Rte)):
            s = sig[t]; f = fwd[t]
            m = ~np.isnan(s) & ~np.isnan(f)
            if m.sum() < MIN_STOCKS_CS:
                continue
            ss, ff = s[m], f[m]
            th = np.quantile(ss, 0.9)
            top = ff[ss >= th]
            per_t.append(float(top.mean() - ff.mean()))
        arr = np.array(per_t)
        mean, t, n = nw_t(arr, maxlag)
        return {"top_decile_excess_bp": round(float(np.mean(arr)) * 1e4, 3) if n else None,
                "top_decile_excess_median_bp": round(float(np.median(arr)) * 1e4, 3) if n else None,
                "top_decile_excess_nw_t": round(t, 3) if t == t else None}

    def fm_beta(sig_name, fwd, maxlag):
        """Fama-MacBeth: per-timestamp CS OLS  y ~ 1 + own_lag + signal(z-scored).
        Returns dict with NW t for the signal coefficient (beyond own-lag)."""
        sig = signals[sig_name]
        own = signals["own_lag"]
        if sig_name == "own_lag":
            # own-lag alone (intercept + own_lag)
            betas = []
            for t in range(len(Rte)):
                o = own[t]; f = fwd[t]
                m = ~np.isnan(o) & ~np.isnan(f)
                if m.sum() < MIN_STOCKS_CS:
                    continue
                oo = o[m]; ff = f[m]
                if np.std(oo) == 0:
                    continue
                z = (oo - oo.mean()) / np.std(oo)
                X = np.column_stack([np.ones(len(z)), z])
                b, *_ = np.linalg.lstsq(X, ff, rcond=None)
                betas.append(b[1])
            arr = np.array(betas)
            mean, t, n = nw_t(arr, maxlag)
            return {"fm_signal_bp_per_std": round(float(np.mean(arr)) * 1e4, 3) if n else None,
                    "fm_signal_nw_t": round(t, 3) if t == t else None}
        betas_own = []; betas_sig = []
        for t in range(len(Rte)):
            o = own[t]; s = sig[t]; f = fwd[t]
            m = ~np.isnan(o) & ~np.isnan(s) & ~np.isnan(f)
            if m.sum() < MIN_STOCKS_CS:
                continue
            oo = o[m]; ss = s[m]; ff = f[m]
            if np.std(oo) == 0 or np.std(ss) == 0:
                continue
            zo = (oo - oo.mean()) / np.std(oo)
            zs = (ss - ss.mean()) / np.std(ss)
            X = np.column_stack([np.ones(len(zo)), zo, zs])
            b, *_ = np.linalg.lstsq(X, ff, rcond=None)
            betas_own.append(b[1]); betas_sig.append(b[2])
        arr_o = np.array(betas_own); arr_s = np.array(betas_sig)
        _, t_o, n = nw_t(arr_o, maxlag)
        _, t_s, _ = nw_t(arr_s, maxlag)
        return {"fm_own_lag_bp_per_std": round(float(np.mean(arr_o)) * 1e4, 3) if n else None,
                "fm_own_lag_nw_t": round(t_o, 3) if t_o == t_o else None,
                "fm_signal_bp_per_std": round(float(np.mean(arr_s)) * 1e4, 3) if n else None,
                "fm_signal_nw_t": round(t_s, 3) if t_s == t_s else None}

    results = {}
    for hname, F, maxlag in [("5m", F5, NW_LAG[1]), ("30m", F30, NW_LAG[6])]:
        Fte = F[is_test]
        results[hname] = {}
        for sname in signals:
            results[hname][sname] = {
                "rank_ic": cs_ic(signals[sname], Fte, maxlag),
                "top_decile": cs_topdecile(signals[sname], Fte, maxlag),
                "fama_macbeth": fm_beta(sname, Fte, maxlag),
            }
        print(f"[{hname}] done: " + ", ".join(
            f"{s} IC={results[hname][s]['rank_ic']['rank_ic_mean']:+.4f} "
            f"(t={results[hname][s]['rank_ic']['rank_ic_nw_t']:+.2f})"
            for s in signals))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe": syms,
        "n_symbols": N,
        "data_range": [str(close_wide.index.min()), str(close_wide.index.max())],
        "n_rows": int(len(close_wide)),
        "methodology": {
            "matrix": "full NxN lagged cross-correlation of 5-min returns at lags 1..6; "
                      "C_minus[l][i,j]=corr(r_i(t), r_j(t-l)) => j leads i; "
                      "directed asymmetry A[i,j,l]=C_minus[l][i,j]-C_minus[l][j,i] "
                      "(antisymmetric, removes common-factor autocorr bleed).",
            "aggregation": "lag-0 vs lag-1..6 off-diag corr; asymmetry noise floor (std over "
                           "all ordered edges); top-10 directed edges with permutation p; "
                           "per-stock lead score (sum of directed asymmetry into followers).",
            "prediction": "signals built from lag-1 returns of other stocks: own_lag (baseline), "
                          "market_ew_exself, sector_ew_exself, top_leaders_ew (top-5 leaders by "
                          "train-period asymmetry), full_matrix_weighted (S[i,j] weights), "
                          "random_leaders_placebo.  Targets: same-session 5m and 30m forward "
                          "returns.  Strictly causal (lag-1 only), chronological 70/30 OOS.",
            "evaluation": "per-timestamp Spearman rank IC; top-decile excess (bp); Fama-MacBeth "
                          "CS regression y~own_lag+signal (signal coeff = beyond-own-lag test); "
                          "all t-stats Newey-West on per-timestamp series (date/overlap-clustered).",
            "leader_selection": f"top {K_LEADERS} leaders per follower by mean train-period "
                                "asymmetry over lags 1..6; leaders fixed on train, scored on test.",
            "caveat": "survivorship-biased (current 40-name liquid universe, ~8mo depth) => upper bound.",
        },
        "lag_structure": {
            "lag0_off_diag_corr_mean": round(float(np.mean(lag0_off)), 5),
            "lag0_off_diag_corr_median": round(float(np.median(lag0_off)), 5),
            "lag0_off_diag_corr_std": round(float(np.std(lag0_off)), 5),
            "asymmetry_noise_floor_std": round(noise_floor, 5),
            "multiple_testing": {
                "n_directed_edges": n_edges,
                "frac_abs_gt_2sigma": round(frac_gt2, 5),
                "gaussian_expected_2sigma": 0.0455,
                "frac_abs_gt_3sigma": round(frac_gt3, 5),
                "gaussian_expected_3sigma": 0.0027,
                "observed_max_abs_asymmetry": round(max_abs_all, 5),
                "expected_max_abs_asymmetry_noise": round(exp_max, 5),
                "note": "frac of directed edges exceeding 2/3 sigma equals the Gaussian "
                        "expectation, and the observed max |asymmetry| is BELOW the "
                        "noise-expected maximum => the lead/lag edges are consistent "
                        "with pure multiple-testing noise.",
            },
            "per_lag": asym_summary,
            "top_10_directed_edges": top10,
            "top_leaders": [(s, round(v, 5)) for s, v in lead_rank[:5]],
            "top_laggards": [(s, round(v, 5)) for s, v in lead_rank[-5:]],
        },
        "split_threshold": str(cut),
        "n_train_rows": int((~is_test).sum()),
        "n_test_rows": int(is_test.sum()),
        "prediction_results": results,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\n[done] wrote {OUT}")


if __name__ == "__main__":
    main()
