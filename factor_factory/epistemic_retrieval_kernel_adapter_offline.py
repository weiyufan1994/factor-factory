from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import stat
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from factor_factory.epistemic_phase_safe_retrieval_offline import (
    FOUR_LANES,
    PHASE_CORPUS_FIELDS,
    compile_offline_corpus,
    compile_phase_request_candidate,
    compile_retrieval_program,
    execute_phase_projection_candidate,
    validate_phase_safe_retrieval_bundle,
)
from factor_factory.knowledge_context import (
    resolve_graph_node_path,
    score_text,
)
from factor_factory.epistemic_source_first_kernel_adapter_offline import (
    FORMALIZATION_SEMANTIC_FIELDS,
    INPUT_DEFINITIONS,
    compile_source_first_kernel_session_candidate,
    validate_source_first_kernel_session_candidate,
)
from factor_factory.research_org.contracts import strict_json_loads
from factor_factory.research_org.rfc8785_canonical import framed_sha256


SCHEMA_ID = "factorforge_epistemic_retrieval_agent_projection_v1"
SCHEMA_VERSION = "1.0.0"
RESULT_SCHEMA_ID = "factorforge_epistemic_retrieval_kernel_adapter_result_candidate_v2"
RESULT_SCHEMA_VERSION = "2.0.0"
RESULT_CONTENT_DOMAIN = "FF_EPISTEMIC_RETRIEVAL_KERNEL_ADAPTER_RESULT_CANDIDATE_V2"
CANONICAL_QUERY_DOMAIN = "FF_EPISTEMIC_RETRIEVAL_CANONICAL_QUERY_V2"
SANITIZED_OBJECT_DOMAIN = "FF_EPISTEMIC_RETRIEVAL_SANITIZED_OBJECT_V2"
PRECEDENT_GROUP_DOMAIN = "FF_EPISTEMIC_RETRIEVAL_PRECEDENT_GROUP_V1"
GRAPH_RAW_BYTES_DOMAIN = "FF_EPISTEMIC_RETRIEVAL_GRAPH_RAW_BYTES_IDENTITY_V1"
REAL_PROJECTED_PRECEDENT_DOMAIN = (
    "FF_EPISTEMIC_RETRIEVAL_REAL_PROJECTED_PRECEDENT_V1"
)
SOURCE_NODE_RAW_BYTES_DOMAIN = (
    "FF_EPISTEMIC_RETRIEVAL_SOURCE_NODE_RAW_BYTES_IDENTITY_V1"
)
HYPOTHESIS_FREEZE_DOMAIN = "FF_EPISTEMIC_RETRIEVAL_HYPOTHESIS_FREEZE_V1"
AUTHORITY_EFFECT = "NONE"

A0 = "A0_MECHANISM_PRIOR"
A1 = "A1_IMPLEMENTATION_FEASIBILITY"
SUPPORTED_PHASES = (A0, A1)

_A1_REQUEST_FIELDS = {
    "phase_branch",
    "phase_input",
    "phase_policy",
    "hypothesis_freeze",
}
_HYPOTHESIS_FREEZE_FIELDS = {"freeze_status", "hypothesis_semantics"}
_SOURCE_FIRST_INPUT_FIELDS = {name for name, _profile in INPUT_DEFINITIONS}
_RESULT_FIELDS = {
    "schema_id",
    "schema_version",
    "phase_branch",
    "agent_visible_projection",
    "private_replay_binding",
    "signed",
    "candidate_only",
    "authority_effect",
    "content_sha256",
}
_PRIVATE_REPLAY_FIELDS = {
    "binding_version",
    "retrieval_mode",
    "source_first_content_sha256",
    "source_first_input_binding_content_sha256",
    "source_first_a0_request_content_sha256",
    "canonical_query",
    "hypothesis_freeze_content_sha256",
    "retrieval_input",
    "filtering_counts",
    "selected_sanitized_objects",
    "agent_visible_projection_content_sha256",
}
_CANONICAL_QUERY_FIELDS = {"query_mode", "phase_branch", "query_value", "content_sha256"}
_SELECTED_BINDING_FIELDS = {
    "ordinal",
    "lane",
    "handle",
    "precedent_group_handle",
    "eligible_lanes",
    "lane_role_rationale",
    "sanitized_object_content_sha256",
}
_SYNTHETIC_INPUT_BINDING_FIELDS = {
    "input_mode",
    "compiled_corpus_content_sha256",
    "compiled_request_content_sha256",
    "corpus_object_count",
}
_REAL_INPUT_BINDING_FIELDS = {
    "input_mode",
    "node_index_raw_bytes_identity",
    "edge_index_raw_bytes_identity",
    "taxonomy_raw_bytes_identity",
    "source_node_raw_bytes_identity",
    "graph_raw_bytes_identity",
}
_RAW_BYTES_IDENTITY_FIELDS = {"byte_count", "raw_sha256"}
_SOURCE_NODE_IDENTITY_FIELDS = {
    "source_node_count",
    "rows",
    "content_sha256",
}
_SOURCE_NODE_IDENTITY_ROW_FIELDS = {"ordinal", "byte_count", "raw_sha256"}
_SYNTHETIC_FILTER_COUNT_FIELDS = {
    "input_object_count",
    "phase_projected_object_count",
    "phase_admissible_object_count",
    "phase_quarantined_object_count",
    "scored_object_count",
    "rejected_object_count",
    "selected_unique_object_count",
    "selected_lane_item_count",
}
_REAL_FILTER_COUNT_FIELDS = {
    "indexed_row_count",
    "source_node_read_count",
    "strict_projection_count",
    "strict_projection_rejected_count",
    "lane_admissible_candidate_count",
    "no_lane_candidate_count",
    "positive_score_candidate_count",
    "zero_score_candidate_count",
    "selected_unique_object_count",
    "selected_lane_item_count",
}
_ROOT_FIELDS = {
    "schema_id",
    "schema_version",
    "phase_branch",
    "result",
    "lanes",
    "use_scope",
    "advisory_only",
    "candidate_only",
    "authority_effect",
}
_LANE_FIELDS = {"lane", "items"}
_A0_ITEM_FIELDS = {
    "handle",
    "precedent_group_handle",
    "eligible_lanes",
    "lane_role_rationale",
    "mechanism",
    "mathematical_analogy",
    "falsifiers",
    "applicability",
    "information_preserved",
    "information_lost",
    "advisory",
    "advisory_only",
}
_A1_ITEM_FIELDS = {
    *_A0_ITEM_FIELDS,
    "implementation_feasibility",
    "operator_requirements",
    "evidence_requirements",
    "numerical_constraints",
    "testability",
    "failure_modes",
    "episode_context",
}

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_HANDLE_RE = re.compile(r"ctx_[A-Za-z0-9_-]{43}\Z")
_GROUP_HANDLE_RE = re.compile(r"grp_[A-Za-z0-9_-]{43}\Z")
_URI_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]{1,15}://")
_ABSOLUTE_PATH_RE = re.compile(
    r"(?:^|\s)(?:/[^\s]+|~/[^\s]+|[A-Za-z]:\\[^\s]+)"
)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_DIGEST_RE = re.compile(
    r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})(?![0-9a-fA-F])"
)
_STABLE_NAMESPACE_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_-]{1,31}::")
_RAW_CODE_RE = re.compile(
    r"```|(?:^|\s)(?:def|class|import|from)\s+[A-Za-z_]|"
    r"(?:^|\s)SELECT\s+.+\s+FROM\s+|(?:^|\s)(?:np|pd)\.[A-Za-z_]",
    re.IGNORECASE,
)
_A0_BACKEND_TEXT_RE = re.compile(
    r"\b(?:code|implementation|data|dataset|data\s+source|table\s+name|column\s+name|"
    r"api\s+endpoint|index\s+(?:health|status|availability)|failure\s+record|"
    r"failure|episode|episode\s+id)\b|代码|实现细节|数据|数据源|数据集|表名|字段名|"
    r"接口地址|索引状态|索引可用性|失败记录|历史记录|历史片段",
    re.IGNORECASE,
)
_A0_PERFORMANCE_TEXT_RE = re.compile(
    r"\b(?:sharpe|pnl|oos|out[- ]of[- ]sample|rank\s*ic|information\s+coefficient|"
    r"backtest|turnover|drawdown|performance|promotion|admission|accepted|rejected|"
    r"annualized?\s+return|long[- ]side\s+return)\b|"
    r"夏普|净值|样本外|信息系数|回测|换手率|回撤|业绩指标|正式晋升|正式录用",
    re.IGNORECASE,
)
_STABLE_KNOWLEDGE_ID_RE = re.compile(
    r"\b(?:alpha|factor|report|research|run)[-_]?[A-Z0-9]{2,}\b",
    re.IGNORECASE,
)
_OOS_COMPONENT_PREFIXES = ("oos", "out_of_sample")
_INFORMATION_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？;；])\s*")
_INFORMATION_CONTRAST_SPLIT_RE = re.compile(
    r"\s*(?:,\s*)?(?:\b(?:while|whereas|but)\b|但(?:是)?|而(?:是)?)\s*",
    re.IGNORECASE,
)
_INFORMATION_MARKED_AND_SPLIT_RE = re.compile(
    r"\s+(?:\band\b|并且?|同时)\s+(?=(?:it\s+)?(?:"
    r"preserv\w*|retain\w*|keep\w*|captur\w*|"
    r"remov\w*|los\w*|alias\w*|delet\w*|compress\w*|distort\w*|"
    r"保留|保持|捕捉|保存|移除|丢失|混叠|删除|压缩|扭曲))",
    re.IGNORECASE,
)
_INFORMATION_PRESERVED_RE = re.compile(
    r"\b(?:preserv\w*|retain\w*|keep\w*|captur\w*)\b|保留|保持|捕捉|保存",
    re.IGNORECASE,
)
_INFORMATION_LOST_RE = re.compile(
    r"\b(?:remov\w*|los\w*|alias\w*|delet\w*|compress\w*|distort\w*)\b|"
    r"移除|丢失|混叠|删除|压缩|扭曲",
    re.IGNORECASE,
)
_EPISODE_CONTEXT_RE = re.compile(
    r"\b(?:historical|episode|market\s+state|prior\s+period|regime)\b|"
    r"历史情景|历史阶段|市场状态|既往阶段|历史片段",
    re.IGNORECASE,
)
_FORBIDDEN_PRIVATE_KEY_PARTS = (
    "object_id",
    "content_sha",
    "payload_sha",
    "corpus",
    "native",
    "score",
    "rejection",
    "index",
    "availability",
    "health",
)
_A0_FORBIDDEN_KEY_PARTS = (
    "implementation",
    "operator",
    "evidence_requirement",
    "observation",
    "data",
    "failure_mode",
    "episode",
    "code",
)

