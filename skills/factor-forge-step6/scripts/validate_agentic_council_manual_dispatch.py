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
MANUAL_VERSION = "factorforge_agentic_manual_dispatch_manifest_v1"
DISPATCH_VERSION = "factorforge_agentic_council_dispatch_manifest_v1"
RUNTIME_POLICY_VERSION = "factorforge_runtime_dispatch_policy_v1"
RUNTIME_VALUES = {"codex", "openclaw", "manual_file", "unknown"}
REQUIRED_MARKDOWN_PHRASES = [
    "Do not edit Step3B handoff.",
    "Do not edit generated_code.",
    "Do not edit factor_library_official.",
    "Do not edit data/clean.",
    "Write only the result JSON.",
    "Expected Result Path:",
    "Public Derivation Record Requirement:",
]
RUNTIME_MARKDOWN_PHRASES = {
    "codex": [
        "Runtime dispatch policy: Codex.",
        "Subagents inherit the current Codex model by default.",
        "Do not choose or invoke external LLM providers.",
    ],
    "openclaw": [
        "Runtime dispatch policy: OpenClaw.",
        "Subagents inherit the main agent provider/model by default.",
        "Factor Forge does not require any specific provider.",
    ],
    "manual_file": [
        "Runtime dispatch policy: manual_file.",
        "Provider/model identity is not sufficient for acceptance.",
    ],
    "unknown": [
        "Runtime dispatch policy: unknown.",
        "Provider/model identity is not sufficient for acceptance.",
    ],
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def load_dispatch_policy(manifest: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]], list[str]]:
    reasons: list[str] = []
    dispatch_path = resolve(manifest.get("source_dispatch_manifest_path"))
    if not dispatch_path.exists():
        return None, {}, ["BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_SOURCE_DISPATCH_MISSING"]
    dispatch = load_json(dispatch_path)
    if dispatch.get("dispatch_manifest_version") != DISPATCH_VERSION:
        reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_SOURCE_DISPATCH_INVALID")
    dispatch_policy = dispatch.get("runtime_dispatch_policy")
    task_packets: dict[str, dict[str, Any]] = {}
    for task in dispatch.get("agent_tasks") or []:
        if not isinstance(task, dict):
            continue
        task_id = task.get("task_id")
        packet_path = resolve(task.get("task_packet_path"))
        if isinstance(task_id, str) and packet_path.exists():
            task_packets[task_id] = load_json(packet_path)
    return dispatch_policy if isinstance(dispatch_policy, dict) else None, task_packets, reasons


