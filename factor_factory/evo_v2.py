from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any


FEEDBACK_LEDGER_VERSION = "factorforge_evo_feedback_ledger_v2"
MECHANISM_DELTA_VERSION = "factorforge_evo_mechanism_delta_v2"
ECONOMIC_BACKPROJECTION_VERSION = (
    "factorforge_evo_economic_backprojection_v2"
)
EXPERIENCE_TRANSFER_BUNDLE_VERSION = (
    "factorforge_evo_experience_transfer_bundle_v2"
)
TRANSFER_USE_RECEIPT_VERSION = "factorforge_evo_transfer_use_receipt_v2"

BLOCK_EVO_V2_INVALID = "BLOCK_FACTORFORGE_EVO_V2_INVALID"
BLOCK_EVO_V2_MATERIALIZATION_CONFLICT = (
    "BLOCK_FACTORFORGE_EVO_V2_MATERIALIZATION_CONFLICT"
)

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")

PROTECTED_FIELDS = [
    "skill",
    "validator",
    "thresholds",
    "oos_policy",
    "estimand",
    "trial_budget",
]
AUTHORITY_GUARD_FIELDS = frozenset(
    {
        "policy",
        "knowledge_authority",
        "evo_scope",
        "protected_fields",
        "mutation_permissions",
        "canonical_write_allowed",
        "factor_verdict_authority",
        "child_execution_allowed",
    }
)
MUTATION_PERMISSION_FIELDS = frozenset(PROTECTED_FIELDS)
IDENTITY_FIELDS = frozenset(
    {"factor_id", "report_id", "research_id", "branch_id", "run_id"}
)
ARTIFACT_AUTHORITY_FIELDS = frozenset(
    {
        "producer_role",
        "authority_class",
        "host_admission_status",
        "host_admission_ref",
        "independent_review_status",
    }
)
REF_FIELDS = frozenset({"path", "sha256"})

QUALIFICATION_STATES = [
    "PREDICTIONS_FROZEN",
    "IS_DIAGNOSTICS_COMPLETE",
    "CONTRADICTION_CANDIDATE",
    "LOWER_LAYER_QUARANTINE",
    "QUALIFIED_CONTRADICTION",
]
LOWER_LAYER_IDS = [
    "implementation",
    "data_integrity",
    "information_set",
    "measurement",
    "alias_and_control",
]
PREDICTION_ROLES = {"primary", "mechanism_alternative", "null_alias"}
EXPERIENCE_LAYERS = {
    "structural_lesson",
    "conditional_realization",
    "historical_episode",
}

ARTIFACT_FILENAMES = {
    "feedback_ledger": "feedback_ledger.json",
    "mechanism_delta": "mechanism_delta.json",
    "economic_backprojection": "economic_backprojection.json",
    "experience_transfer_bundle": "experience_transfer_bundle.json",
    "transfer_use_receipt": "transfer_use_receipt.json",
}


