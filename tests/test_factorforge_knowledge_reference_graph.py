from __future__ import annotations

import json
import shutil
from pathlib import Path

from factor_factory.knowledge_reference import build_knowledge_reference_contract


REPO = Path(__file__).resolve().parents[1]
GRAPH = REPO / "knowledge" / "因子工厂"


def copy_public_graph(root: Path) -> None:
    shutil.copytree(GRAPH / "graph", root / "graph")
    shutil.copytree(GRAPH / "taxonomy", root / "taxonomy")


def test_chinese_graph_retrieval_is_advisory_and_rich(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    copy_public_graph(root)
    contract = build_knowledge_reference_contract(
        repo_root=tmp_path / "other-repo",
        knowledge_root=root,
        query_text="占用测度 价值 支撑",
        producer="test",
        top_k=2,
        retrieval_required=True,
    )
    assert contract["retrieval_status"] == "retrieved"
    assert contract["hit_count"] == 2
    assert contract["retrieved_knowledge_nodes"][0]["advisory_only"] is True
    assert contract["retrieved_knowledge_relations"]
    assert contract["knowledge_advisory"]["advisory_only"] is True


def test_legacy_index_remains_compatible(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "retrieval").mkdir()
    (root / "retrieval" / "factorforge_retrieval_index.jsonl").write_text(
        json.dumps({"id": "legacy-1", "factor_id": "OLD", "decision": "reject", "text": "turnover cost failure"}) + "\n",
        encoding="utf-8",
    )
    contract = build_knowledge_reference_contract(
        repo_root=tmp_path / "other-repo",
        knowledge_root=root,
        query_text="turnover cost failure",
        producer="test",
        top_k=1,
    )
    assert contract["retrieval_status"] == "retrieved"
    assert contract["retrieved_case_ids"] == ["legacy-1"]


def test_missing_graph_is_not_silently_resolved_from_repo(tmp_path: Path) -> None:
    root = tmp_path / "isolated"
    root.mkdir()
    contract = build_knowledge_reference_contract(
        repo_root=REPO,
        knowledge_root=root,
        query_text="occupation measure",
        producer="test",
        retrieval_required=True,
    )
    assert contract["retrieval_status"] == "cold_start"
    assert contract["hit_count"] == 0
    assert all(str(root) in path for path in contract["graph_index_paths_checked"])


def test_corrupt_graph_reports_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    copy_public_graph(root)
    (root / "graph" / "factor_knowledge_nodes.jsonl").write_text("{bad json\n", encoding="utf-8")
    contract = build_knowledge_reference_contract(
        repo_root=tmp_path / "other-repo",
        knowledge_root=root,
        query_text="occupation measure",
        producer="test",
    )
    assert contract["retrieval_status"] == "unavailable"
    assert contract["fallback_reason"].startswith("BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_UNAVAILABLE")
