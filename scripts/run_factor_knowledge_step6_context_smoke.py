#!/usr/bin/env python3
from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

RUN_STEP6_PATH = REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "run_step6.py"


def load_build_retrieval_context():
    spec = importlib.util.spec_from_file_location("factorforge_step6_run_step6_for_knowledge_smoke", RUN_STEP6_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Step6 module from {RUN_STEP6_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_retrieval_context


def main() -> None:
    build_retrieval_context = load_build_retrieval_context()
    bundle = {
        "factor_run_master": {
            "report_id": "SMOKE_FACTOR_KNOWLEDGE_CONTEXT_CURRENT",
            "factor_id": "moneyflow_first_passage_smoke",
            "run_status": "iterate",
        },
        "factor_case_master": {
            "factor_id": "moneyflow_first_passage_smoke",
            "final_status": "iterate",
            "lessons": [
                "moneyflow first_passage repaired absorption profit payer support overhang",
            ],
            "next_actions": [
                "reuse graph context as analogy only",
            ],
        },
    }
    context = build_retrieval_context(bundle, payloads={}, top_k=5)
    graph_context = context.get("factor_knowledge_context") or {}
    graph_cases = [
        item
        for item in context.get("similar_cases") or []
        if item.get("doc_type") == "factor_knowledge_graph_node"
    ]
    if graph_context.get("schema_version") != "factor_knowledge_context_v1":
        raise SystemExit("Step6 retrieval_context missing factor_knowledge_context_v1")
    if graph_context.get("node_count", 0) < 1:
        raise SystemExit("Step6 retrieval_context did not retrieve graph nodes")
    if not graph_cases:
        raise SystemExit("Step6 retrieval_context did not append graph nodes to similar_cases")
    if not graph_cases[0].get("not_same_factor_unless_identity_matches"):
        raise SystemExit("graph similar case missing identity guard")
    print(json.dumps({
        "verdict": "ACCEPT",
        "factor_knowledge_context_node_count": graph_context.get("node_count"),
        "graph_similar_case_count": len(graph_cases),
        "first_graph_case": graph_cases[0].get("graph_node_id"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
