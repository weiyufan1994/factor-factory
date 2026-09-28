from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from factor_factory.step3.template_runtime import (
    BLOCK_STEP3_RUNTIME_COPY_INVALID,
    _atomic_publish_runtime_copy,
    _existing_runtime_copy_hash,
)


def _meta(target: Path, source: Path, report_id: str, workspace: Path, prior=None):
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return {
        "version": "factorforge_step3_runtime_copy_v2",
        "report_id": report_id,
        "factor_workspace": str(workspace),
        "source_template_path": str(source),
        "runtime_copy_path": str(target),
        "source_template_sha256": digest,
        "baseline_template_hash": digest,
        "runtime_copy_hash": digest,
        "supersedes_runtime_copy_hash": prior,
        "policy": "formal_step3_runs_must_execute_workspace_copy",
    }


def test_atomic_publish_replaces_managed_read_only_copy(tmp_path):
    workspace = tmp_path / "workspace"
    target = workspace / "step3_runtime" / "R" / "run_step3__R.py"
    target.parent.mkdir(parents=True)
    old_source = tmp_path / "old.py"
    old_source.write_text("OLD = True\n", encoding="utf-8")
    old_meta = _meta(target, old_source, "R", workspace)
    _atomic_publish_runtime_copy(source=old_source, target=target, meta=old_meta)
    target.chmod(0o444)
    prior = _existing_runtime_copy_hash(
        target, report_id="R", factor_workspace=workspace
    )

    new_source = tmp_path / "new.py"
    new_source.write_text("NEW = True\n", encoding="utf-8")
    new_meta = _meta(target, new_source, "R", workspace, prior=prior)
    _atomic_publish_runtime_copy(source=new_source, target=target, meta=new_meta)

    assert target.read_bytes() == new_source.read_bytes()
    published_meta = json.loads(target.with_suffix(".meta.json").read_text())
    assert published_meta["supersedes_runtime_copy_hash"] == prior
    assert _existing_runtime_copy_hash(
        target, report_id="R", factor_workspace=workspace
    ) == new_meta["runtime_copy_hash"]


def test_existing_runtime_copy_without_meta_blocks(tmp_path):
    workspace = tmp_path / "workspace"
    target = workspace / "step3_runtime" / "R" / "run_step3__R.py"
    target.parent.mkdir(parents=True)
    target.write_text("UNBOUND = True\n", encoding="utf-8")
    with pytest.raises(SystemExit, match=BLOCK_STEP3_RUNTIME_COPY_INVALID):
        _existing_runtime_copy_hash(
            target, report_id="R", factor_workspace=workspace
        )


def test_tampered_runtime_copy_blocks_before_replacement(tmp_path):
    workspace = tmp_path / "workspace"
    target = workspace / "step3_runtime" / "R" / "run_step3__R.py"
    target.parent.mkdir(parents=True)
    source = tmp_path / "source.py"
    source.write_text("BOUND = True\n", encoding="utf-8")
    _atomic_publish_runtime_copy(
        source=source,
        target=target,
        meta=_meta(target, source, "R", workspace),
    )
    target.write_text("TAMPERED = True\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="existing_pair_mismatch"):
        _existing_runtime_copy_hash(
            target, report_id="R", factor_workspace=workspace
        )
