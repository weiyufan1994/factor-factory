from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from factor_factory.epistemic_research_session_offline import (
    AUTHORITY_EFFECT,
    STAGE_DEFINITIONS,
    compile_candidate_research_session_envelope,
    validate_candidate_research_session_envelope,
)
from factor_factory.epistemic_source_first_offline import (
    A0_REQUEST_SCHEMA_ID,
    BLIND_SEED_SCHEMA_ID,
    FORMALIZATION_SCHEMA_ID,
    UNDERSTANDING_SCHEMA_ID,
    compile_a0_request_candidate,
    compile_blind_mechanism_seed,
    compile_formalization_or_abstention,
    compile_source_understanding_bundle,
    validate_source_first_bundle,
)
from factor_factory.research_org.rfc8785_canonical import framed_sha256


SCHEMA_VERSION = "1.0.0"
ADAPTER_ID = "factorforge-source-first-kernel-offline-v1"

INPUT_BINDING_SCHEMA_ID = (
    "factorforge_source_first_kernel_explicit_input_binding_candidate_v1"
)
INPUT_BINDING_DOMAIN = "FF_SOURCE_FIRST_KERNEL_EXPLICIT_INPUT_BINDING_CANDIDATE_V1"
INPUT_BINDING_ID_DOMAIN = "FF_SOURCE_FIRST_KERNEL_EXPLICIT_INPUT_BINDING_ID_V1"
ADAPTER_RESULT_SCHEMA_ID = "factorforge_source_first_kernel_adapter_result_candidate_v1"
ADAPTER_RESULT_DOMAIN = "FF_SOURCE_FIRST_KERNEL_ADAPTER_RESULT_CANDIDATE_V1"

INPUT_DEFINITIONS = (
    ("source_bytes", "RAW_BYTES_SHA256"),
    ("source_lineage", "RFC8785_FRAMED_JSON_SHA256"),
    ("author_claims", "RFC8785_FRAMED_JSON_SHA256"),
    ("analyst_notes", "RFC8785_FRAMED_JSON_SHA256"),
    ("selected_semantic_body", "RFC8785_FRAMED_JSON_SHA256"),
    ("formalization_provenance", "RFC8785_FRAMED_JSON_SHA256_OR_NULL"),
    ("pre_a0_predictions", "RFC8785_FRAMED_JSON_SHA256"),
    ("phase_policy_candidate", "RFC8785_FRAMED_JSON_SHA256_OR_NULL"),
)
INPUT_DOMAINS = {
    name: f"FF_SOURCE_FIRST_KERNEL_INPUT_{name.upper()}_V1"
    for name, _ in INPUT_DEFINITIONS
    if name != "source_bytes"
}

ARTIFACT_FIELDS = {
    "source_understanding",
    "source_faithful_formalization",
    "blind_mechanism_seed",
    "a0_request_candidate",
}
ROOT_FIELDS = {
    "schema_id",
    "schema_version",
    "artifact_status",
    "adapter_id",
    "explicit_input_binding",
    "session_envelope",
    "artifacts",
    "formalization_provenance",
    "source_first_guarantees",
    "execution_summary",
    "signed",
    "candidate_only",
    "authority_effect",
    "content_sha256",
}
INPUT_BINDING_FIELDS = {
    "schema_id",
    "schema_version",
    "artifact_status",
    "binding_id",
    "input_mode",
    "input_commitments",
    "input_count",
    "source_byte_length",
    "source_bytes_sha256",
    "ambient_discovery_performed",
    "environment_lookup_performed",
    "filesystem_read_performed",
    "network_access_performed",
    "source_content_embedded",
    "semantic_input_values_embedded",
    "signed",
    "candidate_only",
    "authority_effect",
    "content_sha256",
}
INPUT_ROW_FIELDS = {"ordinal", "input_name", "commitment_profile", "content_sha256"}
GUARANTEE_FIELDS = {
    "source_understanding_is_first",
    "source_native_and_agent_statements_remain_distinct",
    "novel_source_concepts_allowed_before_taxonomy_mapping",
    "formalization_is_hash_bound_to_source_understanding",
    "blind_seed_is_formalization_bound",
    "a0_request_is_blind_seed_bound",
    "knowledge_policy_allows_supplement_only_after_blind_seed",
    "adapter_retrieval_or_knowledge_access_before_blind_seed",
    "caller_claimed_pre_retrieval_semantic_origin",
    "caller_semantic_origin_independently_verified",
    "strong_no_knowledge_consultation_attestation_present",
}
EXECUTION_SUMMARY_FIELDS = {
    "compiled_artifact_count",
    "retrieval_executed",
    "writes_performed",
    "output_publication_owner",
    "host_authority_present",
    "canonical_write_performed",
    "oos_access_performed",
    "production_activation_performed",
}

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

