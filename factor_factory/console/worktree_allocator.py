from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

from factor_factory.research_workspace import (
    assert_path_under_workspace,
    load_workspace_manifest,
    validate_workspace_manifest,
    workspace_manifest_path,
)


ALLOCATION_CONTRACT_VERSION = "factorforge_console_worktree_allocation_v1"

BLOCK_WORKTREE_IDENTITY_INVALID = "BLOCK_FACTORFORGE_CONSOLE_WORKTREE_IDENTITY_INVALID"
BLOCK_WORKTREE_SOURCE_INVALID = "BLOCK_FACTORFORGE_CONSOLE_WORKTREE_SOURCE_INVALID"
BLOCK_WORKTREE_SOURCE_DIRTY = "BLOCK_FACTORFORGE_CONSOLE_WORKTREE_SOURCE_DIRTY"
BLOCK_WORKTREE_PATH_INVALID = "BLOCK_FACTORFORGE_CONSOLE_WORKTREE_PATH_INVALID"
BLOCK_WORKTREE_PATH_EXISTS = "BLOCK_FACTORFORGE_CONSOLE_WORKTREE_PATH_EXISTS"
BLOCK_WORKTREE_GIT_FAILED = "BLOCK_FACTORFORGE_CONSOLE_WORKTREE_GIT_FAILED"
BLOCK_WORKTREE_WORKSPACE_INVALID = "BLOCK_FACTORFORGE_CONSOLE_WORKTREE_WORKSPACE_INVALID"

_SAFE_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SAFE_BASE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\Z")
_IMPLEMENTATION_MODES = {"operator", "direct_code", "hybrid", "unknown"}


class WorktreeAllocationError(RuntimeError):
    """Raised when a worktree allocation violates an isolation invariant."""


@dataclass(frozen=True)
class WorktreeAllocation:
    factor_id: str
    research_id: str
    report_id: str
    source_repo: Path
    base_commit: str
    worktree_path: Path
    workspace_path: Path
    manifest_path: Path
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": ALLOCATION_CONTRACT_VERSION,
            "factor_id": self.factor_id,
            "research_id": self.research_id,
            "report_id": self.report_id,
            "source_repo": str(self.source_repo),
            "base_commit": self.base_commit,
            "worktree_path": str(self.worktree_path),
            "workspace_path": str(self.workspace_path),
            "created_at": self.created_at,
            "writable_roots": [str(self.workspace_path)],
            "write_policy": {
                "all_factor_outputs_must_stay_under_workspace": True,
                "source_repo_read_only": True,
                "shared_data_read_only": True,
                "cross_factor_writes_allowed": False,
            },
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_identity(value: str, *, label: str) -> str:
    candidate = str(value or "")
    if not _SAFE_IDENTITY_RE.fullmatch(candidate) or ".." in candidate:
        raise WorktreeAllocationError(
            f"{BLOCK_WORKTREE_IDENTITY_INVALID}: unsafe {label}={candidate!r}"
        )
    return candidate


def _validate_base_ref(value: str) -> str:
    candidate = str(value or "")
    if (
        not _SAFE_BASE_REF_RE.fullmatch(candidate)
        or ".." in candidate
        or "//" in candidate
        or "@{" in candidate
    ):
        raise WorktreeAllocationError(
            f"{BLOCK_WORKTREE_SOURCE_INVALID}: unsafe base_ref={candidate!r}"
        )
    return candidate


def _assert_path_under(path: Path, root: Path, *, label: str) -> None:
    candidate = path.expanduser().resolve(strict=False)
    resolved_root = root.expanduser().resolve(strict=False)
    if candidate == resolved_root or not _is_relative_to(candidate, resolved_root):
        raise WorktreeAllocationError(
            f"{BLOCK_WORKTREE_PATH_INVALID}: {label}={candidate} root={resolved_root}"
        )


