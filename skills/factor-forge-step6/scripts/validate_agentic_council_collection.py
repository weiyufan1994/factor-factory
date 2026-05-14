#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path("/home/ubuntu/.openclaw/workspace")
FF = Path(os.getenv("FACTORFORGE_ROOT") or (LEGACY_WORKSPACE / "factorforge" if (LEGACY_WORKSPACE / "factorforge").exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OBJ = FF / "objects"
COLLECTION_VERSION = "factorforge_agentic_council_result_collection_v1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_collection(report_id: str, collection: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if collection.get("collection_version") != COLLECTION_VERSION or collection.get("report_id") != report_id:
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INVALID")
    if collection.get("canonical_write_permission") is True:
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_CANONICAL_WRITE_PERMISSION")
    if collection.get("execution_allowed_by_default") is True:
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_EXECUTION_ALLOWED_BY_DEFAULT")
    required = collection.get("required_result_count")
    present = collection.get("present_result_count")
    valid = collection.get("valid_result_count")
    invalid = collection.get("invalid_result_count")
    missing = collection.get("missing_result_count")
    if not isinstance(required, int) or required <= 0:
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INCOMPLETE")
    if missing != 0 or present != required:
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INCOMPLETE")
    if invalid != 0 or valid != required:
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INVALID_RESULTS")
    if collection.get("ready_for_finalize") is not True or collection.get("status") != "complete":
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_NOT_READY")
    for item in collection.get("valid_results") or []:
        if not isinstance(item, dict):
            reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INVALID_RESULTS")
            continue
        if item.get("status") != "final":
            reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INVALID_RESULTS")
        path = item.get("result_path")
        if not isinstance(path, str) or not Path(path).exists():
            reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INVALID_RESULTS")
    return sorted(set(reasons), key=reasons.index)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    rid = args.report_id
    path = OBJ / "research_iteration_master" / "revision_council" / rid / f"agentic_result_collection__{rid}.json"
    if not path.exists():
        result = {"report_id": rid, "result": "BLOCK", "block_reasons": ["BLOCK_AGENTIC_COUNCIL_COLLECTION_MISSING"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    try:
        collection = load_json(path)
        reasons = validate_collection(rid, collection)
    except Exception as exc:
        reasons = [f"BLOCK_AGENTIC_COUNCIL_COLLECTION_UNREADABLE:{exc}"]
    ok = not reasons
    print(json.dumps({"report_id": rid, "result": "PASS" if ok else "BLOCK", "collection_path": str(path), "block_reasons": reasons}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
