from __future__ import annotations

import json
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
    out = publisher.build_publish_bundle(source_root=root, output=tmp_path / "out")
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
        publisher.build_publish_bundle(source_root=root, output=tmp_path / "out")


def test_rejects_complete_pem_but_not_a_header_literal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _repo(tmp_path)
    (root / "scripts/key.py").write_bytes(
        b"-----BEGIN " + b"PRIVATE KEY-----\nQUJDRA==\n-----END PRIVATE KEY-----\n"
    )
    monkeypatch.setattr(publisher, "build_preview", lambda *, source_root, output: (zipfile.ZipFile(output, "w").writestr("query_knowledge.py", "") or output))
    monkeypatch.setattr(publisher, "_git_metadata", lambda root: (["scripts/key.py"], None, None))
    with pytest.raises(ValueError, match="secret material"):
        publisher.build_publish_bundle(source_root=root, output=tmp_path / "out")
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
