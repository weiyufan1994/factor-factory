from __future__ import annotations

import json
from pathlib import Path

from factor_factory.knowledge_context import score_text
from scripts.build_factor_knowledge_graph import load_json, validate_node


ROOT = Path(__file__).resolve().parents[1]
NODE_PATH = ROOT / "knowledge/因子工厂/graph/nodes/METHOD_TRANSIENT_SIGNAL_MODELS_20260907.json"


def test_transient_signal_method_reference_is_reference_only_and_retrievable() -> None:
    node = json.loads(NODE_PATH.read_text(encoding="utf-8"))
    taxonomy = load_json(ROOT / "knowledge/因子工厂/taxonomy/factor_taxonomy_v1.json")

    assert node["schema_version"] == "factor_knowledge_node_v1"
    assert validate_node(NODE_PATH, node, taxonomy) == []
    assert node["node_type"] == "methodology"
    assert node["taxonomy"]["research_status"] == ["mechanism_candidate"]
    assert node["evidence"]["classification"] == "reference_only_no_empirical_claim"
    assert len(node["evidence"]["primary_references"]) == 4
    assert all(item["url"].startswith("https://") for item in node["evidence"]["primary_references"])
    assert len(node["relations"]) == 4
    assert {item["edge_type"] for item in node["relations"]} == {"inspires"}
    assert all("Conditional inspiration only" in item["note"] for item in node["relations"])
    assert "x_t=F_t x_{t-1}+w_t" in node["mechanism"]["kalman_observation_mapping"]
    assert "generally IIR rather than finite FIR" in node["mechanism"]["kalman_observation_mapping"]
    assert "argmin_u" in node["mechanism"]["variational_tv_observation_mapping"]
    assert "right endpoint no later than t" in node["mechanism"]["variational_tv_observation_mapping"]
    assert "never overwrite" in node["mechanism"]["variational_tv_observation_mapping"]
    assert "t+1" in node["mechanism"]["online_timing_boundary"]
    assert "not inherently leakage" in node["mechanism"]["online_timing_boundary"]
    assert "no factor result, return claim, causal identification" in node["evidence"]["boundary"]
    assert "performance" not in node["summary"].casefold()

    score, overlap = score_text("小波分析", {"title": node["title"], "text": node["summary"], "tags": []})
    assert score > 0 and "小波" in overlap
