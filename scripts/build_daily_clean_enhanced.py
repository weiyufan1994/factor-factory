#!/usr/bin/env python3
"""
Build enhanced daily_clean.parquet with free_float_mcap column (Mac version).
Uses AWS CLI to stream CSV from S3, no boto3 required.

free_float_mcap = close * free_share
ln_mcap_free = ln(free_float_mcap)

Workflow:
1. Stream all daily_basic_incremental CSVs from S3
2. Forward-fill free_share per stock across dates
3. Compute free_float_mcap = close * free_share
4. Merge into daily_clean.parquet (on ts_code + trade_date)
5. Save as daily_clean_enhanced.parquet, optionally overwrite daily_clean.parquet
"""

import io
import logging
import os
import subprocess
import sys
from datetime import datetime

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_daily_clean_enhanced")

LOCAL_DEST = "/Users/humphrey/projects/factor-factory/data/clean/daily_clean.parquet"
LOCAL_ENHANCED = "/Users/humphrey/projects/factor-factory/data/clean/daily_clean_enhanced.parquet"


def s3_list_partitions(prefix: str) -> list[tuple[str, str]]:
    """List all CSV partitions under S3 prefix. Returns [(date_str, s3_key), ...]."""
    result = subprocess.run(
        ["aws", "s3", "ls", "--recursive", prefix],
        capture_output=True, text=True, check=True
    )
    partitions = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        # Format: 2026-04-15 11:26:53     369952 path/to/trade_date=20160104/daily_basic_20160104.csv
        parts = line.split()
        if len(parts) < 4:
            continue
        key = parts[3]
        if "trade_date=" in key and key.endswith(".csv"):
            date_str = key.split("trade_date=")[1].split("/")[0]
            partitions.append((date_str, key))
    partitions.sort(key=lambda x: x[0])
    return partitions


def load_all_daily_basic() -> pd.DataFrame:
    """Stream all daily_basic CSVs from S3, concatenate into one DataFrame."""
    S3_PREFIX = "s3://yufan-data-lake/tushares/行情数据/daily_basic_incremental"
    partitions = s3_list_partitions(S3_PREFIX)
    log.info(f"Found {len(partitions)} S3 partitions")

    dfs = []
    for i, (date_str, key) in enumerate(partitions):
        if i % 200 == 0:
            log.info(f"  Loading partition {i+1}/{len(partitions)} (date={date_str})")
        try:
            proc = subprocess.run(
                ["aws", "s3", "cp", key, "-"],
                capture_output=True, text=True, check=True
            )
            df = pd.read_csv(
                io.StringIO(proc.stdout),
                usecols=["ts_code", "trade_date", "close", "free_share"]
            )
            df["_date_int"] = int(date_str)
            dfs.append(df)
        except Exception as e:
            log.warning(f"  Failed: {key}: {e}")

    log.info(f"Loaded {len(dfs)} partitions, total rows ≈ {sum(len(d) for d in dfs):,}")
    combined = pd.concat(dfs, ignore_index=True)
    return combined


def forward_fill_free_share(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill free_share per stock across dates."""
    log.info(f"Forward filling free_share: {df['ts_code'].nunique()} stocks, "
             f"{df['_date_int'].nunique()} dates")
    df = df.sort_values(["ts_code", "_date_int"])
    df["free_share"] = df.groupby("ts_code")["free_share"].ffill()
    df = df.dropna(subset=["free_share"])
    df = df.drop_duplicates(subset=["ts_code", "_date_int"], keep="last")
    log.info(f"After ffill + dedup: {len(df):,} rows")
    return df


def compute_ln_mcap(df: pd.DataFrame) -> pd.DataFrame:
    """Compute free_float_mcap and ln_mcap_free."""
    import numpy as np
    df = df.copy()
    df["free_float_mcap"] = df["close"] * df["free_share"]
    df["ln_mcap_free"] = np.log(df["free_float_mcap"].clip(lower=1))
    return df[["ts_code", "_date_int", "close", "free_share",
               "free_float_mcap", "ln_mcap_free"]].copy()


def merge_into_daily_clean(mcap_df: pd.DataFrame) -> pd.DataFrame:
    """Merge ln_mcap_free into daily_clean.parquet."""
    log.info(f"Reading daily_clean from {LOCAL_DEST}")
    daily = pd.read_parquet(LOCAL_DEST)
    log.info(f"daily_clean shape: {daily.shape}")

    daily["_date_int"] = daily["trade_date"].astype(str).str.replace("-", "").astype(int)

    before = len(daily)
    daily = daily.merge(
        mcap_df[["ts_code", "_date_int", "ln_mcap_free", "free_float_mcap"]],
        on=["ts_code", "_date_int"],
        how="left"
    )
    log.info(f"After merge: {len(daily):,} rows; "
             f"ln_mcap_free null ratio: {daily['ln_mcap_free'].isna().mean():.3%}")
    return daily


def main():
    t0 = datetime.now()

    log.info("Step 1: Stream all daily_basic partitions from S3")
    df = load_all_daily_basic()

    log.info("Step 2: Forward-fill free_share per stock")
    df = forward_fill_free_share(df)

    log.info("Step 3: Compute free_float_mcap = close * free_share")
    mcap_df = compute_ln_mcap(df)

    log.info("Step 4: Merge into daily_clean.parquet")
    daily = merge_into_daily_clean(mcap_df)

    log.info("Step 5: Save enhanced parquet")
    daily.to_parquet(LOCAL_ENHANCED, index=False)
    log.info(f"Saved: {LOCAL_ENHANCED}")
    log.info(f"File size: {os.path.getsize(LOCAL_ENHANCED) / 1024**2:.1f} MB")

    elapsed = (datetime.now() - t0).total_seconds()
    log.info(f"Done in {elapsed:.0f}s ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
