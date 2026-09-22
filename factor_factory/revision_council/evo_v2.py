from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from factor_factory.evo_v2 import (
    ECONOMIC_BACKPROJECTION_VERSION,
    EvoV2Error,
    FEEDBACK_LEDGER_VERSION,
    MECHANISM_DELTA_VERSION,
    artifact_sha256,
    evo_v2_relative_paths,
    sha256_file,
    stable_json_hash,
    validate_economic_backprojection,
    validate_feedback_ledger,
    validate_mechanism_delta,
)


COUNCIL_EVO_V2_CONTRACT_VERSION = (
    "factorforge_revision_council_evo_v2_intake_v1"
)
NO_DERIVED_LAW_CONTRACT_VERSION = (
    "factorforge_revision_council_no_derived_law_v2"
)

BLOCK_MISSING = "BLOCK_COUNCIL_EVO_V2_MISSING"
BLOCK_CONTRACT = "BLOCK_COUNCIL_EVO_V2_CONTRACT_INVALID"
BLOCK_WORKSPACE = "BLOCK_COUNCIL_EVO_V2_WORKSPACE_REQUIRED"
BLOCK_CORE_REF = "BLOCK_COUNCIL_EVO_V2_CORE_ARTIFACT_REF_INVALID"
BLOCK_CORE = "BLOCK_COUNCIL_EVO_V2_CORE_ARTIFACT_INVALID"
BLOCK_INTAKE = "BLOCK_COUNCIL_EVO_V2_INTAKE_NOT_QUALIFIED"
BLOCK_AUTHORITY = "BLOCK_COUNCIL_EVO_V2_AUTHORITY_INVALID"
BLOCK_OUTCOME = "BLOCK_COUNCIL_EVO_V2_DERIVATION_OUTCOME_INVALID"
BLOCK_LAW_BINDING = "BLOCK_COUNCIL_EVO_V2_PROPOSAL_LAW_BINDING_INVALID"
BLOCK_NO_DERIVED = "BLOCK_COUNCIL_EVO_V2_NO_DERIVED_LAW_INVALID"
BLOCK_SHORTCUT = "BLOCK_COUNCIL_EVO_V2_FORBIDDEN_SHORTCUT"

_ENVELOPE_FIELDS = frozenset(
    {
        "contract_version",
        "intake_gate",
        "authority",
        "feedback_ledger",
        "derivation_outcome",
        "proposal_law_binding",
    }
)
_INTAKE_FIELDS = frozenset(
    {"contradiction_id", "source_state", "validity_quarantine"}
)
_QUARANTINE_FIELDS = frozenset(
    {"state", "status", "unresolved_blockers", "qualified_feedback_ref"}
)
_AUTHORITY_FIELDS = frozenset(
    {
        "mode",
        "human_approval_required",
        "human_approval_status",
        "execution_allowed",
        "canonical_write_allowed",
        "factor_verdict_authority",
        "selection_policy",
        "score_based_selection_allowed",
        "majority_vote_allowed",
        "regime_shortcut_allowed",
        "consumed_oos_reuse_allowed",
        "constitutional_mutation_allowed",
        "protected_surfaces",
    }
)
_PROTECTED_SURFACES = [
    "skill",
    "validator",
    "permissions",
    "thresholds",
    "oos_policy",
    "estimand",
    "trial_budget",
]
_OUTCOME_FIELDS = frozenset(
    {"outcome", "mechanism_delta", "economic_backprojection", "no_derived_law"}
)
_LAW_BINDING_FIELDS = frozenset({"law_index", "law_sha256", "delta_id"})
_NO_DERIVED_FIELDS = frozenset(
    {
        "contract_version",
        "contradiction_id",
        "attempted_derivations",
        "unresolved_proof_obligations",
        "additional_evidence_required",
        "status",
        "factor_verdict",
        "branch_execution_allowed",
        "human_approval_required",
    }
)
_NO_DERIVED_ATTEMPT_FIELDS = frozenset(
    {
        "operator_family",
        "assumption_or_boundary_tested",
        "attempted_minimal_extension",
        "baseline_recovery_test",
        "discriminating_prediction_test",
        "failure_reason",
    }
)

