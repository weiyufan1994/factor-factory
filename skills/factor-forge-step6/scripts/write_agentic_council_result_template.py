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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else FF / candidate


def block(token: str, payload: dict[str, Any]) -> None:
    print(token + ": " + json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    rid = args.report_id
    manifest_path = OBJ / "research_iteration_master" / "revision_council" / rid / f"dispatch_manifest__{rid}.json"
    if not manifest_path.exists():
        block("BLOCK_AGENTIC_COUNCIL_DISPATCH_MANIFEST_MISSING", {"report_id": rid, "manifest_path": str(manifest_path)})
    manifest = load_json(manifest_path)
    task = next((item for item in manifest.get("agent_tasks") or [] if isinstance(item, dict) and item.get("task_id") == args.task_id), None)
    if not task:
        block("BLOCK_AGENTIC_COUNCIL_TASK_PACKET_MISSING", {"report_id": rid, "task_id": args.task_id})
    packet_path = resolve(task.get("task_packet_path"))
    if not packet_path.exists():
        block("BLOCK_AGENTIC_COUNCIL_TASK_PACKET_MISSING", {"report_id": rid, "task_id": args.task_id, "task_packet_path": str(packet_path)})
    packet = load_json(packet_path)
    out = Path(args.output).expanduser() if args.output else resolve(packet.get("expected_result_path"))
    template = {
        "result_version": "factorforge_agentic_revision_council_result_v1",
        "status": "draft",
        "report_id": rid,
        "task_id": packet.get("task_id"),
        "agent_role": packet.get("agent_role"),
        "producer": "real_agent",
        "agent_identifier": packet.get("expected_agent_identifier") or "",
        "dispatch_identity": {
            "source_task_packet_path": task.get("task_packet_path"),
            "source_task_packet_sha256": task.get("task_packet_sha256"),
            "route_fingerprint": packet.get("route_fingerprint"),
            "blind_context_hash": packet.get("blind_context_hash"),
            "evo_v2_task_identity_sha256": (
                (packet.get("evo_v2_task_identity") or {}).get("identity_sha256")
                if isinstance(packet.get("evo_v2_task_identity"), dict)
                else None
            ),
        },
        "evo_v2_task_identity": packet.get("evo_v2_task_identity"),
        "evo_v2": (
            {
                "feedback_ledger": (
                    packet.get("evo_v2_task_identity") or {}
                ).get("canonical_feedback_ref"),
                "intake_gate": {
                    "contradiction_id": (
                        packet.get("evo_v2_task_identity") or {}
                    ).get("contradiction_id"),
                    "source_state": (
                        packet.get("evo_v2_task_identity") or {}
                    ).get("lifecycle_state"),
                    "validity_quarantine": {},
                },
                "authority": {},
                "derivation_outcome": {},
                "proposal_law_binding": None,
            }
            if packet.get("evo_v2_required") is True
            else None
        ),
        "measurement_program_binding": packet.get(
            "measurement_program_binding"
        )
        or {},
        "research_depth": "medium",
        "proposal_generation_mode": "agentic",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "research_protocol_version": packet.get("research_protocol_version"),
        "approach_route": {
            "route_id": packet.get("route_id"),
            "route_family": packet.get("route_family"),
            "core_hypothesis": "",
            "distinct_from_other_routes": "",
            "exact_gap_after_analysis": "",
        },
        "proof_obligation_updates": [
            {
                "obligation_id": obligation_id,
                "status": "open",
                "finding": "",
                "evidence_refs": [],
            }
            for obligation_id in packet.get("proof_obligation_ids") or []
        ],
        "counterexamples": [
            {
                "attack_type": "",
                "construction_or_scenario": "",
                "predicted_failure": "",
                "discriminating_test": "",
                "status": "proposed",
                "evidence_refs": [],
            }
        ],
        "route_status": "open",
        "reopen_criteria": [],
        "independence_attestation": {
            "blind_phase": (
                (packet.get("blind_context_policy") or {}).get("blind_phase")
                is True
            ),
            "favored_thesis_seen_before_submission": None,
            "derived_from_visible_facts_only": None,
        },
        "economic_hypothesis_review": {},
        "math_mechanism_derivation": {
            "baseline_model": (
                packet.get("measurement_program_binding") or {}
            ).get("mechanism_equation_or_functional"),
            "mathematical_objects": [
                (
                    packet.get("measurement_program_binding") or {}
                ).get("mathematical_object")
            ],
        },
        "model_to_formula_translation": {},
        "public_derivation_record": {
            "research_question": packet.get("research_question") or "",
            "assumptions": [],
            "mathematical_objects": [
                {
                    "name": (
                        packet.get("measurement_program_binding") or {}
                    ).get("mathematical_object"),
                    "role": "current_frozen_model",
                }
            ],
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
    write_json(out, template)
    print(json.dumps({"status": "draft_template_written", "report_id": rid, "task_id": args.task_id, "path": str(out)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
