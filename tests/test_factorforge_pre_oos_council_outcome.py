from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from factor_factory.evo_v2 import (
    artifact_sha256,
    sha256_file,
    stable_json_hash,
    with_content_hash,
)
from factor_factory.revision_council.evo_v2 import (
    COUNCIL_EVO_V2_CONTRACT_VERSION,
    proposal_law_sha256,
)
from factor_factory.revision_council.pre_oos_outcome import (
    PRE_OOS_ROOT_SYNTHESIS_VERSION,
    materialize_pre_oos_council_outcome,
    pre_oos_outcome_evidence_reference,
    pre_oos_outcome_verifier_path,
    pre_oos_root_synthesis_path,
    validate_pre_oos_root_synthesis,
)
from factor_factory.revision_council.production import (
    build_evo_task_identity,
    load_formal_evo_packet_context,
    result_evo_outcome_summary,
)
from factor_factory.research_conjecture import (
    build_epistemic_evolution_lifecycle,
    epistemic_evolution_lifecycle_path,
    workspace_runtime_trust_manifest,
)
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.research_org.runtime_trust import load_runtime_trust_store
from tests.test_factorforge_evo_v2 import REPORT_ID
from tests.test_revision_council_evo_v2 import (
    _authority,
    _no_derived_proof,
)
from tests.test_revision_council_evo_v2_production import _formal_workspace


