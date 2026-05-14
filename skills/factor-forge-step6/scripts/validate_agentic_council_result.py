#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path("/home/ubuntu/.openclaw/workspace")
FF = Path(os.getenv("FACTORFORGE_ROOT") or (LEGACY_WORKSPACE / "factorforge" if (LEGACY_WORKSPACE / "factorforge").exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OBJ = FF / "objects"
RESULT_VERSION = "factorforge_agentic_revision_council_result_v1"
FORBIDDEN_TOKEN = "BLOCK_REVISION_COUNCIL_AGENTIC_FORBIDDEN_TEXT"

FORBIDDEN_PATTERNS = [
    "portfolio",
    "rebalance",
    "short leg",
    "short-leg",
    "short_side",
    "short side",
    "long-short",
    "long short",
    "decile trading",
    "buy decile",
    "sell decile",
    "shared clean data",
    "clean data mutation",
    "mutate clean data",
]

SKIP_FORBIDDEN_KEYS = {
    "report_id",
    "task_id",
    "agent_role",
    "why_not_portfolio_fix",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def nonempty_list(value: Any, min_count: int = 1) -> bool:
    return isinstance(value, list) and len(value) >= min_count


def nonempty_str_list(value: Any, min_count: int = 2) -> bool:
    return isinstance(value, list) and len([item for item in value if nonempty_str(item)]) >= min_count and all(isinstance(item, str) for item in value)


def nonempty_object_list(value: Any, min_count: int = 1) -> bool:
    return isinstance(value, list) and len(value) >= min_count and all(isinstance(item, dict) for item in value)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def scan_forbidden(data: Any, path: str = "$") -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key in SKIP_FORBIDDEN_KEYS:
                continue
            findings.extend(scan_forbidden(value, f"{path}.{key}"))
    elif isinstance(data, list):
        for idx, value in enumerate(data):
            findings.extend(scan_forbidden(value, f"{path}[{idx}]"))
    elif isinstance(data, str):
        text = norm(data)
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in text:
                findings.append({"path": path, "pattern": pattern})
    return findings


def validate_agentic_result(result: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not isinstance(result, dict):
        return ["agentic_result_not_object"]
    if result.get("result_version") != RESULT_VERSION:
        reasons.append("agentic_result_version_invalid")
    if result.get("status") != "final":
        reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_RESULT_NOT_FINAL")
    for field in ["report_id", "task_id", "agent_role", "producer", "research_depth", "proposal_generation_mode"]:
        if not nonempty_str(result.get(field)):
            reasons.append(f"agentic_result_missing_field:{field}")
    if result.get("canonical_write_permission") is True:
        reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_CANONICAL_WRITE_PERMISSION")
    if result.get("execution_allowed_by_default") is True:
        reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_EXECUTION_ALLOWED_BY_DEFAULT")
    if result.get("human_approval_required") is not True:
        reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_HUMAN_APPROVAL_REQUIRED")
    producer = result.get("producer")
    depth = result.get("research_depth")
    mode = result.get("proposal_generation_mode")
    if producer == "local_mock_agentic_contract":
        if depth not in {"low", "medium"}:
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_LOCAL_MOCK_DEPTH_INVALID")
        if mode != "agentic_contract_mock":
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_LOCAL_MOCK_MODE_INVALID")
    elif producer == "real_agent":
        if not nonempty_str(result.get("agent_identifier")):
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_REAL_AGENT_IDENTIFIER_MISSING")
        if depth not in {"medium", "high"}:
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_REAL_AGENT_DEPTH_INVALID")
        if mode != "agentic":
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_REAL_AGENT_MODE_INVALID")
    else:
        reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_PRODUCER_INVALID")

    record = result.get("public_derivation_record")
    if not isinstance(record, dict) or not record:
        reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_DERIVATION_MISSING")
    else:
        if not nonempty_object_list(record.get("assumptions")):
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_ASSUMPTIONS_MISSING")
        if not nonempty_object_list(record.get("mathematical_objects")):
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_OBJECTS_MISSING")
        tools = record.get("selected_tools")
        if not nonempty_object_list(tools):
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_TOOLS_MISSING")
        else:
            for idx, item in enumerate(tools):
                if not nonempty_str(item.get("tool")) or not nonempty_str(item.get("why_selected")):
                    reasons.append(f"BLOCK_REVISION_COUNCIL_AGENTIC_TOOL_INVALID:{idx}")
        claims = record.get("formula_claims")
        if not nonempty_object_list(claims):
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_FORMULA_CLAIMS_MISSING")
        else:
            for idx, item in enumerate(claims):
                if not nonempty_str(item.get("claim")) or not nonempty_str(item.get("formula_or_relation")):
                    reasons.append(f"BLOCK_REVISION_COUNCIL_AGENTIC_FORMULA_CLAIM_INVALID:{idx}")
        if not nonempty_list(record.get("derivation_steps_summary")):
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_DERIVATION_STEPS_MISSING")
        if not nonempty_str_list(record.get("falsification_tests"), min_count=2):
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_FALSIFICATION_TESTS_MISSING")
        if not nonempty_str_list(record.get("kill_criteria"), min_count=2):
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_KILL_CRITERIA_MISSING")
        if not nonempty_str(record.get("overclaim_guard")):
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_OVERCLAIM_GUARD_MISSING")

    laws = result.get("candidate_revision_laws")
    if not nonempty_object_list(laws):
        reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_REVISION_LAWS_MISSING")
    else:
        for idx, law in enumerate(laws):
            if not nonempty_str(law.get("law_id")) or not nonempty_str(law.get("law_statement")):
                reasons.append(f"BLOCK_REVISION_COUNCIL_AGENTIC_LAW_INVALID:{idx}")
            if not nonempty_str_list(law.get("expected_metric_change"), min_count=2):
                reasons.append(f"BLOCK_REVISION_COUNCIL_AGENTIC_EXPECTED_METRIC_CHANGE_MISSING:{idx}")
            if not nonempty_str_list(law.get("falsification_tests"), min_count=2):
                reasons.append(f"BLOCK_REVISION_COUNCIL_AGENTIC_LAW_FALSIFICATION_MISSING:{idx}")
            if not nonempty_str_list(law.get("kill_criteria"), min_count=2):
                reasons.append(f"BLOCK_REVISION_COUNCIL_AGENTIC_LAW_KILL_CRITERIA_MISSING:{idx}")
            if not nonempty_str(law.get("why_not_portfolio_fix")):
                reasons.append(f"BLOCK_REVISION_COUNCIL_AGENTIC_WHY_NOT_PORTFOLIO_FIX_MISSING:{idx}")

    forbidden = scan_forbidden(result)
    if forbidden:
        reasons.append(FORBIDDEN_TOKEN + ":" + ",".join(f"{item['path']}={item['pattern']}" for item in forbidden))
    return reasons


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
            reasons = validate_agentic_result(payload)
        except Exception as exc:
            reasons = [f"agentic_result_unreadable:{exc}"]
        results.append({"path": str(path), "status": "BLOCK" if reasons else "PASS", "block_reasons": reasons})
    ok = all(item["status"] == "PASS" for item in results)
    print(json.dumps({"report_id": args.report_id, "result": "PASS" if ok else "BLOCK", "results": results}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
