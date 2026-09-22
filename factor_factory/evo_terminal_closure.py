from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from factor_factory.evo_oos import (
    formal_oos_incident_reasons,
    oos_allocation_path,
    oos_registry_path,
    validate_oos_registry,
    validate_oos_release_consumption,
)
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
    validate_oos_exposure_private_registry_guard,
)
from factor_factory.research_conjecture import (
    epistemic_evolution_lifecycle_path,
    epistemic_evolution_lifecycle_snapshot_path,
    validate_epistemic_evolution_lifecycle,
    workspace_runtime_trust_manifest,
)
from factor_factory.research_org.runtime_trust import (
    load_runtime_trust_store,
    validate_public_trust_manifest,
    verify_signed_receipt_with_manifest,
)
from factor_factory.research_proof import (
    factor_proof_certificate_path,
    validate_factor_proof_certificate,
)
from factor_factory.research_obligation_verifier import (
    validate_component_obligation_report,
)

TERMINAL_CLOSURE_VERSION = (
    "factorforge_evo_v2_post_oos_non_revision_terminal_closure_v2"
)
TERMINAL_CLOSURE_RECEIPT_TYPE = "EVO_V2_POST_OOS_NON_REVISION_TERMINAL_CLOSURE"
TERMINAL_CLOSURE_HOST_AUTHORITY = "ULTIMATE_HOST_SIGNED_IMMUTABLE_TERMINAL_CLOSURE"
TERMINAL_CLOSURE_AUTHORITY_SCOPE = (
    "HOST_TERMINAL_CLOSURE_ONLY_NO_REVISION_OR_MEMORY_PROMOTION_AUTHORITY"
)
BLOCK_TERMINAL_CLOSURE = "BLOCK_FACTORFORGE_EVO_V2_POST_OOS_TERMINAL_CLOSURE_INVALID"

