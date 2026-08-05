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
RESEARCH_PROTOCOL_VERSION = "factorforge_research_conjecture_protocol_v1"
FORBIDDEN_TOKEN = "BLOCK_REVISION_COUNCIL_AGENTIC_FORBIDDEN_TEXT"
TERMINAL_RECOMMENDATION_VALUES = {
    "reject",
    "kill",
    "stop",
    "terminal_reject",
    "no_revision",
    "no_derived_revision",
}

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


def nonempty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def nonempty_limiting_cases(value: Any, min_count: int = 2) -> bool:
    if not isinstance(value, list) or len(value) < min_count:
        return False
    polarities: set[str] = set()
    valid_count = 0
    for item in value:
        if isinstance(item, dict):
            text = item.get("case") or item.get("statement") or item.get("description")
            polarity = str(item.get("polarity") or item.get("case_type") or "").strip().lower()
            if not nonempty_str(text):
                return False
            if polarity in {"positive", "negative"}:
                polarities.add(polarity)
            valid_count += 1
        elif isinstance(item, str) and item.strip():
            valid_count += 1
        else:
            return False
    if polarities:
        return valid_count >= min_count and {"positive", "negative"}.issubset(polarities)
    return valid_count >= min_count


def terminal_recommendation_requested(result: dict[str, Any]) -> bool:
    rec = result.get("revision_or_kill_recommendation")
    if not isinstance(rec, dict) or not isinstance(rec.get("recommendation"), str):
        return False
    return str(rec["recommendation"]).strip().lower() in TERMINAL_RECOMMENDATION_VALUES


def terminal_control_fields(result: dict[str, Any]) -> dict[str, Any]:
    rec = result.get("revision_or_kill_recommendation")
    control = result.get("terminal_control")
    merged: dict[str, Any] = {}
    if isinstance(rec, dict):
        for key in ("terminal_scope", "stop_authority", "terminal_proof", "proof", "reason"):
            if key in rec:
                merged[key] = rec[key]
    if isinstance(control, dict):
        merged.update(control)
    return merged


def terminal_proof_present(control: dict[str, Any]) -> bool:
    proof = control.get("terminal_proof") or control.get("proof")
    return isinstance(proof, str) and bool(proof.strip()) or isinstance(proof, dict) and bool(proof)


def protocol_task(report_id: str, task_id: Any) -> dict[str, Any]:
    if not isinstance(task_id, str) or not task_id:
        return {}
    path = (
        OBJ
        / "research_iteration_master"
        / "revision_council"
        / report_id
        / f"agentic_taskbook__{report_id}.json"
    )
    if not path.exists():
        return {}
    try:
        taskbook = load_json(path)
    except Exception:
        return {}
    if taskbook.get("research_protocol_version") != RESEARCH_PROTOCOL_VERSION:
        return {}
    for task in taskbook.get("agent_tasks") or []:
        if isinstance(task, dict) and task.get("task_id") == task_id:
            return task
    return {}


def resolve_under_root(raw_path: Any) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        return FF / "__missing__"
    path = Path(raw_path)
    return path if path.is_absolute() else FF / path


def expected_manifest_task(report_id: str, result_path: Path) -> dict[str, Any]:
    path = (
        OBJ
        / "research_iteration_master"
        / "revision_council"
        / report_id
        / f"dispatch_manifest__{report_id}.json"
    )
    if not path.exists():
        return {}
    manifest = load_json(path)
    resolved_result = result_path.resolve(strict=False)
    for task in manifest.get("agent_tasks") or []:
        if not isinstance(task, dict):
            continue
        expected = resolve_under_root(task.get("expected_result_path"))
        if expected.resolve(strict=False) == resolved_result:
            return task
    return {}


