#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

BLOCK_FORMAL_RUN_ROOT_FORBIDDEN = "BLOCK_FORMAL_RUN_ROOT_FORBIDDEN"
BLOCK_FORMAL_RUN_ROOT_REUSE_MISMATCH = "BLOCK_FORMAL_RUN_ROOT_REUSE_MISMATCH"
BLOCK_PRODUCTION_SMOKE_ROOT_FORBIDDEN = "BLOCK_PRODUCTION_SMOKE_ROOT_FORBIDDEN"

PRODUCTION_WORKSPACE = Path(os.getenv("FACTORFORGE_PRODUCTION_WORKSPACE", "/home/ubuntu/.openclaw/workspace")).expanduser()
PRODUCTION_RUN_ARCHIVE_ROOT = Path(
    os.getenv("FACTORFORGE_PRODUCTION_RUN_ARCHIVE_ROOT", "/var/lib/factorforge/artifacts")
).expanduser()
FORMAL_MANIFEST_NAME = "formal_run_manifest.json"
FORMAL_RUN_MANIFEST_VERSION = "factorforge_formal_run_manifest_v1"
RUN_STATUS_VERSION = "factorforge_formal_run_status_v1"
ARCHIVE_INDEX_VERSION = "factorforge_formal_run_archive_index_v1"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def current_repo_sha() -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, capture_output=True, check=True)
    return proc.stdout.strip()


def _safe_slug(value: str) -> str:
    out = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return out[:96].strip("._-") or "run"


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _csv_paths(raw: str | None) -> list[Path]:
    if not raw:
        return []
    return [Path(item).expanduser() for item in raw.split(os.pathsep) if item.strip()]


def local_staging_roots() -> list[Path]:
    roots = [
        Path(os.getenv("FACTORFORGE_LOCAL_FORMAL_RUN_STAGING_ROOT", str(Path.home() / ".factorforge-staging"))),
        Path(os.getenv("FACTORFORGE_LOCAL_SMOKE_ROOT", str(Path.home() / ".factorforge-smoke"))),
    ]
    roots.extend(_csv_paths(os.getenv("FACTORFORGE_ALLOWED_FORMAL_RUN_ROOT_PREFIXES")))
    out: list[Path] = []
    for root in roots:
        resolved = _resolve(root)
        if resolved not in out:
            out.append(resolved)
    return out


def production_archive_root() -> Path:
    return _resolve(PRODUCTION_RUN_ARCHIVE_ROOT)


def _is_tmp_path(path: Path) -> bool:
    tmp_roots = [_resolve(Path("/tmp")), _resolve(Path("/private/tmp"))]
    return any(path == tmp or _is_relative_to(path, tmp) for tmp in tmp_roots)


def _workspace_forbidden_roots() -> list[Path]:
    workspace = _resolve(PRODUCTION_WORKSPACE)
    return [workspace / name for name in ["objects", "runs", "output", "tmp"]]


def assert_formal_run_root_allowed(root: Path) -> None:
    resolved = _resolve(root)
    if _is_tmp_path(resolved):
        raise SystemExit(f"{BLOCK_FORMAL_RUN_ROOT_FORBIDDEN}: /tmp roots are not valid formal artifact roots: {resolved}")
    repo = _resolve(REPO_ROOT)
    if resolved == repo or _is_relative_to(resolved, repo):
        raise SystemExit(f"{BLOCK_FORMAL_RUN_ROOT_FORBIDDEN}: repo worktree roots are not valid formal artifact roots: {resolved}")

    workspace = _resolve(PRODUCTION_WORKSPACE)
    archive = production_archive_root()
    if resolved == workspace:
        raise SystemExit(f"{BLOCK_FORMAL_RUN_ROOT_FORBIDDEN}: workspace top-level root is forbidden: {resolved}")
    for forbidden in _workspace_forbidden_roots():
        forbidden = _resolve(forbidden)
        if resolved == forbidden or _is_relative_to(resolved, forbidden):
            raise SystemExit(f"{BLOCK_FORMAL_RUN_ROOT_FORBIDDEN}: workspace top-level artifact root is forbidden: {resolved}")
    if resolved == archive:
        raise SystemExit(f"{BLOCK_FORMAL_RUN_ROOT_FORBIDDEN}: use a run_id child under the production archive root: {resolved}")
    if _is_relative_to(resolved, workspace) and not _is_relative_to(resolved, archive):
        raise SystemExit(f"{BLOCK_FORMAL_RUN_ROOT_FORBIDDEN}: production roots must live under {archive}: {resolved}")

    if _is_relative_to(resolved, archive):
        return
    for staging in local_staging_roots():
        if resolved == staging:
            raise SystemExit(f"{BLOCK_FORMAL_RUN_ROOT_FORBIDDEN}: use a run_id child under the local staging root: {resolved}")
        if _is_relative_to(resolved, staging):
            return
    allowed = ", ".join(str(path) for path in [archive, *local_staging_roots()])
    raise SystemExit(f"{BLOCK_FORMAL_RUN_ROOT_FORBIDDEN}: root={resolved} is outside allowed formal run roots: {allowed}")


