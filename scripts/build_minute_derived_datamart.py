#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access.minute_derived import (  # noqa: E402
    DEFAULT_MINUTE_CUTOFF_TIME,
    DEFAULT_RESEARCH_IN_SAMPLE_END,
    MINUTE_DERIVED_FLOW_STATE_V1,
    default_minute_derived_root,
    derive_flow_state_for_day,
    minute_derived_partition_path,
    normalize_trade_date,
    write_flow_state_partition,
    yyyymmdd_range,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def candidate_minute_roots(explicit: str | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.getenv("FACTORFORGE_LOCAL_MINUTE_ROOT"):
        candidates.append(Path(os.environ["FACTORFORGE_LOCAL_MINUTE_ROOT"]).expanduser())
    if os.getenv("FACTORFORGE_DATA_CACHE"):
        candidates.append(Path(os.environ["FACTORFORGE_DATA_CACHE"]).expanduser() / "s3_parquet" / "minute_bar-raw_v1-0b2b836c57d763c6")
    candidates.extend([
        Path("/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6"),
        Path("/home/ubuntu/.qlib/raw_tushare/分钟数据/raw/stk_mins_1min"),
        Path.home() / ".qlib" / "raw_tushare" / "分钟数据" / "raw" / "stk_mins_1min",
    ])
    out: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            out.append(candidate)
            seen.add(key)
    return out


def minute_partition_files(root: Path, trade_date: str) -> list[Path]:
    date = normalize_trade_date(trade_date)
    date_dir = root / f"trade_date={date}"
    if date_dir.exists():
        parts = sorted(date_dir.glob("*.parquet"))
        if parts:
            return parts
    return sorted(root.glob(f"**/*{date}*.parquet"))


def read_minute_day(roots: list[Path], trade_date: str) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    columns = ["ts_code", "trade_date", "trade_time", "datetime", "open", "close", "vol", "amount"]
    for root in roots:
        files = minute_partition_files(root, trade_date)
        probes.append({"root": str(root), "exists": root.exists(), "file_count": len(files)})
        if not files:
            continue
        frames = []
        for path in files:
            try:
                frames.append(pd.read_parquet(path, columns=[col for col in columns if col != "datetime"]))
            except Exception:
                frames.append(pd.read_parquet(path))
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        return frame, {"source_root": str(root), "file_count": len(files), "files_head": [str(path) for path in files[:5]], "probes": probes}
    return None, {"status": "missing_raw_minute_partition", "probes": probes}


def maybe_sync_to_s3(local_path: Path, metadata_path: Path, s3_uri: str | None) -> dict[str, Any] | None:
    if not s3_uri:
        return None
    target = s3_uri.rstrip("/") + f"/{local_path.parent.name}/"
    started = time.perf_counter()
    commands = [
        ["aws", "s3", "cp", str(local_path), target],
        ["aws", "s3", "cp", str(metadata_path), target],
    ]
    results = []
    for cmd in commands:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        results.append({
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-1000:],
            "stderr_tail": proc.stderr[-1000:],
        })
        if proc.returncode != 0:
            break
    return {"s3_uri": s3_uri, "target": target, "seconds": time.perf_counter() - started, "commands": results}