REPO_ROOT = Path(__file__).resolve().parents[1]
MEASUREMENT_BINDING = {
    "mathematical_object": "mechanism-specific auditable statement",
    "mechanism_equation_or_functional": (
        "primary_object_t = primary_mechanism(inputs_t)"
    ),
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _refresh(payload: dict) -> None:
    payload.pop("content_sha256", None)
    payload.update(with_content_hash(payload))


def _law(task_id: str) -> dict:
    return {
        "law_id": f"law_{task_id}",
        "revision_type": "mechanism_challenge",
        "revision_model_layer": "primary_math_mechanism",
        "law_statement": f"add the single qualified interaction for {task_id}",
        "expression_change_direction": "add one mechanism-bound interaction",
        "expected_metric_change": [
            "the qualified interaction survives its purged IS ablation",
            "the frozen alias residual remains flat",
        ],
        "falsification_tests": [
            "remove the interaction and recover the contradiction",
            "retain the alias control and require a distinct signature",
        ],
        "kill_criteria": [
            "the added term is observationally redundant",
            "the distinctive prediction fails in purged IS",
        ],
        "why_not_portfolio_fix": "the contradiction is in the mathematical mechanism",
    }


def _evo_result(
    *,
    formal_feedback: dict,
    bundle: dict[str, dict],
    context: dict,
    task: dict,
    outcome_name: str,
) -> dict:
    task_id = task["task_id"]
    feedback_ref = context["canonical_feedback_ref"]
    intake = {
        "contradiction_id": context["contradiction_id"],
        "source_state": "QUALIFIED_CONTRADICTION",
        "validity_quarantine": {
            "state": "VALIDITY_QUARANTINE",
            "status": "CLEARED",
            "unresolved_blockers": [],
            "qualified_feedback_ref": copy.deepcopy(feedback_ref),
        },
    }
    law = _law(task_id)
    if outcome_name == "MINIMAL_MECHANISM_DELTA":
        delta = copy.deepcopy(bundle["mechanism_delta"])
        delta["feedback_ref"] = copy.deepcopy(feedback_ref)
        _refresh(delta)
        backprojection = copy.deepcopy(bundle["economic_backprojection"])
        backprojection["mechanism_delta_ref"]["sha256"] = artifact_sha256(delta)
        _refresh(backprojection)
        laws = [law]
        derivation_outcome = {
            "outcome": outcome_name,
            "mechanism_delta": delta,
            "economic_backprojection": backprojection,
            "no_derived_law": None,
        }
        law_binding = {
            "law_index": 0,
            "law_sha256": proposal_law_sha256(law),
            "delta_id": delta["minimal_extension"]["delta_id"],
        }
    else:
        laws = []
        derivation_outcome = {
            "outcome": outcome_name,
            "mechanism_delta": None,
            "economic_backprojection": None,
            "no_derived_law": _no_derived_proof(context["contradiction_id"]),
        }
        law_binding = None
    public_record = {
        "research_question": f"which minimal law resolves {task_id}",
        "assumptions": [{"assumption": "the frozen estimand remains fixed"}],
        "mathematical_objects": [
            {
                "name": MEASUREMENT_BINDING["mathematical_object"],
                "meaning": "the frozen mechanism object",
            }
        ],
        "selected_tools": [
            {
                "tool": "minimal_extension_analysis",
                "why_selected": "it tests one added object against the baseline",
            }
        ],
        "formula_claims": [
            {
                "claim": "the candidate changes one mechanism term",
                "formula_or_relation": "K_prime = K + lambda G",
            }
        ],
        "derivation_steps_summary": [
            "bind the qualified contradiction",
            "test the smallest mechanism extension",
        ],
        "limiting_cases": [
            {"case": "lambda is zero", "polarity": "negative"},
            {"case": "lambda is nonzero", "polarity": "positive"},
        ],
        "falsification_tests": [
            "remove the added term",
            "retain the frozen alias control",
        ],
        "kill_criteria": [
            "the term is redundant",
            "the signature is not distinct",
        ],
        "overclaim_guard": "this remains a review-only pre-OOS derivation",
    }
    return {
        "result_version": "factorforge_agentic_revision_council_result_v1",
        "report_id": REPORT_ID,
        "task_id": task_id,
        "agent_role": task["agent_role"],
        "agent_identifier": task["expected_agent_identifier"],
        "producer": "real_agent",
        "research_depth": "high",
        "proposal_generation_mode": "agentic",
        "status": "final",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "route_status": "supported",
        "approach_route": {
            "route_id": task["route_id"],
            "route_family": task["route_family"],
            "core_hypothesis": "one missing mechanism boundary explains the contradiction",
            "distinct_from_other_routes": "this route changes a different boundary",
            "exact_gap_after_analysis": "fresh child evidence remains unavailable",
        },
        "dispatch_identity": {
            "source_task_packet_sha256": task["task_packet_sha256"],
            "route_fingerprint": task["route_fingerprint"],
            "blind_context_hash": task["blind_context_hash"],
            "evo_v2_task_identity_sha256": task["evo_v2_task_identity"][
                "identity_sha256"
            ],
        },
        "measurement_program_binding": copy.deepcopy(MEASUREMENT_BINDING),
        "economic_hypothesis_review": {
            "refined_second_layer_mechanism": "a missing interaction boundary",
            "payer_or_counterparty_update": "the payer remains a hypothesis",
            "what_step4_metrics_changed_in_the_hypothesis": "none; only purged IS is visible",
            "preserve_broad_direction": True,
        },
        "math_mechanism_derivation": {
            "selected_tool": "minimal_extension_analysis",
            "selected_tool_rationale": "one term is the smallest identified extension",
            "baseline_model": MEASUREMENT_BINDING[
                "mechanism_equation_or_functional"
            ],
            "model_mutation": "add one interaction or retain no derived law",
            "mathematical_objects": [MEASUREMENT_BINDING["mathematical_object"]],
            "derivation_steps": ["bind contradiction", "test recovery limit"],
            "derived_state_variables": ["qualified_interaction_state"],
            "observable_estimators": ["legal purged IS interaction estimator"],
            "expected_metric_signature": ["distinct interaction", "flat alias"],
            "falsification_tests": ["removal test", "alias test"],
        },
        "model_to_formula_translation": {
            "candidate_formula": (
                "-(pre_close / open - 1.0)"
                if outcome_name == "MINIMAL_MECHANISM_DELTA"
                else None
            ),
            "disposition": (
                "candidate_expression"
                if outcome_name == "MINIMAL_MECHANISM_DELTA"
                else "no_derived_revision_with_proof"
            ),
            "operator_support_status": "review_only_not_executed",
            "information_set_legality": "legal_purged_is_only",
            "mapping_from_model_terms_to_formula_components": [
                {"model_term": "G", "formula_component": "qualified_interaction"}
            ],
        },
        "public_derivation_record": public_record,
        "candidate_revision_laws": laws,
        "proof_obligation_updates": [
            {
                "obligation_id": task_id + "_obligation",
                "status": "open",
                "finding": "fresh child evidence is still required",
                "evidence_refs": [],
            }
        ],
        "counterexamples": [
            {
                "attack_type": "alias_attack",
                "construction_or_scenario": "retain the alias and remove the added term",
                "predicted_failure": "the distinctive signature disappears",
                "discriminating_test": "compare the registered component ablations",
            }
        ],
        "reopen_criteria": ["new legal evidence identifies the missing boundary"],
        "independence_attestation": {
            "favored_thesis_seen_before_submission": False,
            "derived_from_visible_facts_only": True,
        },
        "falsification_tests": public_record["falsification_tests"],
        "kill_criteria": public_record["kill_criteria"],
        "overclaim_guard": public_record["overclaim_guard"],
        "evo_v2_task_identity": copy.deepcopy(task["evo_v2_task_identity"]),
        "evo_v2": {
            "contract_version": COUNCIL_EVO_V2_CONTRACT_VERSION,
            "intake_gate": intake,
            "authority": _authority(),
            "feedback_ledger": copy.deepcopy(feedback_ref),
            "derivation_outcome": derivation_outcome,
            "proposal_law_binding": law_binding,
        },
    }


def _artifact_ref(root: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}


def _fixture(
    root: Path,
    *,
    outcomes: tuple[str, ...] = (
        "MINIMAL_MECHANISM_DELTA",
        "NO_DERIVED_LAW",
    ),
    selected_index: int = 0,
) -> tuple[dict, Path]:
    bundle, formal_feedback = _formal_workspace(root)
    context, loaded_feedback = load_formal_evo_packet_context(root, REPORT_ID)
    assert context is not None and loaded_feedback == formal_feedback
    council_dir = (
        root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / REPORT_ID
    )
    result_dir = council_dir / "agent_results"
    taskbook_tasks = []
    for index, _outcome in enumerate(outcomes):
        task_id = f"route_task_{index + 1}"
        route_id = f"route_{index + 1}"
        identity = build_evo_task_identity(
            context,
            report_id=REPORT_ID,
            task_id=task_id,
            route_id=route_id,
            route_fingerprint=f"fingerprint_{index + 1}",
            blind_context_hash=f"blind_hash_{index + 1}",
        )
        taskbook_tasks.append(
            {
                "task_id": task_id,
                "agent_role": f"independent_role_{index + 1}",
                "route_id": route_id,
                "route_family": f"route_family_{index + 1}",
                "route_fingerprint": f"fingerprint_{index + 1}",
                "blind_context_hash": f"blind_hash_{index + 1}",
                "expected_agent_identifier": f"session_agent_{index + 1}",
                "research_protocol_version": (
                    "factorforge_research_conjecture_protocol_v1"
                ),
                "route_status_at_dispatch": "open",
                "blind_context_policy": {
                    "blind_phase": True,
                    "favored_thesis_visible": False,
                },
                "proof_obligation_ids": [task_id + "_obligation"],
                "exact_gap": "derive or reject one minimal law",
                "reopen_only_if": ["new legal evidence changes identification"],
                "research_question": "which minimal law resolves this route",
                "visible_context": {"evo_v2": context},
                "measurement_program_binding": copy.deepcopy(
                    MEASUREMENT_BINDING
                ),
                "evo_v2_required": True,
                "evo_v2_packet_context": context,
                "evo_v2_task_identity": identity,
                "required_outputs": [
                    "economic_hypothesis_review",
                    "math_mechanism_derivation",
                    "measurement_program_binding",
                    "model_to_formula_translation",
                    "public_derivation_record",
                    "candidate_revision_laws",
                    "falsification_tests",
                    "kill_criteria",
                    "overclaim_guard",
                    "approach_route",
                    "proof_obligation_updates",
                    "counterexamples",
                    "route_status",
                    "reopen_criteria",
                    "independence_attestation",
                    "evo_v2_task_identity",
                    "evo_v2_closed_derivation_outcome",
                ],
                "allowed_tools": ["public_derivation"],
                "forbidden_changes": ["change frozen authority"],
            }
        )
    runtime_policy = {
        "policy_version": "factorforge_runtime_dispatch_policy_v1",
        "runtime": "unknown",
        "subagent_dispatcher": "main_agent",
        "default_model_policy": "inherit_main_model",
        "provider_override_policy": "only_if_user_explicitly_requests",
        "provider_required_by_factor_forge": False,
        "external_provider_selection_allowed": False,
        "manual_provider_override": None,
        "model_override": None,
    }
    taskbook = {
        "taskbook_version": "factorforge_agentic_revision_council_taskbook_v1",
        "report_id": REPORT_ID,
        "factor_id": "negative_pv_shape",
        "runtime_dispatch_policy": runtime_policy,
        "research_protocol_version": "factorforge_research_conjecture_protocol_v1",
        "research_protocol_gate": {"status": "PASS"},
        "evo_v2": context,
        "route_selection_policy": {"policy": "mechanism_distinct"},
        "agent_tasks": taskbook_tasks,
    }
    taskbook_path = council_dir / f"agentic_taskbook__{REPORT_ID}.json"
    _write_json(taskbook_path, taskbook)
    environment = os.environ.copy()
    environment["FACTORFORGE_ROOT"] = str(root)
    build = subprocess.run(
        [
            sys.executable,
            str(
                REPO_ROOT
                / "skills/factor-forge-step6/scripts/"
                "build_agentic_council_dispatch_manifest.py"
            ),
            "--report-id",
            REPORT_ID,
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    dispatch_path = council_dir / f"dispatch_manifest__{REPORT_ID}.json"
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    tasks = dispatch["agent_tasks"]

    results = []
    records = []
    for task, outcome_name in zip(tasks, outcomes, strict=True):
        payload = _evo_result(
            formal_feedback=formal_feedback,
            bundle=bundle,
            context=context,
            task=task,
            outcome_name=outcome_name,
        )
        path = root / task["expected_result_path"]
        _write_json(path, payload)
        reference = {
            "task_id": task["task_id"],
            **_artifact_ref(root, path),
        }
        outcome = result_evo_outcome_summary(payload)
        assert outcome is not None
        records.append(
            {
                "task": task,
                "payload": payload,
                "path": path,
                "ref": reference,
                "outcome": outcome,
            }
        )
        results.append(
            {
                "task_id": task["task_id"],
                "agent_role": task["agent_role"],
                "result_path": str(path),
                "producer": "real_agent",
                "agent_identifier": task["expected_agent_identifier"],
                "status": "final",
                "result_sha256": reference["sha256"],
                "evo_v2_task_identity": task["evo_v2_task_identity"],
                "evo_v2_outcome": outcome,
            }
        )
    collection = {
        "collection_version": "factorforge_agentic_council_result_collection_v1",
        "report_id": REPORT_ID,
        "evo_v2": context,
        "status": "complete",
        "required_result_count": len(tasks),
        "present_result_count": len(tasks),
        "valid_result_count": len(tasks),
        "invalid_result_count": 0,
        "missing_result_count": 0,
        "valid_results": results,
        "invalid_results": [],
        "missing_results": [],
        "independence_block_reasons": [],
        "ready_for_finalize": True,
    }
    collection_path = council_dir / f"agentic_result_collection__{REPORT_ID}.json"
    _write_json(collection_path, collection)

    valid_summary_results = []
    route_summary = []
    law_index = []
    for record in records:
        task = record["task"]
        payload = record["payload"]
        valid_summary_results.append(
            {
                "path": str(record["path"]),
                "task_id": task["task_id"],
                "agent_role": task["agent_role"],
                "producer": "real_agent",
                "research_depth": "high",
                "proposal_generation_mode": "agentic",
                "route_id": task["route_id"],
                "route_family": task["route_family"],
                "route_status": "supported",
                "result_sha256": record["ref"]["sha256"],
                "evo_v2_task_identity": task["evo_v2_task_identity"],
                "evo_v2_outcome": record["outcome"],
            }
        )
        route_summary.append(
            {
                "task_id": task["task_id"],
                "agent_role": task["agent_role"],
                "route_id": task["route_id"],
                "route_family": task["route_family"],
                "source_result_path": str(record["path"]),
                "source_result_sha256": record["ref"]["sha256"],
            }
        )
        if record["outcome"]["outcome"] == "MINIMAL_MECHANISM_DELTA":
            law = payload["candidate_revision_laws"][0]
            law_index.append(
                {
                    "law_id": law["law_id"],
                    "route_id": task["route_id"],
                    "source_result_sha256": record["ref"]["sha256"],
                    "law_hash": record["outcome"]["law_sha256"],
                    "evo_v2_task_identity_sha256": record["outcome"][
                        "evo_v2_task_identity_sha256"
                    ],
                    "mechanism_delta_sha256": record["outcome"][
                        "mechanism_delta_sha256"
                    ],
                    "economic_backprojection_sha256": record["outcome"][
                        "economic_backprojection_sha256"
                    ],
                    "delta_id": record["outcome"]["delta_id"],
                }
            )
    summary = {
        "contract_version": "factorforge_revision_council_summary_v1",
        "report_id": REPORT_ID,
        "evo_v2": context,
        "selection_source": "agentic_results",
        "deterministic_fallback_used": False,
        "valid_agent_results": valid_summary_results,
        "blocked_agent_results": [],
        "research_route_summary": route_summary,
        "candidate_law_index": law_index,
        "root_synthesis_contract": {
            "required": True,
            "majority_vote_forbidden": True,
            "must_compare_every_route": True,
            "must_resolve_or_preserve_dissent": True,
            "must_list_open_proof_obligations": True,
            "route_family_count": len(tasks),
        },
    }
    summary_path = council_dir / f"revision_council_summary__{REPORT_ID}.json"
    _write_json(summary_path, summary)
    appendix = {
        "appendix_version": "factorforge_revision_council_derivation_appendix_v1",
        "report_id": REPORT_ID,
        "status": "public_derivation_appendix",
        "selection_source": "agentic_results",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required_before_step3b": True,
        "source_summary_path": str(summary_path),
        "source_paths": [str(record["path"]) for record in records],
        "missing_source_paths": [],
        "agent_derivations": [
            {
                "source_path": str(record["path"]),
                "task_id": record["task"]["task_id"],
                "agent_role": record["task"]["agent_role"],
                "producer": "real_agent",
                "candidate_revision_laws": record["payload"][
                    "candidate_revision_laws"
                ],
            }
            for record in records
        ],
    }
    appendix_json_path = council_dir / f"council_derivation_appendix__{REPORT_ID}.json"
    appendix_md_path = council_dir / f"council_derivation_appendix__{REPORT_ID}.md"
    _write_json(appendix_json_path, appendix)
    appendix_md_path.write_text(f"# {REPORT_ID} pre-OOS derivations\n", encoding="utf-8")

    selected = records[selected_index]
    selected_summary = selected["outcome"]
    selected_laws = selected["payload"]["candidate_revision_laws"]
    selected_law = selected_laws[0] if selected_laws else None
    selected_outcome = {
        "outcome": selected_summary["outcome"],
        "task_id": selected["task"]["task_id"],
        "route_id": selected["task"]["route_id"],
        "result_sha256": selected["ref"]["sha256"],
        "law_id": selected_law["law_id"] if selected_law else None,
        "law_sha256": selected_summary.get("law_sha256"),
        "delta_id": selected_summary.get("delta_id"),
        "mechanism_delta_sha256": selected_summary.get("mechanism_delta_sha256"),
        "economic_backprojection_sha256": selected_summary.get(
            "economic_backprojection_sha256"
        ),
        "no_derived_law_sha256": selected_summary.get("no_derived_law_sha256"),
    }
    synthesis = {
        "contract_version": PRE_OOS_ROOT_SYNTHESIS_VERSION,
        "report_id": REPORT_ID,
        "evidence_view": "PURGED_IS_ONLY",
        "authority": {
            "status": "AGENT_AUTHORED_REVIEW_ONLY",
            "host_transition_authority": False,
            "human_approval_authority": False,
            "canonical_write_allowed": False,
            "execution_allowed": False,
            "factor_verdict": "NOT_ISSUED",
            "oos_accessed": False,
            "child_execution_allowed": False,
        },
        "evidence_bindings": {
            "feedback_ledger_ref": context["canonical_feedback_ref"],
            "lifecycle_ref": context["lifecycle_ref"],
            "dispatch_manifest_ref": _artifact_ref(root, dispatch_path),
            "result_collection_ref": _artifact_ref(root, collection_path),
            "council_summary_ref": _artifact_ref(root, summary_path),
            "derivation_appendix_json_ref": _artifact_ref(root, appendix_json_path),
            "derivation_appendix_markdown_ref": _artifact_ref(root, appendix_md_path),
            "raw_result_refs": [record["ref"] for record in records],
            "selected_proposal_ref": selected["ref"],
        },
        "route_result_analysis": [
            {
                "task_id": record["task"]["task_id"],
                "route_id": record["task"]["route_id"],
                "route_family": record["task"]["route_family"],
                "agent_identifier": record["payload"]["agent_identifier"],
                "result_ref": record["ref"],
                "outcome": record["outcome"]["outcome"],
                "disposition": (
                    "selected" if record is selected else "not_selected"
                ),
                "exact_gap_or_closed_obligation": (
                    "the qualified contradiction is addressed by this exact result"
                ),
                "incompatible_assumptions": [
                    "the competing route assumes a different missing boundary"
                ],
                "discriminating_evidence": [
                    "the preregistered purged IS ablation distinguishes the routes"
                ],
                "open_proof_obligations": [
                    "fresh child evidence remains required"
                ],
                "dissent": {
                    "status": (
                        "SELECTED_RESULT" if record is selected else "PRESERVED_OPEN"
                    ),
                    "position": "this route retains its distinct mechanism claim",
                    "resolution": (
                        "selected as the exact raw result"
                        if record is selected
                        else "preserved for the child discriminating test"
                    ),
                },
            }
            for record in records
        ],
        "dissent_resolution": {
            "policy": (
                "PRESERVE_OR_RESOLVE_EACH_RESULT_DISSENT_WITH_DISCRIMINATING_EVIDENCE"
            ),
            "all_result_positions_covered": True,
            "resolution_summary": (
                "every route remains visible and non-selected objections stay open"
            ),
            "unresolved_task_ids": [
                record["task"]["task_id"]
                for record in records
                if record is not selected
            ],
        },
        "selection": {
            "policy": "EVIDENCE_BASED_EXACT_RAW_RESULT_SELECTION_NO_AGGREGATION",
            "selected_task_id": selected["task"]["task_id"],
            "selected_result_sha256": selected["ref"]["sha256"],
            "rationale": (
                "the selected route supplies the most direct preregistered "
                "discriminating test while preserving all frozen invariants"
            ),
            "decisive_evidence": [
                "the selected result binds the qualified contradiction and exact ablation"
            ],
            "majority_vote_used": False,
            "score_or_rank_used": False,
            "result_aggregation_used": False,
        },
        "selected_outcome": selected_outcome,
    }
    synthesis["content_sha256"] = stable_json_hash(synthesis)
    synthesis_path = pre_oos_root_synthesis_path(root, REPORT_ID)
    _write_json(synthesis_path, synthesis)
    return synthesis, synthesis_path


def _validate_without_external_tools(
    root: Path,
    synthesis: dict,
    synthesis_path: Path,
) -> tuple[dict | None, list[str]]:
    return validate_pre_oos_root_synthesis(
        synthesis,
        workspace_root=root,
        report_id=REPORT_ID,
        synthesis_path=synthesis_path,
        validator_runner=lambda _root, _report, _paths: [],
    )


def test_mixed_outcomes_select_one_exact_raw_result_without_host_authority(
    tmp_path: Path,
) -> None:
    synthesis, synthesis_path = _fixture(tmp_path)
    report, reasons = validate_pre_oos_root_synthesis(
        synthesis,
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        synthesis_path=synthesis_path,
    )
    assert reasons == []
    assert report is not None
    assert report["verifier_status"] == "PASS"
    assert report["authorized_host_transition_state"] == "MINIMAL_MECHANISM_DELTA"
    assert report["validation_counts"] == {
        "required_route_count": 2,
        "validated_raw_result_count": 2,
        "minimal_mechanism_delta_count": 1,
        "no_derived_law_count": 1,
        "preserved_open_dissent_count": 1,
        "selected_raw_result_count": 1,
    }
    assert report["authority"]["host_transition_performed"] is False
    assert report["authority"]["human_approval_granted"] is False
    assert report["selected_outcome"]["law_id"] == "law_route_task_1"


def test_all_no_derived_is_closed_without_inventing_a_law(tmp_path: Path) -> None:
    synthesis, synthesis_path = _fixture(
        tmp_path,
        outcomes=("NO_DERIVED_LAW", "NO_DERIVED_LAW"),
        selected_index=1,
    )
    report, reasons = _validate_without_external_tools(
        tmp_path, synthesis, synthesis_path
    )
    assert reasons == []
    assert report is not None
    selected = report["selected_outcome"]
    assert selected["outcome"] == "NO_DERIVED_LAW"
    assert selected["law_id"] is None
    assert selected["law_sha256"] is None
    assert selected["mechanism_delta_sha256"] is None
    assert selected["economic_backprojection_sha256"] is None
    assert len(selected["no_derived_law_sha256"]) == 64


def test_materialized_outcome_replays_after_signed_lifecycle_append(
    tmp_path: Path,
) -> None:
    synthesis, synthesis_path = _fixture(tmp_path)
    materialize_pre_oos_council_outcome(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        synthesis_path=synthesis_path,
    )
    lifecycle_path = epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID)
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    evidence_ref = lifecycle["events"][-1]["evidence_refs"][0]
    trust = load_runtime_trust_store(
        tmp_path / "host-private-trust",
        installation_id="council-test-installation-001",
    )
    manifest = workspace_runtime_trust_manifest(tmp_path, report_id=REPORT_ID)
    receipt = trust.sign(
        "host_admission",
        {
            "receipt_type": "EVO_V2_LIFECYCLE_TRANSITION",
            "report_id": REPORT_ID,
            "sequence": 3,
            "from_state": "QUALIFIED_CONTRADICTION",
            "to_state": "MINIMAL_MECHANISM_DELTA",
            "lifecycle_parent_sha256": stable_hash(lifecycle),
            "evidence_refs_sha256": stable_hash([evidence_ref]),
            "trust_manifest_sha256": manifest["manifest_sha256"],
            "authority_scope": (
                "HOST_LIFECYCLE_TRANSITION_ONLY_NO_RESEARCH_SEMANTIC_AUTHORITY"
            ),
            "oos_accessed": False,
        },
    )
    receipt_path = lifecycle_path.parent / "lifecycle_transition_receipt__0003.json"
    _write_json(receipt_path, receipt)
    receipt_ref = {
        "path": receipt_path.relative_to(tmp_path).as_posix(),
        "sha256": sha256_file(receipt_path),
        "receipt_id": receipt["receipt_id"],
        "trust_manifest_sha256": manifest["manifest_sha256"],
    }
    appended = build_epistemic_evolution_lifecycle(
        report_id=REPORT_ID,
        to_state="MINIMAL_MECHANISM_DELTA",
        evidence_refs=[evidence_ref],
        existing=lifecycle,
        actor_receipt_ref=receipt_ref,
    )
    _write_json(lifecycle_path, appended)

    reference, reasons = pre_oos_outcome_evidence_reference(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        expected_transition_state="MINIMAL_MECHANISM_DELTA",
    )

    assert reasons == []
    assert reference is not None
    assert reference["authorized_transition_state"] == "MINIMAL_MECHANISM_DELTA"


@pytest.mark.parametrize(
    "mutate,expected_token",
    [
        (
            lambda synthesis: synthesis["route_result_analysis"].pop(),
            "route_result_analysis_coverage_invalid",
        ),
        (
            lambda synthesis: synthesis["selection"].__setitem__(
                "majority_vote_used", True
            ),
            "selection_policy_invalid",
        ),
        (
            lambda synthesis: synthesis["selection"].__setitem__(
                "rationale", "the majority voted for this route"
            ),
            "forbidden_selection_basis",
        ),
        (
            lambda synthesis: synthesis["selection"].__setitem__(
                "result_aggregation_used", True
            ),
            "selection_policy_invalid",
        ),
        (
            lambda synthesis: synthesis["selected_outcome"].__setitem__(
                "law_sha256", "0" * 64
            ),
            "selected_outcome_exact_tuple_mismatch",
        ),
        (
            lambda synthesis: synthesis["evidence_bindings"][
                "selected_proposal_ref"
            ].__setitem__("sha256", "0" * 64),
            "selected_proposal_ref_mismatch",
        ),
    ],
)
def test_synthesis_mutations_fail_closed(
    tmp_path: Path,
    mutate,
    expected_token: str,
) -> None:
    synthesis, synthesis_path = _fixture(tmp_path)
    mutate(synthesis)
    synthesis.pop("content_sha256", None)
    synthesis["content_sha256"] = stable_json_hash(synthesis)
    _write_json(synthesis_path, synthesis)
    report, reasons = _validate_without_external_tools(
        tmp_path, synthesis, synthesis_path
    )
    assert report is None
    assert any(expected_token in reason for reason in reasons)


def test_raw_result_and_merged_artifact_byte_mutations_are_detected(
    tmp_path: Path,
) -> None:
    synthesis, synthesis_path = _fixture(tmp_path)
    raw_ref = synthesis["evidence_bindings"]["raw_result_refs"][1]
    raw_path = tmp_path / raw_ref["path"]
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["agent_identifier"] = "post_collection_mutation"
    _write_json(raw_path, raw)
    report, reasons = _validate_without_external_tools(
        tmp_path, synthesis, synthesis_path
    )
    assert report is None
    assert any(
        token in reason
        for reason in reasons
        for token in (
            "result_collection_binding_mismatch",
            "council_summary_result_mismatch",
            "evidence_binding_mismatch:raw_result_refs",
        )
    )

    synthesis, synthesis_path = _fixture(tmp_path)
    summary_ref = synthesis["evidence_bindings"]["council_summary_ref"]
    summary_path = tmp_path / summary_ref["path"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["candidate_law_index"] = []
    _write_json(summary_path, summary)
    report, reasons = _validate_without_external_tools(
        tmp_path, synthesis, synthesis_path
    )
    assert report is None
    assert any("council_summary_law_index_mismatch" in reason for reason in reasons)


def test_unbound_extra_result_and_missing_appendix_route_are_rejected(
    tmp_path: Path,
) -> None:
    synthesis, synthesis_path = _fixture(tmp_path)
    extra = (
        tmp_path
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / REPORT_ID
        / "agent_results"
        / f"agent_result__{REPORT_ID}__unbound.json"
    )
    _write_json(extra, {"not": "bound"})
    report, reasons = _validate_without_external_tools(
        tmp_path, synthesis, synthesis_path
    )
    assert report is None
    assert any("unbound_or_missing_raw_result_bytes" in reason for reason in reasons)

    extra.unlink()
    appendix_ref = synthesis["evidence_bindings"]["derivation_appendix_json_ref"]
    appendix_path = tmp_path / appendix_ref["path"]
    appendix = json.loads(appendix_path.read_text(encoding="utf-8"))
    appendix["agent_derivations"].pop()
    appendix["source_paths"].pop()
    _write_json(appendix_path, appendix)
    report, reasons = _validate_without_external_tools(
        tmp_path, synthesis, synthesis_path
    )
    assert report is None
    assert any("derivation_appendix" in reason for reason in reasons)


def test_materialization_is_canonical_idempotent_and_replay_detects_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import factor_factory.revision_council.pre_oos_outcome as module

    synthesis, synthesis_path = _fixture(tmp_path)
    monkeypatch.setattr(
        module,
        "_run_existing_validators",
        lambda _root, _report, _paths: [],
    )
    first = materialize_pre_oos_council_outcome(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        synthesis_path=synthesis_path,
    )
    second = materialize_pre_oos_council_outcome(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        synthesis_path=synthesis_path,
    )
    assert first["result"] == "PASS"
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert first["evidence_ref"] == second["evidence_ref"]
    output = pre_oos_outcome_verifier_path(tmp_path, REPORT_ID)
    assert output.read_bytes() == module.canonical_json_bytes(
        json.loads(output.read_text(encoding="utf-8"))
    )
    reference, reasons = pre_oos_outcome_evidence_reference(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        expected_transition_state="MINIMAL_MECHANISM_DELTA",
    )
    assert reasons == []
    assert reference == first["evidence_ref"]

    summary_path = tmp_path / synthesis["evidence_bindings"]["council_summary_ref"][
        "path"
    ]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["root_synthesis_contract"]["majority_vote_forbidden"] = False
    _write_json(summary_path, summary)
    reference, reasons = pre_oos_outcome_evidence_reference(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
    )
    assert reference is None
    assert reasons
