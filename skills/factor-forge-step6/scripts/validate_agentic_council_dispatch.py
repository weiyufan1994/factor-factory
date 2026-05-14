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
MANIFEST_VERSION = "factorforge_agentic_council_dispatch_manifest_v1"
TASK_PACKET_VERSION = "factorforge_agentic_council_task_packet_v1"
RUNTIME_POLICY_VERSION = "factorforge_runtime_dispatch_policy_v1"
RUNTIME_VALUES = {"codex", "openclaw", "manual_file", "unknown"}
REQUIRED_OUTPUTS = {
    "public_derivation_record",
    "candidate_revision_laws",
    "falsification_tests",
    "kill_criteria",
    "overclaim_guard",
}
REQUIRED_FORBIDDEN_TARGET_SUFFIXES = {
    "objects/handoff/handoff_to_step3b__{report_id}.json",
    "generated_code/{report_id}/",
    "objects/factor_library_official/factor_record__{report_id}.json",
    "data/clean/",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(path: str | None) -> Path:
    if not isinstance(path, str) or not path:
        return FF / "__missing__"
    candidate = Path(path)
    return candidate if candidate.is_absolute() else FF / candidate


def nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def expected_forbidden_targets(report_id: str) -> set[str]:
    return {item.format(report_id=report_id) for item in REQUIRED_FORBIDDEN_TARGET_SUFFIXES}


def validate_runtime_policy(policy: Any, prefix: str) -> list[str]:
    reasons: list[str] = []
    if not isinstance(policy, dict):
        return [f"{prefix}_RUNTIME_POLICY_MISSING"]
    if policy.get("policy_version") != RUNTIME_POLICY_VERSION:
        reasons.append(f"{prefix}_RUNTIME_POLICY_INVALID")
    if policy.get("runtime") not in RUNTIME_VALUES:
        reasons.append(f"{prefix}_RUNTIME_INVALID")
    if policy.get("subagent_dispatcher") != "main_agent":
        reasons.append(f"{prefix}_RUNTIME_DISPATCHER_INVALID")
    if policy.get("default_model_policy") != "inherit_main_model":
        reasons.append(f"{prefix}_DEFAULT_MODEL_POLICY_INVALID")
    if policy.get("provider_override_policy") != "only_if_user_explicitly_requests":
        reasons.append(f"{prefix}_PROVIDER_OVERRIDE_POLICY_INVALID")
    if policy.get("provider_required_by_factor_forge") is not False:
        reasons.append(f"{prefix}_PROVIDER_REQUIRED_BY_FACTOR_FORGE")
    provider_override = policy.get("manual_provider_override")
    model_override = policy.get("model_override")
    if policy.get("external_provider_selection_allowed") is True and not isinstance(provider_override, dict):
        reasons.append(f"{prefix}_EXTERNAL_PROVIDER_SELECTION_WITHOUT_OVERRIDE")
    for key, override in (("MANUAL_PROVIDER_OVERRIDE", provider_override), ("MODEL_OVERRIDE", model_override)):
        if override is None:
            continue
        if not isinstance(override, dict) or override.get("reason") != "explicit_user_request":
            reasons.append(f"{prefix}_{key}_REASON_INVALID")
    return reasons


def validate_manifest(report_id: str, manifest: dict[str, Any], manifest_path: Path) -> list[str]:
    reasons: list[str] = []
    if manifest.get("dispatch_manifest_version") != MANIFEST_VERSION:
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_VERSION_INVALID")
    if manifest.get("report_id") != report_id:
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_REPORT_ID_MISMATCH")
    if manifest.get("canonical_write_permission") is True:
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_CANONICAL_WRITE_PERMISSION")
    if manifest.get("execution_allowed_by_default") is True:
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_EXECUTION_ALLOWED_BY_DEFAULT")
    if manifest.get("human_approval_required") is not True:
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_HUMAN_APPROVAL_REQUIRED")
    manifest_policy = manifest.get("runtime_dispatch_policy")
    reasons.extend(validate_runtime_policy(manifest_policy, "BLOCK_AGENTIC_COUNCIL_DISPATCH"))
    targets = set(manifest.get("forbidden_write_targets") or [])
    if not expected_forbidden_targets(report_id).issubset(targets):
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_FORBIDDEN_TARGETS_MISSING")
    tasks = manifest.get("agent_tasks")
    if not isinstance(tasks, list) or not tasks:
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_TASKS_MISSING")
        return reasons
    if manifest.get("agent_task_count") != len(tasks):
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_COUNT_MISMATCH")
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            reasons.append(f"BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_INVALID:{idx}")
            continue
        packet_path = resolve(task.get("task_packet_path"))
        if not packet_path.exists():
            reasons.append(f"BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_PACKET_MISSING:{idx}")
            continue
        try:
            packet = load_json(packet_path)
        except Exception as exc:
            reasons.append(f"BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_PACKET_UNREADABLE:{idx}:{exc}")
            continue
        reasons.extend(validate_task_packet(report_id, task, packet, packet_path, idx, manifest_policy))
    return reasons


def validate_task_packet(report_id: str, manifest_task: dict[str, Any], packet: dict[str, Any], packet_path: Path, idx: int, manifest_policy: Any) -> list[str]:
    reasons: list[str] = []
    if packet.get("task_packet_version") != TASK_PACKET_VERSION:
        reasons.append(f"BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_PACKET_VERSION_INVALID:{idx}")
    if packet.get("report_id") != report_id or manifest_task.get("task_id") != packet.get("task_id"):
        reasons.append(f"BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_PACKET_REPORT_ID_MISMATCH:{idx}")
    if packet.get("canonical_write_permission") is True:
        reasons.append(f"BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_CANONICAL_WRITE_PERMISSION:{idx}")
    if packet.get("execution_allowed_by_default") is True:
        reasons.append(f"BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_EXECUTION_ALLOWED_BY_DEFAULT:{idx}")
    if packet.get("human_approval_required") is not True:
        reasons.append(f"BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_HUMAN_APPROVAL_REQUIRED:{idx}")
    packet_policy = packet.get("runtime_dispatch_policy")
    reasons.extend(validate_runtime_policy(packet_policy, "BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK"))
    if isinstance(manifest_policy, dict) and isinstance(packet_policy, dict) and packet_policy != manifest_policy:
        reasons.append(f"BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_RUNTIME_POLICY_MISMATCH:{idx}")
    task_id = packet.get("task_id")
    expected_result = resolve(packet.get("expected_result_path"))
    agent_results_root = FF / "objects" / "research_iteration_master" / "revision_council" / report_id / "agent_results"
    if not within(expected_result, agent_results_root) or expected_result.name != f"agent_result__{report_id}__{task_id}.json":
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_RESULT_PATH_OUTSIDE_SCOPE")
    write_scope = resolve(packet.get("write_scope"))
    if not within(write_scope, agent_results_root) or write_scope.resolve() != agent_results_root.resolve():
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_WRITE_SCOPE_OUTSIDE_SCOPE")
    if manifest_task.get("expected_result_path") != packet.get("expected_result_path"):
        reasons.append(f"BLOCK_AGENTIC_COUNCIL_DISPATCH_EXPECTED_RESULT_MISMATCH:{idx}")
    required_outputs = set(packet.get("required_outputs") or [])
    if not REQUIRED_OUTPUTS.issubset(required_outputs):
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_REQUIRED_OUTPUTS_MISSING")
    if not nonempty_list(packet.get("allowed_tools")) or not all(nonempty_str(item) for item in packet.get("allowed_tools") or []):
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_ALLOWED_TOOLS_MISSING")
    if not nonempty_list(packet.get("forbidden_changes")) or not all(nonempty_str(item) for item in packet.get("forbidden_changes") or []):
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_FORBIDDEN_CHANGES_MISSING")
    targets = set(packet.get("forbidden_write_targets") or [])
    if not expected_forbidden_targets(report_id).issubset(targets):
        reasons.append("BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_FORBIDDEN_TARGETS_MISSING")
    contract = packet.get("result_contract") or {}
    if contract.get("result_version") != "factorforge_agentic_revision_council_result_v1":
        reasons.append(f"BLOCK_AGENTIC_COUNCIL_DISPATCH_RESULT_CONTRACT_INVALID:{idx}")
    if "real_agent" not in (contract.get("producer_allowed") or []):
        reasons.append(f"BLOCK_AGENTIC_COUNCIL_DISPATCH_REAL_AGENT_NOT_ALLOWED:{idx}")
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    rid = args.report_id
    manifest_path = OBJ / "research_iteration_master" / "revision_council" / rid / f"dispatch_manifest__{rid}.json"
    if not manifest_path.exists():
        result = {"report_id": rid, "result": "BLOCK", "block_reasons": ["BLOCK_AGENTIC_COUNCIL_DISPATCH_MANIFEST_MISSING"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    try:
        manifest = load_json(manifest_path)
        reasons = validate_manifest(rid, manifest, manifest_path)
    except Exception as exc:
        reasons = [f"BLOCK_AGENTIC_COUNCIL_DISPATCH_UNREADABLE:{exc}"]
    ok = not reasons
    print(
        json.dumps(
            {
                "report_id": rid,
                "result": "PASS" if ok else "BLOCK",
                "manifest_path": str(manifest_path),
                "block_reasons": reasons,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