_FORBIDDEN_RANKING_KEYS = frozenset(
    {
        "score",
        "selection_score",
        "performance_score",
        "ranking_score",
        "vote",
        "votes",
        "vote_count",
        "majority_result",
    }
)
_FORBIDDEN_RANKING_KEY_MARKERS = (
    "score",
    "weighted_vote",
    "majority_vote",
    "majority_result",
    "vote_count",
)
_FORBIDDEN_TRUE_KEYS = frozenset(
    {
        "regime_only",
        "regime_match_required",
        "regime_shortcut",
        "consumed_oos_reused",
        "reuse_consumed_oos",
        "skill_mutation_allowed",
        "validator_mutation_allowed",
        "permission_mutation_allowed",
        "constitutional_mutation_allowed",
    }
)
_FORBIDDEN_TRUE_KEY_MARKERS = (
    "regime_only",
    "regime_shortcut",
    "regime_routing",
    "consumed_oos_reuse",
    "reuse_consumed_oos",
    "skill_mutation",
    "validator_mutation",
    "permission_mutation",
    "constitutional_mutation",
)


def proposal_law_sha256(law: Mapping[str, Any]) -> str:
    """Hash one existing Council law without creating another law contract."""

    return stable_json_hash(law)


def _dedupe(reasons: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(reason) for reason in reasons if str(reason)))


def _exact_object(
    value: Any,
    fields: frozenset[str],
    token: str,
    reasons: list[str],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        reasons.append(token)
        return None
    unexpected = sorted(set(value) - fields)
    missing = sorted(fields - set(value))
    if unexpected:
        reasons.append(token + ":unexpected_fields:" + ",".join(unexpected))
    if missing:
        reasons.append(token + ":missing_fields:" + ",".join(missing))
    return value


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_text_list(value: Any, *, minimum: int = 1) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= minimum
        and all(_nonempty_text(item) for item in value)
        and len(set(value)) == len(value)
    )


def _workspace_root(value: Path | str | None, reasons: list[str]) -> Path | None:
    if value is None:
        reasons.append(BLOCK_WORKSPACE)
        return None
    try:
        root = Path(value).resolve(strict=True)
    except (OSError, RuntimeError):
        reasons.append(BLOCK_WORKSPACE)
        return None
    if not root.is_dir():
        reasons.append(BLOCK_WORKSPACE)
        return None
    return root


def _normalized_relative_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        return None
    normalized = path.as_posix()
    if normalized != value or value.endswith("/"):
        return None
    return normalized


