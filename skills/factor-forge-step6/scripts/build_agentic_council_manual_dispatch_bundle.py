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

OBJ = FF / "objects"
DISPATCH_VERSION = "factorforge_agentic_council_dispatch_manifest_v1"
MANUAL_VERSION = "factorforge_agentic_manual_dispatch_manifest_v1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(FF))
    except ValueError:
        return str(path)


def resolve(path: str | None) -> Path:
    if not isinstance(path, str) or not path:
        return FF / "__missing__"
    candidate = Path(path)
    return candidate if candidate.is_absolute() else FF / candidate


def block(token: str, payload: dict[str, Any]) -> None:
    print(token + ": " + json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)


def runtime_policy_markdown(policy: dict[str, Any]) -> str:
    runtime = policy.get("runtime")
    override_lines: list[str] = []
    provider_override = policy.get("manual_provider_override")
    model_override = policy.get("model_override")
    if isinstance(provider_override, dict) and provider_override.get("provider"):
        override_lines.append(f"- Explicit provider override: {provider_override.get('provider')} (reason: explicit_user_request)")
    if isinstance(model_override, dict) and model_override.get("model"):
        override_lines.append(f"- Explicit model override: {model_override.get('model')} (reason: explicit_user_request)")
    overrides = "\n".join(override_lines) if override_lines else "- No provider/model override was requested."
    if runtime == "codex":
        body = """Runtime dispatch policy: Codex.

The main Codex agent may spawn Codex subagents for this task.
Subagents inherit the current Codex model by default.
Do not choose or invoke external LLM providers.
Only use a model override if the user explicitly requested it.
The subagent must write only the expected result JSON."""
    elif runtime == "openclaw":
        body = """Runtime dispatch policy: OpenClaw.

The main OpenClaw agent may spawn OpenClaw subagents for this task.
Subagents inherit the main agent provider/model by default.
Provider/model override is allowed only when the user explicitly requested it.
Factor Forge does not require any specific provider.
The subagent must write only the expected result JSON."""
    elif runtime == "manual_file":
        body = """Runtime dispatch policy: manual_file.

This assignment is file-based.
A human or main agent may give this markdown to any qualified research agent.
The result is accepted only if the returned JSON passes Factor Forge validators.
Provider/model identity is not sufficient for acceptance."""
    else:
        body = """Runtime dispatch policy: unknown.

Factor Forge does not require any specific provider.
The result is accepted only if the returned JSON passes Factor Forge validators.
Provider/model identity is not sufficient for acceptance."""
    return body + "\n\nExplicit Runtime Overrides:\n" + overrides


def assignment_markdown(report_id: str, task: dict[str, Any], packet: dict[str, Any], expected_result_path: str) -> str:
    required_outputs = "\n".join(f"- {item}" for item in packet.get("required_outputs") or [])
    allowed_tools = "\n".join(f"- {item}" for item in packet.get("allowed_tools") or [])
    forbidden_changes = "\n".join(f"- {item}" for item in packet.get("forbidden_changes") or [])
    forbidden_writes = "\n".join(f"- {item}" for item in packet.get("forbidden_write_targets") or [])
    runtime_policy = runtime_policy_markdown(packet.get("runtime_dispatch_policy") or {})
    return f"""# Factor Forge Agentic Council Assignment

Report ID: {report_id}
Task ID: {task.get("task_id")}
Agent Role: {task.get("agent_role")}
Research Question: {packet.get("research_question")}
Expected Result Path: {expected_result_path}
Allowed Write Scope: {packet.get("write_scope")}

Runtime Dispatch Policy:
{runtime_policy}

Forbidden Writes:
{forbidden_writes}

Required Output Sections:
{required_outputs}

Allowed Mathematical / Research Tools:
{allowed_tools}

Forbidden Revision Shortcuts:
{forbidden_changes}

Result Contract:
- result_version: factorforge_agentic_revision_council_result_v1
- status: final
- producer: real_agent
- agent_identifier: nonempty
- research_depth: medium or high
- proposal_generation_mode: agentic
- canonical_write_permission: false
- execution_allowed_by_default: false
- human_approval_required: true

No Hidden Chain-of-Thought Requirement:
Do not provide hidden chain-of-thought. Provide only a public derivation record suitable for audit.

Public Derivation Record Requirement:
Provide assumptions, mathematical objects, selected tools with why_selected, formula claims, derivation summary, limiting cases, falsification tests, kill criteria, and an overclaim guard.

Do not edit Step3B handoff.
Do not edit generated_code.
Do not edit factor_library_official.
Do not edit data/clean.
Do not propose portfolio/rebalance/short-leg/long-short/decile-trading repair.
Write only the result JSON.
"""


