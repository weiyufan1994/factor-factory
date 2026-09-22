from __future__ import annotations

import json
import shutil
from pathlib import Path

from factor_factory.knowledge_context import retrieve_factor_knowledge_context


REPO = Path(__file__).resolve().parents[1]
NODE = REPO / "knowledge/因子工厂/graph/nodes/METHOD_CONDITIONAL_OPERATOR_REFERENCE_20260908.json"


def _temporary_single_node_graph(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    graph = tmp_path / "graph"
    nodes = graph / "nodes"
    nodes.mkdir(parents=True)
    copied = nodes / NODE.name
    shutil.copyfile(NODE, copied)
    node = json.loads(copied.read_text(encoding="utf-8"))
    row = {
        "id": node["id"],
        "node_type": node["node_type"],
        "title": node["title"],
        "summary": node["summary"],
        "factor_ids": node["factor_ids"],
        "report_ids": node["report_ids"],
        "taxonomy": node["taxonomy"],
        "research_status": node["taxonomy"]["research_status"],
        "tags": ["methodology", "argmax", "gating", "causal_convolution"],
        "evidence": node["evidence"],
        "source_paths": node["source_paths"],
        "source_node_path": f"nodes/{NODE.name}",
        "text": json.dumps(node, ensure_ascii=False),
    }
    node_index = graph / "factor_knowledge_nodes.jsonl"
    node_index.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    edge_index = graph / "factor_knowledge_edges.jsonl"
    edge_index.write_text("", encoding="utf-8")
    taxonomy = tmp_path / "taxonomy.json"
    taxonomy.write_text("{}", encoding="utf-8")
    return graph, node_index, edge_index, taxonomy


def test_conditional_operator_node_has_eight_bounded_groups() -> None:
    node = json.loads(NODE.read_text(encoding="utf-8"))
    groups = node["mechanism"]["operator_groups"]
    assert len(groups) == 8
    assert {group["id"] for group in groups} == {
        "return_log_delta",
        "same_direction_mean_deviation_cs_vs_ts",
        "rank_z_mad_zero",
        "mean_sum_causal_convolution",
        "std_skew_kurt_direction",
        "argmax_volume_peak_recursion",
        "winsor_conditional_gating_selection",
        "correlation_residualize_neutralize",
    }
    for group in groups:
        assert all(group.get(field) for field in (
            "mathematical_object", "inputs_and_time_scale", "retained_or_lost",
            "conditional_economic_hypothesis", "applicability_and_failure", "counterexample",
        ))
    assert node["evidence"]["classification"].startswith("reference_only")
    assert "profitability claim" in node["evidence"]["boundary"]


def test_conditional_operator_node_is_retrievable_for_argmax_and_gating(tmp_path: Path) -> None:
    graph, node_index, edge_index, taxonomy = _temporary_single_node_graph(tmp_path)
    for query, group_id in (
        ("argmax volume peak recursion", "argmax_volume_peak_recursion"),
        ("conditional gating winsor selection", "winsor_conditional_gating_selection"),
    ):
        result = retrieve_factor_knowledge_context(
            text=query,
            top_k=1,
            node_index=node_index,
            edge_index=edge_index,
            taxonomy=taxonomy,
            graph_root=graph,
        )
        assert [node["id"] for node in result["nodes"]] == [
            "node::method_conditional_operator_reference_20260908"
        ]
        assert any(group["id"] == group_id for group in result["nodes"][0]["mechanism"]["operator_groups"])
