from __future__ import annotations

import fcntl
import os
from pathlib import Path

import pytest

from factor_factory.research_org.contracts import (
    ResearchOrganizationError,
    read_workspace_json,
    workspace_file_lock,
    write_workspace_json,
)
from factor_factory.research_org.runtime_trust import load_runtime_trust_store


def test_strict_json_rejects_duplicate_keys_and_non_finite_numbers(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    duplicate = workspace / "duplicate.json"
    duplicate.write_text('{"factor_id":"A","factor_id":"B"}\n', encoding="utf-8")
    with pytest.raises(ResearchOrganizationError, match="unreadable_json"):
        read_workspace_json(workspace, "duplicate.json")

    non_finite = workspace / "non_finite.json"
    non_finite.write_text('{"value":NaN}\n', encoding="utf-8")
    with pytest.raises(ResearchOrganizationError, match="unreadable_json"):
        read_workspace_json(workspace, "non_finite.json")


def test_stable_reader_rejects_hardlinked_contract_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "source.json"
    source.write_text('{"value":1}\n', encoding="utf-8")
    os.link(source, workspace / "alias.json")
    with pytest.raises(ResearchOrganizationError, match="unsafe_or_oversized"):
        read_workspace_json(workspace, "source.json")


def test_trust_store_validation_does_not_create_missing_keys(tmp_path: Path) -> None:
    trust_root = tmp_path / "missing-trust"
    with pytest.raises(ResearchOrganizationError, match="trust_root_missing"):
        load_runtime_trust_store(
            trust_root,
            installation_id="missing-trust-test-001",
        )
    assert not trust_root.exists()


def test_openat_writer_blocks_parent_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    parent = workspace / "objects"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    backup = workspace / "objects.original"
    original_open = os.open
    swapped = False

    def swap_before_parent_open(
        path: str | bytes | int,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "objects" and dir_fd is not None and not swapped:
            swapped = True
            parent.rename(backup)
            parent.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_before_parent_open)
    with pytest.raises(ResearchOrganizationError, match="unsafe_parent"):
        write_workspace_json(
            workspace,
            "objects/runtime/state.json",
            {"state": "ACTIVE"},
        )
    assert not (outside / "runtime" / "state.json").exists()


def test_workspace_lock_rejects_inode_replacement_after_flock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = workspace / "plan.json"
    plan.write_text('{"version":1}\n', encoding="utf-8")
    backup = workspace / "plan.original.json"
    original_flock = fcntl.flock
    swapped = False

    def replace_after_lock(descriptor: int, operation: int) -> None:
        nonlocal swapped
        original_flock(descriptor, operation)
        if operation == fcntl.LOCK_EX and not swapped:
            swapped = True
            plan.rename(backup)
            plan.write_text('{"version":2}\n', encoding="utf-8")

    monkeypatch.setattr(fcntl, "flock", replace_after_lock)
    with (
        pytest.raises(ResearchOrganizationError, match="lock_target_replaced"),
        workspace_file_lock(workspace, "plan.json"),
    ):
        raise AssertionError("replaced lock target must never be admitted")