def assert_smoke_root_allowed(root: Path) -> None:
    resolved = _resolve(root)
    if _is_tmp_path(resolved):
        raise SystemExit(f"{BLOCK_PRODUCTION_SMOKE_ROOT_FORBIDDEN}: smoke roots must not use /tmp: {resolved}")
    repo = _resolve(REPO_ROOT)
    if resolved == repo or _is_relative_to(resolved, repo):
        raise SystemExit(f"{BLOCK_PRODUCTION_SMOKE_ROOT_FORBIDDEN}: smoke roots must not be inside the repo worktree: {resolved}")
    workspace = _resolve(PRODUCTION_WORKSPACE)
    archive = production_archive_root()
    if resolved == workspace or _is_relative_to(resolved, workspace) or resolved == archive or _is_relative_to(resolved, archive):
        raise SystemExit(f"{BLOCK_PRODUCTION_SMOKE_ROOT_FORBIDDEN}: smoke roots must not write production workspace/archive paths: {resolved}")
    if not any(_is_relative_to(resolved, staging) for staging in local_staging_roots()):
        allowed = ", ".join(str(path) for path in local_staging_roots())
        raise SystemExit(f"{BLOCK_PRODUCTION_SMOKE_ROOT_FORBIDDEN}: smoke root={resolved} must be under local staging roots: {allowed}")


def assert_root_reuse_matches(root: Path, manifest: dict[str, Any]) -> None:
    resolved = _resolve(root)
    existing_manifest = resolved / FORMAL_MANIFEST_NAME
    if existing_manifest.exists():
        try:
            existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{BLOCK_FORMAL_RUN_ROOT_REUSE_MISMATCH}: existing manifest invalid: {existing_manifest}: {exc}") from exc
        if stable_hash(existing) != stable_hash(manifest):
            raise SystemExit(f"{BLOCK_FORMAL_RUN_ROOT_REUSE_MISMATCH}: existing manifest differs for root={resolved}")
        return
    if resolved.exists() and any(resolved.iterdir()):
        raise SystemExit(f"{BLOCK_FORMAL_RUN_ROOT_REUSE_MISMATCH}: existing non-empty root has no exact manifest: {resolved}")