FORMALIZATION_SEMANTIC_FIELDS = (
    "economic_mechanism_claim",
    "payer_or_constraint",
    "estimand",
    "information_set",
    "horizon",
    "mathematical_object",
    "broken_invariant_or_boundary",
    "observation_mapping",
    "failure_signature",
    "falsifiers",
    "material_rivals",
    "regime_hypotheses",
    "new_assumptions",
    "clarification_questions",
)
PROVENANCE_CLASSES = {
    "CALLER_CLAIMED_SOURCE_GROUNDED",
    "PRE_RETRIEVAL_ANALYST_INFERENCE",
    "NEW_ASSUMPTION",
    "UNRESOLVED",
}
PROVENANCE_INPUT_FIELDS = {"attestation_mode", "field_rows"}
PROVENANCE_ROW_FIELDS = {
    "ordinal",
    "field_name",
    "provenance_class",
    "statement_ids",
}
PROVENANCE_SCHEMA_ID = "factorforge_source_first_formalization_provenance_candidate_v1"
PROVENANCE_DOMAIN = "FF_SOURCE_FIRST_FORMALIZATION_PROVENANCE_CANDIDATE_V1"


class SourceFirstKernelAdapterOfflineError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = tuple(str(reason) for reason in reasons)
        super().__init__(";".join(self.reasons))


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise SourceFirstKernelAdapterOfflineError([label])


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise SourceFirstKernelAdapterOfflineError(
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


def _json_input_sha(input_name: str, value: Any) -> str:
    return framed_sha256(INPUT_DOMAINS[input_name], value)


def _semantic_tokens(value: Any) -> set[str]:
    text = " ".join(str(item) for item in value) if isinstance(value, list) else str(value)
    output = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.casefold()))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        output.update(run[index : index + 2] for index in range(max(0, len(run) - 1)))
    return output