_LANE_ROLE_RATIONALES = {
    "structural_isomorph": "shared causal structure and payer boundary",
    "cross_math_analogy": "alternative mathematical representation with explicit information tradeoffs",
    "near_miss_failure": "near miss boundary and information loss challenge",
    "direct_counterexample": "falsifier and counterexample challenge",
}


class EpistemicRetrievalKernelAdapterError(ValueError):
    pass


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise EpistemicRetrievalKernelAdapterError(label)


def _closed_mapping(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label}:object_required")
    _require(set(value) == expected, f"{label}:closed_fields")
    return value


def _array(value: Any, label: str) -> Sequence[Any]:
    _require(
        isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)),
        f"{label}:array_required",
    )
    return value


def _visible_text(value: Any, label: str, *, phase_branch: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{label}:nonempty_text")
    result = unicodedata.normalize("NFKC", value.strip())
    _require("\x00" not in result, f"{label}:nul_forbidden")
    _require(len(result.encode("utf-8")) <= 4096, f"{label}:too_large")
    _require(_URI_RE.search(result) is None, f"{label}:uri_forbidden")
    _require(_ABSOLUTE_PATH_RE.search(result) is None, f"{label}:absolute_path_forbidden")
    _require(_UUID_RE.search(result) is None, f"{label}:uuid_forbidden")
    _require(_DIGEST_RE.search(result) is None, f"{label}:digest_forbidden")
    _require(_STABLE_NAMESPACE_RE.search(result) is None, f"{label}:stable_namespace_forbidden")
    _require("fixture-local-" not in result, f"{label}:stable_object_id_forbidden")
    _require(_RAW_CODE_RE.search(result) is None, f"{label}:raw_code_forbidden")
    _require(
        not _contains_oos_text(result),
        f"{label}:oos_knowledge_forbidden",
    )
    if phase_branch == A0:
        _require(
            _A0_BACKEND_TEXT_RE.search(result) is None,
            f"{label}:a0_backend_knowledge_forbidden",
        )
        _require(
            _A0_PERFORMANCE_TEXT_RE.search(result) is None,
            f"{label}:a0_performance_knowledge_forbidden",
        )
    return result


def _text_array(value: Any, label: str, *, phase_branch: str) -> list[str]:
    rows = _array(value, label)
    output = [
        _visible_text(item, f"{label}[{ordinal}]", phase_branch=phase_branch)
        for ordinal, item in enumerate(rows)
    ]
    _require(len(output) == len(set(output)), f"{label}:duplicate")
    return output


def _semantic_texts(payload: Mapping[str, Any], field: str) -> list[str]:
    return [str(row["semantic_text"]) for row in payload.get(field, [])]


def _unique_texts(*groups: Sequence[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            if value not in seen:
                seen.add(value)
                output.append(value)
    return output


def _opaque_handle(
    *,
    secret: bytes,
    phase_branch: str,
    request_content_sha256: str,
    object_id: str,
    object_content_sha256: str,
    lane: str = "",
) -> str:
    preimage = b"\x00".join(
        (
            b"FF_EPISTEMIC_RETRIEVAL_SESSION_HANDLE_V1",
            phase_branch.encode("utf-8"),
            request_content_sha256.encode("ascii"),
            object_id.encode("utf-8"),
            object_content_sha256.encode("ascii"),
            lane.encode("utf-8"),
        )
    )
    digest = hmac.new(secret, preimage, hashlib.sha256).digest()
    return "ctx_" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _opaque_precedent_group_handle(
    *,
    secret: bytes,
    phase_branch: str,
    request_content_sha256: str,
    object_id: str,
    precedent_group_content_sha256: str,
) -> str:
    preimage = b"\x00".join(
        (
            b"FF_EPISTEMIC_RETRIEVAL_PRECEDENT_GROUP_HANDLE_V1",
            phase_branch.encode("utf-8"),
            request_content_sha256.encode("ascii"),
            object_id.encode("utf-8"),
            precedent_group_content_sha256.encode("ascii"),
        )
    )
    digest = hmac.new(secret, preimage, hashlib.sha256).digest()
    return "grp_" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _project_common_item(
    *,
    handle: str,
    semantic_payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "handle": handle,
        "mechanism": _unique_texts(
            _semantic_texts(semantic_payload, "economic_game_semantics"),
            _semantic_texts(semantic_payload, "latent_mechanism_semantics"),
        ),
        "mathematical_analogy": _semantic_texts(
            semantic_payload, "mathematical_family_semantics"
        ),
        "falsifiers": _semantic_texts(semantic_payload, "falsifier_semantics"),
        "applicability": _semantic_texts(
            semantic_payload, "applicability_boundary_semantics"
        ),
        "information_preserved": _semantic_texts(
            semantic_payload, "information_preserved_semantics"
        ),
        "information_lost": _semantic_texts(
            semantic_payload, "information_lost_semantics"
        ),
        "advisory": _semantic_texts(semantic_payload, "advisory_semantics"),
        "advisory_only": True,
    }


def _project_item(
    *,
    phase_branch: str,
    handle: str,
    semantic_payload: Mapping[str, Any],
) -> dict[str, Any]:
    item = _project_common_item(handle=handle, semantic_payload=semantic_payload)
    if phase_branch == A1:
        advisory = _semantic_texts(semantic_payload, "advisory_semantics")
        applicability = _semantic_texts(
            semantic_payload, "applicability_boundary_semantics"
        )
        information_lost = _semantic_texts(
            semantic_payload, "information_lost_semantics"
        )
        item.update(
            {
                "implementation_feasibility": _semantic_texts(
                    semantic_payload, "implementation_feasibility_semantics"
                ),
                "operator_requirements": _semantic_texts(
                    semantic_payload, "operator_requirement_semantics"
                ),
                "evidence_requirements": _semantic_texts(
                    semantic_payload, "observation_and_data_semantics"
                ),
                "numerical_constraints": _semantic_texts(
                    semantic_payload, "numerical_constraint_semantics"
                ),
                "testability": _semantic_texts(
                    semantic_payload, "testability_semantics"
                ),
                "failure_modes": _unique_texts(
                    _semantic_texts(semantic_payload, "falsifier_semantics"),
                    information_lost,
                ),
                "episode_context": [
                    text
                    for text in _unique_texts(advisory, applicability)
                    if _EPISODE_CONTEXT_RE.search(text) is not None
                ],
            }
        )
    return item


def _result_token(native_result: str) -> str:
    mapping = {
        "OFFLINE_RETURNED_CANDIDATES": "HIT",
        "OFFLINE_ZERO_HIT_CANDIDATE": "ZERO_HIT",
        "OFFLINE_NO_ADMISSIBLE_CANDIDATE_CLOSURE": "NO_ADMISSIBLE_CANDIDATE",
    }
    _require(native_result in mapping, "native_result:unknown")
    return mapping[native_result]


def _replay_source_first(
    *,
    source_first_candidate: Mapping[str, Any],
    source_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute Source-First from all eight raw inputs; never trust a bare hash."""

    inputs = _closed_mapping(
        source_inputs,
        _SOURCE_FIRST_INPUT_FIELDS,
        "source_inputs",
    )
    _require(
        isinstance(source_first_candidate, Mapping),
        "source_first_candidate:object_required_not_bare_digest",
    )
    replay = validate_source_first_kernel_session_candidate(
        source_first_candidate,
        **dict(inputs),
    )
    independently_compiled = compile_source_first_kernel_session_candidate(
        **dict(inputs)
    )
    _require(
        replay == independently_compiled == dict(source_first_candidate),
        "source_first_candidate:independent_full_replay_equality",
    )
    private = replay["artifacts"]["a0_request_candidate"].get(
        "private_preissuance_request_candidate"
    )
    _require(
        isinstance(private, Mapping)
        and replay["artifacts"]["a0_request_candidate"]["request_branch"]
        == "A0_HOST_PREISSUANCE_CANDIDATE",
        "source_first_candidate:eligible_a0_request_required",
    )
    return replay


def _plain_source_a0_request(source_first: Mapping[str, Any]) -> dict[str, Any]:
    private = source_first["artifacts"]["a0_request_candidate"][
        "private_preissuance_request_candidate"
    ]
    typed_query = private["query_semantics_candidate"]
    source_policy = private["phase_policy_candidate"]
    return {
        "phase_branch": A0,
        "phase_input": {
            field: [row["semantic_text"] for row in rows]
            for field, rows in typed_query.items()
        },
        "phase_policy": {
            "policy_version": "phase-safe-offline-candidate-v1",
            "phase_branch": A0,
            "requested_lane_subset": list(source_policy["requested_lane_subset"]),
            "top_k_per_lane": source_policy["top_k_per_lane"],
        },
    }


def _source_first_real_query(source_first: Mapping[str, Any]) -> str:
    seed = source_first["artifacts"]["blind_mechanism_seed"]["seed_body"]
    _require(
        seed.get("seed_branch") == "BLIND_MECHANISM_SEED_CANDIDATE",
        "source_first_candidate:blind_seed_required",
    )
    fingerprint = seed["mechanism_fingerprint"]
    return unicodedata.normalize(
        "NFKC",
        "\n".join(
            [
                fingerprint["economic_claim"],
                fingerprint["payer_or_constraint"],
                fingerprint["mathematical_object"],
                fingerprint["broken_invariant_or_boundary"],
                fingerprint["observation_mapping"],
                fingerprint["failure_signature"],
                *seed["falsifiers"],
                *seed["material_rivals"],
            ]
        ).strip(),
    )


def _compile_hypothesis_freeze_binding(
    value: Any,
    *,
    source_first_content_sha256: str,
) -> str:
    freeze = _closed_mapping(
        value,
        _HYPOTHESIS_FREEZE_FIELDS,
        "hypothesis_freeze",
    )
    _require(freeze["freeze_status"] == "FROZEN", "hypothesis_freeze.status")
    semantics = _text_array(
        freeze["hypothesis_semantics"],
        "hypothesis_freeze.hypothesis_semantics",
        phase_branch=A1,
    )
    _require(bool(semantics), "hypothesis_freeze.hypothesis_semantics:min_items=1")
    return framed_sha256(
        HYPOTHESIS_FREEZE_DOMAIN,
        {
            "freeze_status": "FROZEN",
            "hypothesis_semantics": semantics,
            "source_first_content_sha256": source_first_content_sha256,
        },
    )


def _canonical_query_binding(
    *,
    query_mode: str,
    phase_branch: str,
    query_value: Any,
) -> dict[str, Any]:
    core = {
        "query_mode": query_mode,
        "phase_branch": phase_branch,
        "query_value": query_value,
    }
    return {**core, "content_sha256": framed_sha256(CANONICAL_QUERY_DOMAIN, core)}


def _sanitized_object_digest(
    *, phase_branch: str, lane: str, item_without_handle: Mapping[str, Any]
) -> str:
    return framed_sha256(
        SANITIZED_OBJECT_DOMAIN,
        {
            "phase_branch": phase_branch,
            "lane": lane,
            "agent_visible_item_without_handle": dict(item_without_handle),
        },
    )


def _decorate_precedent_for_lane(
    *,
    secret: bytes,
    phase_branch: str,
    request_content_sha256: str,
    object_id: str,
    lane: str,
    eligible_lanes: Sequence[str],
    semantic_item_without_handles: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    ordered_lanes = [candidate for candidate in FOUR_LANES if candidate in eligible_lanes]
    _require(bool(ordered_lanes), "precedent_group.eligible_lanes:min_items=1")
    _require(lane in ordered_lanes, "precedent_group.current_lane_ineligible")
    _require(
        list(eligible_lanes) == ordered_lanes,
        "precedent_group.eligible_lanes:canonical_unique_known",
    )
    group_content_sha256 = framed_sha256(
        PRECEDENT_GROUP_DOMAIN,
        {
            "phase_branch": phase_branch,
            "semantic_item_without_handles": dict(semantic_item_without_handles),
        },
    )
    group_handle = _opaque_precedent_group_handle(
        secret=secret,
        phase_branch=phase_branch,
        request_content_sha256=request_content_sha256,
        object_id=object_id,
        precedent_group_content_sha256=group_content_sha256,
    )
    item_without_lane_handle = {
        "precedent_group_handle": group_handle,
        "eligible_lanes": ordered_lanes,
        "lane_role_rationale": [_LANE_ROLE_RATIONALES[lane]],
        **dict(semantic_item_without_handles),
    }
    sanitized_digest = _sanitized_object_digest(
        phase_branch=phase_branch,
        lane=lane,
        item_without_handle=item_without_lane_handle,
    )
    _require(
        sanitized_digest != request_content_sha256,
        "opaque_handle:object_digest_must_not_be_query_digest",
    )
    handle = _opaque_handle(
        secret=secret,
        phase_branch=phase_branch,
        request_content_sha256=request_content_sha256,
        object_id=object_id,
        object_content_sha256=sanitized_digest,
        lane=lane,
    )
    item = {"handle": handle, **item_without_lane_handle}
    private = {
        "ordinal": -1,
        "lane": lane,
        "handle": handle,
        "precedent_group_handle": group_handle,
        "eligible_lanes": ordered_lanes,
        "lane_role_rationale": [_LANE_ROLE_RATIONALES[lane]],
        "sanitized_object_content_sha256": sanitized_digest,
    }
    return item, private


def _build_agent_projection(
    *, phase_branch: str, result: str, selected_by_lane: Mapping[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    projection = {
        "schema_id": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "phase_branch": phase_branch,
        "result": result,
        "lanes": [
            {"lane": lane, "items": selected_by_lane[lane]}
            for lane in FOUR_LANES
        ],
        "use_scope": (
            "STEP1_MECHANISM_PRIOR_ADVISORY_ONLY"
            if phase_branch == A0
            else "POST_HYPOTHESIS_FREEZE_ADVISORY_ONLY"
        ),
        "advisory_only": True,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    validate_epistemic_retrieval_agent_projection(projection)
    return projection


def _lane_ordered_selected_bindings(
    projection: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_handle = {str(row["handle"]): row for row in rows}
    ordered: list[dict[str, Any]] = []
    for lane in projection["lanes"]:
        for item in lane["items"]:
            source = by_handle.get(item["handle"])
            _require(source is not None, "selected_sanitized_objects:handle_missing")
            ordered.append(
                {
                    "ordinal": len(ordered),
                    "lane": lane["lane"],
                    "handle": item["handle"],
                    "precedent_group_handle": item["precedent_group_handle"],
                    "eligible_lanes": list(item["eligible_lanes"]),
                    "lane_role_rationale": list(item["lane_role_rationale"]),
                    "sanitized_object_content_sha256": source[
                        "sanitized_object_content_sha256"
                    ],
                }
            )
    _require(len(ordered) == len(rows), "selected_sanitized_objects:handle_partition")
    return ordered


def _adapter_result(
    *,
    phase_branch: str,
    projection: Mapping[str, Any],
    private_replay_binding: Mapping[str, Any],
) -> dict[str, Any]:
    core = {
        "schema_id": RESULT_SCHEMA_ID,
        "schema_version": RESULT_SCHEMA_VERSION,
        "phase_branch": phase_branch,
        "agent_visible_projection": dict(projection),
        "private_replay_binding": dict(private_replay_binding),
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    result = {
        **core,
        "content_sha256": framed_sha256(RESULT_CONTENT_DOMAIN, core),
    }
    _validate_epistemic_retrieval_kernel_adapter_result_structure(result)
    return result


def validate_epistemic_retrieval_agent_projection(
    projection: Mapping[str, Any],
) -> None:
    root = _closed_mapping(projection, _ROOT_FIELDS, "projection")
    _require(root["schema_id"] == SCHEMA_ID, "projection.schema_id")
    _require(root["schema_version"] == SCHEMA_VERSION, "projection.schema_version")
    phase_branch = root["phase_branch"]
    _require(phase_branch in SUPPORTED_PHASES, "projection.phase_branch")
    _require(
        root["result"] in {"HIT", "ZERO_HIT", "NO_ADMISSIBLE_CANDIDATE"},
        "projection.result",
    )
    expected_scope = (
        "STEP1_MECHANISM_PRIOR_ADVISORY_ONLY"
        if phase_branch == A0
        else "POST_HYPOTHESIS_FREEZE_ADVISORY_ONLY"
    )
    _require(root["use_scope"] == expected_scope, "projection.use_scope")
    _require(root["advisory_only"] is True, "projection.advisory_only")
    _require(root["candidate_only"] is True, "projection.candidate_only")
    _require(root["authority_effect"] == AUTHORITY_EFFECT, "projection.authority_effect")

    lane_rows = list(_array(root["lanes"], "projection.lanes"))
    _require(len(lane_rows) == len(FOUR_LANES), "projection.lanes:exact4")
    seen_handles: set[str] = set()
    expected_item_fields = _A0_ITEM_FIELDS if phase_branch == A0 else _A1_ITEM_FIELDS
    for ordinal, raw_lane in enumerate(lane_rows):
        lane = _closed_mapping(raw_lane, _LANE_FIELDS, f"projection.lanes[{ordinal}]")
        _require(lane["lane"] == FOUR_LANES[ordinal], f"projection.lanes[{ordinal}].lane")
        for item_ordinal, raw_item in enumerate(
            _array(lane["items"], f"projection.lanes[{ordinal}].items")
        ):
            label = f"projection.lanes[{ordinal}].items[{item_ordinal}]"
            item = _closed_mapping(raw_item, expected_item_fields, label)
            handle = item["handle"]
            _require(
                isinstance(handle, str) and _HANDLE_RE.fullmatch(handle) is not None,
                f"{label}.handle",
            )
            _require(handle not in seen_handles, f"{label}.handle:duplicate")
            seen_handles.add(handle)
            group_handle = item["precedent_group_handle"]
            _require(
                isinstance(group_handle, str)
                and _GROUP_HANDLE_RE.fullmatch(group_handle) is not None,
                f"{label}.precedent_group_handle",
            )
            eligible_lanes = list(_array(item["eligible_lanes"], f"{label}.eligible_lanes"))
            _require(
                eligible_lanes
                == [candidate for candidate in FOUR_LANES if candidate in eligible_lanes]
                and lane["lane"] in eligible_lanes,
                f"{label}.eligible_lanes:canonical_and_current",
            )
            rationale = _text_array(
                item["lane_role_rationale"],
                f"{label}.lane_role_rationale",
                phase_branch=phase_branch,
            )
            _require(
                rationale == [_LANE_ROLE_RATIONALES[lane["lane"]]],
                f"{label}.lane_role_rationale:equality",
            )
            _require(item["advisory_only"] is True, f"{label}.advisory_only")
            for field in sorted(
                expected_item_fields
                - {
                    "handle",
                    "precedent_group_handle",
                    "eligible_lanes",
                    "lane_role_rationale",
                    "advisory_only",
                }
            ):
                _text_array(item[field], f"{label}.{field}", phase_branch=phase_branch)

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                lowered = str(key).casefold()
                _require(
                    not any(token in lowered for token in _FORBIDDEN_PRIVATE_KEY_PARTS),
                    f"{path}.{key}:private_key_forbidden",
                )
                if phase_branch == A0:
                    _require(
                        not any(token in lowered for token in _A0_FORBIDDEN_KEY_PARTS),
                        f"{path}.{key}:a0_key_forbidden",
                    )
                walk(child, f"{path}.{key}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for ordinal, child in enumerate(value):
                walk(child, f"{path}[{ordinal}]")
        elif (
            isinstance(value, str)
            and not _HANDLE_RE.fullmatch(value)
            and not _GROUP_HANDLE_RE.fullmatch(value)
        ):
            _require(_DIGEST_RE.search(value) is None, f"{path}:digest_forbidden")
            _require("fixture-local-" not in value, f"{path}:stable_object_id_forbidden")
            _require(_STABLE_NAMESPACE_RE.search(value) is None, f"{path}:stable_namespace_forbidden")

    walk(root, "projection")


def _validate_raw_bytes_identity(value: Any, label: str) -> None:
    identity = _closed_mapping(value, _RAW_BYTES_IDENTITY_FIELDS, label)
    _require(
        type(identity["byte_count"]) is int and identity["byte_count"] >= 0,
        f"{label}.byte_count",
    )
    _require(
        isinstance(identity["raw_sha256"], str)
        and _SHA256_RE.fullmatch(identity["raw_sha256"]) is not None,
        f"{label}.raw_sha256",
    )


def _validate_epistemic_retrieval_kernel_adapter_result_structure(
    result: Mapping[str, Any],
) -> None:
    root = _closed_mapping(result, _RESULT_FIELDS, "adapter_result")
    _require(root["schema_id"] == RESULT_SCHEMA_ID, "adapter_result.schema_id")
    _require(
        root["schema_version"] == RESULT_SCHEMA_VERSION,
        "adapter_result.schema_version",
    )
    _require(root["phase_branch"] in SUPPORTED_PHASES, "adapter_result.phase_branch")
    _require(root["signed"] is False, "adapter_result.signed")
    _require(root["candidate_only"] is True, "adapter_result.candidate_only")
    _require(root["authority_effect"] == AUTHORITY_EFFECT, "adapter_result.authority_effect")
    _require(
        isinstance(root["content_sha256"], str)
        and _SHA256_RE.fullmatch(root["content_sha256"]) is not None,
        "adapter_result.content_sha256",
    )
    core = {key: value for key, value in root.items() if key != "content_sha256"}
    _require(
        root["content_sha256"] == framed_sha256(RESULT_CONTENT_DOMAIN, core),
        "adapter_result.content_sha256:replay",
    )

    projection = root["agent_visible_projection"]
    validate_epistemic_retrieval_agent_projection(projection)
    _require(
        projection["phase_branch"] == root["phase_branch"],
        "adapter_result.phase_projection_equality",
    )
    binding = _closed_mapping(
        root["private_replay_binding"],
        _PRIVATE_REPLAY_FIELDS,
        "private_replay_binding",
    )
    _require(binding["binding_version"] == "1.0.0", "private_replay_binding.version")
    mode = binding["retrieval_mode"]
    _require(mode in {"SYNTHETIC_CORPUS", "REAL_KNOWLEDGE_GRAPH"}, "private_replay_binding.mode")
    for field in (
        "source_first_content_sha256",
        "source_first_input_binding_content_sha256",
        "source_first_a0_request_content_sha256",
        "agent_visible_projection_content_sha256",
    ):
        _require(
            isinstance(binding[field], str)
            and _SHA256_RE.fullmatch(binding[field]) is not None,
            f"private_replay_binding.{field}",
        )
    _require(
        binding["agent_visible_projection_content_sha256"]
        == framed_sha256("FF_EPISTEMIC_RETRIEVAL_AGENT_PROJECTION_V1", projection),
        "private_replay_binding.agent_visible_projection_content_sha256:replay",
    )
    freeze_digest = binding["hypothesis_freeze_content_sha256"]
    if root["phase_branch"] == A0:
        _require(freeze_digest is None, "private_replay_binding.a0_freeze_forbidden")
    else:
        _require(
            isinstance(freeze_digest, str)
            and _SHA256_RE.fullmatch(freeze_digest) is not None,
            "private_replay_binding.a1_freeze_required",
        )

    query = _closed_mapping(
        binding["canonical_query"],
        _CANONICAL_QUERY_FIELDS,
        "private_replay_binding.canonical_query",
    )
    _require(query["phase_branch"] == root["phase_branch"], "canonical_query.phase")
    query_core = {key: value for key, value in query.items() if key != "content_sha256"}
    _require(
        isinstance(query["content_sha256"], str)
        and query["content_sha256"] == framed_sha256(CANONICAL_QUERY_DOMAIN, query_core),
        "canonical_query.content_sha256",
    )

    retrieval_input = binding["retrieval_input"]
    counts = binding["filtering_counts"]
    if mode == "SYNTHETIC_CORPUS":
        input_binding = _closed_mapping(
            retrieval_input,
            _SYNTHETIC_INPUT_BINDING_FIELDS,
            "private_replay_binding.retrieval_input",
        )
        count_rows = _closed_mapping(
            counts,
            _SYNTHETIC_FILTER_COUNT_FIELDS,
            "private_replay_binding.filtering_counts",
        )
        for field in (
            "compiled_corpus_content_sha256",
            "compiled_request_content_sha256",
        ):
            _require(
                isinstance(input_binding[field], str)
                and _SHA256_RE.fullmatch(input_binding[field]) is not None,
                f"private_replay_binding.retrieval_input.{field}",
            )
    else:
        input_binding = _closed_mapping(
            retrieval_input,
            _REAL_INPUT_BINDING_FIELDS,
            "private_replay_binding.retrieval_input",
        )
        count_rows = _closed_mapping(
            counts,
            _REAL_FILTER_COUNT_FIELDS,
            "private_replay_binding.filtering_counts",
        )
        for field in (
            "node_index_raw_bytes_identity",
            "edge_index_raw_bytes_identity",
            "taxonomy_raw_bytes_identity",
        ):
            _validate_raw_bytes_identity(
                input_binding[field],
                f"private_replay_binding.retrieval_input.{field}",
            )
        source_nodes = _closed_mapping(
            input_binding["source_node_raw_bytes_identity"],
            _SOURCE_NODE_IDENTITY_FIELDS,
            "private_replay_binding.retrieval_input.source_nodes",
        )
        rows = list(_array(source_nodes["rows"], "source_nodes.rows"))
        _require(source_nodes["source_node_count"] == len(rows), "source_nodes.count")
        for ordinal, raw in enumerate(rows):
            row = _closed_mapping(
                raw,
                _SOURCE_NODE_IDENTITY_ROW_FIELDS,
                f"source_nodes.rows[{ordinal}]",
            )
            _require(row["ordinal"] == ordinal, f"source_nodes.rows[{ordinal}].ordinal")
            _validate_raw_bytes_identity(
                {"byte_count": row["byte_count"], "raw_sha256": row["raw_sha256"]},
                f"source_nodes.rows[{ordinal}].identity",
            )
        _require(
            source_nodes["content_sha256"]
            == framed_sha256(SOURCE_NODE_RAW_BYTES_DOMAIN, rows),
            "source_nodes.content_sha256",
        )
        _require(
            isinstance(input_binding["graph_raw_bytes_identity"], str)
            and _SHA256_RE.fullmatch(input_binding["graph_raw_bytes_identity"]) is not None,
            "private_replay_binding.retrieval_input.graph_raw_bytes_identity",
        )

    _require(input_binding["input_mode"] == mode, "retrieval_input.input_mode")
    for field, value in count_rows.items():
        _require(type(value) is int and value >= 0, f"filtering_counts.{field}")

    selected = list(
        _array(binding["selected_sanitized_objects"], "selected_sanitized_objects")
    )
    visible_items = [
        item
        for lane in projection["lanes"]
        for item in lane["items"]
    ]
    _require(len(selected) == len(visible_items), "selected_sanitized_objects.count")
    for ordinal, raw in enumerate(selected):
        row = _closed_mapping(
            raw,
            _SELECTED_BINDING_FIELDS,
            f"selected_sanitized_objects[{ordinal}]",
        )
        _require(row["ordinal"] == ordinal, f"selected_sanitized_objects[{ordinal}].ordinal")
        visible = visible_items[ordinal]
        _require(row["handle"] == visible["handle"], f"selected_sanitized_objects[{ordinal}].handle")
        _require(row["lane"] in FOUR_LANES, f"selected_sanitized_objects[{ordinal}].lane")
        _require(
            row["precedent_group_handle"] == visible["precedent_group_handle"]
            and row["eligible_lanes"] == visible["eligible_lanes"]
            and row["lane_role_rationale"] == visible["lane_role_rationale"],
            f"selected_sanitized_objects[{ordinal}].precedent_binding",
        )
        _require(
            isinstance(row["sanitized_object_content_sha256"], str)
            and _SHA256_RE.fullmatch(row["sanitized_object_content_sha256"]) is not None,
            f"selected_sanitized_objects[{ordinal}].digest",
        )


def validate_epistemic_retrieval_kernel_adapter_result(
    result: Mapping[str, Any],
    *,
    source_first_candidate: Mapping[str, Any],
    source_inputs: Mapping[str, Any],
    session_scope_secret: bytes,
    corpus_objects: Sequence[Mapping[str, Any]] | None = None,
    phase_request: Mapping[str, Any] | None = None,
    top_k_per_lane: int | None = None,
    node_index_path: Path | str | None = None,
    edge_index_path: Path | str | None = None,
    taxonomy_path: Path | str | None = None,
    hypothesis_freeze: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate structure and full equality against original replay inputs.

    There is intentionally no public self-consistency-only success path.  The
    caller must supply the same Source-First raw inputs, session secret, and
    synthetic corpus or real graph inputs that produced the candidate.
    """

    _validate_epistemic_retrieval_kernel_adapter_result_structure(result)
    mode = result["private_replay_binding"]["retrieval_mode"]
    if mode == "SYNTHETIC_CORPUS":
        _require(corpus_objects is not None, "full_replay.synthetic_corpus_required")
        _require(
            top_k_per_lane is None
            and node_index_path is None
            and edge_index_path is None
            and taxonomy_path is None
            and hypothesis_freeze is None,
            "full_replay.synthetic_real_inputs_forbidden",
        )
        expected = run_epistemic_retrieval_kernel_adapter_offline(
            source_first_candidate=source_first_candidate,
            source_inputs=source_inputs,
            corpus_objects=corpus_objects,
            session_scope_secret=session_scope_secret,
            phase_request=phase_request,
        )
    else:
        _require(corpus_objects is None, "full_replay.real_synthetic_corpus_forbidden")
        _require(phase_request is None, "full_replay.real_phase_request_forbidden")
        _require(
            type(top_k_per_lane) is int
            and node_index_path is not None
            and edge_index_path is not None
            and taxonomy_path is not None,
            "full_replay.real_inputs_required",
        )
        expected = retrieve_real_knowledge_advisory(
            source_first_candidate=source_first_candidate,
            source_inputs=source_inputs,
            phase_branch=result["phase_branch"],
            top_k_per_lane=top_k_per_lane,
            node_index_path=node_index_path,
            edge_index_path=edge_index_path,
            taxonomy_path=taxonomy_path,
            session_scope_secret=session_scope_secret,
            hypothesis_freeze=hypothesis_freeze,
        )
    _require(
        dict(result) == expected,
        "adapter_result:full_replay_equality",
    )
    return expected


def run_epistemic_retrieval_kernel_adapter_offline(
    *,
    source_first_candidate: Mapping[str, Any],
    source_inputs: Mapping[str, Any],
    corpus_objects: Sequence[Mapping[str, Any]],
    session_scope_secret: bytes,
    phase_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay Source-First, run native retrieval, and return a split result.

    ``agent_visible_projection`` is the only agent-safe view.  The private replay
    binding records content identities and counts.  A0 is always derived from the
    replayed Source-First candidate; callers may supply only a closed A1 request
    containing raw frozen hypothesis semantics, never a bare binding digest.
    """

    _require(type(session_scope_secret) is bytes, "session_scope_secret:bytes_required")
    _require(len(session_scope_secret) >= 32, "session_scope_secret:min_32_bytes")
    source_first = _replay_source_first(
        source_first_candidate=source_first_candidate,
        source_inputs=source_inputs,
    )

    if phase_request is None:
        phase_branch = A0
        request = _plain_source_a0_request(source_first)
        source_binding = source_first["content_sha256"]
        hypothesis_freeze_content_sha256 = None
        _require(
            request["phase_policy"]["requested_lane_subset"] == list(FOUR_LANES),
            "source_first.a0_policy:exact4_canonical_lanes_required",
        )
        canonical_value: Any = request["phase_input"]
        query_mode = "SOURCE_FIRST_REPLAY_DERIVED_A0_TYPED_QUERY"
    else:
        request = _closed_mapping(
            phase_request,
            _A1_REQUEST_FIELDS,
            "phase_request",
        )
        phase_branch = request["phase_branch"]
        _require(phase_branch == A1, "phase_request:a1_only")
        source_binding = None
        hypothesis_freeze_content_sha256 = _compile_hypothesis_freeze_binding(
            request["hypothesis_freeze"],
            source_first_content_sha256=source_first["content_sha256"],
        )
        canonical_value = {
            "source_first_a0_phase_input": _plain_source_a0_request(source_first)[
                "phase_input"
            ],
            "a1_phase_input": request["phase_input"],
            "hypothesis_freeze_content_sha256": hypothesis_freeze_content_sha256,
        }
        query_mode = "SOURCE_FIRST_REPLAY_BOUND_POST_FREEZE_A1_QUERY"
        _require(
            isinstance(request["phase_policy"], Mapping)
            and request["phase_policy"].get("phase_branch") == A1,
            "phase_request.a1_policy",
        )

    corpus = compile_offline_corpus(corpus_objects)
    request_candidate = compile_phase_request_candidate(
        phase_branch=phase_branch,
        phase_input=request["phase_input"],
        phase_policy=request["phase_policy"],
        source_first_binding_content_sha256=source_binding,
    )
    program = compile_retrieval_program(request_candidate, corpus)
    score_ledger, selection_ledger, rejection_ledger = (
        execute_phase_projection_candidate(program)
    )
    validate_phase_safe_retrieval_bundle(
        request_candidate=request_candidate,
        retrieval_program=program,
        score_ledger=score_ledger,
        selection_ledger=selection_ledger,
        rejection_ledger=rejection_ledger,
    )

    selected_by_lane: dict[str, list[dict[str, Any]]] = {
        lane: [] for lane in FOUR_LANES
    }
    selected_bindings: list[dict[str, Any]] = []
    seen_handles: set[str] = set()
    for row in selection_ledger["returned_rows"]:
        lane = row["lane"]
        _require(lane in selected_by_lane, "native_selection:lane_not_exact4")
        item_without_handle = _project_item(
            phase_branch=phase_branch,
            handle="",
            semantic_payload=row["private_sanitized_semantic_candidate"],
        )
        item_without_handle.pop("handle")
        item, private_row = _decorate_precedent_for_lane(
            secret=session_scope_secret,
            phase_branch=phase_branch,
            request_content_sha256=request_candidate["content_sha256"],
            object_id=row["object_id"],
            lane=lane,
            eligible_lanes=[lane],
            semantic_item_without_handles=item_without_handle,
        )
        handle = item["handle"]
        _require(handle not in seen_handles, "opaque_handle:collision")
        seen_handles.add(handle)
        selected_by_lane[lane].append(item)
        selected_bindings.append(private_row)

    projection = _build_agent_projection(
        phase_branch=phase_branch,
        result=_result_token(selection_ledger["result_branch"]),
        selected_by_lane=selected_by_lane,
    )
    selected_bindings = _lane_ordered_selected_bindings(
        projection,
        selected_bindings,
    )
    projected_objects = program["phase_projection"]["projected_objects"]
    admissible_objects = [
        row
        for row in projected_objects
        if row["corpus_class"] == "SYNTHETIC_ADMISSIBLE_CANDIDATE"
    ]
    canonical_query = _canonical_query_binding(
        query_mode=query_mode,
        phase_branch=phase_branch,
        query_value=canonical_value,
    )
    private_binding = {
        "binding_version": "1.0.0",
        "retrieval_mode": "SYNTHETIC_CORPUS",
        "source_first_content_sha256": source_first["content_sha256"],
        "source_first_input_binding_content_sha256": source_first[
            "explicit_input_binding"
        ]["content_sha256"],
        "source_first_a0_request_content_sha256": source_first["artifacts"][
            "a0_request_candidate"
        ]["content_sha256"],
        "canonical_query": canonical_query,
        "hypothesis_freeze_content_sha256": hypothesis_freeze_content_sha256,
        "retrieval_input": {
            "input_mode": "SYNTHETIC_CORPUS",
            "compiled_corpus_content_sha256": corpus["content_sha256"],
            "compiled_request_content_sha256": request_candidate["content_sha256"],
            "corpus_object_count": corpus["object_count"],
        },
        "filtering_counts": {
            "input_object_count": corpus["object_count"],
            "phase_projected_object_count": len(projected_objects),
            "phase_admissible_object_count": len(admissible_objects),
            "phase_quarantined_object_count": len(projected_objects)
            - len(admissible_objects),
            "scored_object_count": len(score_ledger["score_rows"]),
            "rejected_object_count": rejection_ledger["rejected_count"],
            "selected_unique_object_count": len(
                {row["object_id"] for row in selection_ledger["returned_rows"]}
            ),
            "selected_lane_item_count": len(selected_bindings),
        },
        "selected_sanitized_objects": selected_bindings,
        "agent_visible_projection_content_sha256": framed_sha256(
            "FF_EPISTEMIC_RETRIEVAL_AGENT_PROJECTION_V1", projection
        ),
    }
    return _adapter_result(
        phase_branch=phase_branch,
        projection=projection,
        private_replay_binding=private_binding,
    )


def _explicit_safe_file(path: Path | str, label: str) -> Path:
    candidate = Path(path).expanduser()
    _require(candidate.is_absolute(), f"{label}:absolute_path_required")
    _require(candidate.is_file(), f"{label}:file_required")
    _require(not candidate.is_symlink(), f"{label}:symlink_forbidden")
    resolved = candidate.resolve(strict=True)
    _require(
        resolved == candidate,
        f"{label}:resolved_path_or_symlink_ancestor_forbidden",
    )
    stat_result = candidate.stat()
    _require(stat_result.st_nlink == 1, f"{label}:hardlink_forbidden")
    _require(
        not any(_is_oos_path_component(part) for part in candidate.parts),
        f"{label}:oos_path_forbidden",
    )
    return resolved


def _normalized_path_component(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return re.sub(r"_+", "_", normalized)


def _contains_oos_text(value: Any) -> bool:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    if "样本外" in normalized:
        return True
    separator_canonical = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    separator_canonical = re.sub(r"_+", "_", separator_canonical)
    return re.search(
        r"(?:^|_)(?:oos|out_of_sample)(?:_|$)",
        separator_canonical,
    ) is not None


def _is_oos_path_component(value: Any) -> bool:
    normalized = _normalized_path_component(value)
    return any(
        normalized == prefix or normalized.startswith(prefix + "_")
        for prefix in _OOS_COMPONENT_PREFIXES
    )


def _read_bound_bytes(path: Path, label: str, *, max_bytes: int = 16 * 1024 * 1024) -> bytes:
    _require(path.is_absolute(), f"{label}:absolute_path_required")
    declared_parent = path.parent
    _require(not declared_parent.is_symlink(), f"{label}:parent_symlink_forbidden")
    grandparent = declared_parent.parent.resolve(strict=True)
    grandparent_fd = os.open(
        grandparent,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    parent_fd: int | None = None
    descriptor: int | None = None
    try:
        parent_entry_before = os.stat(
            declared_parent.name,
            dir_fd=grandparent_fd,
            follow_symlinks=False,
        )
        _require(
            stat.S_ISDIR(parent_entry_before.st_mode),
            f"{label}:parent_directory_required",
        )
        parent_fd = os.open(
            declared_parent.name,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=grandparent_fd,
        )
        parent_before = os.fstat(parent_fd)
        _require(
            (parent_before.st_dev, parent_before.st_ino)
            == (parent_entry_before.st_dev, parent_entry_before.st_ino),
            f"{label}:parent_entry_identity_mismatch",
        )
        descriptor = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        entry_before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        _require(stat.S_ISREG(before.st_mode), f"{label}:regular_file_required")
        _require(before.st_nlink == 1, f"{label}:hardlink_forbidden")
        _require(before.st_size <= max_bytes, f"{label}:too_large")
        _require(
            (before.st_dev, before.st_ino)
            == (entry_before.st_dev, entry_before.st_ino),
            f"{label}:entry_identity_mismatch",
        )
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            _require(bool(chunk), f"{label}:short_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        entry_after = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        parent_after = os.fstat(parent_fd)
        parent_entry_after = os.stat(
            declared_parent.name,
            dir_fd=grandparent_fd,
            follow_symlinks=False,
        )
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
            value.st_nlink,
        )
        _require(identity(before) == identity(after), f"{label}:changed_during_read")
        _require(
            (after.st_dev, after.st_ino)
            == (entry_after.st_dev, entry_after.st_ino),
            f"{label}:entry_replaced_during_read",
        )
        _require(
            (parent_before.st_dev, parent_before.st_ino)
            == (parent_after.st_dev, parent_after.st_ino),
            f"{label}:parent_replaced_during_read",
        )
        _require(
            (parent_after.st_dev, parent_after.st_ino)
            == (parent_entry_after.st_dev, parent_entry_after.st_ino),
            f"{label}:parent_entry_replaced_during_read",
        )
        raw = b"".join(chunks)
        _require(len(raw) == before.st_size, f"{label}:byte_count_mismatch")
        return raw
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(grandparent_fd)


def _raw_bytes_identity(raw: bytes) -> dict[str, Any]:
    return {"byte_count": len(raw), "raw_sha256": hashlib.sha256(raw).hexdigest()}


def _strict_jsonl_bytes(raw: bytes, label: str) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise EpistemicRetrievalKernelAdapterError(f"{label}:utf8_required") from exc
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        payload = strict_json_loads(line, label=f"{label}[{ordinal}]")
        _require(isinstance(payload, dict), f"{label}[{ordinal}]:object_required")
        rows.append(payload)
    return rows


def _safe_real_text(value: Any, *, phase_branch: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = unicodedata.normalize("NFKC", value.strip())
    if _contains_oos_text(normalized):
        return None
    if _STABLE_KNOWLEDGE_ID_RE.search(normalized) is not None:
        return None
    if re.search(r"\b(?:19|20)\d{2}(?:[-/]?\d{2}){0,2}\b", normalized):
        return None
    try:
        return _visible_text(
            normalized,
            "real_knowledge_projection.text",
            phase_branch=phase_branch,
        )
    except EpistemicRetrievalKernelAdapterError:
        return None


def _safe_real_texts(values: Any, *, phase_branch: str) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, Sequence) or isinstance(values, (bytes, bytearray)):
        return []
    output: list[str] = []
    for value in values:
        text = _safe_real_text(value, phase_branch=phase_branch)
        if text is not None and text not in output:
            output.append(text)
    return output


def _safe_taxonomy_values(
    taxonomy: Mapping[str, Any],
    field: str,
    *,
    phase_branch: str,
) -> list[str]:
    raw = taxonomy.get(field, [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    values: list[str] = []
    for value in raw:
        safe_value = _safe_real_text(
            str(value).replace("_", " "),
            phase_branch=phase_branch,
        )
        if safe_value is not None and safe_value not in values:
            values.append(safe_value)
    return values


def _safe_taxonomy_anchor_tags(
    taxonomy: Mapping[str, Any],
    field: str,
    *,
    phase_branch: str,
) -> list[str]:
    tags: list[str] = []
    for value in _safe_taxonomy_values(
        taxonomy,
        field,
        phase_branch=phase_branch,
    ):
        tag = re.sub(
            r"[^\w]+",
            "_",
            unicodedata.normalize("NFKC", value).casefold(),
        ).strip("_")
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _taxonomy_phrases(
    taxonomy: Mapping[str, Any],
    field: str,
    *,
    prefix: str,
    phase_branch: str,
) -> list[str]:
    values = _safe_taxonomy_values(
        taxonomy,
        field,
        phase_branch=phase_branch,
    )
    if not values:
        return []
    text = _safe_real_text(
        f"{prefix}: {', '.join(values)}", phase_branch=phase_branch
    )
    return [text] if text is not None else []


def _information_tradeoff_semantics(
    value: Any, *, phase_branch: str
) -> tuple[list[str], list[str]]:
    """Split a source-authored trade-off into mutually exclusive clauses.

    Knowledge nodes currently store preserve/remove semantics in one compound
    field.  Returning the whole sentence in both output fields destroys the
    distinction.  This parser only keeps source-authored clauses that contain
    exactly one of the two typed marker families; unresolved mixed clauses are
    omitted instead of being rewritten or guessed.
    """

    source_texts = _safe_real_texts([value], phase_branch=phase_branch)
    preserved: list[str] = []
    lost: list[str] = []
    for source_text in source_texts:
        for sentence in _INFORMATION_SENTENCE_SPLIT_RE.split(source_text):
            for contrast_clause in _INFORMATION_CONTRAST_SPLIT_RE.split(sentence):
                clauses = _INFORMATION_MARKED_AND_SPLIT_RE.split(contrast_clause)
                for raw_clause in clauses:
                    clause = raw_clause.strip(" \t\r\n,.;:，。；：")
                    if not clause:
                        continue
                    has_preserved = _INFORMATION_PRESERVED_RE.search(clause) is not None
                    has_lost = _INFORMATION_LOST_RE.search(clause) is not None
                    if has_preserved == has_lost:
                        continue
                    safe_clause = _safe_real_text(
                        clause,
                        phase_branch=phase_branch,
                    )
                    if safe_clause is None:
                        continue
                    target = preserved if has_preserved else lost
                    if safe_clause not in target:
                        target.append(safe_clause)
    return preserved, lost


def _strict_project_real_node(
    node: Mapping[str, Any], *, phase_branch: str
) -> dict[str, Any] | None:
    """Project a graph node without identity, evidence, status, paths, or metrics."""

    mechanism = node.get("mechanism")
    taxonomy = node.get("taxonomy")
    relations = node.get("relations")
    if not isinstance(mechanism, Mapping):
        mechanism = {}
    if not isinstance(taxonomy, Mapping):
        taxonomy = {}
    if not isinstance(relations, Sequence) or isinstance(
        relations, (str, bytes, bytearray)
    ):
        relations = []

    economic = _safe_real_texts(
        [
            mechanism.get("economic_hypothesis"),
            mechanism.get("payer"),
            mechanism.get("receiver"),
        ],
        phase_branch=phase_branch,
    )
    math = _unique_texts(
        _taxonomy_phrases(
            taxonomy,
            "math_mechanism",
            prefix="mathematical families",
            phase_branch=phase_branch,
        ),
        _safe_real_texts(
            [
                mechanism.get("random_object"),
                mechanism.get("math_forced_insight"),
                mechanism.get("dirac_style_forced_insight"),
            ],
            phase_branch=phase_branch,
        ),
    )
    preserved, lost = _information_tradeoff_semantics(
        mechanism.get("information_preserved_removed"),
        phase_branch=phase_branch,
    )
    advisory = _safe_real_texts(
        node.get("reuse_guidance", []), phase_branch=phase_branch
    )
    applicability = _safe_real_texts(
        [mechanism.get("complexity_penalty_reasoning")],
        phase_branch=phase_branch,
    )
    falsifiers: list[str] = []
    for relation in relations:
        if not isinstance(relation, Mapping):
            continue
        if relation.get("edge_type") != "contradicts":
            continue
        note = _safe_real_text(relation.get("note"), phase_branch=phase_branch)
        if note is not None and note not in falsifiers:
            falsifiers.append(note)

    projected: dict[str, Any] = {
        "mechanism": economic,
        "mathematical_analogy": math,
        "falsifiers": falsifiers,
        "applicability": applicability,
        "information_preserved": preserved,
        "information_lost": lost,
        "advisory": advisory,
    }
    if phase_branch == A1:
        projected.update(
            {
                "implementation_feasibility": _taxonomy_phrases(
                    taxonomy,
                    "worldquant_style",
                    prefix="operator families",
                    phase_branch=phase_branch,
                ),
                "operator_requirements": _taxonomy_phrases(
                    taxonomy,
                    "math_mechanism",
                    prefix="required mathematical operators",
                    phase_branch=phase_branch,
                ),
                "evidence_requirements": _taxonomy_phrases(
                    taxonomy,
                    "data_source",
                    prefix="observation families",
                    phase_branch=phase_branch,
                ),
                "numerical_constraints": _safe_real_texts(
                    [mechanism.get("numerical_constraint")],
                    phase_branch=phase_branch,
                ),
                "testability": falsifiers,
                "failure_modes": _taxonomy_phrases(
                    taxonomy,
                    "failure_mode",
                    prefix="failure modes",
                    phase_branch=phase_branch,
                ),
                "episode_context": [
                    text
                    for text in advisory
                    if _EPISODE_CONTEXT_RE.search(text) is not None
                ],
            }
        )
    if not any(projected.values()):
        return None
    return projected


def _knowledge_score(
    query_text: str,
    projected: Mapping[str, Any],
    *,
    named_math_anchor_tags: Sequence[str] = (),
) -> int:
    visible_text = " ".join(
        text
        for value in projected.values()
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
        for text in value
        if isinstance(text, str)
    )
    # Only typed ``taxonomy.math_mechanism`` values may serve as named-method
    # anchors.  General mathematical prose remains bridge/lexical evidence and
    # cannot manufacture wavelet, convolution, Kalman, or variational coverage.
    score, _overlap = score_text(
        query_text,
        {
            "text": visible_text,
            "tags": list(named_math_anchor_tags),
        },
    )
    return int(round(score * 1000))


def _knowledge_lanes(
    projected: Mapping[str, Any], *, phase_branch: str
) -> tuple[str, ...]:
    lanes: list[str] = []
    if projected.get("mechanism"):
        lanes.append("structural_isomorph")
    if projected.get("mathematical_analogy"):
        lanes.append("cross_math_analogy")
    if projected.get("information_lost") or (
        phase_branch == A1 and projected.get("failure_modes")
    ):
        lanes.append("near_miss_failure")
    if projected.get("falsifiers"):
        lanes.append("direct_counterexample")
    return tuple(lane for lane in FOUR_LANES if lane in lanes)


def retrieve_real_knowledge_advisory(
    *,
    source_first_candidate: Mapping[str, Any],
    source_inputs: Mapping[str, Any],
    phase_branch: str,
    top_k_per_lane: int,
    node_index_path: Path | str,
    edge_index_path: Path | str,
    taxonomy_path: Path | str,
    session_scope_secret: bytes,
    hypothesis_freeze: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay Source-First and retrieve an explicitly bound real graph.

    Query text is derived internally from the replayed blind seed.  Ranking happens
    only after strict projection has removed identities, paths, evidence metrics,
    performance, status, and availability metadata.  The result keeps those safe
    items separate from a private raw-bytes and filtering-count replay binding.
    """

    _require(phase_branch in SUPPORTED_PHASES, "real_knowledge.phase_branch")
    _require(type(session_scope_secret) is bytes, "session_scope_secret:bytes_required")
    _require(len(session_scope_secret) >= 32, "session_scope_secret:min_32_bytes")
    source_first = _replay_source_first(
        source_first_candidate=source_first_candidate,
        source_inputs=source_inputs,
    )
    query_text = _source_first_real_query(source_first)
    _require(
        type(top_k_per_lane) is int and 1 <= top_k_per_lane <= 20,
        "real_knowledge.top_k_per_lane",
    )
    if phase_branch == A0:
        _require(
            hypothesis_freeze is None,
            "real_knowledge.a0_hypothesis_freeze_forbidden",
        )
        source_policy = _plain_source_a0_request(source_first)["phase_policy"]
        _require(
            source_policy["requested_lane_subset"] == list(FOUR_LANES),
            "source_first.a0_policy:exact4_canonical_lanes_required",
        )
        _require(
            top_k_per_lane == source_policy["top_k_per_lane"],
            "real_knowledge.top_k_must_equal_source_first_policy",
        )
        hypothesis_freeze_content_sha256 = None
    else:
        hypothesis_freeze_content_sha256 = _compile_hypothesis_freeze_binding(
            hypothesis_freeze,
            source_first_content_sha256=source_first["content_sha256"],
        )

    node_path = _explicit_safe_file(node_index_path, "node_index_path")
    edge_path = _explicit_safe_file(edge_index_path, "edge_index_path")
    taxonomy_file = _explicit_safe_file(taxonomy_path, "taxonomy_path")
    node_index_raw = _read_bound_bytes(node_path, "node_index_path")
    edge_index_raw = _read_bound_bytes(edge_path, "edge_index_path")
    taxonomy_raw = _read_bound_bytes(taxonomy_file, "taxonomy_path")
    indexed_rows = _strict_jsonl_bytes(node_index_raw, "node_index")
    edge_rows = _strict_jsonl_bytes(edge_index_raw, "edge_index")
    taxonomy_object = strict_json_loads(taxonomy_raw, label="taxonomy")
    _require(isinstance(taxonomy_object, Mapping), "taxonomy:object_required")
    _require(bool(indexed_rows), "real_knowledge.node_index_empty")
    canonical_node_index = (
        Path(__file__).resolve().parents[1]
        / "knowledge"
        / "因子工厂"
        / "graph"
        / "factor_knowledge_nodes.jsonl"
    ).resolve(strict=False)
    if node_path == canonical_node_index:
        declared_source_node_root = node_path.parent / "nodes"
        _require(
            declared_source_node_root.is_dir()
            and not declared_source_node_root.is_symlink(),
            "real_knowledge.source_node_root:canonical_direct_real_directory_required",
        )
        source_node_root = declared_source_node_root.resolve(strict=True)
        _require(
            source_node_root.parent == node_path.parent,
            "real_knowledge.source_node_root:canonical_direct_child_required",
        )
    else:
        # Offline fixtures may keep source nodes beside their explicit index;
        # they are still confined to that one graph-input root.
        source_node_root = node_path.parent.resolve(strict=True)
    _require(
        source_node_root.is_dir() and not source_node_root.is_symlink(),
        "real_knowledge.source_node_root:real_directory_required",
    )
    source_node_root_stat = source_node_root.stat()
    _require(
        not os.path.ismount(source_node_root),
        "real_knowledge.source_node_root:mount_forbidden",
    )
    source_nodes: list[tuple[int, dict[str, Any], dict[str, Any], bytes]] = []
    source_node_identity_rows: list[dict[str, Any]] = []
    for ordinal, row in enumerate(indexed_rows):
        _require(isinstance(row, Mapping), f"real_knowledge.node_index[{ordinal}]:object")
        source_path = str(row.get("source_node_path") or "")
        _require(bool(source_path), f"real_knowledge.node_index[{ordinal}]:source_path")
        _require(
            not any(
                _is_oos_path_component(part) for part in Path(source_path).parts
            ),
            f"real_knowledge.node_index[{ordinal}]:oos_source_forbidden",
        )
        unresolved_source_candidate = resolve_graph_node_path(source_path)
        _require(
            not unresolved_source_candidate.is_symlink(),
            f"real_knowledge.node_index[{ordinal}]:source_symlink_forbidden",
        )
        source_candidate = unresolved_source_candidate.resolve(strict=True)
        _require(
            source_candidate == source_node_root
            or source_node_root in source_candidate.parents,
            f"real_knowledge.node_index[{ordinal}]:source_outside_graph_root",
        )
        resolved_source = _explicit_safe_file(
            source_candidate,
            f"real_knowledge.source_node[{ordinal}]",
        )
        source_metadata = resolved_source.stat()
        _require(
            source_metadata.st_dev == source_node_root_stat.st_dev,
            f"real_knowledge.source_node[{ordinal}]:cross_device_forbidden",
        )
        _require(
            not os.path.ismount(resolved_source),
            f"real_knowledge.source_node[{ordinal}]:mount_forbidden",
        )
        raw_node = _read_bound_bytes(
            resolved_source,
            f"real_knowledge.source_node[{ordinal}]",
        )
        node = strict_json_loads(raw_node, label=f"source_node[{ordinal}]")
        _require(isinstance(node, dict), f"source_node[{ordinal}]:object_required")
        identity = _raw_bytes_identity(raw_node)
        source_node_identity_rows.append({"ordinal": ordinal, **identity})
        source_nodes.append((ordinal, dict(row), node, raw_node))

    # Parsing is part of consumption; neither legacy index text nor edge metadata
    # participates in ranking.  Only the strict projection of source-node bytes does.
    _require(all(isinstance(row, Mapping) for row in edge_rows), "edge_index:rows")
    source_node_raw_identity = {
        "source_node_count": len(source_node_identity_rows),
        "rows": source_node_identity_rows,
        "content_sha256": framed_sha256(
            SOURCE_NODE_RAW_BYTES_DOMAIN,
            source_node_identity_rows,
        ),
    }
    node_index_identity = _raw_bytes_identity(node_index_raw)
    edge_index_identity = _raw_bytes_identity(edge_index_raw)
    taxonomy_identity = _raw_bytes_identity(taxonomy_raw)
    graph_raw_identity = framed_sha256(
        GRAPH_RAW_BYTES_DOMAIN,
        {
            "node_index_raw_bytes_identity": node_index_identity,
            "edge_index_raw_bytes_identity": edge_index_identity,
            "taxonomy_raw_bytes_identity": taxonomy_identity,
            "source_node_raw_bytes_identity": source_node_raw_identity,
        },
    )

    candidates_by_projection: dict[
        str, tuple[int, str, Mapping[str, Any], tuple[str, ...]]
    ] = {}
    strict_projection_count = 0
    strict_projection_rejected_count = 0
    lane_admissible_candidate_count = 0
    no_lane_candidate_count = 0
    positive_score_candidate_count = 0
    zero_score_candidate_count = 0
    for ordinal, _index_row, node, _raw_node in source_nodes:
        projected = _strict_project_real_node(node, phase_branch=phase_branch)
        if projected is None:
            strict_projection_rejected_count += 1
            continue
        strict_projection_count += 1
        lanes = _knowledge_lanes(projected, phase_branch=phase_branch)
        if not lanes:
            no_lane_candidate_count += 1
            continue
        lane_admissible_candidate_count += 1
        taxonomy = node.get("taxonomy")
        if not isinstance(taxonomy, Mapping):
            taxonomy = {}
        math_anchor_tags = _safe_taxonomy_anchor_tags(
            taxonomy,
            "math_mechanism",
            phase_branch=phase_branch,
        )
        score = _knowledge_score(
            query_text,
            projected,
            named_math_anchor_tags=math_anchor_tags,
        )
        if score <= 0:
            zero_score_candidate_count += 1
            continue
        positive_score_candidate_count += 1
        projected_identity = framed_sha256(
            REAL_PROJECTED_PRECEDENT_DOMAIN,
            {
                "phase_branch": phase_branch,
                "strict_projection": projected,
                "eligible_lanes": list(lanes),
            },
        )
        candidate = (score, projected_identity, projected, lanes)
        existing = candidates_by_projection.get(projected_identity)
        _require(
            existing is None or existing == candidate,
            "real_knowledge:projected_precedent_identity_collision",
        )
        candidates_by_projection.setdefault(projected_identity, candidate)
    candidates = list(candidates_by_projection.values())
    candidates.sort(key=lambda row: (-row[0], row[1]))

    selected_by_lane: dict[str, list[dict[str, Any]]] = {
        lane: [] for lane in FOUR_LANES
    }
    canonical_query = _canonical_query_binding(
        query_mode="SOURCE_FIRST_REPLAY_DERIVED_REAL_GRAPH_QUERY",
        phase_branch=phase_branch,
        query_value=query_text,
    )
    selected_bindings: list[dict[str, Any]] = []
    selected_projection_ids: set[str] = set()
    for _score, projected_identity, projected, lanes in candidates:
        for lane in lanes:
            if len(selected_by_lane[lane]) >= top_k_per_lane:
                continue
            item_without_handle = {**dict(projected), "advisory_only": True}
            item, private_row = _decorate_precedent_for_lane(
                secret=session_scope_secret,
                phase_branch=phase_branch,
                request_content_sha256=canonical_query["content_sha256"],
                object_id=projected_identity,
                lane=lane,
                eligible_lanes=lanes,
                semantic_item_without_handles=item_without_handle,
            )
            selected_by_lane[lane].append(item)
            selected_projection_ids.add(projected_identity)
            selected_bindings.append(private_row)

    has_hits = any(selected_by_lane.values())
    result_token = (
        "HIT"
        if has_hits
        else (
            "NO_ADMISSIBLE_CANDIDATE"
            if lane_admissible_candidate_count == 0
            else "ZERO_HIT"
        )
    )
    projection = _build_agent_projection(
        phase_branch=phase_branch,
        result=result_token,
        selected_by_lane=selected_by_lane,
    )
    selected_bindings = _lane_ordered_selected_bindings(
        projection,
        selected_bindings,
    )
    private_binding = {
        "binding_version": "1.0.0",
        "retrieval_mode": "REAL_KNOWLEDGE_GRAPH",
        "source_first_content_sha256": source_first["content_sha256"],
        "source_first_input_binding_content_sha256": source_first[
            "explicit_input_binding"
        ]["content_sha256"],
        "source_first_a0_request_content_sha256": source_first["artifacts"][
            "a0_request_candidate"
        ]["content_sha256"],
        "canonical_query": canonical_query,
        "hypothesis_freeze_content_sha256": hypothesis_freeze_content_sha256,
        "retrieval_input": {
            "input_mode": "REAL_KNOWLEDGE_GRAPH",
            "node_index_raw_bytes_identity": node_index_identity,
            "edge_index_raw_bytes_identity": edge_index_identity,
            "taxonomy_raw_bytes_identity": taxonomy_identity,
            "source_node_raw_bytes_identity": source_node_raw_identity,
            "graph_raw_bytes_identity": graph_raw_identity,
        },
        "filtering_counts": {
            "indexed_row_count": len(indexed_rows),
            "source_node_read_count": len(source_nodes),
            "strict_projection_count": strict_projection_count,
            "strict_projection_rejected_count": strict_projection_rejected_count,
            "lane_admissible_candidate_count": lane_admissible_candidate_count,
            "no_lane_candidate_count": no_lane_candidate_count,
            "positive_score_candidate_count": positive_score_candidate_count,
            "zero_score_candidate_count": zero_score_candidate_count,
            "selected_unique_object_count": len(selected_projection_ids),
            "selected_lane_item_count": len(selected_bindings),
        },
        "selected_sanitized_objects": selected_bindings,
        "agent_visible_projection_content_sha256": framed_sha256(
            "FF_EPISTEMIC_RETRIEVAL_AGENT_PROJECTION_V1", projection
        ),
    }
    return _adapter_result(
        phase_branch=phase_branch,
        projection=projection,
        private_replay_binding=private_binding,
    )


def _demo_semantic_payload(
    *, lane: str, mathematical_analogy: str, advisory: str
) -> dict[str, list[str]]:
    common: dict[str, list[str]] = {
        field: [] for field in PHASE_CORPUS_FIELDS[A0]
    }
    common.update(
        {
            "economic_game_semantics": [
                "transient liquidity pressure creates delayed price adjustment"
            ],
            "latent_mechanism_semantics": [
                "hidden transient state decays across multiple horizons"
            ],
            "mathematical_family_semantics": [mathematical_analogy],
            "falsifier_semantics": [
                "the effect should vanish when transient ordering is destroyed"
            ],
            "applicability_boundary_semantics": [
                "the analogy applies only when scale and state assumptions are explicit"
            ],
            "information_preserved_semantics": [
                "relative timing, scale localization, and state persistence are preserved"
            ],
            "information_lost_semantics": [
                "the analogy does not identify a unique causal payer"
            ],
            "advisory_semantics": [f"{lane} advisory: {advisory}"],
        }
    )
    return common


def build_cross_math_analogy_demo_inputs() -> dict[str, Any]:
    """Return a fully explicit A0 demo corpus/request with four retrieval lanes."""

    shared_math = (
        "wavelet multiscale localization, Kalman latent state filtering, "
        "convolutional smoothing, and variational regularization"
    )
    corpus_objects = [
        {
            "corpus_class": "SYNTHETIC_ADMISSIBLE_CANDIDATE",
            "phase_branch": A0,
            "lane": "structural_isomorph",
            "semantic_payload": _demo_semantic_payload(
                lane="structural isomorph",
                mathematical_analogy=shared_math,
                advisory="compare the same hidden-state decay under a different observable",
            ),
        },
        {
            "corpus_class": "SYNTHETIC_ADMISSIBLE_CANDIDATE",
            "phase_branch": A0,
            "lane": "cross_math_analogy",
            "semantic_payload": _demo_semantic_payload(
                lane="cross math analogy",
                mathematical_analogy=shared_math,
                advisory="compare what each representation preserves before choosing an operator",
            ),
        },
        {
            "corpus_class": "SYNTHETIC_ADMISSIBLE_CANDIDATE",
            "phase_branch": A0,
            "lane": "near_miss_failure",
            "semantic_payload": _demo_semantic_payload(
                lane="near miss",
                mathematical_analogy=shared_math,
                advisory="challenge whether persistent drift was mistaken for a transient state",
            ),
        },
        {
            "corpus_class": "SYNTHETIC_ADMISSIBLE_CANDIDATE",
            "phase_branch": A0,
            "lane": "direct_counterexample",
            "semantic_payload": _demo_semantic_payload(
                lane="direct counterexample",
                mathematical_analogy=shared_math,
                advisory="reject the mechanism if scale scrambling leaves the effect unchanged",
            ),
        },
    ]
    source_inputs = _demo_source_first_inputs(shared_math=shared_math, top_k_per_lane=1)
    source_first_candidate = compile_source_first_kernel_session_candidate(
        **source_inputs
    )
    return {
        "source_first_candidate": source_first_candidate,
        "source_inputs": source_inputs,
        "corpus_objects": corpus_objects,
    }


def _demo_source_first_inputs(
    *, shared_math: str, top_k_per_lane: int
) -> dict[str, Any]:
    source_claim = "transient liquidity pressure creates delayed price adjustment"
    selected_body = {
        "disposition": "FORMALIZED",
        "selected_statement_ids": ["source-claim-1"],
        "economic_mechanism_claim": source_claim,
        "payer_or_constraint": "short horizon liquidity demanders pay patient providers",
        "estimand": "future relative price adjustment conditional on transient pressure",
        "information_set": "decision time price and volume path only",
        "horizon": "next five trading sessions",
        "mathematical_object": shared_math,
        "broken_invariant_or_boundary": "hidden transient state decays across multiple horizons",
        "observation_mapping": "map ordered increments to scale localized state summaries",
        "failure_signature": "the effect survives destruction of transient ordering",
        "falsifiers": [
            "the effect should vanish when transient ordering is destroyed"
        ],
        "material_rivals": ["ordinary reversal without a liquidity payer"],
        "regime_hypotheses": ["the effect strengthens when provision is constrained"],
        "new_assumptions": ["volume is a noisy provision proxy"],
        "clarification_questions": ["which scale carries the payer response"],
    }
    provenance = {
        "attestation_mode": (
            "CALLER_CLAIMED_PRE_RETRIEVAL__NOT_INDEPENDENTLY_VERIFIED"
        ),
        "field_rows": [
            {
                "ordinal": ordinal,
                "field_name": field_name,
                "provenance_class": "NEW_ASSUMPTION",
                "statement_ids": [],
            }
            for ordinal, field_name in enumerate(FORMALIZATION_SEMANTIC_FIELDS)
        ],
    }
    return {
        "source_bytes": source_claim.encode("utf-8"),
        "source_lineage": {
            "source_type": "USER_ORAL_OR_TEXT_HYPOTHESIS",
            "source_event_ref": "retrieval-demo-source-first",
            "source_legally_available_at": "2026-08-31T09:00:00Z",
            "language": "en",
            "source_integrity_status": "VERIFIED",
            "understanding_completeness": "COMPLETE_ENOUGH_TO_FORMALIZE",
            "source_reader_context_status": "SOURCE_ONLY_CANDIDATE",
            "selection_lineage_claim": "EX_ANTE_UNSELECTED_CLAIMED",
            "proposer_outcome_exposure_claim": "NONE_CLAIMED",
            "source_outcome_status": "SOURCE_OUTCOME_FREE",
            "missing_source_components": [],
            "novel_concepts_not_yet_mapped": ["cross representation state decay"],
            "internal_tensions": ["payer direction remains falsifiable"],
        },
        "author_claims": [
            {
                "statement_id": "source-claim-1",
                "classification": "SOURCE_NATIVE_EXPLICIT",
                "text": source_claim,
                "source_locators": ["message:sentence:1"],
                "depends_on_statement_ids": [],
            }
        ],
        "analyst_notes": [],
        "selected_semantic_body": selected_body,
        "formalization_provenance": provenance,
        "pre_a0_predictions": [
            {
                "prediction_id": "prediction-1",
                "prediction": "transient pressure precedes delayed adjustment",
                "horizon": "next five trading sessions",
                "expected_direction": "NEGATIVE",
                "falsified_when": "ordering destruction leaves the relation unchanged",
            }
        ],
        "phase_policy_candidate": {
            "policy_version": "source-first-offline-a0-candidate-v1",
            "phase": "A0",
            "requested_lane_subset": list(FOUR_LANES),
            "top_k_per_lane": top_k_per_lane,
        },
    }
