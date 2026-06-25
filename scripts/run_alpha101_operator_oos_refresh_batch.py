#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class BatchWindow:
    start: str
    end: str

    @property
    def window_id(self) -> str:
        return f"{self.start}_{self.end}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Checkpointed batch wrapper for generic Alpha101 operator OOS factor-value refresh."
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source-report-id", required=True)
    parser.add_argument("--factor-id", required=True)
    parser.add_argument("--formula", required=True)
    parser.add_argument("--target-start", required=True)
    parser.add_argument("--target-end", required=True)
    parser.add_argument("--dataset-id", default="clean_daily_bar_oos_slice")
    parser.add_argument("--catalog-path")
    parser.add_argument("--universe", default="a_share_all")
    parser.add_argument("--history-start", help="Optional global fetch history start used for every batch.")
    parser.add_argument("--expected-formula-hash", help="Optional parent/source formula hash that every batch must match.")
    parser.add_argument("--engine", default="optimized", choices=["optimized", "reference"])
    parser.add_argument("--batch-frequency", default="monthly", choices=["monthly"])
    parser.add_argument("--resume", action="store_true", help="Skip a batch when metadata and compatibility proof already exist.")
    return parser.parse_args()


def yyyymmdd(value: str) -> str:
    return str(value).replace("-", "")


def month_windows(start: str, end: str) -> list[BatchWindow]:
    start_ts = pd.Timestamp(yyyymmdd(start))
    end_ts = pd.Timestamp(yyyymmdd(end))
    if start_ts > end_ts:
        raise SystemExit("BLOCK_OOS_REFRESH_BATCH_INVALID_WINDOW")
    windows: list[BatchWindow] = []
    cursor = start_ts
    while cursor <= end_ts:
        month_end = min(cursor + pd.offsets.MonthEnd(0), end_ts)
        windows.append(BatchWindow(cursor.strftime("%Y%m%d"), month_end.strftime("%Y%m%d")))
        cursor = month_end + pd.Timedelta(days=1)
    return windows


def expected_batch_paths(workspace: Path, source_report_id: str, window: BatchWindow) -> dict[str, Path]:
    out_dir = workspace / "runs" / source_report_id / "oos_refresh" / window.window_id
    return {
        "factor_values": out_dir / f"factor_values__{source_report_id}__oos_{window.window_id}.parquet",
        "metadata": out_dir / f"run_metadata__{source_report_id}__oos_{window.window_id}.json",
        "compatibility": out_dir / f"factor_library_append_compatibility__{source_report_id}__oos_{window.window_id}.json",
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_universe(value: Any) -> Any:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text or text == "a_share_all":
        return "a_share_all"
    if "," in text:
        return [item.strip() for item in text.split(",") if item.strip()]
    return text


def resume_identity_mismatches(args: argparse.Namespace, window: BatchWindow, metadata: dict[str, Any]) -> list[str]:
    input_data = metadata.get("input_data") if isinstance(metadata.get("input_data"), dict) else {}
    identity = metadata.get("step4_formal_factor_identity") if isinstance(metadata.get("step4_formal_factor_identity"), dict) else {}
    expected = {
        "source_report_id": args.source_report_id,
        "factor_id": args.factor_id,
        "formula": args.formula,
        "dataset_id": args.dataset_id,
        "target_start": window.start,
        "target_end": window.end,
        "universe_request": parse_universe(args.universe),
    }
    observed = {
        "source_report_id": metadata.get("source_report_id") or identity.get("source_report_id"),
        "factor_id": metadata.get("factor_id") or identity.get("factor_id"),
        "formula": metadata.get("formula"),
        "dataset_id": input_data.get("dataset_id") or identity.get("dataset_id"),
        "target_start": str(input_data.get("target_start") or ""),
        "target_end": str(input_data.get("target_end") or ""),
        "universe_request": identity.get("universe_request"),
    }
    if args.history_start:
        expected["history_start"] = yyyymmdd(args.history_start)
        observed["history_start"] = str(input_data.get("history_start") or "")
    if args.expected_formula_hash:
        expected["expected_formula_hash"] = args.expected_formula_hash
        observed["expected_formula_hash"] = metadata.get("expected_formula_hash")
    mismatches = []
    for key, expected_value in expected.items():
        if observed.get(key) != expected_value:
            mismatches.append(key)
    return mismatches


def run_batch(args: argparse.Namespace, window: BatchWindow) -> dict[str, Any]:
    paths = expected_batch_paths(args.workspace, args.source_report_id, window)
    if args.resume and paths["metadata"].exists() and paths["compatibility"].exists() and paths["factor_values"].exists():
        metadata = read_json(paths["metadata"])
        compatibility = read_json(paths["compatibility"])
        if metadata.get("status") == "success" and compatibility.get("verdict") == "ACCEPT":
            mismatches = resume_identity_mismatches(args, window, metadata)
            if mismatches:
                return {
                    "window": {"start": window.start, "end": window.end},
                    "status": "failed",
                    "blocked_reason": "BLOCK_OOS_REFRESH_BATCH_RESUME_IDENTITY_MISMATCH",
                    "mismatched_fields": mismatches,
                    "factor_values_path": str(paths["factor_values"]),
                    "metadata_path": str(paths["metadata"]),
                    "compatibility_path": str(paths["compatibility"]),
                }
            return {
                "window": {"start": window.start, "end": window.end},
                "status": "reused_existing_batch",
                "factor_values_path": str(paths["factor_values"]),
                "metadata_path": str(paths["metadata"]),
                "compatibility_path": str(paths["compatibility"]),
                "row_count": metadata.get("output", {}).get("row_count"),
                "date_count": metadata.get("output", {}).get("date_count"),
                "ticker_count": metadata.get("output", {}).get("ticker_count"),
                "non_null_coverage": metadata.get("output", {}).get("factor_non_null_coverage"),
            }
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_alpha101_operator_oos_refresh.py"),
        "--workspace",
        str(args.workspace),
        "--source-report-id",
        args.source_report_id,
        "--factor-id",
        args.factor_id,
        "--formula",
        args.formula,
        "--target-start",
        window.start,
        "--target-end",
        window.end,
        "--dataset-id",
        args.dataset_id,
        "--universe",
        args.universe,
        "--engine",
        args.engine,
    ]
    if args.catalog_path:
        cmd.extend(["--catalog-path", args.catalog_path])
    if args.history_start:
        cmd.extend(["--history-start", args.history_start])
    if args.expected_formula_hash:
        cmd.extend(["--expected-formula-hash", args.expected_formula_hash])
    started = time.perf_counter()
    completed = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=os.environ.copy(), check=False)
    if completed.returncode != 0:
        return {
            "window": {"start": window.start, "end": window.end},
            "status": "failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "wall_seconds": time.perf_counter() - started,
        }
    payload = json.loads(completed.stdout)
    payload.update(
        {
            "window": {"start": window.start, "end": window.end},
            "status": "completed",
            "wall_seconds": time.perf_counter() - started,
        }
    )
    return payload