def _load_core_artifact(
    value: Any,
    *,
    name: str,
    workspace_root: Path | None,
    reasons: list[str],
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Load either an embedded canonical artifact or an exact path/hash ref."""

    if isinstance(value, dict) and set(value) == {"path", "sha256"}:
        relative = _normalized_relative_path(value.get("path"))
        digest = value.get("sha256")
        if relative is None or not isinstance(digest, str) or len(digest) != 64:
            reasons.append(f"{BLOCK_CORE_REF}:{name}")
            return None, None
        try:
            int(digest, 16)
        except ValueError:
            reasons.append(f"{BLOCK_CORE_REF}:{name}")
            return None, None
        if workspace_root is None:
            reasons.append(f"{BLOCK_CORE_REF}:{name}:workspace")
            return None, None
        candidate = workspace_root / relative
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(workspace_root)
        except (OSError, RuntimeError, ValueError):
            reasons.append(f"{BLOCK_CORE_REF}:{name}:readback")
            return None, None
        if candidate.is_symlink() or not resolved.is_file():
            reasons.append(f"{BLOCK_CORE_REF}:{name}:readback")
            return None, None
        if sha256_file(resolved) != digest:
            reasons.append(f"{BLOCK_CORE_REF}:{name}:sha256")
            return None, None
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            reasons.append(f"{BLOCK_CORE_REF}:{name}:json")
            return None, None
        if not isinstance(payload, dict):
            reasons.append(f"{BLOCK_CORE_REF}:{name}:object")
            return None, None
        return payload, {"path": relative, "sha256": digest}
    if isinstance(value, dict):
        return value, None
    reasons.append(f"{BLOCK_CORE_REF}:{name}:embedded_or_ref_required")
    return None, None


def _validate_intake_gate(
    value: Any,
    feedback: Mapping[str, Any] | None,
    reasons: list[str],
) -> None:
    gate = _exact_object(value, _INTAKE_FIELDS, BLOCK_INTAKE, reasons)
    if gate is None:
        return
    quarantine = _exact_object(
        gate.get("validity_quarantine"),
        _QUARANTINE_FIELDS,
        BLOCK_INTAKE + ":validity_quarantine",
        reasons,
    )
    if (
        gate.get("source_state") != "QUALIFIED_CONTRADICTION"
        or quarantine is None
        or quarantine.get("state") != "VALIDITY_QUARANTINE"
        or quarantine.get("status") != "CLEARED"
        or quarantine.get("unresolved_blockers") != []
    ):
        reasons.append(BLOCK_INTAKE)
    contradiction = feedback.get("contradiction") if feedback else None
    contradiction_id = (
        contradiction.get("contradiction_id")
        if isinstance(contradiction, Mapping)
        else None
    )
    if (
        not _nonempty_text(gate.get("contradiction_id"))
        or gate.get("contradiction_id") != contradiction_id
        or (feedback is not None and feedback.get("current_state") != gate.get("source_state"))
    ):
        reasons.append(BLOCK_INTAKE + ":feedback_mismatch")
    identity = feedback.get("artifact_identity") if feedback else None
    report_id = identity.get("report_id") if isinstance(identity, Mapping) else None
    try:
        expected_ref = (
            {
                "path": evo_v2_relative_paths(report_id)["feedback_ledger"],
                "sha256": artifact_sha256(feedback),
            }
            if isinstance(report_id, str) and feedback is not None
            else None
        )
    except (EvoV2Error, TypeError, ValueError, OverflowError):
        expected_ref = None
    if quarantine is not None and quarantine.get("qualified_feedback_ref") != expected_ref:
        reasons.append(BLOCK_INTAKE + ":qualified_feedback_ref")


def _validate_authority(value: Any, reasons: list[str]) -> None:
    authority = _exact_object(value, _AUTHORITY_FIELDS, BLOCK_AUTHORITY, reasons)
    if authority is None:
        return
    expected = {
        "mode": "review_only",
        "human_approval_required": True,
        "human_approval_status": "PENDING_EXTERNAL_HUMAN_APPROVAL",
        "execution_allowed": False,
        "canonical_write_allowed": False,
        "factor_verdict_authority": False,
        "selection_policy": "contradiction_resolution_and_model_discrimination_only",
        "score_based_selection_allowed": False,
        "majority_vote_allowed": False,
        "regime_shortcut_allowed": False,
        "consumed_oos_reuse_allowed": False,
        "constitutional_mutation_allowed": False,
        "protected_surfaces": _PROTECTED_SURFACES,
    }
    if authority != expected:
        reasons.append(BLOCK_AUTHORITY)


def _scan_forbidden_shortcuts(value: Any, path: str = "proposal") -> list[str]:
    reasons: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).strip().lower()
            item_path = f"{path}.{raw_key}"
            ranking_key = key in _FORBIDDEN_RANKING_KEYS or any(
                marker in key for marker in _FORBIDDEN_RANKING_KEY_MARKERS
            )
            if ranking_key and item is not False:
                reasons.append(f"{BLOCK_SHORTCUT}:{item_path}")
            if (
                key in _FORBIDDEN_TRUE_KEYS
                or any(marker in key for marker in _FORBIDDEN_TRUE_KEY_MARKERS)
            ) and item is True:
                reasons.append(f"{BLOCK_SHORTCUT}:{item_path}")
            reasons.extend(_scan_forbidden_shortcuts(item, item_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reasons.extend(_scan_forbidden_shortcuts(item, f"{path}[{index}]"))
    return reasons


def _validate_no_derived_law(
    value: Any,
    *,
    contradiction_id: Any,
    reasons: list[str],
) -> None:
    proof = _exact_object(value, _NO_DERIVED_FIELDS, BLOCK_NO_DERIVED, reasons)
    if proof is None:
        return
    if (
        proof.get("contract_version") != NO_DERIVED_LAW_CONTRACT_VERSION
        or proof.get("contradiction_id") != contradiction_id
        or proof.get("status") != "NO_DERIVED_LAW_REVIEW_ONLY"
        or proof.get("factor_verdict") != "NOT_ISSUED"
        or proof.get("branch_execution_allowed") is not False
        or proof.get("human_approval_required") is not True
        or not _nonempty_text_list(proof.get("unresolved_proof_obligations"))
        or not _nonempty_text_list(proof.get("additional_evidence_required"))
    ):
        reasons.append(BLOCK_NO_DERIVED)
    attempts = proof.get("attempted_derivations")
    if not isinstance(attempts, list) or len(attempts) < 2:
        reasons.append(BLOCK_NO_DERIVED + ":attempts")
        return
    families: set[str] = set()
    for index, raw_attempt in enumerate(attempts):
        attempt = _exact_object(
            raw_attempt,
            _NO_DERIVED_ATTEMPT_FIELDS,
            f"{BLOCK_NO_DERIVED}:attempt:{index}",
            reasons,
        )
        if attempt is None:
            continue
        if not all(_nonempty_text(attempt.get(field)) for field in _NO_DERIVED_ATTEMPT_FIELDS):
            reasons.append(f"{BLOCK_NO_DERIVED}:attempt:{index}")
        family = attempt.get("operator_family")
        if isinstance(family, str):
            families.add(family)
    if len(families) < 2:
        reasons.append(BLOCK_NO_DERIVED + ":operator_diversity")


def validate_no_derived_law(
    value: Any,
    *,
    contradiction_id: Any,
) -> list[str]:
    """Validate the closed Council proof used by the terminal no-law branch.

    The staged protocol validator needs to replay this object without
    reconstructing a complete Council proposal.  Keeping this adapter here
    preserves one semantic authority for the proof shape and operator-family
    diversity requirement.
    """

    reasons: list[str] = []
    _validate_no_derived_law(
        value,
        contradiction_id=contradiction_id,
        reasons=reasons,
    )
    return _dedupe(reasons)


def _validate_law_binding(
    value: Any,
    *,
    proposal: Mapping[str, Any],
    mechanism_delta: Mapping[str, Any],
    reasons: list[str],
) -> None:
    binding = _exact_object(
        value, _LAW_BINDING_FIELDS, BLOCK_LAW_BINDING, reasons
    )
    if binding is None:
        return
    laws = proposal.get("candidate_revision_laws")
    index = binding.get("law_index")
    extension = mechanism_delta.get("minimal_extension")
    delta_id = extension.get("delta_id") if isinstance(extension, Mapping) else None
    if (
        not isinstance(laws, list)
        or len(laws) != 1
        or isinstance(index, bool)
        or not isinstance(index, int)
        or index != 0
        or not isinstance(laws[0], Mapping)
    ):
        reasons.append(BLOCK_LAW_BINDING)
        return
    try:
        law_digest = stable_json_hash(laws[0])
    except (TypeError, ValueError, OverflowError):
        reasons.append(BLOCK_LAW_BINDING)
        return
    if binding.get("law_sha256") != law_digest or binding.get("delta_id") != delta_id:
        reasons.append(BLOCK_LAW_BINDING)


def _canonical_core_bindings(
    *,
    proposal: Mapping[str, Any],
    feedback: Mapping[str, Any],
    mechanism_delta: Mapping[str, Any] | None,
    economic_backprojection: Mapping[str, Any] | None,
    source_refs: Mapping[str, Mapping[str, str] | None],
    reasons: list[str],
) -> tuple[dict[str, str], dict[str, Mapping[str, Any]]]:
    identity = feedback.get("artifact_identity")
    report_id = identity.get("report_id") if isinstance(identity, Mapping) else None
    if not isinstance(report_id, str):
        reasons.append(BLOCK_CORE + ":feedback_identity")
        return {}, {}
    if proposal.get("report_id") != report_id:
        reasons.append(BLOCK_CORE + ":proposal_report_id_mismatch")
    try:
        paths = evo_v2_relative_paths(report_id)
    except EvoV2Error:
        reasons.append(BLOCK_CORE + ":feedback_identity")
        return {}, {}
    artifacts: dict[str, Mapping[str, Any]] = {"feedback_ledger": feedback}
    if mechanism_delta is not None:
        artifacts["mechanism_delta"] = mechanism_delta
    if economic_backprojection is not None:
        artifacts["economic_backprojection"] = economic_backprojection
    identities = [artifact.get("artifact_identity") for artifact in artifacts.values()]
    if any(item != identity for item in identities):
        reasons.append(BLOCK_CORE + ":artifact_identity_mismatch")
    for name, source_ref in source_refs.items():
        if source_ref is None:
            continue
        artifact = artifacts.get(name)
        if artifact is None or source_ref != {
            "path": paths[name],
            "sha256": artifact_sha256(artifact),
        }:
            reasons.append(f"{BLOCK_CORE_REF}:{name}:canonical_binding")
    if mechanism_delta is not None:
        expected = {
            "path": paths["feedback_ledger"],
            "sha256": artifact_sha256(feedback),
        }
        if mechanism_delta.get("feedback_ref") != expected:
            reasons.append(BLOCK_CORE_REF + ":mechanism_delta.feedback_ref")
    if economic_backprojection is not None and mechanism_delta is not None:
        expected = {
            "path": paths["mechanism_delta"],
            "sha256": artifact_sha256(mechanism_delta),
        }
        if economic_backprojection.get("mechanism_delta_ref") != expected:
            reasons.append(
                BLOCK_CORE_REF + ":economic_backprojection.mechanism_delta_ref"
            )
    known = {paths[name]: artifact for name, artifact in artifacts.items()}
    return paths, known


def validate_council_evo_v2_intake(
    payload: Any,
    *,
    proposal: Mapping[str, Any],
    workspace_root: Path | str | None = None,
) -> list[str]:
    """Validate the Council-only envelope around canonical EVO V2 artifacts.

    The core feedback, mechanism-delta, and economic-backprojection semantics
    remain exclusively owned by :mod:`factor_factory.evo_v2`.
    """

    reasons: list[str] = []
    envelope = _exact_object(payload, _ENVELOPE_FIELDS, BLOCK_CONTRACT, reasons)
    if envelope is None:
        return _dedupe(reasons)
    if envelope.get("contract_version") != COUNCIL_EVO_V2_CONTRACT_VERSION:
        reasons.append(BLOCK_CONTRACT)
    root = _workspace_root(workspace_root, reasons)

    feedback, feedback_source = _load_core_artifact(
        envelope.get("feedback_ledger"),
        name="feedback_ledger",
        workspace_root=root,
        reasons=reasons,
    )
    _validate_intake_gate(envelope.get("intake_gate"), feedback, reasons)
    _validate_authority(envelope.get("authority"), reasons)

    outcome = _exact_object(
        envelope.get("derivation_outcome"), _OUTCOME_FIELDS, BLOCK_OUTCOME, reasons
    )
    mechanism_delta: dict[str, Any] | None = None
    economic_backprojection: dict[str, Any] | None = None
    delta_source: dict[str, str] | None = None
    backprojection_source: dict[str, str] | None = None
    if outcome is not None and outcome.get("outcome") == "MINIMAL_MECHANISM_DELTA":
        mechanism_delta, delta_source = _load_core_artifact(
            outcome.get("mechanism_delta"),
            name="mechanism_delta",
            workspace_root=root,
            reasons=reasons,
        )
        economic_backprojection, backprojection_source = _load_core_artifact(
            outcome.get("economic_backprojection"),
            name="economic_backprojection",
            workspace_root=root,
            reasons=reasons,
        )
        if outcome.get("no_derived_law") is not None:
            reasons.append(BLOCK_OUTCOME + ":exclusive_branch")
        if mechanism_delta is not None:
            _validate_law_binding(
                envelope.get("proposal_law_binding"),
                proposal=proposal,
                mechanism_delta=mechanism_delta,
                reasons=reasons,
            )
    elif outcome is not None and outcome.get("outcome") == "NO_DERIVED_LAW":
        if proposal.get("candidate_revision_laws") != []:
            reasons.append(BLOCK_OUTCOME + ":candidate_laws_must_be_empty")
        if (
            outcome.get("mechanism_delta") is not None
            or outcome.get("economic_backprojection") is not None
            or envelope.get("proposal_law_binding") is not None
        ):
            reasons.append(BLOCK_OUTCOME + ":exclusive_branch")
        contradiction = feedback.get("contradiction") if feedback else None
        contradiction_id = (
            contradiction.get("contradiction_id")
            if isinstance(contradiction, Mapping)
            else None
        )
        _validate_no_derived_law(
            outcome.get("no_derived_law"),
            contradiction_id=contradiction_id,
            reasons=reasons,
        )
    elif outcome is not None:
        reasons.append(BLOCK_OUTCOME)

    if feedback is not None:
        try:
            _, known = _canonical_core_bindings(
                proposal=proposal,
                feedback=feedback,
                mechanism_delta=mechanism_delta,
                economic_backprojection=economic_backprojection,
                source_refs={
                    "feedback_ledger": feedback_source,
                    "mechanism_delta": delta_source,
                    "economic_backprojection": backprojection_source,
                },
                reasons=reasons,
            )
            for reason in validate_feedback_ledger(
                feedback,
                workspace_root=root,
                known_artifacts=known,
                verify_refs=True,
            ):
                reasons.append(f"{BLOCK_CORE}:{reason}")
            if mechanism_delta is not None:
                for reason in validate_mechanism_delta(
                    mechanism_delta,
                    feedback_ledger=feedback,
                    workspace_root=root,
                    known_artifacts=known,
                    verify_refs=True,
                ):
                    reasons.append(f"{BLOCK_CORE}:{reason}")
            if economic_backprojection is not None:
                for reason in validate_economic_backprojection(
                    economic_backprojection,
                    mechanism_delta=mechanism_delta,
                    workspace_root=root,
                    known_artifacts=known,
                    verify_refs=True,
                ):
                    reasons.append(f"{BLOCK_CORE}:{reason}")
        except (EvoV2Error, TypeError, ValueError, OverflowError, OSError):
            reasons.append(BLOCK_CORE + ":unserializable_or_invalid_payload")

    reasons.extend(_scan_forbidden_shortcuts(proposal))
    return _dedupe(reasons)


def validate_revision_council_evo_v2(
    proposal: Mapping[str, Any],
    *,
    workspace_root: Path | str | None = None,
    required: bool = False,
) -> list[str]:
    """Adapter used by the existing Revision Council proposal validator."""

    if not isinstance(proposal, Mapping):
        return [BLOCK_CONTRACT]
    payload = proposal.get("evo_v2")
    if payload is None:
        return [BLOCK_MISSING] if required else []
    return validate_council_evo_v2_intake(
        payload,
        proposal=proposal,
        workspace_root=workspace_root,
    )


__all__ = [
    "COUNCIL_EVO_V2_CONTRACT_VERSION",
    "NO_DERIVED_LAW_CONTRACT_VERSION",
    "FEEDBACK_LEDGER_VERSION",
    "MECHANISM_DELTA_VERSION",
    "ECONOMIC_BACKPROJECTION_VERSION",
    "proposal_law_sha256",
    "validate_council_evo_v2_intake",
    "validate_no_derived_law",
    "validate_revision_council_evo_v2",
]
