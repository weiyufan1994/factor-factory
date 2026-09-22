from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from factor_factory.evo_oos import (
    child_control_paths,
    oos_allocation_path,
    oos_registry_path,
    validate_fresh_child_oos_allocation_structural,
    validate_oos_registry_allocation_prefix,
)
from factor_factory.evo_v2 import canonical_json_bytes, sha256_file, stable_json_hash
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
    validate_oos_exposure_private_registry_guard,
)
from factor_factory.research_conjecture import workspace_runtime_trust_manifest
from factor_factory.research_org.runtime_trust import (
    load_runtime_trust_store,
    validate_public_trust_manifest,
    verify_signed_receipt_with_manifest,
)

PUBLIC_CHILD_MATERIALIZATION_TICKET_VERSION = (
    "factorforge_evo_public_child_materialization_ticket_v2"
)
PUBLIC_CHILD_MATERIALIZATION_TICKET_RECEIPT_TYPE = (
    "EVO_V2_PUBLIC_CHILD_MATERIALIZATION_TICKET"
)
TICKET_STATE_NOT_MATERIALIZED = "NOT_MATERIALIZED"
TICKET_STATE_READY = "MATERIALIZATION_READY"
BLOCK_PUBLIC_CHILD_MATERIALIZATION_TICKET = (
    "BLOCK_FACTORFORGE_EVO_PUBLIC_CHILD_MATERIALIZATION_TICKET_INVALID"
)
WAITING_PUBLIC_CHILD_MATERIALIZATION_TICKET = (
    "WAITING_FACTORFORGE_EVO_CHILD_MATERIALIZATION_TICKET_READY"
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,191}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CONTROL_NAMES = (
    "research_state",
    "research_conjecture",
    "approach_registry",
    "search_trial_ledger",
    "metric_verifier_spec",
    "threshold_registration",
)
_LIFECYCLE_BY_MEMORY = {
    "ADMISSIBLE_MEMORY_FOUND": "TRANSFER_RECORDED",
    "COLD_START_NO_ADMISSIBLE_MEMORY": "COLD_START_RECORDED",
}


class PublicChildMaterializationTicketError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = list(dict.fromkeys(str(item) for item in reasons if str(item)))
        super().__init__(";".join(self.reasons))


def _token(reason: str) -> str:
    return f"{BLOCK_PUBLIC_CHILD_MATERIALIZATION_TICKET}:{reason}"


def _waiting(reason: str) -> str:
    return f"{WAITING_PUBLIC_CHILD_MATERIALIZATION_TICKET}:{reason}"


def _safe_id(value: Any) -> bool:
    return isinstance(value, str) and _SAFE_ID.fullmatch(value) is not None


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _within_without_symlinks(root: Path, path: Path) -> bool:
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


