from __future__ import annotations

"""Runnable candidate adapter for the offline failure-diagnosis kernel.

The native planner intentionally produces a plan, not a post-hoc causal verdict.  This
adapter keeps every native object available for replay while exposing a compact view a
Step4/Step5 research agent can actually consume.  It performs no file discovery, test
execution, OOS access, canonical write, or production activation.
"""

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from factor_factory.epistemic_failure_diagnosis_offline import (
    AUTHORITY_EFFECT,
    compile_distinguishing_test_registry_candidate,
    compile_exploit_explore_dirac_advisory_candidate,
    compile_hypothesis_mismatch_candidate,
    compile_layer_assessment_plan_candidate,
    compile_material_rival_registry_candidate,
    compile_partition_independence_plan_candidate,
    compile_planner_terminal_candidate,
    compile_stage2_input_binding_from_raw,
    compile_synthetic_diagnosis_intake,
    validate_failure_diagnosis_planner_bundle,
)
from factor_factory.epistemic_source_first_offline import read_stable_regular_bytes
from factor_factory.research_org.contracts import strict_json_loads
from factor_factory.research_org.rfc8785_canonical import framed_sha256


SCHEMA_VERSION = "1.0.0"
ADAPTER_SCHEMA_ID = "factorforge_epistemic_diagnosis_kernel_adapter_offline_v1"
ADAPTER_DOMAIN = "FF_EPISTEMIC_DIAGNOSIS_KERNEL_ADAPTER_OFFLINE_V1"
DIAGNOSIS_IDENTITY_PROFILE_ID = "FF_EPISTEMIC_DIAGNOSIS_IDENTITY_V1"
DIAGNOSIS_IDENTITY_DOMAIN = "FF_EPISTEMIC_DIAGNOSIS_IDENTITY_V1"
TARGET_IDENTITY_DOMAIN = "FF_EPISTEMIC_DIAGNOSIS_TARGET_IDENTITY_V1"
FROZEN_HYPOTHESIS_DOMAIN = "FF_EPISTEMIC_DIAGNOSIS_FROZEN_HYPOTHESIS_V1"
MAX_RAW_JSON_BYTES = 16 * 1024 * 1024


class DiagnosisKernelAdapterError(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise DiagnosisKernelAdapterError(reason)


def _session_id(value: Any) -> str:
    _require(isinstance(value, str), "session_id:string_required")
    normalized = value.strip()
    _require(3 <= len(normalized) <= 128, "session_id:length")
    _require(all(character.isalnum() or character in "-_." for character in normalized), "session_id:unsafe")
    return normalized


def _sha256(value: Any, *, label: str) -> str:
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value),
        f"{label}:sha256_required",
    )
    return value


def _strict_raw_json_object(raw_bytes: Any, *, label: str) -> tuple[dict[str, Any], str]:
    _require(type(raw_bytes) is bytes, f"{label}:bytes_required")
    _require(0 < len(raw_bytes) <= MAX_RAW_JSON_BYTES, f"{label}:size")
    try:
        payload = strict_json_loads(raw_bytes, label=label)
    except Exception as exc:
        raise DiagnosisKernelAdapterError(f"{label}:invalid_json") from exc
    _require(isinstance(payload, dict), f"{label}:object_required")
    return payload, hashlib.sha256(raw_bytes).hexdigest()


