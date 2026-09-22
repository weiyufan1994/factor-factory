from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from factor_factory.research_org.rfc8785_canonical import framed_sha256


SCHEMA_VERSION = "1.0.0"
AUTHORITY_EFFECT = "NONE"

SESSION_SCHEMA_ID = "factorforge_epistemic_research_session_offline_candidate_v1"
SESSION_DOMAIN = "FF_EPISTEMIC_RESEARCH_SESSION_OFFLINE_CANDIDATE_V1"
SESSION_ID_DOMAIN = "FF_EPISTEMIC_RESEARCH_SESSION_OFFLINE_ID_V1"

WORKFLOW_ID = "SOURCE_FIRST_STEP1_TO_A0_CANDIDATE"
ADAPTER_ID = "factorforge-source-first-kernel-offline-v1"

STAGE_DEFINITIONS = (
    (
        "SOURCE_UNDERSTANDING",
        "factorforge_source_first_offline_understanding_candidate_v1",
    ),
    (
        "SOURCE_FAITHFUL_FORMALIZATION",
        "factorforge_source_first_offline_formalization_candidate_v1",
    ),
    (
        "BLIND_MECHANISM_SEED",
        "factorforge_source_first_offline_blind_seed_candidate_v1",
    ),
    (
        "A0_REQUEST_CANDIDATE",
        "factorforge_source_first_offline_a0_request_candidate_v1",
    ),
)

TERMINAL_STATE_BY_REQUEST_BRANCH = {
    "A0_HOST_PREISSUANCE_CANDIDATE": "AWAITING_HOST_MINT__NOT_EXECUTABLE",
    "NO_A0_REQUEST_LAWFUL_ABSTENTION": "TERMINAL_LAWFUL_ABSTENTION",
    "NO_A0_REQUEST_INELIGIBLE": "TERMINAL_A0_INELIGIBLE",
}

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

ROOT_FIELDS = {
    "schema_id",
    "schema_version",
    "artifact_status",
    "session_id",
    "workflow_id",
    "adapter_id",
    "explicit_input_binding_content_sha256",
    "ordered_stage_bindings",
    "source_first_invariant",
    "execution_boundary",
    "terminal",
    "signed",
    "candidate_only",
    "authority_effect",
    "content_sha256",
}
STAGE_FIELDS = {"ordinal", "stage", "schema_id", "content_sha256"}
SOURCE_FIRST_FIELDS = {
    "understanding_precedes_formalization",
    "formalization_precedes_blind_seed",
    "blind_seed_precedes_knowledge_request",
    "source_or_user_hypothesis_is_primary_input",
    "taxonomy_gate_before_understanding",
    "adapter_knowledge_access_before_blind_seed",
    "adapter_implementation_data_or_results_access_before_blind_seed",
    "caller_claimed_pre_retrieval_semantic_origin",
    "caller_semantic_origin_independently_verified",
}
EXECUTION_BOUNDARY_FIELDS = {
    "mode",
    "ambient_discovery_allowed",
    "environment_lookup_allowed",
    "network_allowed",
    "filesystem_read_allowed",
    "filesystem_write_allowed",
    "output_publication_owner",
    "output_overwrite_allowed",
    "host_authority_present",
    "canonical_write_allowed",
    "oos_access_allowed",
    "production_activation_allowed",
}
TERMINAL_FIELDS = {"request_branch", "session_state", "next_action_owner"}


