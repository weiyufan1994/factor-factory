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

from factor_factory.revision_council.collection import (
    COLLECTION_VERSION,
    load_json,
    sha256_file,
    validate_collection,
)

OBJ = FF / "objects"

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
        reasons = validate_collection(rid, collection, workspace_root=FF)
    except Exception as exc:
        reasons = [f"BLOCK_AGENTIC_COUNCIL_COLLECTION_UNREADABLE:{exc}"]
    ok = not reasons
    print(json.dumps({"report_id": rid, "result": "PASS" if ok else "BLOCK", "collection_path": str(path), "block_reasons": reasons}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