def validate_dispatch_identity(
    result: dict[str, Any],
    expected: dict[str, Any],
    *,
    report_id: str,
) -> list[str]:
    reasons: list[str] = []
    if not expected:
        return ["BLOCK_COUNCIL_RESULT_NOT_BOUND_TO_DISPATCH_TASK"]
    for field, expected_value in (
        ("report_id", report_id),
        ("task_id", expected.get("task_id")),
        ("agent_role", expected.get("agent_role")),
        ("agent_identifier", expected.get("expected_agent_identifier")),
    ):
        if expected_value is not None and result.get(field) != expected_value:
            reasons.append(f"BLOCK_COUNCIL_RESULT_DISPATCH_IDENTITY_MISMATCH:{field}")
    route = result.get("approach_route")
    route = route if isinstance(route, dict) else {}
    for field in ("route_id", "route_family"):
        if route.get(field) != expected.get(field):
            reasons.append(f"BLOCK_COUNCIL_RESULT_DISPATCH_IDENTITY_MISMATCH:{field}")
    binding = result.get("dispatch_identity")
    if not isinstance(binding, dict):
        reasons.append("BLOCK_COUNCIL_RESULT_DISPATCH_BINDING_MISSING")
        binding = {}
    for field, expected_value in (
        ("source_task_packet_sha256", expected.get("task_packet_sha256")),
        ("route_fingerprint", expected.get("route_fingerprint")),
        ("blind_context_hash", expected.get("blind_context_hash")),
    ):
        if binding.get(field) != expected_value:
            reasons.append(f"BLOCK_COUNCIL_RESULT_DISPATCH_BINDING_MISMATCH:{field}")
    return reasons


