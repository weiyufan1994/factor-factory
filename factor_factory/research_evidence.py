from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


def factor_proof_certificate_path(workspace_root: Path, report_id: str) -> Path:
    return (
        workspace_root
        / "objects"
        / "research_protocol"
        / f"factor_proof_certificate__{report_id}.json"
    )


def read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def web_factor_proof_paths(root: Path, report_id: str) -> dict[str, Path]:
    protocol = root / "objects" / "research_protocol"
    return {
        "search_ledger": protocol / f"search_trial_ledger__{report_id}.json",
        "spec": protocol / f"metric_verifier_spec__{report_id}.json",
        "bound_spec": protocol / f"metric_verifier_bound_spec__{report_id}.json",
        "threshold": protocol / f"threshold_registration__{report_id}.json",
        "release": protocol / f"oos_release_manifest__{report_id}.json",
        "panel": protocol / f"factor_proof_panel__{report_id}.parquet",
        "certificate": factor_proof_certificate_path(root, report_id),
        "verifier": protocol / f"factor_proof_verifier_report__{report_id}.json",
        "preregistration": protocol / f"web_factor_proof_preregistration__{report_id}.json",
        "finalization": protocol / f"web_factor_proof_finalization__{report_id}.json",
        "evo_is_panel": protocol / f"evo_purged_is_panel__{report_id}.parquet",
        "evo_is_diagnostics": protocol / f"evo_purged_is_diagnostics__{report_id}.json",
    }


def _component_obligation_paths(
    root: Path,
    report_id: str,
    component_id: str,
) -> dict[str, Path]:
    protocol = root / "objects" / "research_protocol"
    suffix = f"{report_id}__{component_id}"
    return {
        "spec": protocol / f"component_obligation_spec__{suffix}.json",
        "threshold": protocol
        / f"component_obligation_threshold__{suffix}.json",
        "release": protocol / f"component_oos_release__{suffix}.json",
    }


def _legacy_oos_workspace_temps(output: Path) -> list[Path]:
    """Find crash residue from the former workspace-local panel staging path."""

    parent = output.parent
    if not parent.is_dir():
        return []
    prefix = f".{output.name}."
    return sorted(
        (
            candidate
            for candidate in parent.iterdir()
            if candidate.name.startswith(prefix) and candidate.name.endswith(".tmp")
        ),
        key=lambda item: item.name,
    )


def _evo_oos_artifacts(root: Path, report_id: str) -> list[Path]:
    paths = web_factor_proof_paths(root, report_id)
    protocol = root / "objects" / "research_protocol"
    candidates = [
        paths["bound_spec"],
        paths["release"],
        paths["panel"],
        paths["certificate"],
        paths["verifier"],
        paths["finalization"],
        protocol / f"metric_verifier_bundle__{report_id}.json",
    ]
    candidates.extend(_legacy_oos_workspace_temps(paths["panel"]))
    preregistration = paths["preregistration"]
    if preregistration.is_file() and not preregistration.is_symlink():
        receipt = read_json_object(preregistration)
        for item in receipt.get("component_obligation_preregistrations") or []:
            if not isinstance(item, dict):
                continue
            component_id = str(item.get("component_id") or "")
            if component_id:
                candidates.append(
                    _component_obligation_paths(root, report_id, component_id)[
                        "release"
                    ]
                )
    return list(dict.fromkeys(candidates))