_TERMINAL_DECISION_BY_VERDICT = {
    "ACCEPT": "promote_official",
    "REJECT": "reject",
}
_VALIDATOR_SPECS = {
    "step5": (
        "factorforge_step5_validator_current",
        "skills/factor-forge-step5/scripts/validate_step5.py",
    ),
    "step6": (
        "factorforge_step6_validator_current",
        "skills/factor-forge-step6/scripts/validate_step6.py",
    ),
}
_VALIDATOR_REPORT_FIELDS = {
    "validator_id",
    "source_sha256",
    "result",
    "return_code",
    "report_sha256",
    "error_count",
    "warning_count",
}
_REFERENCE_FIELDS = {"path", "sha256"}
_HOST_REFERENCE_FIELDS = {
    "path",
    "sha256",
    "receipt_id",
    "trust_manifest_sha256",
}
_EVIDENCE_KEYS = {
    "lifecycle_head",
    "lifecycle_snapshot",
    "oos_release_manifest",
    "oos_allocation",
    "factor_proof_certificate",
    "factor_case_master",
    "factor_evaluation",
    "factor_run_master",
    "factor_spec_master",
    "handoff_to_step6",
    "research_iteration_master",
    "factor_library_all",
    "research_knowledge_base",
    "factor_library_official",
}
_CLOSURE_FIELDS = {
    "contract_version",
    "report_id",
    "factor_id",
    "lifecycle_state",
    "execution_status",
    "formal_factor_verdict",
    "source_step6_decision",
    "step6_decision",
    "oos_consumption",
    "step_validation",
    "evidence_refs",
    "authority_guard",
    "learning_disposition",
    "host_authority",
    "host_receipt_ref",
    "content_sha256",
}
_AUTHORITY_GUARD = {
    "revision_authority": False,
    "step3b_handoff_authority": False,
    "child_law_issued": False,
    "human_approval_issued": False,
    "child_execution_allowed": False,
    "canonical_lesson_issued": False,
    "canonical_memory_write_allowed": False,
    "skill_or_validator_mutation_allowed": False,
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def terminal_closure_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "evo_v2" / report_id / "post_oos_terminal_closure.json"


def terminal_closure_receipt_path(root: Path, report_id: str) -> Path:
    return (
        root
        / "objects"
        / "evo_v2"
        / report_id
        / "post_oos_terminal_closure_host_receipt.json"
    )


def _relative(root: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()


def _resolve_reference(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if candidate != resolved_root and resolved_root not in candidate.parents:
        return None
    return candidate


def _read_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:unsafe_or_missing:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:invalid_json:{path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:json_object_required:{path}")
    return payload


def _reference(root: Path, path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if (
        (resolved != resolved_root and resolved_root not in resolved.parents)
        or path.is_symlink()
        or not path.is_file()
    ):
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:evidence_path:{path}")
    return {"path": _relative(root, resolved), "sha256": sha256_file(resolved)}


def _reference_reasons(
    root: Path,
    reference: Any,
    *,
    expected_path: Path | None = None,
) -> list[str]:
    if not isinstance(reference, dict) or set(reference) != _REFERENCE_FIELDS:
        return [f"{BLOCK_TERMINAL_CLOSURE}:evidence_reference_shape"]
    path = _resolve_reference(root, reference.get("path"))
    if (
        path is None
        or path.is_symlink()
        or not path.is_file()
        or (expected_path is not None and path != expected_path.resolve(strict=False))
    ):
        return [f"{BLOCK_TERMINAL_CLOSURE}:evidence_reference_path"]
    if reference.get("sha256") != sha256_file(path):
        return [f"{BLOCK_TERMINAL_CLOSURE}:evidence_reference_sha256"]
    return []


def _pretty_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = _pretty_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:unsafe_parent:{path.name}")
    target_exists = path.exists() or path.is_symlink()
    target_is_exact = (
        target_exists
        and not path.is_symlink()
        and path.is_file()
        and path.read_bytes() == encoded
    )
    if target_exists and not target_is_exact:
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:immutable_conflict:{path.name}")
    prefix = f".{path.name}."
    for candidate in path.parent.iterdir():
        if not (candidate.name.startswith(prefix) and candidate.name.endswith(".tmp")):
            continue
        metadata = candidate.lstat()
        linked_exact_target = (
            target_is_exact and metadata.st_nlink == 2 and candidate.samefile(path)
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or (metadata.st_nlink != 1 and not linked_exact_target)
        ):
            raise ValueError(
                f"{BLOCK_TERMINAL_CLOSURE}:unsafe_atomic_temporary:{candidate.name}"
            )
        candidate.unlink()
    if target_is_exact:
        return
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=prefix,
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_temporary)
    try:
        offset = 0
        while offset < len(encoded):
            written = os.write(descriptor, encoded[offset:])
            if written <= 0:
                raise OSError("atomic_write_made_no_progress")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != encoded:
                raise ValueError(
                    f"{BLOCK_TERMINAL_CLOSURE}:immutable_conflict:{path.name}"
                )
            return
        directory_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


@contextmanager
def _closure_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _run_step_validator(
    *,
    workspace_root: Path,
    report_id: str,
    step: str,
) -> dict[str, Any]:
    validator_id, relative_script = _VALIDATOR_SPECS[step]
    repository_root = Path(__file__).resolve().parents[1]
    script_path = repository_root / relative_script
    env = os.environ.copy()
    env.pop("FACTORFORGE_ALLOW_DIRECT_STEP", None)
    env.pop("FACTORFORGE_ALLOW_LEGACY_STEP6_HANDOFF", None)
    env["FACTORFORGE_ROOT"] = str(workspace_root)
    env["FACTORFORGE_ULTIMATE_RUN"] = "1"
    completed = subprocess.run(
        [sys.executable, str(script_path), "--report-id", report_id],
        cwd=repository_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{BLOCK_TERMINAL_CLOSURE}:{step}_validator_output_invalid"
        ) from exc
    if not isinstance(report, dict):
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:{step}_validator_output_invalid")
    errors = report.get("errors")
    warnings = report.get("warnings")
    return {
        "validator_id": validator_id,
        "source_sha256": sha256_file(script_path),
        "result": report.get("result"),
        "return_code": completed.returncode,
        "report_sha256": stable_hash(report),
        "error_count": len(errors) if isinstance(errors, list) else -1,
        "warning_count": len(warnings) if isinstance(warnings, list) else -1,
    }


def _step_validation(workspace_root: Path, report_id: str) -> dict[str, Any]:
    reports = {
        step: _run_step_validator(
            workspace_root=workspace_root,
            report_id=report_id,
            step=step,
        )
        for step in ("step5", "step6")
    }
    reasons: list[str] = []
    for step, report in reports.items():
        if not isinstance(report, dict) or set(report) != _VALIDATOR_REPORT_FIELDS:
            reasons.append(f"{BLOCK_TERMINAL_CLOSURE}:{step}_validator_shape")
            continue
        if (
            report.get("validator_id") != _VALIDATOR_SPECS[step][0]
            or report.get("return_code") != 0
            or report.get("result") not in {"PASS", "WARN"}
            or report.get("error_count") != 0
            or not isinstance(report.get("warning_count"), int)
            or report.get("warning_count") < 0
        ):
            reasons.append(f"{BLOCK_TERMINAL_CLOSURE}:{step}_validator_block")
    if reasons:
        raise ValueError(";".join(reasons))
    return reports


def _canonical_artifact_paths(
    root: Path,
    report_id: str,
    *,
    lifecycle_snapshot: Path,
    release_manifest: Path,
    formal_verdict: str,
) -> dict[str, Path | None]:
    objects = root / "objects"
    return {
        "lifecycle_head": epistemic_evolution_lifecycle_path(root, report_id),
        "lifecycle_snapshot": lifecycle_snapshot,
        "oos_release_manifest": release_manifest,
        "oos_allocation": (
            oos_allocation_path(root, report_id)
            if oos_allocation_path(root, report_id).is_file()
            else None
        ),
        "factor_proof_certificate": factor_proof_certificate_path(root, report_id),
        "factor_case_master": objects
        / "factor_case_master"
        / f"factor_case_master__{report_id}.json",
        "factor_evaluation": objects
        / "validation"
        / f"factor_evaluation__{report_id}.json",
        "factor_run_master": objects
        / "factor_run_master"
        / f"factor_run_master__{report_id}.json",
        "factor_spec_master": objects
        / "factor_spec_master"
        / f"factor_spec_master__{report_id}.json",
        "handoff_to_step6": objects / "handoff" / f"handoff_to_step6__{report_id}.json",
        "research_iteration_master": objects
        / "research_iteration_master"
        / f"research_iteration_master__{report_id}.json",
        "factor_library_all": objects
        / "factor_library_all"
        / f"factor_record__{report_id}.json",
        "research_knowledge_base": objects
        / "research_knowledge_base"
        / f"knowledge_record__{report_id}.json",
        "factor_library_official": (
            objects / "factor_library_official" / f"factor_record__{report_id}.json"
            if formal_verdict == "ACCEPT"
            else None
        ),
    }


def _oos_consumption_projection(
    *,
    root: Path,
    report_id: str,
    release_path: Path,
    incident_trust_root: Path,
    incident_installation_id: str,
    incident_guard: object,
) -> dict[str, Any]:
    reasons = validate_oos_release_consumption(
        workspace_root=root,
        report_id=report_id,
        release_manifest_path=release_path,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=incident_guard,
    )
    if reasons:
        raise ValueError(";".join(reasons))
    registry_path = oos_registry_path(root)
    if not registry_path.exists():
        if oos_allocation_path(root, report_id).exists():
            raise ValueError(
                f"{BLOCK_TERMINAL_CLOSURE}:oos_allocation_without_registry"
            )
        return {
            "mode": "IMMUTABLE_ORIGINAL_RELEASE_CHAIN",
            "allocation_id": None,
            "allocation_event_sha256": None,
            "consumption_event_sha256": None,
        }
    registry = _read_json_object(registry_path)
    registry_reasons = validate_oos_registry(registry, workspace_root=root)
    if registry_reasons:
        raise ValueError(";".join(registry_reasons))
    allocations = [
        event
        for event in registry.get("events") or []
        if isinstance(event, dict)
        and event.get("event_type") == "ALLOCATE"
        and event.get("report_id") == report_id
    ]
    if not allocations:
        if oos_allocation_path(root, report_id).exists():
            raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:oos_allocation_unregistered")
        return {
            "mode": "IMMUTABLE_ORIGINAL_RELEASE_CHAIN",
            "allocation_id": None,
            "allocation_event_sha256": None,
            "consumption_event_sha256": None,
        }
    if len(allocations) != 1:
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:oos_allocation_count")
    allocation = allocations[0]
    consumptions = [
        event
        for event in registry.get("events") or []
        if isinstance(event, dict)
        and event.get("event_type") == "CONSUME"
        and event.get("allocation_id") == allocation.get("allocation_id")
    ]
    if len(consumptions) != 1:
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:oos_consumption_count")
    return {
        "mode": "SIGNED_REGISTRY_ONE_TIME_CONSUMPTION",
        "allocation_id": allocation.get("allocation_id"),
        "allocation_event_sha256": allocation.get("event_sha256"),
        "consumption_event_sha256": consumptions[0].get("event_sha256"),
    }


def _learning_disposition(formal_verdict: str) -> dict[str, Any]:
    return {
        "mode": (
            "TERMINAL_ACCEPT_NO_REVISION"
            if formal_verdict == "ACCEPT"
            else "KILL_AND_LEARN_HISTORICAL_EPISODE_ONLY"
        ),
        "kill_and_learn": formal_verdict == "REJECT",
        "historical_episode_candidate_allowed": True,
        "historical_episode_recorded": False,
        "structural_lesson_generated": False,
        "conditional_lesson_generated": False,
        "canonical_promotion_performed": False,
    }


def _terminal_projection(
    root: Path,
    report_id: str,
    *,
    incident_trust_root: Path,
    incident_installation_id: str,
    incident_guard: object,
) -> dict[str, Any]:
    validate_oos_exposure_private_registry_guard(
        incident_guard,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=report_id,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    if incident_reasons:
        raise ValueError(";".join(incident_reasons))
    lifecycle_path = epistemic_evolution_lifecycle_path(root, report_id)
    lifecycle = _read_json_object(lifecycle_path)
    lifecycle_reasons = validate_epistemic_evolution_lifecycle(
        lifecycle,
        report_id=report_id,
        workspace_root=root,
        require_signed_host_receipts=True,
    )
    if lifecycle_reasons:
        raise ValueError(";".join(lifecycle_reasons))
    events = lifecycle.get("events")
    if (
        lifecycle.get("current_state") != "NO_QUALIFIED_CONTRADICTION"
        or not isinstance(events, list)
        or len(events) != 2
        or events[-1].get("to_state") != "NO_QUALIFIED_CONTRADICTION"
    ):
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:lifecycle_not_terminal_nqc")
    snapshot_path = epistemic_evolution_lifecycle_snapshot_path(
        root, report_id, len(events)
    )
    snapshot = _read_json_object(snapshot_path)
    snapshot_reasons = validate_epistemic_evolution_lifecycle(
        snapshot,
        report_id=report_id,
        workspace_root=root,
        require_signed_host_receipts=True,
    )
    if snapshot_reasons:
        raise ValueError(";".join(snapshot_reasons))
    if (
        snapshot != lifecycle
        or snapshot_path.read_bytes() != lifecycle_path.read_bytes()
    ):
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:lifecycle_snapshot_mismatch")

    certificate_path = factor_proof_certificate_path(root, report_id)
    certificate = _read_json_object(certificate_path)
    factor_id = str(certificate.get("factor_id") or "")
    proof_report = validate_factor_proof_certificate(
        certificate,
        workspace_root=root,
        expected_report_id=report_id,
        expected_factor_id=factor_id,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=incident_guard,
    )
    formal_verdict = proof_report.get("verdict")
    if (
        formal_verdict not in _TERMINAL_DECISION_BY_VERDICT
        or proof_report.get("block_reasons")
        or proof_report.get("current_formal_authority_verified") is not True
        or certificate.get("declared_verdict") != formal_verdict
        or not factor_id
    ):
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:factor_proof_not_terminal")
    component_bindings = certificate.get("component_obligation_bindings")
    if not isinstance(component_bindings, list):
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:component_bindings_missing")
    for binding in component_bindings:
        if not isinstance(binding, Mapping):
            raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:component_binding_invalid")
        component_path = _resolve_reference(root, binding.get("report_ref"))
        if (
            component_path is None
            or not component_path.is_file()
            or component_path.is_symlink()
            or binding.get("report_sha256") != sha256_file(component_path)
        ):
            raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:component_binding_invalid")
        component_reasons = validate_component_obligation_report(
            _read_json_object(component_path),
            workspace_root=root,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=incident_guard,
        )
        if component_reasons:
            raise ValueError(";".join(component_reasons))

    data_contract = certificate.get("data_contract")
    release_raw = (
        data_contract.get("oos_release_manifest_ref")
        if isinstance(data_contract, dict)
        else None
    )
    release_path = _resolve_reference(root, release_raw)
    canonical_release_path = (
        root
        / "objects"
        / "research_protocol"
        / f"oos_release_manifest__{report_id}.json"
    ).resolve(strict=False)
    if release_path != canonical_release_path:
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:oos_release_noncanonical")
    release = _read_json_object(canonical_release_path)
    if (
        release.get("release_status") != "RELEASED"
        or release.get("report_id") != report_id
        or release.get("factor_id") != factor_id
    ):
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:oos_release_identity")
    oos_consumption = _oos_consumption_projection(
        root=root,
        report_id=report_id,
        release_path=canonical_release_path,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        incident_guard=incident_guard,
    )

    iteration_path = (
        root
        / "objects"
        / "research_iteration_master"
        / f"research_iteration_master__{report_id}.json"
    )
    iteration = _read_json_object(iteration_path)
    case = _read_json_object(
        root
        / "objects"
        / "factor_case_master"
        / f"factor_case_master__{report_id}.json"
    )
    expected_decision = _TERMINAL_DECISION_BY_VERDICT[formal_verdict]
    judgment = (
        iteration.get("research_judgment")
        if isinstance(iteration.get("research_judgment"), dict)
        else {}
    )
    source_decision = judgment.get("decision")
    memo = (
        judgment.get("research_memo")
        if isinstance(judgment.get("research_memo"), dict)
        else {}
    )
    revision_strategy = (
        memo.get("revision_strategy")
        if isinstance(memo.get("revision_strategy"), dict)
        else {}
    )
    final_strategy = (
        memo.get("final_revision_strategy")
        if isinstance(memo.get("final_revision_strategy"), dict)
        else {}
    )
    step3b_handoff = (
        root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json"
    )
    if (
        iteration.get("report_id") != report_id
        or iteration.get("factor_id") != factor_id
        or case.get("report_id") != report_id
        or case.get("factor_id") != factor_id
        or (formal_verdict == "ACCEPT" and source_decision != expected_decision)
        or (formal_verdict == "REJECT" and source_decision not in {"reject", "iterate"})
        or revision_strategy.get("loop_authorization") == "approved_for_step3b_handoff"
        or final_strategy.get("loop_authorization") == "approved_for_step3b_handoff"
        or step3b_handoff.exists()
        or step3b_handoff.is_symlink()
    ):
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:active_revision_or_decision")

    artifact_paths = _canonical_artifact_paths(
        root,
        report_id,
        lifecycle_snapshot=snapshot_path,
        release_manifest=canonical_release_path,
        formal_verdict=formal_verdict,
    )
    if formal_verdict == "REJECT":
        official_path = (
            root
            / "objects"
            / "factor_library_official"
            / f"factor_record__{report_id}.json"
        )
        if official_path.exists() or official_path.is_symlink():
            raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:reject_official_record")
    evidence_refs = {
        key: (_reference(root, path) if path is not None else None)
        for key, path in artifact_paths.items()
    }
    step_validation = _step_validation(root, report_id)
    after_refs = {
        key: (_reference(root, path) if path is not None else None)
        for key, path in artifact_paths.items()
    }
    if after_refs != evidence_refs:
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:evidence_changed_during_validation")
    return {
        "report_id": report_id,
        "factor_id": factor_id,
        "lifecycle_state": "NO_QUALIFIED_CONTRADICTION",
        "execution_status": "COMPLETED",
        "formal_factor_verdict": formal_verdict,
        # A generic Step6 run may request another iteration when a validated
        # factor misses promotion thresholds.  Once the EVO lifecycle has
        # closed as NO_QUALIFIED_CONTRADICTION and the sealed OOS has been
        # consumed, that request has no revision authority.  Preserve it as
        # evidence while projecting the formal REJECT to terminal kill-and-
        # learn.  ACCEPT remains strict promote_official only.
        "source_step6_decision": source_decision,
        "step6_decision": expected_decision,
        "oos_consumption": oos_consumption,
        "step_validation": step_validation,
        "evidence_refs": evidence_refs,
        "authority_guard": dict(_AUTHORITY_GUARD),
        "learning_disposition": _learning_disposition(formal_verdict),
        "host_authority": TERMINAL_CLOSURE_HOST_AUTHORITY,
    }


def _closure_core(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"host_receipt_ref", "content_sha256"}
    }


def _receipt_reasons(
    *,
    root: Path,
    report_id: str,
    closure: Mapping[str, Any],
) -> list[str]:
    reference = closure.get("host_receipt_ref")
    if not isinstance(reference, dict) or set(reference) != _HOST_REFERENCE_FIELDS:
        return [f"{BLOCK_TERMINAL_CLOSURE}:host_receipt_reference_shape"]
    receipt_path = _resolve_reference(root, reference.get("path"))
    expected_path = terminal_closure_receipt_path(root, report_id).resolve(strict=False)
    if (
        receipt_path != expected_path
        or receipt_path is None
        or receipt_path.is_symlink()
        or not receipt_path.is_file()
        or reference.get("sha256") != sha256_file(receipt_path)
    ):
        return [f"{BLOCK_TERMINAL_CLOSURE}:host_receipt_reference"]
    try:
        receipt = _read_json_object(receipt_path)
    except ValueError as exc:
        return [str(exc)]
    manifest = workspace_runtime_trust_manifest(root, report_id=report_id)
    if manifest is None or validate_public_trust_manifest(manifest):
        return [f"{BLOCK_TERMINAL_CLOSURE}:trust_manifest"]
    if reference.get("trust_manifest_sha256") != manifest.get("manifest_sha256"):
        return [f"{BLOCK_TERMINAL_CLOSURE}:trust_manifest_binding"]
    if reference.get("receipt_id") != receipt.get("receipt_id"):
        return [f"{BLOCK_TERMINAL_CLOSURE}:host_receipt_id"]
    signature_reasons = verify_signed_receipt_with_manifest(
        receipt,
        trust_manifest=manifest,
        expected_issuer="host_admission",
    )
    if signature_reasons:
        return [
            f"{BLOCK_TERMINAL_CLOSURE}:host_receipt:{reason}"
            for reason in signature_reasons
        ]
    expected_fields = {
        "contract_version",
        "issuer",
        "receipt_id",
        "signature",
        "receipt_type",
        "report_id",
        "factor_id",
        "closure_core_sha256",
        "evidence_refs_sha256",
        "lifecycle_content_sha256",
        "formal_factor_verdict",
        "source_step6_decision",
        "terminal_decision",
        "oos_consumption_sha256",
        "trust_manifest_sha256",
        "authority_scope",
    }
    lifecycle_path = epistemic_evolution_lifecycle_path(root, report_id)
    try:
        lifecycle = _read_json_object(lifecycle_path)
    except ValueError as exc:
        return [str(exc)]
    expected = {
        "receipt_type": TERMINAL_CLOSURE_RECEIPT_TYPE,
        "report_id": report_id,
        "factor_id": closure.get("factor_id"),
        "closure_core_sha256": stable_hash(_closure_core(closure)),
        "evidence_refs_sha256": stable_hash(closure.get("evidence_refs")),
        "lifecycle_content_sha256": lifecycle.get("content_sha256"),
        "formal_factor_verdict": closure.get("formal_factor_verdict"),
        "source_step6_decision": closure.get("source_step6_decision"),
        "terminal_decision": closure.get("step6_decision"),
        "oos_consumption_sha256": stable_hash(closure.get("oos_consumption")),
        "trust_manifest_sha256": manifest.get("manifest_sha256"),
        "authority_scope": TERMINAL_CLOSURE_AUTHORITY_SCOPE,
    }
    if set(receipt) != expected_fields:
        return [f"{BLOCK_TERMINAL_CLOSURE}:host_receipt_shape"]
    mismatched = [
        field for field, value in expected.items() if receipt.get(field) != value
    ]
    return [
        f"{BLOCK_TERMINAL_CLOSURE}:host_receipt_binding:{field}" for field in mismatched
    ]


def validate_evo_post_oos_terminal_closure(
    *,
    workspace_root: Path,
    report_id: str,
    trust_root: Path | None = None,
    installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    if trust_root is None or not installation_id:
        return {
            "verdict": "BLOCK",
            "report_id": report_id,
            "formal_factor_verdict": None,
            "block_reasons": [
                f"{BLOCK_TERMINAL_CLOSURE}:incident_host_context_required"
            ],
        }
    try:
        resolved_trust = trust_root.expanduser().resolve(strict=True)
        if _incident_guard is not None:
            validate_oos_exposure_private_registry_guard(
                _incident_guard,
                trust_root=resolved_trust,
                installation_id=installation_id,
            )
            return _validate_evo_post_oos_terminal_closure_guarded(
                workspace_root=workspace_root,
                report_id=report_id,
                trust_root=resolved_trust,
                installation_id=installation_id,
                _incident_guard=_incident_guard,
            )
        with oos_exposure_private_registry_guard(
            resolved_trust,
            installation_id=installation_id,
        ) as guard:
            return _validate_evo_post_oos_terminal_closure_guarded(
                workspace_root=workspace_root,
                report_id=report_id,
                trust_root=resolved_trust,
                installation_id=installation_id,
                _incident_guard=guard,
            )
    except (OSError, ValueError) as exc:
        return {
            "verdict": "BLOCK",
            "report_id": report_id,
            "formal_factor_verdict": None,
            "block_reasons": [str(exc)],
        }


def _validate_evo_post_oos_terminal_closure_guarded(
    *,
    workspace_root: Path,
    report_id: str,
    trust_root: Path,
    installation_id: str,
    _incident_guard: object,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=False)
    path = terminal_closure_path(root, report_id)
    reasons: list[str] = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=report_id,
        trust_root=trust_root,
        installation_id=installation_id,
    )
    if reasons:
        return {
            "verdict": "BLOCK",
            "report_id": report_id,
            "formal_factor_verdict": None,
            "block_reasons": reasons,
        }
    try:
        closure = _read_json_object(path)
    except ValueError as exc:
        return {
            "verdict": "BLOCK",
            "report_id": report_id,
            "formal_factor_verdict": None,
            "block_reasons": [str(exc)],
        }
    if set(closure) != _CLOSURE_FIELDS:
        reasons.append(f"{BLOCK_TERMINAL_CLOSURE}:closure_shape")
    unsigned = dict(closure)
    content_hash = unsigned.pop("content_sha256", None)
    if content_hash != stable_hash(unsigned):
        reasons.append(f"{BLOCK_TERMINAL_CLOSURE}:content_sha256")
    if (
        closure.get("contract_version") != TERMINAL_CLOSURE_VERSION
        or closure.get("report_id") != report_id
        or closure.get("lifecycle_state") != "NO_QUALIFIED_CONTRADICTION"
        or closure.get("execution_status") != "COMPLETED"
        or closure.get("host_authority") != TERMINAL_CLOSURE_HOST_AUTHORITY
        or closure.get("authority_guard") != _AUTHORITY_GUARD
        or closure.get("learning_disposition")
        != _learning_disposition(str(closure.get("formal_factor_verdict") or ""))
    ):
        reasons.append(f"{BLOCK_TERMINAL_CLOSURE}:closure_contract")
    evidence_refs = closure.get("evidence_refs")
    if not isinstance(evidence_refs, dict) or set(evidence_refs) != _EVIDENCE_KEYS:
        reasons.append(f"{BLOCK_TERMINAL_CLOSURE}:evidence_refs_shape")
    else:
        for key, reference in evidence_refs.items():
            if (
                key in {"oos_allocation", "factor_library_official"}
                and reference is None
            ):
                continue
            reasons.extend(_reference_reasons(root, reference))
    try:
        current = _terminal_projection(
            root,
            report_id,
            incident_trust_root=trust_root,
            incident_installation_id=installation_id,
            incident_guard=_incident_guard,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        reasons.append(str(exc))
        current = None
    if current is not None:
        for field in (
            "report_id",
            "factor_id",
            "lifecycle_state",
            "execution_status",
            "formal_factor_verdict",
            "source_step6_decision",
            "step6_decision",
            "oos_consumption",
            "step_validation",
            "evidence_refs",
            "authority_guard",
            "learning_disposition",
            "host_authority",
        ):
            if closure.get(field) != current.get(field):
                reasons.append(f"{BLOCK_TERMINAL_CLOSURE}:current_state_drift:{field}")
    reasons.extend(_receipt_reasons(root=root, report_id=report_id, closure=closure))
    formal_verdict = closure.get("formal_factor_verdict")
    if formal_verdict not in _TERMINAL_DECISION_BY_VERDICT:
        reasons.append(f"{BLOCK_TERMINAL_CLOSURE}:formal_verdict")
    reasons = list(dict.fromkeys(reasons))
    return {
        "verdict": "BLOCK" if reasons else "PASS",
        "report_id": report_id,
        "formal_factor_verdict": formal_verdict if not reasons else None,
        "terminal_decision": closure.get("step6_decision") if not reasons else None,
        "closure_path": _relative(root, path),
        "closure_sha256": sha256_file(path),
        "block_reasons": reasons,
    }


def issue_evo_post_oos_terminal_closure(
    *,
    workspace_root: Path,
    report_id: str,
    trust_root: Path,
    installation_id: str,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    """Issue the Host-only terminal proof for the non-revision EVO path.

    The function deliberately has no decision, law, approval, or lesson input.
    The factor verdict is re-derived from the current factor-proof certificate,
    and the only accepted lifecycle state is ``NO_QUALIFIED_CONTRADICTION``.
    """

    root = workspace_root.expanduser().resolve(strict=True)
    private_root = trust_root.expanduser().resolve(strict=True)
    if _incident_guard is None:
        with oos_exposure_private_registry_guard(
            private_root,
            installation_id=installation_id,
        ) as incident_guard:
            return issue_evo_post_oos_terminal_closure(
                workspace_root=root,
                report_id=report_id,
                trust_root=private_root,
                installation_id=installation_id,
                _incident_guard=incident_guard,
            )
    validate_oos_exposure_private_registry_guard(
        _incident_guard,
        trust_root=private_root,
        installation_id=installation_id,
    )
    if (
        private_root == root
        or root in private_root.parents
        or private_root in root.parents
    ):
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:trust_root_overlaps_workspace")
    trust_store = load_runtime_trust_store(
        private_root,
        installation_id=installation_id,
    )
    manifest = workspace_runtime_trust_manifest(root, report_id=report_id)
    if (
        manifest is None
        or validate_public_trust_manifest(manifest)
        or manifest != trust_store.public_manifest
    ):
        raise ValueError(f"{BLOCK_TERMINAL_CLOSURE}:trust_manifest_mismatch")
    path = terminal_closure_path(root, report_id)
    with _closure_lock(path):
        incident_reasons = formal_oos_incident_reasons(
            workspace_root=root,
            report_id=report_id,
            trust_root=private_root,
            installation_id=installation_id,
        )
        if incident_reasons:
            raise ValueError(";".join(incident_reasons))
        if path.exists() or path.is_symlink():
            report = validate_evo_post_oos_terminal_closure(
                workspace_root=root,
                report_id=report_id,
                trust_root=private_root,
                installation_id=installation_id,
                _incident_guard=_incident_guard,
            )
            if report.get("verdict") != "PASS":
                raise ValueError(";".join(report.get("block_reasons") or []))
            return {**report, "status": "IDEMPOTENT_REPLAY"}

        projection = _terminal_projection(
            root,
            report_id,
            incident_trust_root=private_root,
            incident_installation_id=installation_id,
            incident_guard=_incident_guard,
        )
        core = {
            "contract_version": TERMINAL_CLOSURE_VERSION,
            **projection,
        }
        lifecycle = _read_json_object(
            epistemic_evolution_lifecycle_path(root, report_id)
        )
        receipt = trust_store.sign(
            "host_admission",
            {
                "receipt_type": TERMINAL_CLOSURE_RECEIPT_TYPE,
                "report_id": report_id,
                "factor_id": projection["factor_id"],
                "closure_core_sha256": stable_hash(core),
                "evidence_refs_sha256": stable_hash(projection["evidence_refs"]),
                "lifecycle_content_sha256": lifecycle["content_sha256"],
                "formal_factor_verdict": projection["formal_factor_verdict"],
                "source_step6_decision": projection["source_step6_decision"],
                "terminal_decision": projection["step6_decision"],
                "oos_consumption_sha256": stable_hash(projection["oos_consumption"]),
                "trust_manifest_sha256": manifest["manifest_sha256"],
                "authority_scope": TERMINAL_CLOSURE_AUTHORITY_SCOPE,
            },
        )
        receipt_path = terminal_closure_receipt_path(root, report_id)
        _write_immutable(receipt_path, receipt)
        receipt_ref = {
            "path": _relative(root, receipt_path),
            "sha256": sha256_file(receipt_path),
            "receipt_id": receipt["receipt_id"],
            "trust_manifest_sha256": manifest["manifest_sha256"],
        }
        unsigned = {**core, "host_receipt_ref": receipt_ref}
        closure = {**unsigned, "content_sha256": stable_hash(unsigned)}
        _write_immutable(path, closure)
        validation = validate_evo_post_oos_terminal_closure(
            workspace_root=root,
            report_id=report_id,
            trust_root=private_root,
            installation_id=installation_id,
            _incident_guard=_incident_guard,
        )
        if validation.get("verdict") != "PASS":
            raise ValueError(";".join(validation.get("block_reasons") or []))
        return {**validation, "status": "ISSUED"}
