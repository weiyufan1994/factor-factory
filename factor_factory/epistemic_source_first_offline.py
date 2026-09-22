from __future__ import annotations

import hashlib
import os
import re
import stat
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
from factor_factory.research_org.contracts import strict_json_loads, write_workspace_json_once
from factor_factory.research_org.rfc8785_canonical import framed_sha256


SCHEMA_VERSION = "1.0.0"
AUTHORITY_EFFECT = "NONE"
MAX_SOURCE_BYTES = 16 * 1024 * 1024

UNDERSTANDING_SCHEMA_ID = "factorforge_source_first_offline_understanding_candidate_v1"
FORMALIZATION_SCHEMA_ID = "factorforge_source_first_offline_formalization_candidate_v1"
BLIND_SEED_SCHEMA_ID = "factorforge_source_first_offline_blind_seed_candidate_v1"
A0_REQUEST_SCHEMA_ID = "factorforge_source_first_offline_a0_request_candidate_v1"
REPORT_SCHEMA_ID = "factorforge_source_first_offline_validation_report_v1"
PACKET_SCHEMA_ID = "factorforge_source_first_offline_candidate_packet_v1"

UNDERSTANDING_DOMAIN = "FF_SOURCE_FIRST_OFFLINE_UNDERSTANDING_CANDIDATE_V1"
SOURCE_BUNDLE_DOMAIN = "FF_SOURCE_FIRST_OFFLINE_SOURCE_BUNDLE_V1"
FORMALIZATION_BODY_DOMAIN = "FF_SOURCE_FIRST_OFFLINE_FORMALIZATION_BODY_V1"
FORMALIZATION_DOMAIN = "FF_SOURCE_FIRST_OFFLINE_FORMALIZATION_CANDIDATE_V1"
BLIND_SEED_BODY_DOMAIN = "FF_SOURCE_FIRST_OFFLINE_BLIND_SEED_BODY_V1"
BLIND_SEED_DOMAIN = "FF_SOURCE_FIRST_OFFLINE_BLIND_SEED_CANDIDATE_V1"
PHASE_POLICY_DOMAIN = "FF_SOURCE_FIRST_OFFLINE_PHASE_POLICY_CANDIDATE_V1"
QUERY_CANDIDATE_DOMAIN = "FF_SOURCE_FIRST_OFFLINE_A0_QUERY_SEMANTICS_CANDIDATE_V1"
A0_REQUEST_DOMAIN = "FF_SOURCE_FIRST_OFFLINE_A0_REQUEST_CANDIDATE_V1"
REPORT_DOMAIN = "FF_SOURCE_FIRST_OFFLINE_VALIDATION_REPORT_V1"
PACKET_ARTIFACT_DOMAIN = "FF_SOURCE_FIRST_OFFLINE_PACKET_ARTIFACT_MANIFEST_V1"
PACKET_DOMAIN = "FF_SOURCE_FIRST_OFFLINE_CANDIDATE_PACKET_V1"

SOURCE_TYPES = {
    "PDF_OR_DOCUMENT",
    "USER_ORAL_OR_TEXT_HYPOTHESIS",
    "FORMULA_ONLY",
    "CODE_OR_PSEUDOCODE_ONLY",
    "MINED_CANDIDATE",
}
AUTHOR_STATEMENT_CLASSES = {"SOURCE_NATIVE_EXPLICIT", "AGENT_PARAPHRASE"}
ANALYST_STATEMENT_CLASSES = {"AGENT_INFERENCE", "UNRESOLVED"}
INTEGRITY_STATES = {"VERIFIED", "PARTIAL", "BLOCKED"}
COMPLETENESS_STATES = {
    "COMPLETE_ENOUGH_TO_FORMALIZE",
    "UNDER_SPECIFIED",
    "CLARIFICATION_REQUIRED",
}
CONTEXT_STATES = {
    "SOURCE_ONLY_CANDIDATE",
    "NONBLIND_EXTERNAL_CONTEXT_DISCLOSED",
    "UNKNOWN",
}
SELECTION_LINEAGE_CLAIMS = {
    "EX_ANTE_UNSELECTED_CLAIMED",
    "OUTCOME_DERIVED",
    "SELECTION_LINEAGE_TAINTED_OR_UNKNOWN",
}
OUTCOME_EXPOSURE_CLAIMS = {
    "NONE_CLAIMED",
    "SOURCE_REPORTED_ONLY",
    "CURRENT_IS_SEEN",
    "PARENT_OOS_SEEN",
    "UNKNOWN",
}
SOURCE_OUTCOME_STATES = {
    "SOURCE_OUTCOME_FREE",
    "EMBEDDED_OUTCOMES_CAPTURED",
    "SOURCE_OUTCOME_CONTENT_UNKNOWN_OR_CONFLICTING",
}
A0_LANES = (
    "structural_isomorph",
    "cross_math_analogy",
    "near_miss_failure",
    "direct_counterexample",
)

SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
URI_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]{1,15}://")
ABSOLUTE_PATH_RE = re.compile(r"(?:^|\s)(?:/[^\s]+|~/[^\s]+|[A-Za-z]:\\[^\s]+)")
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
GIT_OR_CONTENT_DIGEST_RE = re.compile(
    r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})(?![0-9a-fA-F])"
)
STABLE_NAMESPACE_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_-]{1,31}::")
INDEX_AVAILABILITY_RE = re.compile(
    r"\b(?:index|snapshot|registry|case|episode|dataset|code|file|path|receipt|cas)"
    r"[ _-]?(?:id|ref|hash|sha|health|status|available|availability|missing|count)\b",
    re.IGNORECASE,
)

LINEAGE_FIELDS = {
    "source_type",
    "source_event_ref",
    "source_legally_available_at",
    "language",
    "source_integrity_status",
    "understanding_completeness",
    "source_reader_context_status",
    "selection_lineage_claim",
    "proposer_outcome_exposure_claim",
    "source_outcome_status",
    "missing_source_components",
    "novel_concepts_not_yet_mapped",
    "internal_tensions",
}
STATEMENT_INPUT_FIELDS = {
    "statement_id",
    "classification",
    "text",
    "source_locators",
    "depends_on_statement_ids",
}
FORMALIZED_INPUT_FIELDS = {
    "disposition",
    "selected_statement_ids",
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
}
ABSTENTION_INPUT_FIELDS = {
    "disposition",
    "selected_statement_ids",
    "reason_code",
    "clarification_questions",
    "structural_anchor_disposition",
}
ABSTENTION_REASONS = {
    "UNDER_SPECIFIED",
    "CLARIFICATION_REQUIRED",
    "NO_MINIMAL_MECHANISM",
    "SOURCE_TAINT_OR_NONBLIND_CONTEXT",
}
PREDICTION_FIELDS = {
    "prediction_id",
    "prediction",
    "horizon",
    "expected_direction",
    "falsified_when",
}
POLICY_FIELDS = {
    "policy_version",
    "phase",
    "requested_lane_subset",
    "top_k_per_lane",
}

class SourceFirstOfflineError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = tuple(str(reason) for reason in reasons)
        super().__init__(";".join(self.reasons))


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise SourceFirstOfflineError([label])


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise SourceFirstOfflineError(
            [f"{label}:expected={expected!r}:actual={actual!r}"]
        )


def _closed_mapping(value: Any, expected_fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label}:object_required")
    _require_equal(set(value), expected_fields, f"{label}:closed_fields")
    return value


