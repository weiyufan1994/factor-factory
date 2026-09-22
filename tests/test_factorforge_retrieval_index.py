from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.build_factorforge_retrieval_index import (
    CorpusBuildError,
    build_corpus,
    refresh_retrieval_index,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _knowledge_record(report_id: str = "R1") -> dict:
    return {
        "report_id": report_id,
        "factor_id": "PV_SHOCK",
        "decision": "iterate",
        "success_patterns": ["works when liquidity is normal"],
        "failure_patterns": ["fails during limit-up queues"],
        "modification_hypotheses": ["shorten the lookback"],
        "factor_family": "price_volume",
        "monetization_model": "underreaction",
        "bias_type": "behavioral",
        "return_source_hypothesis": "delayed incorporation of flow information",
        "expected_failure_regimes": ["one-sided limit regime"],
        # Real Step6 producer emits a scalar classification, not a list.
        "objective_constraint_dependency": "high",
        "constraint_sources": ["price-limit rule"],
        "research_variant": "EVENT_U_DIRECT_CODE_EXTENSION",
        "paper_replication_status": "NOT_PF_VV_REPLICATION",
        "reuse_constraints": ["same factor needs matching identity"],
        "artifact_identity": {"report_id": report_id, "formula_hash": "f"},
        "source_identity": {"factor_id": "PV_SHOCK", "run_id": "run-1"},
        "source_case_identity": {"branch_id": "main"},
        "evidence_identity": {"case_sha256": "a"},
        "knowledge_scope": "same_factor",
        # Must not be emitted, including through advisory_projection.
        "research_memo": {"evo_transfer_tension_ledger": {"secret": "unreviewed"}},
    }


def test_build_corpus_projects_step6_knowledge_as_advisory_search_text(tmp_path: Path) -> None:
    path = tmp_path / "objects/research_knowledge_base/knowledge_record__R1.json"
    _write(path, _knowledge_record())

    docs = build_corpus(tmp_path / "objects")

    assert len(docs) == 1
    doc = docs[0]
    advisory = doc["advisory_projection"]
    assert advisory["return_source_hypothesis"] == "delayed incorporation of flow information"
    assert advisory["expected_failure_regimes"] == ["one-sided limit regime"]
    assert advisory["reuse_constraints"] == ["same factor needs matching identity"]
    assert advisory["objective_constraint_dependency"] == "high"
    assert advisory["research_variant"] == "EVENT_U_DIRECT_CODE_EXTENSION"
    assert advisory["paper_replication_status"] == "NOT_PF_VV_REPLICATION"
    assert advisory["identity"]["artifact_identity"]["formula_hash"] == "f"
    assert advisory["modification_hypotheses"] == [
        {"text": "shorten the lookback", "status": "candidate_not_verified"}
    ]
    assert "one-sided limit regime" in doc["search_text"]
    assert "NOT_PF_VV_REPLICATION" not in doc["search_text"]
    assert "Candidate hypothesis, not verified: shorten the lookback" in doc["search_text"]
    assert "decision=" not in doc["search_text"]
    assert "R1" not in doc["search_text"]
    assert "PV_SHOCK" not in doc["search_text"]
    assert "expected_failure_regimes" not in doc["search_text"]
    assert doc["text"].splitlines()[0] == "research_variant=EVENT_U_DIRECT_CODE_EXTENSION paper_replication_status=NOT_PF_VV_REPLICATION"
    assert "Knowledge record for PV_SHOCK (R1)." in doc["text"]
    assert doc["factor_family"] == "price_volume"
    assert doc["knowledge_scope"] == "same_factor"
    assert doc["artifact_identity"]["formula_hash"] == "f"
    assert doc["formula_hash"] == "f"
    assert doc["source_identity"]["run_id"] == "run-1"
    assert "research_memo" not in doc
    assert "unreviewed" not in json.dumps(doc, ensure_ascii=False)


def test_build_corpus_rejects_duplicate_retrieval_ids(tmp_path: Path) -> None:
    root = tmp_path / "objects/research_knowledge_base"
    _write(root / "knowledge_record__one.json", _knowledge_record("R1"))
    _write(root / "knowledge_record__two.json", _knowledge_record("R1"))

    with pytest.raises(CorpusBuildError, match="duplicate retrieval id"):
        build_corpus(tmp_path / "objects")


def test_build_corpus_rejects_malformed_record_with_source_path(tmp_path: Path) -> None:
    path = tmp_path / "objects/research_knowledge_base/knowledge_record__bad.json"
    _write(path, {"report_id": "R1", "factor_id": "PV_SHOCK", "failure_patterns": "not-a-list"})

    with pytest.raises(CorpusBuildError, match="failure_patterns.*list of strings") as exc:
        build_corpus(tmp_path / "objects")
    assert str(path) in str(exc.value)


def test_cli_runtime_root_writes_synthetic_round_trip(tmp_path: Path) -> None:
    _write(
        tmp_path / "objects/research_knowledge_base/knowledge_record__R1.json",
        _knowledge_record(),
    )
    script = Path(__file__).parents[1] / "scripts/build_factorforge_retrieval_index.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--runtime-root", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    index = tmp_path / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    manifest = tmp_path / "knowledge/retrieval/factorforge_retrieval_manifest.json"
    assert "[WRITE]" in completed.stdout
    assert index.is_file() and manifest.is_file()
    assert json.loads(index.read_text(encoding="utf-8").strip())["id"] == "knowledge_record::R1"


def test_refresh_rebuilds_workspace_local_derived_index(tmp_path: Path) -> None:
    _write(
        tmp_path / "objects/research_knowledge_base/knowledge_record__R1.json",
        _knowledge_record(),
    )

    summary = refresh_retrieval_index(tmp_path)

    index = tmp_path / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    assert summary["doc_count"] == 1
    assert summary["derived_only"] is True
    assert summary["output_path"] == str(index)
    assert json.loads(index.read_text(encoding="utf-8").strip())["id"] == "knowledge_record::R1"


def test_refresh_bad_source_preserves_existing_index_bytes(tmp_path: Path) -> None:
    index = tmp_path / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    index.parent.mkdir(parents=True)
    index.write_bytes(b"known-good-index\n")
    _write(
        tmp_path / "objects/research_knowledge_base/knowledge_record__bad.json",
        {"report_id": "R1", "factor_id": "PV_SHOCK", "failure_patterns": "bad"},
    )

    with pytest.raises(CorpusBuildError):
        refresh_retrieval_index(tmp_path)

    assert index.read_bytes() == b"known-good-index\n"


def test_refresh_missing_or_empty_sources_preserves_existing_index(tmp_path: Path) -> None:
    index = tmp_path / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    index.parent.mkdir(parents=True)
    index.write_bytes(b"known-good-index\n")

    with pytest.raises(CorpusBuildError, match="source objects directory is missing"):
        refresh_retrieval_index(tmp_path)
    assert index.read_bytes() == b"known-good-index\n"

    (tmp_path / "objects").mkdir()
    with pytest.raises(CorpusBuildError, match="no retrieval source documents"):
        refresh_retrieval_index(tmp_path)
    assert index.read_bytes() == b"known-good-index\n"


def test_refresh_rejects_same_output_and_manifest_path(tmp_path: Path) -> None:
    _write(
        tmp_path / "objects/research_knowledge_base/knowledge_record__R1.json",
        _knowledge_record(),
    )
    target = tmp_path / "derived.json"

    with pytest.raises(ValueError, match="must be different"):
        refresh_retrieval_index(tmp_path, output=target, manifest=target)


@pytest.mark.parametrize("symlink_kind", ["record", "directory"])
def test_refresh_rejects_external_source_symlink_and_preserves_index(
    tmp_path: Path, symlink_kind: str
) -> None:
    index = tmp_path / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    index.parent.mkdir(parents=True)
    index.write_bytes(b"known-good-index\n")
    external = tmp_path / "external"
    _write(external / "knowledge_record__R1.json", _knowledge_record())
    source_directory = tmp_path / "objects/research_knowledge_base"
    if symlink_kind == "record":
        source_directory.mkdir(parents=True)
        (source_directory / "knowledge_record__R1.json").symlink_to(
            external / "knowledge_record__R1.json"
        )
    else:
        source_directory.parent.mkdir(parents=True)
        source_directory.symlink_to(external, target_is_directory=True)

    with pytest.raises(CorpusBuildError, match="must not be a symlink"):
        refresh_retrieval_index(tmp_path)
    assert index.read_bytes() == b"known-good-index\n"