def _assert_roots_do_not_overlap(source_repo: Path, configured_root: Path, run_state_root: Path) -> None:
    roots = (
        ("configured_root", configured_root),
        ("run_state_root", run_state_root),
    )
    for label, root in roots:
        if root == source_repo or _is_relative_to(root, source_repo) or _is_relative_to(source_repo, root):
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_PATH_INVALID}: {label} must not overlap source_repo"
            )
    if (
        configured_root == run_state_root
        or _is_relative_to(configured_root, run_state_root)
        or _is_relative_to(run_state_root, configured_root)
    ):
        raise WorktreeAllocationError(
            f"{BLOCK_WORKTREE_PATH_INVALID}: configured_root and run_state_root must not overlap"
        )


def _assert_no_symlink_components(path: Path, root: Path, *, label: str) -> None:
    resolved_root = root.resolve(strict=False)
    relative = path.relative_to(resolved_root)
    cursor = resolved_root
    for component in relative.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_PATH_INVALID}: symlink in {label} path: {cursor}"
            )


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    failure_token: str,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise WorktreeAllocationError(f"{failure_token}: {detail}") from exc


def _git(repo: Path, *args: str, failure_token: str = BLOCK_WORKTREE_GIT_FAILED) -> str:
    result = _run_command(
        ["git", "-C", str(repo), *args],
        failure_token=failure_token,
    )
    return result.stdout.strip()


def assert_factor_output_path(path: Path, workspace_path: Path, *, label: str = "output") -> Path:
    """Return the resolved output path only when it is inside one factor workspace."""

    workspace = Path(workspace_path).expanduser().resolve(strict=False)
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    candidate = candidate.resolve(strict=False)
    try:
        assert_path_under_workspace(candidate, workspace, label=label)
    except ValueError as exc:
        raise WorktreeAllocationError(f"{BLOCK_WORKTREE_PATH_INVALID}: {exc}") from exc
    return candidate