def dropbox_template(report_id: str, task: dict[str, Any], expected_result_path: str) -> dict[str, Any]:
    return {
        "result_version": "factorforge_agentic_revision_council_result_v1",
        "status": "draft",
        "report_id": report_id,
        "task_id": task.get("task_id"),
        "agent_role": task.get("agent_role"),
        "producer": "real_agent",
        "agent_identifier": "",
        "research_depth": "medium",
        "proposal_generation_mode": "agentic",
        "expected_result_path": expected_result_path,
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "public_derivation_record": {
            "assumptions": [],
            "mathematical_objects": [],
            "selected_tools": [],
            "formula_claims": [],
            "derivation_steps_summary": [],
            "limiting_cases": [],
            "falsification_tests": [],
            "kill_criteria": [],
            "overclaim_guard": "",
        },
        "candidate_revision_laws": [],
        "recommended_branch_templates": [],
        "blocked_reason": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    rid = args.report_id
    council_dir = OBJ / "research_iteration_master" / "revision_council" / rid
    dispatch_path = council_dir / f"dispatch_manifest__{rid}.json"
    if not dispatch_path.exists():
        block("BLOCK_AGENTIC_COUNCIL_DISPATCH_MANIFEST_MISSING", {"report_id": rid, "dispatch_manifest_path": str(dispatch_path)})
    dispatch = load_json(dispatch_path)
    if dispatch.get("dispatch_manifest_version") != DISPATCH_VERSION or dispatch.get("report_id") != rid:
        block("BLOCK_AGENTIC_COUNCIL_DISPATCH_MANIFEST_INVALID", {"report_id": rid, "dispatch_manifest_path": str(dispatch_path)})
    runtime_dispatch_policy = dispatch.get("runtime_dispatch_policy")
    if not isinstance(runtime_dispatch_policy, dict):
        runtime_dispatch_policy = {}

    manual_dir = council_dir / "manual_dispatch"
    assignments: list[dict[str, Any]] = []
    for task in dispatch.get("agent_tasks") or []:
        if not isinstance(task, dict):
            continue
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            continue
        packet_path = resolve(task.get("task_packet_path"))
        if not packet_path.exists():
            block("BLOCK_AGENTIC_COUNCIL_DISPATCH_TASK_PACKET_MISSING", {"report_id": rid, "task_id": task_id, "task_packet_path": str(packet_path)})
        packet = load_json(packet_path)
        expected_result_path = task.get("expected_result_path")
        assignment_path = manual_dir / f"assignment__{rid}__{task_id}.md"
        dropbox_path = manual_dir / f"result_dropbox__{rid}__{task_id}.json"
        write_text(assignment_path, assignment_markdown(rid, task, packet, str(expected_result_path)))
        write_json(dropbox_path, dropbox_template(rid, task, str(expected_result_path)))
        assignments.append(
            {
                "task_id": task_id,
                "agent_role": task.get("agent_role"),
                "assignment_markdown_path": relpath(assignment_path),
                "result_dropbox_path": relpath(dropbox_path),
                "expected_result_path": expected_result_path,
                "status": "awaiting_result",
            }
        )

    manifest = {
        "manual_dispatch_manifest_version": MANUAL_VERSION,
        "report_id": rid,
        "factor_id": dispatch.get("factor_id") or rid,
        "created_at_utc": utc_now(),
        "source_dispatch_manifest_path": relpath(dispatch_path),
        "adapter": "manual_file",
        "status": "awaiting_manual_results",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "runtime_dispatch_policy": runtime_dispatch_policy,
        "agent_count": len(assignments),
        "assignments": assignments,
    }
    out = manual_dir / f"manual_dispatch_manifest__{rid}.json"
    write_json(out, manifest)
    print(json.dumps({"status": "written", "report_id": rid, "manual_dispatch_manifest_path": str(out), "agent_count": len(assignments)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