class EpistemicResearchSessionOfflineError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = tuple(str(reason) for reason in reasons)
        super().__init__(";".join(self.reasons))


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise EpistemicResearchSessionOfflineError([label])


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise EpistemicResearchSessionOfflineError(
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


def _sha256(value: Any, label: str) -> str:
    _require(
        isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
        f"{label}:sha256_required",
    )
    return value


def _normalized_stage_bindings(
    stage_bindings: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = _array(stage_bindings, "ordered_stage_bindings")
    _require_equal(len(rows), len(STAGE_DEFINITIONS), "ordered_stage_bindings:exact4")
    normalized: list[dict[str, Any]] = []
    for ordinal, ((stage, schema_id), raw) in enumerate(zip(STAGE_DEFINITIONS, rows)):
        row = _closed_mapping(
            raw,
            STAGE_FIELDS,
            f"ordered_stage_bindings[{ordinal}]",
        )
        _require_equal(row["ordinal"], ordinal, f"ordered_stage_bindings[{ordinal}].ordinal")
        _require_equal(row["stage"], stage, f"ordered_stage_bindings[{ordinal}].stage")
        _require_equal(
            row["schema_id"],
            schema_id,
            f"ordered_stage_bindings[{ordinal}].schema_id",
        )
        normalized.append(
            {
                "ordinal": ordinal,
                "stage": stage,
                "schema_id": schema_id,
                "content_sha256": _sha256(
                    row["content_sha256"],
                    f"ordered_stage_bindings[{ordinal}].content_sha256",
                ),
            }
        )
    _require_equal(
        len({row["content_sha256"] for row in normalized}),
        len(normalized),
        "ordered_stage_bindings:content_sha256_unique",
    )
    return normalized


def _source_first_invariant() -> dict[str, bool]:
    return {
        "understanding_precedes_formalization": True,
        "formalization_precedes_blind_seed": True,
        "blind_seed_precedes_knowledge_request": True,
        "source_or_user_hypothesis_is_primary_input": True,
        "taxonomy_gate_before_understanding": False,
        "adapter_knowledge_access_before_blind_seed": False,
        "adapter_implementation_data_or_results_access_before_blind_seed": False,
        "caller_claimed_pre_retrieval_semantic_origin": True,
        "caller_semantic_origin_independently_verified": False,
    }


def _execution_boundary() -> dict[str, Any]:
    return {
        "mode": "PURE_OFFLINE_EXPLICIT_INPUTS",
        "ambient_discovery_allowed": False,
        "environment_lookup_allowed": False,
        "network_allowed": False,
        "filesystem_read_allowed": False,
        "filesystem_write_allowed": False,
        "output_publication_owner": "CALLER_CREATE_ONLY",
        "output_overwrite_allowed": False,
        "host_authority_present": False,
        "canonical_write_allowed": False,
        "oos_access_allowed": False,
        "production_activation_allowed": False,
    }


def compile_candidate_research_session_envelope(
    *,
    explicit_input_binding_content_sha256: str,
    ordered_stage_bindings: Sequence[Mapping[str, Any]],
    request_branch: str,
) -> dict[str, Any]:
    """Compile a deterministic, pure-data candidate session envelope.

    The caller owns any create-only publication.  This function deliberately has
    no path, environment, registry, network, or knowledge-store input.
    """

    input_sha = _sha256(
        explicit_input_binding_content_sha256,
        "explicit_input_binding_content_sha256",
    )
    stages = _normalized_stage_bindings(ordered_stage_bindings)
    _require(
        request_branch in TERMINAL_STATE_BY_REQUEST_BRANCH,
        "request_branch:unknown",
    )
    session_preimage = {
        "workflow_id": WORKFLOW_ID,
        "adapter_id": ADAPTER_ID,
        "explicit_input_binding_content_sha256": input_sha,
        "ordered_stage_bindings": stages,
        "request_branch": request_branch,
    }
    session_digest = framed_sha256(SESSION_ID_DOMAIN, session_preimage)
    core = {
        "schema_id": SESSION_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "OFFLINE_CANDIDATE_ONLY__NOT_PUBLISHED_OR_SEALED",
        "session_id": "candidate_ers_" + session_digest[:32],
        "workflow_id": WORKFLOW_ID,
        "adapter_id": ADAPTER_ID,
        "explicit_input_binding_content_sha256": input_sha,
        "ordered_stage_bindings": stages,
        "source_first_invariant": _source_first_invariant(),
        "execution_boundary": _execution_boundary(),
        "terminal": {
            "request_branch": request_branch,
            "session_state": TERMINAL_STATE_BY_REQUEST_BRANCH[request_branch],
            "next_action_owner": "CALLER_OR_GOVERNED_HOST",
        },
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    result = dict(core)
    result["content_sha256"] = framed_sha256(SESSION_DOMAIN, core)
    return result


def validate_candidate_research_session_envelope(
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    """Strictly validate and replay the session envelope from its closed fields."""

    session = _closed_mapping(envelope, ROOT_FIELDS, "session_envelope")
    _sha256(session["content_sha256"], "session_envelope.content_sha256")
    core = {key: value for key, value in session.items() if key != "content_sha256"}
    _require_equal(
        session["content_sha256"],
        framed_sha256(SESSION_DOMAIN, core),
        "session_envelope.content_sha256",
    )
    _require_equal(session["schema_id"], SESSION_SCHEMA_ID, "session_envelope.schema_id")
    _require_equal(
        session["schema_version"],
        SCHEMA_VERSION,
        "session_envelope.schema_version",
    )
    _require_equal(
        session["artifact_status"],
        "OFFLINE_CANDIDATE_ONLY__NOT_PUBLISHED_OR_SEALED",
        "session_envelope.artifact_status",
    )
    _require_equal(session["workflow_id"], WORKFLOW_ID, "session_envelope.workflow_id")
    _require_equal(session["adapter_id"], ADAPTER_ID, "session_envelope.adapter_id")
    _closed_mapping(
        session["source_first_invariant"],
        SOURCE_FIRST_FIELDS,
        "session_envelope.source_first_invariant",
    )
    _closed_mapping(
        session["execution_boundary"],
        EXECUTION_BOUNDARY_FIELDS,
        "session_envelope.execution_boundary",
    )
    _closed_mapping(session["terminal"], TERMINAL_FIELDS, "session_envelope.terminal")
    expected = compile_candidate_research_session_envelope(
        explicit_input_binding_content_sha256=session[
            "explicit_input_binding_content_sha256"
        ],
        ordered_stage_bindings=session["ordered_stage_bindings"],
        request_branch=session["terminal"]["request_branch"],
    )
    _require_equal(dict(session), expected, "session_envelope:closed_replay_equality")
    return expected
