#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH_ROOT = REPO_ROOT / "knowledge" / "因子工厂" / "graph"
DEFAULT_NODE_INDEX = DEFAULT_GRAPH_ROOT / "factor_knowledge_nodes.jsonl"
DEFAULT_EDGE_INDEX = DEFAULT_GRAPH_ROOT / "factor_knowledge_edges.jsonl"
DEFAULT_TAXONOMY = REPO_ROOT / "knowledge" / "因子工厂" / "taxonomy" / "factor_taxonomy_v1.json"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_tags(raw_tags: list[str], taxonomy_path: Path) -> tuple[set[str], dict[str, list[str]]]:
    taxonomy = load_json(taxonomy_path)
    aliases = taxonomy.get("aliases") or {}
    resolved: set[str] = set()
    alias_resolution: dict[str, list[str]] = {}
    for raw_tag in raw_tags:
        mapped = aliases.get(raw_tag)
        if mapped:
            mapped_tags = [str(tag) for tag in mapped]
            resolved.update(mapped_tags)
            alias_resolution[raw_tag] = mapped_tags
        else:
            resolved.add(raw_tag)
    return resolved, alias_resolution


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]+", text.lower()))


def score_text(query: str, row: dict[str, Any]) -> tuple[float, list[str]]:
    q = tokenize(query)
    if not q:
        return 0.0, []
    haystack = " ".join(
        [
            str(row.get("id") or ""),
            str(row.get("title") or ""),
            str(row.get("summary") or ""),
            str(row.get("text") or ""),
            " ".join(row.get("tags") or []),
        ]
    )
    overlap = sorted(q & tokenize(haystack))
    return float(len(overlap)), overlap


def main() -> None:
    parser = argparse.ArgumentParser(description="Query Factor Forge factor knowledge graph indexes.")
    parser.add_argument("--node-index", default=str(DEFAULT_NODE_INDEX))
    parser.add_argument("--edge-index", default=str(DEFAULT_EDGE_INDEX))
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY))
    parser.add_argument("--tag", action="append", default=[], help="Require a tag, e.g. first_passage or math_mechanism:first_passage")
    parser.add_argument("--status", action="append", default=[], help="Require a research_status tag")
    parser.add_argument("--edge-type", help="Return edges of this type instead of nodes")
    parser.add_argument("--text", default="", help="Text query")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    if args.edge_type:
        edges = [row for row in load_jsonl(Path(args.edge_index).expanduser()) if row.get("edge_type") == args.edge_type]
        print(json.dumps({"mode": "edges", "edge_type": args.edge_type, "count": len(edges), "results": edges[: args.top_k]}, ensure_ascii=False, indent=2))
        return

    required_tags, alias_resolution = resolve_tags(args.tag or [], Path(args.taxonomy).expanduser())
    required_status = set(args.status or [])
    results: list[dict[str, Any]] = []
    for row in load_jsonl(Path(args.node_index).expanduser()):
        tags = set(row.get("tags") or [])
        statuses = set(row.get("research_status") or [])
        if required_tags and not required_tags <= tags:
            continue
        if required_status and not required_status <= statuses:
            continue
        score, overlap = score_text(args.text, row) if args.text else (0.0, [])
        if args.text and score <= 0:
            continue
        results.append(
            {
                "score": score,
                "id": row.get("id"),
                "node_type": row.get("node_type"),
                "title": row.get("title"),
                "factor_ids": row.get("factor_ids"),
                "research_status": row.get("research_status"),
                "tags": row.get("tags"),
                "source_paths": row.get("source_paths"),
                "overlap_terms": overlap,
                "summary": row.get("summary"),
            }
        )
    results.sort(key=lambda row: (-float(row["score"]), str(row["id"])))
    print(
        json.dumps(
            {
                "mode": "nodes",
                "count": len(results),
                "resolved_tags": sorted(required_tags),
                "alias_resolution": alias_resolution,
                "results": results[: args.top_k],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
