from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKSPACE_CONTRACT_VERSION = "factorforge_factor_research_workspace_v1"

BLOCK_WORKSPACE_MISSING = "BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MISSING"
BLOCK_WORKSPACE_IDENTITY_INVALID = "BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_IDENTITY_INVALID"
BLOCK_WORKSPACE_MANIFEST_INVALID = "BLOCK_FACTORFORGE_FACTOR_RESEARCH_WORKSPACE_MANIFEST_INVALID"
BLOCK_OUTPUT_OUTSIDE_WORKSPACE = "BLOCK_FACTORFORGE_FACTOR_RESEARCH_OUTPUT_OUTSIDE_WORKSPACE"
BLOCK_STEP3_COPY_OUTSIDE_WORKSPACE = "BLOCK_FACTORFORGE_STEP3_RUNTIME_COPY_OUTSIDE_WORKSPACE"
BLOCK_KNOWLEDGE_WRITE_PATH_INVALID = "BLOCK_FACTORFORGE_KNOWLEDGE_WRITE_PATH_INVALID"
BLOCK_KNOWLEDGE_PROVENANCE_MISSING = "BLOCK_FACTORFORGE_KNOWLEDGE_PROVENANCE_MISSING"
BLOCK_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT = "BLOCK_FACTORFORGE_KNOWLEDGE_VAULT_EXPORT_NOT_EXPLICIT"
BLOCK_REPO_ROOT_DATA_WRITE_FORBIDDEN = "BLOCK_FACTORFORGE_REPO_ROOT_GENERATED_DATA_WRITE_FORBIDDEN"

