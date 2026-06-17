#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_factor_knowledge_graph import DEFAULT_TAXONOMY, load_json, validate_node

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NODES_DIR = REPO_ROOT / "knowledge" / "因子工厂" / "graph" / "nodes"

REQUIRED_TAXONOMY = {
    "market_consensus",
    "economic_mechanism",
    "math_mechanism",
    "data_source",
    "tradability",
    "research_status",
}

EQUATION_KEYS = {
    "key_equation_latex",
    "formula_latex",
    "state_equation_latex",
    "payoff_equation_latex",
    "occupation_measure_latex",
    "signal_latex",
    "formula_candidates",
    "factor_expression",
}

INSIGHT_KEYS = {
    "dirac_style_forced_insight",
    "math_forced_insight",
    "information_preserved_removed",
    "complexity_penalty_reasoning",
}

EVIDENCE_WINDOW_KEYS = {"window", "source_window", "is_window", "sample_window", "oos_window"}
EVIDENCE_BOUNDARY_KEYS = {"falsification", "boundary", "verdict", "classification"}
USEFUL_RELATION_EDGES = {"uses_math", "shares_failure_with", "contradicts", "reusable_as", "refines", "inspires"}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def has_any_key(mapping: dict[str, Any], keys: set[str]) -> bool:
    return any(key in mapping and mapping.get(key) not in (None, "", [], {}) for key in keys)


def is_remote_path(value: str) -> bool:
    return "://" in value


def validate_source_path(node_id: str, source_path: str) -> str:
    if source_path.startswith("/tmp/"):
        raise SystemExit(f"{node_id}: source_paths must not point to temporary files: {source_path}")
    if is_remote_path(source_path):
        return "remote"
    path = Path(source_path)
    if path.is_absolute():
        try:
            repo_rel = path.resolve().relative_to(REPO_ROOT)
        except ValueError:
            return "external_local"
        candidate = REPO_ROOT / repo_rel
    else:
        candidate = REPO_ROOT / source_path
    assert_true(candidate.exists(), f"{node_id}: source_path does not exist: {source_path}")
    return "repo_local"


def resolve_node_path(value: str) -> Path:
    candidate = Path(value)
    if candidate.exists():
        return candidate
    node_candidate = DEFAULT_NODES_DIR / value
    if node_candidate.exists():
        return node_candidate
    if not value.endswith(".json"):
        node_candidate = DEFAULT_NODES_DIR / f"{value}.json"
        if node_candidate.exists():
            return node_candidate
    raise SystemExit(f"knowledge node not found: {value}")


def validate_quality(path: Path, node: dict[str, Any]) -> dict[str, Any]:
    node_id = str(node.get("id") or path.name)
    taxonomy = node.get("taxonomy") or {}
    mechanism = node.get("mechanism") or {}
    evidence = node.get("evidence") or {}
    relations = node.get("relations") or []
    relation_edge_types = {relation.get("edge_type") for relation in relations if isinstance(relation, dict)}

    missing_taxonomy = sorted(category for category in REQUIRED_TAXONOMY if not taxonomy.get(category))
    assert_true(not missing_taxonomy, f"{node_id}: missing required taxonomy values {missing_taxonomy}")
    assert_true(bool(mechanism.get("payer") or mechanism.get("economic_hypothesis")), f"{node_id}: missing payer/economic hypothesis")
    assert_true(bool(mechanism.get("receiver") or node.get("node_type") in {"methodology", "data_state"}), f"{node_id}: missing receiver")
    assert_true(bool(mechanism.get("random_object")), f"{node_id}: missing random_object")
    assert_true(has_any_key(mechanism, EQUATION_KEYS), f"{node_id}: missing equation/formula/law reference")
    assert_true(has_any_key(mechanism, INSIGHT_KEYS), f"{node_id}: missing Dirac/math-forced insight or transform note")
    assert_true(has_any_key(evidence, EVIDENCE_WINDOW_KEYS), f"{node_id}: missing evidence window")
    assert_true(bool(evidence.get("key_metrics")), f"{node_id}: missing key_metrics")
    assert_true(has_any_key(evidence, EVIDENCE_BOUNDARY_KEYS), f"{node_id}: missing falsification/boundary/verdict")
    assert_true(bool(node.get("reuse_guidance")), f"{node_id}: missing reuse_guidance")
    assert_true(bool(USEFUL_RELATION_EDGES & relation_edge_types), f"{node_id}: missing useful relation edge")

    source_paths = node.get("source_paths") or []
    assert_true(bool(source_paths), f"{node_id}: missing source_paths")
    source_path_kinds = [validate_source_path(node_id, source_path) for source_path in source_paths]
    return {
        "node_id": node_id,
        "taxonomy_categories": sorted(taxonomy),
        "relation_edge_types": sorted(relation_edge_types),
        "repo_source_path_count": source_path_kinds.count("repo_local"),
        "remote_source_path_count": source_path_kinds.count("remote"),
        "external_local_source_path_count": source_path_kinds.count("external_local"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate one Factor Forge factor knowledge graph node.")
    parser.add_argument("node", help="Node JSON path, filename under graph/nodes, or stable node filename stem.")
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY))
    args = parser.parse_args()

    path = resolve_node_path(args.node)
    taxonomy = load_json(Path(args.taxonomy).expanduser().resolve())
    node = load_json(path)
    schema_errors = validate_node(path, node, taxonomy)
    if schema_errors:
        raise SystemExit("Factor knowledge node validation failed:\n" + "\n".join(schema_errors))
    quality = validate_quality(path, node)
    print(
        json.dumps(
            {
                "verdict": "ACCEPT",
                "node_path": path.resolve().as_posix(),
                **quality,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