def _text(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{label}:nonempty_text")
    _require("\x00" not in value, f"{label}:nul_forbidden")
    return value.strip()


def _text_list(
    value: Any,
    label: str,
    *,
    min_items: int = 0,
    unique: bool = True,
) -> list[str]:
    _require(
        isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)),
        f"{label}:array_required",
    )
    output = [_text(item, f"{label}[{index}]") for index, item in enumerate(value)]
    _require(len(output) >= min_items, f"{label}:min_items={min_items}")
    if unique:
        _require(len(output) == len(set(output)), f"{label}:duplicate")
    return output


def _safe_token(value: Any, label: str) -> str:
    text = _text(value, label)
    _require(SAFE_TOKEN_RE.fullmatch(text) is not None, f"{label}:unsafe_token")
    return text


def _with_content_sha(payload: Mapping[str, Any], *, domain: str) -> dict[str, Any]:
    _require("content_sha256" not in payload, f"{domain}:content_sha_already_present")
    result = dict(payload)
    result["content_sha256"] = framed_sha256(domain, result)
    return result


def _verify_content(payload: Mapping[str, Any], *, domain: str, label: str) -> None:
    core = dict(payload)
    actual = core.pop("content_sha256", None)
    _require(
        isinstance(actual, str) and SHA256_RE.fullmatch(actual) is not None,
        f"{label}:content_sha256",
    )
    _require_equal(actual, framed_sha256(domain, core), f"{label}:content_sha256")


def _statement_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    allowed_classes: set[str],
    group: str,
    starting_ordinal: int,
    prior_ids: set[str],
) -> list[dict[str, Any]]:
    _require(
        isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)),
        f"{group}:array_required",
    )
    output: list[dict[str, Any]] = []
    known_ids = set(prior_ids)
    for offset, raw in enumerate(rows):
        row = _closed_mapping(raw, STATEMENT_INPUT_FIELDS, f"{group}[{offset}]")
        statement_id = _safe_token(row["statement_id"], f"{group}[{offset}].statement_id")
        _require(statement_id not in known_ids, f"{group}[{offset}]:duplicate_statement_id")
        classification = row["classification"]
        _require(classification in allowed_classes, f"{group}[{offset}]:classification")
        source_locators = _text_list(
            row["source_locators"], f"{group}[{offset}].source_locators"
        )
        dependencies = _text_list(
            row["depends_on_statement_ids"],
            f"{group}[{offset}].depends_on_statement_ids",
        )
        _require(
            all(item in known_ids for item in dependencies),
            f"{group}[{offset}]:dependency_not_prior",
        )
        if classification == "SOURCE_NATIVE_EXPLICIT":
            _require(bool(source_locators), f"{group}[{offset}]:native_locator_required")
            _require(not dependencies, f"{group}[{offset}]:native_dependency_forbidden")
        elif classification == "AGENT_PARAPHRASE":
            _require(bool(source_locators), f"{group}[{offset}]:paraphrase_locator_required")
        elif classification == "AGENT_INFERENCE":
            _require(bool(dependencies), f"{group}[{offset}]:inference_dependency_required")
        output.append(
            {
                "ordinal": starting_ordinal + offset,
                "statement_id": statement_id,
                "statement_group": group,
                "classification": classification,
                "text": _text(row["text"], f"{group}[{offset}].text"),
                "source_locators": source_locators,
                "depends_on_statement_ids": dependencies,
            }
        )
        known_ids.add(statement_id)
    return output


