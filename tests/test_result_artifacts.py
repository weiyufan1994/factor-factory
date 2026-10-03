"""Independent, synthetic-only review of the public result file boundary."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from factor_factory.result_artifacts import (
    build_result_artifacts,
    prepare_result_paths,
    resolve_result_path,
    result_artifact_paths,
    write_result_payload,
)
from factor_factory.runtime_context import FactorForgeContext


def test_relative_base_cannot_reintroduce_cwd_selection():
    with pytest.raises(ValueError, match="absolute|BASE"):
        resolve_result_path("factor.csv", base_dir="relative-workspace")


def test_writer_uses_explicit_base_for_payload_and_references(tmp_path, monkeypatch):
    workspace = tmp_path / "研究 workspace"
    workspace.mkdir()
    elsewhere = tmp_path / "different cwd"
    elsewhere.mkdir()
    (workspace / "nav.csv").write_text("nav\n1\n")
    payload = {"status": "partial", "artifacts": {"daily_nav": "nav.csv"},
               "metrics": {"value": None, "reason": "unavailable"}}
    monkeypatch.chdir(elsewhere)
    write_result_payload("evaluation_payload.json", payload, base_dir=workspace)
    target = workspace / "evaluation_payload.json"
    assert target.is_file()
    assert not (elsewhere / "evaluation_payload.json").exists()
    saved = json.loads(target.read_text())
    assert saved["status"] == payload["status"]
    assert saved["metrics"] == payload["metrics"]
    assert result_artifact_paths(saved, base_dir=workspace)["daily_nav"] == workspace / "nav.csv"


def test_directory_cannot_satisfy_file_role(tmp_path):
    directory = tmp_path / "diagnostics"
    directory.mkdir()
    with pytest.raises(ValueError, match="ARTIFACT_FILE_REQUIRED"):
        build_result_artifacts(files={"monthly_diagnostics": directory})


def test_explicit_file_and_directory_separation_survives_cwd_change(tmp_path, monkeypatch):
    workspace = tmp_path / "研究 workspace"
    diagnostics = workspace / "diagnostics"
    diagnostics.mkdir(parents=True)
    nav = diagnostics / "nav.csv"
    nav.write_text("nav\n1\n")
    fields = build_result_artifacts(
        files={"daily_nav": "diagnostics/nav.csv", "optional": None},
        directories={"diagnostics": "diagnostics"}, base_dir=workspace,
    )
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert result_artifact_paths(fields) == {"daily_nav": nav}
    assert fields["artifacts"]["optional"] is None
    assert fields["artifact_directories"]["diagnostics"] == str(diagnostics)


def test_common_context_allocates_only_parents_without_overwriting(tmp_path):
    root = tmp_path / "research workspace"
    context = FactorForgeContext(repo_root=tmp_path / "repo", workspace_root=tmp_path,
                                 factorforge_root=root)
    planned = prepare_result_paths(context, "REPORT", "daily_backend",
        files={"daily_nav": "accounts/nav.csv"}, directories={"diagnostics": "diagnostics"})
    nav = root / "evaluations/REPORT/daily_backend/accounts/nav.csv"
    assert planned["artifacts"]["daily_nav"] == str(nav)
    assert nav.parent.is_dir() and not nav.exists()
    nav.write_text("original\n")
    prepare_result_paths(context, "REPORT", "daily_backend", files={"daily_nav": "accounts/nav.csv"})
    assert nav.read_text() == "original\n"


def test_allocation_rejects_file_that_is_another_files_parent(tmp_path):
    root = tmp_path / "research workspace"
    context = FactorForgeContext(repo_root=tmp_path / "repo", workspace_root=tmp_path,
                                 factorforge_root=root)
    with pytest.raises(ValueError):
        prepare_result_paths(context, "REPORT", "daily_backend", files={"nav": "data", "trades": "data/trades.csv"})
    assert not root.exists(), "An invalid path allocation must fail before creating the conflicting layout."


@pytest.mark.parametrize('directories', [{'x': 'data'}, {'x': 'data/sub'}, {'x': 'evaluation_payload.json/sub'}])
def test_allocation_rejects_file_directory_conflict_before_mkdir(tmp_path, directories):
    root = tmp_path / 'new workspace'
    ctx = FactorForgeContext(tmp_path, tmp_path, root)
    with pytest.raises(ValueError, match='CONFLICT'):
        prepare_result_paths(ctx, 'R', 'b', files={'nav': 'data'}, directories=directories)
    assert not root.exists()


@pytest.mark.parametrize('path', [True, 123, [], {}, ''])
def test_no_coercion_of_malformed_file_paths(tmp_path, path):
    # Even if a matching filename happens to exist, non-path values are errors.
    (tmp_path / str(path)).write_text('fixture') if str(path) else None
    with pytest.raises(ValueError):
        build_result_artifacts(files={'nav': path}, base_dir=tmp_path)


def test_absolute_and_relative_references_use_the_same_explicit_base(tmp_path):
    file = tmp_path / 'file with spaces.csv'
    file.write_text('observed')
    relative = build_result_artifacts(files={'f': file.name}, base_dir=tmp_path)
    absolute = build_result_artifacts(files={'f': file}, base_dir=tmp_path)
    assert relative == absolute
    with pytest.raises(ValueError, match='BASE_REQUIRED'):
        result_artifact_paths({'artifacts': {'f': file.name}})


def test_public_runnable_example_preserves_existing_results(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'examples/manual_interface_replay/run_result_artifact_demo.py'
    workspace = tmp_path / '中文 workspace'
    cmd = [sys.executable, '-B', str(script), '--output-dir', str(workspace)]
    cp = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    payload_path = Path(cp.stdout.strip())
    before = payload_path.read_bytes()
    payload = json.loads(before)
    assert len(result_artifact_paths(payload, base_dir=workspace)) == 2
    cp = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True)
    assert cp.returncode != 0 and payload_path.read_bytes() == before
