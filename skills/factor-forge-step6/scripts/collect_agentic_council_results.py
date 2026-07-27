#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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
COLLECTION_VERSION = "factorforge_agentic_council_result_collection_v1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    rid = args.report_id
    council_dir = OBJ / "research_iteration_master" / "revision_council" / rid
    manifest_path = council_dir / f"dispatch_manifest__{rid}.json"
    if not manifest_path.exists():
        print("BLOCK_AGENTIC_COUNCIL_DISPATCH_MANIFEST_MISSING: " + json.dumps({"report_id": rid, "manifest_path": str(manifest_path)}, ensure_ascii=False), file=sys.stderr)
        return 1
    manifest = load_json(manifest_path)
    required_tasks = [task for task in manifest.get("agent_tasks") or [] if isinstance(task, dict) and task.get("required") is True]
    valid_results: list[dict[str, Any]] = []
    invalid_results: list[dict[str, Any]] = []
    missing_results: list[dict[str, Any]] = []
    for task in required_tasks:
        task_id = task.get("task_id")
        path = resolve(task.get("expected_result_path"))
        if not path.exists():
            missing_results.append({"task_id": task_id, "expected_result_path": str(path)})
            continue
        try:
            payload = load_json(path)
            reasons = validate_agentic_result(
                payload,
                expected_task=task,
                expected_report_id=rid,
            )
        except Exception as exc:
            reasons = [f"agentic_result_unreadable:{exc}"]
            payload = {}
        entry = {
            "task_id": task_id,
            "agent_role": task.get("agent_role"),
            "result_path": str(path),
            "producer": payload.get("producer"),
            "agent_identifier": payload.get("agent_identifier"),
            "status": payload.get("status"),
        }
        if reasons:
            entry["block_reasons"] = reasons
            invalid_results.append(entry)
        else:
            valid_results.append(entry)
    blind_identifiers = [
        str(entry.get("agent_identifier"))
        for entry in valid_results
        if next(
            (
                task.get("blind_phase")
                for task in required_tasks
                if task.get("task_id") == entry.get("task_id")
            ),
            False,
        )
        and entry.get("agent_identifier")
    ]
    independence_block_reasons: list[str] = []
    if len(blind_identifiers) >= 2 and len(set(blind_identifiers)) != len(
        blind_identifiers
    ):
        independence_block_reasons.append(
            "BLOCK_COUNCIL_BLIND_ROUTES_SHARE_AGENT_IDENTITY"
        )
    ready = (
        not missing_results
        and not invalid_results
        and not independence_block_reasons
        and len(valid_results) == len(required_tasks)
    )
    status = (
        "complete"
        if ready
        else ("blocked" if invalid_results or independence_block_reasons else "partial")
    )
    collection = {
        "collection_version": COLLECTION_VERSION,
        "report_id": rid,
        "status": status,
        "required_result_count": len(required_tasks),
        "present_result_count": len(valid_results) + len(invalid_results),
        "valid_result_count": len(valid_results),
        "invalid_result_count": len(invalid_results),
        "missing_result_count": len(missing_results),
        "valid_results": valid_results,
        "invalid_results": invalid_results,
        "missing_results": missing_results,
        "independence_block_reasons": independence_block_reasons,
        "ready_for_finalize": ready,
        "created_at_utc": utc_now(),
    }
    out = council_dir / f"agentic_result_collection__{rid}.json"
    write_json(out, collection)
    print(json.dumps({"status": "written", "collection_path": str(out), "ready_for_finalize": ready, "report": collection}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
