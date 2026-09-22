from __future__ import annotations

"""Executable offline composition of Source-First, retrieval, and diagnosis kernels."""

from collections.abc import Mapping, Sequence
from typing import Any

from factor_factory.epistemic_diagnosis_kernel_adapter_offline import (
    compile_diagnosis_kernel_candidate,
)
from factor_factory.epistemic_retrieval_kernel_adapter_offline import (
    A0,
    retrieve_real_knowledge_advisory,
    run_epistemic_retrieval_kernel_adapter_offline,
    validate_epistemic_retrieval_kernel_adapter_result,
)
from factor_factory.epistemic_source_first_kernel_adapter_offline import (
    compile_source_first_kernel_session_candidate,
    validate_source_first_kernel_session_candidate,
)
from factor_factory.research_org.rfc8785_canonical import framed_sha256


SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = "factorforge_epistemic_kernel_composition_offline_candidate_v1"
CONTENT_DOMAIN = "FF_EPISTEMIC_KERNEL_COMPOSITION_OFFLINE_CANDIDATE_V1"
SESSION_ID_DOMAIN = "FF_EPISTEMIC_KERNEL_COMPOSITION_SESSION_ID_V1"
AUTHORITY_EFFECT = "NONE"

SOURCE_INPUT_FIELDS = {
    "source_bytes",
    "source_lineage",
    "author_claims",
    "analyst_notes",
    "selected_semantic_body",
    "formalization_provenance",
    "pre_a0_predictions",
    "phase_policy_candidate",
}
DIAGNOSIS_PATH_INPUT_FIELDS = {
    "stage2_manifest_path",
    "fixture_raw_bytes",
    "assertion_dependency_raw_bytes",
}
DIAGNOSIS_RAW_INPUT_FIELDS = {
    "stage2_manifest_raw_bytes",
    "fixture_raw_bytes",
    "assertion_dependency_raw_bytes",
}
REAL_KNOWLEDGE_FIELDS = {
    "node_index_path",
    "edge_index_path",
    "taxonomy_path",
    "top_k_per_lane",
}
ROOT_FIELDS = {
    "schema_id",
    "schema_version",
    "artifact_status",
    "session_id",
    "source_session_id",
    "stage_output_bindings",
    "stage_outputs",
    "chief_research_advisory",
    "lineage_guards",
    "replay_scope",
    "execution_summary",
    "candidate_only",
    "signed",
    "authority_effect",
    "content_sha256",
}


class EpistemicKernelCompositionError(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise EpistemicKernelCompositionError(reason)


def _closed(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label}:object_required")
    _require(set(value) == fields, f"{label}:closed_fields")
    return value


def _closed_diagnosis_inputs(value: Any) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), "diagnosis_inputs:object_required")
    fields = frozenset(value)
    _require(
        fields in {frozenset(DIAGNOSIS_PATH_INPUT_FIELDS), frozenset(DIAGNOSIS_RAW_INPUT_FIELDS)},
        "diagnosis_inputs:closed_path_or_raw_fields",
    )
    return value


def _plain_a0_request(source_first: Mapping[str, Any]) -> dict[str, Any] | None:
    artifact = source_first["artifacts"]["a0_request_candidate"]
    private = artifact["private_preissuance_request_candidate"]
    if private is None:
        return None
    typed_query = private["query_semantics_candidate"]
    phase_input = {
        field: [row["semantic_text"] for row in rows]
        for field, rows in typed_query.items()
    }
    source_policy = private["phase_policy_candidate"]
    return {
        "phase_branch": A0,
        "phase_input": phase_input,
        "phase_policy": {
            "policy_version": "phase-safe-offline-candidate-v1",
            "phase_branch": A0,
            "requested_lane_subset": list(source_policy["requested_lane_subset"]),
            "top_k_per_lane": source_policy["top_k_per_lane"],
        },
        "source_first_binding_content_sha256": source_first["content_sha256"],
        "hypothesis_freeze_content_sha256": None,
    }


