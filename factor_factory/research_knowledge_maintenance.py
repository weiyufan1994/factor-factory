"""Bounded, advisory maintenance records for incomplete local research runs.

These records deliberately preserve wrapper facts only.  They are not Step6
knowledge records, factor verdicts, or explanations of an observed failure.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping


EPISODE_VERSION = "factorforge_research_episode_v1"
EPISODE_RELATIVE_ROOT = Path("knowledge/research_episodes")
EXPORT_RELATIVE_ROOT = Path("knowledge/因子工厂/research_episode_exports")
REPORT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,191}$")


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _safe_target(root: Path, relative: Path) -> Path:
    root = root.resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("research_episode_root_invalid")
    target = root / relative
    parent = target.parent
    # Resolve every existing parent before creating anything, so a mount-like
    # symlink cannot redirect a maintenance write outside the declared root.
    while parent != root and not parent.exists():
        parent = parent.parent
    if parent.is_symlink() or not parent.resolve().is_relative_to(root):
        raise ValueError("research_episode_path_escapes_root")
    return target


def _create_only(root: Path, relative: Path, content: bytes) -> tuple[str, Path]:
    path = _safe_target(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if not path.is_file() or path.is_symlink() or path.read_bytes() != content:
            raise FileExistsError("research_episode_conflict")
        return "IDEMPOTENT", path
    try:
        with path.open("xb") as stream:
            stream.write(content)
        return "WRITTEN", path
    except FileExistsError:
        # Concurrent writers with identical facts converge rather than fail.
        if path.is_file() and not path.is_symlink() and path.read_bytes() == content:
            return "IDEMPOTENT", path
        raise FileExistsError("research_episode_conflict")


def record_local_research_episode(
    *, proof: Mapping[str, Any], workspace: Path | None, repo_root: Path,
    report_id: str, dry_run: bool, local_is_only: bool,
) -> dict[str, Any]:
    """Persist executed local-IS wrapper facts, never research interpretation.

    The caller owns the research proof.  This function is best-effort
    maintenance and raises only to let the wrapper expose a maintenance warning.
    """
    if proof.get("contract_smoke_only") is True:
        return {"status": "SKIPPED", "reason": "engineering_contract_smoke"}
    commands = proof.get("commands")
    if (not local_is_only or dry_run or not isinstance(commands, list) or not commands
            or workspace is None):
        return {"status": "SKIPPED", "reason": "no_executed_local_is_wrapper"}
    workspace = Path(workspace).resolve()
    if workspace == Path(repo_root).resolve() or not workspace.is_dir():
        return {"status": "SKIPPED", "reason": "invalid_workspace"}
    if not REPORT_ID_RE.fullmatch(report_id):
        return {"status": "SKIPPED", "reason": "invalid_report_id"}
    step6 = [row for row in commands if isinstance(row, Mapping) and row.get("name") in {"run_step6", "validate_step6"}]
    if (len(step6) == 2 and {row.get("name") for row in step6} == {"run_step6", "validate_step6"}
            and proof.get("status") == "PASS"
            and all(row.get("status") == "PASS" and row.get("returncode") == 0 for row in step6)):
        return {"status": "SKIPPED", "reason": "completed_step6_uses_knowledge_record"}
    observations = []
    for row in commands:
        if not isinstance(row, Mapping):
            continue
        name, status = row.get("name"), row.get("status")
        if isinstance(name, str) and isinstance(status, str):
            observations.append({"command": name, "status": status, "returncode": row.get("returncode")})
    if not observations:
        return {"status": "SKIPPED", "reason": "no_command_facts"}
    failure = proof.get("failure") if isinstance(proof.get("failure"), Mapping) else {}
    payload: dict[str, Any] = {
        "episode_version": EPISODE_VERSION,
        "report_id": report_id,
        "factor_id": proof.get("factor_id") if isinstance(proof.get("factor_id"), str) else None,
        "run_status": proof.get("status") if isinstance(proof.get("status"), str) else "UNKNOWN",
        "failure_stage": failure.get("command") if isinstance(failure.get("command"), str) else None,
        "observations": observations,
        "lessons_status": "NEEDS_RESEARCHER_REVIEW",
        "source_refs": ["objects/runtime_context/ultimate_run_report__%s.json" % report_id],
        "advisory_only": True,
        "formal_step6_completed": False,
    }
    content = _canonical_bytes(payload)
    digest = hashlib.sha256(content).hexdigest()[:16]
    filename = f"episode__{report_id}__{digest}.json"
    local_status, local_path = _create_only(workspace, EPISODE_RELATIVE_ROOT / filename, content)
    export_status, export_path = _create_only(Path(repo_root), EXPORT_RELATIVE_ROOT / filename, content)
    return {
        "status": "RECORDED",
        "local_status": local_status,
        "export_status": export_status,
        "local_path": str(local_path),
        "export_path": str(export_path),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def refresh_episode_maintenance(*, workspace: Path, repo_root: Path, report_id: str) -> dict[str, Any]:
    """Refresh derivative lexical/optional semantic indexes and prove visibility."""
    from scripts.build_factorforge_retrieval_index import refresh_retrieval_index
    result: dict[str, Any] = {"status": "REFRESHED"}
    local = refresh_retrieval_index(Path(workspace))
    shared = refresh_retrieval_index(Path(repo_root), project_root=Path(repo_root))
    result["workspace_index"] = local["output_path"]
    result["default_index"] = shared["output_path"]
    expected = f"research_episode::{report_id}::"
    with Path(shared["output_path"]).open("r", encoding="utf-8") as stream:
        result["default_readback"] = any(
            str(json.loads(line).get("id") or "").startswith(expected)
            for line in stream if line.strip()
        )
    try:
        from factor_factory.semantic_knowledge_retrieval import refresh_configured_index
        result["semantic"] = refresh_configured_index(Path(repo_root))
    except Exception as exc:
        result["semantic"] = {"status": "FAILED", "error_type": type(exc).__name__}
    return result


def write_latest_maintenance_report(*, repo_root: Path, payload: Mapping[str, Any]) -> str:
    root = Path(repo_root).resolve(strict=True)
    path = _safe_target(root, Path("knowledge/maintenance/latest.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".maintenance-", dir=path.parent)
    try:
        with open(fd, "w", encoding="utf-8", closefd=True) as stream:
            stream.write(content)
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return str(path)
