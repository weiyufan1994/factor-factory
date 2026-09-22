from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from factor_factory.artifact_identity import stable_hash as implementation_hash
from factor_factory.evo_staging import (
    staging_manifest_path,
    validate_evo_v2_staging_manifest,
)
from factor_factory.evo_oos import validate_fresh_child_oos_allocation
from factor_factory.evo_v2 import (
    artifact_sha256,
    canonical_json_bytes,
    evo_v2_paths,
    sha256_file,
    stable_json_hash,
    validate_materialized_evo_v2,
)
from factor_factory.formula.parser import parse_formula
from factor_factory.human_approval import (
    human_approval_trust_path,
    validate_external_human_approval_receipt,
)
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
    validate_oos_exposure_private_registry_guard,
)
from factor_factory.research_conjecture import (
    epistemic_evolution_enabled,
    research_protocol_paths,
    validate_epistemic_evolution_lifecycle,
)
from factor_factory.revision_council.evo_v2 import proposal_law_sha256
from factor_factory.revision_council.pre_oos_outcome import (
    pre_oos_outcome_verifier_path,
    validate_materialized_pre_oos_council_outcome,
)

PRE_OOS_HUMAN_APPROVAL_VERSION = "factorforge_pre_oos_human_approval_v1"
PRE_OOS_CHILD_HANDOFF_VERSION = "factorforge_pre_oos_child_handoff_v1"
PRE_OOS_CHILD_INTENT_VERSION = "factorforge_pre_oos_child_intent_projection_v1"

BLOCK_PRE_OOS_HUMAN = "BLOCK_FACTORFORGE_PRE_OOS_HUMAN_BRIDGE_INVALID"
WAITING_PRE_OOS_TRANSFER = "WAITING_FACTORFORGE_EVO_TRANSFER_USE_RECORD"

_READY_STATES = {"TRANSFER_RECORDED", "COLD_START_RECORDED"}
_APPROVABLE_STATES = set(_READY_STATES)
_HEX = frozenset("0123456789abcdef")

_APPROVAL_AUTHORITY = {
    "approval_kind": "EXTERNAL_HUMAN_FRESH_OOS_CHILD_REVISION",
    "host_lifecycle_transition_performed": False,
    "child_inputs_materialized": False,
    "child_execution_performed": False,
    "child_execution_allowed_by_artifact": False,
    "canonical_write_allowed": False,
    "factor_verdict": "NOT_ISSUED",
    "materializer_must_replay_current_evo_and_oos_gates": True,
}

_HANDOFF_AUTHORITY = {
    "scope": "CONTROLLED_CHILD_INPUT_MATERIALIZATION_ONLY",
    "human_approval_validated": True,
    "execution_allowed_by_default": False,
    "child_execution_allowed": False,
    "canonical_write_allowed": False,
    "factor_verdict": "NOT_ISSUED",
    "fresh_oos_release_allowed": False,
    "current_gate_replay_required": True,
}

_INTENT_AUTHORITY = {
    "source": "SIGNED_EXTERNAL_HUMAN_RECEIPT_EXACT_PROJECTION",
    "allocation_authority": "ULTIMATE_HOST_ONLY",
    "materialization_authority": False,
    "execution_authority": False,
    "oos_release_authority": False,
    "canonical_write_allowed": False,
}


class PreOosHumanBridgeError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = _dedupe(reasons)
        super().__init__(";".join(self.reasons))


def _dedupe(reasons: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(reason) for reason in reasons if str(reason)))


def _token(suffix: str) -> str:
    return f"{BLOCK_PRE_OOS_HUMAN}:{suffix}"


def _incident_context(
    *,
    host_trust_root: Path | str,
    installation_id: str,
    incident_trust_root: Path | str | None,
    incident_installation_id: str | None,
) -> tuple[Path, str]:
    """Resolve the one Host registry that linearizes bridge authority.

    Public-ticket signing and OOS-incident authority deliberately share the
    same Host trust store.  Requiring the incident pair explicitly prevents an
    environment fallback from silently selecting a different registry, while
    the exact-binding check lets the live guard flow into ticket signing rather
    than reacquiring the same non-reentrant ``flock``.
    """

    if incident_trust_root is None or not _nonempty(incident_installation_id):
        raise PreOosHumanBridgeError([_token("incident_host_context_required")])
    host_root = Path(host_trust_root).expanduser().resolve(strict=True)
    incident_root = Path(incident_trust_root).expanduser().resolve(strict=True)
    if incident_root != host_root or incident_installation_id != installation_id:
        raise PreOosHumanBridgeError([_token("incident_host_binding_mismatch")])
    return incident_root, str(incident_installation_id)


def _current_lineage_reasons(
    *,
    root: Path,
    parent_report_id: str,
    child_intent: Mapping[str, Any],
    incident_trust_root: Path,
    incident_installation_id: str,
    incident_guard: object,
) -> list[str]:
    """Replay the full child -> ancestor incident gate under one live guard."""

    child_report_id = str(child_intent.get("child_report_id") or "")
    allocation_id = str(child_intent.get("oos_allocation_id") or "")
    allocation_ref = str(child_intent.get("oos_allocation_ref") or "")
    return validate_fresh_child_oos_allocation(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        allocation_id=allocation_id,
        allocation_ref=allocation_ref,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=incident_guard,
    )


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _load_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise PreOosHumanBridgeError([_token(f"file_invalid:{path.name}")])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreOosHumanBridgeError(
            [_token(f"json_invalid:{path.name}:{type(exc).__name__}")]
        ) from exc
    if not isinstance(payload, dict):
        raise PreOosHumanBridgeError([_token(f"object_required:{path.name}")])
    return payload


def _relative(root: Path, path: Path) -> str:
    return path.resolve(strict=True).relative_to(root).as_posix()


def _path_within_root_without_symlinks(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError:
        return False
    return True


def _file_ref(root: Path, path: Path) -> dict[str, str]:
    if not _path_within_root_without_symlinks(root, path):
        raise PreOosHumanBridgeError([_token(f"file_invalid:{path.name}")])
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)
    if not resolved.is_file():
        raise PreOosHumanBridgeError([_token(f"file_invalid:{path.name}")])
    return {"path": _relative(root, resolved), "sha256": sha256_file(resolved)}


def _content_file_ref(
    root: Path,
    path: Path,
    payload: Mapping[str, Any],
) -> dict[str, str]:
    unsigned = dict(payload)
    content_sha256 = unsigned.pop("content_sha256", None)
    if not _is_sha256(content_sha256) or content_sha256 != stable_json_hash(unsigned):
        raise PreOosHumanBridgeError([_token(f"content_hash_invalid:{path.name}")])
    return {
        **_file_ref(root, path),
        "content_sha256": str(content_sha256),
    }