def _stage2_manifest_input(
    *,
    stage2_manifest_path: Path | str | None,
    stage2_manifest_raw_bytes: bytes | None,
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    """Read exactly one real Stage2 manifest source and replay its closed binder."""

    path_provided = stage2_manifest_path is not None
    raw_provided = stage2_manifest_raw_bytes is not None
    _require(
        path_provided != raw_provided,
        "stage2_manifest:exactly_one_path_or_raw_source_required",
    )
    if path_provided:
        _require(
            isinstance(stage2_manifest_path, (Path, str)),
            "stage2_manifest_path:path_required",
        )
        try:
            manifest_raw = read_stable_regular_bytes(
                Path(stage2_manifest_path),
                label="stage2_manifest_path",
                max_bytes=MAX_RAW_JSON_BYTES,
            )
        except Exception as exc:
            raise DiagnosisKernelAdapterError(
                "stage2_manifest_path:stable_read_failed"
            ) from exc
        input_mode = "STABLE_REGULAR_FILE_READ"
    else:
        _require(
            type(stage2_manifest_raw_bytes) is bytes,
            "stage2_manifest_raw_bytes:bytes_required",
        )
        manifest_raw = stage2_manifest_raw_bytes
        _require(
            0 < len(manifest_raw) <= MAX_RAW_JSON_BYTES,
            "stage2_manifest_raw_bytes:size",
        )
        input_mode = "EXPLICIT_RAW_BYTES"

    manifest_payload, manifest_raw_sha256 = _strict_raw_json_object(
        manifest_raw,
        label="stage2_manifest_raw_bytes",
    )
    try:
        stage2_binding = compile_stage2_input_binding_from_raw(manifest_raw)
    except Exception as exc:
        raise DiagnosisKernelAdapterError(
            "stage2_manifest:closed_compiler_replay_failed"
        ) from exc
    stage2_lineage = {
        "input_mode": input_mode,
        "manifest_raw_sha256": manifest_raw_sha256,
        "manifest_content_sha256": _sha256(
            manifest_payload.get("content_sha256"),
            label="stage2_manifest.content_sha256",
        ),
        "derived_binding_schema_id": stage2_binding["schema_id"],
        "derived_binding_content_sha256": _sha256(
            stage2_binding["content_sha256"],
            label="stage2_binding.content_sha256",
        ),
        "target_packet_id": stage2_binding["stage2_packet"]["packet_id"],
        "target_packet_schema_id": stage2_binding["stage2_packet"]["schema_id"],
        "semantic_payload_accessed": False,
        "stage2_artifact_payload_bytes_read": 0,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return manifest_raw, stage2_binding, stage2_lineage


def _diagnosis_identity(
    *,
    session_id: str,
    source_session_content_sha256: str,
    stage2_lineage: Mapping[str, Any],
    intake: Mapping[str, Any],
    hypothesis: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    identity_core = {
        "identity_profile_id": DIAGNOSIS_IDENTITY_PROFILE_ID,
        "source_session": {
            "session_id": session_id,
            "content_sha256": source_session_content_sha256,
        },
        "stage2": {
            "manifest_raw_sha256": stage2_lineage["manifest_raw_sha256"],
            "manifest_content_sha256": stage2_lineage["manifest_content_sha256"],
            "derived_binding_content_sha256": stage2_lineage[
                "derived_binding_content_sha256"
            ],
            "packet_id": stage2_lineage["target_packet_id"],
        },
        "diagnosis_inputs": {
            "fixture_raw_sha256": intake["fixture_raw_sha256"],
            "assertion_dependency_raw_sha256": intake[
                "assertion_dependency_fixture_raw_sha256"
            ],
        },
        "target": {
            "target_identity_content_sha256": framed_sha256(
                TARGET_IDENTITY_DOMAIN,
                hypothesis["target_identity_candidate"],
            ),
            "frozen_hypothesis_content_sha256": framed_sha256(
                FROZEN_HYPOTHESIS_DOMAIN,
                hypothesis["frozen_hypothesis"],
            ),
            "hypothesis_candidate_content_sha256": hypothesis["content_sha256"],
        },
    }
    identity_content_sha256 = framed_sha256(
        DIAGNOSIS_IDENTITY_DOMAIN,
        identity_core,
    )
    identity = dict(identity_core)
    identity["diagnosis_identity_content_sha256"] = identity_content_sha256
    return f"ffdiag::{identity_content_sha256}", identity


def _native_artifacts(
    *,
    intake: Mapping[str, Any],
    hypothesis: Mapping[str, Any],
    rivals: Mapping[str, Any],
    partition: Mapping[str, Any],
    tests: Mapping[str, Any],
    layers: Mapping[str, Any],
    advisory: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        "intake": dict(intake),
        "hypothesis": dict(hypothesis),
        "rivals": dict(rivals),
        "partition": dict(partition),
        "tests": dict(tests),
        "layers": dict(layers),
        "advisory": dict(advisory),
        "terminal": dict(terminal),
    }


def _agent_projection(
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    diagnosis_id: str,
    diagnosis_identity: Mapping[str, Any],
    stage2_lineage: Mapping[str, Any],
) -> dict[str, Any]:
    hypothesis = artifacts["hypothesis"]
    rivals = artifacts["rivals"]
    partition = artifacts["partition"]
    tests = artifacts["tests"]
    layers = artifacts["layers"]
    advisory = artifacts["advisory"]
    terminal = artifacts["terminal"]

    signature_comparison = [
        {
            "dimension": row["dimension"],
            "expected": row["expected_token"],
            "observed": row["observed_synthetic_token"],
            "mismatch_candidate": row["mismatch_candidate"],
        }
        for row in hypothesis["mechanical_mismatch_vector"]
    ]
    mismatch = [row for row in signature_comparison if row["mismatch_candidate"]]
    rival_rows = [
        {
            "rival_id": row["rival_id"],
            "role": row["role"],
            "target_assertion_ids": list(row["target_assertion_ids"]),
            "target_layer_ids": list(row["target_layer_ids"]),
            "mechanism": row["mechanism_semantics"],
            "predicted_signature": dict(row["predicted_signature_candidate"]),
            "materiality_floor_candidate": row["materiality_floor_candidate"],
            "falsifier": row["falsifier_semantics"],
            "distinguishing_test_ids": list(row["distinguishing_test_ids"]),
            "knowledge_role": row["knowledge_role"],
            "evidence_use": row["evidence_use"],
            "synthetic_freeze_order_candidate_only": row[
                "synthetic_freeze_order_candidate_only"
            ],
            "formal_pre_evidence_freeze_claimed": row[
                "formal_pre_evidence_freeze_claimed"
            ],
        }
        for row in rivals["material_rivals"]
    ]
    test_rows = [
        {
            "test_id": row["test_id"],
            "question": row["discriminating_question"],
            "target_assertion_ids": list(row["target_assertion_ids"]),
            "rival_ids": list(row["rival_ids"]),
            "synthetic_input_roles": list(row["synthetic_input_roles"]),
            "statistic_semantics": row["statistic_semantics"],
            "expected_signature_by_rival": [
                dict(signature) for signature in row["expected_signature_by_rival"]
            ],
            "materiality_floor_candidate": row["materiality_floor_candidate"],
            "correction_law_candidate": row["correction_law_candidate"],
            "missing_data_disposition": row["missing_data_disposition"],
            "nonfinite_disposition": row["nonfinite_disposition"],
            "budget_charge_candidate": row["budget_charge_candidate"],
            "result_fields_structurally_absent": row[
                "result_fields_structurally_absent"
            ],
            "execution_allowed": row["execution_allowed"],
            "same_information_set_and_formation_mask_required": row[
                "same_information_set_and_formation_mask_required"
            ],
            "future_label_membership_mutation_allowed": row[
                "future_label_membership_mutation_allowed"
            ],
        }
        for row in tests["registered_tests"]
    ]
    layer_rows = [
        {
            "layer_id": row["layer_id"],
            "layer_name": row["layer_name"],
            "assessment_state_candidate": row["assessment_state_candidate"],
            "assertion_ids": list(row["assertion_ids"]),
            "material_transitive_prerequisite_assertion_ids": list(
                row["material_transitive_prerequisite_assertion_ids"]
            ),
            "global_evo_hard_gate_criteria_ids": list(
                row["global_evo_hard_gate_criteria_ids"]
            ),
            "planned_test_ids": list(row["planned_test_ids"]),
            "formal_assessment_status_present": row[
                "formal_assessment_status_present"
            ],
            "independent_clearance_receipt_present": row[
                "independent_clearance_receipt_present"
            ],
        }
        for row in layers["layer_rows"]
    ]

    def partition_projection(raw_partition: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "member_count": raw_partition["member_count"],
            "members": [
                {
                    "ordinal": row["ordinal"],
                    "member_id": row["member_id"],
                    "partition_role": row["partition_role"],
                }
                for row in raw_partition["members"]
            ],
            "mask_semantics": raw_partition["mask_semantics"],
        }

    partition_projection_row = {
        "generation_partition": partition_projection(
            partition["generation_partition"]
        ),
        "confirmation_partition": partition_projection(
            partition["confirmation_partition"]
        ),
        "intersection_member_ids": list(partition["intersection_member_ids"]),
        "synthetic_nonoverlap_candidate_pass": partition[
            "synthetic_nonoverlap_candidate_pass"
        ],
        "reservation_order_candidate": partition["reservation_order_candidate"],
        "selection_correction_candidate": partition[
            "selection_correction_candidate"
        ],
        "zero_use_scope_candidate": partition["zero_use_scope_candidate"],
        "activation_count_ceiling": partition["activation_count_ceiling"],
        "formal_reservation_receipt_present": partition[
            "formal_reservation_receipt_present"
        ],
        "formal_nonoverlap_receipt_present": partition[
            "formal_nonoverlap_receipt_present"
        ],
        "formal_zero_use_receipt_present": partition[
            "formal_zero_use_receipt_present"
        ],
        "formal_selection_correction_receipt_present": partition[
            "formal_selection_correction_receipt_present"
        ],
        "same_partition_identification_forbidden": partition[
            "same_partition_identification_forbidden"
        ],
        "identified_cause_allowed": partition["identified_cause_allowed"],
    }

    scope_rows = [
        {
            "ordinal": row["ordinal"],
            "target_assertion_id": row["target_assertion_id"],
            "target_layer_id": row["target_layer_id"],
            "scope_kind": row["scope_kind"],
            "required_prerequisite_id": row["required_prerequisite_id"],
            "required_prerequisite_layer_id": row[
                "required_prerequisite_layer_id"
            ],
            "receipt_family": row["receipt_family"],
            "receipt_key_sha256": row["receipt_key_sha256"],
            "requirement": row["requirement"],
            "receipt_selection_law": row["receipt_selection_law"],
            "latest_head_required": row["latest_head_required"],
            "independent_issuer_required": row["independent_issuer_required"],
            "required_status": row["required_status"],
            "current_receipt_present": row["current_receipt_present"],
            "same_trial_control_substitution_allowed": row[
                "same_trial_control_substitution_allowed"
            ],
        }
        for row in layers["expanded_material_scope_rows"]
    ]

    assertion_partitions = {
        partition_name: [dict(row) for row in rows]
        for partition_name, rows in layers["assertion_partition_plan"].items()
    }
    qualification_guard = {
        "current_evo_global_hard_gate_rows": [
            dict(row) for row in layers["current_evo_global_hard_gate_rows"]
        ],
        "material_assertion_dependency_dag": dict(
            layers["material_assertion_dependency_dag"]
        ),
        "material_target_assertion_count": layers[
            "material_target_assertion_count"
        ],
        "material_transitive_prerequisite_pair_count": layers[
            "material_transitive_prerequisite_pair_count"
        ],
        "global_hard_gate_requirement_count": layers[
            "global_hard_gate_requirement_count"
        ],
        "expanded_material_scope_row_count": layers[
            "expanded_material_scope_row_count"
        ],
        "expanded_material_scope_rows": scope_rows,
        "expanded_material_scope_is_exact_union_of_transitive_dag_and_global_hard_gates": layers[
            "expanded_material_scope_is_exact_union_of_transitive_dag_and_global_hard_gates"
        ],
        "missing_extra_duplicate_or_pruned_scope_disposition": layers[
            "missing_extra_duplicate_or_pruned_scope_disposition"
        ],
        "latest_receipt_selection_law": layers[
            "latest_receipt_selection_law"
        ],
        "assertion_partition_plan": assertion_partitions,
        "assertion_partition_is_exact_disjoint_union": layers[
            "assertion_partition_is_exact_disjoint_union"
        ],
        "latest_independent_assessment_receipts_present": layers[
            "latest_independent_assessment_receipts_present"
        ],
        "all_material_lower_layers_independently_cleared": layers[
            "all_material_lower_layers_independently_cleared"
        ],
        "controlled_or_localized_can_substitute_for_cleared": layers[
            "controlled_or_localized_can_substitute_for_cleared"
        ],
        "qualification_allowed": layers["qualification_allowed"],
        "identified_cause_allowed": layers["identified_cause_allowed"],
    }

    rival_registry_guard = {
        "artifact_status": rivals["artifact_status"],
        "required_role_universe": list(rivals["required_role_universe"]),
        "material_rival_count": rivals["material_rival_count"],
        "advisory_prior_count": rivals["advisory_prior_count"],
        "stage2_a0_rows_consumed": rivals["stage2_a0_rows_consumed"],
        "future_b2_phase_required_for_diagnosis_retrieval": rivals[
            "future_b2_phase_required_for_diagnosis_retrieval"
        ],
        "historical_performance_used": rivals["historical_performance_used"],
        "knowledge_prior_can_adjudicate_current_case": rivals[
            "knowledge_prior_can_adjudicate_current_case"
        ],
        "post_result_rival_addition_allowed": rivals[
            "post_result_rival_addition_allowed"
        ],
        "future_question_namespace_required_for_new_rivals": rivals[
            "future_question_namespace_required_for_new_rivals"
        ],
    }

    test_plan_guard = {
        "registered_test_count": tests["registered_test_count"],
        "applicability_row_count": tests["applicability_row_count"],
        "applicability_rows": [dict(row) for row in tests["applicability_rows"]],
        "applicability_complete": tests["applicability_complete"],
        "rival_signature_vectors": [
            dict(row) for row in tests["rival_signature_vectors"]
        ],
        "all_material_rivals_jointly_distinguishable_in_plan": tests[
            "all_material_rivals_jointly_distinguishable_in_plan"
        ],
        "trial_controls": dict(tests["trial_controls"]),
        "total_budget_charge_candidate": tests["total_budget_charge_candidate"],
        "budget_plan_feasible": tests["budget_plan_feasible"],
        "results_present": tests["results_present"],
        "execution_allowed": tests["execution_allowed"],
    }

    def lane_projection(lane: Mapping[str, Any]) -> dict[str, Any]:
        projection = {
            "disposition": lane["disposition"],
            "reason": lane["reason"],
            "candidates": [
                {
                    key: value
                    for key, value in row.items()
                    if key
                    not in {
                        "content_sha256",
                        "authority_effect",
                        "lane",
                    }
                }
                for row in lane["ordered_candidates"]
            ],
        }
        if "same_parent_hypothesis_required" in lane:
            projection["same_parent_hypothesis_required"] = lane[
                "same_parent_hypothesis_required"
            ]
        if "new_lineage_required" in lane:
            projection["new_lineage_required"] = lane["new_lineage_required"]
        return projection

    return {
        "projection_kind": "STEP4_STEP5_FAILURE_DIAGNOSIS_PLAN_ADVISORY",
        "lineage": {
            "diagnosis_id": diagnosis_id,
            "diagnosis_identity_content_sha256": diagnosis_identity[
                "diagnosis_identity_content_sha256"
            ],
            "source_session": dict(diagnosis_identity["source_session"]),
            "stage2": {
                **dict(diagnosis_identity["stage2"]),
                "input_mode": stage2_lineage["input_mode"],
                "semantic_payload_accessed": stage2_lineage[
                    "semantic_payload_accessed"
                ],
                "stage2_artifact_payload_bytes_read": stage2_lineage[
                    "stage2_artifact_payload_bytes_read"
                ],
            },
            "diagnosis_inputs": dict(diagnosis_identity["diagnosis_inputs"]),
            "target_hashes": dict(diagnosis_identity["target"]),
            "candidate_only": True,
            "authority_effect": AUTHORITY_EFFECT,
        },
        "target_identity_candidate": dict(hypothesis["target_identity_candidate"]),
        "frozen_hypothesis": dict(hypothesis["frozen_hypothesis"]),
        "signature_comparison": signature_comparison,
        "material_mismatches": mismatch,
        "material_mismatch_candidate_count": hypothesis[
            "material_mismatch_candidate_count"
        ],
        "material_rivals": rival_rows,
        "rival_registry_guard": rival_registry_guard,
        "generation_confirmation_nonoverlap_candidate": partition[
            "synthetic_nonoverlap_candidate_pass"
        ],
        "same_partition_identification_forbidden": True,
        "partition_plan": partition_projection_row,
        "distinguishing_tests": test_rows,
        "test_plan_guard": test_plan_guard,
        "layers": layer_rows,
        "qualification_guard": qualification_guard,
        "all_material_lower_layers_independently_cleared": layers[
            "all_material_lower_layers_independently_cleared"
        ],
        "controlled_or_localized_can_substitute_for_cleared": False,
        "exploit": lane_projection(advisory["exploit_lane"]),
        "explore": lane_projection(advisory["explore_lane"]),
        "future_questions": [
            {
                "question_id": row["question_id"],
                "source_kind": row["source_kind"],
                "source_candidate_id": row["source_candidate_id"],
                "question": row["question_semantics"],
                "namespace": row["namespace"],
                "current_diagnosis_or_revision_writeback_allowed": row[
                    "current_diagnosis_or_revision_writeback_allowed"
                ],
            }
            for row in advisory["future_question_namespace"]
        ],
        "advisory_guard": {
            "both_lanes_may_abstain": advisory["both_lanes_may_abstain"],
            "dummy_branch_required": advisory["dummy_branch_required"],
            "branch_selection_by_performance": advisory[
                "branch_selection_by_performance"
            ],
            "portfolio_expression_repair_allowed": advisory[
                "portfolio_expression_repair_allowed"
            ],
            "post_result_new_rival_current_use_allowed": advisory[
                "post_result_new_rival_current_use_allowed"
            ],
            "stage2_a0_cross_phase_consumption_allowed": advisory[
                "stage2_a0_cross_phase_consumption_allowed"
            ],
            "future_phase_safe_retrieval_handoff": dict(
                advisory["future_phase_safe_retrieval_handoff"]
            ),
            "dirac_eligibility_projection": dict(
                advisory["dirac_eligibility_projection"]
            ),
            "branch_selection_or_execution_allowed": advisory[
                "branch_selection_or_execution_allowed"
            ],
            "child_identity_or_handoff_allowed": advisory[
                "child_identity_or_handoff_allowed"
            ],
        },
        "terminal": {
            "disposition": terminal["planner_disposition"],
            "reasons": [
                row["reason_code"]
                for row in terminal["ordered_block_or_inconclusive_reasons"]
            ],
            "cause_identified": False,
            "review_eligible": False,
            "qualification_allowed": False,
        },
        "metric_is_not_cause": True,
        "advisory_only": True,
    }


def compile_diagnosis_kernel_candidate(
    *,
    session_id: str,
    source_session_content_sha256: str,
    fixture_raw_bytes: bytes,
    assertion_dependency_raw_bytes: bytes,
    stage2_manifest_path: Path | str | None = None,
    stage2_manifest_raw_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Compile and validate a complete Step4/Step5 diagnosis-planning candidate."""

    normalized_session_id = _session_id(session_id)
    normalized_source_session_sha256 = _sha256(
        source_session_content_sha256,
        label="source_session_content_sha256",
    )
    _, stage2_binding, stage2_lineage = _stage2_manifest_input(
        stage2_manifest_path=stage2_manifest_path,
        stage2_manifest_raw_bytes=stage2_manifest_raw_bytes,
    )
    fixture_payload, fixture_raw_sha256 = _strict_raw_json_object(
        fixture_raw_bytes,
        label="fixture_raw_bytes",
    )
    assertion_dependency_payload, assertion_dependency_raw_sha256 = (
        _strict_raw_json_object(
            assertion_dependency_raw_bytes,
            label="assertion_dependency_raw_bytes",
        )
    )
    intake = compile_synthetic_diagnosis_intake(
        fixture_payload,
        fixture_raw_sha256=fixture_raw_sha256,
        assertion_dependency_payload=assertion_dependency_payload,
        assertion_dependency_raw_sha256=assertion_dependency_raw_sha256,
    )
    hypothesis = compile_hypothesis_mismatch_candidate(intake)
    rivals = compile_material_rival_registry_candidate(intake, hypothesis)
    partition = compile_partition_independence_plan_candidate(intake, rivals)
    tests = compile_distinguishing_test_registry_candidate(intake, rivals, partition)
    layers = compile_layer_assessment_plan_candidate(intake, hypothesis, rivals, tests)
    advisory = compile_exploit_explore_dirac_advisory_candidate(
        intake, hypothesis, rivals, tests, layers
    )
    terminal = compile_planner_terminal_candidate(
        intake, hypothesis, partition, tests, layers, advisory
    )
    artifacts = _native_artifacts(
        intake=intake,
        hypothesis=hypothesis,
        rivals=rivals,
        partition=partition,
        tests=tests,
        layers=layers,
        advisory=advisory,
        terminal=terminal,
    )
    diagnosis_id, diagnosis_identity = _diagnosis_identity(
        session_id=normalized_session_id,
        source_session_content_sha256=normalized_source_session_sha256,
        stage2_lineage=stage2_lineage,
        intake=intake,
        hypothesis=hypothesis,
    )
    validate_failure_diagnosis_planner_bundle(
        stage2_binding=stage2_binding,
        intake=intake,
        hypothesis=hypothesis,
        rival_registry=rivals,
        partition_plan=partition,
        test_registry=tests,
        layer_plan=layers,
        advisory=advisory,
        terminal=terminal,
    )
    core = {
        "schema_id": ADAPTER_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "adapter_id": "S4D_NATIVE_STAGE3_WHOLE_OBJECT_LOSSLESS_ADAPTER",
        "stage_id": "S3_FAILURE_DIAGNOSIS_PLANNER",
        "session_id": normalized_session_id,
        "source_session_content_sha256": normalized_source_session_sha256,
        "diagnosis_id": diagnosis_id,
        "diagnosis_identity": diagnosis_identity,
        "stage2_lineage": stage2_lineage,
        "stage2_binding_content_sha256": stage2_binding["content_sha256"],
        "native_artifacts": artifacts,
        "agent_visible_projection": _agent_projection(
            artifacts,
            diagnosis_id=diagnosis_id,
            diagnosis_identity=diagnosis_identity,
            stage2_lineage=stage2_lineage,
        ),
        "diagnostic_tests_executed": False,
        "cause_identified": False,
        "qualification_allowed": False,
        "canonical_or_oos_accessed": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    candidate = dict(core)
    candidate["content_sha256"] = framed_sha256(ADAPTER_DOMAIN, core)
    validate_diagnosis_kernel_candidate(
        candidate,
        session_id=normalized_session_id,
        source_session_content_sha256=normalized_source_session_sha256,
        fixture_raw_bytes=fixture_raw_bytes,
        assertion_dependency_raw_bytes=assertion_dependency_raw_bytes,
        stage2_manifest_path=stage2_manifest_path,
        stage2_manifest_raw_bytes=stage2_manifest_raw_bytes,
    )
    return candidate


def validate_diagnosis_kernel_candidate(
    candidate: Mapping[str, Any],
    *,
    session_id: str,
    source_session_content_sha256: str,
    fixture_raw_bytes: bytes,
    assertion_dependency_raw_bytes: bytes,
    stage2_manifest_path: Path | str | None = None,
    stage2_manifest_raw_bytes: bytes | None = None,
) -> None:
    normalized_session_id = _session_id(session_id)
    normalized_source_session_sha256 = _sha256(
        source_session_content_sha256,
        label="source_session_content_sha256",
    )
    _, stage2_binding, expected_stage2_lineage = _stage2_manifest_input(
        stage2_manifest_path=stage2_manifest_path,
        stage2_manifest_raw_bytes=stage2_manifest_raw_bytes,
    )
    expected_fields = {
        "schema_id",
        "schema_version",
        "adapter_id",
        "stage_id",
        "session_id",
        "source_session_content_sha256",
        "diagnosis_id",
        "diagnosis_identity",
        "stage2_lineage",
        "stage2_binding_content_sha256",
        "native_artifacts",
        "agent_visible_projection",
        "diagnostic_tests_executed",
        "cause_identified",
        "qualification_allowed",
        "canonical_or_oos_accessed",
        "candidate_only",
        "signed",
        "authority_effect",
        "content_sha256",
    }
    _require(isinstance(candidate, Mapping), "candidate:object_required")
    _require(set(candidate) == expected_fields, "candidate:closed_fields")
    _require(candidate["schema_id"] == ADAPTER_SCHEMA_ID, "candidate:schema_id")
    _require(candidate["schema_version"] == SCHEMA_VERSION, "candidate:schema_version")
    _require(
        candidate["adapter_id"] == "S4D_NATIVE_STAGE3_WHOLE_OBJECT_LOSSLESS_ADAPTER",
        "candidate:adapter_id",
    )
    _require(candidate["stage_id"] == "S3_FAILURE_DIAGNOSIS_PLANNER", "candidate:stage_id")
    _require(
        candidate["session_id"] == normalized_session_id,
        "candidate:source_session_id_mismatch",
    )
    _require(
        candidate["source_session_content_sha256"]
        == normalized_source_session_sha256,
        "candidate:source_session_content_sha256_mismatch",
    )
    _require(
        candidate["stage2_lineage"] == expected_stage2_lineage,
        "candidate:stage2_lineage_mismatch",
    )
    _require(
        candidate["stage2_binding_content_sha256"] == stage2_binding["content_sha256"],
        "candidate:stage2_binding_mismatch",
    )
    artifacts = candidate["native_artifacts"]
    _require(isinstance(artifacts, Mapping), "candidate.native_artifacts:object_required")
    _require(
        set(artifacts)
        == {"intake", "hypothesis", "rivals", "partition", "tests", "layers", "advisory", "terminal"},
        "candidate.native_artifacts:closed_fields",
    )
    fixture_payload, fixture_raw_sha256 = _strict_raw_json_object(
        fixture_raw_bytes,
        label="fixture_raw_bytes",
    )
    assertion_dependency_payload, assertion_dependency_raw_sha256 = (
        _strict_raw_json_object(
            assertion_dependency_raw_bytes,
            label="assertion_dependency_raw_bytes",
        )
    )
    expected_intake = compile_synthetic_diagnosis_intake(
        fixture_payload,
        fixture_raw_sha256=fixture_raw_sha256,
        assertion_dependency_payload=assertion_dependency_payload,
        assertion_dependency_raw_sha256=assertion_dependency_raw_sha256,
    )
    _require(
        artifacts["intake"] == expected_intake,
        "candidate:intake_replay_mismatch",
    )
    validate_failure_diagnosis_planner_bundle(
        stage2_binding=stage2_binding,
        intake=artifacts["intake"],
        hypothesis=artifacts["hypothesis"],
        rival_registry=artifacts["rivals"],
        partition_plan=artifacts["partition"],
        test_registry=artifacts["tests"],
        layer_plan=artifacts["layers"],
        advisory=artifacts["advisory"],
        terminal=artifacts["terminal"],
    )
    expected_diagnosis_id, expected_diagnosis_identity = _diagnosis_identity(
        session_id=normalized_session_id,
        source_session_content_sha256=normalized_source_session_sha256,
        stage2_lineage=expected_stage2_lineage,
        intake=artifacts["intake"],
        hypothesis=artifacts["hypothesis"],
    )
    _require(
        candidate["diagnosis_id"] == expected_diagnosis_id,
        "candidate:diagnosis_id_mismatch",
    )
    _require(
        candidate["diagnosis_identity"] == expected_diagnosis_identity,
        "candidate:diagnosis_identity_mismatch",
    )
    _require(
        candidate["agent_visible_projection"]
        == _agent_projection(
            artifacts,
            diagnosis_id=expected_diagnosis_id,
            diagnosis_identity=expected_diagnosis_identity,
            stage2_lineage=expected_stage2_lineage,
        ),
        "candidate:agent_projection_mismatch",
    )
    for field in (
        "diagnostic_tests_executed",
        "cause_identified",
        "qualification_allowed",
        "canonical_or_oos_accessed",
        "signed",
    ):
        _require(candidate[field] is False, f"candidate:{field}")
    _require(candidate["candidate_only"] is True, "candidate:candidate_only")
    _require(candidate["authority_effect"] == AUTHORITY_EFFECT, "candidate:authority_effect")
    core = {key: value for key, value in candidate.items() if key != "content_sha256"}
    _require(
        candidate["content_sha256"] == framed_sha256(ADAPTER_DOMAIN, core),
        "candidate:content_sha256",
    )


__all__ = [
    "ADAPTER_SCHEMA_ID",
    "DiagnosisKernelAdapterError",
    "compile_diagnosis_kernel_candidate",
    "validate_diagnosis_kernel_candidate",
]
