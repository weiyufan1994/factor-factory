from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from factor_factory.research_workspace import BLOCK_STEP3_COPY_OUTSIDE_WORKSPACE, assert_path_under_workspace
from factor_factory.runtime_context import load_runtime_manifest, manifest_factor_workspace, manifest_factorforge_root, manifest_report_id


BLOCK_STEP3_RUNTIME_COPY_INVALID = "BLOCK_STEP3_RUNTIME_COPY_INVALID"


def safe_report_id(report_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(report_id)).strip("_") or "unknown_report"


def runtime_copy_path(
    factorforge_root: Path,
    report_id: str,
    *,
    script_stem: str,
    workspace_root: Path | None = None,
) -> Path:
    safe_id = safe_report_id(report_id)
    if workspace_root is not None:
        return Path(workspace_root) / "step3_runtime" / safe_id / f"{script_stem}__{safe_id}.py"
    return factorforge_root / "runs" / safe_id / "step3_runtime" / f"{script_stem}__{safe_id}.py"


def _existing_runtime_copy_hash(
    target: Path,
    *,
    report_id: str,
    factor_workspace: Path | None,
) -> str | None:
    meta_path = target.with_suffix(".meta.json")
    if not target.exists() and not meta_path.exists():
        return None
    if (
        not target.is_file()
        or target.is_symlink()
        or not meta_path.is_file()
        or meta_path.is_symlink()
    ):
        raise SystemExit(f"{BLOCK_STEP3_RUNTIME_COPY_INVALID}: incomplete_or_linked_pair")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit(f"{BLOCK_STEP3_RUNTIME_COPY_INVALID}: metadata_unreadable") from exc
    observed_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    expected_workspace = str(factor_workspace) if factor_workspace else None
    if (
        meta.get("report_id") != report_id
        or meta.get("runtime_copy_path") != str(target)
        or meta.get("runtime_copy_hash") != observed_hash
        or meta.get("factor_workspace") != expected_workspace
    ):
        raise SystemExit(f"{BLOCK_STEP3_RUNTIME_COPY_INVALID}: existing_pair_mismatch")
    return observed_hash


def _atomic_publish_runtime_copy(
    *,
    source: Path,
    target: Path,
    meta: dict,
) -> None:
    """Replace a managed read-only runtime copy without chmod or in-place writes."""

    target.parent.mkdir(parents=True, exist_ok=True)
    meta_path = target.with_suffix(".meta.json")
    script_fd, script_tmp_raw = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    meta_fd, meta_tmp_raw = tempfile.mkstemp(
        prefix=f".{meta_path.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(script_fd)
    os.close(meta_fd)
    script_tmp = Path(script_tmp_raw)
    meta_tmp = Path(meta_tmp_raw)
    try:
        shutil.copy2(source, script_tmp)
        meta_tmp.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        meta_tmp.chmod(0o644)
        if hashlib.sha256(script_tmp.read_bytes()).hexdigest() != meta["runtime_copy_hash"]:
            raise SystemExit(f"{BLOCK_STEP3_RUNTIME_COPY_INVALID}: staged_hash_mismatch")
        os.replace(script_tmp, target)
        os.replace(meta_tmp, meta_path)
    finally:
        for pending in (script_tmp, meta_tmp):
            try:
                pending.unlink()
            except FileNotFoundError:
                pass


def maybe_reexec_from_template_copy(
    *,
    script_stem: str,
    report_id: str | None,
    manifest_path: str | None,
    default_factorforge_root: Path,
    source_path: Path,
    copy_env: str,
    copy_version: str,
    policy: str,
    template_path_env: str,
    runtime_copy_path_env: str,
    allow_canonical_env: str = "FACTORFORGE_ALLOW_CANONICAL_STEP3_TEMPLATE_EXECUTION",
) -> None:
    """Run a formal Step3 runner from a per-report copy.

    The canonical runner remains a template. Formal runs copy it into the
    report-local runtime directory, write a metadata record, set identity env
    vars, and re-exec the copy.
    """
    if os.getenv(copy_env) == "1":
        return
    if os.getenv(allow_canonical_env) == "1":
        return

    manifest = load_runtime_manifest(manifest_path) if manifest_path else None
    resolved_report_id = report_id or (manifest_report_id(manifest) if manifest else None)
    if not resolved_report_id:
        return

    factorforge_root = manifest_factorforge_root(manifest) if manifest else default_factorforge_root
    factor_workspace = manifest_factor_workspace(manifest) if manifest else None
    source = source_path.resolve()
    target = runtime_copy_path(
        factorforge_root,
        resolved_report_id,
        script_stem=script_stem,
        workspace_root=factor_workspace,
    )
    if factor_workspace is not None:
        try:
            assert_path_under_workspace(target, factor_workspace, label="step3_runtime_copy")
        except ValueError as exc:
            raise SystemExit(f"{BLOCK_STEP3_COPY_OUTSIDE_WORKSPACE}: {exc}") from exc
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    prior_runtime_hash = _existing_runtime_copy_hash(
        target,
        report_id=resolved_report_id,
        factor_workspace=factor_workspace,
    )
    runtime_hash = source_hash

    meta = {
        "version": "factorforge_step3_runtime_copy_v2" if factor_workspace else copy_version,
        "report_id": resolved_report_id,
        "factor_id": manifest.get("factor_id") if manifest else None,
        "research_id": manifest.get("research_id") if manifest else None,
        "factor_workspace": str(factor_workspace) if factor_workspace else None,
        "source_template_path": str(source),
        "runtime_copy_path": str(target),
        "source_template_sha256": source_hash,
        "baseline_template_hash": source_hash,
        "runtime_copy_hash": runtime_hash,
        "supersedes_runtime_copy_hash": prior_runtime_hash,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "policy": "formal_step3_runs_must_execute_workspace_copy" if factor_workspace else policy,
    }
    _atomic_publish_runtime_copy(
        source=source,
        target=target,
        meta=meta,
    )

    os.environ[copy_env] = "1"
    os.environ["FACTORFORGE_REPO_ROOT"] = str(source.parents[3])
    os.environ[template_path_env] = str(source)
    os.environ[runtime_copy_path_env] = str(target)
    os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])