def _resolve_ref(root: Path, value: Any) -> Path | None:
    if (
        not isinstance(value, dict)
        or set(value) not in ({"path", "sha256"}, {"task_id", "path", "sha256"})
        or ("task_id" in value and not _nonempty(value.get("task_id")))
    ):
        return None
    raw = value.get("path")
    digest = value.get("sha256")
    if not isinstance(raw, str) or not _is_sha256(digest) or "\\" in raw:
        return None
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != raw:
        return None
    lexical = root.joinpath(*relative.parts)
    if not _path_within_root_without_symlinks(root, lexical):
        return None
    candidate = lexical.resolve(strict=False)
    if not candidate.is_file() or sha256_file(candidate) != digest:
        return None
    return candidate


def pre_oos_human_approval_path(root: Path, report_id: str) -> Path:
    return (
        root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / report_id
        / f"pre_oos_human_approval__{report_id}.json"
    )


def pre_oos_child_handoff_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"


def pre_oos_child_intent_path(root: Path, child_report_id: str) -> Path:
    return (
        root
        / "objects"
        / "research_protocol"
        / f"evo_child_intent__{child_report_id}.json"
    )


def _parent_spec(root: Path, report_id: str) -> tuple[Path, dict[str, Any]]:
    path = (
        root
        / "objects"
        / "factor_spec_master"
        / f"factor_spec_master__{report_id}.json"
    )
    return path, _load_object(path)


def _implementation_mode(spec: Mapping[str, Any]) -> str:
    identity = spec.get("artifact_identity")
    identity = identity if isinstance(identity, Mapping) else {}
    contract = spec.get("implementation_contract")
    contract = contract if isinstance(contract, Mapping) else {}
    for value in (
        identity.get("implementation_mode"),
        spec.get("implementation_mode"),
        contract.get("mode"),
        contract.get("implementation_mode"),
    ):
        if _nonempty(value):
            return str(value)
    return "operator"


def _parent_formula_hash(spec: Mapping[str, Any]) -> str:
    canonical = spec.get("canonical_spec")
    canonical = canonical if isinstance(canonical, Mapping) else {}
    formula = canonical.get("formula_text")
    if not _nonempty(formula):
        raise PreOosHumanBridgeError([_token("parent_formula_missing")])
    parsed = parse_formula(str(formula))
    if parsed.get("parse_status") == "success":
        return str(parsed.get("formula_hash") or "")
    return implementation_hash(
        {
            "hash_role": "parent_formula_audit_hash",
            "formula_text": str(formula),
            "parse_status": "not_formula_ir_parent",
            "parse_errors": parsed.get("parse_errors") or [],
        }
    )


def _child_hash_and_contracts(
    *,
    child_formula: str,
    implementation_mode: str,
    law: Mapping[str, Any],
    result: Mapping[str, Any],
) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    if implementation_mode == "operator":
        parsed = parse_formula(child_formula)
        if parsed.get("parse_status") != "success":
            raise PreOosHumanBridgeError(
                [
                    _token("child_formula_parse_failed:")
                    + ",".join(str(item) for item in parsed.get("parse_errors") or [])
                ]
            )
        return str(parsed.get("formula_hash") or ""), None, None
    if implementation_mode not in {"direct_code", "hybrid"}:
        raise PreOosHumanBridgeError(
            [_token(f"implementation_mode_invalid:{implementation_mode}")]
        )
    translation = result.get("model_to_formula_translation")
    translation = translation if isinstance(translation, Mapping) else {}
    key = (
        "direct_code_revision_contract"
        if implementation_mode == "direct_code"
        else "hybrid_revision_contract"
    )
    contract = law.get(key)
    if not isinstance(contract, dict) or not contract:
        contract = translation.get(key)
    if not isinstance(contract, dict) or not contract:
        raise PreOosHumanBridgeError([_token(f"{key}_missing")])
    child_hash = implementation_hash(
        {
            "hash_role": f"{implementation_mode}_child_code_law_hash",
            "implementation_mode": implementation_mode,
            "child_formula_or_law": child_formula,
            "revision_contract": contract,
        }
    )
    return (
        child_hash,
        dict(contract) if implementation_mode == "direct_code" else None,
        dict(contract) if implementation_mode == "hybrid" else None,
    )


def _staging_prefix_hash(
    events: Sequence[Mapping[str, Any]], count: int, *, report_id: str
) -> str:
    return stable_json_hash(
        {
            "contract_version": "factorforge_evo_v2_staging_manifest_v1",
            "report_id": report_id,
            "host_authority": "ULTIMATE_HOST_FILE_LOCKED_CAS",
            "events": [dict(event) for event in events[:count]],
        }
    )


