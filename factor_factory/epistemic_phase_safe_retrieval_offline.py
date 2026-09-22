from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from factor_factory.epistemic_binding import (
    _atomic_publish_directory_noreplace_at,
    _entry_exists_at,
    _open_absolute_directory_fd,
)
from factor_factory.epistemic_host_bootstrap_b0b import (
    _create_staging_directory,
    _stable_file_row,
    _validate_staging_closure,
)
from factor_factory.epistemic_source_first_offline import (
    read_stable_regular_bytes,
    validate_source_first_offline_candidate_packet,
)
from factor_factory.research_org.contracts import strict_json_loads, write_workspace_json_once
from factor_factory.research_org.rfc8785_canonical import framed_sha256


SCHEMA_VERSION = "1.0.0"
AUTHORITY_EFFECT = "NONE"
MAX_JSON_BYTES = 16 * 1024 * 1024

STAGE1_BINDING_SCHEMA_ID = "factorforge_detached_stage1_prototype_input_binding_v1"
CORPUS_SCHEMA_ID = "factorforge_phase_safe_offline_corpus_candidate_v1"
PROGRAM_SCHEMA_ID = "factorforge_phase_safe_offline_retrieval_program_v1"
SCORE_SCHEMA_ID = "factorforge_phase_safe_offline_score_ledger_v1"
SELECTION_SCHEMA_ID = "factorforge_phase_safe_offline_selection_ledger_v1"
REJECTION_SCHEMA_ID = "factorforge_phase_safe_offline_rejection_zero_hit_ledger_v1"
REPORT_SCHEMA_ID = "factorforge_phase_safe_offline_replay_report_v1"
PACKET_SCHEMA_ID = "factorforge_phase_safe_offline_candidate_packet_v1"

STAGE1_BINDING_DOMAIN = "FF_PHASE_SAFE_OFFLINE_STAGE1_INPUT_BINDING_V1"
CORPUS_OBJECT_ID_DOMAIN = "FF_PHASE_SAFE_OFFLINE_CORPUS_OBJECT_ID_V1"
CORPUS_PAYLOAD_DOMAIN = "FF_PHASE_SAFE_OFFLINE_CORPUS_PAYLOAD_V1"
CORPUS_OBJECT_DOMAIN = "FF_PHASE_SAFE_OFFLINE_CORPUS_OBJECT_V1"
CORPUS_COMMITMENT_DOMAIN = "FF_PHASE_SAFE_OFFLINE_CORPUS_COMMITMENT_V1"
CORPUS_DOMAIN = "FF_PHASE_SAFE_OFFLINE_CORPUS_V1"
PHASE_POLICY_DOMAIN = "FF_PHASE_SAFE_OFFLINE_PHASE_POLICY_V1"
PHASE_QUERY_DOMAIN = "FF_PHASE_SAFE_OFFLINE_PHASE_QUERY_V1"
REQUEST_DOMAIN = "FF_PHASE_SAFE_OFFLINE_REQUEST_CANDIDATE_V1"
PHASE_PROJECTION_DOMAIN = "FF_PHASE_SAFE_OFFLINE_PHASE_PROJECTION_V1"
PROGRAM_PROFILE_DOMAIN = "FF_PHASE_SAFE_OFFLINE_PROGRAM_PROFILE_V1"
PROGRAM_DOMAIN = "FF_PHASE_SAFE_OFFLINE_PROGRAM_V1"
SCORE_ROW_DOMAIN = "FF_PHASE_SAFE_OFFLINE_SCORE_ROW_V1"
SCORE_LEDGER_DOMAIN = "FF_PHASE_SAFE_OFFLINE_SCORE_LEDGER_V1"
SELECTION_ROW_DOMAIN = "FF_PHASE_SAFE_OFFLINE_SELECTION_ROW_V1"
SELECTION_DOMAIN = "FF_PHASE_SAFE_OFFLINE_SELECTION_LEDGER_V1"
REJECTION_ROW_DOMAIN = "FF_PHASE_SAFE_OFFLINE_REJECTION_ROW_V1"
LANE_TERMINAL_DOMAIN = "FF_PHASE_SAFE_OFFLINE_LANE_TERMINAL_V1"
REJECTION_DOMAIN = "FF_PHASE_SAFE_OFFLINE_REJECTION_ZERO_HIT_LEDGER_V1"
REPORT_DOMAIN = "FF_PHASE_SAFE_OFFLINE_REPLAY_REPORT_V1"
PACKET_ARTIFACT_DOMAIN = "FF_PHASE_SAFE_OFFLINE_PACKET_ARTIFACT_MANIFEST_V1"
PACKET_DOMAIN = "FF_PHASE_SAFE_OFFLINE_CANDIDATE_PACKET_V1"

PHASE_BRANCHES = (
    "A0_MECHANISM_PRIOR",
    "A1_IMPLEMENTATION_FEASIBILITY",
    "B1_PREDICTION_CHALLENGE",
    "B2_POSTRESULT_PLAN_SUPPORT",
    "B2_PREMETRIC_FUTURE_QUESTION_ONLY",
)
LANES = (
    "structural_isomorph",
    "cross_math_analogy",
    "near_miss_failure",
    "direct_counterexample",
    "historical_episode_context",
)
FOUR_LANES = LANES[:4]

COMMON_QUERY_FIELDS = {
    "economic_game_semantics",
    "latent_mechanism_semantics",
    "mathematical_family_semantics",
    "falsifier_semantics",
}
PHASE_QUERY_FIELDS: dict[str, set[str]] = {
    "A0_MECHANISM_PRIOR": set(COMMON_QUERY_FIELDS),
    "A1_IMPLEMENTATION_FEASIBILITY": {
        *COMMON_QUERY_FIELDS,
        "implementation_feasibility_semantics",
        "operator_requirement_semantics",
        "observation_and_data_semantics",
        "numerical_constraint_semantics",
        "testability_semantics",
    },
    "B1_PREDICTION_CHALLENGE": {
        *COMMON_QUERY_FIELDS,
        "challenge_question_semantics",
        "preferred_alternative_null_semantics",
        "frozen_prediction_semantics",
        "distinguishing_test_semantics",
        "assumption_boundary_semantics",
    },
    "B2_POSTRESULT_PLAN_SUPPORT": {
        *COMMON_QUERY_FIELDS,
        "observation_semantics",
        "mismatch_semantics",
        "candidate_broken_assertion_semantics",
        "implementation_need_semantics",
        "registered_test_intent_semantics",
    },
    "B2_PREMETRIC_FUTURE_QUESTION_ONLY": {
        *COMMON_QUERY_FIELDS,
        "finalized_mismatch_semantics",
        "failure_layer_semantics",
        "what_survived_semantics",
        "what_failed_semantics",
        "diagnosis_boundary_semantics",
    },
}
CORPUS_ONLY_FIELDS = {
    "applicability_boundary_semantics",
    "information_preserved_semantics",
    "information_lost_semantics",
    "advisory_semantics",
}
PHASE_CORPUS_FIELDS: dict[str, set[str]] = {
    phase: {*fields, *CORPUS_ONLY_FIELDS}
    for phase, fields in PHASE_QUERY_FIELDS.items()
}
PHASE_CORPUS_FIELDS["B2_PREMETRIC_FUTURE_QUESTION_ONLY"].add(
    "historical_episode_annotation_semantics"
)

PHASE_ALLOWED_LANES = {
    "A0_MECHANISM_PRIOR": FOUR_LANES,
    "A1_IMPLEMENTATION_FEASIBILITY": FOUR_LANES,
    "B1_PREDICTION_CHALLENGE": FOUR_LANES,
    "B2_POSTRESULT_PLAN_SUPPORT": LANES,
    "B2_PREMETRIC_FUTURE_QUESTION_ONLY": LANES,
}

ADMISSIBLE_CLASS = "SYNTHETIC_ADMISSIBLE_CANDIDATE"
QUARANTINED_CLASS = "QUARANTINED_REJECTED_CANDIDATE"
CORPUS_CLASSES = {ADMISSIBLE_CLASS, QUARANTINED_CLASS}

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
URI_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]{1,15}://")
ABSOLUTE_PATH_RE = re.compile(r"(?:^|\s)(?:/[^\s]+|~/[^\s]+|[A-Za-z]:\\[^\s]+)")
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
DIGEST_RE = re.compile(r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})(?![0-9a-fA-F])")
STABLE_NAMESPACE_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_-]{1,31}::")
DATE_RE = re.compile(r"\b(?:19|20)\d{2}[-/]\d{1,2}(?:[-/]\d{1,2})?\b")
TICKER_RE = re.compile(r"\b\d{6}\.(?:SZ|SH|BJ)|\b[A-Z]{1,6}\.(?:O|N|HK)\b")
FORBIDDEN_RANK_TEXT_RE = re.compile(
    r"\b(?:sharpe|nav|pnl|oos|ic|return|returns|turnover|information coefficient|backtest return|"
    r"promotion|admission|accepted factor|rejected factor|index health|"
    r"index count|index size|cache hit|bull market|bear market|regime label|event label)\b|"
    r"夏普|净值|历史收益|收益率|换手率|信息系数|回测收益|样本外收益|正式晋升|正式录用|索引健康|索引数量|"
    r"牛市标签|熊市标签|事件标签|状态标签",
    re.IGNORECASE,
)
FORBIDDEN_CURRENT_WRITEBACK_RE = re.compile(
    r"\b(?:revise|rewrite|change|overwrite|write\s*back)\s+(?:the\s+)?current\s+"
    r"(?:diagnosis|qualification|revision|decision|result)\b|"
    r"回填当前诊断|修改当前诊断|改写当前诊断|改变当前资格|修改当前资格|"
    r"回填当前修订|修改当前修订|改写当前结论|覆盖当前结论",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")


class PhaseSafeRetrievalOfflineError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = tuple(str(reason) for reason in reasons)
        super().__init__(";".join(self.reasons))


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise PhaseSafeRetrievalOfflineError([label])


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise PhaseSafeRetrievalOfflineError(
            [f"{label}:expected={expected!r}:actual={actual!r}"]
        )


def _closed_mapping(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label}:object_required")
    _require_equal(set(value), expected, f"{label}:closed_fields")
    return value


def _array(value: Any, label: str) -> Sequence[Any]:
    _require(
        isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)),
        f"{label}:array_required",
    )
    return value