class EvoV2Error(RuntimeError):
    def __init__(self, token: str, reasons: Sequence[str]) -> None:
        self.token = token
        self.reasons = tuple(dict.fromkeys(str(item) for item in reasons if str(item)))
        super().__init__(f"{token}: {'; '.join(self.reasons)}")


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def content_hash(payload: Mapping[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    return stable_json_hash(unsigned)


def with_content_hash(payload: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(payload)
    output.pop("content_sha256", None)
    output["content_sha256"] = stable_json_hash(output)
    return output


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def artifact_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evo_v2_relative_paths(report_id: str) -> dict[str, str]:
    if not isinstance(report_id, str) or not SAFE_ID_RE.fullmatch(report_id):
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, ["report_id.invalid"])
    root = PurePosixPath("objects") / "evo_v2" / report_id
    return {
        name: (root / filename).as_posix()
        for name, filename in ARTIFACT_FILENAMES.items()
    }


def evo_v2_paths(workspace_root: Path, report_id: str) -> dict[str, Path]:
    return {
        name: workspace_root / relative
        for name, relative in evo_v2_relative_paths(report_id).items()
    }


def _exact_object(
    value: Any,
    allowed: frozenset[str],
    path: str,
    reasons: list[str],
    *,
    required: frozenset[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        reasons.append(f"{path}.object_required")
        return None
    unexpected = sorted(set(value) - set(allowed))
    if unexpected:
        reasons.append(f"{path}.unexpected_fields:" + ",".join(unexpected))
    missing = sorted(set(required or allowed) - set(value))
    if missing:
        reasons.append(f"{path}.missing_fields:" + ",".join(missing))
    return value


def _list(
    value: Any,
    path: str,
    reasons: list[str],
    *,
    minimum: int = 0,
) -> list[Any] | None:
    if not isinstance(value, list) or len(value) < minimum:
        reasons.append(f"{path}.list_minimum_{minimum}")
        return None
    return value


def _nonempty_string(value: Any, path: str, reasons: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        reasons.append(f"{path}.nonempty_string_required")
        return None
    normalized = value.strip().lower()
    if normalized in {"unknown", "todo", "tbd", "n/a", "none", "under_specified"}:
        reasons.append(f"{path}.placeholder_forbidden")
        return None
    return value


def _safe_id(value: Any, path: str, reasons: list[str]) -> str | None:
    if (
        not isinstance(value, str)
        or not SAFE_ID_RE.fullmatch(value)
        or ".." in value
    ):
        reasons.append(f"{path}.safe_id_required")
        return None
    return value


def _exact_bool(value: Any, expected: bool, path: str, reasons: list[str]) -> None:
    if value is not expected:
        reasons.append(f"{path}.must_be_{str(expected).lower()}")


def _finite_number(value: Any, path: str, reasons: list[str]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        reasons.append(f"{path}.finite_number_required")
        return None
    result = float(value)
    if not math.isfinite(result):
        reasons.append(f"{path}.finite_number_required")
        return None
    return result


def _string_list(
    value: Any,
    path: str,
    reasons: list[str],
    *,
    minimum: int = 1,
) -> list[str] | None:
    values = _list(value, path, reasons, minimum=minimum)
    if values is None:
        return None
    if any(not isinstance(item, str) or not item.strip() for item in values):
        reasons.append(f"{path}.nonempty_strings_required")
        return None
    if len(set(values)) != len(values):
        reasons.append(f"{path}.duplicates_forbidden")
    return list(values)


def _validate_identity(value: Any, path: str, reasons: list[str]) -> dict[str, Any] | None:
    identity = _exact_object(value, IDENTITY_FIELDS, path, reasons)
    if identity is None:
        return None
    for field in sorted(IDENTITY_FIELDS):
        _safe_id(identity.get(field), f"{path}.{field}", reasons)
    return identity


def _validate_authority_guard(value: Any, path: str, reasons: list[str]) -> None:
    guard = _exact_object(value, AUTHORITY_GUARD_FIELDS, path, reasons)
    if guard is None:
        return
    exact_values = {
        "policy": "constitutional_invariance_epistemic_evolution_only",
        "knowledge_authority": "advisory_only",
        "evo_scope": "questions_tests_public_derivations_and_transfer_mappings_only",
    }
    for field, expected in exact_values.items():
        if guard.get(field) != expected:
            reasons.append(f"{path}.{field}.invalid")
    if guard.get("protected_fields") != PROTECTED_FIELDS:
        reasons.append(f"{path}.protected_fields.invalid")
    permissions = _exact_object(
        guard.get("mutation_permissions"),
        MUTATION_PERMISSION_FIELDS,
        f"{path}.mutation_permissions",
        reasons,
    )
    if permissions is not None:
        for field in PROTECTED_FIELDS:
            _exact_bool(
                permissions.get(field),
                False,
                f"{path}.mutation_permissions.{field}",
                reasons,
            )
    _exact_bool(
        guard.get("canonical_write_allowed"),
        False,
        f"{path}.canonical_write_allowed",
        reasons,
    )
    _exact_bool(
        guard.get("factor_verdict_authority"),
        False,
        f"{path}.factor_verdict_authority",
        reasons,
    )
    _exact_bool(
        guard.get("child_execution_allowed"),
        False,
        f"{path}.child_execution_allowed",
        reasons,
    )


def _validate_artifact_authority(
    value: Any,
    path: str,
    reasons: list[str],
    *,
    workspace_root: Path | None,
    known_artifacts: Mapping[str, Mapping[str, Any]],
    verify_refs: bool,
    expected_class: str,
    expected_review_status: str,
) -> None:
    authority = _exact_object(value, ARTIFACT_AUTHORITY_FIELDS, path, reasons)
    if authority is None:
        return
    _nonempty_string(authority.get("producer_role"), f"{path}.producer_role", reasons)
    if authority.get("authority_class") != expected_class:
        reasons.append(f"{path}.authority_class.invalid")
    if authority.get("host_admission_status") != "HOST_ADMITTED":
        reasons.append(f"{path}.host_admission_status.invalid")
    _validate_ref(
        authority.get("host_admission_ref"),
        f"{path}.host_admission_ref",
        reasons,
        workspace_root=workspace_root,
        known_artifacts=known_artifacts,
        verify_refs=verify_refs,
    )
    if authority.get("independent_review_status") != expected_review_status:
        reasons.append(f"{path}.independent_review_status.invalid")


def _normalize_ref_path(
    value: Any,
    path: str,
    reasons: list[str],
) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        reasons.append(f"{path}.workspace_relative_path_required")
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or candidate == PurePosixPath("."):
        reasons.append(f"{path}.workspace_relative_path_required")
        return None
    normalized = candidate.as_posix()
    if normalized != value or value.endswith("/"):
        reasons.append(f"{path}.normalized_path_required")
        return None
    return normalized


def _validate_ref(
    value: Any,
    path: str,
    reasons: list[str],
    *,
    workspace_root: Path | None,
    known_artifacts: Mapping[str, Mapping[str, Any]],
    verify_refs: bool,
) -> dict[str, Any] | None:
    ref = _exact_object(value, REF_FIELDS, path, reasons)
    if ref is None:
        return None
    relative = _normalize_ref_path(ref.get("path"), f"{path}.path", reasons)
    digest = ref.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        reasons.append(f"{path}.sha256.invalid")
        return ref
    if not verify_refs or relative is None:
        return ref
    if relative in known_artifacts:
        if artifact_sha256(known_artifacts[relative]) != digest:
            reasons.append(f"{path}.sha256_mismatch")
        return ref
    if workspace_root is None:
        reasons.append(f"{path}.workspace_required_for_external_ref")
        return ref
    root = workspace_root.resolve()
    candidate = root / relative
    if not candidate.is_file():
        reasons.append(f"{path}.missing_file")
        return ref
    try:
        candidate.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        reasons.append(f"{path}.path_escape")
        return ref
    if sha256_file(candidate) != digest:
        reasons.append(f"{path}.sha256_mismatch")
    return ref


def _validate_refs(
    value: Any,
    path: str,
    reasons: list[str],
    *,
    workspace_root: Path | None,
    known_artifacts: Mapping[str, Mapping[str, Any]],
    verify_refs: bool,
    minimum: int = 1,
) -> None:
    refs = _list(value, path, reasons, minimum=minimum)
    if refs is None:
        return
    for index, ref in enumerate(refs):
        _validate_ref(
            ref,
            f"{path}[{index}]",
            reasons,
            workspace_root=workspace_root,
            known_artifacts=known_artifacts,
            verify_refs=verify_refs,
        )


def _load_verified_ref_payload(
    value: Any,
    *,
    workspace_root: Path | None,
    known_artifacts: Mapping[str, Mapping[str, Any]],
    verify_refs: bool,
) -> Mapping[str, Any] | None:
    """Read a path/hash-bound JSON reference after the generic ref gate.

    Semantic validators use this only for formal ``verify_refs=True`` calls.
    ``known_artifacts`` may satisfy canonical in-memory bundle refs; external
    receipts must resolve to immutable workspace JSON.
    """

    if not verify_refs or not isinstance(value, dict):
        return None
    relative = value.get("path")
    if not isinstance(relative, str):
        return None
    if relative in known_artifacts:
        candidate = known_artifacts[relative]
        return candidate if isinstance(candidate, Mapping) else None
    if workspace_root is None:
        return None
    root = workspace_root.resolve(strict=False)
    candidate_path = (root / relative).resolve(strict=False)
    try:
        candidate_path.relative_to(root)
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _validate_retrieval_evidence_semantics(
    refs: Any,
    *,
    memory_state: Any,
    mechanism_fingerprint: Mapping[str, Any] | None,
    workspace_root: Path | None,
    known_artifacts: Mapping[str, Mapping[str, Any]],
    verify_refs: bool,
    reasons: list[str],
) -> None:
    if not verify_refs or not isinstance(refs, list):
        return
    payloads = [
        _load_verified_ref_payload(
            item,
            workspace_root=workspace_root,
            known_artifacts=known_artifacts,
            verify_refs=verify_refs,
        )
        for item in refs
    ]
    if any(item is None for item in payloads):
        reasons.append(
            "experience_transfer_bundle.retrieval_policy.retrieval_evidence_payload.invalid"
        )
        return
    for index, payload in enumerate(payloads):
        assert payload is not None
        inventory = (
            payload.get("inventory")
            if isinstance(payload.get("inventory"), Mapping)
            else payload
        )
        hit_count = inventory.get("admissible_hit_count")
        if type(hit_count) is not int or hit_count < 0:
            reasons.append(
                "experience_transfer_bundle.retrieval_policy."
                f"retrieval_evidence_refs[{index}].admissible_hit_count.invalid"
            )
        query = payload.get("query") if isinstance(payload.get("query"), Mapping) else {}
        fingerprint_hash = query.get("mechanism_fingerprint_sha256")
        expected_fingerprint_hash = stable_json_hash(mechanism_fingerprint or {})
        if fingerprint_hash != expected_fingerprint_hash:
            reasons.append(
                "experience_transfer_bundle.retrieval_policy."
                f"retrieval_evidence_refs[{index}].mechanism_fingerprint_hash.mismatch"
            )
        checked = inventory.get("checked_indexes")
        if not isinstance(checked, list) or not checked or any(
            not (
                (isinstance(item, str) and item)
                or (
                    isinstance(item, Mapping)
                    and isinstance(item.get("index_id"), str)
                    and item.get("index_id")
                )
            )
            for item in checked
        ):
            reasons.append(
                "experience_transfer_bundle.retrieval_policy."
                f"retrieval_evidence_refs[{index}].checked_indexes.invalid"
            )
        if (
            memory_state == "COLD_START_NO_ADMISSIBLE_MEMORY"
            and hit_count != 0
        ):
            reasons.append(
                "experience_transfer_bundle.retrieval_policy."
                "cold_start_requires_zero_admissible_hits"
            )
        if memory_state == "ADMISSIBLE_MEMORY_FOUND" and (
            type(hit_count) is not int or hit_count < 1
        ):
            reasons.append(
                "experience_transfer_bundle.retrieval_policy."
                "memory_found_requires_positive_admissible_hits"
            )


def _validate_content_hash(payload: Mapping[str, Any], path: str, reasons: list[str]) -> None:
    digest = payload.get("content_sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        reasons.append(f"{path}.content_sha256.invalid")
    elif digest != content_hash(payload):
        reasons.append(f"{path}.content_sha256_mismatch")


def _validate_oos_control(value: Any, path: str, reasons: list[str]) -> None:
    fields = frozenset(
        {
            "search_use",
            "oos_accessed",
            "oos_used_for_contradiction",
            "oos_used_for_revision",
        }
    )
    control = _exact_object(value, fields, path, reasons)
    if control is None:
        return
    if control.get("search_use") != "SEALED_NOT_ACCESSED":
        reasons.append(f"{path}.search_use.invalid")
    for field in fields - {"search_use"}:
        _exact_bool(control.get(field), False, f"{path}.{field}", reasons)


def validate_feedback_ledger(
    payload: Any,
    *,
    workspace_root: Path | None = None,
    known_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
    verify_refs: bool = True,
) -> list[str]:
    reasons: list[str] = []
    fields = frozenset(
        {
            "contract_version",
            "artifact_identity",
            "authority_guard",
            "artifact_authority",
            "frozen_authority",
            "state_history",
            "current_state",
            "hypothesis_predictions",
            "contradiction",
            "lower_layer_clearance",
            "qualification",
            "oos_control",
            "content_sha256",
        }
    )
    ledger = _exact_object(payload, fields, "feedback_ledger", reasons)
    if ledger is None:
        return reasons
    known = known_artifacts or {}
    if ledger.get("contract_version") != FEEDBACK_LEDGER_VERSION:
        reasons.append("feedback_ledger.contract_version.invalid")
    _validate_identity(ledger.get("artifact_identity"), "feedback_ledger.artifact_identity", reasons)
    _validate_authority_guard(ledger.get("authority_guard"), "feedback_ledger.authority_guard", reasons)
    _validate_artifact_authority(
        ledger.get("artifact_authority"),
        "feedback_ledger.artifact_authority",
        reasons,
        workspace_root=workspace_root,
        known_artifacts=known,
        verify_refs=verify_refs,
        expected_class="qualified_contradiction_advisory_only",
        expected_review_status="NOT_REQUIRED_PRE_MEMORY",
    )

    frozen_fields = frozenset(
        {
            "economic_hypothesis_ref",
            "measurement_program_ref",
            "estimand_id",
            "estimand_sha256",
            "threshold_registry_ref",
            "oos_policy_ref",
            "trial_budget_ref",
            "immutable_values_sha256",
        }
    )
    frozen = _exact_object(
        ledger.get("frozen_authority"),
        frozen_fields,
        "feedback_ledger.frozen_authority",
        reasons,
    )
    if frozen is not None:
        for field in (
            "economic_hypothesis_ref",
            "measurement_program_ref",
            "threshold_registry_ref",
            "oos_policy_ref",
            "trial_budget_ref",
        ):
            _validate_ref(
                frozen.get(field),
                f"feedback_ledger.frozen_authority.{field}",
                reasons,
                workspace_root=workspace_root,
                known_artifacts=known,
                verify_refs=verify_refs,
            )
        _safe_id(
            frozen.get("estimand_id"),
            "feedback_ledger.frozen_authority.estimand_id",
            reasons,
        )
        for field in ("estimand_sha256", "immutable_values_sha256"):
            value = frozen.get(field)
            if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
                reasons.append(f"feedback_ledger.frozen_authority.{field}.invalid")

    history = _list(
        ledger.get("state_history"),
        "feedback_ledger.state_history",
        reasons,
        minimum=len(QUALIFICATION_STATES),
    )
    if history is not None:
        if len(history) != len(QUALIFICATION_STATES):
            reasons.append("feedback_ledger.state_history.exact_sequence_required")
        observed_states: list[Any] = []
        state_fields = frozenset({"sequence", "state", "actor_role", "evidence_refs"})
        for index, item in enumerate(history):
            entry = _exact_object(
                item,
                state_fields,
                f"feedback_ledger.state_history[{index}]",
                reasons,
            )
            if entry is None:
                continue
            if entry.get("sequence") != index + 1:
                reasons.append(f"feedback_ledger.state_history[{index}].sequence.invalid")
            observed_states.append(entry.get("state"))
            _nonempty_string(
                entry.get("actor_role"),
                f"feedback_ledger.state_history[{index}].actor_role",
                reasons,
            )
            _validate_refs(
                entry.get("evidence_refs"),
                f"feedback_ledger.state_history[{index}].evidence_refs",
                reasons,
                workspace_root=workspace_root,
                known_artifacts=known,
                verify_refs=verify_refs,
            )
        if observed_states != QUALIFICATION_STATES:
            reasons.append("feedback_ledger.state_history.invalid_transition")
    if ledger.get("current_state") != "QUALIFIED_CONTRADICTION":
        reasons.append("feedback_ledger.current_state.not_qualified")

    predictions = _list(
        ledger.get("hypothesis_predictions"),
        "feedback_ledger.hypothesis_predictions",
        reasons,
        minimum=3,
    )
    prediction_ids: set[str] = set()
    model_ids: set[str] = set()
    roles: set[str] = set()
    if predictions is not None:
        prediction_fields = frozenset(
            {
                "prediction_id",
                "model_id",
                "model_role",
                "expected_signature",
                "falsifier",
                "preregistration_ref",
                "uses_oos",
            }
        )
        signature_fields = frozenset(
            {
                "metric_id",
                "direction",
                "shape",
                "horizon",
                "conditioning_set",
                "materiality_floor",
                "unique_against_model_ids",
            }
        )
        for index, item in enumerate(predictions):
            prefix = f"feedback_ledger.hypothesis_predictions[{index}]"
            prediction = _exact_object(item, prediction_fields, prefix, reasons)
            if prediction is None:
                continue
            prediction_id = _safe_id(prediction.get("prediction_id"), f"{prefix}.prediction_id", reasons)
            model_id = _safe_id(prediction.get("model_id"), f"{prefix}.model_id", reasons)
            if prediction_id:
                if prediction_id in prediction_ids:
                    reasons.append(f"{prefix}.prediction_id.duplicate")
                prediction_ids.add(prediction_id)
            if model_id:
                if model_id in model_ids:
                    reasons.append(f"{prefix}.model_id.duplicate")
                model_ids.add(model_id)
            role = prediction.get("model_role")
            if role not in PREDICTION_ROLES:
                reasons.append(f"{prefix}.model_role.invalid")
            else:
                roles.add(role)
            signature = _exact_object(
                prediction.get("expected_signature"),
                signature_fields,
                f"{prefix}.expected_signature",
                reasons,
            )
            if signature is not None:
                for field in ("metric_id", "direction", "shape", "horizon", "materiality_floor"):
                    _nonempty_string(signature.get(field), f"{prefix}.expected_signature.{field}", reasons)
                _string_list(
                    signature.get("conditioning_set"),
                    f"{prefix}.expected_signature.conditioning_set",
                    reasons,
                    minimum=1,
                )
                _string_list(
                    signature.get("unique_against_model_ids"),
                    f"{prefix}.expected_signature.unique_against_model_ids",
                    reasons,
                    minimum=1,
                )
            _nonempty_string(prediction.get("falsifier"), f"{prefix}.falsifier", reasons)
            _validate_ref(
                prediction.get("preregistration_ref"),
                f"{prefix}.preregistration_ref",
                reasons,
                workspace_root=workspace_root,
                known_artifacts=known,
                verify_refs=verify_refs,
            )
            _exact_bool(prediction.get("uses_oos"), False, f"{prefix}.uses_oos", reasons)
        if roles != PREDICTION_ROLES:
            reasons.append("feedback_ledger.hypothesis_predictions.required_roles")

    contradiction_fields = frozenset(
        {
            "contradiction_id",
            "source_prediction_ids",
            "observed_signature",
            "mismatch_kind",
            "materiality_assessment",
            "competing_explanations",
            "discriminating_test",
            "evidence_refs",
            "is_large_residual_only",
            "uses_oos",
        }
    )
    contradiction = _exact_object(
        ledger.get("contradiction"),
        contradiction_fields,
        "feedback_ledger.contradiction",
        reasons,
    )
    if contradiction is not None:
        _safe_id(contradiction.get("contradiction_id"), "feedback_ledger.contradiction.contradiction_id", reasons)
        source_predictions = _string_list(
            contradiction.get("source_prediction_ids"),
            "feedback_ledger.contradiction.source_prediction_ids",
            reasons,
            minimum=1,
        )
        if source_predictions is not None and not set(source_predictions) <= prediction_ids:
            reasons.append("feedback_ledger.contradiction.source_prediction_ids.unbound")
        observed_fields = frozenset(
            {"metric_id", "direction", "shape", "horizon", "conditioning_set", "evidence_refs"}
        )
        observed = _exact_object(
            contradiction.get("observed_signature"),
            observed_fields,
            "feedback_ledger.contradiction.observed_signature",
            reasons,
        )
        if observed is not None:
            for field in ("metric_id", "direction", "shape", "horizon"):
                _nonempty_string(observed.get(field), f"feedback_ledger.contradiction.observed_signature.{field}", reasons)
            _string_list(
                observed.get("conditioning_set"),
                "feedback_ledger.contradiction.observed_signature.conditioning_set",
                reasons,
                minimum=1,
            )
            _validate_refs(
                observed.get("evidence_refs"),
                "feedback_ledger.contradiction.observed_signature.evidence_refs",
                reasons,
                workspace_root=workspace_root,
                known_artifacts=known,
                verify_refs=verify_refs,
            )
        if contradiction.get("mismatch_kind") not in {
            "sign",
            "shape",
            "horizon",
            "invariance",
            "interaction",
            "boundary",
            "cost_capacity_projection",
        }:
            reasons.append("feedback_ledger.contradiction.mismatch_kind.invalid")
        _nonempty_string(
            contradiction.get("materiality_assessment"),
            "feedback_ledger.contradiction.materiality_assessment",
            reasons,
        )
        explanations = _list(
            contradiction.get("competing_explanations"),
            "feedback_ledger.contradiction.competing_explanations",
            reasons,
            minimum=2,
        )
        explanation_ids: set[str] = set()
        if explanations is not None:
            explanation_fields = frozenset(
                {"explanation_id", "failed_layer", "claim", "distinguishing_evidence_needed"}
            )
            for index, item in enumerate(explanations):
                prefix = f"feedback_ledger.contradiction.competing_explanations[{index}]"
                explanation = _exact_object(item, explanation_fields, prefix, reasons)
                if explanation is None:
                    continue
                explanation_id = _safe_id(explanation.get("explanation_id"), f"{prefix}.explanation_id", reasons)
                if explanation_id:
                    if explanation_id in explanation_ids:
                        reasons.append(f"{prefix}.explanation_id.duplicate")
                    explanation_ids.add(explanation_id)
                if explanation.get("failed_layer") not in {
                    "economic_hypothesis",
                    "primary_math_mechanism",
                    "market_outcome_projection",
                    "applicable_audits",
                    "observation_equation",
                    "measurement_program",
                }:
                    reasons.append(f"{prefix}.failed_layer.invalid")
                _nonempty_string(explanation.get("claim"), f"{prefix}.claim", reasons)
                _nonempty_string(
                    explanation.get("distinguishing_evidence_needed"),
                    f"{prefix}.distinguishing_evidence_needed",
                    reasons,
                )
        _nonempty_string(
            contradiction.get("discriminating_test"),
            "feedback_ledger.contradiction.discriminating_test",
            reasons,
        )
        _validate_refs(
            contradiction.get("evidence_refs"),
            "feedback_ledger.contradiction.evidence_refs",
            reasons,
            workspace_root=workspace_root,
            known_artifacts=known,
            verify_refs=verify_refs,
        )
        _exact_bool(
            contradiction.get("is_large_residual_only"),
            False,
            "feedback_ledger.contradiction.is_large_residual_only",
            reasons,
        )
        _exact_bool(
            contradiction.get("uses_oos"),
            False,
            "feedback_ledger.contradiction.uses_oos",
            reasons,
        )

    clearance = _list(
        ledger.get("lower_layer_clearance"),
        "feedback_ledger.lower_layer_clearance",
        reasons,
        minimum=len(LOWER_LAYER_IDS),
    )
    if clearance is not None:
        if len(clearance) != len(LOWER_LAYER_IDS):
            reasons.append("feedback_ledger.lower_layer_clearance.exact_set_required")
        observed_layers: list[Any] = []
        clearance_fields = frozenset({"layer_id", "status", "finding", "evidence_refs"})
        for index, item in enumerate(clearance):
            prefix = f"feedback_ledger.lower_layer_clearance[{index}]"
            layer = _exact_object(item, clearance_fields, prefix, reasons)
            if layer is None:
                continue
            observed_layers.append(layer.get("layer_id"))
            if layer.get("status") != "CLEARED":
                reasons.append(f"{prefix}.status.not_cleared")
            _nonempty_string(layer.get("finding"), f"{prefix}.finding", reasons)
            _validate_refs(
                layer.get("evidence_refs"),
                f"{prefix}.evidence_refs",
                reasons,
                workspace_root=workspace_root,
                known_artifacts=known,
                verify_refs=verify_refs,
            )
        if observed_layers != LOWER_LAYER_IDS:
            reasons.append("feedback_ledger.lower_layer_clearance.invalid_order_or_set")

    qualification_fields = frozenset(
        {
            "decision",
            "legal_information_set",
            "preregistered_prediction",
            "within_frozen_trial_budget",
            "multiplicity_controlled",
            "replicated_in_purged_is",
            "materiality_pass",
            "discriminates_models",
            "lower_layers_cleared",
            "oos_reused",
            "authority_scope",
            "factor_verdict_authority",
            "branch_execution_authority",
        }
    )
    qualification = _exact_object(
        ledger.get("qualification"),
        qualification_fields,
        "feedback_ledger.qualification",
        reasons,
    )
    if qualification is not None:
        if qualification.get("decision") != "QUALIFIED":
            reasons.append("feedback_ledger.qualification.decision.invalid")
        for field in (
            "legal_information_set",
            "preregistered_prediction",
            "within_frozen_trial_budget",
            "multiplicity_controlled",
            "replicated_in_purged_is",
            "materiality_pass",
            "discriminates_models",
            "lower_layers_cleared",
        ):
            _exact_bool(
                qualification.get(field),
                True,
                f"feedback_ledger.qualification.{field}",
                reasons,
            )
        for field in ("oos_reused", "factor_verdict_authority", "branch_execution_authority"):
            _exact_bool(
                qualification.get(field),
                False,
                f"feedback_ledger.qualification.{field}",
                reasons,
            )
        if qualification.get("authority_scope") != "research_scheduling_only":
            reasons.append("feedback_ledger.qualification.authority_scope.invalid")
    _validate_oos_control(ledger.get("oos_control"), "feedback_ledger.oos_control", reasons)
    _validate_content_hash(ledger, "feedback_ledger", reasons)
    return list(dict.fromkeys(reasons))


def validate_mechanism_delta(
    payload: Any,
    *,
    feedback_ledger: Mapping[str, Any] | None = None,
    workspace_root: Path | None = None,
    known_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
    verify_refs: bool = True,
) -> list[str]:
    reasons: list[str] = []
    fields = frozenset(
        {
            "contract_version",
            "artifact_identity",
            "authority_guard",
            "artifact_authority",
            "feedback_ref",
            "contradiction_id",
            "baseline_model",
            "minimal_extension",
            "distinctive_predictions",
            "public_derivation_record",
            "status",
            "oos_control",
            "content_sha256",
        }
    )
    delta = _exact_object(payload, fields, "mechanism_delta", reasons)
    if delta is None:
        return reasons
    known = known_artifacts or {}
    if delta.get("contract_version") != MECHANISM_DELTA_VERSION:
        reasons.append("mechanism_delta.contract_version.invalid")
    _validate_identity(delta.get("artifact_identity"), "mechanism_delta.artifact_identity", reasons)
    _validate_authority_guard(delta.get("authority_guard"), "mechanism_delta.authority_guard", reasons)
    _validate_artifact_authority(
        delta.get("artifact_authority"),
        "mechanism_delta.artifact_authority",
        reasons,
        workspace_root=workspace_root,
        known_artifacts=known,
        verify_refs=verify_refs,
        expected_class="dirac_minimal_extension_advisory_only",
        expected_review_status="NOT_CANONICAL_PENDING_INDEPENDENT_REVIEW",
    )
    _validate_ref(
        delta.get("feedback_ref"),
        "mechanism_delta.feedback_ref",
        reasons,
        workspace_root=workspace_root,
        known_artifacts=known,
        verify_refs=verify_refs,
    )
    _safe_id(delta.get("contradiction_id"), "mechanism_delta.contradiction_id", reasons)

    baseline_fields = frozenset(
        {
            "model_id",
            "mathematical_object",
            "mechanism_equation_or_functional",
            "target_functional",
            "market_outcome_projection",
            "observation_mapping",
            "estimand_id",
        }
    )
    baseline = _exact_object(
        delta.get("baseline_model"),
        baseline_fields,
        "mechanism_delta.baseline_model",
        reasons,
    )
    if baseline is not None:
        _safe_id(baseline.get("model_id"), "mechanism_delta.baseline_model.model_id", reasons)
        _safe_id(baseline.get("estimand_id"), "mechanism_delta.baseline_model.estimand_id", reasons)
        for field in baseline_fields - {"model_id", "estimand_id"}:
            _nonempty_string(baseline.get(field), f"mechanism_delta.baseline_model.{field}", reasons)

    extension_fields = frozenset(
        {
            "delta_id",
            "extension_kind",
            "baseline_equation",
            "extended_equation",
            "missing_term",
            "lambda_symbol",
            "recovery_limit",
            "recovery_check",
            "broken_invariant_or_boundary",
            "added_mathematical_object",
            "preserved_invariants",
            "information_preserved",
            "information_discarded",
            "complexity_delta",
            "minimality_argument",
            "minimality_evidence",
            "rejected_larger_extensions",
        }
    )
    extension = _exact_object(
        delta.get("minimal_extension"),
        extension_fields,
        "mechanism_delta.minimal_extension",
        reasons,
    )
    delta_id: str | None = None
    if extension is not None:
        delta_id = _safe_id(extension.get("delta_id"), "mechanism_delta.minimal_extension.delta_id", reasons)
        for field in (
            "extension_kind",
            "baseline_equation",
            "extended_equation",
            "missing_term",
            "lambda_symbol",
            "recovery_limit",
            "broken_invariant_or_boundary",
            "added_mathematical_object",
            "information_preserved",
            "information_discarded",
            "minimality_argument",
        ):
            _nonempty_string(extension.get(field), f"mechanism_delta.minimal_extension.{field}", reasons)
        if baseline is not None and extension.get("baseline_equation") != baseline.get("mechanism_equation_or_functional"):
            reasons.append("mechanism_delta.minimal_extension.baseline_equation.mismatch")
        _string_list(
            extension.get("preserved_invariants"),
            "mechanism_delta.minimal_extension.preserved_invariants",
            reasons,
            minimum=1,
        )

        complexity = extension.get("complexity_delta")
        if isinstance(complexity, bool) or not isinstance(complexity, int) or complexity < 1:
            reasons.append("mechanism_delta.minimal_extension.complexity_delta.positive_integer_required")
        recovery_fields = frozenset({"parameter", "limit_value", "recovers_baseline"})
        recovery = _exact_object(
            extension.get("recovery_check"),
            recovery_fields,
            "mechanism_delta.minimal_extension.recovery_check",
            reasons,
        )
        if recovery is not None:
            if recovery.get("parameter") != extension.get("lambda_symbol"):
                reasons.append("mechanism_delta.minimal_extension.recovery_check.parameter_mismatch")
            if recovery.get("limit_value") != 0:
                reasons.append("mechanism_delta.minimal_extension.recovery_check.limit_value_must_be_zero")
            _exact_bool(
                recovery.get("recovers_baseline"),
                True,
                "mechanism_delta.minimal_extension.recovery_check.recovers_baseline",
                reasons,
            )
        evidence_fields = frozenset(
            {
                "term_necessity_test",
                "removal_recovers_contradiction",
                "no_estimand_change",
                "no_threshold_change",
                "no_trial_budget_change",
            }
        )
        evidence = _exact_object(
            extension.get("minimality_evidence"),
            evidence_fields,
            "mechanism_delta.minimal_extension.minimality_evidence",
            reasons,
        )
        if evidence is not None:
            _nonempty_string(
                evidence.get("term_necessity_test"),
                "mechanism_delta.minimal_extension.minimality_evidence.term_necessity_test",
                reasons,
            )
            for field in evidence_fields - {"term_necessity_test"}:
                _exact_bool(
                    evidence.get(field),
                    True,
                    f"mechanism_delta.minimal_extension.minimality_evidence.{field}",
                    reasons,
                )
        _string_list(
            extension.get("rejected_larger_extensions"),
            "mechanism_delta.minimal_extension.rejected_larger_extensions",
            reasons,
            minimum=1,
        )

    predictions = _list(
        delta.get("distinctive_predictions"),
        "mechanism_delta.distinctive_predictions",
        reasons,
        minimum=1,
    )
    delta_prediction_ids: set[str] = set()
    if predictions is not None:
        prediction_fields = frozenset(
            {
                "prediction_id",
                "target_model_ids",
                "predicted_signature",
                "unique_to_extension",
                "discriminating_test",
                "falsifier",
                "legal_information_time",
                "uses_oos",
            }
        )
        for index, item in enumerate(predictions):
            prefix = f"mechanism_delta.distinctive_predictions[{index}]"
            prediction = _exact_object(item, prediction_fields, prefix, reasons)
            if prediction is None:
                continue
            prediction_id = _safe_id(prediction.get("prediction_id"), f"{prefix}.prediction_id", reasons)
            if prediction_id:
                if prediction_id in delta_prediction_ids:
                    reasons.append(f"{prefix}.prediction_id.duplicate")
                delta_prediction_ids.add(prediction_id)
            targets = _string_list(prediction.get("target_model_ids"), f"{prefix}.target_model_ids", reasons, minimum=2)
            if targets is not None and baseline is not None and baseline.get("model_id") not in targets:
                reasons.append(f"{prefix}.target_model_ids.baseline_missing")
            for field in ("predicted_signature", "discriminating_test", "falsifier", "legal_information_time"):
                _nonempty_string(prediction.get(field), f"{prefix}.{field}", reasons)
            _exact_bool(prediction.get("unique_to_extension"), True, f"{prefix}.unique_to_extension", reasons)
            _exact_bool(prediction.get("uses_oos"), False, f"{prefix}.uses_oos", reasons)

    derivation_fields = frozenset(
        {
            "definitions",
            "assumptions",
            "key_derivation_steps",
            "limiting_cases",
            "overclaim_guard",
            "private_chain_of_thought_included",
        }
    )
    derivation = _exact_object(
        delta.get("public_derivation_record"),
        derivation_fields,
        "mechanism_delta.public_derivation_record",
        reasons,
    )
    if derivation is not None:
        for field, minimum in (
            ("definitions", 1),
            ("assumptions", 1),
            ("key_derivation_steps", 2),
            ("limiting_cases", 2),
        ):
            _string_list(
                derivation.get(field),
                f"mechanism_delta.public_derivation_record.{field}",
                reasons,
                minimum=minimum,
            )
        _nonempty_string(
            derivation.get("overclaim_guard"),
            "mechanism_delta.public_derivation_record.overclaim_guard",
            reasons,
        )
        _exact_bool(
            derivation.get("private_chain_of_thought_included"),
            False,
            "mechanism_delta.public_derivation_record.private_chain_of_thought_included",
            reasons,
        )
    if delta.get("status") != "DERIVED_REVIEW_ONLY":
        reasons.append("mechanism_delta.status.invalid")
    _validate_oos_control(delta.get("oos_control"), "mechanism_delta.oos_control", reasons)

    if feedback_ledger is not None:
        if feedback_ledger.get("current_state") != "QUALIFIED_CONTRADICTION":
            reasons.append("mechanism_delta.feedback.not_qualified")
        feedback_contradiction = feedback_ledger.get("contradiction")
        if not isinstance(feedback_contradiction, dict) or delta.get("contradiction_id") != feedback_contradiction.get("contradiction_id"):
            reasons.append("mechanism_delta.contradiction_id.feedback_mismatch")
        feedback_frozen = feedback_ledger.get("frozen_authority")
        if isinstance(feedback_frozen, dict) and baseline is not None:
            if baseline.get("estimand_id") != feedback_frozen.get("estimand_id"):
                reasons.append("mechanism_delta.baseline_model.estimand_changed")
        feedback_predictions = feedback_ledger.get("hypothesis_predictions")
        feedback_model_ids = {
            str(item.get("model_id"))
            for item in feedback_predictions or []
            if isinstance(item, dict)
        }
        if predictions is not None:
            for index, item in enumerate(predictions):
                if isinstance(item, dict):
                    targets = set(item.get("target_model_ids") or [])
                    if not targets <= feedback_model_ids:
                        reasons.append(f"mechanism_delta.distinctive_predictions[{index}].target_model_ids.unbound")
    _validate_content_hash(delta, "mechanism_delta", reasons)
    return list(dict.fromkeys(reasons))


def validate_economic_backprojection(
    payload: Any,
    *,
    mechanism_delta: Mapping[str, Any] | None = None,
    workspace_root: Path | None = None,
    known_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
    verify_refs: bool = True,
) -> list[str]:
    reasons: list[str] = []
    fields = frozenset(
        {
            "contract_version",
            "artifact_identity",
            "authority_guard",
            "artifact_authority",
            "mechanism_delta_ref",
            "delta_id",
            "economic_mapping",
            "competing_economic_explanations",
            "predicted_economic_signatures",
            "qualification",
            "status",
            "oos_control",
            "content_sha256",
        }
    )
    backprojection = _exact_object(payload, fields, "economic_backprojection", reasons)
    if backprojection is None:
        return reasons
    known = known_artifacts or {}
    if backprojection.get("contract_version") != ECONOMIC_BACKPROJECTION_VERSION:
        reasons.append("economic_backprojection.contract_version.invalid")
    _validate_identity(backprojection.get("artifact_identity"), "economic_backprojection.artifact_identity", reasons)
    _validate_authority_guard(backprojection.get("authority_guard"), "economic_backprojection.authority_guard", reasons)
    _validate_artifact_authority(
        backprojection.get("artifact_authority"),
        "economic_backprojection.artifact_authority",
        reasons,
        workspace_root=workspace_root,
        known_artifacts=known,
        verify_refs=verify_refs,
        expected_class="economic_backprojection_hypothesis_advisory_only",
        expected_review_status="NOT_CANONICAL_PENDING_INDEPENDENT_REVIEW",
    )
    _validate_ref(
        backprojection.get("mechanism_delta_ref"),
        "economic_backprojection.mechanism_delta_ref",
        reasons,
        workspace_root=workspace_root,
        known_artifacts=known,
        verify_refs=verify_refs,
    )
    _safe_id(backprojection.get("delta_id"), "economic_backprojection.delta_id", reasons)

    mapping_fields = frozenset(
        {
            "mapping_id",
            "missing_term_id",
            "actor",
            "receiver",
            "payer",
            "binding_constraint",
            "action",
            "payoff_or_profit_transfer_equation",
            "persistence_mechanism",
            "capacity_boundary",
            "disappearance_condition",
            "observable_proxy",
            "proxy_information_time",
            "counterfactual",
            "no_story_without_proxy",
        }
    )
    mapping = _exact_object(
        backprojection.get("economic_mapping"),
        mapping_fields,
        "economic_backprojection.economic_mapping",
        reasons,
    )
    if mapping is not None:
        _safe_id(mapping.get("mapping_id"), "economic_backprojection.economic_mapping.mapping_id", reasons)
        _safe_id(mapping.get("missing_term_id"), "economic_backprojection.economic_mapping.missing_term_id", reasons)
        for field in mapping_fields - {"mapping_id", "missing_term_id", "no_story_without_proxy"}:
            _nonempty_string(mapping.get(field), f"economic_backprojection.economic_mapping.{field}", reasons)
        _exact_bool(
            mapping.get("no_story_without_proxy"),
            True,
            "economic_backprojection.economic_mapping.no_story_without_proxy",
            reasons,
        )

    explanation_fields = frozenset(
        {"explanation_id", "economic_mechanism", "payer", "distinguishing_test", "falsifier"}
    )
    explanations = _list(
        backprojection.get("competing_economic_explanations"),
        "economic_backprojection.competing_economic_explanations",
        reasons,
        minimum=2,
    )
    explanation_ids: set[str] = set()
    if explanations is not None:
        for index, item in enumerate(explanations):
            prefix = f"economic_backprojection.competing_economic_explanations[{index}]"
            explanation = _exact_object(item, explanation_fields, prefix, reasons)
            if explanation is None:
                continue
            explanation_id = _safe_id(explanation.get("explanation_id"), f"{prefix}.explanation_id", reasons)
            if explanation_id:
                if explanation_id in explanation_ids:
                    reasons.append(f"{prefix}.explanation_id.duplicate")
                explanation_ids.add(explanation_id)
            for field in explanation_fields - {"explanation_id"}:
                _nonempty_string(explanation.get(field), f"{prefix}.{field}", reasons)

    signature_fields = frozenset(
        {
            "signature_id",
            "mechanism_prediction_id",
            "economic_signature",
            "observable_proxy",
            "discriminating_test",
            "falsifier",
            "unique_against_explanation_ids",
        }
    )
    signatures = _list(
        backprojection.get("predicted_economic_signatures"),
        "economic_backprojection.predicted_economic_signatures",
        reasons,
        minimum=1,
    )
    mechanism_prediction_ids: set[str] = set()
    if mechanism_delta is not None:
        mechanism_prediction_ids = {
            str(item.get("prediction_id"))
            for item in mechanism_delta.get("distinctive_predictions") or []
            if isinstance(item, dict)
        }
    if signatures is not None:
        for index, item in enumerate(signatures):
            prefix = f"economic_backprojection.predicted_economic_signatures[{index}]"
            signature = _exact_object(item, signature_fields, prefix, reasons)
            if signature is None:
                continue
            _safe_id(signature.get("signature_id"), f"{prefix}.signature_id", reasons)
            prediction_id = _safe_id(signature.get("mechanism_prediction_id"), f"{prefix}.mechanism_prediction_id", reasons)
            if mechanism_delta is not None and prediction_id not in mechanism_prediction_ids:
                reasons.append(f"{prefix}.mechanism_prediction_id.unbound")
            for field in ("economic_signature", "observable_proxy", "discriminating_test", "falsifier"):
                _nonempty_string(signature.get(field), f"{prefix}.{field}", reasons)
            unique_ids = _string_list(
                signature.get("unique_against_explanation_ids"),
                f"{prefix}.unique_against_explanation_ids",
                reasons,
                minimum=1,
            )
            if unique_ids is not None and not set(unique_ids) <= explanation_ids:
                reasons.append(f"{prefix}.unique_against_explanation_ids.unbound")

    qualification_fields = frozenset(
        {"claim_level", "payer_validated", "current_factor_proof", "branch_authority"}
    )
    qualification = _exact_object(
        backprojection.get("qualification"),
        qualification_fields,
        "economic_backprojection.qualification",
        reasons,
    )
    if qualification is not None:
        if qualification.get("claim_level") != "HYPOTHESIS_ONLY_UNTIL_VALIDATED":
            reasons.append("economic_backprojection.qualification.claim_level.invalid")
        for field in qualification_fields - {"claim_level"}:
            _exact_bool(
                qualification.get(field),
                False,
                f"economic_backprojection.qualification.{field}",
                reasons,
            )
    if backprojection.get("status") != "CAUSAL_MAPPING_REVIEW_ONLY":
        reasons.append("economic_backprojection.status.invalid")
    _validate_oos_control(backprojection.get("oos_control"), "economic_backprojection.oos_control", reasons)
    if mechanism_delta is not None:
        extension = mechanism_delta.get("minimal_extension")
        expected_delta_id = extension.get("delta_id") if isinstance(extension, dict) else None
        if backprojection.get("delta_id") != expected_delta_id:
            reasons.append("economic_backprojection.delta_id.mechanism_delta_mismatch")
    _validate_content_hash(backprojection, "economic_backprojection", reasons)
    return list(dict.fromkeys(reasons))


def _validate_review_authority(
    value: Any,
    path: str,
    reasons: list[str],
    *,
    layer: str,
    workspace_root: Path | None,
    known_artifacts: Mapping[str, Mapping[str, Any]],
    verify_refs: bool,
) -> None:
    fields = frozenset({"required", "status", "independent_session", "reviewer_receipt_ref"})
    authority = _exact_object(value, fields, path, reasons)
    if authority is None:
        return
    if layer in {"structural_lesson", "conditional_realization"}:
        _exact_bool(authority.get("required"), True, f"{path}.required", reasons)
        if authority.get("status") != "APPROVE_CANONICAL":
            reasons.append(f"{path}.status.independent_approval_required")
        _exact_bool(
            authority.get("independent_session"),
            True,
            f"{path}.independent_session",
            reasons,
        )
        _validate_ref(
            authority.get("reviewer_receipt_ref"),
            f"{path}.reviewer_receipt_ref",
            reasons,
            workspace_root=workspace_root,
            known_artifacts=known_artifacts,
            verify_refs=verify_refs,
        )
    else:
        _exact_bool(authority.get("required"), False, f"{path}.required", reasons)
        if authority.get("status") != "HOST_SIGNED_EPISODE_NO_STRUCTURAL_AUTHORITY":
            reasons.append(f"{path}.status.episode_authority_invalid")
        _exact_bool(
            authority.get("independent_session"),
            False,
            f"{path}.independent_session",
            reasons,
        )
        if authority.get("reviewer_receipt_ref") is not None:
            reasons.append(f"{path}.reviewer_receipt_ref.must_be_null")


def _validate_experience_lesson(
    value: Any,
    path: str,
    reasons: list[str],
    *,
    layer: str,
) -> None:
    if layer == "structural_lesson":
        fields = frozenset(
            {
                "mechanism_pattern",
                "payer_or_constraint",
                "estimand",
                "mathematical_object",
                "invariant_or_boundary",
                "observation_mapping",
                "expected_signature",
                "falsifier",
                "counterexample",
                "reuse_boundary",
                "historical_context",
            }
        )
        lesson = _exact_object(value, fields, path, reasons)
        if lesson is not None:
            for field in fields:
                _nonempty_string(lesson.get(field), f"{path}.{field}", reasons)
        return
    if layer == "conditional_realization":
        fields = frozenset(
            {
                "structural_lesson_id",
                "condition_kind",
                "causal_condition",
                "measurable_diagnostic",
                "expected_interaction_signature",
                "enabling_or_suppressing",
                "condition_falsifier",
                "reuse_boundary",
                "historical_context",
            }
        )
        lesson = _exact_object(value, fields, path, reasons)
        if lesson is not None:
            _safe_id(lesson.get("structural_lesson_id"), f"{path}.structural_lesson_id", reasons)
            for field in fields - {"structural_lesson_id"}:
                _nonempty_string(lesson.get(field), f"{path}.{field}", reasons)
            if lesson.get("enabling_or_suppressing") not in {"enabling", "suppressing", "challenging"}:
                reasons.append(f"{path}.enabling_or_suppressing.invalid")
        return
    fields = frozenset(
        {
            "window",
            "assets",
            "institutional_rules",
            "participant_structure",
            "event_timeline",
            "state_variables",
            "predicted_vs_observed",
            "layered_verdict",
            "causal_role",
        }
    )
    lesson = _exact_object(value, fields, path, reasons)
    if lesson is not None:
        for field in (
            "window",
            "assets",
            "institutional_rules",
            "participant_structure",
            "predicted_vs_observed",
            "layered_verdict",
        ):
            _nonempty_string(lesson.get(field), f"{path}.{field}", reasons)
        _string_list(lesson.get("event_timeline"), f"{path}.event_timeline", reasons, minimum=1)
        _string_list(lesson.get("state_variables"), f"{path}.state_variables", reasons, minimum=1)
        if lesson.get("causal_role") not in {
            "enabler",
            "suppressor",
            "confounder",
            "challenger",
            "unknown_not_used_for_routing",
        }:
            reasons.append(f"{path}.causal_role.invalid")


def validate_experience_transfer_bundle(
    payload: Any,
    *,
    mechanism_delta: Mapping[str, Any] | None = None,
    economic_backprojection: Mapping[str, Any] | None = None,
    workspace_root: Path | None = None,
    known_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
    verify_refs: bool = True,
) -> list[str]:
    reasons: list[str] = []
    fields = frozenset(
        {
            "contract_version",
            "artifact_identity",
            "authority_guard",
            "artifact_authority",
            "mechanism_delta_ref",
            "economic_backprojection_ref",
            "retrieval_policy",
            "mechanism_fingerprint",
            "experiences",
            "transfer_mappings",
            "status",
            "content_sha256",
        }
    )
    bundle = _exact_object(payload, fields, "experience_transfer_bundle", reasons)
    if bundle is None:
        return reasons
    known = known_artifacts or {}
    if bundle.get("contract_version") != EXPERIENCE_TRANSFER_BUNDLE_VERSION:
        reasons.append("experience_transfer_bundle.contract_version.invalid")
    _validate_identity(bundle.get("artifact_identity"), "experience_transfer_bundle.artifact_identity", reasons)
    _validate_authority_guard(bundle.get("authority_guard"), "experience_transfer_bundle.authority_guard", reasons)
    raw_retrieval = bundle.get("retrieval_policy")
    memory_state = (
        raw_retrieval.get("memory_state")
        if isinstance(raw_retrieval, dict)
        else None
    )
    expected_source_review = (
        "RETRIEVAL_PROVENANCE_VERIFIED_NO_SOURCE"
        if memory_state == "COLD_START_NO_ADMISSIBLE_MEMORY"
        else "SOURCE_AUTHORITY_VERIFIED"
    )
    _validate_artifact_authority(
        bundle.get("artifact_authority"),
        "experience_transfer_bundle.artifact_authority",
        reasons,
        workspace_root=workspace_root,
        known_artifacts=known,
        verify_refs=verify_refs,
        expected_class="mechanism_first_advisory_transfer_only",
        expected_review_status=expected_source_review,
    )
    for field in ("mechanism_delta_ref", "economic_backprojection_ref"):
        _validate_ref(
            bundle.get(field),
            f"experience_transfer_bundle.{field}",
            reasons,
            workspace_root=workspace_root,
            known_artifacts=known,
            verify_refs=verify_refs,
        )

    retrieval_fields = frozenset(
        {
            "query_mode",
            "blind_derivation_completed",
            "primary_retrieval_key",
            "retrieval_lanes",
            "market_regime_role",
            "regime_shortcut_allowed",
            "historical_score_used_for_ranking",
            "current_factor_proof_authority",
            "memory_state",
            "cold_start_reason",
            "retrieval_evidence_refs",
        }
    )
    retrieval = _exact_object(
        bundle.get("retrieval_policy"),
        retrieval_fields,
        "experience_transfer_bundle.retrieval_policy",
        reasons,
    )
    if retrieval is not None:
        exact_values = {
            "query_mode": "MECHANISM_FIRST_AFTER_BLIND_DERIVATION",
            "primary_retrieval_key": "mechanism_fingerprint",
            "market_regime_role": "historical_context_or_preregistered_boundary_only",
        }
        for field, expected in exact_values.items():
            if retrieval.get(field) != expected:
                reasons.append(f"experience_transfer_bundle.retrieval_policy.{field}.invalid")
        if retrieval.get("retrieval_lanes") != [
            "structural_isomorph",
            "cross_math_analogy",
            "near_miss_failure",
            "direct_counterexample",
            "historical_episode_context",
        ]:
            reasons.append("experience_transfer_bundle.retrieval_policy.retrieval_lanes.invalid")
        _exact_bool(
            retrieval.get("blind_derivation_completed"),
            True,
            "experience_transfer_bundle.retrieval_policy.blind_derivation_completed",
            reasons,
        )
        for field in (
            "regime_shortcut_allowed",
            "historical_score_used_for_ranking",
            "current_factor_proof_authority",
        ):
            _exact_bool(
                retrieval.get(field),
                False,
                f"experience_transfer_bundle.retrieval_policy.{field}",
                reasons,
            )
        if retrieval.get("memory_state") not in {
            "ADMISSIBLE_MEMORY_FOUND",
            "COLD_START_NO_ADMISSIBLE_MEMORY",
        }:
            reasons.append(
                "experience_transfer_bundle.retrieval_policy.memory_state.invalid"
            )
        if retrieval.get("memory_state") == "COLD_START_NO_ADMISSIBLE_MEMORY":
            _nonempty_string(
                retrieval.get("cold_start_reason"),
                "experience_transfer_bundle.retrieval_policy.cold_start_reason",
                reasons,
            )
        elif retrieval.get("cold_start_reason") is not None:
            reasons.append(
                "experience_transfer_bundle.retrieval_policy.cold_start_reason.must_be_null_when_found"
            )
        _validate_refs(
            retrieval.get("retrieval_evidence_refs"),
            "experience_transfer_bundle.retrieval_policy.retrieval_evidence_refs",
            reasons,
            workspace_root=workspace_root,
            known_artifacts=known,
            verify_refs=verify_refs,
            minimum=1,
        )

    fingerprint_fields = frozenset(
        {
            "economic_claim",
            "estimand_id",
            "payer_or_constraint",
            "mathematical_object",
            "broken_invariant_or_boundary",
            "observation_mapping",
            "failure_signature",
        }
    )
    fingerprint = _exact_object(
        bundle.get("mechanism_fingerprint"),
        fingerprint_fields,
        "experience_transfer_bundle.mechanism_fingerprint",
        reasons,
    )
    if fingerprint is not None:
        _safe_id(fingerprint.get("estimand_id"), "experience_transfer_bundle.mechanism_fingerprint.estimand_id", reasons)
        for field in fingerprint_fields - {"estimand_id"}:
            _nonempty_string(fingerprint.get(field), f"experience_transfer_bundle.mechanism_fingerprint.{field}", reasons)

    _validate_retrieval_evidence_semantics(
        retrieval.get("retrieval_evidence_refs") if retrieval is not None else None,
        memory_state=memory_state,
        mechanism_fingerprint=fingerprint,
        workspace_root=workspace_root,
        known_artifacts=known,
        verify_refs=verify_refs,
        reasons=reasons,
    )

    experience_fields = frozenset(
        {
            "experience_id",
            "layer",
            "source_ref",
            "source_factor_id",
            "source_report_id",
            "source_outcome",
            "host_admission_ref",
            "review_authority",
            "lesson",
        }
    )
    cold_start = memory_state == "COLD_START_NO_ADMISSIBLE_MEMORY"
    experiences = _list(
        bundle.get("experiences"),
        "experience_transfer_bundle.experiences",
        reasons,
        minimum=0 if cold_start else 3,
    )
    experience_by_id: dict[str, str] = {}
    if experiences is not None:
        observed_layers: set[str] = set()
        for index, item in enumerate(experiences):
            prefix = f"experience_transfer_bundle.experiences[{index}]"
            experience = _exact_object(item, experience_fields, prefix, reasons)
            if experience is None:
                continue
            experience_id = _safe_id(experience.get("experience_id"), f"{prefix}.experience_id", reasons)
            layer = experience.get("layer")
            if layer not in EXPERIENCE_LAYERS:
                reasons.append(f"{prefix}.layer.invalid")
                continue
            observed_layers.add(layer)
            if experience_id:
                if experience_id in experience_by_id:
                    reasons.append(f"{prefix}.experience_id.duplicate")
                experience_by_id[experience_id] = layer
            for field in ("source_factor_id", "source_report_id"):
                _safe_id(experience.get(field), f"{prefix}.{field}", reasons)
            if experience.get("source_outcome") not in {"ACCEPT", "REJECT"}:
                reasons.append(f"{prefix}.source_outcome.invalid")
            for field in ("source_ref", "host_admission_ref"):
                _validate_ref(
                    experience.get(field),
                    f"{prefix}.{field}",
                    reasons,
                    workspace_root=workspace_root,
                    known_artifacts=known,
                    verify_refs=verify_refs,
                )
            _validate_review_authority(
                experience.get("review_authority"),
                f"{prefix}.review_authority",
                reasons,
                layer=layer,
                workspace_root=workspace_root,
                known_artifacts=known,
                verify_refs=verify_refs,
            )
            _validate_experience_lesson(experience.get("lesson"), f"{prefix}.lesson", reasons, layer=layer)
        if not cold_start and observed_layers != EXPERIENCE_LAYERS:
            reasons.append("experience_transfer_bundle.experiences.all_three_layers_required")
        if cold_start and experiences:
            reasons.append(
                "experience_transfer_bundle.experiences.must_be_empty_for_cold_start"
            )

    mapping_fields = frozenset(
        {
            "mapping_id",
            "source_experience_id",
            "source_layer",
            "target_delta_id",
            "source_to_target",
            "preserved_invariants",
            "broken_assumptions",
            "boundary_review",
            "transferred_prediction",
            "distinguishing_test",
            "disposition",
            "use_limit",
            "performance_score_used_for_ranking",
            "regime_match_required",
            "current_factor_evidence",
        }
    )
    source_to_target_fields = frozenset(
        {"payer_or_constraint", "estimand", "mathematical_object", "invariant_or_boundary", "observation_mapping"}
    )
    mappings = _list(
        bundle.get("transfer_mappings"),
        "experience_transfer_bundle.transfer_mappings",
        reasons,
        minimum=0 if cold_start else 3,
    )
    mapping_ids: set[str] = set()
    mapped_experience_ids: set[str] = set()
    target_delta_id = None
    if mechanism_delta is not None and isinstance(mechanism_delta.get("minimal_extension"), dict):
        target_delta_id = mechanism_delta["minimal_extension"].get("delta_id")
    if mappings is not None:
        for index, item in enumerate(mappings):
            prefix = f"experience_transfer_bundle.transfer_mappings[{index}]"
            mapping = _exact_object(item, mapping_fields, prefix, reasons)
            if mapping is None:
                continue
            mapping_id = _safe_id(mapping.get("mapping_id"), f"{prefix}.mapping_id", reasons)
            if mapping_id:
                if mapping_id in mapping_ids:
                    reasons.append(f"{prefix}.mapping_id.duplicate")
                mapping_ids.add(mapping_id)
            experience_id = _safe_id(mapping.get("source_experience_id"), f"{prefix}.source_experience_id", reasons)
            if experience_id:
                mapped_experience_ids.add(experience_id)
            source_layer = mapping.get("source_layer")
            if source_layer not in EXPERIENCE_LAYERS:
                reasons.append(f"{prefix}.source_layer.invalid")
            if experience_id and experience_by_id.get(experience_id) != source_layer:
                reasons.append(f"{prefix}.source_layer.source_mismatch")
            _safe_id(mapping.get("target_delta_id"), f"{prefix}.target_delta_id", reasons)
            if target_delta_id is not None and mapping.get("target_delta_id") != target_delta_id:
                reasons.append(f"{prefix}.target_delta_id.mismatch")
            source_to_target = _exact_object(
                mapping.get("source_to_target"),
                source_to_target_fields,
                f"{prefix}.source_to_target",
                reasons,
            )
            if source_to_target is not None:
                for field in source_to_target_fields:
                    _nonempty_string(source_to_target.get(field), f"{prefix}.source_to_target.{field}", reasons)
            _string_list(mapping.get("preserved_invariants"), f"{prefix}.preserved_invariants", reasons, minimum=1)
            _string_list(mapping.get("broken_assumptions"), f"{prefix}.broken_assumptions", reasons, minimum=0)
            for field in ("boundary_review", "transferred_prediction", "distinguishing_test", "use_limit"):
                _nonempty_string(mapping.get(field), f"{prefix}.{field}", reasons)
            disposition = mapping.get("disposition")
            if disposition not in {"adopted_for_test_only", "challenge_only", "context_only", "mapping_rejected"}:
                reasons.append(f"{prefix}.disposition.invalid")
            if source_layer == "historical_episode" and disposition not in {
                "challenge_only",
                "context_only",
                "mapping_rejected",
            }:
                reasons.append(f"{prefix}.historical_episode.cannot_authorize_adoption")
            for field in (
                "performance_score_used_for_ranking",
                "regime_match_required",
                "current_factor_evidence",
            ):
                _exact_bool(mapping.get(field), False, f"{prefix}.{field}", reasons)
        if set(experience_by_id) != mapped_experience_ids:
            reasons.append("experience_transfer_bundle.transfer_mappings.every_experience_must_be_disposed")
        if cold_start and mappings:
            reasons.append(
                "experience_transfer_bundle.transfer_mappings.must_be_empty_for_cold_start"
            )

    expected_status = (
        "COLD_START_RECORDED_NO_TRANSFER"
        if cold_start
        else "ADVISORY_TRANSFER_REVIEWED"
    )
    if bundle.get("status") != expected_status:
        reasons.append("experience_transfer_bundle.status.invalid")
    if mechanism_delta is not None and fingerprint is not None:
        baseline = mechanism_delta.get("baseline_model")
        extension = mechanism_delta.get("minimal_extension")
        if isinstance(baseline, dict):
            if fingerprint.get("estimand_id") != baseline.get("estimand_id"):
                reasons.append("experience_transfer_bundle.mechanism_fingerprint.estimand_mismatch")
            if fingerprint.get("mathematical_object") != baseline.get("mathematical_object"):
                reasons.append("experience_transfer_bundle.mechanism_fingerprint.mathematical_object_mismatch")
            if fingerprint.get("observation_mapping") != baseline.get("observation_mapping"):
                reasons.append("experience_transfer_bundle.mechanism_fingerprint.observation_mapping_mismatch")
        if isinstance(extension, dict) and fingerprint.get("broken_invariant_or_boundary") != extension.get("broken_invariant_or_boundary"):
            reasons.append("experience_transfer_bundle.mechanism_fingerprint.boundary_mismatch")
    if economic_backprojection is not None and fingerprint is not None:
        mapping = economic_backprojection.get("economic_mapping")
        if isinstance(mapping, dict):
            payer_constraint = f"{mapping.get('payer')} | {mapping.get('binding_constraint')}"
            if fingerprint.get("payer_or_constraint") != payer_constraint:
                reasons.append("experience_transfer_bundle.mechanism_fingerprint.payer_constraint_mismatch")
    _validate_content_hash(bundle, "experience_transfer_bundle", reasons)
    return list(dict.fromkeys(reasons))


def validate_transfer_use_receipt(
    payload: Any,
    *,
    transfer_bundle: Mapping[str, Any] | None = None,
    mechanism_delta: Mapping[str, Any] | None = None,
    workspace_root: Path | None = None,
    known_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
    verify_refs: bool = True,
) -> list[str]:
    reasons: list[str] = []
    fields = frozenset(
        {
            "contract_version",
            "artifact_identity",
            "authority_guard",
            "artifact_authority",
            "transfer_bundle_ref",
            "mechanism_delta_ref",
            "receipt_id",
            "transfer_mode",
            "host_action",
            "reviewer_action",
            "uses",
            "outcome_recording",
            "status",
            "content_sha256",
        }
    )
    receipt = _exact_object(payload, fields, "transfer_use_receipt", reasons)
    if receipt is None:
        return reasons
    known = known_artifacts or {}
    if receipt.get("contract_version") != TRANSFER_USE_RECEIPT_VERSION:
        reasons.append("transfer_use_receipt.contract_version.invalid")
    _validate_identity(receipt.get("artifact_identity"), "transfer_use_receipt.artifact_identity", reasons)
    _validate_authority_guard(receipt.get("authority_guard"), "transfer_use_receipt.authority_guard", reasons)
    transfer_mode = receipt.get("transfer_mode")
    if transfer_mode not in {"MAPPINGS_USED", "COLD_START_NO_TRANSFER"}:
        reasons.append("transfer_use_receipt.transfer_mode.invalid")
    cold_start = transfer_mode == "COLD_START_NO_TRANSFER"
    _validate_artifact_authority(
        receipt.get("artifact_authority"),
        "transfer_use_receipt.artifact_authority",
        reasons,
        workspace_root=workspace_root,
        known_artifacts=known,
        verify_refs=verify_refs,
        expected_class="host_recorded_advisory_use_no_factor_authority",
        expected_review_status=(
            "NOT_REQUIRED_VERIFIED_COLD_START"
            if cold_start
            else "INDEPENDENT_REVIEW_APPROVED"
        ),
    )
    for field in ("transfer_bundle_ref", "mechanism_delta_ref"):
        _validate_ref(
            receipt.get(field),
            f"transfer_use_receipt.{field}",
            reasons,
            workspace_root=workspace_root,
            known_artifacts=known,
            verify_refs=verify_refs,
        )
    _safe_id(receipt.get("receipt_id"), "transfer_use_receipt.receipt_id", reasons)

    host_fields = frozenset({"actor_role", "action", "host_receipt_ref"})
    host = _exact_object(receipt.get("host_action"), host_fields, "transfer_use_receipt.host_action", reasons)
    if host is not None:
        if host.get("actor_role") != "Host Research Director":
            reasons.append("transfer_use_receipt.host_action.actor_role.invalid")
        expected_host_action = (
            "RECORDED_COLD_START_NO_TRANSFER"
            if cold_start
            else "RECORDED_ADVISORY_USE"
        )
        if host.get("action") != expected_host_action:
            reasons.append("transfer_use_receipt.host_action.action.invalid")
        _validate_ref(
            host.get("host_receipt_ref"),
            "transfer_use_receipt.host_action.host_receipt_ref",
            reasons,
            workspace_root=workspace_root,
            known_artifacts=known,
            verify_refs=verify_refs,
        )

    reviewer_fields = frozenset({"decision", "independent_session", "reviewer_receipt_ref"})
    reviewer = _exact_object(
        receipt.get("reviewer_action"),
        reviewer_fields,
        "transfer_use_receipt.reviewer_action",
        reasons,
    )
    if reviewer is not None:
        if cold_start:
            if reviewer.get("decision") != "NOT_REQUIRED_COLD_START":
                reasons.append("transfer_use_receipt.reviewer_action.decision.invalid")
            _exact_bool(
                reviewer.get("independent_session"),
                False,
                "transfer_use_receipt.reviewer_action.independent_session",
                reasons,
            )
            if reviewer.get("reviewer_receipt_ref") is not None:
                reasons.append(
                    "transfer_use_receipt.reviewer_action.reviewer_receipt_ref.must_be_null"
                )
        else:
            if reviewer.get("decision") != "APPROVE_ADVISORY_USE":
                reasons.append("transfer_use_receipt.reviewer_action.decision.invalid")
            _exact_bool(
                reviewer.get("independent_session"),
                True,
                "transfer_use_receipt.reviewer_action.independent_session",
                reasons,
            )
            _validate_ref(
                reviewer.get("reviewer_receipt_ref"),
                "transfer_use_receipt.reviewer_action.reviewer_receipt_ref",
                reasons,
                workspace_root=workspace_root,
                known_artifacts=known,
                verify_refs=verify_refs,
            )

    bundle_mappings: dict[str, Mapping[str, Any]] = {}
    if transfer_bundle is not None:
        bundle_mappings = {
            str(item.get("mapping_id")): item
            for item in transfer_bundle.get("transfer_mappings") or []
            if isinstance(item, dict)
        }
    use_fields = frozenset(
        {
            "mapping_id",
            "disposition",
            "research_effect",
            "generated_test_id",
            "preregistration_ref",
            "changed_research_question_or_test",
            "current_factor_evidence",
            "threshold_change",
            "estimand_change",
            "trial_budget_change",
            "oos_access",
            "skill_or_validator_change",
        }
    )
    uses = _list(
        receipt.get("uses"),
        "transfer_use_receipt.uses",
        reasons,
        minimum=0 if cold_start else 1,
    )
    used_mapping_ids: set[str] = set()
    if uses is not None:
        for index, item in enumerate(uses):
            prefix = f"transfer_use_receipt.uses[{index}]"
            use = _exact_object(item, use_fields, prefix, reasons)
            if use is None:
                continue
            mapping_id = _safe_id(use.get("mapping_id"), f"{prefix}.mapping_id", reasons)
            if mapping_id:
                if mapping_id in used_mapping_ids:
                    reasons.append(f"{prefix}.mapping_id.duplicate")
                used_mapping_ids.add(mapping_id)
            source_mapping = bundle_mappings.get(str(mapping_id))
            if transfer_bundle is not None and source_mapping is None:
                reasons.append(f"{prefix}.mapping_id.unbound")
            if source_mapping is not None and use.get("disposition") != source_mapping.get("disposition"):
                reasons.append(f"{prefix}.disposition.bundle_mismatch")
            if use.get("research_effect") not in {
                "test_order_changed",
                "question_broadened",
                "counterexample_added",
                "historical_context_recorded",
                "mapping_rejected",
            }:
                reasons.append(f"{prefix}.research_effect.invalid")
            _safe_id(use.get("generated_test_id"), f"{prefix}.generated_test_id", reasons)
            _validate_ref(
                use.get("preregistration_ref"),
                f"{prefix}.preregistration_ref",
                reasons,
                workspace_root=workspace_root,
                known_artifacts=known,
                verify_refs=verify_refs,
            )
            if use.get("disposition") == "mapping_rejected":
                _exact_bool(
                    use.get("changed_research_question_or_test"),
                    False,
                    f"{prefix}.changed_research_question_or_test",
                    reasons,
                )
            else:
                _exact_bool(
                    use.get("changed_research_question_or_test"),
                    True,
                    f"{prefix}.changed_research_question_or_test",
                    reasons,
                )
            for field in (
                "current_factor_evidence",
                "threshold_change",
                "estimand_change",
                "trial_budget_change",
                "oos_access",
                "skill_or_validator_change",
            ):
                _exact_bool(use.get(field), False, f"{prefix}.{field}", reasons)
        if transfer_bundle is not None and set(bundle_mappings) != used_mapping_ids:
            reasons.append("transfer_use_receipt.uses.every_mapping_requires_receipt")
        if cold_start and uses:
            reasons.append("transfer_use_receipt.uses.must_be_empty_for_cold_start")

    if transfer_bundle is not None:
        bundle_retrieval = transfer_bundle.get("retrieval_policy")
        bundle_memory_state = (
            bundle_retrieval.get("memory_state")
            if isinstance(bundle_retrieval, dict)
            else None
        )
        expected_mode = (
            "COLD_START_NO_TRANSFER"
            if bundle_memory_state == "COLD_START_NO_ADMISSIBLE_MEMORY"
            else "MAPPINGS_USED"
        )
        if transfer_mode != expected_mode:
            reasons.append("transfer_use_receipt.transfer_mode.bundle_mismatch")

    outcome_fields = frozenset(
        {"status", "factor_verdict", "promotion_authority", "canonical_memory_write"}
    )
    outcome = _exact_object(
        receipt.get("outcome_recording"),
        outcome_fields,
        "transfer_use_receipt.outcome_recording",
        reasons,
    )
    if outcome is not None:
        if outcome.get("status") != "CURRENT_FACTOR_OUTCOME_NOT_INFERRED":
            reasons.append("transfer_use_receipt.outcome_recording.status.invalid")
        if outcome.get("factor_verdict") != "NOT_ISSUED":
            reasons.append("transfer_use_receipt.outcome_recording.factor_verdict.invalid")
        for field in ("promotion_authority", "canonical_memory_write"):
            _exact_bool(
                outcome.get(field),
                False,
                f"transfer_use_receipt.outcome_recording.{field}",
                reasons,
            )
    expected_status = (
        "HOST_RECORDED_COLD_START_NO_TRANSFER"
        if cold_start
        else "HOST_RECORDED_REVIEWED_ADVISORY_USE"
    )
    if receipt.get("status") != expected_status:
        reasons.append("transfer_use_receipt.status.invalid")
    _validate_content_hash(receipt, "transfer_use_receipt", reasons)
    return list(dict.fromkeys(reasons))


def _same_identity(
    artifacts: Mapping[str, Mapping[str, Any]],
    reasons: list[str],
) -> dict[str, Any] | None:
    identities = {
        name: payload.get("artifact_identity")
        for name, payload in artifacts.items()
        if isinstance(payload, Mapping)
    }
    reference = identities.get("feedback_ledger")
    if not isinstance(reference, dict):
        return None
    for name, identity in identities.items():
        if identity != reference:
            reasons.append(f"bundle.artifact_identity_mismatch:{name}")
    return reference


def validate_evo_v2_bundle(
    artifacts: Mapping[str, Any],
    *,
    workspace_root: Path,
    report_id: str,
    verify_refs: bool = True,
) -> list[str]:
    reasons: list[str] = []
    unexpected = sorted(set(artifacts) - set(ARTIFACT_FILENAMES))
    missing = sorted(set(ARTIFACT_FILENAMES) - set(artifacts))
    if unexpected:
        reasons.append("bundle.unexpected_artifacts:" + ",".join(unexpected))
    if missing:
        reasons.append("bundle.missing_artifacts:" + ",".join(missing))
    if unexpected or missing:
        return reasons
    typed_artifacts: dict[str, Mapping[str, Any]] = {}
    for name, payload in artifacts.items():
        if not isinstance(payload, dict):
            reasons.append(f"bundle.{name}.object_required")
        else:
            typed_artifacts[name] = payload
    if len(typed_artifacts) != len(ARTIFACT_FILENAMES):
        return reasons
    identity = _same_identity(typed_artifacts, reasons)
    if identity is not None and identity.get("report_id") != report_id:
        reasons.append("bundle.report_id.identity_mismatch")
    expected_relatives = evo_v2_relative_paths(report_id)
    known_artifacts = {
        expected_relatives[name]: typed_artifacts[name]
        for name in ARTIFACT_FILENAMES
    }

    reasons.extend(
        validate_feedback_ledger(
            typed_artifacts["feedback_ledger"],
            workspace_root=workspace_root,
            known_artifacts=known_artifacts,
            verify_refs=verify_refs,
        )
    )
    reasons.extend(
        validate_mechanism_delta(
            typed_artifacts["mechanism_delta"],
            feedback_ledger=typed_artifacts["feedback_ledger"],
            workspace_root=workspace_root,
            known_artifacts=known_artifacts,
            verify_refs=verify_refs,
        )
    )
    reasons.extend(
        validate_economic_backprojection(
            typed_artifacts["economic_backprojection"],
            mechanism_delta=typed_artifacts["mechanism_delta"],
            workspace_root=workspace_root,
            known_artifacts=known_artifacts,
            verify_refs=verify_refs,
        )
    )
    reasons.extend(
        validate_experience_transfer_bundle(
            typed_artifacts["experience_transfer_bundle"],
            mechanism_delta=typed_artifacts["mechanism_delta"],
            economic_backprojection=typed_artifacts["economic_backprojection"],
            workspace_root=workspace_root,
            known_artifacts=known_artifacts,
            verify_refs=verify_refs,
        )
    )
    reasons.extend(
        validate_transfer_use_receipt(
            typed_artifacts["transfer_use_receipt"],
            transfer_bundle=typed_artifacts["experience_transfer_bundle"],
            mechanism_delta=typed_artifacts["mechanism_delta"],
            workspace_root=workspace_root,
            known_artifacts=known_artifacts,
            verify_refs=verify_refs,
        )
    )

    expected_refs = {
        ("mechanism_delta", "feedback_ref"): "feedback_ledger",
        ("economic_backprojection", "mechanism_delta_ref"): "mechanism_delta",
        ("experience_transfer_bundle", "mechanism_delta_ref"): "mechanism_delta",
        ("experience_transfer_bundle", "economic_backprojection_ref"): "economic_backprojection",
        ("transfer_use_receipt", "transfer_bundle_ref"): "experience_transfer_bundle",
        ("transfer_use_receipt", "mechanism_delta_ref"): "mechanism_delta",
    }
    for (artifact_name, field), target_name in expected_refs.items():
        ref = typed_artifacts[artifact_name].get(field)
        expected_path = expected_relatives[target_name]
        if not isinstance(ref, dict) or ref.get("path") != expected_path:
            reasons.append(f"bundle.{artifact_name}.{field}.canonical_path_required")
        elif ref.get("sha256") != artifact_sha256(typed_artifacts[target_name]):
            reasons.append(f"bundle.{artifact_name}.{field}.canonical_hash_required")
    return list(dict.fromkeys(reasons))


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, [f"json_load_failed:{path}:{type(exc).__name__}"]) from exc
    if not isinstance(value, dict):
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, [f"json_object_required:{path}"])
    return value


def load_materialized_evo_v2(
    workspace_root: Path,
    report_id: str,
) -> dict[str, dict[str, Any]]:
    paths = evo_v2_paths(workspace_root, report_id)
    artifacts: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    for name, path in paths.items():
        if not path.is_file():
            reasons.append(f"materialized.{name}.missing")
            continue
        try:
            artifacts[name] = load_json_object(path)
        except EvoV2Error as exc:
            reasons.extend(exc.reasons)
    if reasons:
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, reasons)
    return artifacts


def validate_materialized_evo_v2(
    workspace_root: Path,
    report_id: str,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    try:
        artifacts = load_materialized_evo_v2(workspace_root, report_id)
    except EvoV2Error as exc:
        return {}, list(exc.reasons)
    reasons = validate_evo_v2_bundle(
        artifacts,
        workspace_root=workspace_root,
        report_id=report_id,
        verify_refs=True,
    )
    paths = evo_v2_paths(workspace_root, report_id)
    for name, path in paths.items():
        if path.is_file() and path.read_bytes() != canonical_json_bytes(artifacts[name]):
            reasons.append(f"materialized.{name}.noncanonical_json_bytes")
    return artifacts, list(dict.fromkeys(reasons))


def materialize_evo_v2_bundle(
    artifacts: Mapping[str, Any],
    *,
    workspace_root: Path,
    report_id: str,
) -> dict[str, Path]:
    root = workspace_root.resolve(strict=True)
    reasons = validate_evo_v2_bundle(
        artifacts,
        workspace_root=root,
        report_id=report_id,
        verify_refs=True,
    )
    if reasons:
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, reasons)
    paths = evo_v2_paths(root, report_id)
    payload_bytes = {
        name: canonical_json_bytes(artifacts[name])
        for name in ARTIFACT_FILENAMES
    }
    conflicts = [
        f"materialized.{name}.different_content_exists"
        for name, path in paths.items()
        if path.exists() and (not path.is_file() or path.read_bytes() != payload_bytes[name])
    ]
    if conflicts:
        raise EvoV2Error(BLOCK_EVO_V2_MATERIALIZATION_CONFLICT, conflicts)
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.parent.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise EvoV2Error(
                BLOCK_EVO_V2_INVALID,
                [f"materialized.path_escape:{path}"],
            ) from exc
    staged: dict[str, Path] = {}
    try:
        for name, path in paths.items():
            if path.exists():
                continue
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
            )
            os.close(descriptor)
            temporary_path = Path(temporary)
            temporary_path.write_bytes(payload_bytes[name])
            staged[name] = temporary_path
        for name, temporary_path in staged.items():
            os.replace(temporary_path, paths[name])
        staged.clear()
    finally:
        for temporary_path in staged.values():
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    _, post_reasons = validate_materialized_evo_v2(root, report_id)
    if post_reasons:
        raise EvoV2Error(BLOCK_EVO_V2_INVALID, post_reasons)
    return paths