def main() -> int:
    args = parse_args()
    args.workspace = args.workspace.expanduser()
    windows = month_windows(args.target_start, args.target_end)
    batch_root = args.workspace / "runs" / args.source_report_id / "oos_refresh_batch" / f"{yyyymmdd(args.target_start)}_{yyyymmdd(args.target_end)}"
    batch_root.mkdir(parents=True, exist_ok=True)
    manifest_path = batch_root / f"batch_manifest__{args.source_report_id}__oos_{yyyymmdd(args.target_start)}_{yyyymmdd(args.target_end)}.json"
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    for window in windows:
        result = run_batch(args, window)
        results.append(result)
        manifest = build_manifest(args, windows, results, started)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if result.get("status") == "failed":
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
            return 1
    manifest = build_manifest(args, windows, results, started)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["verdict"] == "ACCEPT" else 1


def build_manifest(args: argparse.Namespace, windows: list[BatchWindow], results: list[dict[str, Any]], started: float) -> dict[str, Any]:
    failed = [item for item in results if item.get("status") == "failed"]
    completed = [item for item in results if item.get("status") in {"completed", "reused_existing_batch"}]
    row_count = sum(int(item.get("row_count") or 0) for item in completed)
    date_count = sum(int(item.get("date_count") or 0) for item in completed)
    data_cache = os.environ.get("FACTORFORGE_DATA_CACHE")
    return {
        "version": "factorforge_alpha101_operator_oos_refresh_batch_v1",
        "verdict": "ACCEPT" if not failed and len(completed) == len(windows) else "BLOCK",
        "source_report_id": args.source_report_id,
        "factor_id": args.factor_id,
        "formula": args.formula,
        "window": {"start": yyyymmdd(args.target_start), "end": yyyymmdd(args.target_end)},
        "batch_frequency": args.batch_frequency,
        "batch_count": len(windows),
        "completed_batch_count": len(completed),
        "failed_batch_count": len(failed),
        "row_count": row_count,
        "date_count_sum": date_count,
        "batch_execution_plan": {
            "version": "factorforge_batch_execution_plan_v1",
            "memory_budget": {
                "mode": "bounded_monthly_subprocess",
                "peak_memory_estimate": "bounded_by_single_month_source_slice_plus_formula_intermediates",
                "no_cross_batch_dataframe_accumulation": True,
            },
            "partition_key": "calendar_month",
            "batch_frequency": args.batch_frequency,
            "selected_columns": "derived_from_formula_ir_and_dataset_contract",
            "predicate_pushdown_policy": {
                "dataset_id": args.dataset_id,
                "target_window_per_batch": True,
                "history_start": args.history_start,
                "universe": args.universe,
            },
            "rolling_or_lookback_policy": {
                "history_start_applied_to_each_batch": bool(args.history_start),
                "formula_lookback_overlap": "delegated_to_single_window_refresh_history_start",
                "cross_batch_state_carried": False,
            },
            "output_format": "parquet_factor_values_plus_json_metadata",
            "checkpoint_resume_path": str(
                args.workspace
                / "runs"
                / args.source_report_id
                / "oos_refresh_batch"
                / f"{yyyymmdd(args.target_start)}_{yyyymmdd(args.target_end)}"
            ),
            "cache_identity": {
                "factorforge_data_cache": data_cache,
                "catalog_path": args.catalog_path or "factorforge_data_api_default_catalog",
            },
            "validation_sample_policy": "run_alpha101_operator_oos_refresh_batch_smoke.py",
        },
        "refresh_policy": {
            "revision_fitting_allowed": False,
            "same_report_id_parent_factor_parquet_overwrite": False,
            "checkpoint_resume_supported": True,
            "append_outputs_are_batch_partitioned": True,
        },
        "results": results,
        "wall_seconds": time.perf_counter() - started,
    }


if __name__ == "__main__":
    raise SystemExit(main())