def _validate_staging_selection(
    *,
    root: Path,
    report_id: str,
    selected_result: Mapping[str, Any],
    selected_outcome: Mapping[str, Any],
    lifecycle_state: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = staging_manifest_path(root, report_id)
    manifest = _load_object(path)
    if path.read_bytes() != canonical_json_bytes(manifest):
        raise PreOosHumanBridgeError([_token("staging_noncanonical_json")])
    reasons = validate_evo_v2_staging_manifest(
        manifest,
        root=root,
        report_id=report_id,
        verify_readback=True,
    )
    events = manifest.get("events")
    if not isinstance(events, list) or len(events) < 2:
        reasons.append(_token("staging_council_outcome_missing"))
        events = []
    if events:
        second = events[1]
        if (
            second.get("stage") != "admit-council-outcome"
            or second.get("outcome") != "MINIMAL_MECHANISM_DELTA"
            or (second.get("input_digests") or {}).get("council_proposal")
            != artifact_sha256(selected_result)
        ):
            reasons.append(_token("staging_selected_result_mismatch"))
        outputs = {
            ref.get("name"): ref
            for ref in second.get("output_artifact_refs") or []
            if isinstance(ref, dict)
        }
        if (outputs.get("mechanism_delta") or {}).get("sha256") != selected_outcome.get(
            "mechanism_delta_sha256"
        ) or (outputs.get("economic_backprojection") or {}).get(
            "sha256"
        ) != selected_outcome.get("economic_backprojection_sha256"):
            reasons.append(_token("staging_selected_artifact_mismatch"))
        required_count = 4 if lifecycle_state in _READY_STATES else 2
        if len(events) < required_count:
            reasons.append(
                WAITING_PRE_OOS_TRANSFER
                if lifecycle_state in _READY_STATES
                else _token("staging_minimal_sequence_incomplete")
            )
    if reasons:
        raise PreOosHumanBridgeError(reasons)
    second = events[1]
    binding = {
        "path": _relative(root, path),
        "sha256": sha256_file(path),
        "content_sha256": manifest["content_sha256"],
        "event_count": len(events),
        "admit_council_outcome_event_sha256": second["event_sha256"],
        "admit_transfer_event_sha256": events[2]["event_sha256"],
        "record_use_event_sha256": events[3]["event_sha256"],
        "two_event_prefix_content_sha256": _staging_prefix_hash(
            events, 2, report_id=report_id
        ),
    }
    return manifest, binding


def _selected_projection(
    *,
    root: Path,
    report_id: str,
    report: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], Path, dict[str, Any], Path]:
    selected_outcome = report.get("selected_outcome")
    if (
        not isinstance(selected_outcome, dict)
        or selected_outcome.get("outcome") != "MINIMAL_MECHANISM_DELTA"
    ):
        raise PreOosHumanBridgeError([_token("minimal_outcome_required")])
    synthesis_ref = report.get("validated_synthesis_ref")
    synthesis_path = _resolve_ref(root, synthesis_ref)
    selected_ref = (report.get("evidence_bindings") or {}).get("selected_proposal_ref")
    selected_path = _resolve_ref(
        root,
        {
            "path": selected_ref.get("path"),
            "sha256": selected_ref.get("sha256"),
        }
        if isinstance(selected_ref, Mapping)
        else None,
    )
    if synthesis_path is None or selected_path is None:
        raise PreOosHumanBridgeError([_token("pre_oos_source_ref_invalid")])
    synthesis = _load_object(synthesis_path)
    selected_result = _load_object(selected_path)
    laws = selected_result.get("candidate_revision_laws")
    if not isinstance(laws, list) or len(laws) != 1 or not isinstance(laws[0], dict):
        raise PreOosHumanBridgeError([_token("exact_selected_law_required")])
    law = laws[0]
    if law.get("law_id") != selected_outcome.get("law_id") or proposal_law_sha256(
        law
    ) != selected_outcome.get("law_sha256"):
        raise PreOosHumanBridgeError([_token("selected_law_binding_mismatch")])
    translation = selected_result.get("model_to_formula_translation")
    translation = translation if isinstance(translation, Mapping) else {}
    child_formula = translation.get("candidate_formula")
    if not _nonempty(child_formula):
        raise PreOosHumanBridgeError([_token("agent_authored_child_formula_missing")])
    spec_path, spec = _parent_spec(root, report_id)
    mode = _implementation_mode(spec)
    child_hash, direct_contract, hybrid_contract = _child_hash_and_contracts(
        child_formula=str(child_formula),
        implementation_mode=mode,
        law=law,
        result=selected_result,
    )
    if child_hash == _parent_formula_hash(spec):
        raise PreOosHumanBridgeError([_token("child_revision_no_effect")])
    math = selected_result.get("math_mechanism_derivation")
    math = math if isinstance(math, Mapping) else {}
    signature = math.get("expected_metric_signature")
    if (
        not isinstance(signature, list)
        or not signature
        or not all(_nonempty(item) for item in signature)
    ):
        raise PreOosHumanBridgeError([_token("expected_metric_signature_missing")])
    falsification = law.get("falsification_tests")
    kill = law.get("kill_criteria")
    if not isinstance(falsification, list) or not falsification:
        raise PreOosHumanBridgeError([_token("falsification_tests_missing")])
    if not isinstance(kill, list) or not kill:
        raise PreOosHumanBridgeError([_token("kill_criteria_missing")])
    proof_updates = selected_result.get("proof_obligation_updates")
    proof_updates = proof_updates if isinstance(proof_updates, list) else []
    open_ids = [
        item.get("obligation_id")
        for item in proof_updates
        if isinstance(item, Mapping)
        and item.get("status") == "open"
        and _nonempty(item.get("obligation_id"))
    ]
    selection = synthesis.get("selection")
    selection = selection if isinstance(selection, Mapping) else {}
    economic = selected_result.get("economic_hypothesis_review")
    economic = economic if isinstance(economic, Mapping) else {}
    projection = {
        "law_id": law["law_id"],
        "law_or_formula_hash": selected_outcome["law_sha256"],
        "delta_id": selected_outcome["delta_id"],
        "child_formula": str(child_formula),
        "child_formula_hash": child_hash,
        "implementation_mode": mode,
        "direct_code_revision_contract": direct_contract,
        "hybrid_revision_contract": hybrid_contract,
        "expected_metric_signature": {
            "source": (
                "selected_raw_result.math_mechanism_derivation."
                "expected_metric_signature"
            ),
            "predictions": list(signature),
        },
        "falsification_tests": list(falsification),
        "kill_criteria": list(kill),
        "formula_mutation_description": law.get("law_statement"),
        "source_route_ids": [selected_outcome["route_id"]],
        "source_result_hashes": [selected_outcome["result_sha256"]],
        "open_proof_obligation_ids": open_ids,
        "why_selected": selection.get("rationale"),
        "economic_mechanism_link": economic.get("refined_second_layer_mechanism"),
        "math_model_link": math.get("model_mutation"),
    }
    if any(
        not _nonempty(projection.get(field))
        for field in (
            "formula_mutation_description",
            "why_selected",
            "economic_mechanism_link",
            "math_model_link",
        )
    ):
        raise PreOosHumanBridgeError([_token("selected_projection_incomplete")])
    return projection, selected_result, selected_path, synthesis, spec_path