def _compile_formalization_provenance(
    *,
    understanding: Mapping[str, Any],
    formalization: Mapping[str, Any],
    raw_provenance: Mapping[str, Any] | None,
) -> dict[str, Any]:
    body = formalization["formalization_body"]
    if body["disposition"] != "FORMALIZED":
        _require(raw_provenance is None, "formalization_provenance:forbidden_for_abstention")
        core = {
            "schema_id": PROVENANCE_SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "formalization_content_sha256": formalization["content_sha256"],
            "disposition": "NOT_APPLICABLE_NONFORMALIZED",
            "attestation_mode": "NO_SEMANTIC_ORIGIN_ATTESTATION_REQUIRED",
            "field_rows": [],
            "field_count": 0,
            "caller_claimed_source_grounded_field_count": 0,
            "pre_retrieval_analyst_inference_field_count": 0,
            "new_assumption_field_count": 0,
            "unresolved_field_count": 0,
            "caller_claimed_pre_retrieval_semantic_origin": False,
            "caller_semantic_origin_independently_verified": False,
            "strong_source_faithful_claim_allowed": False,
            "candidate_only": True,
            "authority_effect": AUTHORITY_EFFECT,
        }
        result = dict(core)
        result["content_sha256"] = framed_sha256(PROVENANCE_DOMAIN, core)
        return result

    raw = _closed_mapping(
        raw_provenance,
        PROVENANCE_INPUT_FIELDS,
        "formalization_provenance",
    )
    _require_equal(
        raw["attestation_mode"],
        "CALLER_CLAIMED_PRE_RETRIEVAL__NOT_INDEPENDENTLY_VERIFIED",
        "formalization_provenance.attestation_mode",
    )
    statements = {
        row["statement_id"]: row for row in understanding["semantic_statements"]
    }
    selected_ids = set(body["selected_statement_ids"])
    rows = _array(raw["field_rows"], "formalization_provenance.field_rows")
    _require_equal(
        len(rows),
        len(FORMALIZATION_SEMANTIC_FIELDS),
        "formalization_provenance.field_rows:exact14",
    )
    normalized: list[dict[str, Any]] = []
    for ordinal, (field_name, raw_row) in enumerate(
        zip(FORMALIZATION_SEMANTIC_FIELDS, rows, strict=True)
    ):
        row = _closed_mapping(
            raw_row,
            PROVENANCE_ROW_FIELDS,
            f"formalization_provenance.field_rows[{ordinal}]",
        )
        _require_equal(row["ordinal"], ordinal, f"formalization_provenance.field_rows[{ordinal}].ordinal")
        _require_equal(row["field_name"], field_name, f"formalization_provenance.field_rows[{ordinal}].field_name")
        provenance_class = str(row["provenance_class"])
        _require(
            provenance_class in PROVENANCE_CLASSES,
            f"formalization_provenance.field_rows[{ordinal}].provenance_class",
        )
        raw_ids = _array(
            row["statement_ids"],
            f"formalization_provenance.field_rows[{ordinal}].statement_ids",
        )
        statement_ids = [str(value) for value in raw_ids]
        _require(
            len(statement_ids) == len(set(statement_ids)),
            f"formalization_provenance.field_rows[{ordinal}].duplicate_statement_id",
        )
        _require(
            all(value in statements for value in statement_ids),
            f"formalization_provenance.field_rows[{ordinal}].statement_id_unknown",
        )
        classes = {statements[value]["classification"] for value in statement_ids}
        if provenance_class == "CALLER_CLAIMED_SOURCE_GROUNDED":
            _require(bool(statement_ids), f"formalization_provenance.field_rows[{ordinal}].source_statement_required")
            _require(
                all(value in selected_ids for value in statement_ids),
                f"formalization_provenance.field_rows[{ordinal}].source_statement_not_selected",
            )
            _require(
                classes <= {"SOURCE_NATIVE_EXPLICIT", "AGENT_PARAPHRASE"},
                f"formalization_provenance.field_rows[{ordinal}].source_class",
            )
        elif provenance_class == "PRE_RETRIEVAL_ANALYST_INFERENCE":
            _require(
                all(value in selected_ids for value in statement_ids),
                f"formalization_provenance.field_rows[{ordinal}].analyst_statement_not_selected",
            )
            _require(
                "AGENT_INFERENCE" in classes,
                f"formalization_provenance.field_rows[{ordinal}].analyst_inference_required",
            )
        elif provenance_class == "UNRESOLVED":
            _require(
                "UNRESOLVED" in classes,
                f"formalization_provenance.field_rows[{ordinal}].unresolved_statement_required",
            )
        else:
            _require(
                not statement_ids,
                f"formalization_provenance.field_rows[{ordinal}].new_assumption_must_not_fake_statement",
            )
        if statement_ids:
            cited_text = " ".join(statements[value]["text"] for value in statement_ids)
            _require(
                bool(_semantic_tokens(body[field_name]) & _semantic_tokens(cited_text)),
                f"formalization_provenance.field_rows[{ordinal}].no_lexical_grounding",
            )
        normalized.append(
            {
                "ordinal": ordinal,
                "field_name": field_name,
                "provenance_class": provenance_class,
                "statement_ids": statement_ids,
            }
        )
    counts = {
        provenance_class: sum(
            row["provenance_class"] == provenance_class for row in normalized
        )
        for provenance_class in PROVENANCE_CLASSES
    }
    core = {
        "schema_id": PROVENANCE_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "formalization_content_sha256": formalization["content_sha256"],
        "disposition": "MIXED_FIELD_LEVEL_PROVENANCE_CANDIDATE",
        "attestation_mode": raw["attestation_mode"],
        "field_rows": normalized,
        "field_count": len(normalized),
        "caller_claimed_source_grounded_field_count": counts[
            "CALLER_CLAIMED_SOURCE_GROUNDED"
        ],
        "pre_retrieval_analyst_inference_field_count": counts[
            "PRE_RETRIEVAL_ANALYST_INFERENCE"
        ],
        "new_assumption_field_count": counts["NEW_ASSUMPTION"],
        "unresolved_field_count": counts["UNRESOLVED"],
        "caller_claimed_pre_retrieval_semantic_origin": True,
        "caller_semantic_origin_independently_verified": False,
        # The adapter validates caller-supplied field provenance and local lexical
        # grounding, but it is not an isolated source-reader attestation service.
        # A strong semantic-fidelity claim therefore remains unavailable even if
        # every caller row is classified CALLER_CLAIMED_SOURCE_GROUNDED.
        "strong_source_faithful_claim_allowed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    result = dict(core)
    result["content_sha256"] = framed_sha256(PROVENANCE_DOMAIN, core)
    return result


def _compile_explicit_input_binding(
    *,
    source_bytes: bytes,
    source_lineage: Mapping[str, Any],
    author_claims: Sequence[Mapping[str, Any]],
    analyst_notes: Sequence[Mapping[str, Any]],
    selected_semantic_body: Mapping[str, Any],
    formalization_provenance: Mapping[str, Any] | None,
    pre_a0_predictions: Sequence[Mapping[str, Any]],
    phase_policy_candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    _require(isinstance(source_bytes, bytes), "source_bytes:bytes_required")
    values: dict[str, Any] = {
        "source_bytes": source_bytes,
        "source_lineage": source_lineage,
        "author_claims": author_claims,
        "analyst_notes": analyst_notes,
        "selected_semantic_body": selected_semantic_body,
        "formalization_provenance": formalization_provenance,
        "pre_a0_predictions": pre_a0_predictions,
        "phase_policy_candidate": phase_policy_candidate,
    }
    rows: list[dict[str, Any]] = []
    for ordinal, (name, profile) in enumerate(INPUT_DEFINITIONS):
        content_sha = (
            hashlib.sha256(source_bytes).hexdigest()
            if name == "source_bytes"
            else _json_input_sha(name, values[name])
        )
        rows.append(
            {
                "ordinal": ordinal,
                "input_name": name,
                "commitment_profile": profile,
                "content_sha256": content_sha,
            }
        )
    binding_id_sha = framed_sha256(
        INPUT_BINDING_ID_DOMAIN,
        {
            "input_commitments": rows,
            "source_byte_length": len(source_bytes),
        },
    )
    core = {
        "schema_id": INPUT_BINDING_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "OFFLINE_CANDIDATE_ONLY__EXPLICIT_INPUTS_NOT_EMBEDDED",
        "binding_id": "candidate_sfi_" + binding_id_sha[:32],
        "input_mode": "CALLER_SUPPLIED_EXPLICIT_VALUES",
        "input_commitments": rows,
        "input_count": len(rows),
        "source_byte_length": len(source_bytes),
        "source_bytes_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "ambient_discovery_performed": False,
        "environment_lookup_performed": False,
        "filesystem_read_performed": False,
        "network_access_performed": False,
        "source_content_embedded": False,
        "semantic_input_values_embedded": False,
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    result = dict(core)
    result["content_sha256"] = framed_sha256(INPUT_BINDING_DOMAIN, core)
    return result


def _stage_bindings(artifacts: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    artifact_keys = (
        "source_understanding",
        "source_faithful_formalization",
        "blind_mechanism_seed",
        "a0_request_candidate",
    )
    rows: list[dict[str, Any]] = []
    for ordinal, ((stage, schema_id), key) in enumerate(zip(STAGE_DEFINITIONS, artifact_keys)):
        artifact = artifacts[key]
        _require_equal(artifact.get("schema_id"), schema_id, f"artifacts.{key}.schema_id")
        rows.append(
            {
                "ordinal": ordinal,
                "stage": stage,
                "schema_id": schema_id,
                "content_sha256": _sha256(
                    artifact.get("content_sha256"),
                    f"artifacts.{key}.content_sha256",
                ),
            }
        )
    return rows


def compile_source_first_kernel_session_candidate(
    *,
    source_bytes: bytes,
    source_lineage: Mapping[str, Any],
    author_claims: Sequence[Mapping[str, Any]],
    analyst_notes: Sequence[Mapping[str, Any]],
    selected_semantic_body: Mapping[str, Any],
    formalization_provenance: Mapping[str, Any] | None,
    pre_a0_predictions: Sequence[Mapping[str, Any]],
    phase_policy_candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Run the source-first Step1-to-A0 candidate kernel entirely in memory.

    Every semantic input is supplied by the caller.  The adapter never discovers
    files, environment state, indexes, prior factors, code, data, or results.  It
    returns pure JSON-compatible data; create-only publication belongs upstream.
    """

    understanding = compile_source_understanding_bundle(
        source_bytes,
        source_lineage,
        author_claims,
        analyst_notes,
    )
    formalization = compile_formalization_or_abstention(
        understanding,
        selected_semantic_body,
    )
    provenance = _compile_formalization_provenance(
        understanding=understanding,
        formalization=formalization,
        raw_provenance=formalization_provenance,
    )
    blind_seed = compile_blind_mechanism_seed(formalization, pre_a0_predictions)
    a0_request = compile_a0_request_candidate(blind_seed, phase_policy_candidate)
    validate_source_first_bundle(
        understanding=understanding,
        formalization=formalization,
        blind_seed=blind_seed,
        a0_request_candidate=a0_request,
    )
    input_binding = _compile_explicit_input_binding(
        source_bytes=source_bytes,
        source_lineage=source_lineage,
        author_claims=author_claims,
        analyst_notes=analyst_notes,
        selected_semantic_body=selected_semantic_body,
        formalization_provenance=formalization_provenance,
        pre_a0_predictions=pre_a0_predictions,
        phase_policy_candidate=phase_policy_candidate,
    )
    artifacts = {
        "source_understanding": understanding,
        "source_faithful_formalization": formalization,
        "blind_mechanism_seed": blind_seed,
        "a0_request_candidate": a0_request,
    }
    session = compile_candidate_research_session_envelope(
        explicit_input_binding_content_sha256=input_binding["content_sha256"],
        ordered_stage_bindings=_stage_bindings(artifacts),
        request_branch=a0_request["request_branch"],
    )
    core = {
        "schema_id": ADAPTER_RESULT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "OFFLINE_CANDIDATE_ONLY__NOT_PUBLISHED_OR_SEALED",
        "adapter_id": ADAPTER_ID,
        "explicit_input_binding": input_binding,
        "session_envelope": session,
        "artifacts": artifacts,
        "formalization_provenance": provenance,
        "source_first_guarantees": {
            "source_understanding_is_first": True,
            "source_native_and_agent_statements_remain_distinct": True,
            "novel_source_concepts_allowed_before_taxonomy_mapping": True,
            "formalization_is_hash_bound_to_source_understanding": True,
            "blind_seed_is_formalization_bound": True,
            "a0_request_is_blind_seed_bound": True,
            "knowledge_policy_allows_supplement_only_after_blind_seed": True,
            "adapter_retrieval_or_knowledge_access_before_blind_seed": False,
            "caller_claimed_pre_retrieval_semantic_origin": provenance[
                "caller_claimed_pre_retrieval_semantic_origin"
            ],
            "caller_semantic_origin_independently_verified": False,
            "strong_no_knowledge_consultation_attestation_present": False,
        },
        "execution_summary": {
            "compiled_artifact_count": 4,
            "retrieval_executed": False,
            "writes_performed": False,
            "output_publication_owner": "CALLER_CREATE_ONLY",
            "host_authority_present": False,
            "canonical_write_performed": False,
            "oos_access_performed": False,
            "production_activation_performed": False,
        },
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    result = dict(core)
    result["content_sha256"] = framed_sha256(ADAPTER_RESULT_DOMAIN, core)
    return result


def run_source_first_kernel_offline_candidate(**explicit_inputs: Any) -> dict[str, Any]:
    """Ergonomic alias for the pure in-memory compiler."""

    return compile_source_first_kernel_session_candidate(**explicit_inputs)


def validate_source_first_kernel_session_candidate(
    candidate: Mapping[str, Any],
    *,
    source_bytes: bytes,
    source_lineage: Mapping[str, Any],
    author_claims: Sequence[Mapping[str, Any]],
    analyst_notes: Sequence[Mapping[str, Any]],
    selected_semantic_body: Mapping[str, Any],
    formalization_provenance: Mapping[str, Any] | None,
    pre_a0_predictions: Sequence[Mapping[str, Any]],
    phase_policy_candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate structure, lineage, and a full replay against explicit inputs."""

    result = _closed_mapping(candidate, ROOT_FIELDS, "adapter_result")
    _sha256(result["content_sha256"], "adapter_result.content_sha256")
    core = {key: value for key, value in result.items() if key != "content_sha256"}
    _require_equal(
        result["content_sha256"],
        framed_sha256(ADAPTER_RESULT_DOMAIN, core),
        "adapter_result.content_sha256",
    )
    _require_equal(result["schema_id"], ADAPTER_RESULT_SCHEMA_ID, "adapter_result.schema_id")
    _require_equal(result["schema_version"], SCHEMA_VERSION, "adapter_result.schema_version")
    _require_equal(result["adapter_id"], ADAPTER_ID, "adapter_result.adapter_id")
    _require_equal(result["candidate_only"], True, "adapter_result.candidate_only")
    _require_equal(result["signed"], False, "adapter_result.signed")
    _require_equal(result["authority_effect"], AUTHORITY_EFFECT, "adapter_result.authority_effect")

    input_binding = _closed_mapping(
        result["explicit_input_binding"],
        INPUT_BINDING_FIELDS,
        "explicit_input_binding",
    )
    _require_equal(
        input_binding,
        _compile_explicit_input_binding(
            source_bytes=source_bytes,
            source_lineage=source_lineage,
            author_claims=author_claims,
            analyst_notes=analyst_notes,
            selected_semantic_body=selected_semantic_body,
            formalization_provenance=formalization_provenance,
            pre_a0_predictions=pre_a0_predictions,
            phase_policy_candidate=phase_policy_candidate,
        ),
        "explicit_input_binding:replay_equality",
    )
    rows = _array(input_binding["input_commitments"], "input_commitments")
    _require_equal(len(rows), len(INPUT_DEFINITIONS), "input_commitments:exact8")
    for ordinal, ((name, profile), raw) in enumerate(zip(INPUT_DEFINITIONS, rows)):
        row = _closed_mapping(raw, INPUT_ROW_FIELDS, f"input_commitments[{ordinal}]")
        _require_equal(row["ordinal"], ordinal, f"input_commitments[{ordinal}].ordinal")
        _require_equal(row["input_name"], name, f"input_commitments[{ordinal}].input_name")
        _require_equal(
            row["commitment_profile"],
            profile,
            f"input_commitments[{ordinal}].commitment_profile",
        )
        _sha256(row["content_sha256"], f"input_commitments[{ordinal}].content_sha256")

    artifacts = _closed_mapping(result["artifacts"], ARTIFACT_FIELDS, "artifacts")
    validate_source_first_bundle(
        understanding=artifacts["source_understanding"],
        formalization=artifacts["source_faithful_formalization"],
        blind_seed=artifacts["blind_mechanism_seed"],
        a0_request_candidate=artifacts["a0_request_candidate"],
    )
    _require_equal(
        result["formalization_provenance"],
        _compile_formalization_provenance(
            understanding=artifacts["source_understanding"],
            formalization=artifacts["source_faithful_formalization"],
            raw_provenance=formalization_provenance,
        ),
        "formalization_provenance:replay_equality",
    )
    session = validate_candidate_research_session_envelope(result["session_envelope"])
    _require_equal(
        session["explicit_input_binding_content_sha256"],
        input_binding["content_sha256"],
        "session_envelope.input_binding",
    )
    _require_equal(
        session["ordered_stage_bindings"],
        _stage_bindings(artifacts),
        "session_envelope.stage_bindings",
    )
    _require_equal(
        session["terminal"]["request_branch"],
        artifacts["a0_request_candidate"]["request_branch"],
        "session_envelope.request_branch",
    )
    _closed_mapping(
        result["source_first_guarantees"],
        GUARANTEE_FIELDS,
        "source_first_guarantees",
    )
    _closed_mapping(
        result["execution_summary"],
        EXECUTION_SUMMARY_FIELDS,
        "execution_summary",
    )

    replay = compile_source_first_kernel_session_candidate(
        source_bytes=source_bytes,
        source_lineage=source_lineage,
        author_claims=author_claims,
        analyst_notes=analyst_notes,
        selected_semantic_body=selected_semantic_body,
        formalization_provenance=formalization_provenance,
        pre_a0_predictions=pre_a0_predictions,
        phase_policy_candidate=phase_policy_candidate,
    )
    _require_equal(dict(result), replay, "adapter_result:full_replay_equality")
    return replay


assert tuple(schema for _, schema in STAGE_DEFINITIONS) == (
    UNDERSTANDING_SCHEMA_ID,
    FORMALIZATION_SCHEMA_ID,
    BLIND_SEED_SCHEMA_ID,
    A0_REQUEST_SCHEMA_ID,
)
