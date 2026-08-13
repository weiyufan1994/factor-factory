#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
TASKBOOK_VERSION = "factorforge_agentic_revision_council_taskbook_v1"
MANIFEST_VERSION = "factorforge_agentic_council_dispatch_manifest_v1"
TASK_PACKET_VERSION = "factorforge_agentic_council_task_packet_v1"
TOKEN_TASKBOOK_MISSING = "BLOCK_AGENTIC_COUNCIL_TASKBOOK_MISSING"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(FF))
    except ValueError:
        return str(path)


def block(token: str, payload: dict[str, Any]) -> None:
    print(token + ": " + json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    rid = args.report_id
    council_dir = OBJ / "research_iteration_master" / "revision_council" / rid
    taskbook_path = council_dir / f"agentic_taskbook__{rid}.json"
    if not taskbook_path.exists():
        block(TOKEN_TASKBOOK_MISSING, {"report_id": rid, "taskbook_path": str(taskbook_path)})
    taskbook = load_json(taskbook_path)
    if taskbook.get("taskbook_version") != TASKBOOK_VERSION or taskbook.get("report_id") != rid:
        block("BLOCK_AGENTIC_COUNCIL_TASKBOOK_INVALID", {"report_id": rid, "taskbook_path": str(taskbook_path)})

    task_dir = council_dir / "agent_tasks"
    result_dir = council_dir / "agent_results"
    forbidden_write_targets = [
        f"objects/handoff/handoff_to_step3b__{rid}.json",
        f"generated_code/{rid}/",
        f"objects/factor_library_official/factor_record__{rid}.json",
        "data/clean/",
    ]
    runtime_dispatch_policy = taskbook.get("runtime_dispatch_policy")
    if not isinstance(runtime_dispatch_policy, dict):
        runtime_dispatch_policy = {}
    manifest_tasks: list[dict[str, Any]] = []
    task_packet_paths: list[str] = []
    for task in taskbook.get("agent_tasks") or []:
        if not isinstance(task, dict):
            continue
        task_id = task.get("task_id")
        agent_role = task.get("agent_role")
        if not isinstance(task_id, str) or not task_id:
            continue
        task_packet_path = task_dir / f"task__{rid}__{task_id}.json"
        expected_result_path = result_dir / f"agent_result__{rid}__{task_id}.json"
        packet = {
            "task_packet_version": TASK_PACKET_VERSION,
            "report_id": rid,
            "factor_id": taskbook.get("factor_id") or rid,
            "task_id": task_id,
            "agent_role": agent_role,
            "research_protocol_version": task.get("research_protocol_version"),
            "route_id": task.get("route_id"),
            "route_family": task.get("route_family"),
            "route_status_at_dispatch": task.get("route_status_at_dispatch"),
            "route_fingerprint": task.get("route_fingerprint"),
            "blind_context_hash": task.get("blind_context_hash"),
            "expected_agent_identifier": task.get("expected_agent_identifier"),
            "blind_context_policy": task.get("blind_context_policy") or {},
            "proof_obligation_ids": task.get("proof_obligation_ids") or [],
            "exact_gap": task.get("exact_gap"),
            "reopen_only_if": task.get("reopen_only_if") or [],
            "source_taskbook_path": relpath(taskbook_path),
            "source_packet_path": taskbook.get("source_packet_path"),
            "expected_result_path": relpath(expected_result_path),
            "write_scope": relpath(result_dir) + "/",
            "canonical_write_permission": False,
            "execution_allowed_by_default": False,
            "human_approval_required": True,
            "runtime_dispatch_policy": runtime_dispatch_policy,
            "research_question": task.get("research_question"),
            "shared_context": task.get("visible_context") or {},
            "measurement_program_binding": task.get(
                "measurement_program_binding"
            )
            or {},
            "evo_v2_required": task.get("evo_v2_required") is True,
            "evo_v2_packet_context": task.get("evo_v2_packet_context"),
            "evo_v2_task_identity": task.get("evo_v2_task_identity"),
            "required_outputs": task.get("required_outputs") or [],
            "allowed_tools": task.get("allowed_tools") or [],
            "forbidden_changes": task.get("forbidden_changes") or [],
            "forbidden_write_targets": forbidden_write_targets,
            "result_contract": {
                "result_version": "factorforge_agentic_revision_council_result_v1",
                "producer_allowed": ["real_agent"],
                "proposal_generation_mode_allowed": ["agentic"],
                "research_depth_allowed": ["medium", "high"],
                "identity_binding_required": True,
                "measurement_program_binding_required": True,
                "evo_v2_closed_union_required": task.get("evo_v2_required") is True,
                "evo_v2_allowed_outcomes": (
                    ["MINIMAL_MECHANISM_DELTA", "NO_DERIVED_LAW"]
                    if task.get("evo_v2_required") is True
                    else []
                ),
                "candidate_revision_law_cardinality": (
                    {
                        "MINIMAL_MECHANISM_DELTA": 1,
                        "NO_DERIVED_LAW": 0,
                    }
                    if task.get("evo_v2_required") is True
                    else None
                ),
            },
        }
        write_json(task_packet_path, packet)
        task_packet_sha256 = sha256_file(task_packet_path)
        task_packet_paths.append(relpath(task_packet_path))
        manifest_tasks.append(
            {
                "task_id": task_id,
                "agent_role": agent_role,
                "route_id": task.get("route_id"),
                "route_family": task.get("route_family"),
                "route_fingerprint": task.get("route_fingerprint"),
                "blind_context_hash": task.get("blind_context_hash"),
                "expected_agent_identifier": task.get("expected_agent_identifier"),
                "measurement_program_binding": task.get(
                    "measurement_program_binding"
                )
                or {},
                "evo_v2_required": task.get("evo_v2_required") is True,
                "evo_v2_packet_context": task.get("evo_v2_packet_context"),
                "evo_v2_task_identity": task.get("evo_v2_task_identity"),
                "task_packet_sha256": task_packet_sha256,
                "blind_phase": (
                    (task.get("blind_context_policy") or {}).get("blind_phase")
                    is True
                ),
                "task_packet_path": relpath(task_packet_path),
                "expected_result_path": relpath(expected_result_path),
                "status": "awaiting_result",
                "required": True,
            }
        )

    manifest = {
        "dispatch_manifest_version": MANIFEST_VERSION,
        "report_id": rid,
        "factor_id": taskbook.get("factor_id") or rid,
        "created_at_utc": utc_now(),
        "source_taskbook_path": relpath(taskbook_path),
        "status": "awaiting_agent_results",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "runtime_dispatch_policy": runtime_dispatch_policy,
        "research_protocol_version": taskbook.get("research_protocol_version"),
        "research_protocol_gate": taskbook.get("research_protocol_gate") or {},
        "evo_v2": taskbook.get("evo_v2"),
        "route_selection_policy": taskbook.get("route_selection_policy") or {},
        "agent_task_count": len(manifest_tasks),
        "agent_tasks": manifest_tasks,
        "forbidden_write_targets": forbidden_write_targets,
        "next_steps": [
            "Each assigned agent reads its task packet.",
            "Each assigned agent writes only its expected result path.",
            "Main agent runs validate_agentic_council_result.py.",
            "Main agent runs finalize_agentic_council_dispatch.py.",
        ],
    }
    out = council_dir / f"dispatch_manifest__{rid}.json"
    write_json(out, manifest)
    print(
        json.dumps(
            {
                "status": "written",
                "report_id": rid,
                "dispatch_manifest_path": str(out),
                "agent_task_count": len(manifest_tasks),
                "agent_task_packet_paths": task_packet_paths,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
