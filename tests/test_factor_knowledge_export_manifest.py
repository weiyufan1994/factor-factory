from __future__ import annotations

import hashlib
import json
from pathlib import Path

import scripts.validate_factor_knowledge_commit_scope as validator


PAYLOAD_PATH = "knowledge/因子工厂/graph/factor_knowledge_nodes.jsonl"


def write_manifest(root: Path, payload_path: Path) -> Path:
    manifest_path = (
        root
        / "knowledge"
        / "因子工厂"
        / "export_manifest"
        / "repo_root_knowledge_export_test.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    content = payload_path.read_bytes()
    files = [
        {
            "path": PAYLOAD_PATH,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    ]
    manifest_path.write_text(
        json.dumps(
            {
                "contract_version": validator.EXPORT_MANIFEST_VERSION,
                "export_root": "knowledge/因子工厂",
                "export_target": "repo_root_knowledge_vault",
                "scope": {
                    "mode": "git_diff_payload_exact",
                    "base_commit": "a" * 40,
                    "payload_count": 1,
                },
                "payload_snapshot_sha256": validator.stable_hash(files),
                "files": files,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_export_manifest_validates_bytes_sha_and_exact_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload_path = tmp_path / PAYLOAD_PATH
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text('{"id":"node::test"}\n', encoding="utf-8")
    manifest_path = write_manifest(tmp_path, payload_path)
    monkeypatch.setattr(validator, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        validator,
        "changed_paths_since",
        lambda _base: {PAYLOAD_PATH},
    )

    result = validator.validate_export_manifest(manifest_path)

    assert result["verdict"] == "ACCEPT"
    assert result["failures"] == []


def test_export_manifest_blocks_payload_tamper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload_path = tmp_path / PAYLOAD_PATH
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text('{"id":"node::test"}\n', encoding="utf-8")
    manifest_path = write_manifest(tmp_path, payload_path)
    payload_path.write_text('{"id":"node::tampered"}\n', encoding="utf-8")
    monkeypatch.setattr(validator, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        validator,
        "changed_paths_since",
        lambda _base: {PAYLOAD_PATH},
    )

    result = validator.validate_export_manifest(manifest_path)

    assert result["verdict"] == "BLOCK"
    assert f"{PAYLOAD_PATH}:sha256_mismatch" in result["failures"]


def test_export_manifest_blocks_uncovered_git_diff_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload_path = tmp_path / PAYLOAD_PATH
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text('{"id":"node::test"}\n', encoding="utf-8")
    manifest_path = write_manifest(tmp_path, payload_path)
    missing_path = "knowledge/因子工厂/graph/factor_knowledge_edges.jsonl"
    monkeypatch.setattr(validator, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        validator,
        "changed_paths_since",
        lambda _base: {PAYLOAD_PATH, missing_path},
    )

    result = validator.validate_export_manifest(manifest_path)

    assert result["verdict"] == "BLOCK"
    assert any(
        failure.startswith("manifest_scope_paths_missing:")
        and missing_path in failure
        for failure in result["failures"]
    )