def build_manifest(
    *,
    report_id: str,
    root: Path,
    pdf_sha256: str,
    step_scope: str,
    repo_sha: str | None = None,
    step1_provider: str | None = None,
    step1_model: str | None = None,
    step2_provider: str | None = None,
    step2_model: str | None = None,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    created = created_at_utc or now_utc()
    run_id_seed = {
        "created_at_utc": created,
        "report_id": report_id,
        "repo_sha": repo_sha or current_repo_sha(),
        "pdf_sha256": pdf_sha256,
        "step_scope": step_scope,
    }
    run_hash = stable_hash(run_id_seed)[:12]
    run_id = f"{created.replace(':', '').replace('-', '').replace('.', '')}_{_safe_slug(report_id)}_{step_scope}_{run_hash}"
    steps: dict[str, Any] = {}
    if step1_provider or step1_model:
        steps["step1"] = {"provider": step1_provider, "model": step1_model}
    if step2_provider or step2_model:
        steps["step2"] = {"provider": step2_provider, "model": step2_model}
    return {
        "manifest_version": FORMAL_RUN_MANIFEST_VERSION,
        "run_id": run_id,
        "created_at_utc": created,
        "report_id": report_id,
        "factorforge_root": str(_resolve(root)),
        "artifact_root": str(_resolve(root)),
        "report_pdf_sha256": pdf_sha256,
        "repo_sha": repo_sha or current_repo_sha(),
        "step_scope": step_scope,
        "steps": steps,
    }


def allocate_formal_run_root(
    *,
    report_id: str,
    pdf_sha256: str,
    step_scope: str,
    archive_root: Path | None = None,
    repo_sha: str | None = None,
    step1_provider: str | None = None,
    step1_model: str | None = None,
    step2_provider: str | None = None,
    step2_model: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    archive = _resolve(archive_root or production_archive_root())
    manifest_seed = build_manifest(
        report_id=report_id,
        root=archive / "placeholder",
        pdf_sha256=pdf_sha256,
        step_scope=step_scope,
        repo_sha=repo_sha,
        step1_provider=step1_provider,
        step1_model=step1_model,
        step2_provider=step2_provider,
        step2_model=step2_model,
    )
    run_id = manifest_seed["run_id"]
    root = archive / run_id
    manifest = build_manifest(
        report_id=report_id,
        root=root,
        pdf_sha256=pdf_sha256,
        step_scope=step_scope,
        repo_sha=repo_sha,
        step1_provider=step1_provider,
        step1_model=step1_model,
        step2_provider=step2_provider,
        step2_model=step2_model,
        created_at_utc=manifest_seed["created_at_utc"],
    )
    assert_formal_run_root_allowed(root)
    root.mkdir(parents=True, exist_ok=False)
    (root / FORMAL_MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status = {
        "version": RUN_STATUS_VERSION,
        "run_id": run_id,
        "report_id": report_id,
        "status": "allocated",
        "created_at_utc": manifest["created_at_utc"],
        "runtime_context_written": False,
        "worker_started": False,
    }
    (root / "run_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_entry = {
        "run_id": run_id,
        "report_id": report_id,
        "root": str(root),
        "repo_sha": manifest["repo_sha"],
        "pdf_sha256": pdf_sha256,
        "step_scope": step_scope,
        "created_at_utc": manifest["created_at_utc"],
    }
    (root / "archive_index.json").write_text(
        json.dumps({"version": ARCHIVE_INDEX_VERSION, "runs": [index_entry]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    archive.mkdir(parents=True, exist_ok=True)
    global_index_path = archive / "archive_index.json"
    global_index = {"version": ARCHIVE_INDEX_VERSION, "runs": []}
    if global_index_path.exists():
        try:
            global_index = json.loads(global_index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            global_index = {"version": ARCHIVE_INDEX_VERSION, "runs": []}
    runs = [item for item in global_index.get("runs", []) if isinstance(item, dict) and item.get("run_id") != run_id]
    runs.append(index_entry)
    global_index["runs"] = runs
    global_index_path.write_text(json.dumps(global_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return root, manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    alloc = sub.add_parser("allocate")
    alloc.add_argument("--report-id", required=True)
    alloc.add_argument("--pdf-sha256", required=True)
    alloc.add_argument("--step-scope", required=True)
    alloc.add_argument("--archive-root")
    alloc.add_argument("--repo-sha")
    alloc.add_argument("--step1-provider")
    alloc.add_argument("--step1-model")
    alloc.add_argument("--step2-provider")
    alloc.add_argument("--step2-model")
    args = ap.parse_args()
    if args.cmd == "allocate":
        root, manifest = allocate_formal_run_root(
            report_id=args.report_id,
            pdf_sha256=args.pdf_sha256,
            step_scope=args.step_scope,
            archive_root=Path(args.archive_root).expanduser() if args.archive_root else None,
            repo_sha=args.repo_sha,
            step1_provider=args.step1_provider,
            step1_model=args.step1_model,
            step2_provider=args.step2_provider,
            step2_model=args.step2_model,
        )
        print(json.dumps({"root": str(root), "manifest": manifest}, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
