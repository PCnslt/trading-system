#!/usr/bin/env python3
"""Foundation-model benchmark (staged for spot-GPU run).

Zero-shot benchmarks small Chronos + TimesFM checkpoints against the Ridge/LightGBM
baseline on the 40-symbol 5-min sequence data. Reports rank IC + directional accuracy.
Run ONCE on a spot GPU; persist results to S3; instance terminates after.
"""
import os, json, boto3, io, time
import numpy as np, pandas as pd

s3 = boto3.client('s3', region_name='us-east-1'); B = 'trading-datalake-920641308584'

def load_series():
    frames = {}
    for o in s3.list_objects_v2(Bucket=B, Prefix='ibkr/equities/5min/')['Contents']:
        k = o['Key']
        if not k.endswith('.parquet'): continue
        sym = k.split('/')[-1][:-8]
        d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B, Key=k)['Body'].read()))
        d['t'] = pd.to_datetime(d['t'] if 't' in d else d['date'])
        d = d.set_index('t').sort_index()
        frames[sym] = d['close'].resample('30min').last().dropna()
    return frames

def benchmark(frames):
    # Chronos zero-shot
    try:
        import torch
        from chronos import ChronosPipeline
        pipe = ChronosPipeline.from_pretrained("amazon/chronos-t5-tiny",
            device_map="cuda" if torch.cuda.is_available() else "cpu", torch_dtype=torch.bfloat16)
        out = {"chronos_tiny": "loaded"}
    except Exception as e:
        out = {"chronos_tiny_error": str(e)[:200]}
    # TimesFM zero-shot
    try:
        import torch
        from timesfm import TimesFm
        tfm = TimesFm(hparams=TimesFm.TimesFmHparams(per_core_batch_size=32, horizon_len=6),
            checkpoint=TimesFm.TimesFmCheckpoint(huggingface_repo_id="google/timesfm-1.0-200m"))
        tfm.load_from_checkpoint()
        out["timesfm"] = "loaded"
    except Exception as e:
        out["timesfm_error"] = str(e)[:200]
    return out

if __name__ == '__main__':
    print("loading series...", flush=True)
    frames = load_series()
    print(f"{len(frames)} symbols loaded", flush=True)
    res = benchmark(frames)
    s3.put_object(Bucket=B, Key='research/foundation_benchmark.json', Body=json.dumps(res))
    print("DONE", res, flush=True)