def _text(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{label}:nonempty_text")
    result = unicodedata.normalize("NFKC", value.strip())
    _require("\x00" not in result, f"{label}:nul_forbidden")
    _require(len(result.encode("utf-8")) <= 4096, f"{label}:too_large")
    _require(URI_RE.search(result) is None, f"{label}:uri_forbidden")
    _require(ABSOLUTE_PATH_RE.search(result) is None, f"{label}:absolute_path_forbidden")
    _require(UUID_RE.search(result) is None, f"{label}:uuid_forbidden")
    _require(DIGEST_RE.search(result) is None, f"{label}:digest_forbidden")
    _require(STABLE_NAMESPACE_RE.search(result) is None, f"{label}:stable_namespace_forbidden")
    _require(DATE_RE.search(result) is None, f"{label}:date_identity_forbidden")
    _require(TICKER_RE.search(result) is None, f"{label}:asset_identity_forbidden")
    _require(FORBIDDEN_RANK_TEXT_RE.search(result) is None, f"{label}:rank_feature_forbidden")
    _require(
        FORBIDDEN_CURRENT_WRITEBACK_RE.search(result) is None,
        f"{label}:current_writeback_instruction_forbidden",
    )
    return result


def _safe_reason(value: Any, label: str) -> str:
    result = _text(value, label)
    _require(re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", result) is not None, f"{label}:reason_token")
    return result


def _with_content_sha(payload: Mapping[str, Any], *, domain: str) -> dict[str, Any]:
    _require("content_sha256" not in payload, f"{domain}:content_sha_already_present")
    result = dict(payload)
    result["content_sha256"] = framed_sha256(domain, result)
    return result


def _verify_content(payload: Mapping[str, Any], *, domain: str, label: str) -> None:
    core = dict(payload)
    actual = core.pop("content_sha256", None)
    _require(isinstance(actual, str) and SHA256_RE.fullmatch(actual) is not None, f"{label}:content_sha256")
    _require_equal(actual, framed_sha256(domain, core), f"{label}:content_sha256")


def _semantic_atoms(value: Any, field: str, label: str, *, min_items: int = 0) -> list[dict[str, str]]:
    values = _array(value, label)
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    atom_kind = field.removesuffix("_semantics").upper()
    for index, item in enumerate(values):
        text = _text(item, f"{label}[{index}]")
        _require(text not in seen, f"{label}:duplicate")
        seen.add(text)
        output.append({"atom_kind": atom_kind, "semantic_text": text})
    _require(len(output) >= min_items, f"{label}:min_items={min_items}")
    return output


def _validate_atom_mapping(
    payload: Mapping[str, Any], *, expected_fields: set[str], label: str
) -> None:
    _closed_mapping(payload, expected_fields, label)
    nonempty = 0
    for field in sorted(expected_fields):
        rows = _array(payload[field], f"{label}.{field}")
        seen: set[str] = set()
        for ordinal, row in enumerate(rows):
            atom = _closed_mapping(
                row,
                {"atom_kind", "semantic_text"},
                f"{label}.{field}[{ordinal}]",
            )
            _require(isinstance(atom["atom_kind"], str) and bool(atom["atom_kind"]), f"{label}.{field}:atom_kind")
            text = _text(atom["semantic_text"], f"{label}.{field}[{ordinal}].semantic_text")
            _require(text not in seen, f"{label}.{field}:duplicate")
            seen.add(text)
        nonempty += int(bool(rows))
    _require(nonempty > 0, f"{label}:all_semantics_empty")


def _normalize_semantic_payload(
    raw_payload: Mapping[str, Any], *, phase_branch: str, label: str
) -> dict[str, list[dict[str, str]]]:
    expected = PHASE_CORPUS_FIELDS[phase_branch]
    payload = _closed_mapping(raw_payload, expected, label)
    output: dict[str, list[dict[str, str]]] = {}
    for field in sorted(expected):
        output[field] = _semantic_atoms(payload[field], field, f"{label}.{field}")
    _require(
        any(output[field] for field in PHASE_QUERY_FIELDS[phase_branch]),
        f"{label}:rankable_semantics_required",
    )
    _require(bool(output["advisory_semantics"]), f"{label}:advisory_required")
    return output


def _normalize_phase_query(
    raw_query: Mapping[str, Any], *, phase_branch: str, atoms_already_typed: bool = False
) -> dict[str, list[dict[str, str]]]:
    expected = PHASE_QUERY_FIELDS[phase_branch]
    query = _closed_mapping(raw_query, expected, "phase_input")
    if atoms_already_typed:
        output = {field: [dict(row) for row in _array(query[field], f"phase_input.{field}")] for field in sorted(expected)}
        _validate_atom_mapping(output, expected_fields=expected, label="phase_input")
        return output
    output = {
        field: _semantic_atoms(query[field], field, f"phase_input.{field}")
        for field in sorted(expected)
    }
    _require(any(output.values()), "phase_input:all_semantics_empty")
    return output


def _phase_policy(phase_branch: str, raw_policy: Mapping[str, Any]) -> dict[str, Any]:
    policy = _closed_mapping(
        raw_policy,
        {"policy_version", "phase_branch", "requested_lane_subset", "top_k_per_lane"},
        "phase_policy",
    )
    _require_equal(policy["policy_version"], "phase-safe-offline-candidate-v1", "phase_policy.policy_version")
    _require_equal(policy["phase_branch"], phase_branch, "phase_policy.phase_branch")
    raw_lanes = list(_array(policy["requested_lane_subset"], "phase_policy.requested_lane_subset"))
    allowed = PHASE_ALLOWED_LANES[phase_branch]
    _require(bool(raw_lanes), "phase_policy:lane_subset_empty")
    _require(len(raw_lanes) == len(set(raw_lanes)), "phase_policy:duplicate_lane")
    _require(all(lane in allowed for lane in raw_lanes), "phase_policy:lane_not_allowed")
    canonical = [lane for lane in allowed if lane in raw_lanes]
    _require_equal(raw_lanes, canonical, "phase_policy:lane_order")
    _require("direct_counterexample" in raw_lanes, "phase_policy:direct_counterexample_required")
    top_k = policy["top_k_per_lane"]
    _require(type(top_k) is int and 1 <= top_k <= 20, "phase_policy:top_k")
    return {
        "policy_version": "phase-safe-offline-candidate-v1",
        "phase_branch": phase_branch,
        "allowed_lane_tokens": list(allowed),
        "requested_lane_subset": raw_lanes,
        "top_k_per_lane": top_k,
        "score_floor": 1,
        "historical_episode_context_allowed": phase_branch.startswith("B2_"),
        "bounded_evidence_mode": "FORBIDDEN_IN_STANDALONE_PROTOTYPE",
    }


def _phase_use_policy(phase_branch: str) -> dict[str, Any]:
    if phase_branch == "A0_MECHANISM_PRIOR":
        return {
            "use_scope": "STEP1_MODEL_CANDIDATE_ADVISORY_ONLY",
            "current_source_formalization_or_blind_seed_mutation_allowed": False,
        }
    if phase_branch == "A1_IMPLEMENTATION_FEASIBILITY":
        return {
            "use_scope": "IMPLEMENTATION_FEASIBILITY_ADVISORY_ONLY",
            "current_formula_code_or_data_contract_mutation_allowed": False,
        }
    if phase_branch == "B1_PREDICTION_CHALLENGE":
        return {
            "use_scope": "FROZEN_PREDICTION_CHALLENGE_ADVISORY_ONLY",
            "current_prediction_or_result_mutation_allowed": False,
        }
    if phase_branch == "B2_POSTRESULT_PLAN_SUPPORT":
        return {
            "use_scope": "POSTRESULT_PLAN_SUPPORT_ADVISORY_ONLY",
            "current_rival_prediction_or_result_mutation_allowed": False,
            "final_cause_or_confirmation_claim_allowed": False,
        }
    if phase_branch == "B2_PREMETRIC_FUTURE_QUESTION_ONLY":
        return {
            "use_scope": "FUTURE_QUESTION_NAMESPACE_ONLY",
            "future_question_namespace_only": True,
            "current_diagnosis_qualification_revision_writeback_allowed": False,
            "current_parent_council_consumption_allowed": False,
        }
    raise PhaseSafeRetrievalOfflineError(["phase_use_policy:unknown_phase"])


def compile_offline_corpus(objects: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    raw_objects = _array(objects, "corpus_objects")
    _require(bool(raw_objects), "corpus_objects:empty")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_payloads: set[str] = set()
    for ordinal, raw in enumerate(raw_objects):
        _require(isinstance(raw, Mapping), f"corpus_objects[{ordinal}]:object_required")
        corpus_class = raw.get("corpus_class")
        _require(corpus_class in CORPUS_CLASSES, f"corpus_objects[{ordinal}]:corpus_class")
        expected_fields = {"corpus_class", "phase_branch", "lane", "semantic_payload"}
        if corpus_class == QUARANTINED_CLASS:
            expected_fields.add("quarantine_reasons")
        obj = _closed_mapping(raw, expected_fields, f"corpus_objects[{ordinal}]")
        phase_branch = obj["phase_branch"]
        _require(phase_branch in PHASE_BRANCHES, f"corpus_objects[{ordinal}]:phase_branch")
        lane = obj["lane"]
        _require(lane in PHASE_ALLOWED_LANES[phase_branch], f"corpus_objects[{ordinal}]:lane")
        semantic_payload = _normalize_semantic_payload(
            obj["semantic_payload"],
            phase_branch=phase_branch,
            label=f"corpus_objects[{ordinal}].semantic_payload",
        )
        identity_preimage: dict[str, Any] = {
            "corpus_class": corpus_class,
            "phase_branch": phase_branch,
            "lane": lane,
            "semantic_payload": semantic_payload,
        }
        if corpus_class == QUARANTINED_CLASS:
            reasons = [
                _safe_reason(value, f"corpus_objects[{ordinal}].quarantine_reasons[{index}]")
                for index, value in enumerate(_array(obj["quarantine_reasons"], f"corpus_objects[{ordinal}].quarantine_reasons"))
            ]
            _require(bool(reasons), f"corpus_objects[{ordinal}]:quarantine_reason_required")
            _require(len(reasons) == len(set(reasons)), f"corpus_objects[{ordinal}]:duplicate_quarantine_reason")
            identity_preimage["quarantine_reasons"] = reasons
        payload_sha = framed_sha256(CORPUS_PAYLOAD_DOMAIN, identity_preimage)
        object_id = "fixture-local-" + framed_sha256(CORPUS_OBJECT_ID_DOMAIN, identity_preimage)
        _require(object_id not in seen_ids, f"corpus_objects[{ordinal}]:duplicate_object_id")
        _require(payload_sha not in seen_payloads, f"corpus_objects[{ordinal}]:duplicate_payload")
        seen_ids.add(object_id)
        seen_payloads.add(payload_sha)
        row_core = {
            "ordinal": ordinal,
            "object_id": object_id,
            "corpus_class": corpus_class,
            "phase_branch": phase_branch,
            "lane": lane,
            "semantic_payload": semantic_payload,
            "payload_sha256": payload_sha,
            "rank_admission_candidate": corpus_class == ADMISSIBLE_CLASS,
            "provenance_class": "SYNTHETIC" if corpus_class == ADMISSIBLE_CLASS else "QUARANTINED",
            "authority_effect": AUTHORITY_EFFECT,
        }
        if corpus_class == QUARANTINED_CLASS:
            row_core["quarantine_reasons"] = identity_preimage["quarantine_reasons"]
        rows.append(_with_content_sha(row_core, domain=CORPUS_OBJECT_DOMAIN))
    commitment = hashlib.sha256(
        CORPUS_COMMITMENT_DOMAIN.encode("utf-8")
        + b"\x00"
        + b"".join(
            row["ordinal"].to_bytes(8, "big") + bytes.fromhex(row["content_sha256"])
            for row in rows
        )
    ).hexdigest()
    core = {
        "schema_id": CORPUS_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "CLOSED_SYNTHETIC_OR_QUARANTINED_OFFLINE_CORPUS_CANDIDATE",
        "object_count": len(rows),
        "synthetic_admissible_candidate_count": sum(row["corpus_class"] == ADMISSIBLE_CLASS for row in rows),
        "quarantined_rejected_candidate_count": sum(row["corpus_class"] == QUARANTINED_CLASS for row in rows),
        "objects": rows,
        "corpus_manifest_commitment_sha256": commitment,
        "ambient_index_or_directory_discovery_allowed": False,
        "host_or_canonical_memory_source_allowed": False,
        "oos_or_realized_performance_source_allowed": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=CORPUS_DOMAIN)


def compile_phase_request_candidate(
    *,
    phase_branch: str,
    phase_input: Mapping[str, Any],
    phase_policy: Mapping[str, Any],
    source_first_binding_content_sha256: str | None = None,
    atoms_already_typed: bool = False,
) -> dict[str, Any]:
    _require(phase_branch in PHASE_BRANCHES, "phase_branch:unknown")
    if phase_branch == "A0_MECHANISM_PRIOR":
        _require(
            isinstance(source_first_binding_content_sha256, str)
            and SHA256_RE.fullmatch(source_first_binding_content_sha256) is not None,
            "a0:source_first_binding_required",
        )
    else:
        _require(source_first_binding_content_sha256 is None, "non_a0:source_first_binding_forbidden")
    query = _normalize_phase_query(
        phase_input,
        phase_branch=phase_branch,
        atoms_already_typed=atoms_already_typed,
    )
    policy = _phase_policy(phase_branch, phase_policy)
    policy_sha = framed_sha256(PHASE_POLICY_DOMAIN, policy)
    query_sha = framed_sha256(PHASE_QUERY_DOMAIN, query)
    core = {
        "request_kind": "PRIVATE_OFFLINE_RETRIEVAL_REQUEST_CANDIDATE",
        "phase_branch": phase_branch,
        "source_first_binding_content_sha256": source_first_binding_content_sha256,
        "query_semantics": query,
        "query_semantics_sha256": query_sha,
        "phase_policy": policy,
        "phase_policy_content_sha256": policy_sha,
        "phase_use_policy": _phase_use_policy(phase_branch),
        "request_not_issuable": True,
        "agent_visible_projection": None,
        "host_minted_opaque_handle_present": False,
        "host_capability_or_grant_present": False,
        "stable_identity_or_index_metadata_agent_visible": False,
        "runtime_retrieval_authority": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=REQUEST_DOMAIN)


def _read_json_object(path: Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
    raw = read_stable_regular_bytes(
        path,
        label=label,
        max_bytes=MAX_JSON_BYTES,
        require_private=True,
    )
    payload = strict_json_loads(raw, label=str(path))
    _require(isinstance(payload, dict), f"{label}:object_required")
    return raw, payload


def _validated_stage1_inputs(
    source_first_manifest_path: Path, *, source_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest_path = Path(source_first_manifest_path)
    manifest = validate_source_first_offline_candidate_packet(
        manifest_path,
        source_path=Path(source_path),
    )
    manifest_raw, parsed_manifest = _read_json_object(
        manifest_path, label="stage1_packet_manifest"
    )
    _require_equal(parsed_manifest, manifest, "stage1_packet_manifest:validated_equality")
    seed_raw, seed = _read_json_object(
        manifest_path.parent / "02_blind_mechanism_seed_candidate.json",
        label="stage1_blind_seed",
    )
    request_raw, request = _read_json_object(
        manifest_path.parent / "03_a0_request_candidate.json",
        label="stage1_a0_request_candidate",
    )
    _require_equal(
        request.get("request_branch"),
        "A0_HOST_PREISSUANCE_CANDIDATE",
        "stage1:a0_eligible_request_required",
    )
    _require_equal(
        request["private_replay_binding"]["blind_seed_content_sha256"],
        seed["content_sha256"],
        "stage1:blind_seed_request_binding",
    )
    core = {
        "schema_id": STAGE1_BINDING_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "input_role": "DETACHED_STAGE1_PROTOTYPE_INPUT__NOT_PREDECESSOR",
        "stage1_packet": {
            "packet_id": manifest["packet_id"],
            "lineage_mode": manifest["lineage_mode"],
            "factor_forge_successor": manifest["factor_forge_successor"],
            "manifest_bytes": len(manifest_raw),
            "manifest_raw_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "manifest_content_sha256": manifest["content_sha256"],
            "artifact_manifest_commitment_sha256": manifest[
                "artifact_manifest_commitment_sha256"
            ],
        },
        "stage1_blind_seed": {
            "bytes": len(seed_raw),
            "raw_sha256": hashlib.sha256(seed_raw).hexdigest(),
            "content_sha256": seed["content_sha256"],
        },
        "stage1_a0_request_candidate": {
            "bytes": len(request_raw),
            "raw_sha256": hashlib.sha256(request_raw).hexdigest(),
            "content_sha256": request["content_sha256"],
            "query_semantics_candidate_sha256": request[
                "private_preissuance_request_candidate"
            ]["query_semantics_candidate_sha256"],
        },
        "stage1_independently_revalidated": True,
        "prototype_dependency_not_normative_predecessor": True,
        "may_satisfy_any_factor_forge_gate": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    binding = _with_content_sha(core, domain=STAGE1_BINDING_DOMAIN)
    return binding, seed, request


def compile_stage1_input_binding(
    source_first_manifest_path: Path, *, source_path: Path
) -> dict[str, Any]:
    binding, _, _ = _validated_stage1_inputs(
        source_first_manifest_path,
        source_path=source_path,
    )
    return binding


def compile_a0_request_from_stage1(
    stage1_binding: Mapping[str, Any],
    stage1_blind_seed: Mapping[str, Any],
    stage1_a0_request: Mapping[str, Any],
) -> dict[str, Any]:
    _verify_content(stage1_binding, domain=STAGE1_BINDING_DOMAIN, label="stage1_binding")
    _require_equal(
        stage1_binding["stage1_blind_seed"]["content_sha256"],
        stage1_blind_seed.get("content_sha256"),
        "stage1_binding:blind_seed",
    )
    _require_equal(
        stage1_binding["stage1_a0_request_candidate"]["content_sha256"],
        stage1_a0_request.get("content_sha256"),
        "stage1_binding:a0_request",
    )
    candidate = stage1_a0_request["private_preissuance_request_candidate"]
    _require_equal(candidate["phase"], "A0", "stage1_request:phase")
    _require_equal(
        candidate["query_semantics_candidate_sha256"],
        stage1_binding["stage1_a0_request_candidate"][
            "query_semantics_candidate_sha256"
        ],
        "stage1_request:query_binding",
    )
    _require_equal(
        stage1_a0_request["private_replay_binding"]["blind_seed_content_sha256"],
        stage1_blind_seed["content_sha256"],
        "stage1_request:seed_binding",
    )
    stage1_policy = candidate["phase_policy_candidate"]
    policy = {
        "policy_version": "phase-safe-offline-candidate-v1",
        "phase_branch": "A0_MECHANISM_PRIOR",
        "requested_lane_subset": stage1_policy["requested_lane_subset"],
        "top_k_per_lane": stage1_policy["top_k_per_lane"],
    }
    return compile_phase_request_candidate(
        phase_branch="A0_MECHANISM_PRIOR",
        phase_input=candidate["query_semantics_candidate"],
        phase_policy=policy,
        source_first_binding_content_sha256=stage1_binding["content_sha256"],
        atoms_already_typed=True,
    )


def _validate_request_candidate(request: Mapping[str, Any]) -> None:
    expected = {
        "request_kind",
        "phase_branch",
        "source_first_binding_content_sha256",
        "query_semantics",
        "query_semantics_sha256",
        "phase_policy",
        "phase_policy_content_sha256",
        "phase_use_policy",
        "request_not_issuable",
        "agent_visible_projection",
        "host_minted_opaque_handle_present",
        "host_capability_or_grant_present",
        "stable_identity_or_index_metadata_agent_visible",
        "runtime_retrieval_authority",
        "candidate_only",
        "signed",
        "authority_effect",
        "content_sha256",
    }
    _closed_mapping(request, expected, "request_candidate")
    _verify_content(request, domain=REQUEST_DOMAIN, label="request_candidate")
    phase = request["phase_branch"]
    _require(phase in PHASE_BRANCHES, "request_candidate:phase")
    _validate_atom_mapping(
        request["query_semantics"],
        expected_fields=PHASE_QUERY_FIELDS[phase],
        label="request_candidate.query_semantics",
    )
    _require_equal(
        request["query_semantics_sha256"],
        framed_sha256(PHASE_QUERY_DOMAIN, request["query_semantics"]),
        "request_candidate.query_semantics_sha256",
    )
    policy_input = {
        "policy_version": request["phase_policy"]["policy_version"],
        "phase_branch": request["phase_policy"]["phase_branch"],
        "requested_lane_subset": request["phase_policy"]["requested_lane_subset"],
        "top_k_per_lane": request["phase_policy"]["top_k_per_lane"],
    }
    _require_equal(
        request["phase_policy"],
        _phase_policy(phase, policy_input),
        "request_candidate.phase_policy",
    )
    _require_equal(
        request["phase_policy_content_sha256"],
        framed_sha256(PHASE_POLICY_DOMAIN, request["phase_policy"]),
        "request_candidate.phase_policy_content_sha256",
    )
    _require_equal(
        request["phase_use_policy"],
        _phase_use_policy(phase),
        "request_candidate.phase_use_policy",
    )
    if phase == "A0_MECHANISM_PRIOR":
        _require(
            isinstance(request["source_first_binding_content_sha256"], str)
            and SHA256_RE.fullmatch(request["source_first_binding_content_sha256"]) is not None,
            "request_candidate:a0_source_first_binding",
        )
    else:
        _require_equal(
            request["source_first_binding_content_sha256"],
            None,
            "request_candidate:non_a0_source_binding",
        )
    fixed = {
        "request_kind": "PRIVATE_OFFLINE_RETRIEVAL_REQUEST_CANDIDATE",
        "request_not_issuable": True,
        "agent_visible_projection": None,
        "host_minted_opaque_handle_present": False,
        "host_capability_or_grant_present": False,
        "stable_identity_or_index_metadata_agent_visible": False,
        "runtime_retrieval_authority": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    for field, expected_value in fixed.items():
        _require_equal(request[field], expected_value, f"request_candidate.{field}")


def _validate_corpus(corpus: Mapping[str, Any]) -> None:
    _closed_mapping(
        corpus,
        {
            "schema_id",
            "schema_version",
            "artifact_status",
            "object_count",
            "synthetic_admissible_candidate_count",
            "quarantined_rejected_candidate_count",
            "objects",
            "corpus_manifest_commitment_sha256",
            "ambient_index_or_directory_discovery_allowed",
            "host_or_canonical_memory_source_allowed",
            "oos_or_realized_performance_source_allowed",
            "candidate_only",
            "signed",
            "authority_effect",
            "content_sha256",
        },
        "corpus",
    )
    _verify_content(corpus, domain=CORPUS_DOMAIN, label="corpus")
    _require_equal(corpus["schema_id"], CORPUS_SCHEMA_ID, "corpus.schema_id")
    rows = list(_array(corpus["objects"], "corpus.objects"))
    _require_equal(corpus["object_count"], len(rows), "corpus.object_count")
    _require_equal([row.get("ordinal") for row in rows], list(range(len(rows))), "corpus.ordinals")
    seen_ids: set[str] = set()
    seen_payloads: set[str] = set()
    for ordinal, raw in enumerate(rows):
        _require(isinstance(raw, Mapping), f"corpus.objects[{ordinal}]:object")
        corpus_class = raw.get("corpus_class")
        expected = {
            "ordinal",
            "object_id",
            "corpus_class",
            "phase_branch",
            "lane",
            "semantic_payload",
            "payload_sha256",
            "rank_admission_candidate",
            "provenance_class",
            "authority_effect",
            "content_sha256",
        }
        if corpus_class == QUARANTINED_CLASS:
            expected.add("quarantine_reasons")
        row = _closed_mapping(raw, expected, f"corpus.objects[{ordinal}]")
        _verify_content(row, domain=CORPUS_OBJECT_DOMAIN, label=f"corpus.objects[{ordinal}]")
        _require(corpus_class in CORPUS_CLASSES, f"corpus.objects[{ordinal}]:class")
        phase = row["phase_branch"]
        _require(phase in PHASE_BRANCHES, f"corpus.objects[{ordinal}]:phase")
        _require(row["lane"] in PHASE_ALLOWED_LANES[phase], f"corpus.objects[{ordinal}]:lane")
        _validate_atom_mapping(
            row["semantic_payload"],
            expected_fields=PHASE_CORPUS_FIELDS[phase],
            label=f"corpus.objects[{ordinal}].semantic_payload",
        )
        identity: dict[str, Any] = {
            "corpus_class": corpus_class,
            "phase_branch": phase,
            "lane": row["lane"],
            "semantic_payload": row["semantic_payload"],
        }
        if corpus_class == QUARANTINED_CLASS:
            reasons = list(_array(row["quarantine_reasons"], f"corpus.objects[{ordinal}].quarantine_reasons"))
            _require(bool(reasons) and len(reasons) == len(set(reasons)), f"corpus.objects[{ordinal}]:quarantine_reasons")
            for index, reason in enumerate(reasons):
                _safe_reason(reason, f"corpus.objects[{ordinal}].quarantine_reasons[{index}]")
            identity["quarantine_reasons"] = reasons
        payload_sha = framed_sha256(CORPUS_PAYLOAD_DOMAIN, identity)
        object_id = "fixture-local-" + framed_sha256(CORPUS_OBJECT_ID_DOMAIN, identity)
        _require_equal(row["payload_sha256"], payload_sha, f"corpus.objects[{ordinal}].payload_sha256")
        _require_equal(row["object_id"], object_id, f"corpus.objects[{ordinal}].object_id")
        _require(object_id not in seen_ids, f"corpus.objects[{ordinal}]:duplicate_id")
        _require(payload_sha not in seen_payloads, f"corpus.objects[{ordinal}]:duplicate_payload")
        seen_ids.add(object_id)
        seen_payloads.add(payload_sha)
        _require_equal(row["rank_admission_candidate"], corpus_class == ADMISSIBLE_CLASS, f"corpus.objects[{ordinal}].rank_admission_candidate")
        _require_equal(row["provenance_class"], "SYNTHETIC" if corpus_class == ADMISSIBLE_CLASS else "QUARANTINED", f"corpus.objects[{ordinal}].provenance_class")
        _require_equal(row["authority_effect"], AUTHORITY_EFFECT, f"corpus.objects[{ordinal}].authority_effect")
    commitment = hashlib.sha256(
        CORPUS_COMMITMENT_DOMAIN.encode("utf-8")
        + b"\x00"
        + b"".join(row["ordinal"].to_bytes(8, "big") + bytes.fromhex(row["content_sha256"]) for row in rows)
    ).hexdigest()
    _require_equal(corpus["corpus_manifest_commitment_sha256"], commitment, "corpus.commitment")
    _require_equal(corpus["synthetic_admissible_candidate_count"], sum(row["corpus_class"] == ADMISSIBLE_CLASS for row in rows), "corpus.synthetic_count")
    _require_equal(corpus["quarantined_rejected_candidate_count"], sum(row["corpus_class"] == QUARANTINED_CLASS for row in rows), "corpus.quarantine_count")
    for field in (
        "ambient_index_or_directory_discovery_allowed",
        "host_or_canonical_memory_source_allowed",
        "oos_or_realized_performance_source_allowed",
    ):
        _require_equal(corpus[field], False, f"corpus.{field}")
    _require_equal(corpus["candidate_only"], True, "corpus.candidate_only")
    _require_equal(corpus["signed"], False, "corpus.signed")
    _require_equal(corpus["authority_effect"], AUTHORITY_EFFECT, "corpus.authority_effect")


def _program_profile() -> dict[str, Any]:
    core = {
        "profile_id": "FF_PHASE_SAFE_OFFLINE_DETERMINISTIC_INTEGER_RANK_V1",
        "normalization": "UNICODE_NFKC_CASEFOLD",
        "tokenization": "ASCII_ALNUM_WORDS_PLUS_OVERLAPPING_CJK_BIGRAMS",
        "scoring": {
            "exact_atom_match_weight": 32,
            "shared_unique_token_weight": 3,
            "matched_field_weight": 7,
            "score_floor": 1,
            "binary_float_forbidden": True,
        },
        "rank_key": [
            "score_total_desc",
            "exact_atom_matches_desc",
            "shared_unique_token_count_desc",
            "object_id_asc",
        ],
        "lane_semantic_gates": {
            "structural_isomorph": "ECONOMIC_GAME_AND_LATENT_MECHANISM_OVERLAP",
            "cross_math_analogy": "ECONOMIC_OR_LATENT_OVERLAP_AND_MATH_OVERLAP",
            "near_miss_failure": "MECHANISM_OR_MATH_OVERLAP_AND_FALSIFIER_OVERLAP",
            "direct_counterexample": "FALSIFIER_OVERLAP_OR_MECHANISM_AND_MATH_OVERLAP",
            "historical_episode_context": "MECHANISM_OVERLAP_AND_PHASE_SPECIFIC_OVERLAP",
        },
        "authority_integrity_is_exclusion_only": True,
        "historical_performance_or_outcome_feature_allowed": False,
        "full_corpus_digest_in_phase_program_allowed": False,
        "ambient_index_discovery_allowed": False,
    }
    return _with_content_sha(core, domain=PROGRAM_PROFILE_DOMAIN)


def _phase_projection(corpus: Mapping[str, Any], phase_branch: str) -> dict[str, Any]:
    rows = [
        {
            "object_id": row["object_id"],
            "object_content_sha256": row["payload_sha256"],
            "corpus_class": row["corpus_class"],
            "lane": row["lane"],
            "semantic_payload": row["semantic_payload"],
            **(
                {"quarantine_reasons": row["quarantine_reasons"]}
                if row["corpus_class"] == QUARANTINED_CLASS
                else {}
            ),
        }
        for row in corpus["objects"]
        if row["phase_branch"] == phase_branch
    ]
    rows.sort(key=lambda row: row["object_id"])
    core = {
        "phase_branch": phase_branch,
        "projected_object_count": len(rows),
        "projected_objects": rows,
        "later_phase_object_counts_or_health_structurally_absent": True,
        "full_corpus_commitment_structurally_absent": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=PHASE_PROJECTION_DOMAIN)


def compile_retrieval_program(
    request_candidate: Mapping[str, Any], corpus_bundle: Mapping[str, Any]
) -> dict[str, Any]:
    _validate_request_candidate(request_candidate)
    _validate_corpus(corpus_bundle)
    projection = _phase_projection(corpus_bundle, request_candidate["phase_branch"])
    profile = _program_profile()
    core = {
        "schema_id": PROGRAM_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "PRIVATE_OFFLINE_PROGRAM_CANDIDATE__NOT_RUNTIME_EXECUTION",
        "phase_branch": request_candidate["phase_branch"],
        "request_candidate": dict(request_candidate),
        "phase_use_policy": request_candidate["phase_use_policy"],
        "phase_projection": projection,
        "phase_projection_content_sha256": projection["content_sha256"],
        "program_profile": profile,
        "program_profile_content_sha256": profile["content_sha256"],
        "full_corpus_content_sha256_or_commitment_present": False,
        "private_full_world_is_manifest_sidecar_only": True,
        "agent_visible_projection": None,
        "retrieval_runtime_executed": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=PROGRAM_DOMAIN)


def _token_set(texts: Sequence[str]) -> set[str]:
    tokens: set[str] = set()
    for text in texts:
        normalized = unicodedata.normalize("NFKC", text).casefold()
        for token in TOKEN_RE.findall(normalized):
            if re.fullmatch(r"[\u3400-\u9fff]+", token):
                if len(token) == 1:
                    tokens.add(token)
                else:
                    tokens.update(token[index : index + 2] for index in range(len(token) - 1))
            else:
                tokens.add(token)
    return tokens


def _field_texts(payload: Mapping[str, Any], field: str) -> list[str]:
    rows = payload.get(field, [])
    return [row["semantic_text"] for row in rows]


def _score_payload(
    query: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, int]:
    exact_matches = 0
    shared_tokens: set[tuple[str, str]] = set()
    matched_fields = 0
    for field in sorted(set(query).intersection(candidate)):
        query_texts = _field_texts(query, field)
        candidate_texts = _field_texts(candidate, field)
        exact_matches += len(set(query_texts).intersection(candidate_texts))
        overlap = _token_set(query_texts).intersection(_token_set(candidate_texts))
        if overlap:
            matched_fields += 1
            shared_tokens.update((field, token) for token in overlap)
    score = exact_matches * 32 + len(shared_tokens) * 3 + matched_fields * 7
    return {
        "exact_atom_matches": exact_matches,
        "shared_unique_token_count": len(shared_tokens),
        "matched_field_count": matched_fields,
        "score_total": score,
    }


def _field_has_overlap(
    query: Mapping[str, Any], candidate: Mapping[str, Any], field: str
) -> bool:
    return bool(
        _token_set(_field_texts(query, field)).intersection(
            _token_set(_field_texts(candidate, field))
        )
    )


def _lane_semantic_gate(
    query: Mapping[str, Any], candidate: Mapping[str, Any], lane: str
) -> bool:
    economic = _field_has_overlap(query, candidate, "economic_game_semantics")
    latent = _field_has_overlap(query, candidate, "latent_mechanism_semantics")
    math = _field_has_overlap(query, candidate, "mathematical_family_semantics")
    falsifier = _field_has_overlap(query, candidate, "falsifier_semantics")
    if lane == "structural_isomorph":
        return economic and latent
    if lane == "cross_math_analogy":
        return (economic or latent) and math
    if lane == "near_miss_failure":
        return (economic or latent or math) and falsifier
    if lane == "direct_counterexample":
        return falsifier or ((economic or latent) and math)
    if lane == "historical_episode_context":
        common = economic or latent or math or falsifier
        phase_specific_fields = set(query).difference(COMMON_QUERY_FIELDS)
        return common and any(
            _field_has_overlap(query, candidate, field)
            for field in phase_specific_fields
        )
    raise PhaseSafeRetrievalOfflineError(["lane_semantic_gate:unknown_lane"])


def _rank_key(row: Mapping[str, Any]) -> tuple[int, int, int, str]:
    components = row["score_components"]
    return (
        -components["score_total"],
        -components["exact_atom_matches"],
        -components["shared_unique_token_count"],
        row["object_id"],
    )


def _validate_program(program: Mapping[str, Any]) -> None:
    _closed_mapping(
        program,
        {
            "schema_id",
            "schema_version",
            "artifact_status",
            "phase_branch",
            "request_candidate",
            "phase_use_policy",
            "phase_projection",
            "phase_projection_content_sha256",
            "program_profile",
            "program_profile_content_sha256",
            "full_corpus_content_sha256_or_commitment_present",
            "private_full_world_is_manifest_sidecar_only",
            "agent_visible_projection",
            "retrieval_runtime_executed",
            "candidate_only",
            "signed",
            "authority_effect",
            "content_sha256",
        },
        "retrieval_program",
    )
    _verify_content(program, domain=PROGRAM_DOMAIN, label="retrieval_program")
    _require_equal(program["schema_id"], PROGRAM_SCHEMA_ID, "retrieval_program.schema_id")
    _validate_request_candidate(program["request_candidate"])
    phase = program["request_candidate"]["phase_branch"]
    _require_equal(program["phase_branch"], phase, "retrieval_program.phase_branch")
    _require_equal(
        program["phase_use_policy"],
        _phase_use_policy(phase),
        "retrieval_program.phase_use_policy",
    )
    projection = _closed_mapping(
        program["phase_projection"],
        {
            "phase_branch",
            "projected_object_count",
            "projected_objects",
            "later_phase_object_counts_or_health_structurally_absent",
            "full_corpus_commitment_structurally_absent",
            "authority_effect",
            "content_sha256",
        },
        "retrieval_program.phase_projection",
    )
    _verify_content(projection, domain=PHASE_PROJECTION_DOMAIN, label="retrieval_program.phase_projection")
    _require_equal(projection["phase_branch"], phase, "retrieval_program.phase_projection.phase")
    _require_equal(projection["projected_object_count"], len(projection["projected_objects"]), "retrieval_program.phase_projection.count")
    _require_equal(
        [row["object_id"] for row in projection["projected_objects"]],
        sorted(row["object_id"] for row in projection["projected_objects"]),
        "retrieval_program.phase_projection.order",
    )
    for ordinal, raw in enumerate(projection["projected_objects"]):
        corpus_class = raw.get("corpus_class")
        fields = {
            "object_id",
            "object_content_sha256",
            "corpus_class",
            "lane",
            "semantic_payload",
        }
        if corpus_class == QUARANTINED_CLASS:
            fields.add("quarantine_reasons")
        row = _closed_mapping(raw, fields, f"retrieval_program.phase_projection.objects[{ordinal}]")
        _require(corpus_class in CORPUS_CLASSES, f"retrieval_program.phase_projection.objects[{ordinal}]:class")
        _require(row["lane"] in PHASE_ALLOWED_LANES[phase], f"retrieval_program.phase_projection.objects[{ordinal}]:lane")
        _validate_atom_mapping(
            row["semantic_payload"],
            expected_fields=PHASE_CORPUS_FIELDS[phase],
            label=f"retrieval_program.phase_projection.objects[{ordinal}].semantic_payload",
        )
        _require(isinstance(row["object_content_sha256"], str) and SHA256_RE.fullmatch(row["object_content_sha256"]) is not None, f"retrieval_program.phase_projection.objects[{ordinal}]:hash")
    _require_equal(program["phase_projection_content_sha256"], projection["content_sha256"], "retrieval_program.phase_projection_content_sha256")
    _require_equal(program["program_profile"], _program_profile(), "retrieval_program.program_profile")
    _require_equal(program["program_profile_content_sha256"], program["program_profile"]["content_sha256"], "retrieval_program.program_profile_content_sha256")
    fixed = {
        "full_corpus_content_sha256_or_commitment_present": False,
        "private_full_world_is_manifest_sidecar_only": True,
        "agent_visible_projection": None,
        "retrieval_runtime_executed": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    for field, expected in fixed.items():
        _require_equal(program[field], expected, f"retrieval_program.{field}")


def _compile_score_ledger(program: Mapping[str, Any]) -> dict[str, Any]:
    _validate_program(program)
    request = program["request_candidate"]
    query = request["query_semantics"]
    requested_lanes = request["phase_policy"]["requested_lane_subset"]
    projected = program["phase_projection"]["projected_objects"]
    rows: list[dict[str, Any]] = []
    for obj in projected:
        if obj["corpus_class"] != ADMISSIBLE_CLASS or obj["lane"] not in requested_lanes:
            continue
        semantic_gate_pass = _lane_semantic_gate(
            query, obj["semantic_payload"], obj["lane"]
        )
        row_core = {
            "ordinal": len(rows),
            "lane": obj["lane"],
            "object_id": obj["object_id"],
            "object_content_sha256": obj["object_content_sha256"],
            "corpus_class": obj["corpus_class"],
            "quarantine_gate_pass": True,
            "lane_gate_pass": True,
            "lane_semantic_gate_pass": semantic_gate_pass,
            "rank_eligible": semantic_gate_pass,
            "score_components": _score_payload(query, obj["semantic_payload"]),
            "used_rank_feature_tokens": [
                "EXACT_SANITIZED_SEMANTIC_ATOM_MATCH",
                "SHARED_SANITIZED_TOKEN",
                "MATCHED_SEMANTIC_FIELD",
            ],
            "performance_outcome_identity_or_index_feature_used": False,
            "authority_effect": AUTHORITY_EFFECT,
        }
        rows.append(_with_content_sha(row_core, domain=SCORE_ROW_DOMAIN))
    core = {
        "schema_id": SCORE_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "PRIVATE_OFFLINE_COMPLETE_PHASE_SCORE_LEDGER_CANDIDATE",
        "retrieval_program_content_sha256": program["content_sha256"],
        "phase_projection_content_sha256": program["phase_projection_content_sha256"],
        "requested_lane_count": len(requested_lanes),
        "phase_projected_object_count": len(projected),
        "expected_score_row_count": len(rows),
        "score_rows": rows,
        "phase_only_execution_access_trace": {
            "accepted_input_kind": "CLOSED_PHASE_PROJECTION_PROGRAM_ONLY",
            "full_world_argument_accepted": False,
            "filesystem_open_stat_or_directory_discovery_count": 0,
            "index_count_health_or_availability_probe_count": 0,
            "network_or_host_api_call_count": 0,
            "timing_bucket": "PURE_CPU_DETERMINISTIC_NO_EXTERNAL_IO",
        },
        "full_corpus_content_sha256_or_commitment_present": False,
        "agent_visible_projection": None,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=SCORE_LEDGER_DOMAIN)


def _compile_selection_ledger(
    program: Mapping[str, Any], score_ledger: Mapping[str, Any]
) -> dict[str, Any]:
    request = program["request_candidate"]
    phase = request["phase_branch"]
    requested = request["phase_policy"]["requested_lane_subset"]
    top_k = request["phase_policy"]["top_k_per_lane"]
    floor = request["phase_policy"]["score_floor"]
    projected_by_id = {
        row["object_id"]: row for row in program["phase_projection"]["projected_objects"]
    }
    lane_results: list[dict[str, Any]] = []
    all_selected: list[dict[str, Any]] = []
    global_ordinal = 0
    for lane in PHASE_ALLOWED_LANES[phase]:
        selected_rows: list[dict[str, Any]] = []
        if lane in requested:
            candidates = [
                row
                for row in score_ledger["score_rows"]
                if row["lane"] == lane
                and row["rank_eligible"]
                and row["score_components"]["score_total"] >= floor
            ]
            candidates.sort(key=_rank_key)
            for lane_ordinal, score_row in enumerate(candidates[:top_k]):
                obj = projected_by_id[score_row["object_id"]]
                row_core = {
                    "global_ordinal": global_ordinal,
                    "lane_ordinal": lane_ordinal,
                    "lane": lane,
                    "object_id": score_row["object_id"],
                    "object_content_sha256": score_row["object_content_sha256"],
                    "score_row_content_sha256": score_row["content_sha256"],
                    "score_total": score_row["score_components"]["score_total"],
                    "private_sanitized_semantic_candidate": obj["semantic_payload"],
                    "advisory_only": True,
                    "future_question_namespace_only": (
                        phase == "B2_PREMETRIC_FUTURE_QUESTION_ONLY"
                    ),
                    "current_diagnosis_qualification_revision_writeback_allowed": False,
                    "agent_visible_handle_minted": False,
                    "authority_effect": AUTHORITY_EFFECT,
                }
                selected = _with_content_sha(row_core, domain=SELECTION_ROW_DOMAIN)
                selected_rows.append(selected)
                all_selected.append(selected)
                global_ordinal += 1
        lane_results.append(
            {
                "lane": lane,
                "requested": lane in requested,
                "selected_count": len(selected_rows),
                "selected": selected_rows,
            }
        )
    core = {
        "schema_id": SELECTION_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "PRIVATE_OFFLINE_SELECTION_CANDIDATE__NOT_AGENT_RESPONSE",
        "retrieval_program_content_sha256": program["content_sha256"],
        "score_ledger_content_sha256": score_ledger["content_sha256"],
        "phase_projection_content_sha256": program["phase_projection_content_sha256"],
        "allowed_lane_count": len(PHASE_ALLOWED_LANES[phase]),
        "lane_results": lane_results,
        "selected_count": len(all_selected),
        "returned_rows": all_selected,
        "phase_use_policy": _phase_use_policy(phase),
        "result_branch": (
            "OFFLINE_RETURNED_CANDIDATES"
            if all_selected
            else (
                "OFFLINE_ZERO_HIT_CANDIDATE"
                if not program["phase_projection"]["projected_objects"]
                or any(row["rank_eligible"] for row in score_ledger["score_rows"])
                else "OFFLINE_NO_ADMISSIBLE_CANDIDATE_CLOSURE"
            )
        ),
        "selected_score_row_content_sha256": [
            row["score_row_content_sha256"] for row in all_selected
        ],
        "full_corpus_content_sha256_or_commitment_present": False,
        "agent_visible_projection": None,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=SELECTION_DOMAIN)


def _compile_rejection_ledger(
    program: Mapping[str, Any],
    score_ledger: Mapping[str, Any],
    selection_ledger: Mapping[str, Any],
) -> dict[str, Any]:
    request = program["request_candidate"]
    phase = request["phase_branch"]
    requested = request["phase_policy"]["requested_lane_subset"]
    floor = request["phase_policy"]["score_floor"]
    selected_score_rows = set(selection_ledger["selected_score_row_content_sha256"])
    selected_object_ids = {
        row["object_id"] for row in selection_ledger["returned_rows"]
    }
    score_by_object = {
        row["object_id"]: row for row in score_ledger["score_rows"]
    }
    projected = program["phase_projection"]["projected_objects"]
    rejections: list[dict[str, Any]] = []
    for obj in projected:
        if obj["object_id"] in selected_object_ids:
            continue
        score_row = score_by_object.get(obj["object_id"])
        if obj["corpus_class"] == QUARANTINED_CLASS:
            reason = "QUARANTINED"
        elif obj["lane"] not in requested:
            reason = "LANE_INELIGIBLE"
        elif score_row is None:
            raise PhaseSafeRetrievalOfflineError(["rejection:missing_score_row"])
        elif not score_row["lane_semantic_gate_pass"]:
            reason = "LANE_SEMANTIC_GATE_FAILED"
        elif score_row["score_components"]["score_total"] < floor:
            reason = "NO_MATCH"
        else:
            reason = "BELOW_TOP_K_CUTOFF"
        row_core = {
            "ordinal": len(rejections),
            "lane": obj["lane"],
            "object_id": obj["object_id"],
            "score_row_content_sha256": (
                score_row["content_sha256"] if score_row is not None else None
            ),
            "reason_code": reason,
            "authority_effect": AUTHORITY_EFFECT,
        }
        rejections.append(_with_content_sha(row_core, domain=REJECTION_ROW_DOMAIN))
    lane_terminals: list[dict[str, Any]] = []
    for lane in PHASE_ALLOWED_LANES[phase]:
        if lane not in requested:
            terminal = {
                "lane": lane,
                "requested": False,
                "terminal_disposition": "NOT_REQUESTED",
                "admissible_pool_count": 0,
                "selected_count": 0,
                "zero_hit_is_signed_or_verified": False,
                "authority_effect": AUTHORITY_EFFECT,
            }
        else:
            lane_scores = [row for row in score_ledger["score_rows"] if row["lane"] == lane]
            lane_source_count = sum(obj["lane"] == lane for obj in projected)
            admissible_pool_count = sum(row["rank_eligible"] for row in lane_scores)
            selected_count = next(
                row["selected_count"]
                for row in selection_ledger["lane_results"]
                if row["lane"] == lane
            )
            if selected_count:
                disposition = "HIT"
            elif lane_source_count == 0:
                disposition = "ZERO_HIT_CANDIDATE"
            elif admissible_pool_count:
                disposition = "ZERO_HIT_CANDIDATE"
            else:
                disposition = "NO_ADMISSIBLE_CANDIDATE_CLOSURE"
            terminal = {
                "lane": lane,
                "requested": True,
                "terminal_disposition": disposition,
                "admissible_pool_count": admissible_pool_count,
                "selected_count": selected_count,
                "zero_hit_is_signed_or_verified": False,
                "authority_effect": AUTHORITY_EFFECT,
            }
        lane_terminals.append(_with_content_sha(terminal, domain=LANE_TERMINAL_DOMAIN))
    overall = selection_ledger["result_branch"]
    core = {
        "schema_id": REJECTION_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "PRIVATE_OFFLINE_REJECTION_AND_ZERO_HIT_CANDIDATE_LEDGER",
        "retrieval_program_content_sha256": program["content_sha256"],
        "score_ledger_content_sha256": score_ledger["content_sha256"],
        "selection_ledger_content_sha256": selection_ledger["content_sha256"],
        "phase_projection_content_sha256": program["phase_projection_content_sha256"],
        "overall_disposition": overall,
        "rejected_count": len(rejections),
        "rejections": rejections,
        "rejection_rows": rejections,
        "lane_terminals": lane_terminals,
        "object_partition_complete": len(selected_object_ids) + len(rejections) == len(projected),
        "selected_and_rejected_disjoint": not selected_object_ids.intersection(
            row["object_id"] for row in rejections
        ),
        "direct_counterexample_has_hit_or_unsigned_candidate_closure": next(
            row["terminal_disposition"] for row in lane_terminals if row["lane"] == "direct_counterexample"
        ) in {"HIT", "ZERO_HIT_CANDIDATE", "NO_ADMISSIBLE_CANDIDATE_CLOSURE"},
        "signed_zero_hit_attestation_claimed": False,
        "full_corpus_content_sha256_or_commitment_present": False,
        "agent_visible_projection": None,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=REJECTION_DOMAIN)


def execute_phase_projection_candidate(
    retrieval_program: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Execute only a closed phase projection; no full-world input is accepted."""

    _validate_program(retrieval_program)
    scores = _compile_score_ledger(retrieval_program)
    selections = _compile_selection_ledger(retrieval_program, scores)
    rejections = _compile_rejection_ledger(retrieval_program, scores, selections)
    return scores, selections, rejections


def _contains_scalar(value: Any, target: str) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_scalar(item, target) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_scalar(item, target) for item in value)
    return value == target


def _validate_private_projection_binding(
    corpus_bundle: Mapping[str, Any], retrieval_program: Mapping[str, Any]
) -> None:
    _validate_corpus(corpus_bundle)
    expected_projection = _phase_projection(
        corpus_bundle, retrieval_program["request_candidate"]["phase_branch"]
    )
    _require_equal(
        retrieval_program["phase_projection"],
        expected_projection,
        "private_projector:phase_projection_closed_equality",
    )
    full_world_values = {
        corpus_bundle["content_sha256"],
        corpus_bundle["corpus_manifest_commitment_sha256"],
    }
    for value in full_world_values:
        _require(
            not _contains_scalar(retrieval_program, value),
            "private_projector:program_full_world_digest_leak",
        )


def validate_phase_safe_retrieval_bundle(
    *,
    request_candidate: Mapping[str, Any] | None = None,
    retrieval_program: Mapping[str, Any],
    score_ledger: Mapping[str, Any],
    selection_ledger: Mapping[str, Any],
    rejection_ledger: Mapping[str, Any],
) -> None:
    if request_candidate is not None:
        _require_equal(
            retrieval_program["request_candidate"],
            request_candidate,
            "bundle:request_candidate_closed_equality",
        )
    _validate_program(retrieval_program)
    expected_scores, expected_selections, expected_rejections = (
        execute_phase_projection_candidate(retrieval_program)
    )
    _require_equal(score_ledger, expected_scores, "bundle:score_ledger_closed_equality")
    _require_equal(selection_ledger, expected_selections, "bundle:selection_ledger_closed_equality")
    _require_equal(rejection_ledger, expected_rejections, "bundle:rejection_ledger_closed_equality")


def compile_local_replay_report(
    *,
    stage1_binding: Mapping[str, Any],
    corpus_bundle: Mapping[str, Any],
    retrieval_program: Mapping[str, Any],
    score_ledger: Mapping[str, Any],
    selection_ledger: Mapping[str, Any],
    rejection_ledger: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_private_projection_binding(corpus_bundle, retrieval_program)
    validate_phase_safe_retrieval_bundle(
        retrieval_program=retrieval_program,
        score_ledger=score_ledger,
        selection_ledger=selection_ledger,
        rejection_ledger=rejection_ledger,
    )
    checks = (
        "DETACHED_STAGE1_PROTOTYPE_REVALIDATED_NOT_PROMOTED_TO_PREDECESSOR",
        "FULL_SYNTHETIC_WORLD_BOUND_ONLY_BY_PRIVATE_REPLAY_SIDECAR",
        "PHASE_PROGRAM_BINDS_ONLY_PHASE_PROJECTION",
        "A0_EXECUTION_INPUT_AND_CALL_GRAPH_EXCLUDE_FULL_WORLD_AND_HIDDEN_PHASES",
        "A0_HIDDEN_PHASE_OBJECTS_ABSENT_FROM_SCORE_SELECTION_REJECTION",
        "SYNTHETIC_OR_QUARANTINED_CORPUS_ONLY",
        "QUARANTINED_OBJECTS_NEVER_RANK_OR_RETURN",
        "INTEGER_ONLY_DETERMINISTIC_RANK_AND_TIE_BREAK",
        "SELECTED_REJECTED_DISJOINT_COMPLETE_PARTITION",
        "DIRECT_COUNTEREXAMPLE_HIT_OR_UNSIGNED_CANDIDATE_CLOSURE",
        "NO_SIGNED_ZERO_HIT_OR_OPAQUE_HANDLE_MINT_CLAIM",
        "NO_PERFORMANCE_OUTCOME_IDENTITY_OR_INDEX_RANK_FEATURE",
        "B2_PREMETRIC_OUTPUT_IS_FUTURE_QUESTION_NAMESPACE_ONLY",
        "NO_HOST_CANONICAL_MEMORY_OOS_SKILL_RAG_RUNTIME_OR_DEPLOYMENT_AUTHORITY",
    )
    core = {
        "schema_id": REPORT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "report_status": "LOCAL_OFFLINE_REPLAY_PASS__NOT_OPERATING_AUTHORITY",
        "private_sidecar_bindings": {
            "stage1_binding_content_sha256": stage1_binding["content_sha256"],
            "full_corpus_content_sha256": corpus_bundle["content_sha256"],
            "full_corpus_manifest_commitment_sha256": corpus_bundle[
                "corpus_manifest_commitment_sha256"
            ],
            "retrieval_program_content_sha256": retrieval_program["content_sha256"],
            "score_ledger_content_sha256": score_ledger["content_sha256"],
            "selection_ledger_content_sha256": selection_ledger["content_sha256"],
            "rejection_ledger_content_sha256": rejection_ledger["content_sha256"],
        },
        "phase_response_like_artifacts_bind_full_world": False,
        "phase_execution_accepts_or_reads_full_world": False,
        "phase_execution_input_kind": "CLOSED_PHASE_PROJECTION_PROGRAM_ONLY",
        "phase_execution_external_io_operation_count": 0,
        "private_projector_is_execution_dependency": False,
        "ordered_check_count": len(checks),
        "ordered_checks": [
            {"ordinal": ordinal, "check_id": check, "result": "PASS"}
            for ordinal, check in enumerate(checks)
        ],
        "pure_offline_transform_performed": True,
        "retrieval_runtime_executed": False,
        "host_or_canonical_memory_accessed": False,
        "oos_accessed": False,
        "skill_or_rag_runtime_invoked_or_mutated": False,
        "network_or_ambient_index_discovery_performed": False,
        "opaque_handle_or_signed_zero_hit_minted": False,
        "canonical_write_or_promotion_performed": False,
        "runtime_or_deployment_performed": False,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=REPORT_DOMAIN)


def compile_packet_manifest(
    *,
    artifact_rows: Sequence[Mapping[str, Any]],
    stage1_binding: Mapping[str, Any],
    corpus_bundle: Mapping[str, Any],
    retrieval_program: Mapping[str, Any],
) -> dict[str, Any]:
    _require_equal(
        [row["ordinal"] for row in artifact_rows],
        list(range(7)),
        "packet.artifact_ordinals",
    )
    artifact_commitment = hashlib.sha256(
        PACKET_ARTIFACT_DOMAIN.encode("utf-8")
        + b"\x00"
        + b"".join(bytes.fromhex(row["sha256"]) for row in artifact_rows)
    ).hexdigest()
    compiler_raw = read_stable_regular_bytes(
        Path(__file__),
        label="phase_safe_retrieval_compiler_module",
        max_bytes=4 * 1024 * 1024,
    )
    core = {
        "schema_id": PACKET_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "packet_id": "FF_PHASE_SAFE_RETRIEVAL_STANDALONE_OFFLINE_PROTOTYPE_20260829_R3",
        "manifest_status": (
            "STANDALONE_OFFLINE_RETRIEVAL_PROTOTYPE_COMPLETE__"
            "ALL_FACTOR_FORGE_AND_OPERATING_AUTHORITY_UNBOUND_BLOCKING"
        ),
        "lineage_mode": "STANDALONE_OFFLINE_ALGORITHM_PROTOTYPE",
        "factor_forge_successor": False,
        "direct_predecessor_manifest_raw_sha256": None,
        "normative_dependency_count": 0,
        "may_satisfy_any_factor_forge_gate": False,
        "prototype_input_dependency_count": 1,
        "prototype_input_dependencies": [
            {
                "ordinal": 0,
                "role": "DETACHED_STAGE1_PROTOTYPE_INPUT__NOT_PREDECESSOR",
                "stage1_packet_id": stage1_binding["stage1_packet"]["packet_id"],
                "stage1_manifest_raw_sha256": stage1_binding["stage1_packet"][
                    "manifest_raw_sha256"
                ],
                "stage1_manifest_content_sha256": stage1_binding["stage1_packet"][
                    "manifest_content_sha256"
                ],
                "stage1_binding_content_sha256": stage1_binding["content_sha256"],
                "authority_effect": AUTHORITY_EFFECT,
            }
        ],
        "artifact_count": 7,
        "ordered_artifacts": [dict(row) for row in artifact_rows],
        "artifact_manifest_commitment_sha256": artifact_commitment,
        "compiler_profile": {
            "module": "factor_factory/epistemic_phase_safe_retrieval_offline.py",
            "bytes": len(compiler_raw),
            "sha256": hashlib.sha256(compiler_raw).hexdigest(),
            "canonicalization": "RFC8785_INTEGER_ONLY_ACCEPTED_JSON_PROFILE",
            "content_digest_formula": (
                "SHA256(UTF8(domain)||0x00||"
                "RFC8785(payload_without_content_sha256))"
            ),
            "artifact_commitment_formula": (
                "SHA256(UTF8(FF_PHASE_SAFE_OFFLINE_PACKET_ARTIFACT_MANIFEST_V1)"
                "||0x00||CONCAT(ordered_artifact_raw_sha256_bytes))"
            ),
        },
        "private_full_world_sidecar": {
            "corpus_content_sha256": corpus_bundle["content_sha256"],
            "corpus_manifest_commitment_sha256": corpus_bundle[
                "corpus_manifest_commitment_sha256"
            ],
            "phase_response_like_artifact_dependency_allowed": False,
        },
        "phase_projection_content_sha256": retrieval_program[
            "phase_projection_content_sha256"
        ],
        "offline_transform_allowed": True,
        "retrieval_runtime_allowed": False,
        "host_or_canonical_memory_allowed": False,
        "oos_allowed": False,
        "skill_or_rag_runtime_allowed": False,
        "network_or_ambient_index_discovery_allowed": False,
        "opaque_handle_or_signed_zero_hit_mint_allowed": False,
        "canonical_write_or_promotion_allowed": False,
        "runtime_or_deployment_allowed": False,
        "steward_or_host_authority_present": False,
        "permissions_opened_count": 0,
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=PACKET_DOMAIN)


def _packet_artifact_spec() -> tuple[tuple[str, str], ...]:
    return (
        ("00_stage1_input_binding.json", "DETACHED_STAGE1_INPUT_BINDING"),
        ("01_closed_corpus_bundle.json", "CLOSED_SYNTHETIC_QUARANTINED_CORPUS"),
        ("02_retrieval_program.json", "PHASE_SAFE_RETRIEVAL_PROGRAM"),
        ("03_scored_candidate_ledger.json", "SCORED_CANDIDATE_LEDGER"),
        ("04_selection_ledger.json", "SELECTION_LEDGER"),
        ("05_rejection_and_zero_hit_ledger.json", "REJECTION_ZERO_HIT_LEDGER"),
        ("06_local_replay_report.json", "LOCAL_REPLAY_REPORT"),
    )


def validate_phase_safe_retrieval_offline_candidate_packet(
    packet_manifest_path: Path,
    *,
    source_first_manifest_path: Path,
    source_path: Path,
) -> dict[str, Any]:
    manifest_path = Path(packet_manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = Path.cwd() / manifest_path
    _require_equal(manifest_path.name, "packet_manifest.json", "packet_manifest:name")
    root = manifest_path.parent
    specs = _packet_artifact_spec()
    expected_names = {"packet_manifest.json", *(name for name, _ in specs)}
    actual_names: set[str] = set()
    for path in root.iterdir():
        metadata = path.lstat()
        _require(
            stat.S_ISREG(metadata.st_mode)
            and not stat.S_ISLNK(metadata.st_mode)
            and metadata.st_nlink == 1,
            f"packet_entry:unsafe:{path.name}",
        )
        actual_names.add(path.name)
    _require_equal(actual_names, expected_names, "packet:exact8_closure")

    _, manifest = _read_json_object(
        manifest_path, label="phase_safe_packet_manifest"
    )
    _verify_content(manifest, domain=PACKET_DOMAIN, label="phase_safe_packet_manifest")
    rows: list[dict[str, Any]] = []
    payloads: dict[str, dict[str, Any]] = {}
    for ordinal, (name, role) in enumerate(specs):
        raw, payload = _read_json_object(root / name, label=f"packet_artifact:{name}")
        rows.append(
            {
                "ordinal": ordinal,
                "role": role,
                "path": name,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        payloads[role] = payload
    _require_equal(manifest["ordered_artifacts"], rows, "packet_manifest:artifact_rows")
    _require_equal(manifest["artifact_count"], 7, "packet_manifest:artifact_count")

    expected_binding, stage1_seed, stage1_request = _validated_stage1_inputs(
        Path(source_first_manifest_path),
        source_path=Path(source_path),
    )
    stage1_binding = payloads["DETACHED_STAGE1_INPUT_BINDING"]
    _require_equal(stage1_binding, expected_binding, "packet:stage1_binding_closed_equality")
    _verify_content(stage1_binding, domain=STAGE1_BINDING_DOMAIN, label="packet.stage1_binding")
    corpus = payloads["CLOSED_SYNTHETIC_QUARANTINED_CORPUS"]
    _validate_corpus(corpus)
    request = compile_a0_request_from_stage1(
        stage1_binding,
        stage1_seed,
        stage1_request,
    )
    expected_program = compile_retrieval_program(request, corpus)
    program = payloads["PHASE_SAFE_RETRIEVAL_PROGRAM"]
    _require_equal(program, expected_program, "packet:retrieval_program_closed_equality")
    _validate_private_projection_binding(corpus, expected_program)
    scores, selections, rejections = execute_phase_projection_candidate(
        expected_program
    )
    _require_equal(payloads["SCORED_CANDIDATE_LEDGER"], scores, "packet:score_ledger_closed_equality")
    _require_equal(payloads["SELECTION_LEDGER"], selections, "packet:selection_ledger_closed_equality")
    _require_equal(payloads["REJECTION_ZERO_HIT_LEDGER"], rejections, "packet:rejection_ledger_closed_equality")
    expected_report = compile_local_replay_report(
        stage1_binding=stage1_binding,
        corpus_bundle=corpus,
        retrieval_program=program,
        score_ledger=scores,
        selection_ledger=selections,
        rejection_ledger=rejections,
    )
    _require_equal(payloads["LOCAL_REPLAY_REPORT"], expected_report, "packet:replay_report_closed_equality")
    expected_manifest = compile_packet_manifest(
        artifact_rows=rows,
        stage1_binding=stage1_binding,
        corpus_bundle=corpus,
        retrieval_program=program,
    )
    _require_equal(manifest, expected_manifest, "packet_manifest:closed_equality")
    return manifest


def write_phase_safe_retrieval_offline_candidate_packet(
    output_root: Path,
    *,
    source_first_manifest_path: Path,
    source_path: Path,
    corpus_objects: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    stage1_binding, stage1_seed, stage1_request = _validated_stage1_inputs(
        Path(source_first_manifest_path),
        source_path=Path(source_path),
    )
    corpus = compile_offline_corpus(corpus_objects)
    request = compile_a0_request_from_stage1(
        stage1_binding,
        stage1_seed,
        stage1_request,
    )
    program = compile_retrieval_program(request, corpus)
    _validate_private_projection_binding(corpus, program)
    scores, selections, rejections = execute_phase_projection_candidate(program)
    report = compile_local_replay_report(
        stage1_binding=stage1_binding,
        corpus_bundle=corpus,
        retrieval_program=program,
        score_ledger=scores,
        selection_ledger=selections,
        rejection_ledger=rejections,
    )
    artifacts = (
        ("00_stage1_input_binding.json", "DETACHED_STAGE1_INPUT_BINDING", stage1_binding),
        ("01_closed_corpus_bundle.json", "CLOSED_SYNTHETIC_QUARANTINED_CORPUS", corpus),
        ("02_retrieval_program.json", "PHASE_SAFE_RETRIEVAL_PROGRAM", program),
        ("03_scored_candidate_ledger.json", "SCORED_CANDIDATE_LEDGER", scores),
        ("04_selection_ledger.json", "SELECTION_LEDGER", selections),
        ("05_rejection_and_zero_hit_ledger.json", "REJECTION_ZERO_HIT_LEDGER", rejections),
        ("06_local_replay_report.json", "LOCAL_REPLAY_REPORT", report),
    )

    root = Path(output_root)
    _require(
        root.is_absolute() and root.name not in {"", ".", ".."} and ".." not in root.parts,
        "output_root:invalid",
    )
    parent = root.parent.resolve(strict=True)
    parent_descriptor = _open_absolute_directory_fd(parent)
    staging_descriptor: int | None = None
    try:
        _require(not _entry_exists_at(parent_descriptor, root.name), "output_root:exists")
        staging_name = _create_staging_directory(parent_descriptor)
        staging_root = parent / staging_name
        staging_descriptor = os.open(
            staging_name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_descriptor,
        )
        pinned = os.fstat(staging_descriptor)
        _require(
            stat.S_ISDIR(pinned.st_mode) and not stat.S_IMODE(pinned.st_mode) & 0o077,
            "staging:not_private",
        )
        for name, _, payload in artifacts:
            write_workspace_json_once(staging_root, name, payload)
        rows = [
            _stable_file_row(staging_root / name, ordinal=ordinal, role=role)
            for ordinal, (name, role, _) in enumerate(artifacts)
        ]
        manifest = compile_packet_manifest(
            artifact_rows=rows,
            stage1_binding=stage1_binding,
            corpus_bundle=corpus,
            retrieval_program=program,
        )
        write_workspace_json_once(staging_root, "packet_manifest.json", manifest)
        validate_phase_safe_retrieval_offline_candidate_packet(
            staging_root / "packet_manifest.json",
            source_first_manifest_path=Path(source_first_manifest_path),
            source_path=Path(source_path),
        )
        _validate_staging_closure(
            staging_descriptor,
            expected_names={"packet_manifest.json", *(row["path"] for row in rows)},
        )
        current = os.stat(staging_name, dir_fd=parent_descriptor, follow_symlinks=False)
        _require_equal(
            (current.st_dev, current.st_ino),
            (pinned.st_dev, pinned.st_ino),
            "staging:identity_changed",
        )
        _require(not _entry_exists_at(parent_descriptor, root.name), "output_root:race")
        os.fsync(staging_descriptor)
        _atomic_publish_directory_noreplace_at(parent_descriptor, staging_name, root.name)
        os.fsync(parent_descriptor)
        return manifest
    finally:
        if staging_descriptor is not None:
            os.close(staging_descriptor)
        os.close(parent_descriptor)