def validate_research_protocol_result(
    result: dict[str, Any],
    task: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    route = result.get("approach_route")
    if not nonempty_dict(route):
        reasons.append("BLOCK_COUNCIL_RESEARCH_ROUTE_MISSING")
        route = {}
    if route.get("route_id") != task.get("route_id"):
        reasons.append("BLOCK_COUNCIL_RESEARCH_ROUTE_ID_MISMATCH")
    if route.get("route_family") != task.get("route_family"):
        reasons.append("BLOCK_COUNCIL_RESEARCH_ROUTE_FAMILY_MISMATCH")
    for field in (
        "core_hypothesis",
        "distinct_from_other_routes",
        "exact_gap_after_analysis",
    ):
        if not nonempty_str(route.get(field)):
            reasons.append(f"BLOCK_COUNCIL_RESEARCH_ROUTE_UNDERSPECIFIED:{field}")

    updates = result.get("proof_obligation_updates")
    if not nonempty_object_list(updates):
        reasons.append("BLOCK_COUNCIL_PROOF_OBLIGATION_UPDATES_MISSING")
        updates = []
    expected_ids = set(task.get("proof_obligation_ids") or [])
    actual_ids = {
        str(item.get("obligation_id"))
        for item in updates
        if isinstance(item, dict) and item.get("obligation_id")
    }
    if expected_ids and not expected_ids.issubset(actual_ids):
        reasons.append(
            "BLOCK_COUNCIL_PROOF_OBLIGATION_COVERAGE_MISSING:"
            + ",".join(sorted(expected_ids - actual_ids))
        )
    for idx, item in enumerate(updates):
        if not isinstance(item, dict):
            continue
        if item.get("status") not in {
            "open",
            "blocked",
            "failed",
            "passed",
            "not_applicable",
        }:
            reasons.append(f"BLOCK_COUNCIL_PROOF_OBLIGATION_STATUS_INVALID:{idx}")
        if not nonempty_str(item.get("finding")):
            reasons.append(f"BLOCK_COUNCIL_PROOF_OBLIGATION_FINDING_MISSING:{idx}")
        if item.get("status") == "passed" and not nonempty_list(item.get("evidence_refs")):
            reasons.append(f"BLOCK_COUNCIL_PROOF_OBLIGATION_EVIDENCE_MISSING:{idx}")

    counterexamples = result.get("counterexamples")
    if not nonempty_object_list(counterexamples):
        reasons.append("BLOCK_COUNCIL_COUNTEREXAMPLE_SEARCH_MISSING")
    else:
        for idx, item in enumerate(counterexamples):
            for field in (
                "attack_type",
                "construction_or_scenario",
                "predicted_failure",
                "discriminating_test",
            ):
                if not nonempty_str(item.get(field)):
                    reasons.append(f"BLOCK_COUNCIL_COUNTEREXAMPLE_INVALID:{idx}:{field}")

    route_status = result.get("route_status")
    if route_status not in {
        "open",
        "active",
        "blocked",
        "falsified",
        "supported",
        "inconclusive",
        "closed",
    }:
        reasons.append("BLOCK_COUNCIL_RESEARCH_ROUTE_STATUS_INVALID")
    if route_status in {"blocked", "falsified"} and not nonempty_str_list(
        result.get("reopen_criteria"),
        min_count=1,
    ):
        reasons.append("BLOCK_COUNCIL_RESEARCH_ROUTE_REOPEN_CRITERIA_MISSING")

    attestation = result.get("independence_attestation")
    if not nonempty_dict(attestation):
        reasons.append("BLOCK_COUNCIL_INDEPENDENCE_ATTESTATION_MISSING")
    else:
        blind = task.get("blind_context_policy")
        blind = blind if isinstance(blind, dict) else {}
        if blind.get("blind_phase") is True:
            if attestation.get("favored_thesis_seen_before_submission") is not False:
                reasons.append("BLOCK_COUNCIL_BLIND_INDEPENDENCE_VIOLATED")
            if attestation.get("derived_from_visible_facts_only") is not True:
                reasons.append("BLOCK_COUNCIL_BLIND_INDEPENDENCE_ATTESTATION_INVALID")
    return reasons


def validate_real_agent_derivation_contract(result: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    econ = result.get("economic_hypothesis_review")
    math = result.get("math_mechanism_derivation")
    translation = result.get("model_to_formula_translation")
    if not nonempty_dict(econ) or not nonempty_dict(math):
        reasons.append("BLOCK_COUNCIL_VERDICT_WITHOUT_DERIVATION")
        return reasons
    for field in ("refined_second_layer_mechanism", "payer_or_counterparty_update", "what_step4_metrics_changed_in_the_hypothesis"):
        if not nonempty_str(econ.get(field)):
            reasons.append(f"BLOCK_COUNCIL_VERDICT_WITHOUT_DERIVATION:{field}")
    if not isinstance(econ.get("preserve_broad_direction"), bool):
        reasons.append("BLOCK_COUNCIL_VERDICT_WITHOUT_DERIVATION:preserve_broad_direction")

    selected_tool = math.get("selected_tool")
    selected_tool_rationale = math.get("selected_tool_rationale") or math.get("why_selected")
    if not nonempty_str(selected_tool) or not nonempty_str(selected_tool_rationale):
        reasons.append("BLOCK_COUNCIL_NO_TOOL_SELECTION_RATIONALE")
    for field in ("baseline_model", "model_mutation"):
        if not nonempty_str(math.get(field)):
            reasons.append(f"BLOCK_COUNCIL_VERDICT_WITHOUT_DERIVATION:{field}")
    for field in ("mathematical_objects", "derivation_steps", "derived_state_variables", "observable_estimators", "expected_metric_signature", "falsification_tests"):
        if not nonempty_list(math.get(field)):
            reasons.append(f"BLOCK_COUNCIL_VERDICT_WITHOUT_DERIVATION:{field}")

    if not nonempty_dict(translation):
        reasons.append("BLOCK_COUNCIL_NO_MODEL_TO_FORMULA_MAPPING")
    else:
        candidate = translation.get("candidate_formula")
        disposition = translation.get("disposition") or translation.get("terminal_disposition")
        if not nonempty_str(candidate) and disposition not in {"research_hold", "operator_block", "no_derived_revision_with_proof"}:
            reasons.append("BLOCK_COUNCIL_NO_MODEL_TO_FORMULA_MAPPING")
        for field in ("operator_support_status", "information_set_legality"):
            if not nonempty_str(translation.get(field)):
                reasons.append(f"BLOCK_COUNCIL_NO_MODEL_TO_FORMULA_MAPPING:{field}")
        if not nonempty_list(translation.get("mapping_from_model_terms_to_formula_components")):
            reasons.append("BLOCK_COUNCIL_NO_MODEL_TO_FORMULA_MAPPING:mapping_from_model_terms_to_formula_components")

    prior = result.get("prior_revision_outcome_review")
    prior_text = json.dumps(prior, ensure_ascii=False).lower() if isinstance(prior, dict) else ""
    prior_parameter_failed = "parameter_repair" in prior_text and ("falsified" in prior_text or "failed" in prior_text)
    if prior_parameter_failed:
        for law in result.get("candidate_revision_laws") or []:
            if not isinstance(law, dict):
                continue
            if law.get("revision_kind") == "parameter_repair":
                diagnosis = law.get("prior_revision_model_diagnosis") or result.get("prior_revision_model_diagnosis")
                if not nonempty_dict(diagnosis):
                    reasons.append("BLOCK_COUNCIL_PARAMETER_REPAIR_AFTER_PARAMETER_FAILURE_WITHOUT_MODEL_DIAGNOSIS")
    if terminal_recommendation_requested(result):
        control = terminal_control_fields(result)
        rec = result.get("revision_or_kill_recommendation") if isinstance(result.get("revision_or_kill_recommendation"), dict) else {}
        scope = control.get("terminal_scope") or rec.get("terminal_scope")
        if scope not in {"revision_branch_only", "factor_instance", "mechanism_family"}:
            reasons.append("BLOCK_COUNCIL_VERDICT_WITHOUT_DERIVATION:terminal_scope")
        authority = str(control.get("stop_authority") or "").strip()
        has_proof = terminal_proof_present(control)
        if scope == "revision_branch_only":
            if authority and authority not in {"advisory_only", "branch_falsification_only"}:
                reasons.append("BLOCK_COUNCIL_TERMINAL_AUTHORITY_INVALID")
        elif scope in {"factor_instance", "mechanism_family"}:
            allowed = {"human_override", "evidence_block", "block_with_proof", "validated_no_derived_revision", "max_loop_cap"}
            if authority not in allowed or not has_proof:
                reasons.append("BLOCK_COUNCIL_TERMINAL_AUTHORITY_MISSING")
    return reasons


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


def validate_agentic_result(
    result: dict[str, Any],
    *,
    expected_task: dict[str, Any] | None = None,
    expected_report_id: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(result, dict):
        return ["agentic_result_not_object"]
    if expected_task is not None or expected_report_id is not None:
        reasons.extend(
            validate_dispatch_identity(
                result,
                expected_task or {},
                report_id=str(expected_report_id or result.get("report_id") or ""),
            )
        )
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
        reasons.extend(validate_real_agent_derivation_contract(result))
        task_report_id = str(expected_report_id or result.get("report_id") or "")
        task_id = (
            (expected_task or {}).get("task_id")
            if expected_task is not None
            else result.get("task_id")
        )
        task = protocol_task(task_report_id, task_id)
        if task:
            reasons.extend(validate_research_protocol_result(result, task))
        elif (expected_task or {}).get("route_id"):
            reasons.append("BLOCK_COUNCIL_RESEARCH_PROTOCOL_TASK_BINDING_MISSING")
    else:
        reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_PRODUCER_INVALID")

    record = result.get("public_derivation_record")
    if not isinstance(record, dict) or not record:
        reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_DERIVATION_MISSING")
    else:
        if not nonempty_str(record.get("research_question")):
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_RESEARCH_QUESTION_MISSING")
        if not nonempty_limiting_cases(record.get("limiting_cases"), min_count=2):
            reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_LIMITING_CASES_MISSING")
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
            expected = expected_manifest_task(args.report_id, path)
            reasons = validate_agentic_result(
                payload,
                expected_task=expected,
                expected_report_id=args.report_id,
            )
        except Exception as exc:
            reasons = [f"agentic_result_unreadable:{exc}"]
        results.append({"path": str(path), "status": "BLOCK" if reasons else "PASS", "block_reasons": reasons})
    ok = all(item["status"] == "PASS" for item in results)
    print(json.dumps({"report_id": args.report_id, "result": "PASS" if ok else "BLOCK", "results": results}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
