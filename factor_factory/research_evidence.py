from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


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
