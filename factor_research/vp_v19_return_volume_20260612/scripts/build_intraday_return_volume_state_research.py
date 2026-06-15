#!/usr/bin/env python3
"""
Build research-side intraday return-volume state from local minute bars.

This is not a production P0 datamart. It is a reusable research artifact that
lets V19/V20-style factors consume daily return-volume states without repeatedly
scanning raw one-minute bars.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd

from research_vp_v18_drift_persistence_eval import clean_date
from research_vp_v19_return_volume_eval import derive_return_volume_for_day, read_minute_day


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minute-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start-date", default="20160104")
    parser.add_argument("--end-date", default="20250711")
    parser.add_argument("--cutoff-time", default="14:50:00")
    parser.add_argument("--max-dates", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--proof-path", type=Path)
    parser.add_argument("--progress-every", type=int, default=50)
    return parser.parse_args()


def discover_dates(minute_root: Path, start_date: str, end_date: str, max_dates: int | None) -> list[str]:
    dates: list[str] = []
    for path in sorted(minute_root.glob("trade_date=*")):
        if not path.is_dir():
            continue
        if not list(path.glob("*.parquet")):
            continue
        date = clean_date(path.name.split("=", 1)[-1])
        if start_date <= date <= end_date:
            dates.append(date)
    if max_dates is not None and max_dates > 0:
        dates = dates[:max_dates]
    return dates


def output_path(output_root: Path, trade_date: str) -> Path:
    return output_root / f"trade_date={trade_date}" / "part-000.parquet"


def build_one_day(minute_root: Path, output_root: Path, trade_date: str, cutoff_time: str, overwrite: bool) -> dict[str, Any]:
    started = time.perf_counter()
    out_path = output_path(output_root, trade_date)
    if out_path.exists() and not overwrite:
        try:
            rows = len(pd.read_parquet(out_path, columns=["ts_code"]))
        except Exception:
            rows = None
        return {
            "trade_date": trade_date,
            "status": "cached",
            "rows": rows,
            "seconds": time.perf_counter() - started,
            "path": str(out_path),
        }

    minute, source_profile = read_minute_day([minute_root], trade_date)
    if minute is None or minute.empty:
        return {
            "trade_date": trade_date,
            "status": "missing_minute",
            "rows": 0,
            "seconds": time.perf_counter() - started,
            "source_profile": source_profile,
        }
    state = derive_return_volume_for_day(minute, trade_date, cutoff_time)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".parquet.tmp")
    state.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, out_path)
    return {
        "trade_date": trade_date,
        "status": "built",
        "rows": int(len(state)),
        "minute_rows": int(len(minute)),
        "seconds": time.perf_counter() - started,
        "path": str(out_path),
        "source_profile": source_profile,
    }


def main() -> None:
    args = parse_args()
    minute_root = args.minute_root.expanduser()
    output_root = args.output_root.expanduser()
    output_root.mkdir(parents=True, exist_ok=True)
    start_date = clean_date(args.start_date)
    end_date = clean_date(args.end_date)
    proof_path = args.proof_path or (output_root / "_meta" / "intraday_return_volume_state_research.proof.json")
    proof_path.parent.mkdir(parents=True, exist_ok=True)

    dates = discover_dates(minute_root, start_date, end_date, args.max_dates)
    profiles: list[dict[str, Any]] = []
    row_count = 0
    started = time.perf_counter()
    print(f"[START] minute_root={minute_root}", flush=True)
    print(f"[START] output_root={output_root}", flush=True)
    print(f"[DATES] {len(dates):,} dates in {start_date}-{end_date}", flush=True)
    for idx, date in enumerate(dates, start=1):
        profile = build_one_day(minute_root, output_root, date, args.cutoff_time, args.overwrite)
        profiles.append(profile)
        row_count += int(profile.get("rows") or 0)
        if idx % args.progress_every == 0 or idx == len(dates):
            built = sum(1 for item in profiles if item.get("status") == "built")
            cached = sum(1 for item in profiles if item.get("status") == "cached")
            missing = sum(1 for item in profiles if item.get("status") == "missing_minute")
            print(
                f"[PROGRESS] dates={idx:,}/{len(dates):,} built={built:,} cached={cached:,} "
                f"missing={missing:,} rows={row_count:,}",
                flush=True,
            )

    status_counts: dict[str, int] = {}
    for item in profiles:
        status = str(item.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
    proof = {
        "dataset_id": "intraday_return_volume_state_research_v1",
        "production_status": "research_artifact_not_p0",
        "minute_root": str(minute_root),
        "output_root": str(output_root),
        "start_date": start_date,
        "end_date": end_date,
        "cutoff_time": args.cutoff_time,
        "date_count_requested": len(dates),
        "status_counts": status_counts,
        "row_count": row_count,
        "seconds": time.perf_counter() - started,
        "profiles_head": profiles[:10],
        "profiles_tail": profiles[-10:],
    }
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[OK] wrote proof {proof_path}", flush=True)


if __name__ == "__main__":
    main()