def _formal_transfer_use_binding(
    *,
    root: Path,
    report_id: str,
    lifecycle_state: str,
    host_trust_root: Path | str | None,
    installation_id: str | None,
    admissions_root: Path | str | None,
) -> dict[str, Any]:
    """Replay the canonical Host transfer/cold closure without duplicating it."""

    if host_trust_root is None or not _nonempty(installation_id):
        raise PreOosHumanBridgeError(
            [_token("formal_transfer_use_host_trust_required")]
        )
    try:
        from factor_factory.evo_execution_addendum import (
            ADDENDUM_STATUS,
            execution_addendum_path,
        )
        from factor_factory.evo_transfer_use_orchestrator import (
            transfer_use_orchestration_path,
            validate_evo_v2_transfer_use_orchestration,
        )

        orchestration_path = transfer_use_orchestration_path(root, report_id)
        if orchestration_path.is_symlink() or not orchestration_path.is_file():
            raise PreOosHumanBridgeError(
                [_token("formal_transfer_use_orchestration_missing")]
            )
        orchestration = _load_object(orchestration_path)
        lifecycle_binding = orchestration.get("lifecycle")
        staging_binding = orchestration.get("staging_manifest")
        if not isinstance(lifecycle_binding, Mapping) or not isinstance(
            staging_binding, Mapping
        ):
            raise PreOosHumanBridgeError([_token("formal_transfer_use_binding_shape")])
        minimal_lifecycle_sha256 = lifecycle_binding.get("minimal_lifecycle_sha256")
        minimal_staging_sha256 = staging_binding.get("minimal_prefix_content_sha256")
        if not _is_sha256(minimal_lifecycle_sha256) or not _is_sha256(
            minimal_staging_sha256
        ):
            raise PreOosHumanBridgeError([_token("formal_transfer_use_prefix_hashes")])
        private_admissions = (
            Path(admissions_root).expanduser().resolve(strict=True)
            if admissions_root is not None
            else None
        )
        result = validate_evo_v2_transfer_use_orchestration(
            workspace_root=root,
            report_id=report_id,
            expected_minimal_lifecycle_sha256=str(minimal_lifecycle_sha256),
            expected_staging_content_sha256=str(minimal_staging_sha256),
            trust_root=Path(host_trust_root).expanduser().resolve(strict=True),
            installation_id=str(installation_id),
            admissions_root=private_admissions,
        )
        formal_ref = _content_file_ref(
            root,
            orchestration_path,
            orchestration,
        )
        if (
            result.get("verdict") != "PASS"
            or result.get("orchestration_ref") != formal_ref
        ):
            raise PreOosHumanBridgeError(
                [_token("formal_transfer_use_verifier_result")]
            )

        expected_memory_state = {
            "TRANSFER_RECORDED": "ADMISSIBLE_MEMORY_FOUND",
            "COLD_START_RECORDED": "COLD_START_NO_ADMISSIBLE_MEMORY",
        }.get(lifecycle_state)
        if (
            expected_memory_state is None
            or result.get("lifecycle_state") != lifecycle_state
            or result.get("memory_state") != expected_memory_state
        ):
            raise PreOosHumanBridgeError(
                [_token("formal_transfer_use_lifecycle_branch_mismatch")]
            )

        authority = result.get("authority")
        gate = orchestration.get("gate_evidence")
        if not isinstance(authority, Mapping) or not isinstance(gate, Mapping):
            raise PreOosHumanBridgeError(
                [_token("formal_transfer_use_authority_shape")]
            )
        addendum_ref: dict[str, str] | None = None
        if lifecycle_state == "TRANSFER_RECORDED":
            if private_admissions is None:
                raise PreOosHumanBridgeError(
                    [_token("formal_transfer_use_admissions_root_required")]
                )
            addendum_path = execution_addendum_path(root, report_id)
            addendum = _load_object(addendum_path)
            addendum_ref = _content_file_ref(root, addendum_path, addendum)
            if (
                gate.get("execution_addendum_ref") != addendum_ref
                or gate.get("execution_addendum_status") != ADDENDUM_STATUS
                or addendum.get("status") != ADDENDUM_STATUS
                or (addendum.get("execution_binding") or {}).get("state")
                != "PREREGISTERED_AND_BOUND_NOT_EVALUATED"
                or (addendum.get("execution_binding") or {}).get("execution_completed")
                is not False
                or authority.get("preregistered_transfer_tests_bound") is not True
                or authority.get("transfer_test_execution_completed") is not False
                or authority.get("transfer_execution_state")
                != "PREREGISTERED_AND_BOUND_NOT_EXECUTED"
                or authority.get("cold_start_zero_hit_verified") is not False
            ):
                raise PreOosHumanBridgeError(
                    [_token("formal_transfer_use_found_contract")]
                )
        else:
            addendum_path = execution_addendum_path(root, report_id)
            if (
                gate.get("execution_addendum_ref") is not None
                or gate.get("execution_addendum_status") is not None
                or addendum_path.exists()
                or addendum_path.is_symlink()
                or authority.get("preregistered_transfer_tests_bound") is not False
                or authority.get("transfer_test_execution_completed") is not False
                or authority.get("transfer_execution_state")
                != "NOT_APPLICABLE_COLD_START"
                or authority.get("cold_start_zero_hit_verified") is not True
            ):
                raise PreOosHumanBridgeError(
                    [_token("formal_transfer_use_cold_contract")]
                )
        if (
            authority.get("human_approval_granted") is not False
            or authority.get("oos_accessed") is not False
            or authority.get("child_execution_allowed") is not False
        ):
            raise PreOosHumanBridgeError(
                [_token("formal_transfer_use_authority_escalation")]
            )
        return {
            "memory_state": expected_memory_state,
            "orchestration_ref": formal_ref,
            "execution_addendum_ref": addendum_ref,
        }
    except PreOosHumanBridgeError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PreOosHumanBridgeError(
            [_token(f"formal_transfer_use_invalid:{type(exc).__name__}:{exc}")]
        ) from exc


