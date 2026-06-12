#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access import default_clean_daily_layer_root, default_local_data_root
from factor_factory.data_access.mutation_guard import require_data_mutation_authority


DEFAULT_BUCKET = "yufan-data-lake"
DEFAULT_DAILY_INCREMENTAL_PREFIX = "tushares/行情数据/daily_incremental"
DEFAULT_DAILY_BASIC_PREFIX = "tushares/行情数据/daily_basic_incremental"
DEFAULT_S3_URI = "s3://yufan-data-lake/factorforge/datamart/clean_daily_bar/v1/daily_clean.parquet"
DEFAULT_FACTORFORGE_ROOT = Path(os.getenv("FACTORFORGE_ROOT", "/home/ubuntu/.openclaw/workspace/factorforge")).expanduser()
DEFAULT_RUN_ROOT = Path(os.getenv("FACTORFORGE_RUN_ROOT", "/home/ubuntu/.openclaw/workspace/runs")).expanduser()
DEFAULT_QLIB_PROVIDER_DIR = Path(os.getenv("QLIB_PROVIDER_URI") or (Path.home() / ".qlib" / "qlib_data" / "cn_data")).expanduser()
DEFAULT_QLIB_PROVIDER_ENV = Path(os.getenv("FACTORFORGE_QLIB_PROVIDER_ENV") or (Path.home() / ".factorforge" / "qlib_provider.env")).expanduser()
DEFAULT_QLIB_PROVIDER_S3_URI = "s3://yufan-data-lake/factorforge/datamart/qlib_data/cn_data/"
DEFAULT_WORKER_QLIB_PYTHON = Path("/home/ubuntu/miniconda3/envs/rdagent4qlib/bin/python")


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(cmd, cwd=REPO_ROOT, env=merged_env, text=True, capture_output=True, check=True)


def aws_text(args: list[str]) -> str:
    return run(["aws", *args]).stdout


def normalize_end_date(value: str) -> str:
    text = str(value).strip().replace("-", "")
    if text == "current":
        return datetime.now().strftime("%Y%m%d")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"expected YYYYMMDD end date, got {value!r}")
    return text


def s3_partition_dates(bucket: str, prefix: str, end_date: str) -> set[str]:
    raw = aws_text(["s3", "ls", f"s3://{bucket}/{prefix.rstrip('/')}/"])
    dates: set[str] = set()
    for line in raw.splitlines():
        if "trade_date=" not in line:
            continue
        part = line.split("trade_date=", 1)[1].split("/", 1)[0].strip()
        if len(part) == 8 and part.isdigit() and part <= end_date:
            dates.add(part)
    return dates


def latest_common_raw_date(args: argparse.Namespace) -> dict[str, Any]:
    end_date = normalize_end_date(args.end_date)
    daily_dates = s3_partition_dates(args.bucket, args.daily_incremental_prefix, end_date)
    daily_basic_dates = s3_partition_dates(args.bucket, args.daily_basic_prefix, end_date)
    common = sorted(daily_dates & daily_basic_dates)
    if not common:
        raise RuntimeError(
            "no common raw daily/daily_basic S3 partition found through "
            f"{end_date}: daily_count={len(daily_dates)} daily_basic_count={len(daily_basic_dates)}"
        )
    return {
        "requested_end_date": end_date,
        "effective_end_date": common[-1],
        "daily_last_trade_date": max(daily_dates) if daily_dates else None,
        "daily_basic_last_trade_date": max(daily_basic_dates) if daily_basic_dates else None,
    }


def read_json_from_stdout(proc: subprocess.CompletedProcess[str]) -> Any:
    text = proc.stdout.strip()
    if not text:
        return {}
    start = text.find("{")
    if start < 0:
        return {"stdout": text}
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return {"stdout": text}


def parquet_trade_date_max(path: Path) -> str | None:
    if not path.exists():
        return None
    frame = pd.read_parquet(path, columns=["trade_date"])
    if frame.empty:
        return None
    return str(frame["trade_date"].astype(str).str.replace(".0", "", regex=False).str.zfill(8).max())


def clean_meta_s3_uri(clean_s3_uri: str) -> str:
    if clean_s3_uri.endswith(".parquet"):
        return clean_s3_uri[:-len(".parquet")] + ".meta.json"
    return clean_s3_uri.rstrip("/") + ".meta.json"


