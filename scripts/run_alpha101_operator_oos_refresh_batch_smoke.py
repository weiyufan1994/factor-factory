#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    tmp_root = Path("/tmp/factorforge_alpha101_oos_refresh_batch_smoke")
    if tmp_root.exists():
        import shutil

        shutil.rmtree(tmp_root)
    workspace = tmp_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    catalog_path = ROOT / "data" / "catalog" / "data_catalog.json"
    if not catalog_path.exists():
        catalog_path = Path("/Users/humphrey/projects/factor-factory/data/catalog/data_catalog.json")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_alpha101_operator_oos_refresh_batch.py"),
        "--workspace",
        str(workspace),
        "--source-report-id",
        "SMOKE_ALPHA101_OOS_REFRESH_BATCH",
        "--factor-id",
        "SMOKE",
        "--formula",
        "rank(close)",
        "--target-start",
        "20250731",
        "--target-end",
        "20250801",
        "--history-start",
        "20250731",
        "--universe",
        "000001.SZ,000002.SZ",
        "--catalog-path",
        str(catalog_path),
        "--resume",
    ]
    env = dict(os.environ)
    env["FACTORFORGE_DATA_CACHE"] = str(tmp_root / "data_api_cache")
    first_completed = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=env, check=False)
    if first_completed.returncode != 0:
        print(first_completed.stdout)
        print(first_completed.stderr, file=sys.stderr)
        return first_completed.returncode
    first_manifest = json.loads(first_completed.stdout)

    second_completed = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=env, check=False)
    if second_completed.returncode != 0:
        print(second_completed.stdout)
        print(second_completed.stderr, file=sys.stderr)
        return second_completed.returncode
    second_manifest = json.loads(second_completed.stdout)
    second_statuses = [item.get("status") for item in second_manifest.get("results", [])]

    mismatch_cmd = list(cmd)
    mismatch_cmd[mismatch_cmd.index("--formula") + 1] = "rank(open)"
    mismatch_completed = subprocess.run(mismatch_cmd, cwd=ROOT, text=True, capture_output=True, env=env, check=False)
    mismatch_manifest = json.loads(mismatch_completed.stdout) if mismatch_completed.stdout.strip().startswith("{") else {}
    mismatch_reasons = [
        item.get("blocked_reason")
        for item in mismatch_manifest.get("results", [])
        if isinstance(item, dict) and item.get("blocked_reason")
    ]
    checks = {
        "first_run_verdict_accept": first_manifest.get("verdict") == "ACCEPT",
        "first_run_two_month_batches": first_manifest.get("batch_count") == 2,
        "first_run_all_batches_completed": first_manifest.get("completed_batch_count") == 2,
        "first_run_has_batch_execution_plan": first_manifest.get("batch_execution_plan", {}).get("version")
        == "factorforge_batch_execution_plan_v1",
        "first_run_checkpoint_resume_supported": first_manifest.get("refresh_policy", {}).get("checkpoint_resume_supported")
        is True,
        "first_run_row_count_positive": int(first_manifest.get("row_count") or 0) > 0,
        "first_run_no_failed_batches": first_manifest.get("failed_batch_count") == 0,
        "second_run_verdict_accept": second_manifest.get("verdict") == "ACCEPT",
        "second_run_reused_all_batches": second_statuses == ["reused_existing_batch", "reused_existing_batch"],
        "second_run_completed_all_batches": second_manifest.get("completed_batch_count") == second_manifest.get("batch_count") == 2,
        "second_run_no_failed_batches": second_manifest.get("failed_batch_count") == 0,
        "second_run_row_count_matches_first": second_manifest.get("row_count") == first_manifest.get("row_count"),
        "second_run_date_count_matches_first": second_manifest.get("date_count_sum") == first_manifest.get("date_count_sum"),
        "mismatch_run_blocks": mismatch_completed.returncode != 0,
        "mismatch_run_reports_identity_blocker": "BLOCK_OOS_REFRESH_BATCH_RESUME_IDENTITY_MISMATCH" in mismatch_reasons,
    }
    verdict = "ACCEPT" if all(checks.values()) else "BLOCK"
    print(
        json.dumps(
            {
                "verdict": verdict,
                "checks": checks,
                "first_manifest": first_manifest,
                "second_manifest": second_manifest,
                "mismatch_manifest": mismatch_manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if verdict == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
