import json
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _make_source_repo(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "factor_factory").mkdir(parents=True)
    (source / "scripts").mkdir(parents=True)
    shutil.copy2(
        PROJECT_ROOT / "factor_factory" / "__init__.py",
        source / "factor_factory" / "__init__.py",
    )
    shutil.copy2(
        PROJECT_ROOT / "factor_factory" / "research_workspace.py",
        source / "factor_factory" / "research_workspace.py",
    )
    shutil.copy2(
        PROJECT_ROOT / "scripts" / "init_factor_research_workspace.py",
        source / "scripts" / "init_factor_research_workspace.py",
    )
    (source / "README.md").write_text("fixture\n", encoding="utf-8")

    _git(source, "init")
    _git(source, "config", "user.name", "Factor Forge Test")
    _git(source, "config", "user.email", "factor-forge-test@example.invalid")
    _git(source, "add", "README.md", "factor_factory", "scripts")
    _git(source, "commit", "-m", "Create allocator fixture")
    return source


def _allocator(tmp_path: Path, source: Path):
    from factor_factory.console.worktree_allocator import FactorWorktreeAllocator

    return FactorWorktreeAllocator(
        source_repo=source,
        configured_root=tmp_path / "worktrees",
        run_state_root=tmp_path / "run-state",
        base_ref="HEAD",
    )


def test_allocates_detached_isolated_worktrees_and_workspaces(tmp_path):
    from factor_factory.console.worktree_allocator import (
        WorktreeAllocationError,
        assert_factor_output_path,
    )
    from factor_factory.research_workspace import (
        load_workspace_manifest,
        validate_workspace_manifest,
        workspace_manifest_path,
    )

    source = _make_source_repo(tmp_path)
    source_commit = _git(source, "rev-parse", "HEAD").stdout.strip()
    allocator = _allocator(tmp_path, source)

    first = allocator.allocate(
        factor_id="FACTOR_ALPHA",
        research_id="research_20260801_a",
        report_id="report_alpha",
    )
    second = allocator.allocate(
        factor_id="FACTOR_BETA",
        research_id="research_20260801_b",
        report_id="report_beta",
    )

    assert first.worktree_path == (
        tmp_path / "worktrees" / "FACTOR_ALPHA" / "research_20260801_a" / "repo"
    ).resolve()
    assert second.worktree_path == (
        tmp_path / "worktrees" / "FACTOR_BETA" / "research_20260801_b" / "repo"
    ).resolve()
    assert first.workspace_path == (
        first.worktree_path / "factor_research" / "FACTOR_ALPHA" / "research_20260801_a"
    )
    assert second.workspace_path == (
        second.worktree_path / "factor_research" / "FACTOR_BETA" / "research_20260801_b"
    )
    assert first.worktree_path != second.worktree_path
    assert first.workspace_path != second.workspace_path

    assert _git(first.worktree_path, "rev-parse", "HEAD").stdout.strip() == source_commit
    assert _git(second.worktree_path, "rev-parse", "HEAD").stdout.strip() == source_commit
    assert _git(first.worktree_path, "symbolic-ref", "--quiet", "HEAD", check=False).returncode != 0
    assert _git(second.worktree_path, "symbolic-ref", "--quiet", "HEAD", check=False).returncode != 0

    first_workspace_manifest = load_workspace_manifest(workspace_manifest_path(first.workspace_path))
    second_workspace_manifest = load_workspace_manifest(workspace_manifest_path(second.workspace_path))
    assert validate_workspace_manifest(first_workspace_manifest) == []
    assert validate_workspace_manifest(second_workspace_manifest) == []
    assert first_workspace_manifest["repo_root"] == str(first.worktree_path)
    assert second_workspace_manifest["repo_root"] == str(second.worktree_path)

    first_payload = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    second_payload = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert first.manifest_path == (
        tmp_path / "run-state" / "FACTOR_ALPHA" / "research_20260801_a" / "worktree_allocation.json"
    )
    assert second.manifest_path == (
        tmp_path / "run-state" / "FACTOR_BETA" / "research_20260801_b" / "worktree_allocation.json"
    )
    assert first_payload["source_repo"] == str(source.resolve())
    assert first_payload["base_commit"] == source_commit
    assert first_payload["worktree_path"] == str(first.worktree_path)
    assert first_payload["workspace_path"] == str(first.workspace_path)
    assert first_payload["factor_id"] == "FACTOR_ALPHA"
    assert first_payload["research_id"] == "research_20260801_a"
    assert first_payload["report_id"] == "report_alpha"
    assert first_payload["created_at"].endswith("Z")
    assert first_payload["writable_roots"] == [str(first.workspace_path)]

    first_output = assert_factor_output_path(
        Path("objects") / "alpha.json",
        first.workspace_path,
    )
    second_output = assert_factor_output_path(
        Path("objects") / "beta.json",
        second.workspace_path,
    )
    first_output.write_text('{"factor":"alpha"}\n', encoding="utf-8")
    second_output.write_text('{"factor":"beta"}\n', encoding="utf-8")
    assert first_output.read_text(encoding="utf-8") != second_output.read_text(encoding="utf-8")
    assert not (first.workspace_path / "objects" / "beta.json").exists()
    assert not (second.workspace_path / "objects" / "alpha.json").exists()

    with pytest.raises(WorktreeAllocationError, match="BLOCK_FACTORFORGE_CONSOLE_WORKTREE_PATH_INVALID"):
        assert_factor_output_path(second_output, first.workspace_path, label="cross_factor_output")
    with pytest.raises(WorktreeAllocationError, match="BLOCK_FACTORFORGE_CONSOLE_WORKTREE_PATH_INVALID"):
        assert_factor_output_path(first_output, second.workspace_path, label="cross_factor_output")

    assert _git(source, "status", "--porcelain=v1", "--untracked-files=all").stdout == ""


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("factor_id", "../escape"),
        ("factor_id", "factor/escape"),
        ("research_id", ".."),
        ("research_id", "research\\escape"),
        ("report_id", "/absolute"),
    ],
)
def test_rejects_unsafe_identities_before_creating_paths(tmp_path, field, unsafe_value):
    from factor_factory.console.worktree_allocator import WorktreeAllocationError

    source = _make_source_repo(tmp_path)
    allocator = _allocator(tmp_path, source)
    identities = {
        "factor_id": "FACTOR_SAFE",
        "research_id": "research_safe",
        "report_id": "report_safe",
    }
    identities[field] = unsafe_value

    with pytest.raises(WorktreeAllocationError, match="BLOCK_FACTORFORGE_CONSOLE_WORKTREE_IDENTITY_INVALID"):
        allocator.allocate(**identities)

    assert list((tmp_path / "worktrees").iterdir()) == []
    assert list((tmp_path / "run-state").iterdir()) == []