def _group_retrieval_precedents(
    retrieval_lanes: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Represent each precedent once and keep lane membership as a role."""

    groups_by_handle: dict[str, dict[str, Any]] = {}
    ordered_groups: list[dict[str, Any]] = []
    assignments_by_lane: dict[str, list[dict[str, Any]]] = {}
    for lane_row in retrieval_lanes:
        lane = str(lane_row["lane"])
        _require(lane not in assignments_by_lane, "chief_advisory:duplicate_lane")
        assignments_by_lane[lane] = []
        for raw_item in lane_row["items"]:
            item = dict(raw_item)
            group_handle = str(item.pop("precedent_group_handle"))
            lane_handle = str(item.pop("handle"))
            eligible_lanes = list(item.pop("eligible_lanes"))
            lane_role_rationale = list(item.pop("lane_role_rationale"))
            assignment = {
                "precedent_group_handle": group_handle,
                "lane_handle": lane_handle,
                "lane_role_rationale": lane_role_rationale,
            }
            group = groups_by_handle.get(group_handle)
            if group is None:
                group = {
                    "precedent_group_handle": group_handle,
                    "eligible_lanes": eligible_lanes,
                    "advisory_payload": item,
                    "lane_assignments": [],
                }
                groups_by_handle[group_handle] = group
                ordered_groups.append(group)
            else:
                _require(
                    group["eligible_lanes"] == eligible_lanes,
                    "chief_advisory:group_eligible_lanes_mismatch",
                )
                _require(
                    group["advisory_payload"] == item,
                    "chief_advisory:group_payload_mismatch",
                )
            _require(
                lane in eligible_lanes,
                "chief_advisory:assigned_lane_not_eligible",
            )
            _require(
                all(row["lane"] != lane for row in group["lane_assignments"]),
                "chief_advisory:duplicate_group_lane_assignment",
            )
            group["lane_assignments"].append({"lane": lane, **assignment})
            assignments_by_lane[lane].append(assignment)

    lane_assignments = [
        {"lane": lane, "assignments": assignments}
        for lane, assignments in assignments_by_lane.items()
    ]
    return ordered_groups, lane_assignments


def _assignments_for_lane(
    lane_assignments: Sequence[Mapping[str, Any]], lane: str
) -> list[dict[str, Any]]:
    for row in lane_assignments:
        if row["lane"] == lane:
            return [dict(item) for item in row["assignments"]]
    return []


def _challenge_group_assignments(
    lane_assignments: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    for lane in ("near_miss_failure", "direct_counterexample"):
        for assignment in _assignments_for_lane(lane_assignments, lane):
            group_handle = assignment["precedent_group_handle"]
            group = grouped.get(group_handle)
            if group is None:
                group = {
                    "precedent_group_handle": group_handle,
                    "challenge_roles": [],
                }
                grouped[group_handle] = group
                ordered.append(group)
            group["challenge_roles"].append(
                {
                    "lane": lane,
                    "lane_handle": assignment["lane_handle"],
                    "lane_role_rationale": assignment["lane_role_rationale"],
                }
            )
    return ordered


def _chief_advisory(
    *,
    source_first: Mapping[str, Any],
    retrieval: Mapping[str, Any] | None,
    diagnosis: Mapping[str, Any] | None,
) -> dict[str, Any]:
    artifacts = source_first["artifacts"]
    understanding = artifacts["source_understanding"]
    formalization = artifacts["source_faithful_formalization"]
    seed = artifacts["blind_mechanism_seed"]
    formalization_body = formalization["formalization_body"]
    source_claims = [
        {
            "statement_id": row["statement_id"],
            "classification": row["classification"],
            "text": row["text"],
        }
        for row in understanding["semantic_statements"]
    ]
    retrieval_projection = (
        None if retrieval is None else retrieval["agent_visible_projection"]
    )
    retrieval_lanes = (
        [] if retrieval_projection is None else list(retrieval_projection["lanes"])
    )
    precedent_groups, lane_assignments = _group_retrieval_precedents(
        retrieval_lanes
    )
    if formalization_body["disposition"] != "FORMALIZED":
        next_step = "CLARIFY_SOURCE"
    elif retrieval is None:
        next_step = "STEP1_A0_RETRIEVAL_OR_EXPLICIT_COLD_START"
    else:
        next_step = (
            "STEP1_POST_A0_MODEL_DIVERSIFICATION_AND_MEASUREMENT_PROGRAM"
        )
    return {
        "advisory_kind": "FACTOR_FORGE_STEP1_RESEARCH_BRAIN_SIDECAR",
        "source_first": {
            "source_claims": source_claims,
            "novel_concepts_not_yet_mapped": list(
                understanding["novel_concepts_not_yet_mapped"]
            ),
            "internal_tensions": list(understanding["internal_tensions"]),
            "formalization_disposition": formalization_body["disposition"],
            "formalization": dict(formalization_body),
            "formalization_provenance": dict(
                source_first["formalization_provenance"]
            ),
            "blind_seed": dict(seed["seed_body"]),
        },
        "knowledge_priors": {
            "result": (
                "NOT_REQUESTED"
                if retrieval_projection is None
                else retrieval_projection["result"]
            ),
            "precedent_groups": precedent_groups,
            "lane_assignments": lane_assignments,
            "unique_precedent_group_count": len(precedent_groups),
            "may_supplement_source_understanding": True,
            "may_rewrite_source_understanding_or_blind_seed": False,
            "may_select_model_by_historical_performance": False,
        },
        "exploit_and_explore": {
            "exploit_candidates": _assignments_for_lane(
                lane_assignments, "structural_isomorph"
            ),
            "explore_candidates": _assignments_for_lane(
                lane_assignments, "cross_math_analogy"
            ),
            "challenge_candidates": _challenge_group_assignments(
                lane_assignments
            ),
            "selection_status": (
                "ADVISORY_ONLY__AGENT_MUST_DERIVE_AND_COMPARE_MODELS"
            ),
            "zero_candidate_or_abstention_allowed": True,
            "dummy_branch_required": False,
        },
        "failure_diagnosis": (
            None if diagnosis is None else diagnosis["agent_visible_projection"]
        ),
        "next_step": next_step,
        "advisory_only": True,
    }


def _compile(
    *,
    source_inputs: Mapping[str, Any],
    retrieval_corpus_objects: Sequence[Mapping[str, Any]] | None,
    real_knowledge_inputs: Mapping[str, Any] | None,
    session_scope_secret: bytes | None,
    diagnosis_inputs: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source = _closed(source_inputs, SOURCE_INPUT_FIELDS, "source_inputs")
    source_first = compile_source_first_kernel_session_candidate(**source)
    retrieval_request = _plain_a0_request(source_first)
    if retrieval_request is None:
        _require(
            retrieval_corpus_objects is None
            and real_knowledge_inputs is None
            and session_scope_secret is None,
            "retrieval:forbidden_without_eligible_a0_seed",
        )
        retrieval = None
    else:
        _require(
            not (retrieval_corpus_objects is not None and real_knowledge_inputs is not None),
            "retrieval:synthetic_and_real_modes_are_mutually_exclusive",
        )
        if retrieval_corpus_objects is None and real_knowledge_inputs is None:
            _require(session_scope_secret is None, "retrieval:secret_without_retrieval")
            retrieval = None
        else:
            _require(
                isinstance(session_scope_secret, bytes),
                "session_scope_secret:bytes_required",
            )
            if real_knowledge_inputs is not None:
                real = _closed(
                    real_knowledge_inputs,
                    REAL_KNOWLEDGE_FIELDS,
                    "real_knowledge_inputs",
                )
                retrieval = retrieve_real_knowledge_advisory(
                    source_first_candidate=source_first,
                    source_inputs=source,
                    phase_branch=A0,
                    top_k_per_lane=real["top_k_per_lane"],
                    node_index_path=real["node_index_path"],
                    edge_index_path=real["edge_index_path"],
                    taxonomy_path=real["taxonomy_path"],
                    session_scope_secret=session_scope_secret,
                )
            else:
                _require(
                    isinstance(retrieval_corpus_objects, Sequence)
                    and not isinstance(
                        retrieval_corpus_objects, (str, bytes, bytearray)
                    ),
                    "retrieval_corpus_objects:array_required",
                )
                retrieval = run_epistemic_retrieval_kernel_adapter_offline(
                    source_first_candidate=source_first,
                    source_inputs=source,
                    corpus_objects=retrieval_corpus_objects,
                    session_scope_secret=session_scope_secret,
                )

    diagnosis = None
    if diagnosis_inputs is not None:
        inputs = _closed_diagnosis_inputs(diagnosis_inputs)
        diagnosis = compile_diagnosis_kernel_candidate(
            session_id=source_first["session_envelope"]["session_id"],
            source_session_content_sha256=source_first["content_sha256"],
            **inputs,
        )

    stage_outputs = {
        "source_first": source_first,
        "retrieval": retrieval,
        "diagnosis": diagnosis,
    }
    source_session_id = source_first["session_envelope"]["session_id"]
    stage_output_bindings = {
        "source_first_content_sha256": source_first["content_sha256"],
        "retrieval_content_sha256": (
            None if retrieval is None else retrieval["content_sha256"]
        ),
        "diagnosis_content_sha256": (
            None if diagnosis is None else diagnosis["content_sha256"]
        ),
    }
    session_id = "candidate_ekc_" + framed_sha256(
        SESSION_ID_DOMAIN,
        {
            "source_session_id": source_session_id,
            "stage_output_bindings": stage_output_bindings,
        },
    )[:32]
    core = {
        "schema_id": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "RUNNABLE_OFFLINE_CANDIDATE__NOT_PRODUCTION_ACTIVATED",
        "session_id": session_id,
        "source_session_id": source_session_id,
        "stage_output_bindings": stage_output_bindings,
        "stage_outputs": stage_outputs,
        "chief_research_advisory": _chief_advisory(
            source_first=source_first,
            retrieval=retrieval,
            diagnosis=diagnosis,
        ),
        "lineage_guards": {
            "source_understanding_precedes_knowledge": True,
            "blind_seed_precedes_a0_retrieval": True,
            "retrieval_cannot_rewrite_current_source_or_seed": True,
            "diagnosis_new_explanations_are_future_question_only": True,
            "lower_layer_control_or_localization_substitutes_for_cleared": False,
            "composition_session_binds_all_stage_outputs": True,
        },
        "replay_scope": {
            "status": "PUBLISHER_TIME_FULL_REPLAY_VALIDATED__NON_SELF_CONTAINED",
            "standalone_replay_from_delivery_only_supported": False,
            "original_external_inputs_required": True,
            "source_input_names": sorted(SOURCE_INPUT_FIELDS),
            "retrieval_external_input_mode": (
                "NONE"
                if retrieval is None
                else (
                    "REAL_GRAPH_AND_SOURCE_NODE_BYTES_PLUS_SESSION_SECRET"
                    if real_knowledge_inputs is not None
                    else "SYNTHETIC_CORPUS_PLUS_SESSION_SECRET"
                )
            ),
            "diagnosis_external_input_mode": (
                "NONE"
                if diagnosis is None
                else "STAGE2_MANIFEST_FIXTURE_AND_ASSERTION_DAG_BYTES"
            ),
            "external_dependency_bytes_embedded_for_standalone_replay": False,
            "session_scope_secret_persisted": False,
            "candidate_only": True,
            "authority_effect": AUTHORITY_EFFECT,
        },
        "execution_summary": {
            "source_first_executed": True,
            "retrieval_executed": retrieval is not None,
            "diagnosis_planner_executed": diagnosis is not None,
            "diagnostic_tests_executed": False,
            "network_or_ambient_discovery_performed": False,
            "canonical_write_performed": False,
            "oos_access_performed": False,
            "production_activation_performed": False,
        },
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    result = dict(core)
    result["content_sha256"] = framed_sha256(CONTENT_DOMAIN, core)
    return result


def compose_epistemic_kernel_candidate(
    *,
    source_inputs: Mapping[str, Any],
    retrieval_corpus_objects: Sequence[Mapping[str, Any]] | None = None,
    real_knowledge_inputs: Mapping[str, Any] | None = None,
    session_scope_secret: bytes | None = None,
    diagnosis_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the candidate research brain from explicit, in-memory inputs."""

    result = _compile(
        source_inputs=source_inputs,
        retrieval_corpus_objects=retrieval_corpus_objects,
        real_knowledge_inputs=real_knowledge_inputs,
        session_scope_secret=session_scope_secret,
        diagnosis_inputs=diagnosis_inputs,
    )
    validate_epistemic_kernel_composition(
        result,
        source_inputs=source_inputs,
        retrieval_corpus_objects=retrieval_corpus_objects,
        real_knowledge_inputs=real_knowledge_inputs,
        session_scope_secret=session_scope_secret,
        diagnosis_inputs=diagnosis_inputs,
    )
    return result


def validate_epistemic_kernel_composition(
    candidate: Mapping[str, Any],
    *,
    source_inputs: Mapping[str, Any],
    retrieval_corpus_objects: Sequence[Mapping[str, Any]] | None = None,
    real_knowledge_inputs: Mapping[str, Any] | None = None,
    session_scope_secret: bytes | None = None,
    diagnosis_inputs: Mapping[str, Any] | None = None,
) -> None:
    root = _closed(candidate, ROOT_FIELDS, "composition")
    _require(root["schema_id"] == SCHEMA_ID, "composition:schema_id")
    _require(root["schema_version"] == SCHEMA_VERSION, "composition:schema_version")
    _require(root["candidate_only"] is True, "composition:candidate_only")
    _require(root["signed"] is False, "composition:signed")
    _require(root["authority_effect"] == AUTHORITY_EFFECT, "composition:authority_effect")
    core = {key: value for key, value in root.items() if key != "content_sha256"}
    _require(
        root["content_sha256"] == framed_sha256(CONTENT_DOMAIN, core),
        "composition:content_sha256",
    )
    expected = _compile(
        source_inputs=source_inputs,
        retrieval_corpus_objects=retrieval_corpus_objects,
        real_knowledge_inputs=real_knowledge_inputs,
        session_scope_secret=session_scope_secret,
        diagnosis_inputs=diagnosis_inputs,
    )
    _require(dict(root) == expected, "composition:full_replay_equality")
    validate_source_first_kernel_session_candidate(
        root["stage_outputs"]["source_first"], **source_inputs
    )
    retrieval = root["stage_outputs"]["retrieval"]
    if retrieval is not None:
        _require(
            isinstance(session_scope_secret, bytes),
            "composition:retrieval_secret_required_for_full_replay",
        )
        if real_knowledge_inputs is None:
            _require(
                retrieval_corpus_objects is not None,
                "composition:synthetic_corpus_required_for_full_replay",
            )
            validate_epistemic_retrieval_kernel_adapter_result(
                retrieval,
                source_first_candidate=root["stage_outputs"]["source_first"],
                source_inputs=source_inputs,
                session_scope_secret=session_scope_secret,
                corpus_objects=retrieval_corpus_objects,
            )
        else:
            validate_epistemic_retrieval_kernel_adapter_result(
                retrieval,
                source_first_candidate=root["stage_outputs"]["source_first"],
                source_inputs=source_inputs,
                session_scope_secret=session_scope_secret,
                top_k_per_lane=real_knowledge_inputs["top_k_per_lane"],
                node_index_path=real_knowledge_inputs["node_index_path"],
                edge_index_path=real_knowledge_inputs["edge_index_path"],
                taxonomy_path=real_knowledge_inputs["taxonomy_path"],
            )


__all__ = [
    "EpistemicKernelCompositionError",
    "compose_epistemic_kernel_candidate",
    "validate_epistemic_kernel_composition",
]
