from __future__ import annotations

import json
from pathlib import Path


def test_knowledge_graph_node_path_remaps_cross_host_absolute_path(tmp_path, monkeypatch):
    import factor_factory.knowledge_context as knowledge

    monkeypatch.setattr(knowledge, "REPO_ROOT", tmp_path)
    node_path = tmp_path / "knowledge" / "因子工厂" / "graph" / "nodes" / "opening_case.json"
    node_path.parent.mkdir(parents=True)
    node_path.write_text(
        json.dumps(
            {
                "id": "node::opening_case",
                "node_type": "factor_case",
                "title": "Opening pressure case",
                "summary": "Opening pressure must be separated from reversal and liquidity aliases.",
                "taxonomy": {"research_status": ["rejected"]},
                "reuse_guidance": ["Preserve the alias controls."],
            }
        ),
        encoding="utf-8",
    )
    stale_path = "/Users/old-host/project/knowledge/因子工厂/graph/nodes/opening_case.json"
    node_index = tmp_path / "node_index.jsonl"
    node_index.write_text(
        json.dumps(
            {
                "id": "node::opening_case",
                "title": "Opening pressure case",
                "summary": "Opening pressure reversal liquidity",
                "tags": ["opening"],
                "research_status": ["rejected"],
                "source_node_path": stale_path,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    edge_index = tmp_path / "edge_index.jsonl"
    edge_index.write_text("", encoding="utf-8")

    context = knowledge.retrieve_factor_knowledge_context(
        text="opening pressure reversal",
        top_k=3,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=tmp_path / "missing_taxonomy.json",
    )

    assert context["node_count"] == 1
    assert context["nodes"][0]["id"] == "node::opening_case"
    assert context["nodes"][0]["reuse_guidance"] == ["Preserve the alias controls."]


def test_current_checkout_node_wins_over_existing_stale_checkout(tmp_path, monkeypatch):
    import factor_factory.knowledge_context as module

    current_root = tmp_path / "current"
    stale_root = tmp_path / "stale"
    relative = Path("knowledge/因子工厂/graph/nodes/case.json")
    current_path = current_root / relative
    stale_path = stale_root / relative
    current_path.parent.mkdir(parents=True)
    stale_path.parent.mkdir(parents=True)
    current_path.write_text('{"id":"current"}\n', encoding="utf-8")
    stale_path.write_text('{"id":"stale"}\n', encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", current_root)

    assert module.resolve_graph_node_path(stale_path) == current_path


def test_stale_checkout_node_is_not_used_when_current_node_is_missing(tmp_path, monkeypatch):
    import factor_factory.knowledge_context as module

    current_root = tmp_path / "current"
    stale_path = tmp_path / "stale" / "knowledge/因子工厂/graph/nodes/case.json"
    stale_path.parent.mkdir(parents=True)
    stale_path.write_text('{"id":"stale"}\n', encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", current_root)

    resolved = module.resolve_graph_node_path(stale_path)

    assert resolved == current_root / "knowledge/因子工厂/graph/nodes/case.json"
    assert not resolved.exists()
