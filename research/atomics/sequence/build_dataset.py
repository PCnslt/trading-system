"""Phase 4 — intraday SEQUENCE dataset builder.

Builds a per-symbol 5-minute feature frame (flat scalars) *and* a sequence
representation (last 12 bars x 4 channels) for ~40 liquid US equities from the
S3 data lake. Everything is strictly causal (features <= t, label = forward
30-min return). Chronological 70/30 split by bar timestamp (never shuffled).

Reuses the ATOMIC-STACK target registry from atomics.core (read-only import).
Writes intermediate artifacts to cache/ (git-ignored) and is consumed by
benchmark.py.
"""
from __future__ import annotations
import io, os, sys, json
import numpy as np
import pandas as pd
import boto3
from numpy.lib.stride_tricks import sliding_window_view

sys.path.insert(0, "/home/ubuntu/trading-system/research")
from atomics.core import build_target  # noqa: E402

BUCKET = "trading-datalake-920641308584"
PREFIX = "ibkr/equities/5min/"
REGION = "us-east-1"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
RAW_DIR = os.path.join(CACHE_DIR, "raw")

SEQ_T = 12
SEQ_CHANNELS = ["return", "volume_ratio", "range_pct", "vwap_dist"]

FLAT_FEATURES = [
    "r1", "r3", "r6", "r12",
    "rsi14", "vwap_dist", "rel_vol", "realized_vol20",
    "cs_ret_rank", "cs_vol_rank", "minute_of_day",
]


def list_symbols(s3) -> list[str]:
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX, MaxKeys=200)
    syms = []
    for o in r.get("Contents", []):
        key = o["Key"]
        if key.endswith(".parquet"):
            syms.append(key.split("/")[-1].split(".parquet")[0])
    return sorted(syms)


def download_raw(s3, symbol: str) -> pd.DataFrame:
    path = os.path.join(RAW_DIR, f"{symbol}.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)
    obj = s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}{symbol}.parquet")
    df = pd.read_parquet(io.BytesIO(obj["Body"].read()))
    df.to_parquet(path)
    return df


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def session_vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    return (pv.groupby(df["date"].dt.date).cumsum()
            / df["volume"].groupby(df["date"].dt.date).cumsum())


def build_symbol_frame(df: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame, np.ndarray]:
    """Per-symbol flat features + sequence tensor + validity masks."""
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"]
    n = len(df)

    # ---- flat features (all causal / <= t) ---------------------------------
    r1 = close.pct_change(1)
    r3 = close.pct_change(3)
    r6 = close.pct_change(6)
    r12 = close.pct_change(12)
    rsi14 = rsi(close, 14)
    vwap = session_vwap(df)
    vwap_dist = close / vwap - 1.0
    rel_vol = df["volume"] / df["volume"].rolling(20).mean()
    realized_vol20 = close.pct_change(1).rolling(20).std()
    minute_of_day = (df["date"].dt.hour * 60 + df["date"].dt.minute).astype(float)

    # label = forward 30-min return (horizon 6), strictly after t
    label = build_target(df, "30m_return")

    flat = pd.DataFrame({
        "symbol": symbol,
        "date": df["date"],
        "r1": r1, "r3": r3, "r6": r6, "r12": r12,
        "rsi14": rsi14, "vwap_dist": vwap_dist, "rel_vol": rel_vol,
        "realized_vol20": realized_vol20, "minute_of_day": minute_of_day,
        "label": label,
    })

    # ---- sequence channels (per-bar, causal) -------------------------------
    ch_return = close.pct_change(1).to_numpy(dtype=np.float32)
    ch_volratio = rel_vol.to_numpy(dtype=np.float32)
    ch_range = ((df["high"] - df["low"]) / close).to_numpy(dtype=np.float32)
    ch_vwapdist = vwap_dist.to_numpy(dtype=np.float32)

    channels = np.stack([ch_return, ch_volratio, ch_range, ch_vwapdist], axis=1)  # (n, 4)

    seq_full = np.full((n, SEQ_T, len(SEQ_CHANNELS)), np.nan, dtype=np.float32)
    if n >= SEQ_T:
        win = sliding_window_view(channels, SEQ_T, axis=0).transpose(0, 2, 1)  # (n-11, 12, 4)
        seq_full[SEQ_T - 1:] = win

    return flat, seq_full