def _source_bundle(
    *,
    root: Path,
    report_id: str,
    host_trust_root: Path | str | None,
    installation_id: str | None,
    admissions_root: Path | str | None,
) -> dict[str, Any]:
    protocol = research_protocol_paths(root, report_id)
    conjecture = _load_object(protocol["conjecture"])
    if not epistemic_evolution_enabled(conjecture):
        raise PreOosHumanBridgeError([_token("evo_v2_not_enabled")])
    lifecycle = _load_object(protocol["evo_lifecycle"])
    reasons = validate_epistemic_evolution_lifecycle(
        lifecycle,
        report_id=report_id,
        workspace_root=root,
        require_signed_host_receipts=True,
    )
    state = lifecycle.get("current_state")
    if reasons or state not in _APPROVABLE_STATES:
        state_reason = (
            WAITING_PRE_OOS_TRANSFER
            if state == "MINIMAL_MECHANISM_DELTA"
            else _token(f"lifecycle_not_approvable:{state}")
        )
        raise PreOosHumanBridgeError([*reasons, state_reason])
    outcome_report, outcome_reasons = validate_materialized_pre_oos_council_outcome(
        workspace_root=root,
        report_id=report_id,
        expected_transition_state="MINIMAL_MECHANISM_DELTA",
    )
    if outcome_report is None or outcome_reasons:
        raise PreOosHumanBridgeError(outcome_reasons or [_token("outcome_missing")])
    selected, selected_result, selected_path, synthesis, spec_path = (
        _selected_projection(root=root, report_id=report_id, report=outcome_report)
    )
    _complete_evo, complete_evo_reasons = validate_materialized_evo_v2(root, report_id)
    if complete_evo_reasons:
        raise PreOosHumanBridgeError(
            [
                _token(f"complete_evo_invalid:{reason}")
                for reason in complete_evo_reasons
            ]
        )
    _manifest, staging_binding = _validate_staging_selection(
        root=root,
        report_id=report_id,
        selected_result=selected_result,
        selected_outcome=outcome_report["selected_outcome"],
        lifecycle_state=str(state),
    )
    core = evo_v2_paths(root, report_id)
    delta = _load_object(core["mechanism_delta"])
    backprojection = _load_object(core["economic_backprojection"])
    identity = delta.get("artifact_identity")
    identity = identity if isinstance(identity, dict) else {}
    if (
        identity.get("report_id") != report_id
        or backprojection.get("artifact_identity") != identity
        or delta.get("minimal_extension", {}).get("delta_id")
        != selected.get("delta_id")
        or backprojection.get("delta_id") != selected.get("delta_id")
        or artifact_sha256(delta)
        != outcome_report["selected_outcome"]["mechanism_delta_sha256"]
        or artifact_sha256(backprojection)
        != outcome_report["selected_outcome"]["economic_backprojection_sha256"]
    ):
        raise PreOosHumanBridgeError([_token("staged_delta_identity_mismatch")])
    run_id = identity.get("run_id")
    if not _nonempty(run_id):
        raise PreOosHumanBridgeError([_token("run_id_missing")])
    formal_transfer_use = _formal_transfer_use_binding(
        root=root,
        report_id=report_id,
        lifecycle_state=str(state),
        host_trust_root=host_trust_root,
        installation_id=installation_id,
        admissions_root=admissions_root,
    )
    return {
        "conjecture": conjecture,
        "lifecycle": lifecycle,
        "lifecycle_state": state,
        "outcome_report": outcome_report,
        "outcome_report_path": pre_oos_outcome_verifier_path(root, report_id),
        "selected": selected,
        "selected_result": selected_result,
        "selected_result_path": selected_path,
        "synthesis": synthesis,
        "synthesis_path": _resolve_ref(root, outcome_report["validated_synthesis_ref"]),
        "spec_path": spec_path,
        "delta": delta,
        "delta_path": core["mechanism_delta"],
        "backprojection": backprojection,
        "backprojection_path": core["economic_backprojection"],
        "identity": identity,
        "run_id": run_id,
        "staging_binding": staging_binding,
        "formal_transfer_use": formal_transfer_use,
    }


def _approval_payload(
    *,
    root: Path,
    report_id: str,
    source: Mapping[str, Any],
    receipt: Mapping[str, Any],
    receipt_path: Path,
    trust_path: Path,
    lifecycle_state_at_approval: str | None = None,
) -> dict[str, Any]:
    intent = dict(receipt["child_intent"])
    formal = source["formal_transfer_use"]
    payload = {
        "contract_version": PRE_OOS_HUMAN_APPROVAL_VERSION,
        "report_id": report_id,
        "run_id": source["run_id"],
        "lifecycle_state_at_approval": (
            lifecycle_state_at_approval or source["lifecycle_state"]
        ),
        "evidence_bindings": {
            "root_synthesis_ref": _file_ref(root, source["synthesis_path"]),
            "outcome_verifier_ref": _file_ref(root, source["outcome_report_path"]),
            "selected_result_ref": _file_ref(root, source["selected_result_path"]),
            "staging_manifest_ref": source["staging_binding"],
            "formal_transfer_use_orchestration_ref": formal["orchestration_ref"],
            "execution_addendum_ref": formal["execution_addendum_ref"],
            "mechanism_delta_ref": _file_ref(root, source["delta_path"]),
            "economic_backprojection_ref": _file_ref(
                root, source["backprojection_path"]
            ),
            "parent_factor_spec_ref": _file_ref(root, source["spec_path"]),
            "external_human_receipt_ref": _file_ref(root, receipt_path),
            "human_trust_manifest_ref": _file_ref(root, trust_path),
            "oos_allocation_ref": {
                "path": intent["oos_allocation_ref"],
                "sha256": intent["oos_allocation_sha256"],
            },
            "oos_registry_prefix_ref": dict(intent["oos_registry_prefix_ref"]),
        },
        "selected_revision": source["selected"],
        "child_intent": intent,
        "human_issuer": receipt["issuer"],
        "external_human_receipt_id": receipt["receipt_id"],
        "external_human_issued_at_utc": receipt["issued_at_utc"],
        "authority": dict(_APPROVAL_AUTHORITY),
    }
    payload["content_sha256"] = stable_json_hash(payload)
    return payload