def main() -> None:
    ap = argparse.ArgumentParser(description="Build reusable Factor Forge minute-derived datamart partitions.")
    ap.add_argument("--dataset", default=MINUTE_DERIVED_FLOW_STATE_V1, choices=[MINUTE_DERIVED_FLOW_STATE_V1])
    ap.add_argument("--start-date", default="2016-01-01")
    ap.add_argument("--end-date", default=DEFAULT_RESEARCH_IN_SAMPLE_END)
    ap.add_argument("--cutoff-time", default=DEFAULT_MINUTE_CUTOFF_TIME)
    ap.add_argument("--minute-root")
    ap.add_argument("--output-root", default=str(default_minute_derived_root()))
    ap.add_argument("--source-data-version", default=os.getenv("FACTORFORGE_MINUTE_SOURCE_DATA_VERSION") or "minute_bar_raw_v1")
    ap.add_argument("--source-minute-dataset-id", default="minute_bar")
    ap.add_argument("--batch-days", type=int, default=20)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--s3-uri", default=os.getenv("FACTORFORGE_MINUTE_DERIVED_S3_URI"))
    ap.add_argument("--profile-path")
    ap.add_argument("--failed-manifest")
    args = ap.parse_args()

    output_root = Path(args.output_root).expanduser()
    roots = candidate_minute_roots(args.minute_root)
    dates = yyyymmdd_range(args.start_date, args.end_date)
    profile_path = Path(args.profile_path).expanduser() if args.profile_path else output_root / "backfill_profiles" / f"minute_derived_backfill__{dates[0]}__{dates[-1]}.json"
    failed_manifest_path = Path(args.failed_manifest).expanduser() if args.failed_manifest else output_root / "backfill_profiles" / f"minute_derived_failed_dates__{dates[0]}__{dates[-1]}.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    processed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    s3_syncs: list[dict[str, Any]] = []
    for idx, trade_date in enumerate(dates):
        partition = minute_derived_partition_path(output_root, trade_date)
        if partition.exists() and not args.force:
            skipped.append({"trade_date": trade_date, "reason": "partition_exists", "path": str(partition)})
            continue
        day_started = time.perf_counter()
        try:
            minute_df, source_profile = read_minute_day(roots, trade_date)
            if minute_df is None or minute_df.empty:
                failed.append({"trade_date": trade_date, "reason": "missing_or_empty_raw_minute", "source_profile": source_profile})
                continue
            derived = derive_flow_state_for_day(
                minute_df,
                cutoff_time=args.cutoff_time,
                source_minute_dataset_id=args.source_minute_dataset_id,
                source_data_version=args.source_data_version,
            )
            metadata = write_flow_state_partition(
                derived,
                root=output_root,
                trade_date=trade_date,
                cutoff_time=args.cutoff_time,
                source_data_version=args.source_data_version,
            )
            meta_path = partition.with_name(partition.name.replace(".parquet", ".metadata.json"))
            s3_profile = maybe_sync_to_s3(partition, meta_path, args.s3_uri)
            if s3_profile:
                s3_syncs.append({"trade_date": trade_date, **s3_profile})
            processed.append({
                "trade_date": trade_date,
                "row_count": int(len(derived)),
                "minute_rows": int(len(minute_df)),
                "partition_path": str(partition),
                "artifact_hash": metadata.get("artifact_hash"),
                "seconds": time.perf_counter() - day_started,
                "source_profile": source_profile,
            })
        except Exception as exc:
            failed.append({"trade_date": trade_date, "reason": type(exc).__name__, "detail": str(exc)})
        if (idx + 1) % max(1, args.batch_days) == 0:
            interim = {
                "status": "running",
                "updated_at_utc": utc_now(),
                "processed_count": len(processed),
                "skipped_count": len(skipped),
                "failed_count": len(failed),
                "last_trade_date": trade_date,
            }
            profile_path.write_text(json.dumps(interim, ensure_ascii=False, indent=2), encoding="utf-8")

    profile = {
        "dataset_id": args.dataset,
        "status": "complete" if not failed else "partial",
        "started_at_utc": utc_now(),
        "date_start": dates[0],
        "date_end": dates[-1],
        "date_count": len(dates),
        "output_root": str(output_root),
        "source_data_version": args.source_data_version,
        "cutoff_time": args.cutoff_time,
        "minute_roots": [str(root) for root in roots],
        "processed_count": len(processed),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "processed_head": processed[:5],
        "processed_tail": processed[-5:],
        "skipped_head": skipped[:5],
        "failed_dates": failed,
        "s3_syncs_head": s3_syncs[:5],
        "profile_path": str(profile_path),
        "failed_manifest_path": str(failed_manifest_path),
        "total_seconds": time.perf_counter() - started,
    }
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    failed_manifest_path.write_text(json.dumps({"failed_dates": failed}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": "ACCEPT" if not failed else "PARTIAL", "profile_path": str(profile_path), "failed_manifest_path": str(failed_manifest_path), "processed": len(processed), "skipped": len(skipped), "failed": len(failed)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