def build() -> dict:
    os.makedirs(RAW_DIR, exist_ok=True)
    s3 = boto3.client("s3", region_name=REGION)
    symbols = list_symbols(s3)
    print(f"[build] {len(symbols)} symbols: {symbols[:5]} ... {symbols[-2:]}")

    flat_parts, seq_parts, seq_valid_parts = [], [], []
    sym_list = []
    for sym in symbols:
        raw = download_raw(s3, sym)
        flat, seq_full = build_symbol_frame(raw, sym)
        flat_parts.append(flat)
        seq_parts.append(seq_full)
        # valid sequence = window has no NaN (warmup) and no lookahead
        seq_valid_parts.append(~np.isnan(seq_full).any(axis=(1, 2)))
        sym_list.append(sym)
        print(f"  {sym}: {len(raw)} bars")

    df_all = pd.concat(flat_parts, ignore_index=True)

    # ---- cross-sectional ranks (at each timestamp, across the ~40 names) ---
    df_all["cs_ret_rank"] = df_all.groupby("date")["r6"].rank(pct=True)
    df_all["cs_vol_rank"] = df_all.groupby("date")["rel_vol"].rank(pct=True)

    # ---- global chronological order (stable) -------------------------------
    df_all = df_all.sort_values(["date", "symbol"], kind="stable").reset_index(drop=True)
    N = len(df_all)

    seq_all = np.empty((N, SEQ_T, len(SEQ_CHANNELS)), dtype=np.float32)
    seq_valid_all = np.zeros(N, dtype=bool)
    for sym, seq_full, sv in zip(sym_list, seq_parts, seq_valid_parts):
        m = (df_all["symbol"] == sym).to_numpy()
        seq_all[m] = seq_full
        seq_valid_all[m] = sv

    # ---- unified sample set (same rows for flat & sequence models) --------
    label_ok = df_all["label"].notna().to_numpy()
    flat_ok = df_all[FLAT_FEATURES].notna().all(axis=1).to_numpy()
    mask = label_ok & flat_ok & seq_valid_all
    print(f"[build] rows={N} label_ok={label_ok.sum()} flat_ok={flat_ok.sum()} "
          f"seq_ok={seq_valid_all.sum()} sample={mask.sum()}")

    df_all["sample"] = mask

    # ---- chronological 70/30 split (by unique timestamp, never shuffle) ----
    times = np.sort(df_all.loc[mask, "date"].unique())
    split_idx = int(0.70 * len(times))
    threshold = times[split_idx]
    print(f"[build] split threshold: {threshold}  "
          f"(unique timestamps={len(times)}, split_idx={split_idx})")
    df_all["split"] = np.where(df_all["date"] < threshold, "train", "test")

    # ---- persist samples only ---------------------------------------------
    samples = df_all[mask].reset_index(drop=True)
    seq_samples = seq_all[mask]

    samples_path = os.path.join(CACHE_DIR, "samples.parquet")
    seq_path = os.path.join(CACHE_DIR, "seq.npy")
    samples.to_parquet(samples_path)
    np.save(seq_path, seq_samples)

    meta = {
        "target": "30m_return",
        "target_horizon_bars": 6,
        "n_symbols": len(symbols),
        "symbols": symbols,
        "n_rows_total": int(N),
        "n_samples": int(mask.sum()),
        "n_train": int((samples["split"] == "train").sum()),
        "n_test": int((samples["split"] == "test").sum()),
        "split_threshold": str(threshold),
        "split_ratio": 0.70,
        "flat_features": FLAT_FEATURES,
        "sequence_shape": [SEQ_T, len(SEQ_CHANNELS)],
        "sequence_channels": SEQ_CHANNELS,
        "data_range": [str(df_all["date"].min()), str(df_all["date"].max())],
    }
    with open(os.path.join(CACHE_DIR, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[build] wrote {samples_path} ({len(samples)} rows), {seq_path} "
          f"({seq_samples.shape}, {seq_samples.dtype})")
    return meta


if __name__ == "__main__":
    build()
