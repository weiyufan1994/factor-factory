from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import build_factorforge_publish_bundle as publisher


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "factor_factory").mkdir()
    (root / publisher.EXPORT_ROOT).mkdir(parents=True)
    (root / "README.md").write_text("old\n")
    (root / "README.zh-CN.md").write_text("old\n")
    (root / "AGENTS.md").write_text("# Project instructions\n")
    (root / "docs/quickstart-publish.zh-CN.md").write_text("# Quickstart\n")
    (root / "scripts/run.py").write_text("print('ok')\n")
    (root / "factor_factory/core.py").write_text("x = 1\n")
    (root / "dist").mkdir()
    (root / "dist/bad.txt").write_text("omit\n")
    for report_id in publisher.ALLOWED_EXPORT_IDS:
        (root / publisher.EXPORT_ROOT / f"knowledge_record__{report_id}.json").write_text(json.dumps({
            "export_version": "factorforge_workspace_experience_export_v1",
            "export_status": "LOCAL_PROJECT_ADVISORY_CANDIDATE_NOT_CANONICAL",
            "advisory_only": True, "same_factor_not_generalized": True,
            "canonical_promotion_allowed": False, "report_id": report_id,
            "factor_id": "MSZQ", "success_patterns": [], "failure_patterns": [],
            "modification_hypotheses": [], "reuse_constraints": [],
        }), encoding="utf-8")
    return root


def test_bounded_bundle_and_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _repo(tmp_path)
    preview = tmp_path / "preview.zip"

    def fake_preview(*, source_root, output):
        with zipfile.ZipFile(output, "w") as zf:
            zf.writestr("query_knowledge.py", "#!/usr/bin/env python3\n")
            zf.writestr("knowledge/public.json", "{}\n")
        return output

    monkeypatch.setattr(publisher, "build_preview", fake_preview)
    def fake_rebuild(staging: Path):
        target = staging / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(json.dumps({"source_path": (publisher.EXPORT_ROOT / f"knowledge_record__{report_id}.json").as_posix()}) for report_id in publisher.ALLOWED_EXPORT_IDS) + "\n")
    monkeypatch.setattr(publisher, "_rebuild_staging_index", fake_rebuild)
    monkeypatch.setattr(publisher, "_git_metadata", lambda root: (["AGENTS.md", "README.md", "README.zh-CN.md", "scripts/run.py", "factor_factory/core.py", "dist/bad.txt"], "abc", "main"))
    out = publisher._build_tree_bundle(source_root=root, output=tmp_path / "out")
    inventory = json.loads((out / "bundle_inventory.json").read_text())
    assert "dist/bad.txt" in inventory["excluded_paths"]
    assert (out / "factor-forge").is_dir()
    assert (out / "factor-forge/AGENTS.md").read_bytes() == (root / "AGENTS.md").read_bytes()
    assert "AGENTS.md" in inventory["selected_paths"]
    assert any(item["path"] == "AGENTS.md" for item in inventory["files"])
    with zipfile.ZipFile(out / "factor-forge.zip") as zf:
        names = set(zf.namelist())
        assert zf.read("factor-forge/AGENTS.md") == (root / "AGENTS.md").read_bytes()
        assert "factor-forge/README.md" in names
        assert zf.read("factor-forge/README.md") == b"# Quickstart\n"
        assert "factor-forge/query_knowledge.py" in names
        assert "factor-forge/knowledge/public.json" in names
        assert "bundle_inventory.json" in names
        assert not any("dist/" in n for n in names)
        assert zf.getinfo("factor-forge/README.md").compress_type == zipfile.ZIP_DEFLATED


def test_rejects_secret_and_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _repo(tmp_path)
    (root / "scripts/secret.py").write_bytes(b"AK" + b"IA1234567890ABCDEF\n")
    monkeypatch.setattr(publisher, "build_preview", lambda *, source_root, output: (zipfile.ZipFile(output, "w").writestr("query_knowledge.py", "") or output))
    monkeypatch.setattr(publisher, "_git_metadata", lambda root: (["scripts/secret.py"], None, None))
    with pytest.raises(ValueError, match="secret material"):
        publisher._build_tree_bundle(source_root=root, output=tmp_path / "out")


def test_rejects_complete_pem_but_not_a_header_literal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _repo(tmp_path)
    (root / "scripts/key.py").write_bytes(
        b"-----BEGIN " + b"PRIVATE KEY-----\nQUJDRA==\n-----END PRIVATE KEY-----\n"
    )
    monkeypatch.setattr(publisher, "build_preview", lambda *, source_root, output: (zipfile.ZipFile(output, "w").writestr("query_knowledge.py", "") or output))
    monkeypatch.setattr(publisher, "_git_metadata", lambda root: (["scripts/key.py"], None, None))
    with pytest.raises(ValueError, match="secret material"):
        publisher._build_tree_bundle(source_root=root, output=tmp_path / "out")
    assert not publisher.PEM_PRIVATE_KEY.search(b"-----BEGIN PRIVATE KEY-----")


