#!/usr/bin/env python3
"""
Materialize research-side intraday return-volume state from S3 minute bars.

This script is intentionally self-contained for one-off EC2/OpenClaw execution:
it downloads one trade_date parquet to a local temp directory, computes daily
state rows, uploads the result to S3, then removes the raw temp file.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


FLOW_FEATURE_COLUMNS = [
    "ts_code",
    "trade_date",
    "rv_corr",
    "rv_corr_pos",
    "up_down_amount_share_diff",
    "downside_amount_share",
    "upside_amount_share",
    "amount_weighted_return",
    "impact_efficiency",
    "downside_absorption",
    "high_volume_downside_break",
    "cutoff_return",
    "drawdown_recovery",
    "minute_count_flow",
    "flow_amount_total",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-s3-prefix", default="s3://yufan-data-lake/tushares/分钟数据/raw/stk_mins_1min/")
    parser.add_argument(
        "--output-s3-prefix",
        default="s3://yufan-data-lake/factorforge/research_datamart/intraday_return_volume_state_research/v1/",
    )
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/factorforge_v19_return_volume_materialize"))
    parser.add_argument("--start-date", default="20160104")
    parser.add_argument("--end-date", default="20250711")
    parser.add_argument("--cutoff-time", default="14:50:00")
    parser.add_argument("--max-dates", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--proof-name", default="intraday_return_volume_state_research.proof.json")
    return parser.parse_args()


def clean_date(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value))
    return digits[:8]


def cutoff_to_hhmmss(value: str) -> int:
    digits = re.sub(r"[^0-9]", "", str(value))
    if len(digits) <= 4:
        return int(digits) * 100
    return int(digits[:6])


def time_key(series: pd.Series) -> pd.Series:
    token = series.astype(str).str.strip().str.split().str[-1].str.replace(":", "", regex=False)
    digits = token.str.extract(r"(\d{3,6})$", expand=False).fillna("145000")
    numeric = pd.to_numeric(digits, errors="coerce")
    short = numeric.where(digits.str.len() > 4, numeric * 100)
    return short.fillna(145000).astype(int)


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"command failed rc={result.returncode}: {' '.join(cmd)}\n{message}")
    return result


def list_s3(s3_prefix: str) -> list[str]:
    result = run(["aws", "s3", "ls", s3_prefix, "--recursive"], check=False)
    if result.returncode != 0:
        return []
    return result.stdout.splitlines()


def parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3 uri: {uri}")
    rest = uri[5:]
    bucket, _, prefix = rest.partition("/")
    return bucket, prefix.rstrip("/") + "/"


def discover_raw_targets(raw_s3_prefix: str, start_date: str, end_date: str, max_dates: int | None) -> list[dict[str, Any]]:
    lines = list_s3(raw_s3_prefix)
    targets: list[dict[str, Any]] = []
    bucket, _ = parse_s3_uri(raw_s3_prefix)
    for line in lines:
        parts = line.split(maxsplit=3)
        if len(parts) < 4:
            continue
        size = int(parts[2])
        key = parts[3]
        if "trade_date=" not in key or not key.endswith(".parquet"):
            continue
        date = clean_date(key.split("trade_date=", 1)[1].split("/", 1)[0])
        if start_date <= date <= end_date:
            targets.append({"date": date, "size": size, "key": key, "uri": f"s3://{bucket}/{key}"})
    targets = sorted({item["date"]: item for item in targets}.values(), key=lambda item: item["date"])
    if max_dates is not None and max_dates > 0:
        targets = targets[:max_dates]
    return targets


def discover_output_dates(output_s3_prefix: str) -> set[str]:
    dates: set[str] = set()
    for line in list_s3(output_s3_prefix):
        parts = line.split(maxsplit=3)
        if len(parts) < 4:
            continue
        key = parts[3]
        if "trade_date=" in key and key.endswith(".parquet"):
            dates.add(clean_date(key.split("trade_date=", 1)[1].split("/", 1)[0]))
    return dates


def corr_or_nan(x: pd.Series, y: pd.Series) -> float:
    if len(x) < 10:
        return np.nan
    sx = float(np.nanstd(x))
    sy = float(np.nanstd(y))
    if sx == 0.0 or sy == 0.0 or not math.isfinite(sx) or not math.isfinite(sy):
        return np.nan
    return float(np.corrcoef(x, y)[0, 1])


def derive_return_volume_for_day(minute_df: pd.DataFrame, trade_date: str, cutoff_time: str) -> pd.DataFrame:
    cutoff = cutoff_to_hhmmss(cutoff_time)
    minute = minute_df.copy()
    if "trade_time" not in minute.columns and "bar_time" in minute.columns:
        minute["trade_time"] = minute["bar_time"]
    if "trade_time" not in minute.columns and "datetime" in minute.columns:
        minute["trade_time"] = minute["datetime"]
    if "trade_time" not in minute.columns:
        minute["trade_time"] = cutoff_time
    if "trade_date" not in minute.columns:
        minute["trade_date"] = trade_date
    if "open" not in minute.columns:
        minute["open"] = minute["close"]
    minute["trade_date"] = minute["trade_date"].map(clean_date)
    minute["hhmmss"] = time_key(minute["trade_time"])
    minute = minute[minute["hhmmss"] <= cutoff].copy()
    for col in ["open", "close", "amount", "vol"]:
        if col in minute.columns:
            minute[col] = pd.to_numeric(minute[col], errors="coerce")
    if "amount" not in minute.columns and "vol" in minute.columns:
        minute["amount"] = minute["vol"]
    minute = minute.dropna(subset=["ts_code", "trade_date", "open", "close", "amount"])
    minute = minute[(minute["open"] > 0) & (minute["close"] > 0) & (minute["amount"].abs() > 0)]
    if minute.empty:
        return pd.DataFrame(columns=FLOW_FEATURE_COLUMNS)

    minute = minute.sort_values(["ts_code", "trade_date", "hhmmss"]).reset_index(drop=True)
    grouped = minute.groupby(["ts_code", "trade_date"], sort=False)
    minute["prev_close"] = grouped["close"].shift(1)
    first_open = grouped["open"].transform("first")
    minute["ret"] = np.log(minute["close"] / minute["prev_close"])
    first_mask = minute["prev_close"].isna()
    minute.loc[first_mask, "ret"] = np.log(minute.loc[first_mask, "close"] / minute.loc[first_mask, "open"])
    minute["ret"] = minute["ret"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    minute["amount_abs"] = minute["amount"].abs()
    minute["log_amount"] = np.log1p(minute["amount_abs"])
    minute["pos_amount"] = np.where(minute["ret"] > 0, minute["amount_abs"], 0.0)
    minute["neg_amount"] = np.where(minute["ret"] < 0, minute["amount_abs"], 0.0)
    minute["ret_amount"] = minute["ret"] * minute["amount_abs"]
    minute["abs_ret_amount"] = minute["ret"].abs() * minute["amount_abs"]

    close_min = grouped["close"].transform("min")
    last_close = grouped["close"].transform("last")
    minute["first_open"] = first_open
    minute["last_close"] = last_close
    minute["min_close"] = close_min

    rows: list[dict[str, Any]] = []
    for (ts_code, date), group in minute.groupby(["ts_code", "trade_date"], sort=False):
        gross = float(group["amount_abs"].sum())
        if gross <= 0:
            continue
        ret = group["ret"]
        log_amount = group["log_amount"]
        pos_share = float(group["pos_amount"].sum() / gross)
        neg_share = float(group["neg_amount"].sum() / gross)
        cutoff_ret = float(group["last_close"].iloc[-1] / group["first_open"].iloc[0] - 1.0)
        max_drawdown = float(group["min_close"].iloc[0] / group["first_open"].iloc[0] - 1.0)
        recovery = max(0.0, cutoff_ret - max_drawdown)
        abs_ret_amount = float(group["abs_ret_amount"].sum())
        amount_weighted_return = float(group["ret_amount"].sum() / gross)
        impact_eff = float(cutoff_ret / (abs_ret_amount / gross + 1e-8))
        rv_corr = corr_or_nan(ret, log_amount)
        rows.append(
            {
                "ts_code": str(ts_code),
                "trade_date": clean_date(date),
                "rv_corr": rv_corr,
                "rv_corr_pos": max(0.0, rv_corr) if math.isfinite(rv_corr) else 0.0,
                "up_down_amount_share_diff": pos_share - neg_share,
                "downside_amount_share": neg_share,
                "upside_amount_share": pos_share,
                "amount_weighted_return": amount_weighted_return,
                "impact_efficiency": impact_eff,
                "downside_absorption": neg_share * recovery,
                "high_volume_downside_break": neg_share * max(0.0, -cutoff_ret),
                "cutoff_return": cutoff_ret,
                "drawdown_recovery": recovery,
                "minute_count_flow": int(len(group)),
                "flow_amount_total": gross,
            }
        )
    return pd.DataFrame(rows, columns=FLOW_FEATURE_COLUMNS)


def read_minute(path: Path) -> pd.DataFrame:
    columns = ["ts_code", "trade_date", "trade_time", "bar_time", "datetime", "open", "close", "amount", "vol"]
    physical = pq.ParquetFile(path).schema_arrow.names
    use_cols = [col for col in columns if col in physical]
    return pd.read_parquet(path, columns=use_cols)


def upload_file(local_path: Path, s3_uri: str) -> None:
    run(["aws", "s3", "cp", str(local_path), s3_uri, "--no-progress"])


def main() -> None:
    args = parse_args()
    start_date = clean_date(args.start_date)
    end_date = clean_date(args.end_date)
    raw_dir = args.work_dir / "raw"
    out_dir = args.work_dir / "out"
    meta_dir = args.work_dir / "_meta"
    for path in [raw_dir, out_dir, meta_dir]:
        path.mkdir(parents=True, exist_ok=True)

    output_prefix = args.output_s3_prefix.rstrip("/") + "/"
    output_dates = set() if args.overwrite else discover_output_dates(output_prefix)
    targets = discover_raw_targets(args.raw_s3_prefix, start_date, end_date, args.max_dates)

    profiles: list[dict[str, Any]] = []
    row_count = 0
    started = time.perf_counter()
    print(f"[START] raw_s3_prefix={args.raw_s3_prefix}", flush=True)
    print(f"[START] output_s3_prefix={output_prefix}", flush=True)
    print(f"[TARGETS] count={len(targets):,} output_cached_dates={len(output_dates):,}", flush=True)

    for idx, target in enumerate(targets, start=1):
        date = target["date"]
        item_start = time.perf_counter()
        out_s3_uri = f"{output_prefix}trade_date={date}/part-000.parquet"
        if date in output_dates and not args.overwrite:
            profiles.append({"trade_date": date, "status": "cached_s3", "rows": None, "seconds": 0.0, "s3_uri": out_s3_uri})
            continue

        raw_path = raw_dir / f"{date}.parquet"
        out_path = out_dir / f"{date}.parquet"
        try:
            run(["aws", "s3", "cp", target["uri"], str(raw_path), "--no-progress"])
            minute = read_minute(raw_path)
            state = derive_return_volume_for_day(minute, date, args.cutoff_time)
            state.to_parquet(out_path, index=False)
            upload_file(out_path, out_s3_uri)
            rows = int(len(state))
            row_count += rows
            profiles.append(
                {
                    "trade_date": date,
                    "status": "built_uploaded",
                    "rows": rows,
                    "minute_rows": int(len(minute)),
                    "raw_bytes": int(target["size"]),
                    "seconds": time.perf_counter() - item_start,
                    "s3_uri": out_s3_uri,
                }
            )
        except Exception as exc:
            profiles.append(
                {
                    "trade_date": date,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "seconds": time.perf_counter() - item_start,
                    "source_uri": target["uri"],
                }
            )
        finally:
            raw_path.unlink(missing_ok=True)
            out_path.unlink(missing_ok=True)

        if idx % args.progress_every == 0 or idx == len(targets):
            counts: dict[str, int] = {}
            for item in profiles:
                status = str(item.get("status"))
                counts[status] = counts.get(status, 0) + 1
            print(f"[PROGRESS] dates={idx:,}/{len(targets):,} rows={row_count:,} status_counts={counts}", flush=True)

    counts: dict[str, int] = {}
    for item in profiles:
        status = str(item.get("status"))
        counts[status] = counts.get(status, 0) + 1
    proof = {
        "dataset_id": "intraday_return_volume_state_research_v1",
        "production_status": "research_artifact_not_p0",
        "raw_s3_prefix": args.raw_s3_prefix,
        "output_s3_prefix": output_prefix,
        "work_dir": str(args.work_dir),
        "start_date": start_date,
        "end_date": end_date,
        "cutoff_time": args.cutoff_time,
        "target_count": len(targets),
        "status_counts": counts,
        "row_count_built_this_run": row_count,
        "seconds": time.perf_counter() - started,
        "profiles_head": profiles[:10],
        "profiles_tail": profiles[-10:],
    }
    proof_path = meta_dir / args.proof_name
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    proof_s3_uri = f"{output_prefix}_meta/{args.proof_name}"
    upload_file(proof_path, proof_s3_uri)
    print(f"[OK] wrote proof {proof_s3_uri}", flush=True)
    shutil.rmtree(raw_dir, ignore_errors=True)
    shutil.rmtree(out_dir, ignore_errors=True)
    if counts.get("failed", 0):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