def test_rejects_dirty_non_bare_source_without_allocating(tmp_path):
    from factor_factory.console.worktree_allocator import WorktreeAllocationError

    source = _make_source_repo(tmp_path)
    (source / "dirty.txt").write_text("must block\n", encoding="utf-8")
    allocator = _allocator(tmp_path, source)

    with pytest.raises(WorktreeAllocationError, match="BLOCK_FACTORFORGE_CONSOLE_WORKTREE_SOURCE_DIRTY"):
        allocator.allocate(
            factor_id="FACTOR_DIRTY",
            research_id="research_dirty",
            report_id="report_dirty",
        )

    assert list((tmp_path / "worktrees").iterdir()) == []
    assert not (tmp_path / "run-state" / "FACTOR_DIRTY").exists()


def test_rejects_existing_allocation_paths_without_overwrite(tmp_path):
    from factor_factory.console.worktree_allocator import WorktreeAllocationError

    source = _make_source_repo(tmp_path)
    allocator = _allocator(tmp_path, source)
    existing = tmp_path / "worktrees" / "FACTOR_EXISTING" / "research_existing"
    existing.mkdir(parents=True)
    marker = existing / "do-not-overwrite.txt"
    marker.write_text("preserve\n", encoding="utf-8")

    with pytest.raises(WorktreeAllocationError, match="BLOCK_FACTORFORGE_CONSOLE_WORKTREE_PATH_EXISTS"):
        allocator.allocate(
            factor_id="FACTOR_EXISTING",
            research_id="research_existing",
            report_id="report_existing",
        )

    assert marker.read_text(encoding="utf-8") == "preserve\n"
    assert not (existing / "repo").exists()