def test_no_git_fallback_prunes_caches_and_data(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "scripts/__pycache__").mkdir()
    (root / "scripts/__pycache__/run.pyc").write_bytes(b"cache")
    (root / "scripts/.pytest_cache").mkdir()
    (root / "scripts/.pytest_cache/ignored.py").write_text("x\n")
    (root / "data").mkdir()
    (root / "data/large.parquet").write_bytes(b"not scanned")
    selected, excluded = publisher._select(root)
    assert "scripts/run.py" in selected
    assert "AGENTS.md" in selected
    assert not any("__pycache__" in path or ".pytest_cache" in path or path.endswith(".pyc") for path in selected + excluded)
    assert not any(path.startswith("data/") for path in selected + excluded)


def _commit_repo(root: Path) -> str:
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.name=Package Test', '-c', 'user.email=test@example.invalid',
                    'commit', '-qm', 'fixture'], cwd=root, check=True)
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()


def _selection(root: Path):
    (root / 'packaging').mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'packaging/research-files.toml',
                    root / 'packaging/research-files.toml')


def test_git_snapshot_ignores_dirty_untracked_and_historical_sources(tmp_path):
    root = _repo(tmp_path)
    _selection(root)
    excluded = root / 'factor_factory/epistemic_host_bootstrap_expectation_proposal.py'
    excluded.write_text('historical = True\n')
    head = _commit_repo(root)
    (root / 'factor_factory/core.py').write_text('dirty = True\n')
    (root / 'factor_factory/untracked.py').write_text('untracked = True\n')
    (root / 'packaging/research-files.toml').write_text('invalid draft selector\n')
    target = tmp_path / 'snapshot'
    identity = publisher._snapshot_source(root, head, target)
    assert identity['commit'] == head
    assert (target / 'factor_factory/core.py').read_text() == 'x = 1\n'
    assert not (target / excluded.relative_to(root)).exists()
    assert not (target / 'factor_factory/untracked.py').exists()
    assert not (target / 'dist').exists()
    assert (target / publisher.EXPORT_ROOT).is_dir()


def test_selected_git_symlink_is_rejected_without_following_it(tmp_path):
    root = _repo(tmp_path)
    _selection(root)
    (root / 'factor_factory/escape.py').symlink_to('/outside-package/read-is-not-allowed')
    head = _commit_repo(root)
    with pytest.raises(ValueError, match='unsafe selected Git member'):
        publisher._snapshot_source(root, head, tmp_path / 'snapshot')


def test_client_sdk_selection_omits_operational_scripts(tmp_path):
    root = tmp_path / 'sdk'
    (root / 'factorforge_data_api').mkdir(parents=True)
    (root / 'factorforge_data_api/client.py').write_text('class DataApiClient: pass\n')
    (root / 'pyproject.toml').write_text('[project]\nname="sdk"\n')
    (root / 'scripts').mkdir()
    (root / 'scripts/production_backfill.py').write_text('raise RuntimeError("not a client")\n')
    rules = publisher.tomllib.loads((Path(__file__).resolve().parents[1] /
                                    'packaging/research-files.toml').read_text())['data_sdk']
    target = tmp_path / 'copy'
    rows = publisher._copy_data_sdk(root, target, rules)
    assert {row['path'] for row in rows} == {'factorforge_data_api/client.py', 'pyproject.toml'}
    assert not (target / 'scripts').exists()


def test_public_builder_hands_only_commit_bytes_to_staging(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    _selection(root)
    head = _commit_repo(root)
    (root / 'factor_factory/core.py').write_text('dirty = True\n')
    calls = []

    def inspect_staging(**kwargs):
        assert kwargs['source_identity']['commit'] == head
        assert (kwargs['source_root'] / 'factor_factory/core.py').read_text() == 'x = 1\n'
        assert kwargs['build_python'] == 'explicit-build-python'
        calls.append(kwargs['source_identity'])
        return kwargs['output']

    monkeypatch.setattr(publisher, '_build_tree_bundle', inspect_staging)
    output = publisher.build_publish_bundle(source_root=root, source_commit=head,
                                            output=tmp_path / 'out', build_python='explicit-build-python')
    assert output == tmp_path / 'out'
    assert len(calls) == 1
