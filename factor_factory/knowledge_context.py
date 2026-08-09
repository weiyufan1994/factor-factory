from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH_ROOT = REPO_ROOT / "knowledge" / "因子工厂" / "graph"
DEFAULT_NODE_INDEX = DEFAULT_GRAPH_ROOT / "factor_knowledge_nodes.jsonl"
DEFAULT_EDGE_INDEX = DEFAULT_GRAPH_ROOT / "factor_knowledge_edges.jsonl"
DEFAULT_TAXONOMY = REPO_ROOT / "knowledge" / "因子工厂" / "taxonomy" / "factor_taxonomy_v1.json"
BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE = "BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_UNAVAILABLE"

FORMULA_QUERY_EXPANSIONS = {
    "normalize": {"cross_sectional", "standardization", "zscore", "截面标准化"},
    "cs_zscore": {"cross_sectional", "standardization", "zscore", "截面标准化"},
    "s_log_lp": {"signed_log", "robust_transform", "tail_compression"},
    "s_log_1p": {"signed_log", "robust_transform", "tail_compression"},
    "signed_log1p": {"signed_log", "robust_transform", "tail_compression"},
    "ts_kurtosis": {"kurtosis", "distribution_moment", "tail", "crash_regime"},
    "rolling_excess_kurtosis": {"kurtosis", "distribution_moment", "tail", "crash_regime"},
    "rolling_pearson_kurtosis": {"kurtosis", "distribution_moment", "tail", "crash_regime"},
    "ts_max_skew": {"skewness", "distribution_moment", "volume_spike", "regime"},
    "ts_min_skew": {"skewness", "distribution_moment", "volume_baseline", "regime"},
    "rolling_topk_skew": {"skewness", "distribution_moment", "volume_spike", "regime"},
    "rolling_bottomk_skew": {"skewness", "distribution_moment", "volume_baseline", "regime"},
    "rolling_max_inner_skew": {"skewness", "distribution_moment", "volume_spike", "regime"},
    "rolling_min_inner_skew": {"skewness", "distribution_moment", "volume_baseline", "regime"},
    "ts_max_sum": {"momentum", "path_functional", "trend", "maximum_subwindow"},
    "rolling_max_subwindow_sum": {"momentum", "path_functional", "trend", "maximum_subwindow"},
    "rolling_topk_sum": {"momentum", "order_statistic", "extreme_values"},
    "volume": {"price_volume", "liquidity", "attention"},
    "close": {"price", "daily_ohlcv"},
    "returns": {"return", "price_process"},
    "change_pct": {"returns", "return", "price_process"},
}


class KnowledgeRetrievalError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_graph_node_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    parts = path.parts
    for marker in (("knowledge", "因子工厂"), ("knowledge", "factor_factory")):
        for index in range(len(parts) - len(marker) + 1):
            if tuple(parts[index : index + len(marker)]) != marker:
                continue
            remapped = REPO_ROOT.joinpath(*parts[index:])
            if remapped.is_file():
                return remapped
            return remapped
    if path.is_file():
        return path
    return path


def resolve_tags(raw_tags: list[str] | None, taxonomy_path: Path | str = DEFAULT_TAXONOMY) -> tuple[set[str], dict[str, list[str]]]:
    taxonomy = load_json(Path(taxonomy_path).expanduser()) if Path(taxonomy_path).expanduser().exists() else {}
    aliases = taxonomy.get("aliases") or {}
    resolved: set[str] = set()
    alias_resolution: dict[str, list[str]] = {}
    for raw_tag in raw_tags or []:
        mapped = aliases.get(raw_tag)
        if mapped:
            mapped_tags = [str(tag) for tag in mapped]
            resolved.update(mapped_tags)
            alias_resolution[raw_tag] = mapped_tags
        else:
            resolved.add(raw_tag)
    return resolved, alias_resolution


def tokenize(text: str) -> set[str]:
    raw = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]+", text.lower()))
    expanded = set(raw)
    for token in raw:
        if "_" in token:
            expanded.update(part for part in token.split("_") if len(part) >= 3)
    return expanded


