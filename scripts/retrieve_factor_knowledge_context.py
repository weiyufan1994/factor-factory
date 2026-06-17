#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH_ROOT = REPO_ROOT / "knowledge" / "因子工厂" / "graph"
DEFAULT_NODE_INDEX = DEFAULT_GRAPH_ROOT / "factor_knowledge_nodes.jsonl"
DEFAULT_EDGE_INDEX = DEFAULT_GRAPH_ROOT / "factor_knowledge_edges.jsonl"
DEFAULT_TAXONOMY = REPO_ROOT / "knowledge" / "因子工厂" / "taxonomy" / "factor_taxonomy_v1.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.knowledge_context import retrieve_factor_knowledge_context


def maybe_build_graph(no_build: bool) -> None:
    if no_build:
        return
    subprocess.run(
        [sys.executable, "scripts/build_factor_knowledge_graph.py"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def build_context(args: argparse.Namespace) -> dict[str, Any]:
    maybe_build_graph(args.no_build)
    return retrieve_factor_knowledge_context(
        text=args.text,
        tags=args.tag or [],
        status=args.status or [],
        node_type=args.node_type or [],
        top_k=args.top_k,
        node_index=args.node_index,
        edge_index=args.edge_index,
        taxonomy=args.taxonomy,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieve full Factor Forge knowledge context for research steps.")
    parser.add_argument("--node-index", default=str(DEFAULT_NODE_INDEX))
    parser.add_argument("--edge-index", default=str(DEFAULT_EDGE_INDEX))
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY))
    parser.add_argument("--tag", action="append", default=[], help="Require a tag, e.g. first_passage or market_consensus:reversal")
    parser.add_argument("--status", action="append", default=[], help="Require a research_status tag")
    parser.add_argument("--node-type", action="append", default=[], help="Require a node_type")
    parser.add_argument("--text", default="", help="Text query")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--no-build", action="store_true", help="Do not rebuild the graph index before retrieving context.")
    parser.add_argument("--output", help="Optional output JSON path.")
    args = parser.parse_args()

    context = build_context(args)
    payload = json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