def validate_manifest(report_id: str, manifest: dict[str, Any], manifest_path: Path) -> list[str]:
    reasons: list[str] = []
    manual_root = manifest_path.parent
    agent_results_root = OBJ / "research_iteration_master" / "revision_council" / report_id / "agent_results"
    if manifest.get("manual_dispatch_manifest_version") != MANUAL_VERSION or manifest.get("report_id") != report_id:
        reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_INVALID")
    if manifest.get("adapter") != "manual_file":
        reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_ADAPTER_INVALID")
    if manifest.get("canonical_write_permission") is True:
        reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_CANONICAL_WRITE_PERMISSION")
    if manifest.get("execution_allowed_by_default") is True:
        reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_EXECUTION_ALLOWED_BY_DEFAULT")
    if manifest.get("human_approval_required") is not True:
        reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_HUMAN_APPROVAL_REQUIRED")
    manifest_policy = manifest.get("runtime_dispatch_policy")
    reasons.extend(validate_runtime_policy(manifest_policy, "BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH"))
    dispatch_policy, task_packets, dispatch_reasons = load_dispatch_policy(manifest)
    reasons.extend(dispatch_reasons)
    if isinstance(manifest_policy, dict) and isinstance(dispatch_policy, dict) and manifest_policy != dispatch_policy:
        reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_RUNTIME_POLICY_MISMATCH")
    assignments = manifest.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_ASSIGNMENTS_MISSING")
        return reasons
    if manifest.get("agent_count") != len(assignments):
        reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_AGENT_COUNT_MISMATCH")
    for idx, item in enumerate(assignments):
        if not isinstance(item, dict):
            reasons.append(f"BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_ASSIGNMENT_INVALID:{idx}")
            continue
        task_id = item.get("task_id")
        assignment_path = resolve(item.get("assignment_markdown_path"))
        dropbox_path = resolve(item.get("result_dropbox_path"))
        expected_path = resolve(item.get("expected_result_path"))
        if not within(dropbox_path, manual_root) or dropbox_path.name != f"result_dropbox__{report_id}__{task_id}.json":
            reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_DROPBOX_PATH_OUTSIDE_SCOPE")
        if not within(expected_path, agent_results_root) or expected_path.name != f"agent_result__{report_id}__{task_id}.json":
            reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_EXPECTED_RESULT_OUTSIDE_SCOPE")
        if not assignment_path.exists():
            reasons.append(f"BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_ASSIGNMENT_MISSING:{idx}")
        else:
            text = assignment_path.read_text(encoding="utf-8")
            if str(item.get("expected_result_path")) not in text:
                reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_EXPECTED_RESULT_NOT_IN_MARKDOWN")
            for phrase in REQUIRED_MARKDOWN_PHRASES:
                if phrase not in text:
                    reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_MARKDOWN_PROHIBITION_MISSING")
                    break
            runtime = manifest_policy.get("runtime") if isinstance(manifest_policy, dict) else None
            for phrase in RUNTIME_MARKDOWN_PHRASES.get(str(runtime), []):
                if phrase not in text:
                    reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_RUNTIME_TEXT_MISSING")
                    break
            if isinstance(manifest_policy, dict) and (manifest_policy.get("manual_provider_override") or manifest_policy.get("model_override")):
                if "Explicit Runtime Overrides:" not in text or "explicit_user_request" not in text:
                    reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_OVERRIDE_TEXT_MISSING")
        packet = task_packets.get(str(task_id))
        if isinstance(packet, dict):
            packet_policy = packet.get("runtime_dispatch_policy")
            reasons.extend(validate_runtime_policy(packet_policy, "BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_TASK"))
            if isinstance(manifest_policy, dict) and isinstance(packet_policy, dict) and packet_policy != manifest_policy:
                reasons.append("BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_TASK_RUNTIME_POLICY_MISMATCH")
        if not dropbox_path.exists():
            reasons.append(f"BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_DROPBOX_MISSING:{idx}")
        else:
            try:
                dropbox = load_json(dropbox_path)
            except Exception as exc:
                reasons.append(f"BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_DROPBOX_UNREADABLE:{idx}:{exc}")
                continue
            if dropbox.get("result_version") != "factorforge_agentic_revision_council_result_v1":
                reasons.append(f"BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_DROPBOX_INVALID:{idx}")
            if dropbox.get("canonical_write_permission") is True:
                reasons.append(f"BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_DROPBOX_CANONICAL_WRITE_PERMISSION:{idx}")
            if dropbox.get("execution_allowed_by_default") is True:
                reasons.append(f"BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_DROPBOX_EXECUTION_ALLOWED_BY_DEFAULT:{idx}")
    return sorted(set(reasons), key=reasons.index)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    rid = args.report_id
    path = OBJ / "research_iteration_master" / "revision_council" / rid / "manual_dispatch" / f"manual_dispatch_manifest__{rid}.json"
    if not path.exists():
        result = {"report_id": rid, "result": "BLOCK", "block_reasons": ["BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_MANIFEST_MISSING"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    try:
        manifest = load_json(path)
        reasons = validate_manifest(rid, manifest, path)
    except Exception as exc:
        reasons = [f"BLOCK_AGENTIC_COUNCIL_MANUAL_DISPATCH_UNREADABLE:{exc}"]
    ok = not reasons
    print(json.dumps({"report_id": rid, "result": "PASS" if ok else "BLOCK", "manual_dispatch_manifest_path": str(path), "block_reasons": reasons}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