class FactorWorktreeAllocator:
    """Allocate server-owned, detached Git worktrees for isolated factor runs."""

    def __init__(
        self,
        *,
        source_repo: Path,
        configured_root: Path,
        run_state_root: Path,
        base_ref: str,
    ) -> None:
        self.source_repo = Path(source_repo).expanduser().resolve(strict=False)
        self.configured_root = Path(configured_root).expanduser().resolve(strict=False)
        self.run_state_root = Path(run_state_root).expanduser().resolve(strict=False)
        self.base_ref = _validate_base_ref(base_ref)

        if not self.source_repo.is_dir():
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_SOURCE_INVALID}: source_repo does not exist: {self.source_repo}"
            )
        _assert_roots_do_not_overlap(
            self.source_repo,
            self.configured_root,
            self.run_state_root,
        )
        self._validate_git_source()
        self.base_commit = self._resolve_base_commit()
        self.configured_root.mkdir(parents=True, exist_ok=True)
        self.run_state_root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _worktree_lock(self) -> Iterator[None]:
        lock_path = self.run_state_root / ".git-worktree-allocation.lock"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _validate_git_source(self) -> None:
        inside = _git(
            self.source_repo,
            "rev-parse",
            "--is-inside-work-tree",
            failure_token=BLOCK_WORKTREE_SOURCE_INVALID,
        )
        bare = _git(
            self.source_repo,
            "rev-parse",
            "--is-bare-repository",
            failure_token=BLOCK_WORKTREE_SOURCE_INVALID,
        )
        if inside != "true" and bare != "true":
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_SOURCE_INVALID}: source_repo is not a Git worktree or bare repository"
            )

    def _assert_source_clean(self) -> None:
        is_bare = _git(
            self.source_repo,
            "rev-parse",
            "--is-bare-repository",
            failure_token=BLOCK_WORKTREE_SOURCE_INVALID,
        )
        if is_bare == "true":
            return
        status = _git(
            self.source_repo,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            failure_token=BLOCK_WORKTREE_SOURCE_INVALID,
        )
        if status:
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_SOURCE_DIRTY}: source_repo has tracked or untracked changes"
            )

    def _resolve_base_commit(self) -> str:
        commit = _git(
            self.source_repo,
            "rev-parse",
            "--verify",
            f"{self.base_ref}^{{commit}}",
            failure_token=BLOCK_WORKTREE_SOURCE_INVALID,
        )
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_SOURCE_INVALID}: base_ref did not resolve to a commit"
            )
        return commit.lower()

    def _allocation_paths(self, factor_id: str, research_id: str) -> tuple[Path, Path, Path]:
        run_root = self.configured_root / factor_id / research_id
        worktree_path = run_root / "repo"
        state_root = self.run_state_root / factor_id / research_id
        _assert_path_under(run_root, self.configured_root, label="run_root")
        _assert_path_under(worktree_path, self.configured_root, label="worktree_path")
        _assert_path_under(state_root, self.run_state_root, label="state_root")
        _assert_no_symlink_components(run_root, self.configured_root, label="run_root")
        _assert_no_symlink_components(state_root, self.run_state_root, label="state_root")
        return run_root, worktree_path, state_root

    def _validate_initialized_workspace(
        self,
        *,
        worktree_path: Path,
        workspace_path: Path,
        factor_id: str,
        research_id: str,
        report_id: str,
        base_commit: str,
    ) -> None:
        expected_workspace = (
            worktree_path / "factor_research" / factor_id / research_id
        ).resolve(strict=False)
        if workspace_path.resolve(strict=False) != expected_workspace:
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_WORKSPACE_INVALID}: workspace path mismatch"
            )
        _assert_path_under(workspace_path, worktree_path, label="workspace_path")

        manifest_file = workspace_manifest_path(workspace_path)
        if not manifest_file.is_file():
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_WORKSPACE_INVALID}: workspace manifest missing"
            )
        manifest = load_workspace_manifest(manifest_file)
        failures = validate_workspace_manifest(manifest)
        if failures:
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_WORKSPACE_INVALID}: {'; '.join(failures)}"
            )

        expected_values = {
            "factor_id": factor_id,
            "research_id": research_id,
            "root_report_id": report_id,
            "active_report_id": report_id,
            "repo_root": str(worktree_path.resolve()),
            "factorforge_root": str(worktree_path.resolve()),
            "workspace_root": str(workspace_path.resolve()),
        }
        for key, expected in expected_values.items():
            if str(manifest.get(key) or "") != expected:
                raise WorktreeAllocationError(
                    f"{BLOCK_WORKTREE_WORKSPACE_INVALID}: {key} mismatch"
                )

        provenance = manifest.get("provenance")
        if not isinstance(provenance, dict) or str(provenance.get("repo_commit") or "") != base_commit:
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_WORKSPACE_INVALID}: provenance.repo_commit mismatch"
            )
        paths = manifest.get("paths")
        if not isinstance(paths, dict) or not paths:
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_WORKSPACE_INVALID}: writable paths missing"
            )
        for key, raw_path in paths.items():
            assert_factor_output_path(
                Path(str(raw_path)),
                workspace_path,
                label=f"workspace.paths.{key}",
            )

        write_policy = manifest.get("write_policy")
        required_policy = {
            "production_writes_must_stay_under_workspace": True,
            "repo_root_knowledge_write_allowed": False,
            "repo_root_data_write_allowed": False,
        }
        if not isinstance(write_policy, dict) or any(
            write_policy.get(key) is not expected for key, expected in required_policy.items()
        ):
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_WORKSPACE_INVALID}: write policy mismatch"
            )

        # Any file created or modified by initialization must remain inside the factor workspace.
        changed_paths: set[str] = set()
        for args in (
            ("diff", "--name-only", "-z"),
            ("diff", "--cached", "--name-only", "-z"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
            ("ls-files", "--others", "--ignored", "--exclude-standard", "-z"),
        ):
            output = _git(worktree_path, *args)
            changed_paths.update(item for item in output.split("\0") if item)
        for relative_path in changed_paths:
            assert_factor_output_path(
                worktree_path / relative_path,
                workspace_path,
                label="initializer_write",
            )

    def allocate(
        self,
        *,
        factor_id: str,
        research_id: str,
        report_id: str,
        implementation_mode: str = "unknown",
    ) -> WorktreeAllocation:
        factor_id = _validate_identity(factor_id, label="factor_id")
        research_id = _validate_identity(research_id, label="research_id")
        report_id = _validate_identity(report_id, label="report_id")
        if implementation_mode not in _IMPLEMENTATION_MODES:
            raise WorktreeAllocationError(
                f"{BLOCK_WORKTREE_IDENTITY_INVALID}: invalid implementation_mode={implementation_mode!r}"
            )

        with self._worktree_lock():
            self._validate_git_source()
            self._assert_source_clean()
            base_commit = self.base_commit
            run_root, worktree_path, state_root = self._allocation_paths(
                factor_id,
                research_id,
            )
            if run_root.exists() or state_root.exists():
                raise WorktreeAllocationError(
                    f"{BLOCK_WORKTREE_PATH_EXISTS}: allocation path already exists"
                )

            run_root.mkdir(parents=True, exist_ok=False)
            state_root.mkdir(parents=True, exist_ok=False)
            _git(
                self.source_repo,
                "worktree",
                "add",
                "--detach",
                str(worktree_path),
                base_commit,
            )

            checked_out_commit = _git(worktree_path, "rev-parse", "HEAD")
            if checked_out_commit.lower() != base_commit:
                raise WorktreeAllocationError(
                    f"{BLOCK_WORKTREE_GIT_FAILED}: detached worktree commit mismatch"
                )
            symbolic_ref = subprocess.run(
                ["git", "-C", str(worktree_path), "symbolic-ref", "--quiet", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
            )
            if symbolic_ref.returncode == 0:
                raise WorktreeAllocationError(
                    f"{BLOCK_WORKTREE_GIT_FAILED}: allocated worktree is not detached"
                )

            init_script = worktree_path / "scripts" / "init_factor_research_workspace.py"
            if not init_script.is_file():
                raise WorktreeAllocationError(
                    f"{BLOCK_WORKTREE_WORKSPACE_INVALID}: init script missing at pinned commit"
                )
            _run_command(
                [
                    sys.executable,
                    str(init_script),
                    "--factor-id",
                    factor_id,
                    "--research-id",
                    research_id,
                    "--report-id",
                    report_id,
                    "--factorforge-root",
                    str(worktree_path),
                    "--implementation-mode",
                    implementation_mode,
                ],
                cwd=worktree_path,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                failure_token=BLOCK_WORKTREE_WORKSPACE_INVALID,
            )

            workspace_path = (
                worktree_path / "factor_research" / factor_id / research_id
            ).resolve(strict=False)
            self._validate_initialized_workspace(
                worktree_path=worktree_path,
                workspace_path=workspace_path,
                factor_id=factor_id,
                research_id=research_id,
                report_id=report_id,
                base_commit=base_commit,
            )
            self._assert_source_clean()

            allocation = WorktreeAllocation(
                factor_id=factor_id,
                research_id=research_id,
                report_id=report_id,
                source_repo=self.source_repo,
                base_commit=base_commit,
                worktree_path=worktree_path.resolve(),
                workspace_path=workspace_path,
                manifest_path=state_root / "worktree_allocation.json",
                created_at=_utc_now(),
            )
            with allocation.manifest_path.open("x", encoding="utf-8") as manifest_file:
                json.dump(
                    allocation.to_dict(),
                    manifest_file,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                manifest_file.write("\n")
            return allocation