def _load_object(path: Path, *, canonical: bool = False) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PublicChildMaterializationTicketError(
            [_token(f"missing_or_unsafe:{path.name}")]
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicChildMaterializationTicketError(
            [_token(f"invalid_json:{path.name}")]
        ) from exc
    if not isinstance(payload, dict):
        raise PublicChildMaterializationTicketError(
            [_token(f"object_required:{path.name}")]
        )
    if canonical and path.read_bytes() != canonical_json_bytes(payload):
        raise PublicChildMaterializationTicketError(
            [_token(f"noncanonical_json:{path.name}")]
        )
    return payload


def _content_sha256(payload: Mapping[str, Any]) -> str:
    declared = payload.get("content_sha256")
    if declared is None:
        return stable_json_hash(dict(payload))
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if not _is_sha256(declared) or declared != stable_json_hash(unsigned):
        raise PublicChildMaterializationTicketError([_token("bound_content_hash")])
    return str(declared)


def _object_ref(root: Path, path: Path, payload: Mapping[str, Any]) -> dict[str, str]:
    if not _within_without_symlinks(root, path):
        raise PublicChildMaterializationTicketError([_token(f"unsafe_ref:{path.name}")])
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise PublicChildMaterializationTicketError(
            [_token(f"missing_ref:{path.name}")]
        )
    return {
        "path": resolved.relative_to(root).as_posix(),
        "sha256": sha256_file(resolved),
        "content_sha256": _content_sha256(payload),
    }


def _resolve_object_ref(
    root: Path,
    reference: Any,
    *,
    expected_path: Path,
    label: str,
) -> tuple[Path | None, dict[str, Any] | None, list[str]]:
    if not isinstance(reference, Mapping) or set(reference) != {
        "path",
        "sha256",
        "content_sha256",
    }:
        return None, None, [_token(f"{label}_ref_shape")]
    raw = reference.get("path")
    if (
        not isinstance(raw, str)
        or "\\" in raw
        or not _is_sha256(reference.get("sha256"))
        or not _is_sha256(reference.get("content_sha256"))
    ):
        return None, None, [_token(f"{label}_ref_values")]
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != raw:
        return None, None, [_token(f"{label}_ref_path")]
    lexical = root.joinpath(*relative.parts)
    expected = expected_path.resolve(strict=False)
    if (
        not _within_without_symlinks(root, lexical)
        or lexical.resolve(strict=False) != expected
        or not expected.is_file()
        or expected.is_symlink()
    ):
        return None, None, [_token(f"{label}_ref_not_canonical")]
    try:
        payload = _load_object(expected)
        observed = _object_ref(root, expected, payload)
    except PublicChildMaterializationTicketError as exc:
        return None, None, exc.reasons
    if dict(reference) != observed:
        return None, None, [_token(f"{label}_ref_readback")]
    return expected, payload, []


def public_child_materialization_ticket_path(
    workspace_root: Path,
    child_report_id: str,
    *,
    materialization_ready: bool,
) -> Path:
    if not _safe_id(child_report_id):
        raise PublicChildMaterializationTicketError([_token("child_report_id")])
    suffix = "ready" if materialization_ready else "authorization"
    return (
        Path(workspace_root)
        / "objects"
        / "research_protocol"
        / f"evo_child_materialization_ticket__{child_report_id}__{suffix}.json"
    )


def public_child_materialization_trust_manifest_path(workspace_root: Path) -> Path:
    return (
        Path(workspace_root)
        / "identity"
        / "evo_child_materialization_host_trust_manifest.json"
    )


def _approval_path(root: Path, parent_report_id: str) -> Path:
    return (
        root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / parent_report_id
        / f"pre_oos_human_approval__{parent_report_id}.json"
    )


def _handoff_path(root: Path, parent_report_id: str) -> Path:
    return root / "objects" / "handoff" / f"handoff_to_step3b__{parent_report_id}.json"


def _intent_path(root: Path, child_report_id: str) -> Path:
    return (
        root
        / "objects"
        / "research_protocol"
        / f"evo_child_intent__{child_report_id}.json"
    )


def _parent_data_prep_path(root: Path, parent_report_id: str) -> Path:
    return (
        root
        / "objects"
        / "data_prep_master"
        / f"data_prep_master__{parent_report_id}.json"
    )


def _orchestration_path(root: Path, parent_report_id: str) -> Path:
    return (
        root
        / "objects"
        / "evo_v2"
        / parent_report_id
        / "transfer_use_orchestration.json"
    )


def _addendum_path(root: Path, parent_report_id: str) -> Path:
    return root / "objects" / "evo_v2" / parent_report_id / "execution_addendum.json"


def _declared_input_ref(
    root: Path,
    raw: Any,
    *,
    label: str,
) -> dict[str, str]:
    if not isinstance(raw, str) or not raw.strip():
        raise PublicChildMaterializationTicketError(
            [_token(f"parent_daily_input_missing:{label}")]
        )
    declared = Path(raw).expanduser()
    candidates = [declared] if declared.is_absolute() else [root / declared]
    if not declared.is_absolute() and declared.parts and declared.parts[0] == root.name:
        candidates.append(root.parent / declared)
    existing: dict[Path, Path] = {}
    for candidate in candidates:
        if not _within_without_symlinks(root, candidate):
            continue
        resolved = candidate.resolve(strict=False)
        if resolved.is_file():
            existing[resolved] = candidate
    if len(existing) != 1:
        raise PublicChildMaterializationTicketError(
            [_token(f"parent_daily_input_invalid_or_ambiguous:{label}")]
        )
    resolved, lexical = next(iter(existing.items()))
    if lexical.is_symlink() or not _within_without_symlinks(root, lexical):
        raise PublicChildMaterializationTicketError(
            [_token(f"parent_daily_input_invalid:{label}")]
        )
    return {
        "path": resolved.relative_to(root).as_posix(),
        "sha256": sha256_file(resolved),
    }


def _frozen_parent_daily_inputs(
    *,
    root: Path,
    parent_report_id: str,
    data_prep: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    if data_prep.get("report_id") != parent_report_id:
        raise PublicChildMaterializationTicketError(
            [_token("parent_data_prep_identity")]
        )
    local = data_prep.get("local_input_paths")
    if not isinstance(local, Mapping):
        raise PublicChildMaterializationTicketError(
            [_token("parent_data_prep_local_inputs")]
        )
    selected = [
        key
        for key in ("daily_df_parquet", "daily_df_csv")
        if isinstance(local.get(key), str) and str(local[key]).strip()
    ]
    if not selected:
        raise PublicChildMaterializationTicketError(
            [_token("parent_selected_daily_snapshot_required")]
        )
    if (
        not isinstance(local.get("daily_input_meta_json"), str)
        or not str(local["daily_input_meta_json"]).strip()
    ):
        raise PublicChildMaterializationTicketError(
            [_token("parent_daily_input_meta_required")]
        )
    declared_snapshot_keys = (
        "daily_df_parquet",
        "daily_df_csv",
        "daily_df_csv_sample",
        "evaluation_daily_df_parquet",
        "evaluation_daily_df_csv",
        "signal_daily_df_parquet",
        "signal_daily_df_csv",
        "daily_input_meta_json",
    )
    keys = [
        key
        for key in declared_snapshot_keys
        if isinstance(local.get(key), str) and str(local[key]).strip()
    ]
    return {
        key: _declared_input_ref(root, local[key], label=key) for key in sorted(keys)
    }


def _verify_public_orchestration(
    *,
    root: Path,
    parent_report_id: str,
    orchestration: Mapping[str, Any],
    trust_manifest: Mapping[str, Any],
) -> list[str]:
    from factor_factory.evo_transfer_use_orchestrator import (
        ORCHESTRATION_RECEIPT_TYPE,
        ORCHESTRATION_VERSION,
    )
    from factor_factory.research_obligation_verifier import stable_hash

    reasons: list[str] = []
    if (
        orchestration.get("contract_version") != ORCHESTRATION_VERSION
        or orchestration.get("report_id") != parent_report_id
        or orchestration.get("verifier_status") != "PASS"
    ):
        reasons.append(_token("formal_orchestration_identity"))
    unsigned = dict(orchestration)
    content = unsigned.pop("content_sha256", None)
    if content != stable_hash(unsigned):
        reasons.append(_token("formal_orchestration_content_hash"))
    receipt = orchestration.get("host_completion_receipt")
    if not isinstance(receipt, Mapping):
        reasons.append(_token("formal_orchestration_host_receipt"))
        return reasons
    reasons.extend(
        _token(f"formal_orchestration_signature:{reason}")
        for reason in verify_signed_receipt_with_manifest(
            receipt,
            trust_manifest=trust_manifest,
            expected_issuer="host_admission",
        )
    )
    core = {
        key: value
        for key, value in orchestration.items()
        if key not in {"host_completion_receipt", "content_sha256"}
    }
    expected_bindings = {
        "orchestration_core_sha256": stable_hash(core),
        "memory_state": orchestration.get("memory_state"),
        "lifecycle": orchestration.get("lifecycle"),
        "staging_manifest": orchestration.get("staging_manifest"),
        "canonical_artifacts": orchestration.get("canonical_artifacts"),
        "gate_evidence": orchestration.get("gate_evidence"),
    }
    if (
        receipt.get("receipt_type") != ORCHESTRATION_RECEIPT_TYPE
        or receipt.get("identity") != orchestration.get("artifact_identity")
        or receipt.get("bindings") != expected_bindings
        or (receipt.get("outcome") or {}).get("verifier_status") != "PASS"
    ):
        reasons.append(_token("formal_orchestration_host_binding"))
    authority = orchestration.get("authority")
    if (
        not isinstance(authority, Mapping)
        or authority.get("human_approval_granted") is not False
        or authority.get("oos_accessed") is not False
        or authority.get("child_execution_allowed") is not False
        or authority.get("factor_verdict") != "NOT_ISSUED"
    ):
        reasons.append(_token("formal_orchestration_authority"))
    return reasons


def _verify_public_addendum(
    *,
    parent_report_id: str,
    addendum: Mapping[str, Any],
    trust_manifest: Mapping[str, Any],
) -> list[str]:
    from factor_factory.evo_execution_addendum import (
        ADDENDUM_STATUS,
        EXECUTION_ADDENDUM_RECEIPT_TYPE,
        EXECUTION_ADDENDUM_VERSION,
        REGISTERED_STATUS,
    )

    reasons: list[str] = []
    unsigned = dict(addendum)
    content = unsigned.pop("content_sha256", None)
    binding = addendum.get("execution_binding")
    if (
        addendum.get("contract_version") != EXECUTION_ADDENDUM_VERSION
        or addendum.get("report_id") != parent_report_id
        or addendum.get("execution_target") != "FRESH_CHILD_PURGED_IS"
        or addendum.get("status") != ADDENDUM_STATUS
        or content != stable_json_hash(unsigned)
        or not isinstance(binding, Mapping)
        or binding.get("state") != REGISTERED_STATUS
        or binding.get("execution_completed") is not False
    ):
        reasons.append(_token("execution_addendum_contract"))
    receipt = addendum.get("host_attestation")
    if not isinstance(receipt, Mapping):
        return [*reasons, _token("execution_addendum_host_attestation")]
    reasons.extend(
        _token(f"execution_addendum_signature:{reason}")
        for reason in verify_signed_receipt_with_manifest(
            receipt,
            trust_manifest=trust_manifest,
            expected_issuer="host_admission",
        )
    )
    expected_bindings = {
        "report_id": parent_report_id,
        "execution_target": addendum.get("execution_target"),
        "source_refs": addendum.get("source_refs"),
        "frozen_web_research_plan_ref": addendum.get("frozen_web_research_plan_ref"),
        "before_research_plan_ref": addendum.get("before_research_plan_ref"),
        "after_research_plan_ref": addendum.get("after_research_plan_ref"),
        "private_memory_admission_ref": addendum.get("private_memory_admission_ref"),
        "required_evidence_refs": addendum.get("required_evidence_refs"),
        "protected_contracts": addendum.get("protected_contracts"),
        "execution_tests_sha256": stable_json_hash(addendum.get("execution_tests")),
    }
    expected_outcome = {
        "state": REGISTERED_STATUS,
        "execution_completed": False,
        "current_factor_evidence": False,
        "factor_verdict": "NOT_ISSUED",
        "child_execution_allowed": False,
    }
    if (
        receipt.get("receipt_type") != EXECUTION_ADDENDUM_RECEIPT_TYPE
        or receipt.get("identity") != addendum.get("artifact_identity")
        or receipt.get("bindings") != expected_bindings
        or receipt.get("outcome") != expected_outcome
    ):
        reasons.append(_token("execution_addendum_host_binding"))
    return reasons


def _source_artifacts(
    root: Path,
    parent_report_id: str,
    child_report_id: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    paths = {
        "approval": _approval_path(root, parent_report_id),
        "handoff": _handoff_path(root, parent_report_id),
        "child_intent": _intent_path(root, child_report_id),
        "formal_orchestration": _orchestration_path(root, parent_report_id),
        "oos_allocation": oos_allocation_path(root, child_report_id),
        "oos_registry": oos_registry_path(root),
        "parent_data_prep": _parent_data_prep_path(root, parent_report_id),
    }
    unsafe = [
        path.name for path in paths.values() if not _within_without_symlinks(root, path)
    ]
    if unsafe:
        raise PublicChildMaterializationTicketError(
            [_token(f"source_path_unsafe:{name}") for name in unsafe]
        )
    payloads = {name: _load_object(path) for name, path in paths.items()}
    approval = payloads["approval"]
    handoff = payloads["handoff"]
    intent = payloads["child_intent"]
    orchestration = payloads["formal_orchestration"]
    data_prep = payloads["parent_data_prep"]
    frozen_daily_inputs = _frozen_parent_daily_inputs(
        root=root,
        parent_report_id=parent_report_id,
        data_prep=data_prep,
    )
    signed_intent = handoff.get("fresh_oos_child_intent")
    if (
        approval.get("contract_version") != "factorforge_pre_oos_human_approval_v1"
        or approval.get("report_id") != parent_report_id
        or handoff.get("contract_version") != "factorforge_pre_oos_child_handoff_v1"
        or handoff.get("parent_report_id") != parent_report_id
        or handoff.get("child_report_id") != child_report_id
        or intent.get("contract_version")
        != "factorforge_pre_oos_child_intent_projection_v1"
        or intent.get("parent_report_id") != parent_report_id
        or intent.get("child_report_id") != child_report_id
        or intent.get("signed_child_intent") != signed_intent
        or approval.get("child_intent") != signed_intent
        or not isinstance(signed_intent, Mapping)
    ):
        raise PublicChildMaterializationTicketError(
            [_token("pre_oos_projection_identity")]
        )
    addendum: dict[str, Any] | None = None
    memory_state = orchestration.get("memory_state")
    lifecycle_state = (orchestration.get("lifecycle") or {}).get("current_state")
    if _LIFECYCLE_BY_MEMORY.get(str(memory_state)) != lifecycle_state:
        raise PublicChildMaterializationTicketError(
            [_token("transfer_lifecycle_branch")]
        )
    addendum_ref = handoff.get("execution_addendum_ref")
    gate_addendum = (orchestration.get("gate_evidence") or {}).get(
        "execution_addendum_ref"
    )
    if memory_state == "ADMISSIBLE_MEMORY_FOUND":
        addendum_path = _addendum_path(root, parent_report_id)
        addendum = _load_object(addendum_path)
        paths["execution_addendum"] = addendum_path
        payloads["execution_addendum"] = addendum
        if (
            not isinstance(addendum_ref, Mapping)
            or dict(addendum_ref) != _object_ref(root, addendum_path, addendum)
            or gate_addendum != addendum_ref
        ):
            raise PublicChildMaterializationTicketError(
                [_token("execution_addendum_projection")]
            )
    elif memory_state == "COLD_START_NO_ADMISSIBLE_MEMORY":
        addendum_path = _addendum_path(root, parent_report_id)
        if (
            addendum_ref is not None
            or gate_addendum is not None
            or addendum_path.exists()
        ):
            raise PublicChildMaterializationTicketError(
                [_token("cold_addendum_forbidden")]
            )
    else:
        raise PublicChildMaterializationTicketError([_token("memory_state")])
    refs = {
        name: _object_ref(root, paths[name], payloads[name])
        for name in paths
        if name != "oos_registry"
    }
    if (
        handoff.get("pre_oos_human_approval_ref") != refs["approval"]
        or intent.get("approval_ref") != refs["approval"]
        or intent.get("handoff_ref") != refs["handoff"]
        or handoff.get("formal_transfer_use_orchestration_ref")
        != refs["formal_orchestration"]
        or intent.get("formal_transfer_use_orchestration_ref")
        != refs["formal_orchestration"]
        or approval.get("evidence_bindings", {}).get(
            "formal_transfer_use_orchestration_ref"
        )
        != refs["formal_orchestration"]
        or approval.get("evidence_bindings", {}).get("execution_addendum_ref")
        != (refs.get("execution_addendum") if addendum is not None else None)
    ):
        raise PublicChildMaterializationTicketError(
            [_token("pre_oos_exact_ref_projection")]
        )
    allocation_ref = str(signed_intent.get("oos_allocation_ref") or "")
    allocation_id = str(signed_intent.get("oos_allocation_id") or "")
    if (
        signed_intent.get("child_report_id") != child_report_id
        or signed_intent.get("oos_allocation_sha256")
        != refs["oos_allocation"]["sha256"]
        or signed_intent.get("oos_allocation_ref") != refs["oos_allocation"]["path"]
    ):
        raise PublicChildMaterializationTicketError([_token("fresh_oos_projection")])
    registry_prefix = signed_intent.get("oos_registry_prefix_ref")
    prefix_reasons = validate_oos_registry_allocation_prefix(
        registry_prefix,
        root=root,
        allocation_id=allocation_id,
        report_id=child_report_id,
    )
    if prefix_reasons:
        raise PublicChildMaterializationTicketError(
            [_token(f"fresh_oos_prefix:{reason}") for reason in prefix_reasons]
        )
    refs["oos_registry_prefix"] = dict(registry_prefix)
    oos_reasons = validate_fresh_child_oos_allocation_structural(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        allocation_id=allocation_id,
        allocation_ref=allocation_ref,
    )
    if oos_reasons:
        raise PublicChildMaterializationTicketError(
            [_token(f"fresh_oos:{reason}") for reason in oos_reasons]
        )
    return {
        "approval": approval,
        "handoff": handoff,
        "child_intent": intent,
        "formal_orchestration": orchestration,
        "execution_addendum": addendum,
        "memory_state": str(memory_state),
        "lifecycle_state": str(lifecycle_state),
        "allocation_id": allocation_id,
        "frozen_daily_input_refs": frozen_daily_inputs,
    }, refs


def _expected_execution_projection(source: Mapping[str, Any]) -> tuple[int, str]:
    addendum = source.get("execution_addendum")
    tests = (
        list(addendum.get("execution_tests") or [])
        if isinstance(addendum, Mapping)
        else []
    )
    return len(tests), stable_json_hash(tests)


def _child_control_paths(root: Path, child_report_id: str) -> dict[str, Path]:
    """Resolve the canonical preregistration controls without duplicating paths."""

    from factor_factory.evo_child_preregistration import (
        child_metric_verifier_spec_path,
    )

    return {
        **child_control_paths(root, child_report_id),
        "metric_verifier_spec": child_metric_verifier_spec_path(root, child_report_id),
    }


def _control_projection(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    source: Mapping[str, Any],
    materialization_ready: bool,
    expected_host_trust_manifest_sha256: str,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    if _incident_guard is not None and (
        incident_trust_root is None or not incident_installation_id
    ):
        raise PublicChildMaterializationTicketError(
            [_token("incident_guard_context_incomplete")]
        )
    expected_count, expected_sha = _expected_execution_projection(source)
    if not materialization_ready:
        return {
            "state": TICKET_STATE_NOT_MATERIALIZED,
            "refs": None,
            "expected_execution_test_count": expected_count,
            "expected_execution_tests_sha256": expected_sha,
        }
    # READY is a Host signature over a completed preregistration transaction,
    # never an oracle for a handful of workspace files that merely resemble
    # controls.  The shared preregistration validator recomputes every target,
    # its proof-component projections, frozen lifecycle, source bindings and
    # immutable receipt from the public authorization plus the out-of-band
    # Host trust pin.
    try:
        from factor_factory.evo_child_preregistration import (
            CHILD_PREREGISTRATION_STATUS,
            EvoChildPreregistrationError,
            validate_evo_child_preregistration_receipt,
            validate_evo_child_preregistration_receipt_structural,
        )

        if incident_trust_root is not None and incident_installation_id:
            preregistration = validate_evo_child_preregistration_receipt(
                workspace_root=root,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
                incident_trust_root=incident_trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=_incident_guard,
            )
        else:
            preregistration = validate_evo_child_preregistration_receipt_structural(
                workspace_root=root,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
            )
    except (EvoChildPreregistrationError, OSError, ValueError, KeyError, TypeError) as exc:
        reasons = getattr(exc, "reasons", None)
        if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes)):
            detail = ":".join(str(item) for item in reasons[:8])
        else:
            detail = type(exc).__name__
        raise PublicChildMaterializationTicketError(
            [_token(f"child_preregistration_receipt:{detail}")]
        ) from exc
    if (
        preregistration.get("verdict") != "PASS"
        or preregistration.get("status")
        != CHILD_PREREGISTRATION_STATUS
        or preregistration.get("parent_report_id") != parent_report_id
        or preregistration.get("child_report_id") != child_report_id
        or not isinstance(preregistration.get("receipt_ref"), Mapping)
        or not isinstance(
            preregistration.get("child_web_research_plan_ref"), Mapping
        )
    ):
        raise PublicChildMaterializationTicketError(
            [_token("child_preregistration_receipt_status")]
        )
    controls = _child_control_paths(root, child_report_id)
    missing = [name for name in _CONTROL_NAMES if not controls[name].is_file()]
    if missing:
        raise PublicChildMaterializationTicketError(
            [_waiting(f"child_control_missing:{name}") for name in missing]
        )
    unsafe = [
        name
        for name in _CONTROL_NAMES
        if not _within_without_symlinks(root, controls[name])
    ]
    if unsafe:
        raise PublicChildMaterializationTicketError(
            [_token(f"child_control_path_unsafe:{name}") for name in unsafe]
        )
    payloads = {name: _load_object(controls[name]) for name in _CONTROL_NAMES}
    ledger = payloads["search_trial_ledger"]
    metric_spec = payloads["metric_verifier_spec"]
    threshold = payloads["threshold_registration"]
    if (
        ledger.get("version") != "factorforge_search_trial_ledger_v1"
        or ledger.get("search_status") != "FROZEN"
        or ledger.get("report_id") != child_report_id
        or not isinstance(ledger.get("trials"), list)
        or ledger.get("trial_count") != len(ledger.get("trials") or [])
    ):
        raise PublicChildMaterializationTicketError([_token("child_ledger_not_frozen")])
    ledger_path = controls["search_trial_ledger"]
    expected_ledger_ref = ledger_path.resolve(strict=True).relative_to(root).as_posix()
    expected_threshold_ref = (
        controls["threshold_registration"]
        .resolve(strict=True)
        .relative_to(root)
        .as_posix()
    )
    from factor_factory.research_release import (
        METRIC_THRESHOLD_REGISTRATION_VERSION,
        METRIC_VERIFIER_SPEC_VERSION,
        evaluation_contract_hash,
    )
    from factor_factory.research_release import (
        stable_hash as release_stable_hash,
    )

    try:
        window_contract = metric_spec.get("window_contract")
        if not isinstance(window_contract, Mapping):
            raise TypeError("window_contract_required")
        expected_contract_hashes = {
            "window_hash": release_stable_hash(window_contract),
            "evaluation_contract_hash": evaluation_contract_hash(metric_spec),
            "label_contract_hash": release_stable_hash(
                metric_spec.get("label_contract")
            ),
        }
    except (TypeError, ValueError) as exc:
        raise PublicChildMaterializationTicketError(
            [_token(f"child_metric_verifier_spec:{type(exc).__name__}")]
        ) from exc
    if (
        metric_spec.get("version") != METRIC_VERIFIER_SPEC_VERSION
        or metric_spec.get("verification_scope") != "production"
        or metric_spec.get("report_id") != child_report_id
        or metric_spec.get("factor_id") != ledger.get("factor_id")
        or window_contract.get("search_trial_ledger_ref") != expected_ledger_ref
        or metric_spec.get("threshold_registration_ref") != expected_threshold_ref
        or metric_spec.get("window_hash") != expected_contract_hashes["window_hash"]
        or threshold.get("version") != METRIC_THRESHOLD_REGISTRATION_VERSION
        or threshold.get("registration_status") != "LOCKED"
        or threshold.get("report_id") != child_report_id
        or threshold.get("factor_id") != metric_spec.get("factor_id")
        or threshold.get("claim_class") != metric_spec.get("claim_class")
        or threshold.get("verification_scope") != "production"
        or threshold.get("registered_before_evaluation") is not True
        or threshold.get("search_trial_ledger_ref") != expected_ledger_ref
        or threshold.get("search_trial_ledger_sha256") != sha256_file(ledger_path)
    ):
        raise PublicChildMaterializationTicketError(
            [_token("child_threshold_ledger_binding")]
        )
    if any(
        threshold.get(field) != expected
        for field, expected in expected_contract_hashes.items()
    ):
        raise PublicChildMaterializationTicketError(
            [_token("child_threshold_contract_hash_binding")]
        )
    # The shared child-ledger validator is the sole authority for deciding that
    # found-branch addendum tests (or the cold zero-test projection) are exact.
    try:
        from factor_factory.evo_child_execution import (
            validate_frozen_child_execution_ledger,
        )
    except ImportError as exc:
        raise PublicChildMaterializationTicketError(
            [_token("shared_child_ledger_validator_unavailable")]
        ) from exc
    ledger_reasons = validate_frozen_child_execution_ledger(
        workspace_root=root,
        parent_report_id=str(source["formal_orchestration"]["report_id"]),
        child_report_id=child_report_id,
        search_trial_ledger=ledger,
        execution_addendum=source.get("execution_addendum"),
    )
    if ledger_reasons:
        raise PublicChildMaterializationTicketError(
            [_token(f"child_ledger:{reason}") for reason in ledger_reasons]
        )
    return {
        "state": TICKET_STATE_READY,
        "preregistration_receipt_ref": dict(
            preregistration["receipt_ref"]
        ),
        "child_web_research_plan_ref": dict(
            preregistration["child_web_research_plan_ref"]
        ),
        "frozen_artifact_count": preregistration["frozen_artifact_count"],
        "refs": {
            name: _object_ref(root, controls[name], payloads[name])
            for name in _CONTROL_NAMES
        },
        "expected_execution_test_count": expected_count,
        "expected_execution_tests_sha256": expected_sha,
    }


def _authority(*, materialization_ready: bool) -> dict[str, Any]:
    return {
        "scope": "CONTROLLED_CHILD_INPUT_MATERIALIZATION_ONLY",
        "host_attested": True,
        "materialization_ready": materialization_ready,
        "child_inputs_materialization_allowed": materialization_ready,
        "child_execution_allowed": False,
        "oos_release_allowed": False,
        "oos_consumption_allowed": False,
        "factor_verdict": "NOT_ISSUED",
        "canonical_write_allowed": False,
        "skill_or_policy_mutation_allowed": False,
    }


def _ticket_core(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    source: Mapping[str, Any],
    refs: Mapping[str, Mapping[str, str]],
    trust_manifest_ref: Mapping[str, str],
    trust_manifest: Mapping[str, Any],
    materialization_ready: bool,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    handoff = source["handoff"]
    selected = handoff.get("selected_revision")
    selected = selected if isinstance(selected, Mapping) else {}
    state = (
        TICKET_STATE_READY if materialization_ready else TICKET_STATE_NOT_MATERIALIZED
    )
    core = {
        "receipt_type": PUBLIC_CHILD_MATERIALIZATION_TICKET_RECEIPT_TYPE,
        "ticket_contract_version": PUBLIC_CHILD_MATERIALIZATION_TICKET_VERSION,
        "ticket_state": state,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "run_id": handoff.get("parent_run_id"),
        "lifecycle_state": source["lifecycle_state"],
        "memory_state": source["memory_state"],
        "trust_manifest_sha256": trust_manifest.get("manifest_sha256"),
        "trust_manifest_ref": dict(trust_manifest_ref),
        "selected_revision": {
            "law_id": selected.get("law_id"),
            "delta_id": selected.get("delta_id"),
            "child_formula_hash": selected.get("child_formula_hash"),
            "projection_sha256": stable_json_hash(dict(selected)),
        },
        "bindings": {
            "approval_ref": dict(refs["approval"]),
            "handoff_ref": dict(refs["handoff"]),
            "child_intent_ref": dict(refs["child_intent"]),
            "formal_transfer_use_orchestration_ref": dict(refs["formal_orchestration"]),
            "execution_addendum_ref": (
                dict(refs["execution_addendum"])
                if "execution_addendum" in refs
                else None
            ),
            "oos_allocation_id": source["allocation_id"],
            "oos_allocation_ref": dict(refs["oos_allocation"]),
            "oos_registry_prefix_ref": dict(refs["oos_registry_prefix"]),
            "parent_data_prep_ref": dict(refs["parent_data_prep"]),
            "frozen_daily_input_refs": {
                key: dict(source["frozen_daily_input_refs"][key])
                for key in sorted(source["frozen_daily_input_refs"])
            },
            "child_controls": _control_projection(
                root=root,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                source=source,
                materialization_ready=materialization_ready,
                expected_host_trust_manifest_sha256=str(
                    trust_manifest.get("manifest_sha256") or ""
                ),
                incident_trust_root=incident_trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=_incident_guard,
            ),
        },
        "authority": _authority(materialization_ready=materialization_ready),
    }
    return {**core, "ticket_content_sha256": stable_json_hash(core)}


def _cleanup_temporaries(path: Path, *, exact_target: bool) -> None:
    prefix = f".{path.name}."
    for candidate in path.parent.iterdir():
        if not candidate.name.startswith(prefix) or not candidate.name.endswith(".tmp"):
            continue
        metadata = candidate.lstat()
        linked_exact = (
            exact_target and metadata.st_nlink == 2 and candidate.samefile(path)
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or (metadata.st_nlink != 1 and not linked_exact)
        ):
            raise PublicChildMaterializationTicketError(
                [_token(f"unsafe_ticket_temporary:{candidate.name}")]
            )
        candidate.unlink()


def _safe_output_parent(root: Path, path: Path) -> Path:
    resolved_root = root.resolve(strict=True)
    try:
        relative = path.relative_to(resolved_root)
    except ValueError as exc:
        raise PublicChildMaterializationTicketError(
            [_token("ticket_output_outside_workspace")]
        ) from exc
    current = resolved_root
    for part in relative.parent.parts:
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if current.is_symlink() or not current.is_dir():
            raise PublicChildMaterializationTicketError(
                [_token("ticket_output_parent_unsafe")]
            )
        try:
            current.resolve(strict=True).relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise PublicChildMaterializationTicketError(
                [_token("ticket_output_parent_unsafe")]
            ) from exc
    return current


def _atomic_write_once(
    root: Path,
    path: Path,
    payload: Mapping[str, Any],
) -> bool:
    expected = canonical_json_bytes(payload)
    parent = _safe_output_parent(root, path)
    if parent != path.parent or not _within_without_symlinks(root, path):
        raise PublicChildMaterializationTicketError([_token("ticket_output_path")])
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise PublicChildMaterializationTicketError(
            [_token(f"ticket_path_unsafe:{path.name}")]
        )
    if path.is_file():
        exact = not path.is_symlink() and path.read_bytes() == expected
        _cleanup_temporaries(path, exact_target=exact)
        if not exact:
            raise PublicChildMaterializationTicketError(
                [_token(f"immutable_ticket_conflict:{path.name}")]
            )
        return True
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    os.fchmod(descriptor, 0o600)
    try:
        offset = 0
        while offset < len(expected):
            written = os.write(descriptor, expected[offset:])
            if written <= 0:
                raise OSError("ticket_atomic_write_no_progress")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
                raise PublicChildMaterializationTicketError(
                    [_token(f"immutable_ticket_conflict:{path.name}")]
                )
            return True
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return False
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


@contextmanager
def _ticket_lock(root: Path, child_report_id: str) -> Iterator[None]:
    path = public_child_materialization_ticket_path(
        root,
        child_report_id,
        materialization_ready=False,
    ).with_suffix(".lock")
    parent = _safe_output_parent(root, path)
    if parent != path.parent or not _within_without_symlinks(root, path):
        raise PublicChildMaterializationTicketError([_token("ticket_lock_path")])
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PublicChildMaterializationTicketError([_token("ticket_lock")])
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _trust_store(
    *,
    root: Path,
    parent_report_id: str,
    trust_root: Path,
    installation_id: str,
) -> tuple[Any, dict[str, Any]]:
    private = trust_root.expanduser().resolve(strict=True)
    if private == root or private in root.parents or root in private.parents:
        raise PublicChildMaterializationTicketError([_token("trust_root_overlap")])
    store = load_runtime_trust_store(private, installation_id=installation_id)
    manifest = workspace_runtime_trust_manifest(root, report_id=parent_report_id)
    if (
        manifest is None
        or validate_public_trust_manifest(manifest)
        or manifest != store.public_manifest
    ):
        raise PublicChildMaterializationTicketError([_token("workspace_trust_pin")])
    return store, manifest


def materialize_public_child_materialization_ticket(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    trust_root: Path | str,
    installation_id: str,
    admissions_root: Path | str | None = None,
    materialization_ready: bool = False,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    private_trust = Path(trust_root).expanduser().resolve(strict=True)
    if _incident_guard is None:
        with oos_exposure_private_registry_guard(
            private_trust,
            installation_id=installation_id,
        ) as guard:
            return materialize_public_child_materialization_ticket(
                workspace_root=root,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                trust_root=private_trust,
                installation_id=installation_id,
                admissions_root=admissions_root,
                materialization_ready=materialization_ready,
                _incident_guard=guard,
            )
    validate_oos_exposure_private_registry_guard(
        _incident_guard,
        trust_root=private_trust,
        installation_id=installation_id,
    )
    if (
        not _safe_id(parent_report_id)
        or not _safe_id(child_report_id)
        or parent_report_id == child_report_id
    ):
        raise PublicChildMaterializationTicketError([_token("report_identity")])
    store, manifest = _trust_store(
        root=root,
        parent_report_id=parent_report_id,
        trust_root=private_trust,
        installation_id=installation_id,
    )
    with _ticket_lock(root, child_report_id):
        trust_manifest_path = public_child_materialization_trust_manifest_path(root)
        _atomic_write_once(root, trust_manifest_path, manifest)
        trust_manifest_ref = _object_ref(root, trust_manifest_path, manifest)
        # Signing is Host-only, but possession of a Host key must not let a
        # caller skip the private human/transfer/admission replay performed by
        # the bridge. Import lazily to avoid a module cycle at import time.
        from factor_factory.pre_oos_human_bridge import (
            validate_pre_oos_child_handoff,
        )

        validated_handoff, handoff_reasons = validate_pre_oos_child_handoff(
            workspace_root=root,
            parent_report_id=parent_report_id,
            require_materialization_ready=False,
            host_trust_root=trust_root,
            installation_id=installation_id,
            admissions_root=admissions_root,
            incident_trust_root=private_trust,
            incident_installation_id=installation_id,
            _incident_guard=_incident_guard,
        )
        if validated_handoff is None or handoff_reasons:
            raise PublicChildMaterializationTicketError(
                [
                    _token(f"private_bridge_replay:{reason}")
                    for reason in handoff_reasons
                ]
            )
        if validated_handoff.get("child_report_id") != child_report_id:
            raise PublicChildMaterializationTicketError(
                [_token("private_bridge_child_identity")]
            )
        source, refs = _source_artifacts(root, parent_report_id, child_report_id)
        reasons = _verify_public_orchestration(
            root=root,
            parent_report_id=parent_report_id,
            orchestration=source["formal_orchestration"],
            trust_manifest=manifest,
        )
        if isinstance(source.get("execution_addendum"), Mapping):
            reasons.extend(
                _verify_public_addendum(
                    parent_report_id=parent_report_id,
                    addendum=source["execution_addendum"],
                    trust_manifest=manifest,
                )
            )
        if reasons:
            raise PublicChildMaterializationTicketError(reasons)
        core = _ticket_core(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            source=source,
            refs=refs,
            trust_manifest_ref=trust_manifest_ref,
            trust_manifest=manifest,
            materialization_ready=materialization_ready,
            incident_trust_root=trust_root,
            incident_installation_id=installation_id,
            _incident_guard=_incident_guard,
        )
        ticket = store.sign("host_admission", core)
        path = public_child_materialization_ticket_path(
            root,
            child_report_id,
            materialization_ready=materialization_ready,
        )
        if not _within_without_symlinks(root, path):
            raise PublicChildMaterializationTicketError([_token("ticket_output_path")])
        replayed = _atomic_write_once(root, path, ticket)
        validated, validation_reasons = validate_public_child_materialization_ticket(
            workspace_root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            require_materialization_ready=materialization_ready,
            exact_ticket_path=path,
            expected_host_trust_manifest_sha256=str(manifest["manifest_sha256"]),
            incident_trust_root=trust_root,
            incident_installation_id=installation_id,
            _incident_guard=_incident_guard,
        )
        if validated is None or validation_reasons:
            raise PublicChildMaterializationTicketError(validation_reasons)
        return {
            "verdict": "PASS",
            "status": ticket["ticket_state"],
            "ticket_ref": _object_ref(root, path, ticket),
            "expected_host_trust_manifest_sha256": manifest["manifest_sha256"],
            "idempotent_replay": replayed,
            "authority": dict(ticket["authority"]),
        }


def validate_public_child_materialization_ticket(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    require_materialization_ready: bool = False,
    handoff: Mapping[str, Any] | None = None,
    exact_ticket_path: Path | None = None,
    expected_host_trust_manifest_sha256: str | None = None,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    if bool(incident_trust_root is not None) != bool(incident_installation_id):
        return None, [_token("incident_host_context_incomplete")]
    if incident_trust_root is not None and incident_installation_id:
        private_trust = Path(incident_trust_root).expanduser().resolve(strict=True)
        if _incident_guard is None:
            with oos_exposure_private_registry_guard(
                private_trust,
                installation_id=incident_installation_id,
            ) as guard:
                return validate_public_child_materialization_ticket(
                    workspace_root=workspace_root,
                    parent_report_id=parent_report_id,
                    child_report_id=child_report_id,
                    require_materialization_ready=require_materialization_ready,
                    handoff=handoff,
                    exact_ticket_path=exact_ticket_path,
                    expected_host_trust_manifest_sha256=(
                        expected_host_trust_manifest_sha256
                    ),
                    incident_trust_root=private_trust,
                    incident_installation_id=incident_installation_id,
                    _incident_guard=guard,
                )
        validate_oos_exposure_private_registry_guard(
            _incident_guard,
            trust_root=private_trust,
            installation_id=incident_installation_id,
        )
    try:
        root = Path(workspace_root).expanduser().resolve(strict=True)
        ready_path = public_child_materialization_ticket_path(
            root, child_report_id, materialization_ready=True
        )
        authorization_path = public_child_materialization_ticket_path(
            root, child_report_id, materialization_ready=False
        )
        path = (
            exact_ticket_path
            if exact_ticket_path is not None
            else ready_path
            if ready_path.is_file()
            else authorization_path
        )
        if not _is_sha256(expected_host_trust_manifest_sha256):
            return None, [_token("external_host_trust_pin_required")]
        if path.resolve(strict=False) not in {
            ready_path.resolve(strict=False),
            authorization_path.resolve(strict=False),
        }:
            return None, [_token("ticket_path_not_canonical")]
        if not _within_without_symlinks(root, path):
            return None, [_token("ticket_path_unsafe")]
        if require_materialization_ready and path.resolve(strict=False) != ready_path:
            return None, [_waiting("ready_ticket_missing")]
        ticket = _load_object(path, canonical=True)
        manifest = workspace_runtime_trust_manifest(root, report_id=parent_report_id)
        trust_path = public_child_materialization_trust_manifest_path(root)
        trust_payload = _load_object(trust_path, canonical=True)
        trust_ref = _object_ref(root, trust_path, trust_payload)
        if (
            manifest is None
            or validate_public_trust_manifest(manifest)
            or trust_payload != manifest
            or manifest.get("manifest_sha256") != expected_host_trust_manifest_sha256
        ):
            return None, [_token("workspace_trust_manifest")]
        reasons = [
            _token(f"ticket_signature:{reason}")
            for reason in verify_signed_receipt_with_manifest(
                ticket,
                trust_manifest=manifest,
                expected_issuer="host_admission",
            )
        ]
        fields = {
            "contract_version",
            "issuer",
            "receipt_type",
            "ticket_contract_version",
            "ticket_state",
            "parent_report_id",
            "child_report_id",
            "run_id",
            "lifecycle_state",
            "memory_state",
            "trust_manifest_sha256",
            "trust_manifest_ref",
            "selected_revision",
            "bindings",
            "authority",
            "ticket_content_sha256",
            "receipt_id",
            "signature",
        }
        core = {
            key: value
            for key, value in ticket.items()
            if key not in {"contract_version", "issuer", "receipt_id", "signature"}
        }
        expected_state = (
            TICKET_STATE_READY
            if path.resolve(strict=False) == ready_path
            else TICKET_STATE_NOT_MATERIALIZED
        )
        if (
            set(ticket) != fields
            or ticket.get("receipt_type")
            != PUBLIC_CHILD_MATERIALIZATION_TICKET_RECEIPT_TYPE
            or ticket.get("ticket_contract_version")
            != PUBLIC_CHILD_MATERIALIZATION_TICKET_VERSION
            or ticket.get("ticket_state") != expected_state
            or ticket.get("parent_report_id") != parent_report_id
            or ticket.get("child_report_id") != child_report_id
            or ticket.get("trust_manifest_sha256") != manifest.get("manifest_sha256")
            or ticket.get("trust_manifest_ref") != trust_ref
            or ticket.get("ticket_content_sha256")
            != stable_json_hash(
                {
                    key: value
                    for key, value in core.items()
                    if key != "ticket_content_sha256"
                }
            )
        ):
            reasons.append(_token("ticket_shape_or_identity"))
        source, refs = _source_artifacts(root, parent_report_id, child_report_id)
        reasons.extend(
            _verify_public_orchestration(
                root=root,
                parent_report_id=parent_report_id,
                orchestration=source["formal_orchestration"],
                trust_manifest=manifest,
            )
        )
        addendum = source.get("execution_addendum")
        if isinstance(addendum, Mapping):
            reasons.extend(
                _verify_public_addendum(
                    parent_report_id=parent_report_id,
                    addendum=addendum,
                    trust_manifest=manifest,
                )
            )
        expected_core = _ticket_core(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            source=source,
            refs=refs,
            trust_manifest_ref=trust_ref,
            trust_manifest=manifest,
            materialization_ready=expected_state == TICKET_STATE_READY,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
        signed_core = {
            key: value
            for key, value in ticket.items()
            if key not in {"contract_version", "issuer", "receipt_id", "signature"}
        }
        if signed_core != expected_core:
            reasons.append(_token("ticket_exact_projection"))
        canonical_handoff = source["handoff"]
        if handoff is not None and dict(handoff) != canonical_handoff:
            reasons.append(_token("supplied_handoff_mismatch"))
        materialization_ready = expected_state == TICKET_STATE_READY
        if ticket.get("authority") != _authority(
            materialization_ready=materialization_ready
        ):
            reasons.append(_token("ticket_authority"))
        if require_materialization_ready and not materialization_ready:
            reasons.append(_waiting("not_materialized_ticket"))
        return (ticket if not reasons else None), list(dict.fromkeys(reasons))
    except PublicChildMaterializationTicketError as exc:
        return None, exc.reasons
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, [_token(f"unexpected:{type(exc).__name__}")]


__all__ = [
    "BLOCK_PUBLIC_CHILD_MATERIALIZATION_TICKET",
    "PUBLIC_CHILD_MATERIALIZATION_TICKET_VERSION",
    "TICKET_STATE_NOT_MATERIALIZED",
    "TICKET_STATE_READY",
    "WAITING_PUBLIC_CHILD_MATERIALIZATION_TICKET",
    "PublicChildMaterializationTicketError",
    "materialize_public_child_materialization_ticket",
    "public_child_materialization_ticket_path",
    "public_child_materialization_trust_manifest_path",
    "validate_public_child_materialization_ticket",
]
