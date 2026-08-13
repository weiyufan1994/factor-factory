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
    expected_result_path = resolve(packet.get("expected_result_path"))
    required_outputs = "\n".join(f"- {item}" for item in packet.get("required_outputs") or [])
    allowed_tools = "\n".join(f"- {item}" for item in packet.get("allowed_tools") or [])
    forbidden_changes = "\n".join(f"- {item}" for item in packet.get("forbidden_changes") or [])
    forbidden_targets = "\n".join(f"- {item}" for item in packet.get("forbidden_write_targets") or [])
    print(
        f"""# Agentic Revision Council Assignment

Report ID: {rid}
Task ID: {packet.get("task_id")}
Agent role: {packet.get("agent_role")}

You are an advisory research agent.
You may only write the expected result JSON.
Do not modify Step3B handoff, generated_code, official library, or data/clean.
Do not propose portfolio/rebalance/short-leg/long-short/decile trading repair.
Do not provide hidden chain-of-thought.
Provide a public derivation record only.

Task packet path:
{packet_path}

Expected result path:
{expected_result_path}

Research question:
{packet.get("research_question")}

Required outputs:
{required_outputs}

Allowed tools:
{allowed_tools}

Forbidden changes:
{forbidden_changes}

Forbidden canonical write targets:
{forbidden_targets}

Result schema summary:
- result_version: factorforge_agentic_revision_council_result_v1
- status: final
- producer: real_agent
- agent_identifier: nonempty agent id
- research_depth: medium or high
- proposal_generation_mode: agentic
- canonical_write_permission: false
- execution_allowed_by_default: false
- human_approval_required: true
- measurement_program_binding: copy exactly from the task packet
- math_mechanism_derivation.baseline_model: exactly the frozen mechanism
  equation; put any alternative in model_mutation/candidate_revision_laws
- economic_hypothesis_review: preserve_broad_direction, refined_second_layer_mechanism, payer_or_counterparty_update, what_step4_metrics_changed_in_the_hypothesis
- math_mechanism_derivation: selected_tool plus rationale, rejected_tools, baseline_model, model_mutation, mathematical_objects, derivation_steps, derived_state_variables, observable_estimators, expected_metric_signature, falsification_tests
- model_to_formula_translation: candidate_formula or research_hold/operator_block/no_derived_revision_with_proof disposition, operator_support_status, mapping_from_model_terms_to_formula_components, information_set_legality
- public_derivation_record: assumptions, mathematical_objects, selected_tools with why_selected, formula_claims, derivation_steps_summary, limiting_cases, falsification_tests, kill_criteria, overclaim_guard
- candidate_revision_laws: revision_kind, expected_metric_change, falsification_tests, kill_criteria, why_not_portfolio_fix
- if evo_v2_required: copy evo_v2_task_identity exactly and return exactly one
  closed outcome: MINIMAL_MECHANISM_DELTA (one law plus mechanism_delta and
  economic_backprojection) or NO_DERIVED_LAW (zero laws plus complete proof)
- if evo_v2_required: use only PURGED_IS_ONLY context and do not read or cite
  sealed or consumed OOS artifacts
- terminal_control: required if recommending terminal stop; before max loops use revision_branch_only unless validated no-derived-revision, human override, or evidence BLOCK proof exists

Canonical write prohibition:
This task is advisory-only. The agent result cannot authorize Step3B, generated_code, official library, or clean-data writes.
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