REQUIRED_WORKSPACE_DIRS = (
    "identity",
    "step1",
    "step2",
    "step3_runtime",
    "runs",
    "objects",
    "evaluations",
    "council",
    "branch_comparison",
    "knowledge/canonical",
    "knowledge/human_readable",
    "knowledge/export_manifest",
    "reports",
    "logs",
    "tmp",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_identity(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._-")
    return text or "unknown"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_repo_commit(repo_root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()
    except Exception:
        return None


def default_workspace_root(*, factorforge_root: Path, factor_id: str, research_id: str) -> Path:
    return (
        Path(factorforge_root).expanduser()
        / "factor_research"
        / safe_identity(factor_id)
        / safe_identity(research_id)
    )


def _path_payload(workspace_root: Path) -> dict[str, str]:
    return {
        "objects_root": str(workspace_root / "objects"),
        "runs_root": str(workspace_root / "runs"),
        "evaluations_root": str(workspace_root / "evaluations"),
        "step3_runtime_root": str(workspace_root / "step3_runtime"),
        "knowledge_root": str(workspace_root / "knowledge"),
        "knowledge_canonical_root": str(workspace_root / "knowledge" / "canonical"),
        "knowledge_human_root": str(workspace_root / "knowledge" / "human_readable"),
        "knowledge_export_manifest_root": str(workspace_root / "knowledge" / "export_manifest"),
        "council_root": str(workspace_root / "council"),
        "branch_comparison_root": str(workspace_root / "branch_comparison"),
        "logs_root": str(workspace_root / "logs"),
        "tmp_root": str(workspace_root / "tmp"),
    }


def build_workspace_manifest(
    *,
    repo_root: Path,
    factorforge_root: Path,
    factor_id: str,
    research_id: str,
    root_report_id: str,
    active_report_id: str | None = None,
    implementation_mode: str = "unknown",
    shared_clean_data_root: Path | None = None,
) -> dict[str, Any]:
    repo_root = Path(repo_root).expanduser().resolve()
    factorforge_root = Path(factorforge_root).expanduser().resolve()
    workspace_root = default_workspace_root(
        factorforge_root=factorforge_root,
        factor_id=factor_id,
        research_id=research_id,
    ).resolve()
    return {
        "contract_version": WORKSPACE_CONTRACT_VERSION,
        "factor_id": str(factor_id),
        "research_id": str(research_id),
        "root_report_id": str(root_report_id),
        "active_report_id": str(active_report_id or root_report_id),
        "created_at_utc": utc_now(),
        "created_by": "factor_forge_ultimate",
        "repo_root": str(repo_root),
        "factorforge_root": str(factorforge_root),
        "workspace_root": str(workspace_root),
        "implementation_mode": implementation_mode,
        "status": "active",
        "identity": {
            "source_type": "factor_research_workspace",
            "report_ids": [str(root_report_id)],
            "branch_ids": [],
            "law_ids": [],
            "formula_hashes": [],
            "code_law_hashes": [],
        },
        "paths": _path_payload(workspace_root),
        "shared_inputs": {
            "clean_data_root": str(shared_clean_data_root.expanduser().resolve())
            if shared_clean_data_root
            else str(factorforge_root / "data" / "clean"),
            "provider_root": None,
        },
        "write_policy": {
            "production_writes_must_stay_under_workspace": True,
            "repo_root_knowledge_write_allowed": False,
            "repo_root_data_write_allowed": False,
            "vault_export_requires_explicit_flag": True,
        },
        "provenance": {
            "repo_commit": current_repo_commit(repo_root),
            "runtime_context_path": None,
            "source_feedback_doc": "docs/operations/factorforge-factor-research-workspace-isolation-feedback-20260612.zh-CN.md",
        },
    }


def create_required_dirs(workspace_root: Path) -> None:
    for rel in REQUIRED_WORKSPACE_DIRS:
        (workspace_root / rel).mkdir(parents=True, exist_ok=True)


def write_workspace_manifest(path: Path, manifest: dict[str, Any]) -> Path:
    path = Path(path).expanduser()
    workspace_root = Path(str(manifest.get("workspace_root") or path.parent)).expanduser()
    create_required_dirs(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_workspace_manifest(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def assert_path_under_workspace(path: Path, workspace_root: Path, *, label: str) -> None:
    workspace = Path(workspace_root).expanduser().resolve()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    candidate = candidate.resolve(strict=False)
    if candidate != workspace and not _is_relative_to(candidate, workspace):
        raise ValueError(f"{BLOCK_OUTPUT_OUTSIDE_WORKSPACE}: {label}={candidate} workspace={workspace}")


def validate_workspace_manifest(manifest: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if manifest.get("contract_version") != WORKSPACE_CONTRACT_VERSION:
        failures.append(f"{BLOCK_WORKSPACE_MANIFEST_INVALID}: contract_version")
    for key in ("factor_id", "research_id", "root_report_id", "workspace_root", "factorforge_root", "repo_root"):
        if not manifest.get(key):
            failures.append(f"{BLOCK_WORKSPACE_IDENTITY_INVALID}: {key}")
    workspace_root_raw = manifest.get("workspace_root")
    if not workspace_root_raw:
        return failures
    workspace_root = Path(str(workspace_root_raw)).expanduser().resolve()
    paths = manifest.get("paths") if isinstance(manifest.get("paths"), dict) else {}
    expected = _path_payload(workspace_root)
    for rel in REQUIRED_WORKSPACE_DIRS:
        if not (workspace_root / rel).exists():
            failures.append(f"{BLOCK_WORKSPACE_MANIFEST_INVALID}: required_dir_missing:{rel}")
    for key, expected_value in expected.items():
        raw = paths.get(key)
        if not raw:
            failures.append(f"{BLOCK_WORKSPACE_MANIFEST_INVALID}: paths.{key}")
            continue
        if Path(str(raw)).expanduser().resolve(strict=False) != Path(expected_value).resolve(strict=False):
            failures.append(f"{BLOCK_WORKSPACE_MANIFEST_INVALID}: paths.{key}_mismatch")
        try:
            assert_path_under_workspace(Path(str(raw)), workspace_root, label=f"paths.{key}")
        except ValueError as exc:
            failures.append(str(exc))
    write_policy = manifest.get("write_policy") if isinstance(manifest.get("write_policy"), dict) else {}
    if write_policy.get("production_writes_must_stay_under_workspace") is not True:
        failures.append(f"{BLOCK_WORKSPACE_MANIFEST_INVALID}: write_policy.production_writes_must_stay_under_workspace")
    if write_policy.get("repo_root_knowledge_write_allowed") is not False:
        failures.append(f"{BLOCK_WORKSPACE_MANIFEST_INVALID}: write_policy.repo_root_knowledge_write_allowed")
    return failures


def validate_workspace_cli_identity(
    manifest: dict[str, Any],
    *,
    factor_id: str | None = None,
    research_id: str | None = None,
) -> list[str]:
    failures: list[str] = []
    expected = {
        "factor_id": factor_id,
        "research_id": research_id,
    }
    for key, raw in expected.items():
        if raw is None:
            continue
        if str(manifest.get(key) or "") != str(raw):
            failures.append(
                f"{BLOCK_WORKSPACE_IDENTITY_INVALID}: {key} mismatch "
                f"manifest={manifest.get(key)!r} cli={raw!r}"
            )
    return failures


def workspace_manifest_path(workspace_root: Path) -> Path:
    return Path(workspace_root).expanduser() / "manifest.json"


def is_repo_root_vault(path: Path, repo_root: Path) -> bool:
    return Path(path).expanduser().resolve(strict=False) == (
        Path(repo_root).expanduser().resolve(strict=False) / "knowledge" / "因子工厂"
    )