def _handoff_payload(
    *,
    root: Path,
    report_id: str,
    source: Mapping[str, Any],
    approval_path: Path,
    approval: Mapping[str, Any],
    receipt_path: Path,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    intent = dict(receipt["child_intent"])
    child_id = str(intent["child_report_id"])
    formal = source["formal_transfer_use"]
    payload = {
        "contract_version": PRE_OOS_CHILD_HANDOFF_VERSION,
        "parent_report_id": report_id,
        "child_report_id": child_id,
        "parent_identity": source["identity"],
        "parent_run_id": source["run_id"],
        "branch_id": f"evo_{source['selected']['delta_id']}",
        "trigger": "external_human_approved_pre_oos_minimal_mechanism_delta",
        "pre_oos_human_approval_ref": {
            "path": _relative(root, approval_path),
            "sha256": sha256_file(approval_path),
            "content_sha256": approval["content_sha256"],
        },
        "pre_oos_root_synthesis_ref": _file_ref(root, source["synthesis_path"]),
        "pre_oos_outcome_verifier_ref": _file_ref(root, source["outcome_report_path"]),
        "formal_transfer_use_orchestration_ref": formal["orchestration_ref"],
        "execution_addendum_ref": formal["execution_addendum_ref"],
        "selected_revision": source["selected"],
        "external_human_approval_receipt": {
            **_file_ref(root, receipt_path),
            "receipt_id": receipt["receipt_id"],
            "issuer": receipt["issuer"],
        },
        "fresh_oos_child_intent": intent,
        "authority": dict(_HANDOFF_AUTHORITY),
    }
    payload["content_sha256"] = stable_json_hash(payload)
    return payload


def _child_intent_payload(
    *,
    root: Path,
    report_id: str,
    approval_path: Path,
    approval: Mapping[str, Any],
    handoff_path: Path,
    handoff: Mapping[str, Any],
    intent: Mapping[str, Any],
    formal_transfer_use: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "contract_version": PRE_OOS_CHILD_INTENT_VERSION,
        "parent_report_id": report_id,
        "child_report_id": intent["child_report_id"],
        "approval_ref": _content_file_ref(root, approval_path, approval),
        "handoff_ref": _content_file_ref(root, handoff_path, handoff),
        "formal_transfer_use_orchestration_ref": formal_transfer_use[
            "orchestration_ref"
        ],
        "execution_addendum_ref": formal_transfer_use["execution_addendum_ref"],
        "signed_child_intent": dict(intent),
        "authority": dict(_INTENT_AUTHORITY),
    }
    payload["content_sha256"] = stable_json_hash(payload)
    return payload


def _write_once(root: Path, path: Path, payload: Mapping[str, Any]) -> bool:
    if not _path_within_root_without_symlinks(root, path):
        raise PreOosHumanBridgeError([_token(f"output_path_invalid:{path.name}")])
    expected = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
            raise PreOosHumanBridgeError([_token(f"output_conflict:{path.name}")])
        return True
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        temporary_path.write_bytes(expected)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return False


@contextmanager
def _bridge_lock(root: Path, report_id: str) -> Iterator[None]:
    path = pre_oos_human_approval_path(root, report_id).with_suffix(".lock")
    if not _path_within_root_without_symlinks(root, path):
        raise PreOosHumanBridgeError([_token("bridge_lock_path_invalid")])
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def materialize_pre_oos_human_bridge(
    *,
    workspace_root: Path | str,
    report_id: str,
    human_approval_receipt: Path | str,
    human_trust_manifest_sha256: str,
    host_trust_root: Path | str,
    installation_id: str,
    incident_trust_root: Path | str,
    incident_installation_id: str,
    admissions_root: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    incident_root, incident_installation = _incident_context(
        host_trust_root=host_trust_root,
        installation_id=installation_id,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
    )
    receipt_candidate = Path(human_approval_receipt).expanduser()
    if not receipt_candidate.is_absolute():
        receipt_candidate = root / receipt_candidate
    if not _path_within_root_without_symlinks(root, receipt_candidate):
        raise PreOosHumanBridgeError([_token("receipt_outside_workspace_or_symlink")])
    receipt_path = receipt_candidate.resolve(strict=False)
    trust_path = human_approval_trust_path(root)
    with oos_exposure_private_registry_guard(
        incident_root,
        installation_id=incident_installation,
    ) as incident_guard:
        validate_oos_exposure_private_registry_guard(
            incident_guard,
            trust_root=incident_root,
            installation_id=incident_installation,
        )
        if (
            not _path_within_root_without_symlinks(root, trust_path)
            or not trust_path.is_file()
            or trust_path.is_symlink()
            or not _is_sha256(human_trust_manifest_sha256)
            or sha256_file(trust_path) != human_trust_manifest_sha256
        ):
            raise PreOosHumanBridgeError([_token("human_trust_pin_mismatch")])
        receipt = _load_object(receipt_path)
        trust = _load_object(trust_path)
        source = _source_bundle(
            root=root,
            report_id=report_id,
            host_trust_root=host_trust_root,
            installation_id=installation_id,
            admissions_root=admissions_root,
        )
        selected = source["selected"]
        reasons = validate_external_human_approval_receipt(
            receipt,
            trust_manifest=trust,
            workspace_root=root,
            report_id=report_id,
            run_id=source["run_id"],
            synthesis_path=source["synthesis_path"],
            selected_law_id=selected["law_id"],
            selected_law_hash=selected["law_or_formula_hash"],
            child_formula_hash=selected["child_formula_hash"],
            mechanism_delta_path=source["delta_path"],
            economic_backprojection_path=source["backprojection_path"],
        )
        if reasons:
            raise PreOosHumanBridgeError(reasons)
        if receipt["child_intent"]["child_report_id"] == report_id:
            raise PreOosHumanBridgeError([_token("child_report_id_collision")])
        lineage_reasons = _current_lineage_reasons(
            root=root,
            parent_report_id=report_id,
            child_intent=receipt["child_intent"],
            incident_trust_root=incident_root,
            incident_installation_id=incident_installation,
            incident_guard=incident_guard,
        )
        if lineage_reasons:
            raise PreOosHumanBridgeError(lineage_reasons)
        approval_path = pre_oos_human_approval_path(root, report_id)
        handoff_path = pre_oos_child_handoff_path(root, report_id)
        intent_path = pre_oos_child_intent_path(
            root, receipt["child_intent"]["child_report_id"]
        )
        with _bridge_lock(root, report_id):
            prior_approval_state: str | None = None
            if approval_path.is_file() and not approval_path.is_symlink():
                prior = _load_object(approval_path)
                candidate_state = prior.get("lifecycle_state_at_approval")
                lifecycle_states = [
                    event.get("to_state")
                    for event in source["lifecycle"].get("events") or []
                    if isinstance(event, Mapping)
                ]
                if (
                    candidate_state in _APPROVABLE_STATES
                    and candidate_state in lifecycle_states
                ):
                    prior_approval_state = str(candidate_state)
            approval = _approval_payload(
                root=root,
                report_id=report_id,
                source=source,
                receipt=receipt,
                receipt_path=receipt_path,
                trust_path=trust_path,
                lifecycle_state_at_approval=prior_approval_state,
            )
            replayed = _write_once(root, approval_path, approval)
            handoff = _handoff_payload(
                root=root,
                report_id=report_id,
                source=source,
                approval_path=approval_path,
                approval=approval,
                receipt_path=receipt_path,
                receipt=receipt,
            )
            replayed = _write_once(root, handoff_path, handoff) and replayed
            child_intent = _child_intent_payload(
                root=root,
                report_id=report_id,
                approval_path=approval_path,
                approval=approval,
                handoff_path=handoff_path,
                handoff=handoff,
                intent=receipt["child_intent"],
                formal_transfer_use=source["formal_transfer_use"],
            )
            replayed = _write_once(root, intent_path, child_intent) and replayed
            approval_ref = _content_file_ref(root, approval_path, approval)
            handoff_ref = _content_file_ref(root, handoff_path, handoff)
            child_intent_ref = _content_file_ref(root, intent_path, child_intent)
            # The Host projects a public, signature-verifiable materialization
            # ticket only while the same incident guard remains live.  Passing
            # the token avoids a nested flock and keeps signing plus readback in
            # the bridge transaction.
            from factor_factory.evo_child_materialization_ticket import (
                materialize_public_child_materialization_ticket,
            )
            from factor_factory.evo_child_preregistration import (
                child_preregistration_receipt_path,
            )

            authorization_ticket = materialize_public_child_materialization_ticket(
                workspace_root=root,
                parent_report_id=report_id,
                child_report_id=str(receipt["child_intent"]["child_report_id"]),
                trust_root=host_trust_root,
                installation_id=installation_id,
                admissions_root=admissions_root,
                materialization_ready=False,
                _incident_guard=incident_guard,
            )
            child_report_id = str(receipt["child_intent"]["child_report_id"])
            preregistration_receipt = child_preregistration_receipt_path(
                root, child_report_id
            )
            ready_ticket = (
                materialize_public_child_materialization_ticket(
                    workspace_root=root,
                    parent_report_id=report_id,
                    child_report_id=child_report_id,
                    trust_root=host_trust_root,
                    installation_id=installation_id,
                    admissions_root=admissions_root,
                    materialization_ready=True,
                    _incident_guard=incident_guard,
                )
                if preregistration_receipt.is_file()
                and not preregistration_receipt.is_symlink()
                else None
            )
            return {
                "verdict": "PASS",
                "status": "EXTERNAL_HUMAN_APPROVED_CHILD_NOT_EXECUTED",
                "report_id": report_id,
                "child_report_id": receipt["child_intent"]["child_report_id"],
                "lifecycle_state": source["lifecycle_state"],
                "materialization_gate": (
                    "PUBLIC_HOST_TICKET_READY_FOR_CHILD_INPUT_MATERIALIZATION"
                    if ready_ticket is not None
                    else "WAITING_HOST_ATTESTED_CHILD_CONTROL_FREEZE"
                ),
                "approval_ref": approval_ref,
                "handoff_ref": handoff_ref,
                "child_intent_ref": child_intent_ref,
                "public_materialization_authorization_ticket_ref": (
                    authorization_ticket["ticket_ref"]
                ),
                "expected_host_trust_manifest_sha256": authorization_ticket[
                    "expected_host_trust_manifest_sha256"
                ],
                "public_materialization_ready_ticket_ref": (
                    ready_ticket["ticket_ref"] if ready_ticket is not None else None
                ),
                "idempotent_replay": replayed,
                "authority": dict(_APPROVAL_AUTHORITY),
            }


def validate_pre_oos_child_handoff(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    handoff: Mapping[str, Any] | None = None,
    require_materialization_ready: bool = False,
    host_trust_root: Path | str | None = None,
    installation_id: str | None = None,
    admissions_root: Path | str | None = None,
    expected_host_trust_manifest_sha256: str | None = None,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    if bool(incident_trust_root is not None) != bool(incident_installation_id):
        return None, [_token("incident_host_context_incomplete")]
    if _incident_guard is not None and (
        incident_trust_root is None or not incident_installation_id
    ):
        return None, [_token("incident_guard_context_incomplete")]
    if incident_trust_root is not None and incident_installation_id:
        try:
            resolved_incident_root = (
                Path(incident_trust_root).expanduser().resolve(strict=True)
            )
            if _incident_guard is None:
                with oos_exposure_private_registry_guard(
                    resolved_incident_root,
                    installation_id=incident_installation_id,
                ) as incident_guard:
                    return validate_pre_oos_child_handoff(
                        workspace_root=workspace_root,
                        parent_report_id=parent_report_id,
                        handoff=handoff,
                        require_materialization_ready=require_materialization_ready,
                        host_trust_root=host_trust_root,
                        installation_id=installation_id,
                        admissions_root=admissions_root,
                        expected_host_trust_manifest_sha256=(
                            expected_host_trust_manifest_sha256
                        ),
                        incident_trust_root=resolved_incident_root,
                        incident_installation_id=incident_installation_id,
                        _incident_guard=incident_guard,
                    )
            validate_oos_exposure_private_registry_guard(
                _incident_guard,
                trust_root=resolved_incident_root,
                installation_id=incident_installation_id,
            )
        except (OSError, ValueError) as exc:
            return None, [_token(f"incident_guard_invalid:{exc}")]
    try:
        root = Path(workspace_root).expanduser().resolve(strict=True)
        path = pre_oos_child_handoff_path(root, parent_report_id)
        payload = dict(handoff) if isinstance(handoff, Mapping) else _load_object(path)
        if payload.get("contract_version") != PRE_OOS_CHILD_HANDOFF_VERSION:
            return None, [_token("handoff_version")]
        unsigned = dict(payload)
        digest = unsigned.pop("content_sha256", None)
        if digest != stable_json_hash(unsigned):
            return None, [_token("handoff_content_sha256")]
        if (
            not _path_within_root_without_symlinks(root, path)
            or not path.is_file()
            or path.is_symlink()
            or _load_object(path) != payload
        ):
            return None, [_token("handoff_readback")]
        if incident_trust_root is not None and incident_installation_id:
            fresh_intent = payload.get("fresh_oos_child_intent")
            if not isinstance(fresh_intent, Mapping):
                return None, [_token("fresh_oos_child_intent_shape")]
            lineage_reasons = _current_lineage_reasons(
                root=root,
                parent_report_id=parent_report_id,
                child_intent=fresh_intent,
                incident_trust_root=resolved_incident_root,
                incident_installation_id=incident_installation_id,
                incident_guard=_incident_guard,
            )
            if lineage_reasons:
                return None, _dedupe(lineage_reasons)
        if (
            host_trust_root is None
            and installation_id is None
            and admissions_root is None
        ):
            # Child-side replay consumes only the Host-signed public projection.
            # It never receives access to the Host trust root or private memory.
            from factor_factory.evo_child_materialization_ticket import (
                WAITING_PUBLIC_CHILD_MATERIALIZATION_TICKET,
                validate_public_child_materialization_ticket,
            )

            _ticket, public_reasons = validate_public_child_materialization_ticket(
                workspace_root=root,
                parent_report_id=parent_report_id,
                child_report_id=str(payload.get("child_report_id") or ""),
                require_materialization_ready=require_materialization_ready,
                handoff=payload,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
                incident_trust_root=incident_trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=_incident_guard,
            )
            if (
                require_materialization_ready
                and public_reasons
                and all(
                    reason.startswith(WAITING_PUBLIC_CHILD_MATERIALIZATION_TICKET)
                    for reason in public_reasons
                )
            ):
                public_reasons = [WAITING_PRE_OOS_TRANSFER, *public_reasons]
            return (
                (payload if not public_reasons else None),
                _dedupe(public_reasons),
            )
        if host_trust_root is None or not _nonempty(installation_id):
            return None, [_token("partial_private_replay_credentials")]
        if incident_trust_root is None or not incident_installation_id:
            return None, [_token("incident_host_context_required")]
        source = _source_bundle(
            root=root,
            report_id=parent_report_id,
            host_trust_root=host_trust_root,
            installation_id=installation_id,
            admissions_root=admissions_root,
        )
        approval_ref = payload.get("pre_oos_human_approval_ref")
        if not isinstance(approval_ref, dict) or set(approval_ref) != {
            "path",
            "sha256",
            "content_sha256",
        }:
            return None, [_token("approval_ref_shape")]
        approval_path = _resolve_ref(
            root,
            {"path": approval_ref.get("path"), "sha256": approval_ref.get("sha256")},
        )
        if approval_path is None:
            return None, [_token("approval_ref_invalid")]
        if approval_path != pre_oos_human_approval_path(root, parent_report_id).resolve(
            strict=False
        ):
            return None, [_token("approval_ref_not_canonical")]
        approval = _load_object(approval_path)
        receipt_ref = payload.get("external_human_approval_receipt")
        if not isinstance(receipt_ref, dict) or set(receipt_ref) != {
            "path",
            "sha256",
            "receipt_id",
            "issuer",
        }:
            return None, [_token("receipt_ref_shape")]
        receipt_path = _resolve_ref(
            root,
            {"path": receipt_ref.get("path"), "sha256": receipt_ref.get("sha256")},
        )
        if receipt_path is None:
            return None, [_token("receipt_ref_invalid")]
        receipt = _load_object(receipt_path)
        trust_path = human_approval_trust_path(root)
        trust = _load_object(trust_path)
        selected = source["selected"]
        receipt_reasons = validate_external_human_approval_receipt(
            receipt,
            trust_manifest=trust,
            workspace_root=root,
            report_id=parent_report_id,
            run_id=source["run_id"],
            synthesis_path=source["synthesis_path"],
            selected_law_id=selected["law_id"],
            selected_law_hash=selected["law_or_formula_hash"],
            child_formula_hash=selected["child_formula_hash"],
            mechanism_delta_path=source["delta_path"],
            economic_backprojection_path=source["backprojection_path"],
        )
        approval_state = approval.get("lifecycle_state_at_approval")
        lifecycle_states = [
            event.get("to_state")
            for event in source["lifecycle"].get("events") or []
            if isinstance(event, Mapping)
        ]
        if (
            approval_state not in _APPROVABLE_STATES
            or approval_state not in lifecycle_states
        ):
            return None, [_token("approval_lifecycle_state_not_in_lineage")]
        expected_approval = _approval_payload(
            root=root,
            report_id=parent_report_id,
            source=source,
            receipt=receipt,
            receipt_path=receipt_path,
            trust_path=trust_path,
            lifecycle_state_at_approval=str(approval_state),
        )
        if approval != expected_approval or approval.get(
            "content_sha256"
        ) != approval_ref.get("content_sha256"):
            return None, [_token("approval_exact_projection_mismatch")]
        expected = {
            "contract_version": PRE_OOS_CHILD_HANDOFF_VERSION,
            "parent_report_id": parent_report_id,
            "child_report_id": receipt["child_intent"]["child_report_id"],
            "parent_identity": source["identity"],
            "parent_run_id": source["run_id"],
            "branch_id": f"evo_{selected['delta_id']}",
            "trigger": "external_human_approved_pre_oos_minimal_mechanism_delta",
            "pre_oos_human_approval_ref": approval_ref,
            "pre_oos_root_synthesis_ref": _file_ref(root, source["synthesis_path"]),
            "pre_oos_outcome_verifier_ref": _file_ref(
                root, source["outcome_report_path"]
            ),
            "formal_transfer_use_orchestration_ref": source["formal_transfer_use"][
                "orchestration_ref"
            ],
            "execution_addendum_ref": source["formal_transfer_use"][
                "execution_addendum_ref"
            ],
            "selected_revision": selected,
            "external_human_approval_receipt": receipt_ref,
            "fresh_oos_child_intent": receipt["child_intent"],
            "authority": dict(_HANDOFF_AUTHORITY),
        }
        expected["content_sha256"] = stable_json_hash(expected)
        reasons = list(receipt_reasons)
        if payload != expected:
            reasons.append(_token("handoff_exact_projection_mismatch"))
        child_intent_path = pre_oos_child_intent_path(
            root,
            str(receipt["child_intent"]["child_report_id"]),
        )
        if child_intent_path.is_symlink() or not child_intent_path.is_file():
            reasons.append(_token("child_intent_readback"))
        else:
            child_intent = _load_object(child_intent_path)
            expected_child_intent = _child_intent_payload(
                root=root,
                report_id=parent_report_id,
                approval_path=approval_path,
                approval=approval,
                handoff_path=path,
                handoff=payload,
                intent=receipt["child_intent"],
                formal_transfer_use=source["formal_transfer_use"],
            )
            if child_intent != expected_child_intent:
                reasons.append(_token("child_intent_exact_projection_mismatch"))
        if require_materialization_ready:
            state = source["lifecycle_state"]
            manifest = _load_object(staging_manifest_path(root, parent_report_id))
            if state not in _READY_STATES or len(manifest.get("events") or []) != 4:
                reasons.append(WAITING_PRE_OOS_TRANSFER)
            from factor_factory.evo_child_materialization_ticket import (
                validate_public_child_materialization_ticket,
            )

            _ticket, ticket_reasons = validate_public_child_materialization_ticket(
                workspace_root=root,
                parent_report_id=parent_report_id,
                child_report_id=str(payload.get("child_report_id") or ""),
                require_materialization_ready=True,
                handoff=payload,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
                incident_trust_root=incident_trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=_incident_guard,
            )
            reasons.extend(ticket_reasons)
        return (payload if not reasons else None), _dedupe(reasons)
    except PreOosHumanBridgeError as exc:
        return None, exc.reasons
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, [_token(f"unexpected:{type(exc).__name__}")]


__all__ = [
    "BLOCK_PRE_OOS_HUMAN",
    "PRE_OOS_CHILD_HANDOFF_VERSION",
    "PRE_OOS_CHILD_INTENT_VERSION",
    "PRE_OOS_HUMAN_APPROVAL_VERSION",
    "WAITING_PRE_OOS_TRANSFER",
    "PreOosHumanBridgeError",
    "materialize_pre_oos_human_bridge",
    "pre_oos_child_handoff_path",
    "pre_oos_child_intent_path",
    "pre_oos_human_approval_path",
    "validate_pre_oos_child_handoff",
]