def restore_clean_layer_from_s3_if_missing(args: argparse.Namespace) -> dict[str, Any]:
    clean_parquet = args.clean_dir / "daily_clean.parquet"
    clean_meta = args.clean_dir / "daily_clean.meta.json"
    if clean_parquet.exists() and clean_meta.exists():
        return {
            "skipped": True,
            "reason": "local_clean_layer_present",
            "clean_parquet": str(clean_parquet),
            "clean_meta": str(clean_meta),
        }

    args.clean_dir.mkdir(parents=True, exist_ok=True)
    parquet_proc = run(["aws", "s3", "cp", args.s3_uri, str(clean_parquet), "--only-show-errors"])
    meta_uri = clean_meta_s3_uri(args.s3_uri)
    meta_proc = run(["aws", "s3", "cp", meta_uri, str(clean_meta), "--only-show-errors"])
    return {
        "skipped": False,
        "reason": "local_clean_layer_missing",
        "source_parquet_uri": args.s3_uri,
        "source_meta_uri": meta_uri,
        "clean_parquet": str(clean_parquet),
        "clean_meta": str(clean_meta),
        "parquet_stdout_tail": parquet_proc.stdout[-1000:],
        "meta_stdout_tail": meta_proc.stdout[-1000:],
    }


def resolve_publisher_script() -> Path:
    candidates = [
        REPO_ROOT / "scripts" / "factorforge_data_api.py",
        REPO_ROOT.parent / "factor-factory-data-api" / "scripts" / "factorforge_data_api.py",
        Path("/home/ubuntu/.openclaw/workspace/factorforge/scripts/factorforge_data_api.py"),
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("factorforge_data_api.py not found; cannot publish clean_daily_bar catalog entry")


def publish_qlib_provider(args: argparse.Namespace, effective_end_date: str, env: dict[str, str]) -> dict[str, Any]:
    provider_dir = args.qlib_provider_dir.expanduser()
    qlib_python = args.qlib_provider_python.expanduser()
    python_executable = str(qlib_python) if qlib_python.exists() else sys.executable
    cmd = [
        python_executable,
        "scripts/publish_qlib_daily_provider.py",
        "--data-api",
        "--catalog-path",
        str(args.catalog),
        "--dataset-id",
        "clean_daily_bar",
        "--start-date",
        args.qlib_provider_start_date,
        "--end-date",
        effective_end_date,
        "--provider-dir",
        str(provider_dir),
        "--instrument-style",
        args.qlib_provider_instrument_style,
        "--raw-smoke",
        "--write-env-file",
        str(args.qlib_provider_env_file.expanduser()),
    ]
    if args.qlib_provider_qlib_smoke:
        cmd.append("--qlib-smoke")
    if args.qlib_provider_s3_uri:
        cmd.extend(["--sync-s3-uri", args.qlib_provider_s3_uri])
    proc = run(cmd, env={**env, "QLIB_PROVIDER_URI": str(provider_dir)})
    payload = read_json_from_stdout(proc)
    return {
        "skipped": False,
        "command": cmd,
        "provider_dir": str(provider_dir),
        "env_file": str(args.qlib_provider_env_file.expanduser()),
        "python_executable": python_executable,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-2000:],
        "publish_report": payload,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refresh and publish clean_daily_bar after daily_incremental and daily_basic_incremental are updated."
    )
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--daily-incremental-prefix", default=DEFAULT_DAILY_INCREMENTAL_PREFIX)
    parser.add_argument("--daily-basic-prefix", default=DEFAULT_DAILY_BASIC_PREFIX)
    parser.add_argument("--end-date", default="current")
    parser.add_argument("--local-root", type=Path, default=default_local_data_root())
    parser.add_argument("--clean-dir", type=Path, default=default_clean_daily_layer_root())
    parser.add_argument("--s3-uri", default=DEFAULT_S3_URI)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_FACTORFORGE_ROOT / "data" / "catalog" / "data_catalog.json")
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT / "clean-daily-bar-update")
    parser.add_argument("--operator", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--skip-core-sync", action="store_true", help="Do not sync daily.csv/adj_factor/core CSVs from S3 before refreshing.")
    parser.add_argument("--publish", action="store_true", help="Explicitly upload parquet/meta and upsert the catalog after refresh.")
    parser.add_argument("--skip-publish", action="store_true", help="Compatibility no-op; publish is skipped unless --publish is provided.")
    parser.add_argument("--skip-qlib-provider-publish", action="store_true", help="Do not publish the global Microsoft Qlib provider after clean_daily_bar refresh.")
    parser.add_argument("--qlib-provider-dir", type=Path, default=DEFAULT_QLIB_PROVIDER_DIR)
    parser.add_argument("--qlib-provider-env-file", type=Path, default=DEFAULT_QLIB_PROVIDER_ENV)
    parser.add_argument("--qlib-provider-s3-uri", default=DEFAULT_QLIB_PROVIDER_S3_URI)
    parser.add_argument("--qlib-provider-python", type=Path, default=Path(os.getenv("FACTORFORGE_QLIB_PROVIDER_PYTHON") or DEFAULT_WORKER_QLIB_PYTHON))
    parser.add_argument("--qlib-provider-start-date", default="20100104")
    parser.add_argument("--qlib-provider-instrument-style", default="legacy_qlib", choices=["ts_code", "tushare", "provider", "legacy_qlib", "qlib", "raw"])
    parser.add_argument("--qlib-provider-qlib-smoke", action="store_true", help="Also run Microsoft Qlib read smoke after publishing the provider.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    require_data_mutation_authority(args.operator, operation="update_clean_daily_bar_after_daily_update")
    args.local_root = args.local_root.expanduser()
    args.clean_dir = args.clean_dir.expanduser()
    args.catalog = args.catalog.expanduser()
    args.run_root = args.run_root.expanduser()
    args.qlib_provider_dir = args.qlib_provider_dir.expanduser()
    args.qlib_provider_env_file = args.qlib_provider_env_file.expanduser()
    args.run_root.mkdir(parents=True, exist_ok=True)
    if args.publish and args.skip_publish:
        raise SystemExit("BLOCK_CLEAN_DAILY_PUBLISH_CONFLICT: use either --publish or --skip-publish, not both")

    raw_state = latest_common_raw_date(args)
    effective_end_date = raw_state["effective_end_date"]
    env = {
        "FACTORFORGE_DATA_MUTATION_APPROVED": os.environ.get("FACTORFORGE_DATA_MUTATION_APPROVED", "codex-approved"),
        "FACTORFORGE_LOCAL_DATA_ROOT": str(args.local_root),
        "FACTORFORGE_CLEAN_DAILY_DIR": str(args.clean_dir),
        "FACTORFORGE_ROOT": str(args.catalog.parents[2]) if len(args.catalog.parents) >= 3 else str(DEFAULT_FACTORFORGE_ROOT),
    }

    summary: dict[str, Any] = {
        "status": "running",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_state": raw_state,
        "paths": {
            "local_root": str(args.local_root),
            "clean_dir": str(args.clean_dir),
            "catalog": str(args.catalog),
            "s3_uri": args.s3_uri,
            "qlib_provider_dir": str(args.qlib_provider_dir),
            "qlib_provider_env_file": str(args.qlib_provider_env_file),
        },
    }

    if args.skip_core_sync:
        summary["sync_core"] = {"skipped": True}
    else:
        proc = run(
            [
                sys.executable,
                "scripts/sync_tushare_raw_from_s3.py",
                "--local-root",
                str(args.local_root),
                "--operator",
                args.operator,
                "sync-core",
            ],
            env=env,
        )
        summary["sync_core"] = {
            "skipped": False,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-2000:],
        }

    summary["restore_clean_layer"] = restore_clean_layer_from_s3_if_missing(args)

    refresh_cmd = [
        sys.executable,
        "scripts/refresh_clean_daily_after_tushare_update.py",
        "--local-root",
        str(args.local_root),
        "--clean-dir",
        str(args.clean_dir),
        "--end-date",
        effective_end_date,
        "--operator",
        args.operator,
        "--sync-all-daily-basic-if-missing",
    ]
    if args.force:
        refresh_cmd.append("--force")
    if args.backup:
        refresh_cmd.append("--backup")
    proc = run(refresh_cmd, env=env)
    summary["refresh_clean_layer"] = read_json_from_stdout(proc)

    clean_parquet = args.clean_dir / "daily_clean.parquet"
    summary["after_refresh"] = {
        "clean_trade_date_max": parquet_trade_date_max(clean_parquet),
        "clean_size_mb": round(clean_parquet.stat().st_size / 1024**2, 1) if clean_parquet.exists() else None,
    }

    if not args.publish:
        summary["publish"] = {"skipped": True, "reason": "publish_requires_explicit_flag"}
    else:
        proc = run(
            [
                sys.executable,
                str(resolve_publisher_script()),
                "--catalog",
                str(args.catalog),
                "publish-clean-daily",
                "--s3-uri",
                args.s3_uri,
                "--description",
                "FactorForge point-in-time cleaned daily A-share bar layer with daily_basic enrichment.",
            ],
            env=env,
        )
        summary["publish"] = read_json_from_stdout(proc)

    if args.skip_qlib_provider_publish:
        summary["qlib_provider_publish"] = {"skipped": True, "reason": "skip_qlib_provider_publish"}
    else:
        summary["qlib_provider_publish"] = publish_qlib_provider(args, effective_end_date, env)

    final_max = summary["after_refresh"]["clean_trade_date_max"]
    summary["status"] = "ok" if final_max and final_max >= effective_end_date else "stale_after_refresh"
    latest_path = args.run_root / "latest.json"
    dated_path = args.run_root / f"clean_daily_bar_update_{effective_end_date}.json"
    latest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dated_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
