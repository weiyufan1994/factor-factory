#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path("/home/ubuntu/.openclaw/workspace")
FF = Path(os.getenv("FACTORFORGE_ROOT") or (LEGACY_WORKSPACE / "factorforge" if (LEGACY_WORKSPACE / "factorforge").exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validate_agentic_council_result import validate_agentic_result

OBJ = FF / "objects"
MANUAL_VERSION = "factorforge_agentic_manual_dispatch_manifest_v1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve(path: str | None) -> Path:
    if not isinstance(path, str) or not path:
        return FF / "__missing__"
    candidate = Path(path)
    return candidate if candidate.is_absolute() else FF / candidate


def within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_payload(path: Path) -> list[str]:
    try:
        return validate_agentic_result(load_json(path))
    except Exception as exc:
        return [f"agentic_result_unreadable:{exc}"]


def run_status_update(report_id: str) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "skills/factor-forge-step6/scripts/update_agentic_council_dispatch_status.py", "--report-id", report_id],
        cwd=str(REPO_ROOT),
        env={**os.environ, "FACTORFORGE_ROOT": str(FF)},
        text=True,
        capture_output=True,
    )
    return {"rc": proc.returncode, "stdout_tail": proc.stdout[-4000:], "stderr_tail": proc.stderr[-4000:]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--overwrite-invalid", action="store_true")
    args = parser.parse_args()
    rid = args.report_id
    council_dir = OBJ / "research_iteration_master" / "revision_council" / rid
    manifest_path = council_dir / "manual_dispatch" / f"manual_dispatch_manifest__{rid}.json"
    if not manifest_path.exists():
        print("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_MANIFEST_MISSING: " + json.dumps({"report_id": rid, "manual_dispatch_manifest_path": str(manifest_path)}, ensure_ascii=False), file=sys.stderr)
        return 1
    manifest = load_json(manifest_path)
    if manifest.get("manual_dispatch_manifest_version") != MANUAL_VERSION or manifest.get("report_id") != rid:
        print("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_INVALID", file=sys.stderr)
        return 1
    manual_root = manifest_path.parent
    agent_results_root = council_dir / "agent_results"
    imported: list[dict[str, Any]] = []
    awaiting: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    assignments = [item for item in manifest.get("assignments") or [] if isinstance(item, dict)]
    if args.task_id:
        assignments = [item for item in assignments if item.get("task_id") == args.task_id]
    for item in assignments:
        task_id = item.get("task_id")
        dropbox_path = resolve(item.get("result_dropbox_path"))
        expected_path = resolve(item.get("expected_result_path"))
        if not within(dropbox_path, manual_root) or not within(expected_path, agent_results_root):
            blocked.append({"task_id": task_id, "reason": "path_outside_scope", "dropbox_path": str(dropbox_path), "expected_result_path": str(expected_path)})
            continue
        if not dropbox_path.exists():
            awaiting.append({"task_id": task_id, "reason": "dropbox_missing", "result_dropbox_path": str(dropbox_path)})
            continue
        payload = load_json(dropbox_path)
        if payload.get("status") == "draft":
            awaiting.append({"task_id": task_id, "reason": "draft", "result_dropbox_path": str(dropbox_path)})
            continue
        if payload.get("status") != "final":
            invalid.append({"task_id": task_id, "reason": "not_final", "result_dropbox_path": str(dropbox_path)})
            continue
        reasons = validate_agentic_result(payload)
        if reasons:
            invalid.append({"task_id": task_id, "result_dropbox_path": str(dropbox_path), "block_reasons": reasons})
            continue
        if expected_path.exists():
            existing_reasons = validate_payload(expected_path)
            if not existing_reasons:
                skipped.append({"task_id": task_id, "reason": "existing_valid_result_not_overwritten", "expected_result_path": str(expected_path)})
                continue
            if not args.overwrite_invalid:
                skipped.append({"task_id": task_id, "reason": "existing_invalid_result_requires_overwrite_invalid", "expected_result_path": str(expected_path), "existing_block_reasons": existing_reasons})
                continue
        expected_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dropbox_path, expected_path)
        imported.append({"task_id": task_id, "expected_result_path": str(expected_path)})
    status_update = run_status_update(rid)
    report = {
        "manual_import_version": "factorforge_agentic_manual_result_import_v1",
        "report_id": rid,
        "created_at_utc": utc_now(),
        "source_manual_dispatch_manifest_path": str(manifest_path),
        "imported_count": len(imported),
        "awaiting_count": len(awaiting),
        "invalid_count": len(invalid),
        "skipped_count": len(skipped),
        "blocked_count": len(blocked),
        "imported": imported,
        "awaiting": awaiting,
        "invalid": invalid,
        "skipped": skipped,
        "blocked": blocked,
        "status_update": status_update,
    }
    out = manual_root / f"manual_result_import__{rid}.json"
    write_json(out, report)
    print(json.dumps({"status": "written", "manual_result_import_path": str(out), "report": report}, ensure_ascii=False, indent=2))
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
