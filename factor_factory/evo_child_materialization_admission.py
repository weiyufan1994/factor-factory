from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from factor_factory.child_materialization import validate_child_materialization_readback
from factor_factory.console.web_research_plan import (
    WebResearchPlanError,
    validate_materialized_web_research,
)
from factor_factory.evo_child_materialization_ticket import (
    public_child_materialization_ticket_path,
    validate_public_child_materialization_ticket,
)
from factor_factory.evo_child_preregistration import (
    child_preregistration_receipt_path,
    validate_evo_child_preregistration_receipt,
)
from factor_factory.evo_v2 import canonical_json_bytes, sha256_file
from factor_factory.pre_oos_human_bridge import pre_oos_child_handoff_path
from factor_factory.research_conjecture import workspace_runtime_trust_manifest
from factor_factory.research_org.runtime_trust import (
    load_runtime_trust_store,
    validate_public_trust_manifest,
    verify_signed_receipt_with_manifest,
)
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
    validate_oos_exposure_private_registry_guard,
)

ADMISSION_VERSION = "factorforge_evo_child_materialization_admission_v1"
ADMISSION_RECEIPT_TYPE = "EVO_CHILD_MATERIALIZATION_HOST_ADMISSION"
BLOCK_CHILD_MATERIALIZATION_ADMISSION = (
    "BLOCK_FACTORFORGE_EVO_CHILD_MATERIALIZATION_ADMISSION_INVALID"
)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,191}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class EvoChildMaterializationAdmissionError(ValueError):
    def __init__(self, reasons: list[str]):
        self.reasons = list(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _token(reason: str) -> str:
    return f"{BLOCK_CHILD_MATERIALIZATION_ADMISSION}:{reason}"


def _safe_id(value: Any) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvoChildMaterializationAdmissionError([_token("invalid_json")]) from exc
    if not isinstance(payload, dict):
        raise EvoChildMaterializationAdmissionError([_token("object_required")])
    return payload


def _ref(root: Path, path: Path, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    reference = {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
    }
    if payload is not None and isinstance(payload.get("content_sha256"), str):
        reference["content_sha256"] = payload["content_sha256"]
    return reference


def child_materialization_report_path(
    root: Path, parent_report_id: str, child_report_id: str
) -> Path:
    digest = hashlib.sha256(
        f"{parent_report_id}\0{child_report_id}".encode()
    ).hexdigest()[:16]
    filename = (
        "child_revision_materialization__"
        f"{parent_report_id[:40].rstrip('_')}__"
        f"{child_report_id[:40].rstrip('_')}__{digest}.json"
    )
    return root / "objects" / "runtime_context" / filename


def child_materialization_admission_path(root: Path, child_report_id: str) -> Path:
    if not _safe_id(child_report_id):
        raise EvoChildMaterializationAdmissionError([_token("child_report_id")])
    return (
        root
        / "objects"
        / "runtime_context"
        / f"evo_child_materialization_admission__{child_report_id}.json"
    )


def _safe_output_parent(root: Path, path: Path) -> None:
    resolved_root = root.resolve(strict=True)
    try:
        relative = path.relative_to(resolved_root)
    except ValueError as exc:
        raise EvoChildMaterializationAdmissionError([_token("output_escape")]) from exc
    current = resolved_root
    for part in relative.parent.parts:
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if current.is_symlink() or not current.is_dir():
            raise EvoChildMaterializationAdmissionError([_token("output_parent")])
        try:
            current.resolve(strict=True).relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise EvoChildMaterializationAdmissionError([_token("output_parent")]) from exc


def _write_once(root: Path, path: Path, payload: Mapping[str, Any]) -> bool:
    _safe_output_parent(root, path)
    expected = canonical_json_bytes(payload)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise EvoChildMaterializationAdmissionError([_token("output_unsafe")])
    if path.is_file():
        if path.read_bytes() != expected:
            raise EvoChildMaterializationAdmissionError([_token("immutable_conflict")])
        return True
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(expected):
            written = os.write(descriptor, expected[offset:])
            if written <= 0:
                raise OSError("materialization_admission_write_no_progress")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
                raise EvoChildMaterializationAdmissionError([_token("immutable_conflict")])
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


def _canonical_target_map(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    ready: Mapping[str, Any],
) -> dict[str, str]:
    """Return the complete code-owned target map for a formal child materialization.

    The materializer report is intentionally not an authority for either the target
    set or target paths.  In particular, a workspace writer must not be able to
    omit a target (or substitute another workspace path), rewrite the report and
    staging manifest consistently, and then have the Host countersign that state.
    """

    expected: dict[str, Path] = {
        "alpha_idea_master": root
        / "objects"
        / "alpha_idea_master"
        / f"alpha_idea_master__{child_report_id}.json",
        "factor_spec_master": root
        / "objects"
        / "factor_spec_master"
        / f"factor_spec_master__{child_report_id}.json",
        "data_prep_master": root
        / "objects"
        / "data_prep_master"
        / f"data_prep_master__{child_report_id}.json",
        "executable_revision_spec": root
        / "objects"
        / "research_iteration_master"
        / f"executable_revision_spec__{child_report_id}.json",
        "handoff_to_step4": root
        / "objects"
        / "handoff"
        / f"handoff_to_step4__{child_report_id}.json",
        "qlib_adapter_config": root
        / "objects"
        / "data_prep_master"
        / f"qlib_adapter_config__{child_report_id}.json",
        "state_dependency_contract": root
        / "objects"
        / "data_prep_master"
        / child_report_id
        / f"state_dependency_contract__{child_report_id}.json",
        "state_resolution": root
        / "objects"
        / "data_prep_master"
        / child_report_id
        / f"state_resolution__{child_report_id}.json",
    }
    parent_handoff_to_step3 = (
        root
        / "objects"
        / "handoff"
        / f"handoff_to_step3__{parent_report_id}.json"
    )
    if parent_handoff_to_step3.is_file() and not parent_handoff_to_step3.is_symlink():
        expected["handoff_to_step3"] = (
            root
            / "objects"
            / "handoff"
            / f"handoff_to_step3__{child_report_id}.json"
        )

    bindings = ready.get("bindings")
    frozen = (
        bindings.get("frozen_daily_input_refs")
        if isinstance(bindings, Mapping)
        else None
    )
    if not isinstance(frozen, Mapping):
        raise EvoChildMaterializationAdmissionError(
            [_token("ready_frozen_daily_input_refs")]
        )
    supported_daily = {
        "daily_df_parquet",
        "daily_df_csv",
        "evaluation_daily_df_parquet",
        "evaluation_daily_df_csv",
        "signal_daily_df_parquet",
        "signal_daily_df_csv",
    }
    for source_key in sorted(supported_daily.intersection(frozen)):
        suffix = "parquet" if source_key.endswith("_parquet") else "csv"
        prefix = source_key.removesuffix("_parquet").removesuffix("_csv")
        expected[f"child_daily_input_{source_key}"] = (
            root
            / "runs"
            / child_report_id
            / "step3a_local_inputs"
            / f"daily_input__{child_report_id}.{prefix}.{suffix}"
        )
    if "daily_input_meta_json" in frozen:
        expected["child_daily_input_meta_json"] = (
            root
            / "runs"
            / child_report_id
            / "step3a_local_inputs"
            / f"daily_input_meta__{child_report_id}.json"
        )
    return {
        kind: path.relative_to(root).as_posix()
        for kind, path in sorted(expected.items())
    }


def _exact_target_reasons(
    *,
    report: Mapping[str, Any],
    expected: Mapping[str, str],
) -> list[str]:
    rows = report.get("materialization_target_hashes")
    if not isinstance(rows, list):
        return [_token("target_hashes")]
    observed: dict[str, str] = {}
    reasons: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            reasons.append(_token(f"target[{index}].shape"))
            continue
        kind = row.get("kind")
        path = row.get("path")
        if not isinstance(kind, str) or not isinstance(path, str) or kind in observed:
            reasons.append(_token(f"target[{index}].identity"))
            continue
        observed[kind] = path
    if set(observed) != set(expected):
        reasons.append(_token("target_set_exact"))
    for kind, path in expected.items():
        if observed.get(kind) != path:
            reasons.append(_token(f"target_path:{kind}"))
    return reasons


def _validated_materialization(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    if (
        not _safe_id(parent_report_id)
        or not _safe_id(child_report_id)
        or parent_report_id == child_report_id
        or _HEX.fullmatch(expected_host_trust_manifest_sha256 or "") is None
    ):
        raise EvoChildMaterializationAdmissionError([_token("identity_or_pin")])
    ready_path = public_child_materialization_ticket_path(
        root, child_report_id, materialization_ready=True
    )
    ready, ready_reasons = validate_public_child_materialization_ticket(
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        require_materialization_ready=True,
        exact_ticket_path=ready_path,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    if ready is None or ready_reasons:
        raise EvoChildMaterializationAdmissionError(
            [_token(f"ready_ticket:{reason}") for reason in ready_reasons]
            or [_token("ready_ticket")]
        )
    prereg = validate_evo_child_preregistration_receipt(
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    report_path = child_materialization_report_path(
        root, parent_report_id, child_report_id
    )
    report = _load(report_path)
    try:
        validate_materialized_web_research(
            root,
            report_id=child_report_id,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
            incident_trust_root=(
                Path(incident_trust_root)
                if incident_trust_root is not None
                else None
            ),
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
            current_authority=True,
        )
    except WebResearchPlanError as exc:
        raise EvoChildMaterializationAdmissionError(
            [_token(f"web_semantics:{reason}") for reason in exc.reasons]
        ) from exc
    handoff_path = pre_oos_child_handoff_path(root, parent_report_id)
    expected_targets = _canonical_target_map(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        ready=ready,
    )
    exact_target_reasons = _exact_target_reasons(
        report=report,
        expected=expected_targets,
    )
    if exact_target_reasons:
        raise EvoChildMaterializationAdmissionError(exact_target_reasons)
    readback_reasons = validate_child_materialization_readback(
        workspace_root=root,
        report_path=report_path,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        source_handoff_sha256=sha256_file(handoff_path),
        required_target_kinds=set(expected_targets),
    )
    if readback_reasons:
        raise EvoChildMaterializationAdmissionError(
            [_token(f"readback:{reason}") for reason in readback_reasons]
        )
    targets = report.get("materialization_target_hashes")
    if not isinstance(targets, list) or not targets:
        raise EvoChildMaterializationAdmissionError([_token("target_hashes")])
    return {
        "ready": ready,
        "ready_path": ready_path,
        "prereg": prereg,
        "prereg_path": child_preregistration_receipt_path(root, child_report_id),
        "handoff_path": handoff_path,
        "report": report,
        "report_path": report_path,
        "targets": targets,
    }


def _admission_core(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    material: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "receipt_type": ADMISSION_RECEIPT_TYPE,
        "admission_contract_version": ADMISSION_VERSION,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "trust_manifest_sha256": expected_host_trust_manifest_sha256,
        "ready_ticket_ref": _ref(root, material["ready_path"], material["ready"]),
        "preregistration_receipt_ref": dict(material["prereg"]["receipt_ref"]),
        "parent_handoff_ref": _ref(root, material["handoff_path"]),
        "materialization_report_ref": _ref(root, material["report_path"]),
        "materialization_target_hashes": list(material["targets"]),
        "authority": {
            "scope": "HOST_ADMIT_EXACT_CHILD_MATERIALIZATION_ONLY",
            "child_execution_allowed": True,
            "child_execution_start_step": "3b",
            "oos_release_allowed": False,
            "factor_verdict": "NOT_ISSUED",
            "human_approval_granted_by_this_receipt": False,
            "semantic_authorship_granted_by_this_receipt": False,
            "canonical_factor_write_allowed": False,
            "skill_or_policy_mutation_allowed": False,
        },
    }


def materialize_evo_child_materialization_admission(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    trust_root: Path | str,
    installation_id: str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    private = Path(trust_root).expanduser().resolve(strict=True)
    if private == root or private in root.parents or root in private.parents:
        raise EvoChildMaterializationAdmissionError([_token("trust_root_overlap")])
    store = load_runtime_trust_store(private, installation_id=installation_id)
    manifest = workspace_runtime_trust_manifest(root, report_id=parent_report_id)
    if (
        manifest is None
        or validate_public_trust_manifest(manifest)
        or manifest != store.public_manifest
        or manifest.get("manifest_sha256") != expected_host_trust_manifest_sha256
    ):
        raise EvoChildMaterializationAdmissionError([_token("trust_manifest_pin")])
    with oos_exposure_private_registry_guard(
        private,
        installation_id=installation_id,
    ) as incident_guard:
        material = _validated_materialization(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
            incident_trust_root=private,
            incident_installation_id=installation_id,
            _incident_guard=incident_guard,
        )
        admission = store.sign(
            "host_admission",
            _admission_core(
                root=root,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
                material=material,
            ),
        )
        path = child_materialization_admission_path(root, child_report_id)
        replayed = _write_once(root, path, admission)
        validated, reasons = validate_evo_child_materialization_admission(
            workspace_root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
            incident_trust_root=private,
            incident_installation_id=installation_id,
            _incident_guard=incident_guard,
        )
    if validated is None or reasons:
        raise EvoChildMaterializationAdmissionError(reasons)
    return {
        "verdict": "PASS",
        "status": "HOST_ADMITTED_EXACT_CHILD_MATERIALIZATION",
        "admission_ref": _ref(root, path),
        "expected_host_trust_manifest_sha256": expected_host_trust_manifest_sha256,
        "idempotent_replay": replayed,
        "authority": dict(admission["authority"]),
    }


def validate_evo_child_materialization_admission(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    if incident_trust_root is None and incident_installation_id is None:
        return None, [_token("incident_host_context_required")]
    if bool(incident_trust_root is not None) != bool(incident_installation_id):
        return None, [_token("incident_host_context_incomplete")]
    if incident_trust_root is not None and incident_installation_id:
        try:
            private_trust = Path(incident_trust_root).expanduser().resolve(strict=True)
        except (OSError, ValueError):
            return None, [_token("incident_host_context_invalid")]
        if _incident_guard is None:
            try:
                with oos_exposure_private_registry_guard(
                    private_trust,
                    installation_id=incident_installation_id,
                ) as guard:
                    return validate_evo_child_materialization_admission(
                        workspace_root=workspace_root,
                        parent_report_id=parent_report_id,
                        child_report_id=child_report_id,
                        expected_host_trust_manifest_sha256=(
                            expected_host_trust_manifest_sha256
                        ),
                        incident_trust_root=private_trust,
                        incident_installation_id=incident_installation_id,
                        _incident_guard=guard,
                    )
            except (OSError, ValueError) as exc:
                return None, [_token(f"incident_guard:{type(exc).__name__}")]
        try:
            validate_oos_exposure_private_registry_guard(
                _incident_guard,
                trust_root=private_trust,
                installation_id=incident_installation_id,
            )
        except (OSError, ValueError) as exc:
            return None, [_token(f"incident_guard:{type(exc).__name__}")]
    try:
        root = Path(workspace_root).expanduser().resolve(strict=True)
        manifest = workspace_runtime_trust_manifest(root, report_id=parent_report_id)
        if (
            manifest is None
            or validate_public_trust_manifest(manifest)
            or manifest.get("manifest_sha256") != expected_host_trust_manifest_sha256
        ):
            return None, [_token("trust_manifest_pin")]
        material = _validated_materialization(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
        path = child_materialization_admission_path(root, child_report_id)
        admission = _load(path)
        reasons = [
            _token(f"signature:{reason}")
            for reason in verify_signed_receipt_with_manifest(
                admission,
                trust_manifest=manifest,
                expected_issuer="host_admission",
            )
        ]
        expected_core = _admission_core(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
            material=material,
        )
        signed_core = {
            key: value
            for key, value in admission.items()
            if key not in {"contract_version", "issuer", "receipt_id", "signature"}
        }
        if signed_core != expected_core:
            reasons.append(_token("exact_projection"))
        return (admission if not reasons else None), list(dict.fromkeys(reasons))
    except EvoChildMaterializationAdmissionError as exc:
        return None, exc.reasons
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, [_token(f"unexpected:{type(exc).__name__}")]


__all__ = [
    "ADMISSION_VERSION",
    "BLOCK_CHILD_MATERIALIZATION_ADMISSION",
    "EvoChildMaterializationAdmissionError",
    "child_materialization_admission_path",
    "child_materialization_report_path",
    "materialize_evo_child_materialization_admission",
    "validate_evo_child_materialization_admission",
]