def web_factor_proof_oos_recovery_state(
    workspace_root: Path,
    report_id: str,
) -> dict[str, Any]:
    """Detect an OOS publication that forbids returning to Agent phases.

    Existence is deliberately sufficient. A corrupt, symlinked, or only
    partially written artifact is still an information-release boundary and
    may only be handled by the trusted finalizer/terminal path.
    """

    root = Path(workspace_root).expanduser().resolve(strict=True)
    artifacts = [
        path
        for path in _evo_oos_artifacts(root, report_id)
        if path.exists() or path.is_symlink()
    ]
    paths = web_factor_proof_paths(root, report_id)
    return {
        "recovery_required": bool(artifacts),
        "allowed_execution": (
            "HOST_FINALIZER_OR_TERMINAL_ONLY" if artifacts else "NORMAL"
        ),
        "artifact_refs": [str(path.relative_to(root)) for path in artifacts],
        "finalization_receipt_present": (
            paths["finalization"].exists()
            or paths["finalization"].is_symlink()
        ),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_workspace_evidence_path(workspace_root: Path, raw_path: Any) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    root = workspace_root.expanduser().resolve(strict=False)
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        return None
    return candidate


def validate_evidence_reference(
    reference: Any,
    *,
    workspace_root: Path | None,
    token_prefix: str,
    require_verifier_pass: bool = True,
    allowed_verifier_ids: set[str] | None = None,
    expected_verifier_source_sha256: str | None = None,
    expected_bindings: dict[str, Any] | None = None,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(reference, dict):
        return [f"{token_prefix}_REFERENCE_INVALID"]
    for field in (
        "path",
        "sha256",
        "dataset_snapshot_hash",
        "window_hash",
        "verifier_id",
    ):
        value = reference.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"{token_prefix}_FIELD_MISSING:{field}")
    for field in ("sha256", "dataset_snapshot_hash", "window_hash"):
        value = reference.get(field)
        if isinstance(value, str) and value.strip() and not SHA256_RE.fullmatch(
            value.strip().lower()
        ):
            reasons.append(f"{token_prefix}_HASH_INVALID:{field}")
    if require_verifier_pass and reference.get("verifier_status") != "PASS":
        reasons.append(f"{token_prefix}_VERIFIER_NOT_PASS")
    if (
        allowed_verifier_ids is not None
        and reference.get("verifier_id") not in allowed_verifier_ids
    ):
        reasons.append(f"{token_prefix}_VERIFIER_UNTRUSTED")
    if (
        expected_verifier_source_sha256 is not None
        and reference.get("verifier_source_sha256")
        != expected_verifier_source_sha256
    ):
        reasons.append(f"{token_prefix}_VERIFIER_SOURCE_MISMATCH")
    for field, expected in (expected_bindings or {}).items():
        if reference.get(field) != expected:
            reasons.append(f"{token_prefix}_REFERENCE_BINDING_MISMATCH:{field}")
    if workspace_root is None:
        reasons.append(f"{token_prefix}_WORKSPACE_ROOT_MISSING")
        return reasons
    path = resolve_workspace_evidence_path(workspace_root, reference.get("path"))
    if path is None:
        reasons.append(f"{token_prefix}_PATH_INVALID")
        return reasons
    if not path.is_file():
        reasons.append(f"{token_prefix}_PATH_MISSING:{reference.get('path')}")
        return reasons
    expected_hash = str(reference.get("sha256") or "")
    if expected_hash and sha256_file(path) != expected_hash:
        reasons.append(f"{token_prefix}_SHA256_MISMATCH:{reference.get('path')}")
        return reasons
    try:
        evidence_payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        reasons.append(f"{token_prefix}_VERIFIER_REPORT_INVALID")
        return reasons
    if not isinstance(evidence_payload, dict):
        reasons.append(f"{token_prefix}_VERIFIER_REPORT_INVALID")
        return reasons
    embedded_status = evidence_payload.get("verifier_status")
    if embedded_status != reference.get("verifier_status"):
        reasons.append(f"{token_prefix}_VERIFIER_STATUS_BINDING_MISMATCH")
    for field in ("verifier_id", "dataset_snapshot_hash", "window_hash"):
        if evidence_payload.get(field) != reference.get(field):
            reasons.append(f"{token_prefix}_VERIFIER_REPORT_BINDING_MISMATCH:{field}")
    if (
        expected_verifier_source_sha256 is not None
        and evidence_payload.get("verifier_source_sha256")
        != expected_verifier_source_sha256
    ):
        reasons.append(f"{token_prefix}_VERIFIER_REPORT_SOURCE_MISMATCH")
    for field, expected in (expected_bindings or {}).items():
        if evidence_payload.get(field) != expected:
            reasons.append(f"{token_prefix}_VERIFIER_REPORT_BINDING_MISMATCH:{field}")
    return reasons
