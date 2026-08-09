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
STATUS_VERSION = "factorforge_agentic_dispatch_status_v1"


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    rid = args.report_id
    council_dir = OBJ / "research_iteration_master" / "revision_council" / rid
    dispatch_path = council_dir / f"dispatch_manifest__{rid}.json"
    manual_path = council_dir / "manual_dispatch" / f"manual_dispatch_manifest__{rid}.json"
    if not dispatch_path.exists():
        print("BLOCK_AGENTIC_COUNCIL_DISPATCH_MANIFEST_MISSING: " + json.dumps({"report_id": rid, "dispatch_manifest_path": str(dispatch_path)}, ensure_ascii=False), file=sys.stderr)
        return 1
    dispatch = load_json(dispatch_path)
    tasks: list[dict[str, Any]] = []
    valid_count = 0
    invalid_count = 0
    missing_count = 0
    for item in dispatch.get("agent_tasks") or []:
        if not isinstance(item, dict):
            continue
        path = resolve(item.get("expected_result_path"))
        entry = {
            "task_id": item.get("task_id"),
            "agent_role": item.get("agent_role"),
            "status": "awaiting_result",
            "expected_result_path": str(path),
            "result_exists": path.exists(),
            "validation_rc": None,
            "validation_token": None,
        }
        if not path.exists():
            missing_count += 1
        else:
            try:
                reasons = validate_agentic_result(
                    load_json(path),
                    expected_task=item,
                    expected_report_id=rid,
                )
            except Exception as exc:
                reasons = [f"agentic_result_unreadable:{exc}"]
            if reasons:
                invalid_count += 1
                entry["status"] = "received_invalid"
                entry["validation_rc"] = 1
                entry["validation_token"] = reasons[0]
            else:
                valid_count += 1
                entry["status"] = "received_valid"
                entry["validation_rc"] = 0
        tasks.append(entry)
    ready = bool(tasks) and valid_count == len(tasks) and invalid_count == 0 and missing_count == 0
    status = "complete" if ready else ("blocked" if invalid_count else ("partial" if valid_count else "awaiting_results"))
    ledger = {
        "dispatch_status_version": STATUS_VERSION,
        "report_id": rid,
        "created_at_utc": utc_now(),
        "source_dispatch_manifest_path": str(dispatch_path),
        "source_manual_dispatch_manifest_path": str(manual_path) if manual_path.exists() else None,
        "status": status,
        "tasks": tasks,
        "ready_for_collection": ready,
    }
    out = council_dir / f"agentic_dispatch_status__{rid}.json"
    write_json(out, ledger)
    print(json.dumps({"status": "written", "status_ledger_path": str(out), "ready_for_collection": ready, "ledger": ledger}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
