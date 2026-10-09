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

from factor_factory.revision_council.agentic_result import (
    RESULT_VERSION,
    RESEARCH_PROTOCOL_VERSION,
    FORBIDDEN_TOKEN,
    TERMINAL_RECOMMENDATION_VALUES,
    NO_REVISION_RECOMMENDATION_VALUES,
    FORBIDDEN_PATTERNS,
    SKIP_FORBIDDEN_KEYS,
    load_json,
    nonempty_str,
    nonempty_list,
    nonempty_str_list,
    nonempty_object_list,
    nonempty_dict,
    nonempty_limiting_cases,
    terminal_recommendation_requested,
    terminal_control_fields,
    terminal_proof_present,
    advisory_no_revision_reasons,
    protocol_task,
    resolve_under_root,
    expected_manifest_task,
    validate_dispatch_identity,
    validate_measurement_program_result_binding,
    validate_research_protocol_result,
    validate_real_agent_derivation_contract,
    norm,
    scan_forbidden,
    validate_agentic_result,
)

OBJ = FF / "objects"

def result_paths(report_id: str, result_path: str | None) -> list[Path]:
    if result_path:
        return [Path(result_path).expanduser()]
    return sorted((OBJ / "research_iteration_master" / "revision_council" / report_id / "agent_results").glob(f"agent_result__{report_id}__*.json"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--result-path", default=None)
    args = parser.parse_args()
    paths = result_paths(args.report_id, args.result_path)
    results = []
    if not paths:
        results.append({"path": None, "status": "BLOCK", "block_reasons": ["BLOCK_REVISION_COUNCIL_AGENTIC_RESULTS_MISSING"]})
    for path in paths:
        try:
            payload = load_json(path)
            expected = expected_manifest_task(args.report_id, path, workspace_root=FF)
            reasons = validate_agentic_result(
                payload,
                expected_task=expected,
                expected_report_id=args.report_id,
                workspace_root=FF,
            )
        except Exception as exc:
            reasons = [f"agentic_result_unreadable:{exc}"]
        results.append({"path": str(path), "status": "BLOCK" if reasons else "PASS", "block_reasons": reasons})
    ok = all(item["status"] == "PASS" for item in results)
    print(json.dumps({"report_id": args.report_id, "result": "PASS" if ok else "BLOCK", "results": results}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
