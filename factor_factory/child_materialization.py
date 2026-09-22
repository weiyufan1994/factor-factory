from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from factor_factory.artifact_identity import stable_hash


MATERIALIZATION_VERSION = "factorforge_step6_child_revision_materialization_v2"
STAGING_MANIFEST_VERSION = "factorforge_child_materialization_staging_manifest_v1"
MATERIALIZATION_READBACK_BLOCK = (
    "BLOCK_FACTORFORGE_CHILD_MATERIALIZATION_READBACK_INVALID"
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workspace_path(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve(strict=False)
    if path != root and root not in path.parents:
        return None
    return path


def _target_projection(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "kind": entry.get("kind"),
            "path": entry.get("target_path"),
            "sha256": entry.get("sha256"),
            "size_bytes": entry.get("size_bytes"),
        }
        for entry in sorted(entries, key=lambda item: str(item.get("kind")))
    ]


def validate_child_materialization_readback(
    *,
    workspace_root: Path,
    report_path: Path,
    parent_report_id: str,
    child_report_id: str,
    source_handoff_sha256: str,
    required_target_kinds: set[str] | None = None,
) -> list[str]:
    root = workspace_root.expanduser().resolve(strict=False)
    report_path = report_path.expanduser().resolve(strict=False)
    reasons: list[str] = []
    if (
        (report_path != root and root not in report_path.parents)
        or not report_path.is_file()
        or report_path.is_symlink()
    ):
        return [f"{MATERIALIZATION_READBACK_BLOCK}:report_missing_or_unsafe"]
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [f"{MATERIALIZATION_READBACK_BLOCK}:report_invalid_json"]
    if not isinstance(report, dict):
        return [f"{MATERIALIZATION_READBACK_BLOCK}:report_not_object"]
    if report.get("materialization_version") != MATERIALIZATION_VERSION:
        reasons.append(f"{MATERIALIZATION_READBACK_BLOCK}:report_version")
    if report.get("parent_report_id") != parent_report_id:
        reasons.append(f"{MATERIALIZATION_READBACK_BLOCK}:parent_binding")
    if report.get("child_report_id") != child_report_id:
        reasons.append(f"{MATERIALIZATION_READBACK_BLOCK}:child_binding")
    if report.get("source_handoff_sha256") != source_handoff_sha256:
        reasons.append(f"{MATERIALIZATION_READBACK_BLOCK}:source_handoff_binding")

    manifest_ref = report.get("staging_manifest_ref")
    if not isinstance(manifest_ref, dict) or set(manifest_ref) != {
        "path",
        "content_sha256",
    }:
        reasons.append(f"{MATERIALIZATION_READBACK_BLOCK}:staging_manifest_ref")
        return reasons
    manifest_path = _workspace_path(root, manifest_ref.get("path"))
    if (
        manifest_path is None
        or not manifest_path.is_file()
        or manifest_path.is_symlink()
    ):
        return [*reasons, f"{MATERIALIZATION_READBACK_BLOCK}:staging_manifest_path"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [*reasons, f"{MATERIALIZATION_READBACK_BLOCK}:staging_manifest_json"]
    if not isinstance(manifest, dict):
        return [*reasons, f"{MATERIALIZATION_READBACK_BLOCK}:staging_manifest_object"]
    unsigned = dict(manifest)
    declared_manifest_hash = unsigned.pop("content_sha256", None)
    if (
        manifest.get("contract_version") != STAGING_MANIFEST_VERSION
        or manifest.get("state") != "PREPARED"
        or declared_manifest_hash != stable_hash(unsigned)
        or manifest_ref.get("content_sha256") != declared_manifest_hash
    ):
        reasons.append(f"{MATERIALIZATION_READBACK_BLOCK}:staging_manifest_hash")
    if (
        manifest.get("parent_report_id") != parent_report_id
        or manifest.get("child_report_id") != child_report_id
        or manifest.get("source_handoff_sha256") != source_handoff_sha256
    ):
        reasons.append(f"{MATERIALIZATION_READBACK_BLOCK}:staging_manifest_binding")
    if _workspace_path(root, manifest.get("materialization_report_path")) != report_path:
        reasons.append(f"{MATERIALIZATION_READBACK_BLOCK}:report_path_binding")

    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        reasons.append(f"{MATERIALIZATION_READBACK_BLOCK}:manifest_entries")
        entries = []
    target_hashes = report.get("materialization_target_hashes")
    if not isinstance(target_hashes, list) or target_hashes != _target_projection(entries):
        reasons.append(f"{MATERIALIZATION_READBACK_BLOCK}:target_hash_projection")
        target_hashes = []
    expected_report = json.loads(json.dumps(manifest.get("report_payload")))
    if not isinstance(expected_report, dict):
        reasons.append(f"{MATERIALIZATION_READBACK_BLOCK}:report_payload")
    else:
        expected_report["staging_manifest_ref"] = {
            "path": manifest_ref.get("path"),
            "content_sha256": manifest.get("content_sha256"),
        }
        if report != expected_report:
            reasons.append(f"{MATERIALIZATION_READBACK_BLOCK}:report_projection")

    seen_kinds: set[str] = set()
    seen_paths: set[str] = set()
    for index, row in enumerate(target_hashes):
        prefix = f"{MATERIALIZATION_READBACK_BLOCK}:target[{index}]"
        if not isinstance(row, dict) or set(row) != {
            "kind",
            "path",
            "sha256",
            "size_bytes",
        }:
            reasons.append(f"{prefix}:shape")
            continue
        kind = row.get("kind")
        raw_path = row.get("path")
        digest = row.get("sha256")
        size = row.get("size_bytes")
        path = _workspace_path(root, raw_path)
        if not isinstance(kind, str) or not kind or kind in seen_kinds:
            reasons.append(f"{prefix}:kind")
        else:
            seen_kinds.add(kind)
        if not isinstance(raw_path, str) or raw_path in seen_paths or path is None:
            reasons.append(f"{prefix}:path")
        else:
            seen_paths.add(raw_path)
        if (
            path is None
            or not path.is_file()
            or path.is_symlink()
            or not isinstance(size, int)
            or path.stat().st_size != size
            or not isinstance(digest, str)
            or _sha256_file(path) != digest
        ):
            reasons.append(f"{prefix}:hash_mismatch")
    missing_kinds = sorted((required_target_kinds or set()) - seen_kinds)
    if missing_kinds:
        reasons.append(
            f"{MATERIALIZATION_READBACK_BLOCK}:required_targets_missing:"
            + ",".join(missing_kinds)
        )
    return list(dict.fromkeys(reasons))


__all__ = [
    "MATERIALIZATION_READBACK_BLOCK",
    "MATERIALIZATION_VERSION",
    "STAGING_MANIFEST_VERSION",
    "validate_child_materialization_readback",
]