def _candidate_blind_eligibility(
    *, lineage: Mapping[str, Any], statements: Sequence[Mapping[str, Any]]
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if lineage["source_integrity_status"] != "VERIFIED":
        reasons.append("SOURCE_INTEGRITY_NOT_VERIFIED")
    if lineage["understanding_completeness"] != "COMPLETE_ENOUGH_TO_FORMALIZE":
        reasons.append("UNDERSTANDING_NOT_COMPLETE_ENOUGH")
    if lineage["source_reader_context_status"] != "SOURCE_ONLY_CANDIDATE":
        reasons.append("SOURCE_ONLY_CONTEXT_NOT_CLEAN")
    if lineage["selection_lineage_claim"] != "EX_ANTE_UNSELECTED_CLAIMED":
        reasons.append("SELECTION_LINEAGE_NOT_EX_ANTE")
    if lineage["proposer_outcome_exposure_claim"] not in {
        "NONE_CLAIMED",
        "SOURCE_REPORTED_ONLY",
    }:
        reasons.append("PROPOSER_OUTCOME_EXPOSURE_NOT_CLEAN")
    if lineage["source_outcome_status"] != "SOURCE_OUTCOME_FREE":
        reasons.append("SOURCE_OUTCOME_CONTENT_NOT_FREE")
    _require(bool(statements), "candidate_blind_eligibility:statements_required")
    return ("ELIGIBLE_CANDIDATE_ONLY", []) if not reasons else ("A0_INELIGIBLE", reasons)


def compile_source_understanding_bundle(
    source_bytes: bytes,
    source_lineage: Mapping[str, Any],
    author_claims: Sequence[Mapping[str, Any]],
    analyst_notes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compile a source-first semantic record without consulting any knowledge system.

    This function validates public semantic statements supplied by a reader; it does
    not perform NLP, retrieval, classification, or authority attestation.
    """

    _require(isinstance(source_bytes, bytes), "source_bytes:bytes_required")
    _require(0 < len(source_bytes) <= MAX_SOURCE_BYTES, "source_bytes:size")
    lineage = _closed_mapping(source_lineage, LINEAGE_FIELDS, "source_lineage")
    source_type = lineage["source_type"]
    _require(source_type in SOURCE_TYPES, "source_lineage:source_type")
    source_event_ref = _safe_token(
        lineage["source_event_ref"], "source_lineage.source_event_ref"
    )
    available_at = _text(
        lineage["source_legally_available_at"],
        "source_lineage.source_legally_available_at",
    )
    _require(UTC_RE.fullmatch(available_at) is not None, "source_lineage:utc_required")
    language = _safe_token(lineage["language"], "source_lineage.language")
    _require(lineage["source_integrity_status"] in INTEGRITY_STATES, "source_lineage:integrity")
    _require(
        lineage["understanding_completeness"] in COMPLETENESS_STATES,
        "source_lineage:completeness",
    )
    _require(
        lineage["source_reader_context_status"] in CONTEXT_STATES,
        "source_lineage:context",
    )
    _require(
        lineage["selection_lineage_claim"] in SELECTION_LINEAGE_CLAIMS,
        "source_lineage:selection_lineage",
    )
    _require(
        lineage["proposer_outcome_exposure_claim"] in OUTCOME_EXPOSURE_CLAIMS,
        "source_lineage:outcome_exposure",
    )
    _require(
        lineage["source_outcome_status"] in SOURCE_OUTCOME_STATES,
        "source_lineage:source_outcome_status",
    )
    missing = _text_list(
        lineage["missing_source_components"], "source_lineage.missing_source_components"
    )
    novel = _text_list(
        lineage["novel_concepts_not_yet_mapped"],
        "source_lineage.novel_concepts_not_yet_mapped",
    )
    tensions = _text_list(
        lineage["internal_tensions"], "source_lineage.internal_tensions"
    )

    author_rows = _statement_rows(
        author_claims,
        allowed_classes=AUTHOR_STATEMENT_CLASSES,
        group="AUTHOR_OR_SOURCE",
        starting_ordinal=0,
        prior_ids=set(),
    )
    author_ids = {row["statement_id"] for row in author_rows}
    analyst_rows = _statement_rows(
        analyst_notes,
        allowed_classes=ANALYST_STATEMENT_CLASSES,
        group="ANALYST",
        starting_ordinal=len(author_rows),
        prior_ids=author_ids,
    )
    statements = [*author_rows, *analyst_rows]
    _require(bool(statements), "semantic_statements:empty")
    source_raw_sha = hashlib.sha256(source_bytes).hexdigest()
    source_bundle = {
        "source_type": source_type,
        "source_event_ref": source_event_ref,
        "source_legally_available_at": available_at,
        "language": language,
        "source_byte_length": len(source_bytes),
        "source_bytes_sha256": source_raw_sha,
    }
    source_bundle_sha = framed_sha256(SOURCE_BUNDLE_DOMAIN, source_bundle)
    eligibility, reasons = _candidate_blind_eligibility(
        lineage=lineage, statements=statements
    )
    core = {
        "schema_id": UNDERSTANDING_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "OFFLINE_CANDIDATE_ONLY__NOT_SEALED",
        "understanding_id": "candidate_sfu_" + source_bundle_sha[:32],
        "source_bundle": source_bundle,
        "source_bundle_sha256": source_bundle_sha,
        "semantic_statements": statements,
        "statement_count": len(statements),
        "native_vocabulary": sorted(
            {
                row["text"]
                for row in statements
                if row["classification"] == "SOURCE_NATIVE_EXPLICIT"
            }
        ),
        "novel_concepts_not_yet_mapped": novel,
        "internal_tensions": tensions,
        "unresolved_statement_ids": [
            row["statement_id"]
            for row in statements
            if row["classification"] == "UNRESOLVED"
        ],
        "missing_source_components": missing,
        "source_integrity_status": lineage["source_integrity_status"],
        "understanding_completeness": lineage["understanding_completeness"],
        "source_reader_context_status": lineage["source_reader_context_status"],
        "selection_lineage_claim": lineage["selection_lineage_claim"],
        "proposer_outcome_exposure_claim": lineage[
            "proposer_outcome_exposure_claim"
        ],
        "source_outcome_status": lineage["source_outcome_status"],
        "candidate_blind_semantic_eligibility": eligibility,
        "candidate_blind_ineligibility_reasons": reasons,
        "selection_or_exposure_attestation_present": False,
        "formal_a0_authority_present": False,
        "knowledge_or_retrieval_consulted": False,
        "taxonomy_required_before_understanding": False,
        "implementation_or_data_availability_consulted": False,
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=UNDERSTANDING_DOMAIN)


def _validate_selected_statement_ids(
    understanding: Mapping[str, Any], raw_ids: Any
) -> list[str]:
    selected = _text_list(raw_ids, "selected_statement_ids", min_items=1)
    rows = understanding["semantic_statements"]
    allowed = {
        row["statement_id"]
        for row in rows
        if row["classification"] != "UNRESOLVED"
    }
    _require(all(item in allowed for item in selected), "selected_statement_ids:invalid")
    return selected


def compile_formalization_or_abstention(
    understanding: Mapping[str, Any],
    selected_semantic_body: Mapping[str, Any],
) -> dict[str, Any]:
    _verify_content(understanding, domain=UNDERSTANDING_DOMAIN, label="understanding")
    disposition = selected_semantic_body.get("disposition")
    if disposition == "FORMALIZED":
        body = _closed_mapping(
            selected_semantic_body, FORMALIZED_INPUT_FIELDS, "formalization_body"
        )
        normalized: dict[str, Any] = {
            "disposition": "FORMALIZED",
            "selected_statement_ids": _validate_selected_statement_ids(
                understanding, body["selected_statement_ids"]
            ),
        }
        for field in (
            "economic_mechanism_claim",
            "payer_or_constraint",
            "estimand",
            "information_set",
            "horizon",
            "mathematical_object",
            "broken_invariant_or_boundary",
            "observation_mapping",
            "failure_signature",
        ):
            normalized[field] = _text(body[field], f"formalization_body.{field}")
        normalized["falsifiers"] = _text_list(
            body["falsifiers"], "formalization_body.falsifiers", min_items=1
        )
        normalized["material_rivals"] = _text_list(
            body["material_rivals"], "formalization_body.material_rivals", min_items=1
        )
        for field in (
            "regime_hypotheses",
            "new_assumptions",
            "clarification_questions",
        ):
            normalized[field] = _text_list(
                body[field], f"formalization_body.{field}"
            )
    elif disposition == "LAWFUL_ABSTENTION":
        body = _closed_mapping(
            selected_semantic_body, ABSTENTION_INPUT_FIELDS, "abstention_body"
        )
        _require(body["reason_code"] in ABSTENTION_REASONS, "abstention_body:reason")
        _require_equal(
            body["structural_anchor_disposition"],
            "TERMINAL_CLARIFICATION",
            "abstention_body:structural_anchor_disposition",
        )
        normalized = {
            "disposition": "LAWFUL_ABSTENTION",
            "selected_statement_ids": _validate_selected_statement_ids(
                understanding, body["selected_statement_ids"]
            ),
            "reason_code": body["reason_code"],
            "clarification_questions": _text_list(
                body["clarification_questions"],
                "abstention_body.clarification_questions",
                min_items=1,
            ),
            "structural_anchor_disposition": "TERMINAL_CLARIFICATION",
        }
    else:
        raise SourceFirstOfflineError(["formalization_body:unknown_disposition"])

    body_sha = framed_sha256(FORMALIZATION_BODY_DOMAIN, normalized)
    core = {
        "schema_id": FORMALIZATION_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "OFFLINE_CANDIDATE_ONLY__NOT_SEALED",
        "formalization_id": "candidate_sff_" + body_sha[:32],
        "source_understanding_content_sha256": understanding["content_sha256"],
        "source_candidate_blind_semantic_eligibility": understanding[
            "candidate_blind_semantic_eligibility"
        ],
        "source_candidate_blind_ineligibility_reasons": understanding[
            "candidate_blind_ineligibility_reasons"
        ],
        "source_formalization_mode": "STEP1_SOURCE_FAITHFUL_FORMALIZATION",
        "formalization_body": normalized,
        "formalization_body_sha256": body_sha,
        "knowledge_or_retrieval_consulted": False,
        "implementation_or_data_availability_consulted": False,
        "factor_view_created": False,
        "step2_readiness_asserted": False,
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=FORMALIZATION_DOMAIN)


def _prediction_rows(raw_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    _require(
        isinstance(raw_rows, Sequence)
        and not isinstance(raw_rows, (str, bytes, bytearray)),
        "pre_a0_predictions:array_required",
    )
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ordinal, raw in enumerate(raw_rows):
        row = _closed_mapping(raw, PREDICTION_FIELDS, f"prediction[{ordinal}]")
        prediction_id = _safe_token(
            row["prediction_id"], f"prediction[{ordinal}].prediction_id"
        )
        _require(prediction_id not in seen, f"prediction[{ordinal}]:duplicate_id")
        seen.add(prediction_id)
        output.append(
            {
                "ordinal": ordinal,
                "prediction_id": prediction_id,
                "prediction": _text(row["prediction"], f"prediction[{ordinal}].prediction"),
                "horizon": _text(row["horizon"], f"prediction[{ordinal}].horizon"),
                "expected_direction": _text(
                    row["expected_direction"],
                    f"prediction[{ordinal}].expected_direction",
                ),
                "falsified_when": _text(
                    row["falsified_when"], f"prediction[{ordinal}].falsified_when"
                ),
            }
        )
    return output


def compile_blind_mechanism_seed(
    formalization: Mapping[str, Any],
    pre_a0_predictions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    _verify_content(formalization, domain=FORMALIZATION_DOMAIN, label="formalization")
    body = formalization["formalization_body"]
    predictions = _prediction_rows(pre_a0_predictions)
    if formalization["source_candidate_blind_semantic_eligibility"] != "ELIGIBLE_CANDIDATE_ONLY":
        _require(not predictions, "a0_ineligible:predictions_forbidden")
        seed_body = {
            "seed_branch": "A0_INELIGIBLE_NO_SEED",
            "ineligibility_reasons": formalization[
                "source_candidate_blind_ineligibility_reasons"
            ],
            "pre_a0_predictions": [],
            "a0_request_candidate_allowed": False,
        }
    elif body["disposition"] == "LAWFUL_ABSTENTION":
        _require(not predictions, "abstention:predictions_forbidden")
        seed_body: dict[str, Any] = {
            "seed_branch": "LAWFUL_ABSTENTION_NO_SEED",
            "abstention_reason_code": body["reason_code"],
            "clarification_questions": body["clarification_questions"],
            "pre_a0_predictions": [],
            "a0_request_candidate_allowed": False,
        }
    else:
        _require(bool(predictions), "formalized:pre_a0_predictions_required")
        fingerprint = {
            "economic_claim": body["economic_mechanism_claim"],
            "estimand": body["estimand"],
            "payer_or_constraint": body["payer_or_constraint"],
            "mathematical_object": body["mathematical_object"],
            "broken_invariant_or_boundary": body["broken_invariant_or_boundary"],
            "observation_mapping": body["observation_mapping"],
            "failure_signature": body["failure_signature"],
        }
        seed_body = {
            "seed_branch": "BLIND_MECHANISM_SEED_CANDIDATE",
            "mechanism_fingerprint": fingerprint,
            "information_set": body["information_set"],
            "horizon": body["horizon"],
            "falsifiers": body["falsifiers"],
            "material_rivals": body["material_rivals"],
            "regime_hypotheses": body["regime_hypotheses"],
            "pre_a0_predictions": predictions,
            "a0_request_candidate_allowed": True,
        }
    seed_body_sha = framed_sha256(BLIND_SEED_BODY_DOMAIN, seed_body)
    core = {
        "schema_id": BLIND_SEED_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "OFFLINE_CANDIDATE_ONLY__NOT_RESERVED_OR_SEALED",
        "blind_seed_id": "candidate_bms_" + seed_body_sha[:32],
        "formalization_content_sha256": formalization["content_sha256"],
        "seed_body": seed_body,
        "seed_body_sha256": seed_body_sha,
        "namespace_reservation_present": False,
        "blind_seed_seal_present": False,
        "factor_view_created": False,
        "knowledge_or_retrieval_consulted": False,
        "implementation_data_code_or_result_ref_present": False,
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=BLIND_SEED_DOMAIN)


def _policy_core(phase_policy_candidate: Mapping[str, Any]) -> dict[str, Any]:
    policy = _closed_mapping(
        phase_policy_candidate, POLICY_FIELDS, "phase_policy_candidate"
    )
    _require_equal(policy["phase"], "A0", "phase_policy_candidate.phase")
    _require_equal(
        policy["policy_version"],
        "source-first-offline-a0-candidate-v1",
        "phase_policy_candidate.policy_version",
    )
    lanes = _text_list(
        policy["requested_lane_subset"],
        "phase_policy_candidate.requested_lane_subset",
        min_items=1,
    )
    _require(all(lane in A0_LANES for lane in lanes), "phase_policy_candidate:lane")
    _require(
        "direct_counterexample" in lanes,
        "phase_policy_candidate:direct_counterexample_required",
    )
    top_k = policy["top_k_per_lane"]
    _require(type(top_k) is int and 1 <= top_k <= 20, "phase_policy_candidate:top_k")
    return {
        "policy_version": policy["policy_version"],
        "phase": "A0",
        "requested_lane_subset": lanes,
        "top_k_per_lane": top_k,
    }


def _semantic_atom(atom_kind: str, value: Any, label: str) -> dict[str, str]:
    text = _text(value, label)
    _require(len(text.encode("utf-8")) <= 4096, f"{label}:too_large")
    _require(URI_RE.search(text) is None, f"{label}:uri_forbidden")
    _require(ABSOLUTE_PATH_RE.search(text) is None, f"{label}:absolute_path_forbidden")
    _require(UUID_RE.search(text) is None, f"{label}:uuid_forbidden")
    _require(
        GIT_OR_CONTENT_DIGEST_RE.search(text) is None,
        f"{label}:digest_or_git_identity_forbidden",
    )
    _require(STABLE_NAMESPACE_RE.search(text) is None, f"{label}:stable_namespace_forbidden")
    _require(
        INDEX_AVAILABILITY_RE.search(text) is None,
        f"{label}:index_availability_forbidden",
    )
    _require(
        not any(
            phrase in text
            for phrase in (
                "索引可用",
                "索引缺失",
                "索引健康",
                "索引数量",
                "代码可用性",
                "数据可用性",
            )
        ),
        f"{label}:hidden_availability_forbidden",
    )
    return {"atom_kind": atom_kind, "semantic_text": text}


def _expected_preissuance_query_semantics(
    blind_seed: Mapping[str, Any],
) -> dict[str, list[dict[str, str]]]:
    seed_body = blind_seed.get("seed_body")
    _require(isinstance(seed_body, Mapping), "query_derivation:seed_body")
    _require_equal(
        seed_body.get("seed_branch"),
        "BLIND_MECHANISM_SEED_CANDIDATE",
        "query_derivation:eligible_seed_required",
    )
    fingerprint = seed_body.get("mechanism_fingerprint")
    _require(isinstance(fingerprint, Mapping), "query_derivation:fingerprint")
    return {
        "economic_game_semantics": [
            _semantic_atom(
                "MECHANISM_CLAIM",
                fingerprint["economic_claim"],
                "query.economic_claim",
            ),
            _semantic_atom(
                "PAYER_OR_CONSTRAINT",
                fingerprint["payer_or_constraint"],
                "query.payer_or_constraint",
            ),
        ],
        "latent_mechanism_semantics": [
            _semantic_atom(
                "BROKEN_INVARIANT_OR_BOUNDARY",
                fingerprint["broken_invariant_or_boundary"],
                "query.broken_invariant_or_boundary",
            ),
            _semantic_atom(
                "OBSERVATION_MAPPING",
                fingerprint["observation_mapping"],
                "query.observation_mapping",
            ),
        ],
        "mathematical_family_semantics": [
            _semantic_atom(
                "MATHEMATICAL_OBJECT",
                fingerprint["mathematical_object"],
                "query.mathematical_object",
            )
        ],
        "falsifier_semantics": [
            _semantic_atom("FALSIFIER", text, f"query.falsifier[{ordinal}]")
            for ordinal, text in enumerate(seed_body["falsifiers"])
        ],
    }


def compile_a0_request_candidate(
    blind_seed: Mapping[str, Any],
    phase_policy_candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    _verify_content(blind_seed, domain=BLIND_SEED_DOMAIN, label="blind_seed")
    seed_body = blind_seed["seed_body"]
    if seed_body["seed_branch"] == "LAWFUL_ABSTENTION_NO_SEED":
        _require(phase_policy_candidate is None, "abstention:a0_policy_forbidden")
        request_branch = "NO_A0_REQUEST_LAWFUL_ABSTENTION"
        private_candidate = None
    elif seed_body["seed_branch"] == "A0_INELIGIBLE_NO_SEED":
        _require(phase_policy_candidate is None, "a0_ineligible:a0_policy_forbidden")
        request_branch = "NO_A0_REQUEST_INELIGIBLE"
        private_candidate = None
    else:
        _require(
            isinstance(phase_policy_candidate, Mapping),
            "eligible_seed:phase_policy_candidate_required",
        )
        policy_core = _policy_core(phase_policy_candidate)
        policy_sha = framed_sha256(PHASE_POLICY_DOMAIN, policy_core)
        query_semantics = _expected_preissuance_query_semantics(blind_seed)
        query_sha = framed_sha256(QUERY_CANDIDATE_DOMAIN, query_semantics)
        private_candidate = {
            "candidate_kind": "HOST_PREISSUANCE_A0_REQUEST_INPUT",
            "phase": "A0",
            "phase_policy_candidate": policy_core,
            "phase_policy_content_sha256": policy_sha,
            "query_semantics_candidate": query_semantics,
            "query_semantics_candidate_sha256": query_sha,
        }
        request_branch = "A0_HOST_PREISSUANCE_CANDIDATE"
    core = {
        "schema_id": A0_REQUEST_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "artifact_status": "OFFLINE_CANDIDATE_ONLY__NOT_EXECUTABLE",
        "request_branch": request_branch,
        "agent_visible_projection": None,
        "private_preissuance_request_candidate": private_candidate,
        "private_replay_binding": {
            "blind_seed_content_sha256": blind_seed["content_sha256"],
        },
        "host_minted_single_use_opaque_handle_required": private_candidate is not None,
        "request_not_issuable": True,
        "retrieval_executed": False,
        "execution_authorized": False,
        "host_capability_present": False,
        "bounded_evidence_grant_present": False,
        "stable_identity_or_index_metadata_agent_visible": False,
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=A0_REQUEST_DOMAIN)


def _expected_understanding_fields() -> set[str]:
    return {
        "schema_id",
        "schema_version",
        "artifact_status",
        "understanding_id",
        "source_bundle",
        "source_bundle_sha256",
        "semantic_statements",
        "statement_count",
        "native_vocabulary",
        "novel_concepts_not_yet_mapped",
        "internal_tensions",
        "unresolved_statement_ids",
        "missing_source_components",
        "source_integrity_status",
        "understanding_completeness",
        "source_reader_context_status",
        "selection_lineage_claim",
        "proposer_outcome_exposure_claim",
        "source_outcome_status",
        "candidate_blind_semantic_eligibility",
        "candidate_blind_ineligibility_reasons",
        "selection_or_exposure_attestation_present",
        "formal_a0_authority_present",
        "knowledge_or_retrieval_consulted",
        "taxonomy_required_before_understanding",
        "implementation_or_data_availability_consulted",
        "signed",
        "candidate_only",
        "authority_effect",
        "content_sha256",
    }


def validate_source_first_bundle(
    *,
    understanding: Mapping[str, Any],
    formalization: Mapping[str, Any],
    blind_seed: Mapping[str, Any],
    a0_request_candidate: Mapping[str, Any],
) -> None:
    _closed_mapping(understanding, _expected_understanding_fields(), "understanding")
    _verify_content(understanding, domain=UNDERSTANDING_DOMAIN, label="understanding")
    _require_equal(
        understanding["schema_id"], UNDERSTANDING_SCHEMA_ID, "understanding.schema_id"
    )
    _closed_mapping(
        understanding["source_bundle"],
        {
            "source_type",
            "source_event_ref",
            "source_legally_available_at",
            "language",
            "source_byte_length",
            "source_bytes_sha256",
        },
        "understanding.source_bundle",
    )
    _require_equal(
        understanding["statement_count"],
        len(understanding["semantic_statements"]),
        "understanding.statement_count",
    )
    _require_equal(
        understanding["source_bundle_sha256"],
        framed_sha256(SOURCE_BUNDLE_DOMAIN, understanding["source_bundle"]),
        "understanding.source_bundle_sha256",
    )
    _require_equal(
        [row["ordinal"] for row in understanding["semantic_statements"]],
        list(range(understanding["statement_count"])),
        "understanding.statement_ordinals",
    )
    for ordinal, row in enumerate(understanding["semantic_statements"]):
        _closed_mapping(
            row,
            {
                "ordinal",
                "statement_id",
                "statement_group",
                "classification",
                "text",
                "source_locators",
                "depends_on_statement_ids",
            },
            f"understanding.semantic_statements[{ordinal}]",
        )

    expected_formalization_fields = {
        "schema_id",
        "schema_version",
        "artifact_status",
        "formalization_id",
        "source_understanding_content_sha256",
        "source_candidate_blind_semantic_eligibility",
        "source_candidate_blind_ineligibility_reasons",
        "source_formalization_mode",
        "formalization_body",
        "formalization_body_sha256",
        "knowledge_or_retrieval_consulted",
        "implementation_or_data_availability_consulted",
        "factor_view_created",
        "step2_readiness_asserted",
        "signed",
        "candidate_only",
        "authority_effect",
        "content_sha256",
    }
    _closed_mapping(formalization, expected_formalization_fields, "formalization")
    _verify_content(formalization, domain=FORMALIZATION_DOMAIN, label="formalization")
    _require_equal(
        formalization["source_understanding_content_sha256"],
        understanding["content_sha256"],
        "formalization.understanding_binding",
    )
    _require_equal(
        formalization["formalization_body_sha256"],
        framed_sha256(FORMALIZATION_BODY_DOMAIN, formalization["formalization_body"]),
        "formalization.body_sha256",
    )
    if formalization["formalization_body"]["disposition"] == "FORMALIZED":
        _closed_mapping(
            formalization["formalization_body"],
            FORMALIZED_INPUT_FIELDS,
            "formalization.formalization_body",
        )
    else:
        _closed_mapping(
            formalization["formalization_body"],
            ABSTENTION_INPUT_FIELDS,
            "formalization.formalization_body",
        )
    _require_equal(
        formalization["source_candidate_blind_semantic_eligibility"],
        understanding["candidate_blind_semantic_eligibility"],
        "formalization.source_eligibility",
    )
    _require_equal(
        formalization["source_candidate_blind_ineligibility_reasons"],
        understanding["candidate_blind_ineligibility_reasons"],
        "formalization.source_ineligibility_reasons",
    )

    expected_seed_fields = {
        "schema_id",
        "schema_version",
        "artifact_status",
        "blind_seed_id",
        "formalization_content_sha256",
        "seed_body",
        "seed_body_sha256",
        "namespace_reservation_present",
        "blind_seed_seal_present",
        "factor_view_created",
        "knowledge_or_retrieval_consulted",
        "implementation_data_code_or_result_ref_present",
        "signed",
        "candidate_only",
        "authority_effect",
        "content_sha256",
    }
    _closed_mapping(blind_seed, expected_seed_fields, "blind_seed")
    _verify_content(blind_seed, domain=BLIND_SEED_DOMAIN, label="blind_seed")
    _require_equal(
        blind_seed["formalization_content_sha256"],
        formalization["content_sha256"],
        "blind_seed.formalization_binding",
    )
    _require_equal(
        blind_seed["seed_body_sha256"],
        framed_sha256(BLIND_SEED_BODY_DOMAIN, blind_seed["seed_body"]),
        "blind_seed.body_sha256",
    )
    seed_body = blind_seed["seed_body"]
    seed_branch = seed_body["seed_branch"]
    if seed_branch == "BLIND_MECHANISM_SEED_CANDIDATE":
        _closed_mapping(
            seed_body,
            {
                "seed_branch",
                "mechanism_fingerprint",
                "information_set",
                "horizon",
                "falsifiers",
                "material_rivals",
                "regime_hypotheses",
                "pre_a0_predictions",
                "a0_request_candidate_allowed",
            },
            "blind_seed.seed_body",
        )
        _closed_mapping(
            seed_body["mechanism_fingerprint"],
            {
                "economic_claim",
                "estimand",
                "payer_or_constraint",
                "mathematical_object",
                "broken_invariant_or_boundary",
                "observation_mapping",
                "failure_signature",
            },
            "blind_seed.mechanism_fingerprint",
        )
        for ordinal, prediction in enumerate(seed_body["pre_a0_predictions"]):
            _closed_mapping(
                prediction,
                {"ordinal", *PREDICTION_FIELDS},
                f"blind_seed.prediction[{ordinal}]",
            )
            _require_equal(
                prediction["ordinal"],
                ordinal,
                f"blind_seed.prediction[{ordinal}].ordinal",
            )
    elif seed_branch == "LAWFUL_ABSTENTION_NO_SEED":
        _closed_mapping(
            seed_body,
            {
                "seed_branch",
                "abstention_reason_code",
                "clarification_questions",
                "pre_a0_predictions",
                "a0_request_candidate_allowed",
            },
            "blind_seed.seed_body",
        )
    elif seed_branch == "A0_INELIGIBLE_NO_SEED":
        _closed_mapping(
            seed_body,
            {
                "seed_branch",
                "ineligibility_reasons",
                "pre_a0_predictions",
                "a0_request_candidate_allowed",
            },
            "blind_seed.seed_body",
        )
    else:
        raise SourceFirstOfflineError(["blind_seed.seed_body:unknown_branch"])

    expected_request_fields = {
        "schema_id",
        "schema_version",
        "artifact_status",
        "request_branch",
        "agent_visible_projection",
        "private_preissuance_request_candidate",
        "private_replay_binding",
        "host_minted_single_use_opaque_handle_required",
        "request_not_issuable",
        "retrieval_executed",
        "execution_authorized",
        "host_capability_present",
        "bounded_evidence_grant_present",
        "stable_identity_or_index_metadata_agent_visible",
        "signed",
        "candidate_only",
        "authority_effect",
        "content_sha256",
    }
    _closed_mapping(a0_request_candidate, expected_request_fields, "a0_request")
    _verify_content(a0_request_candidate, domain=A0_REQUEST_DOMAIN, label="a0_request")
    _require_equal(
        a0_request_candidate["private_replay_binding"]["blind_seed_content_sha256"],
        blind_seed["content_sha256"],
        "a0_request.blind_seed_binding",
    )
    _closed_mapping(
        a0_request_candidate["private_replay_binding"],
        {"blind_seed_content_sha256"},
        "a0_request.private_replay_binding",
    )
    _require_equal(
        a0_request_candidate["agent_visible_projection"],
        None,
        "a0_request.agent_visible_projection_absent_before_host_mint",
    )
    _require_equal(
        a0_request_candidate["request_not_issuable"],
        True,
        "a0_request.request_not_issuable",
    )
    if a0_request_candidate["request_branch"] == "A0_HOST_PREISSUANCE_CANDIDATE":
        candidate = _closed_mapping(
            a0_request_candidate["private_preissuance_request_candidate"],
            {
                "candidate_kind",
                "phase",
                "phase_policy_candidate",
                "phase_policy_content_sha256",
                "query_semantics_candidate",
                "query_semantics_candidate_sha256",
            },
            "a0_request.private_preissuance_request_candidate",
        )
        _require_equal(
            candidate["candidate_kind"],
            "HOST_PREISSUANCE_A0_REQUEST_INPUT",
            "a0_request.candidate_kind",
        )
        _require_equal(candidate["phase"], "A0", "a0_request.phase")
        _closed_mapping(
            candidate["phase_policy_candidate"],
            POLICY_FIELDS,
            "a0_request.phase_policy_candidate",
        )
        _require_equal(
            candidate["phase_policy_candidate"],
            _policy_core(candidate["phase_policy_candidate"]),
            "a0_request.phase_policy_candidate_closed_equality",
        )
        _require_equal(
            candidate["phase_policy_content_sha256"],
            framed_sha256(PHASE_POLICY_DOMAIN, candidate["phase_policy_candidate"]),
            "a0_request.phase_policy_content_sha256",
        )
        query = _closed_mapping(
            candidate["query_semantics_candidate"],
            {
                "economic_game_semantics",
                "latent_mechanism_semantics",
                "mathematical_family_semantics",
                "falsifier_semantics",
            },
            "a0_request.query_semantics_candidate",
        )
        _require_equal(
            candidate["query_semantics_candidate_sha256"],
            framed_sha256(QUERY_CANDIDATE_DOMAIN, query),
            "a0_request.query_semantics_candidate_sha256",
        )
        _require_equal(
            query,
            _expected_preissuance_query_semantics(blind_seed),
            "a0_request.query_semantics_blind_seed_closed_equality",
        )
        allowed_atom_kinds = {
            "MECHANISM_CLAIM",
            "PAYER_OR_CONSTRAINT",
            "BROKEN_INVARIANT_OR_BOUNDARY",
            "OBSERVATION_MAPPING",
            "MATHEMATICAL_OBJECT",
            "FALSIFIER",
        }
        for lane, atoms in query.items():
            _require(
                isinstance(atoms, Sequence)
                and not isinstance(atoms, (str, bytes, bytearray))
                and bool(atoms),
                f"a0_request.query_semantics_candidate.{lane}:nonempty_array",
            )
            for ordinal, raw_atom in enumerate(atoms):
                atom = _closed_mapping(
                    raw_atom,
                    {"atom_kind", "semantic_text"},
                    f"a0_request.query_semantics_candidate.{lane}[{ordinal}]",
                )
                _require(
                    atom["atom_kind"] in allowed_atom_kinds,
                    f"a0_request.query_semantics_candidate.{lane}[{ordinal}]:atom_kind",
                )
                _require_equal(
                    atom,
                    _semantic_atom(
                        atom["atom_kind"],
                        atom["semantic_text"],
                        f"a0_request.query_semantics_candidate.{lane}[{ordinal}]",
                    ),
                    f"a0_request.query_semantics_candidate.{lane}[{ordinal}]:sanitized",
                )
        _require_equal(
            a0_request_candidate["host_minted_single_use_opaque_handle_required"],
            True,
            "a0_request.host_mint_required",
        )
    elif a0_request_candidate["request_branch"] in {
        "NO_A0_REQUEST_LAWFUL_ABSTENTION",
        "NO_A0_REQUEST_INELIGIBLE",
    }:
        _require_equal(
            a0_request_candidate["private_preissuance_request_candidate"],
            None,
            "a0_request.no_request_private_candidate",
        )
        _require_equal(
            a0_request_candidate["host_minted_single_use_opaque_handle_required"],
            False,
            "a0_request.no_request_host_mint_forbidden",
        )
    else:
        raise SourceFirstOfflineError(["a0_request:unknown_request_branch"])
    for payload_name, payload in (
        ("understanding", understanding),
        ("formalization", formalization),
        ("blind_seed", blind_seed),
        ("a0_request", a0_request_candidate),
    ):
        _require_equal(
            payload["authority_effect"],
            AUTHORITY_EFFECT,
            f"{payload_name}.authority_effect",
        )
        _require_equal(payload["candidate_only"], True, f"{payload_name}.candidate_only")
        _require_equal(payload["signed"], False, f"{payload_name}.signed")


def compile_validation_report(
    *,
    understanding: Mapping[str, Any],
    formalization: Mapping[str, Any],
    blind_seed: Mapping[str, Any],
    a0_request_candidate: Mapping[str, Any],
) -> dict[str, Any]:
    checks = [
        "EXTERNAL_SOURCE_BYTES_REHASHED_AND_BOUND_AT_PACKET_BUILD",
        "SOURCE_AND_ANALYST_STATEMENTS_DISJOINTLY_CLASSIFIED",
        "SOURCE_UNDERSTANDING_PRECEDES_FORMALIZATION",
        "FORMALIZATION_PRECEDES_BLIND_SEED",
        "BLIND_SEED_PRECEDES_A0_REQUEST_CANDIDATE",
        "NO_RETRIEVAL_DURING_UNDERSTANDING_OR_FORMALIZATION",
        "A0_AGENT_VISIBLE_PROJECTION_STRUCTURALLY_ABSENT_PRE_HOST",
        "PRIVATE_QUERY_USES_CLOSED_SANITIZED_SEMANTIC_ATOMS",
        "OFFLINE_COMPILER_DOES_NOT_MINT_OPAQUE_HANDLE_OR_CAPABILITY",
        "ABSTENTION_AND_INELIGIBLE_BRANCHES_REQUIRE_ZERO_A0_POLICY",
        "NO_FACTOR_VIEW_STEP2_RUNTIME_OOS_OR_CANONICAL_AUTHORITY",
    ]
    core = {
        "schema_id": REPORT_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "report_status": "LOCAL_OFFLINE_CONFORMANCE_PASS__NOT_OPERATING_AUTHORITY",
        "understanding_content_sha256": understanding["content_sha256"],
        "formalization_content_sha256": formalization["content_sha256"],
        "blind_seed_content_sha256": blind_seed["content_sha256"],
        "a0_request_candidate_content_sha256": a0_request_candidate["content_sha256"],
        "ordered_check_count": len(checks),
        "ordered_checks": [
            {"ordinal": ordinal, "check_id": check, "result": "PASS"}
            for ordinal, check in enumerate(checks)
        ],
        "source_only_nlp_or_human_semantic_capture_performed_externally": True,
        "retrieval_executed": False,
        "host_memory_accessed": False,
        "canonical_memory_accessed_or_written": False,
        "oos_accessed": False,
        "skill_or_rag_runtime_mutated_or_invoked": False,
        "runtime_or_deployment_performed": False,
        "opaque_handle_minted": False,
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=REPORT_DOMAIN)


def read_stable_regular_bytes(
    path: Path,
    *,
    label: str,
    max_bytes: int,
    require_private: bool = False,
    allow_empty: bool = False,
) -> bytes:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    before = candidate.lstat()
    _require(
        stat.S_ISREG(before.st_mode)
        and not stat.S_ISLNK(before.st_mode)
        and before.st_nlink == 1,
        f"{label}:unsafe",
    )
    if require_private:
        _require(before.st_uid == os.getuid(), f"{label}:wrong_owner")
        _require(stat.S_IMODE(before.st_mode) & 0o077 == 0, f"{label}:not_private")
    _require(
        (allow_empty or before.st_size > 0) and before.st_size <= max_bytes,
        f"{label}:size",
    )
    descriptor = os.open(
        candidate,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        pinned = os.fstat(descriptor)
        _require_equal(
            (pinned.st_dev, pinned.st_ino, pinned.st_size, pinned.st_mtime_ns),
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
            f"{label}:identity_changed_before_read",
        )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            _require(total <= max_bytes, f"{label}:size")
        after_fd = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after_path = candidate.lstat()
    _require_equal(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
        (
            after_fd.st_dev,
            after_fd.st_ino,
            after_fd.st_size,
            after_fd.st_mtime_ns,
        ),
        f"{label}:changed_during_read",
    )
    _require_equal(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
        (
            after_path.st_dev,
            after_path.st_ino,
            after_path.st_size,
            after_path.st_mtime_ns,
        ),
        f"{label}:path_replaced_during_read",
    )
    raw = b"".join(chunks)
    _require_equal(len(raw), before.st_size, f"{label}:read_size")
    return raw


def _strict_source_bytes(path: Path) -> bytes:
    return read_stable_regular_bytes(
        path,
        label="source_file",
        max_bytes=MAX_SOURCE_BYTES,
    )


def compile_packet_manifest(
    *, artifact_rows: Sequence[Mapping[str, Any]], source_bytes: bytes
) -> dict[str, Any]:
    _require_equal(
        [row["ordinal"] for row in artifact_rows],
        list(range(5)),
        "packet.artifact_ordinals",
    )
    artifact_commitment = hashlib.sha256(
        PACKET_ARTIFACT_DOMAIN.encode("utf-8")
        + b"\x00"
        + b"".join(bytes.fromhex(row["sha256"]) for row in artifact_rows)
    ).hexdigest()
    compiler_raw = read_stable_regular_bytes(
        Path(__file__),
        label="compiler_module",
        max_bytes=4 * 1024 * 1024,
    )
    core = {
        "schema_id": PACKET_SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "packet_id": (
            "FF_SOURCE_FIRST_BLIND_HANDOFF_"
            "STANDALONE_OFFLINE_PROTOTYPE_20260829_R1"
        ),
        "manifest_status": (
            "STANDALONE_OFFLINE_ALGORITHM_PROTOTYPE_COMPLETE__"
            "ALL_FACTOR_FORGE_AND_OPERATING_AUTHORITY_UNBOUND_BLOCKING"
        ),
        "lineage_mode": "STANDALONE_OFFLINE_ALGORITHM_PROTOTYPE",
        "factor_forge_successor": False,
        "direct_predecessor_manifest_raw_sha256": None,
        "normative_dependency_count": 0,
        "may_satisfy_any_factor_forge_gate": False,
        "artifact_count": 5,
        "ordered_artifacts": [dict(row) for row in artifact_rows],
        "artifact_manifest_commitment_sha256": artifact_commitment,
        "compiler_profile": {
            "module": "factor_factory/epistemic_source_first_offline.py",
            "bytes": len(compiler_raw),
            "sha256": hashlib.sha256(compiler_raw).hexdigest(),
            "canonicalization": "RFC8785_INTEGER_ONLY_ACCEPTED_JSON_PROFILE",
            "content_digest_formula": (
                "SHA256(UTF8(domain)||0x00||"
                "RFC8785(payload_without_content_sha256))"
            ),
        },
        "source_bytes": len(source_bytes),
        "source_bytes_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "owner_instruction_provenance_state": (
            "CHAT_CONTEXT_ONLY__WORKSPACE_MUTATION_PERMISSION__NONAUTHORITY"
        ),
        "retrieval_execution_allowed": False,
        "host_or_canonical_memory_allowed": False,
        "oos_allowed": False,
        "skill_or_rag_runtime_mutation_allowed": False,
        "runtime_or_deployment_allowed": False,
        "steward_or_host_authority_present": False,
        "permissions_opened_count": 0,
        "signed": False,
        "candidate_only": True,
        "authority_effect": AUTHORITY_EFFECT,
    }
    return _with_content_sha(core, domain=PACKET_DOMAIN)


def validate_source_first_offline_candidate_packet(
    packet_manifest_path: Path, *, source_path: Path
) -> dict[str, Any]:
    manifest_path = Path(packet_manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = Path.cwd() / manifest_path
    _require_equal(manifest_path.name, "packet_manifest.json", "packet_manifest:name")
    root = manifest_path.parent
    expected_artifacts = (
        ("00_source_understanding_candidate.json", "SOURCE_UNDERSTANDING"),
        ("01_source_faithful_formalization_candidate.json", "SOURCE_FORMALIZATION"),
        ("02_blind_mechanism_seed_candidate.json", "BLIND_MECHANISM_SEED"),
        ("03_a0_request_candidate.json", "A0_REQUEST_CANDIDATE"),
        ("04_local_validation_report.json", "LOCAL_VALIDATION_REPORT"),
    )
    expected_names = {"packet_manifest.json", *(name for name, _ in expected_artifacts)}
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
    _require_equal(actual_names, expected_names, "packet:exact6_closure")

    manifest_raw = read_stable_regular_bytes(
        manifest_path,
        label="packet_manifest",
        max_bytes=4 * 1024 * 1024,
        require_private=True,
    )
    manifest = strict_json_loads(manifest_raw, label=str(manifest_path))
    _require(isinstance(manifest, dict), "packet_manifest:object_required")
    _verify_content(manifest, domain=PACKET_DOMAIN, label="packet_manifest")
    rows: list[dict[str, Any]] = []
    payloads: dict[str, dict[str, Any]] = {}
    for ordinal, (name, role) in enumerate(expected_artifacts):
        raw = read_stable_regular_bytes(
            root / name,
            label=f"packet_artifact:{name}",
            max_bytes=4 * 1024 * 1024,
            require_private=True,
        )
        payload = strict_json_loads(raw, label=name)
        _require(isinstance(payload, dict), f"packet_artifact:{name}:object_required")
        payloads[role] = payload
        rows.append(
            {
                "ordinal": ordinal,
                "role": role,
                "path": name,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    _require_equal(manifest["ordered_artifacts"], rows, "packet_manifest:artifact_rows")
    _require_equal(manifest["artifact_count"], 5, "packet_manifest:artifact_count")
    compiler_raw = read_stable_regular_bytes(
        Path(__file__),
        label="compiler_module",
        max_bytes=4 * 1024 * 1024,
    )
    _require_equal(
        manifest["compiler_profile"],
        {
            "module": "factor_factory/epistemic_source_first_offline.py",
            "bytes": len(compiler_raw),
            "sha256": hashlib.sha256(compiler_raw).hexdigest(),
            "canonicalization": "RFC8785_INTEGER_ONLY_ACCEPTED_JSON_PROFILE",
            "content_digest_formula": (
                "SHA256(UTF8(domain)||0x00||"
                "RFC8785(payload_without_content_sha256))"
            ),
        },
        "packet_manifest:compiler_profile",
    )
    _require_equal(
        manifest["artifact_manifest_commitment_sha256"],
        hashlib.sha256(
            PACKET_ARTIFACT_DOMAIN.encode("utf-8")
            + b"\x00"
            + b"".join(bytes.fromhex(row["sha256"]) for row in rows)
        ).hexdigest(),
        "packet_manifest:artifact_commitment",
    )
    understanding = payloads["SOURCE_UNDERSTANDING"]
    formalization = payloads["SOURCE_FORMALIZATION"]
    seed = payloads["BLIND_MECHANISM_SEED"]
    request = payloads["A0_REQUEST_CANDIDATE"]
    validate_source_first_bundle(
        understanding=understanding,
        formalization=formalization,
        blind_seed=seed,
        a0_request_candidate=request,
    )
    expected_report = compile_validation_report(
        understanding=understanding,
        formalization=formalization,
        blind_seed=seed,
        a0_request_candidate=request,
    )
    _require_equal(
        payloads["LOCAL_VALIDATION_REPORT"],
        expected_report,
        "packet:validation_report_closed_equality",
    )
    _require_equal(
        manifest["source_bytes"],
        understanding["source_bundle"]["source_byte_length"],
        "packet_manifest:source_bytes",
    )
    _require_equal(
        manifest["source_bytes_sha256"],
        understanding["source_bundle"]["source_bytes_sha256"],
        "packet_manifest:source_sha256",
    )
    source_bytes = _strict_source_bytes(source_path)
    _require_equal(
        manifest["source_bytes"],
        len(source_bytes),
        "packet_manifest:external_source_bytes",
    )
    _require_equal(
        manifest["source_bytes_sha256"],
        hashlib.sha256(source_bytes).hexdigest(),
        "packet_manifest:external_source_sha256",
    )
    _require_equal(
        manifest,
        compile_packet_manifest(artifact_rows=rows, source_bytes=source_bytes),
        "packet_manifest:closed_equality",
    )
    return manifest


def write_source_first_offline_candidate_packet(
    output_root: Path,
    *,
    source_path: Path,
    source_lineage: Mapping[str, Any],
    author_claims: Sequence[Mapping[str, Any]],
    analyst_notes: Sequence[Mapping[str, Any]],
    selected_semantic_body: Mapping[str, Any],
    pre_a0_predictions: Sequence[Mapping[str, Any]],
    phase_policy_candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source_bytes = _strict_source_bytes(source_path)
    understanding = compile_source_understanding_bundle(
        source_bytes, source_lineage, author_claims, analyst_notes
    )
    formalization = compile_formalization_or_abstention(
        understanding, selected_semantic_body
    )
    blind_seed = compile_blind_mechanism_seed(formalization, pre_a0_predictions)
    request = compile_a0_request_candidate(blind_seed, phase_policy_candidate)
    validate_source_first_bundle(
        understanding=understanding,
        formalization=formalization,
        blind_seed=blind_seed,
        a0_request_candidate=request,
    )
    report = compile_validation_report(
        understanding=understanding,
        formalization=formalization,
        blind_seed=blind_seed,
        a0_request_candidate=request,
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
        artifacts = (
            (
                "00_source_understanding_candidate.json",
                "SOURCE_UNDERSTANDING",
                understanding,
            ),
            (
                "01_source_faithful_formalization_candidate.json",
                "SOURCE_FORMALIZATION",
                formalization,
            ),
            ("02_blind_mechanism_seed_candidate.json", "BLIND_MECHANISM_SEED", blind_seed),
            ("03_a0_request_candidate.json", "A0_REQUEST_CANDIDATE", request),
            ("04_local_validation_report.json", "LOCAL_VALIDATION_REPORT", report),
        )
        for name, _, payload in artifacts:
            write_workspace_json_once(staging_root, name, payload)
        rows = [
            _stable_file_row(staging_root / name, ordinal=ordinal, role=role)
            for ordinal, (name, role, _) in enumerate(artifacts)
        ]
        manifest = compile_packet_manifest(artifact_rows=rows, source_bytes=source_bytes)
        write_workspace_json_once(staging_root, "packet_manifest.json", manifest)
        validate_source_first_offline_candidate_packet(
            staging_root / "packet_manifest.json",
            source_path=source_path,
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