def semantic_query_terms(text: str) -> set[str]:
    terms: set[str] = set()
    lowered = str(text or "").lower()
    lexical = tokenize(lowered)
    for name, additions in FORMULA_QUERY_EXPANSIONS.items():
        if name in lexical or re.search(rf"\b{re.escape(name)}\b", lowered):
            terms.update(additions)
    return terms


def score_text(query: str, row: dict[str, Any]) -> tuple[float, list[str]]:
    lexical_query = tokenize(query)
    semantic_query = semantic_query_terms(query)
    q = lexical_query | semantic_query
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
    haystack_terms = tokenize(haystack)
    overlap = sorted(q & haystack_terms)
    semantic_overlap = semantic_query & haystack_terms
    return float(len(overlap) + 0.5 * len(semantic_overlap)), overlap


def ensure_graph_index(node_index_path: Path, edge_index_path: Path) -> None:
    if node_index_path.exists() and edge_index_path.exists():
        return
    builder = REPO_ROOT / "scripts" / "build_factor_knowledge_graph.py"
    if not builder.exists():
        return
    subprocess.run(
        [sys.executable, str(builder)],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def compact_node(full_node: dict[str, Any], indexed_row: dict[str, Any], overlap_terms: list[str]) -> dict[str, Any]:
    taxonomy = full_node.get("taxonomy") or {}
    return {
        "id": full_node.get("id"),
        "node_type": full_node.get("node_type"),
        "title": full_node.get("title"),
        "summary": full_node.get("summary"),
        "factor_ids": full_node.get("factor_ids") or [],
        "report_ids": full_node.get("report_ids") or [],
        "taxonomy": taxonomy,
        "research_status": taxonomy.get("research_status") or indexed_row.get("research_status") or [],
        "mechanism": full_node.get("mechanism") or {},
        "evidence": full_node.get("evidence") or {},
        "relations": full_node.get("relations") or [],
        "reuse_guidance": full_node.get("reuse_guidance") or [],
        "source_paths": full_node.get("source_paths") or [],
        "source_node_path": indexed_row.get("source_node_path"),
        "overlap_terms": overlap_terms,
    }


def retrieve_factor_knowledge_context(
    *,
    text: str = "",
    tags: list[str] | None = None,
    status: list[str] | None = None,
    node_type: list[str] | None = None,
    top_k: int = 5,
    node_index: Path | str = DEFAULT_NODE_INDEX,
    edge_index: Path | str = DEFAULT_EDGE_INDEX,
    taxonomy: Path | str = DEFAULT_TAXONOMY,
) -> dict[str, Any]:
    node_index_path = Path(node_index).expanduser()
    edge_index_path = Path(edge_index).expanduser()
    ensure_graph_index(node_index_path, edge_index_path)
    for role, path in (("node", node_index_path), ("edge", edge_index_path)):
        if not path.is_file() or path.is_symlink():
            raise KnowledgeRetrievalError(
                f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: {role} index missing or unsafe: {path}"
            )
    required_tags, alias_resolution = resolve_tags(tags or [], taxonomy)
    required_status = set(status or [])
    required_node_types = set(node_type or [])
    scored_rows: list[tuple[float, list[str], dict[str, Any]]] = []

    indexed_nodes = load_jsonl(node_index_path)
    for row in indexed_nodes:
        source_node_path = row.get("source_node_path")
        if not source_node_path:
            continue
        resolved_node_path = resolve_graph_node_path(source_node_path)
        if not resolved_node_path.is_file() or resolved_node_path.is_symlink():
            raise KnowledgeRetrievalError(
                f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: stale node index row "
                f"id={row.get('id')} path={resolved_node_path}"
            )

    for row in indexed_nodes:
        row_tags = set(row.get("tags") or [])
        row_status = set(row.get("research_status") or [])
        if required_tags and not required_tags <= row_tags:
            continue
        if required_status and not required_status <= row_status:
            continue
        if required_node_types and row.get("node_type") not in required_node_types:
            continue
        score, overlap = score_text(text, row) if text else (0.0, [])
        if text and score <= 0:
            continue
        scored_rows.append((score, overlap, row))

    scored_rows.sort(key=lambda item: (-item[0], str(item[2].get("id") or "")))
    full_nodes: list[dict[str, Any]] = []
    for _score, overlap, row in scored_rows[:top_k]:
        source_node_path = row.get("source_node_path")
        if source_node_path:
            resolved_node_path = resolve_graph_node_path(source_node_path)
            full_node = load_json(resolved_node_path)
        else:
            full_node = row
        full_nodes.append(compact_node(full_node, row, overlap))

    selected_ids = {node["id"] for node in full_nodes}
    related_edges = [
        edge
        for edge in load_jsonl(edge_index_path)
        if edge.get("source") in selected_ids or edge.get("target") in selected_ids
    ]

    brief_lines: list[str] = []
    for node in full_nodes:
        status_label = ",".join(node.get("research_status") or [])
        brief_lines.append(f"- {node['id']} ({status_label}): {node.get('summary')}")
        guidance = node.get("reuse_guidance") or []
        if guidance:
            brief_lines.append(f"  reuse: {guidance[0]}")

    return {
        "schema_version": "factor_knowledge_context_v1",
        "created_at_utc": utc_now(),
        "query": {
            "text": text,
            "semantic_expansion_terms": sorted(semantic_query_terms(text)),
            "tags": tags or [],
            "resolved_tags": sorted(required_tags),
            "alias_resolution": alias_resolution,
            "status": status or [],
            "node_type": node_type or [],
            "top_k": top_k,
        },
        "node_index_path": str(node_index_path),
        "edge_index_path": str(edge_index_path),
        "node_index_available": node_index_path.exists(),
        "edge_index_available": edge_index_path.exists(),
        "node_count": len(full_nodes),
        "edge_count": len(related_edges),
        "nodes": full_nodes,
        "related_edges": related_edges,
        "researcher_brief": "\n".join(brief_lines),
    }


def graph_node_to_similar_case(node: dict[str, Any], *, score: float = 0.0) -> dict[str, Any]:
    taxonomy = node.get("taxonomy") or {}
    statuses = set(taxonomy.get("research_status") or node.get("research_status") or [])
    failure_modes = taxonomy.get("failure_mode") or []
    market_consensus = taxonomy.get("market_consensus") or []
    economic_mechanism = taxonomy.get("economic_mechanism") or []
    factor_ids = node.get("factor_ids") or []
    report_ids = node.get("report_ids") or []
    knowledge_scope = "anti_pattern" if "anti_pattern" in statuses or "rejected" in statuses else "similar_case"
    decision = "reject" if knowledge_scope == "anti_pattern" or "standalone_rejected" in statuses else (
        "promote_official" if "official" in statuses else "needs_human_review"
    )
    return {
        "score": round(score, 4),
        "lexical_score": round(score, 4),
        "report_id": report_ids[0] if report_ids else node.get("id"),
        "factor_id": factor_ids[0] if factor_ids else node.get("id"),
        "doc_type": "factor_knowledge_graph_node",
        "decision": decision,
        "knowledge_scope": knowledge_scope,
        "factor_family": (market_consensus or economic_mechanism or ["knowledge_graph"])[0],
        "failure_signature": failure_modes[0] if failure_modes else None,
        "formula_hash": None,
        "artifact_identity": {},
        "source_identity": {"graph_node_id": node.get("id"), "source_node_path": node.get("source_node_path")},
        "source_path": node.get("source_node_path"),
        "overlap_terms": node.get("overlap_terms") or [],
        "snippet": str(node.get("summary") or "")[:280],
        "graph_node_id": node.get("id"),
        "taxonomy": taxonomy,
        "mechanism": node.get("mechanism") or {},
        "evidence": node.get("evidence") or {},
        "reuse_guidance": node.get("reuse_guidance") or [],
        "not_same_factor_unless_identity_matches": True,
    }
