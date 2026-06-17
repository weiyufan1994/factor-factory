#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "knowledge" / "因子工厂" / "graph" / "templates" / "factor_knowledge_node_template.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.knowledge_context import graph_node_to_similar_case, retrieve_factor_knowledge_context


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO_ROOT, check=True, text=True, capture_output=True)


def main() -> None:
    if not TEMPLATE_PATH.exists():
        raise SystemExit(f"missing graph node writeback template: {TEMPLATE_PATH}")
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    required_template_keys = {
        "schema_version",
        "id",
        "node_type",
        "taxonomy",
        "mechanism",
        "evidence",
        "relations",
        "reuse_guidance",
    }
    missing_template_keys = sorted(required_template_keys - set(template))
    if missing_template_keys:
        raise SystemExit(f"template missing keys: {missing_template_keys}")

    build = run([sys.executable, "scripts/build_factor_knowledge_graph.py"])
    manifest = json.loads(build.stdout)
    if manifest.get("node_count", 0) < 4:
        raise SystemExit("expected at least four graph nodes covering multiple mechanisms")
    if manifest.get("edge_count", 0) < 10:
        raise SystemExit("expected at least ten graph edges")

    query = run([sys.executable, "scripts/query_factor_knowledge_graph.py", "--tag", "first_passage", "--text", "moneyflow", "--top-k", "3"])
    payload = json.loads(query.stdout)
    ids = [row.get("id") for row in payload.get("results") or []]
    if "node::moneyflow_feature_candidates_v15_v18_v19_20260617" not in ids:
        raise SystemExit(f"moneyflow first_passage node not found: {ids}")

    occupation = run([sys.executable, "scripts/query_factor_knowledge_graph.py", "--tag", "occupation_measure", "--text", "support", "--top-k", "3"])
    occupation_payload = json.loads(occupation.stdout)
    occupation_ids = [row.get("id") for row in occupation_payload.get("results") or []]
    if "node::vp_support_overhang_occupation_20260610" not in occupation_ids:
        raise SystemExit(f"occupation-measure node not found: {occupation_ids}")

    residual = run([
        sys.executable,
        "scripts/query_factor_knowledge_graph.py",
        "--tag",
        "math_mechanism:residualization",
        "--top-k",
        "10",
    ])
    residual_payload = json.loads(residual.stdout)
    residual_ids = [row.get("id") for row in residual_payload.get("results") or []]
    if "node::cs_residual_vol_20d_neg_20260616" not in residual_ids:
        raise SystemExit(f"residualization node not found: {residual_ids}")

    buyside = run([sys.executable, "scripts/query_factor_knowledge_graph.py", "--tag", "buyside_style:microstructure_alpha", "--top-k", "20"])
    buyside_payload = json.loads(buyside.stdout)
    buyside_ids = [row.get("id") for row in buyside_payload.get("results") or []]
    expected_buyside_nodes = {
        "node::moneyflow_feature_candidates_v15_v18_v19_20260617",
        "node::vp_support_overhang_occupation_20260610",
    }
    if not expected_buyside_nodes <= set(buyside_ids):
        raise SystemExit(f"buyside microstructure nodes not found: {buyside_ids}")

    flow_alpha = run([sys.executable, "scripts/query_factor_knowledge_graph.py", "--tag", "buyside_style:flow_alpha", "--top-k", "20"])
    flow_alpha_payload = json.loads(flow_alpha.stdout)
    flow_alpha_ids = [row.get("id") for row in flow_alpha_payload.get("results") or []]
    expected_flow_alpha_nodes = {
        "node::moneyflow_feature_candidates_v15_v18_v19_20260617",
        "node::cpv_occ_loc_stability_v3_20260616",
    }
    if not expected_flow_alpha_nodes <= set(flow_alpha_ids):
        raise SystemExit(f"buyside flow-alpha nodes not found: {flow_alpha_ids}")

    edge_query = run([sys.executable, "scripts/query_factor_knowledge_graph.py", "--edge-type", "shares_failure_with", "--top-k", "5"])
    edge_payload = json.loads(edge_query.stdout)
    if not edge_payload.get("results"):
        raise SystemExit("expected shares_failure_with edge")

    context = run([
        sys.executable,
        "scripts/retrieve_factor_knowledge_context.py",
        "--tag",
        "first_passage",
        "--text",
        "moneyflow",
        "--top-k",
        "2",
    ])
    context_payload = json.loads(context.stdout)
    if context_payload.get("schema_version") != "factor_knowledge_context_v1":
        raise SystemExit("knowledge context schema mismatch")
    if not context_payload.get("nodes"):
        raise SystemExit("expected retrieved knowledge context nodes")
    first_node = context_payload["nodes"][0]
    if not first_node.get("mechanism"):
        raise SystemExit("retrieved context must include mechanism")
    if not first_node.get("reuse_guidance"):
        raise SystemExit("retrieved context must include reuse_guidance")
    module_context = retrieve_factor_knowledge_context(text="moneyflow first passage", tags=["first_passage"], top_k=2)
    if module_context.get("node_count", 0) < 1:
        raise SystemExit("module retrieval returned no graph nodes")
    similar_case = graph_node_to_similar_case(module_context["nodes"][0], score=3.0)
    if similar_case.get("doc_type") != "factor_knowledge_graph_node":
        raise SystemExit("graph node was not mapped to Step6-compatible similar case")
    if similar_case.get("knowledge_scope") not in {"similar_case", "anti_pattern"}:
        raise SystemExit("graph similar case has invalid knowledge_scope")

    step1 = run([sys.executable, "scripts/run_factor_knowledge_step1_context_smoke.py"])
    step1_payload = json.loads(step1.stdout)
    if step1_payload.get("verdict") != "ACCEPT":
        raise SystemExit("Step1 knowledge context smoke failed")

    step2 = run([sys.executable, "scripts/run_factor_knowledge_step2_context_smoke.py"])
    step2_payload = json.loads(step2.stdout)
    if step2_payload.get("verdict") != "ACCEPT":
        raise SystemExit("Step2 knowledge context smoke failed")

    step6 = run([sys.executable, "scripts/run_factor_knowledge_step6_context_smoke.py"])
    step6_payload = json.loads(step6.stdout)
    if step6_payload.get("verdict") != "ACCEPT":
        raise SystemExit("Step6 knowledge context smoke failed")

    print(json.dumps({
        "verdict": "ACCEPT",
        "node_count": manifest.get("node_count"),
        "edge_count": manifest.get("edge_count"),
        "moneyflow_node_found": True,
        "occupation_node_found": True,
        "residualization_node_found": True,
        "buyside_microstructure_nodes_found": True,
        "buyside_flow_alpha_nodes_found": True,
        "shares_failure_with_edges": len(edge_payload.get("results") or []),
        "template_found": True,
        "context_retrieval_found": True,
        "step6_case_mapping_found": True,
        "step1_context_integration_found": True,
        "step2_context_integration_found": True,
        "step6_context_integration_found": True,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
