"""Validate a Council result collection against its selected workspace."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from factor_factory.runtime_context import resolve_factorforge_context
from factor_factory.revision_council.production import (
    CouncilEvoProductionError,
    load_formal_evo_packet_context,
    result_evo_outcome_summary,
)


COLLECTION_VERSION = "factorforge_agentic_council_result_collection_v1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_collection(report_id: str, collection: dict[str, Any], *, workspace_root: Path | str | None = None) -> list[str]:
    root = resolve_factorforge_context(workspace_root).factorforge_root
    reasons: list[str] = []
    if collection.get("collection_version") != COLLECTION_VERSION or collection.get("report_id") != report_id:
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INVALID")
    if collection.get("canonical_write_permission") is True:
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_CANONICAL_WRITE_PERMISSION")
    if collection.get("execution_allowed_by_default") is True:
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_EXECUTION_ALLOWED_BY_DEFAULT")
    required = collection.get("required_result_count")
    present = collection.get("present_result_count")
    valid = collection.get("valid_result_count")
    invalid = collection.get("invalid_result_count")
    missing = collection.get("missing_result_count")
    if not isinstance(required, int) or required <= 0:
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INCOMPLETE")
    if missing != 0 or present != required:
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INCOMPLETE")
    if invalid != 0 or valid != required:
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INVALID_RESULTS")
    if collection.get("ready_for_finalize") is not True or collection.get("status") != "complete":
        reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_NOT_READY")
    evo_context = collection.get("evo_v2")
    council_dir = (
        root / "objects"
        / "research_iteration_master"
        / "revision_council"
        / report_id
    )
    manifest_path = council_dir / f"dispatch_manifest__{report_id}.json"
    manifest = load_json(manifest_path) if manifest_path.is_file() else {}
    try:
        expected_evo, _feedback = load_formal_evo_packet_context(
            root,
            report_id,
            bound_context=(evo_context if isinstance(evo_context, dict) else None),
        )
    except CouncilEvoProductionError as exc:
        reasons.extend(exc.reasons)
        expected_evo = None
    if evo_context != expected_evo:
        reasons.append("BLOCK_COUNCIL_EVO_V2_COLLECTION_CONTEXT_MISMATCH")
    if manifest.get("evo_v2") != evo_context:
        reasons.append("BLOCK_COUNCIL_EVO_V2_COLLECTION_CONTEXT_MISMATCH")
    manifest_tasks = {
        item.get("task_id"): item
        for item in manifest.get("agent_tasks") or []
        if isinstance(item, dict) and item.get("task_id")
    }
    for item in collection.get("valid_results") or []:
        if not isinstance(item, dict):
            reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INVALID_RESULTS")
            continue
        if item.get("status") != "final":
            reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INVALID_RESULTS")
        raw_path = item.get("result_path")
        path = Path(raw_path) if isinstance(raw_path, str) else Path()
        path = path if path.is_absolute() else root / path
        if not isinstance(raw_path, str) or not path.exists():
            reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_INVALID_RESULTS")
            continue
        if item.get("result_sha256") is not None and item.get(
            "result_sha256"
        ) != sha256_file(path):
            reasons.append("BLOCK_AGENTIC_COUNCIL_COLLECTION_RESULT_HASH_MISMATCH")
        if evo_context is not None:
            try:
                payload = load_json(path)
            except Exception:
                reasons.append("BLOCK_COUNCIL_EVO_V2_COLLECTION_RESULT_UNREADABLE")
                continue
            expected_task = manifest_tasks.get(item.get("task_id")) or {}
            expected_identity = expected_task.get("evo_v2_task_identity")
            if (
                item.get("evo_v2_task_identity") != expected_identity
                or payload.get("evo_v2_task_identity") != expected_identity
            ):
                reasons.append("BLOCK_COUNCIL_EVO_V2_COLLECTION_TASK_IDENTITY_MISMATCH")
            expected_outcome = result_evo_outcome_summary(payload)
            if item.get("evo_v2_outcome") != expected_outcome:
                reasons.append("BLOCK_COUNCIL_EVO_V2_COLLECTION_OUTCOME_MISMATCH")
            if not isinstance(expected_outcome, dict) or expected_outcome.get(
                "outcome"
            ) not in {"MINIMAL_MECHANISM_DELTA", "NO_DERIVED_LAW"}:
                reasons.append("BLOCK_COUNCIL_EVO_V2_COLLECTION_OUTCOME_INVALID")
    return sorted(set(reasons), key=reasons.index)
