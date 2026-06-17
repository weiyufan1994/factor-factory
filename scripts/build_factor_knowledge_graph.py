#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KNOWLEDGE_ROOT = REPO_ROOT / "knowledge" / "因子工厂"
DEFAULT_TAXONOMY = DEFAULT_KNOWLEDGE_ROOT / "taxonomy" / "factor_taxonomy_v1.json"
DEFAULT_NODES_DIR = DEFAULT_KNOWLEDGE_ROOT / "graph" / "nodes"
DEFAULT_NODE_INDEX = DEFAULT_KNOWLEDGE_ROOT / "graph" / "factor_knowledge_nodes.jsonl"
DEFAULT_EDGE_INDEX = DEFAULT_KNOWLEDGE_ROOT / "graph" / "factor_knowledge_edges.jsonl"
DEFAULT_MANIFEST = DEFAULT_KNOWLEDGE_ROOT / "graph" / "factor_knowledge_graph_manifest.json"

REQUIRED_NODE_FIELDS = {
    "schema_version",
    "id",
    "node_type",
    "title",
    "summary",
    "taxonomy",
    "evidence",
    "source_paths",
    "relations",
    "reuse_guidance",
}

ALLOWED_NODE_TYPES = {
    "factor",
    "mechanism",
    "anti_pattern",
    "feature_candidate",
    "methodology",
    "data_state",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def validate_taxonomy(node: dict[str, Any], taxonomy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    node_taxonomy = node.get("taxonomy")
    if not isinstance(node_taxonomy, dict):
        return ["taxonomy must be an object"]
    categories = taxonomy.get("categories") or {}
    for category, tags in node_taxonomy.items():
        if category not in categories:
            errors.append(f"{node['id']}: unknown taxonomy category {category!r}")
            continue
        allowed = set(categories[category])
        if not isinstance(tags, list):
            errors.append(f"{node['id']}: taxonomy.{category} must be a list")
            continue
        for tag in tags:
            if tag not in allowed:
                errors.append(f"{node['id']}: tag {category}.{tag} is not in taxonomy")
    return errors


def validate_relations(node: dict[str, Any], taxonomy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed_edges = set(taxonomy.get("edge_types") or [])
    relations = node.get("relations")
    if not isinstance(relations, list):
        return [f"{node['id']}: relations must be a list"]
    for idx, relation in enumerate(relations):
        if not isinstance(relation, dict):
            errors.append(f"{node['id']}: relation {idx} must be an object")
            continue
        edge_type = relation.get("edge_type")
        target = relation.get("target")
        if edge_type not in allowed_edges:
            errors.append(f"{node['id']}: relation {idx} has unknown edge_type {edge_type!r}")
        if not isinstance(target, str) or not target:
            errors.append(f"{node['id']}: relation {idx} missing target")
    return errors


def validate_node(path: Path, node: dict[str, Any], taxonomy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_NODE_FIELDS - set(node))
    if missing:
        errors.append(f"{path}: missing fields {missing}")
    if node.get("schema_version") != "factor_knowledge_node_v1":
        errors.append(f"{path}: unsupported schema_version {node.get('schema_version')!r}")
    if not isinstance(node.get("id"), str) or not node.get("id"):
        errors.append(f"{path}: id must be a non-empty string")
    if node.get("node_type") not in ALLOWED_NODE_TYPES:
        errors.append(f"{path}: unsupported node_type {node.get('node_type')!r}")
    if not isinstance(node.get("source_paths"), list):
        errors.append(f"{path}: source_paths must be a list")
    if not isinstance(node.get("reuse_guidance"), list):
        errors.append(f"{path}: reuse_guidance must be a list")
    if "taxonomy" in node:
        errors.extend(validate_taxonomy(node, taxonomy))
    if "relations" in node:
        errors.extend(validate_relations(node, taxonomy))
    return errors


def flatten_tags(node: dict[str, Any]) -> list[str]:
    tags: list[str] = [str(node.get("node_type") or "")]
    for category, values in (node.get("taxonomy") or {}).items():
        for value in values or []:
            tags.append(str(value))
            tags.append(f"{category}:{value}")
    return sorted({tag for tag in tags if tag})


def node_text(node: dict[str, Any]) -> str:
    mechanism = node.get("mechanism") or {}
    parts = [
        str(node.get("title") or ""),
        str(node.get("summary") or ""),
        " ".join(flatten_tags(node)),
        " ".join(str(item) for item in node.get("reuse_guidance") or []),
        " ".join(str(value) for value in mechanism.values() if isinstance(value, str)),
    ]
    return "\n".join(part for part in parts if part)


def build(args: argparse.Namespace) -> dict[str, Any]:
    taxonomy_path = Path(args.taxonomy).expanduser().resolve()
    nodes_dir = Path(args.nodes_dir).expanduser().resolve()
    node_index = Path(args.node_index).expanduser().resolve()
    edge_index = Path(args.edge_index).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()

    taxonomy = load_json(taxonomy_path)
    node_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for path in sorted(nodes_dir.glob("*.json")):
        node = load_json(path)
        errors.extend(validate_node(path, node, taxonomy))
        tags = flatten_tags(node)
        node_rows.append(
            {
                "id": node["id"],
                "node_type": node.get("node_type"),
                "title": node.get("title"),
                "summary": node.get("summary"),
                "factor_ids": node.get("factor_ids") or [],
                "report_ids": node.get("report_ids") or [],
                "taxonomy": node.get("taxonomy") or {},
                "research_status": (node.get("taxonomy") or {}).get("research_status") or [],
                "tags": tags,
                "evidence": node.get("evidence") or {},
                "source_paths": node.get("source_paths") or [],
                "source_node_path": str(path),
                "text": node_text(node),
            }
        )
        for relation in node.get("relations") or []:
            edge_rows.append(
                {
                    "source": node["id"],
                    "edge_type": relation.get("edge_type"),
                    "target": relation.get("target"),
                    "note": relation.get("note"),
                    "source_node_path": str(path),
                }
            )

    if errors and not args.allow_errors:
        raise SystemExit("Factor knowledge graph validation failed:\n" + "\n".join(errors))

    write_jsonl(node_index, node_rows)
    write_jsonl(edge_index, edge_rows)
    manifest = {
        "schema_version": "factor_knowledge_graph_manifest_v1",
        "created_at_utc": utc_now(),
        "taxonomy_path": str(taxonomy_path),
        "nodes_dir": str(nodes_dir),
        "node_index": str(node_index),
        "edge_index": str(edge_index),
        "node_count": len(node_rows),
        "edge_count": len(edge_rows),
        "node_types": dict(Counter(row["node_type"] for row in node_rows)),
        "tag_counts": dict(Counter(tag for row in node_rows for tag in row["tags"])),
        "errors": errors,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Factor Forge factor knowledge graph indexes.")
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY))
    parser.add_argument("--nodes-dir", default=str(DEFAULT_NODES_DIR))
    parser.add_argument("--node-index", default=str(DEFAULT_NODE_INDEX))
    parser.add_argument("--edge-index", default=str(DEFAULT_EDGE_INDEX))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--allow-errors", action="store_true")
    args = parser.parse_args()
    manifest = build(args)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
