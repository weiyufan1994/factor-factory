"""Create-only advisory projection of a completed workspace Step6 record."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


EXPORT_VERSION = "factorforge_workspace_experience_export_v1"
EXPORT_RELATIVE_ROOT = Path("knowledge/因子工厂/workspace_experience_exports")
ALLOWED = (
    "report_id", "factor_id", "decision", "factor_family", "monetization_model",
    "bias_type", "return_source_hypothesis", "expected_failure_regimes",
    "objective_constraint_dependency", "constraint_sources", "success_patterns",
    "research_variant", "paper_replication_status",
    "failure_patterns", "modification_hypotheses", "mathematical_object",
    "reusable_heuristics", "modification_hypotheses_future_only",
    "reusable_operator", "implementation_references", "structured_knowledge_status",
    "learning_and_innovation", "research_compatibility_profile",
    "next_research_tests_absence_reason",
    "modification_hypotheses_status", "knowledge_scope", "reuse_constraints",
    "artifact_identity", "source_identity", "source_case_identity", "evidence_identity",
    "applicability_conditions", "regime_detection", "treatment_effect", "evidence_class",
    "validity_status", "invalidation_reason",
    "created_at_utc", "producer",
)


def export_workspace_knowledge_record(*, workspace: Path, repo_root: Path, report_id: str) -> dict[str, Any]:
    workspace, repo_root = Path(workspace).resolve(), Path(repo_root).resolve()
    source = workspace / "objects/research_knowledge_base" / f"knowledge_record__{report_id}.json"
    if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(workspace):
        raise ValueError("workspace_knowledge_record_invalid")
    raw = source.read_bytes()
    record = json.loads(raw)
    if not isinstance(record, dict) or record.get("report_id") != report_id:
        raise ValueError("workspace_knowledge_record_identity_invalid")
    if record.get("validity_status") == "withdrawn" and not str(record.get("invalidation_reason") or "").strip():
        raise ValueError("workspace_knowledge_record_withdrawn_reason_missing")
    payload = {key: record.get(key) for key in ALLOWED if key in record}
    payload.update({
        "export_version": EXPORT_VERSION,
        "export_status": "LOCAL_PROJECT_ADVISORY_CANDIDATE_NOT_CANONICAL",
        "advisory_only": True,
        "same_factor_not_generalized": True,
        "canonical_promotion_allowed": False,
        "source_record_relative_ref": str(source.relative_to(workspace)),
        "source_record_sha256": hashlib.sha256(raw).hexdigest(),
    })
    content = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    target = repo_root / EXPORT_RELATIVE_ROOT / f"knowledge_record__{report_id}.json"
    target_parent = target.parent
    try:
        target_parent.resolve(strict=False).relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("workspace_experience_export_target_outside_repo") from exc
    target_parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != content:
            raise FileExistsError("workspace_experience_export_conflict")
        return {"status": "IDEMPOTENT", "path": str(target), "sha256": hashlib.sha256(content).hexdigest()}
    with target.open("xb") as stream:
        stream.write(content)
    return {"status": "EXPORTED", "path": str(target), "sha256": hashlib.sha256(content).hexdigest()}
