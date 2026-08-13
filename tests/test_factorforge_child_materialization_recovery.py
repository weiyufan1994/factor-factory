from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_materializer():
    path = (
        REPO_ROOT
        / "skills/factor-forge-step6/scripts/materialize_step6_child_revision.py"
    )
    spec = importlib.util.spec_from_file_location(
        "factorforge_child_materializer_recovery_under_test",
        path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _legacy_materializer_fixture(root: Path) -> tuple[str, str]:
    parent = "PARENT"
    child = "PARENT__LOOP01__REVISION"
    _write_json(
        root / f"objects/handoff/handoff_to_step3b__{parent}.json",
        {
            "new_branch_id": "REVISION",
            "parent_run_id": "parent_run_001",
        },
    )
    _write_json(
        root
        / f"objects/research_iteration_master/research_iteration_master__{parent}.json",
        {
            "research_judgment": {
                "research_memo": {
                    "revision_strategy": {
                        "loop_authorization": "approved_for_step3b_handoff"
                    }
                }
            }
        },
    )
    _write_json(
        root / f"objects/alpha_idea_master/alpha_idea_master__{parent}.json",
        {"report_id": parent},
    )
    _write_json(
        root / f"objects/factor_spec_master/factor_spec_master__{parent}.json",
        {
            "report_id": parent,
            "canonical_spec": {"formula_text": "close"},
            "artifact_identity": {"report_id": parent},
        },
    )
    _write_json(
        root / f"objects/data_prep_master/data_prep_master__{parent}.json",
        {
            "report_id": parent,
            "factor_id": "FACTOR",
            "local_input_paths": {},
            "minute_derived_state_requirements": [],
        },
    )
    _write_json(
        root
        / "objects/research_iteration_master/revision_council"
        / parent
        / f"main_agent_council_synthesis__{parent}.json",
        {
            "contract_version": "factorforge_main_agent_council_synthesis_v1",
            "report_id": parent,
            "producer": "test_main_agent",
            "canonical_write_permission": False,
            "execution_allowed_by_default": False,
            "human_approval_required": True,
            "selected_revision": {
                "law_id": "invert_close",
                "child_formula": "-close",
                "expected_metric_signature": {"rank_ic": "negative_to_positive"},
                "falsification_tests": ["rank_ic_remains_negative"],
                "kill_criteria": ["no_improvement"],
            },
        },
    )
    return parent, child


def _prepared_transaction(module, root: Path):
    parent = "PARENT"
    child = "CHILD"
    source_handoff_sha256 = "a" * 64
    staging = module._prepare_staging_directory(root, parent, child)
    targets = {
        "alpha_idea_master": root / "objects/alpha/child.json",
        "daily_snapshot": root / "runs/CHILD/input.parquet",
    }
    entries = [
        module._stage_materialization_bytes(
            root=root,
            staging_directory=staging,
            kind=kind,
            target_path=target,
            data=f"payload:{kind}".encode("utf-8"),
        )
        for kind, target in targets.items()
    ]
    report_payload = {
        "materialization_version": module.MATERIALIZATION_VERSION,
        "created_at_utc": "2026-08-12T00:00:00Z",
        "workspace_root": str(root.resolve()),
        "parent_report_id": parent,
        "child_report_id": child,
        "source_handoff_sha256": source_handoff_sha256,
        "materialization_target_hashes": module._target_hash_projection(entries),
    }
    manifest_path, _manifest = module._write_prepared_materialization_manifest(
        root=root,
        parent=parent,
        child=child,
        source_handoff_sha256=source_handoff_sha256,
        entries=entries,
        report_payload=report_payload,
    )
    return parent, child, source_handoff_sha256, targets, manifest_path


def test_child_materialization_recovers_after_interrupted_atomic_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_materializer()
    root = tmp_path / "workspace"
    root.mkdir()
    parent, child, source_sha, targets, manifest_path = _prepared_transaction(
        module,
        root,
    )
    real_publish = module._atomic_publish_staged_file
    publish_count = 0

    def _interrupt_second_publish(staged_path: Path, target_path: Path) -> None:
        nonlocal publish_count
        publish_count += 1
        if publish_count == 2:
            raise RuntimeError("simulated process interruption")
        real_publish(staged_path, target_path)

    monkeypatch.setattr(
        module,
        "_atomic_publish_staged_file",
        _interrupt_second_publish,
    )
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        module._commit_prepared_materialization(
            root=root,
            manifest_path=manifest_path,
            parent=parent,
            child=child,
            source_handoff_sha256=source_sha,
        )
    assert sum(path.exists() for path in targets.values()) == 1
    report_path = module.materialization_report_path(root, parent, child)
    assert not report_path.exists()

    monkeypatch.setattr(module, "_atomic_publish_staged_file", real_publish)
    report = module._commit_prepared_materialization(
        root=root,
        manifest_path=manifest_path,
        parent=parent,
        child=child,
        source_handoff_sha256=source_sha,
    )
    assert all(path.is_file() for path in targets.values())
    assert len(report["materialization_target_hashes"]) == len(targets)
    assert module.materialization_readback_reasons(
        report_path,
        parent=parent,
        child=child,
        source_handoff_sha256=source_sha,
        root=root,
    ) == []
    assert module.idempotent_marker_matches(
        report_path,
        parent=parent,
        child=child,
        source_handoff_sha256=source_sha,
        root=root,
    ) is True


def test_child_materialization_target_tamper_cannot_be_idempotent_noop(
    tmp_path: Path,
) -> None:
    module = _load_materializer()
    root = tmp_path / "workspace"
    root.mkdir()
    parent, child, source_sha, targets, manifest_path = _prepared_transaction(
        module,
        root,
    )
    module._commit_prepared_materialization(
        root=root,
        manifest_path=manifest_path,
        parent=parent,
        child=child,
        source_handoff_sha256=source_sha,
    )
    report_path = module.materialization_report_path(root, parent, child)
    targets["alpha_idea_master"].write_bytes(b"tampered")

    reasons = module.materialization_readback_reasons(
        report_path,
        parent=parent,
        child=child,
        source_handoff_sha256=source_sha,
        root=root,
    )
    assert any("hash_mismatch" in reason for reason in reasons)
    assert module.idempotent_marker_matches(
        report_path,
        parent=parent,
        child=child,
        source_handoff_sha256=source_sha,
        root=root,
    ) is False


def test_materializer_cli_replays_exact_hashes_and_blocks_target_tamper(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    parent, child = _legacy_materializer_fixture(root)
    script = (
        REPO_ROOT
        / "skills/factor-forge-step6/scripts/materialize_step6_child_revision.py"
    )
    command = [
        sys.executable,
        str(script),
        "--factorforge-root",
        str(root),
        "--parent-report-id",
        parent,
        "--child-report-id",
        child,
    ]
    environment = os.environ.copy()
    environment["FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE"] = "1"

    first = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert '"status": "materialized"' in first.stdout
    second = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert '"status": "idempotent_noop"' in second.stdout

    child_alpha = (
        root / f"objects/alpha_idea_master/alpha_idea_master__{child}.json"
    )
    child_alpha.write_text('{"tampered":true}', encoding="utf-8")
    blocked = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert blocked.returncode == 1
    assert "BLOCK_FACTORFORGE_CHILD_MATERIALIZATION_READBACK_INVALID" in (
        blocked.stdout + blocked.stderr
    )
    assert '"status": "idempotent_noop"' not in blocked.stdout


def test_ultimate_loop_reuse_requires_hash_bound_materialization_readback(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    parent, child = _legacy_materializer_fixture(root)
    script = (
        REPO_ROOT
        / "skills/factor-forge-step6/scripts/materialize_step6_child_revision.py"
    )
    command = [
        sys.executable,
        str(script),
        "--factorforge-root",
        str(root),
        "--parent-report-id",
        parent,
        "--child-report-id",
        child,
    ]
    environment = os.environ.copy()
    environment["FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE"] = "1"
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    loop_path = REPO_ROOT / "scripts/run_factorforge_ultimate_loop.py"
    spec = importlib.util.spec_from_file_location(
        "factorforge_ultimate_loop_materialization_readback_under_test",
        loop_path,
    )
    assert spec and spec.loader
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    assert loop.existing_materialization_report(root, parent, child)["ok"] is True

    child_spec = (
        root / f"objects/factor_spec_master/factor_spec_master__{child}.json"
    )
    child_spec.write_text('{"tampered":true}', encoding="utf-8")
    result = loop.existing_materialization_report(root, parent, child)
    assert result["ok"] is False
    assert result["reason"] == "materialization_hash_readback_invalid"
