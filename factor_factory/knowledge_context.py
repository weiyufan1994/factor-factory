from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from factor_factory.research_org.contracts import (
    MAX_CONTRACT_JSON_BYTES,
    ResearchOrganizationError,
    SAFE_ID_RE,
    SHA256_RE,
    read_workspace_bytes,
    stable_json_hash,
    strict_json_loads,
    with_content_hash,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH_ROOT = REPO_ROOT / "knowledge" / "因子工厂" / "graph"
DEFAULT_NODE_INDEX = DEFAULT_GRAPH_ROOT / "factor_knowledge_nodes.jsonl"
DEFAULT_EDGE_INDEX = DEFAULT_GRAPH_ROOT / "factor_knowledge_edges.jsonl"
DEFAULT_TAXONOMY = REPO_ROOT / "knowledge" / "因子工厂" / "taxonomy" / "factor_taxonomy_v1.json"
BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE = "BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_UNAVAILABLE"
BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID = (
    "BLOCK_FACTORFORGE_EVO_V2_MEMORY_RETRIEVAL_INVALID"
)
EVO_V2_MEMORY_RETRIEVAL_PROJECTION_VERSION = (
    "factorforge_researcher_memory_evo_v2_retrieval_projection_v1"
)
EVO_V2_COLD_START_SEARCH_RECEIPT_TYPE = (
    "factorforge_researcher_memory_evo_v2_cold_start_search_receipt_v1"
)
EVO_V2_COLD_START_SEARCH_REQUEST_VERSION = (
    "factorforge_researcher_memory_evo_v2_cold_start_search_request_v1"
)
EVO_V2_COLD_START_SEARCH_AGENT_RECORD_VERSION = (
    "factorforge_researcher_memory_evo_v2_cold_start_search_agent_record_v1"
)
EVO_V2_COLD_START_SEARCH_ROLE_ID = "knowledge_librarian"
EVO_V2_COLD_START_SEARCH_SESSIONS_ROOT = (
    "researcher-memory-evo-v2-retrieval-sessions"
)

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

# A named mathematical method has two deliberately separate projections:
# ``anchors`` prove that a graph row actually knows that method, while
# ``bridges`` describe nearby mathematical ideas.  A bridge never substitutes
# for a missing anchor.  This prevents a generic multiscale/path node from being
# reported as a wavelet or convolution hit.
NAMED_MATH_QUERY_PROFILES: dict[str, dict[str, set[str]]] = {
    "wavelet": {
        "triggers": {"wavelet", "小波", "ψ", "psi"},
        "anchors": {"wavelet", "wavelets", "wavelet_transform", "小波"},
        "bridges": {"multiscale", "time_frequency", "local_energy"},
    },
    "kalman": {
        "triggers": {"kalman", "卡尔曼"},
        "anchors": {"kalman", "kalman_filter", "卡尔曼"},
        "bridges": {"state_space", "latent_state", "filtering"},
    },
    "convolution": {
        "triggers": {"convolution", "convolutional", "卷积"},
        "anchors": {"convolution", "convolutional", "convolution_kernel", "卷积"},
        "bridges": {"kernel", "local_filter", "multiscale"},
    },
    "variational": {
        "triggers": {"variational", "变分"},
        "anchors": {"variational", "variational_method", "变分"},
        "bridges": {"latent_state", "regularization", "posterior", "optimization"},
    },
}

# These words describe the fact that a method is being discussed, not the
# economic or mathematical content of the query.  Once a named method profile
# fires they are excluded from lexical fallback, so ``小波分析`` cannot retrieve
# a generic analysis node and ``卡尔曼滤波`` cannot retrieve generic filtering.
NAMED_MATH_GENERIC_COMPANIONS = {
    "analysis",
    "method",
    "model",
    "filter",
    "filtering",
    "estimator",
    "estimation",
    "algorithm",
    "transform",
    "framework",
    "分析",
    "方法",
    "模型",
    "滤波",
    "估计",
    "算法",
    "变换",
    "框架",
    # Formula punctuation accompanying the auditable wavelet mother-function
    # alias is not independent mechanism evidence.
    "∫",
    "integral",
}

# Auditable formula aliases.  The symbol itself only selects a named profile;
# it never supplies lexical fallback when the corpus lacks a typed anchor.
FORMULA_SYMBOL_NAMED_MATH_ALIASES = {"ψ": "wavelet"}

# Exact mechanism anchors are intentionally distinct from broad semantic
# bridges.  For example, a query for ``liquidity`` may match a node whose title
# or typed tag says exactly liquidity, but must not match merely because a
# longer token ends in that word (``illiquidity`` or ``liquidity_provision``).
# This also gives Chinese and English queries the same deterministic anchor.
EXACT_MECHANISM_QUERY_PROFILES: dict[str, dict[str, set[str]]] = {
    "liquidity": {
        "triggers": {"liquidity", "流动性"},
        "anchors": {"liquidity", "流动性"},
    },
}

# Generic bridge concepts are weaker still.  One bridge concept alone is never
# a hit, even when it expands to several terms.  Two concepts count only when
# they match distinct graph terms.
SEMANTIC_BRIDGE_QUERY_EXPANSIONS = {
    "liquidity": {"liquidity", "liquidity_provision", "price_volume"},
    "流动性": {"liquidity", "liquidity_provision", "price_volume"},
    "crowding": {"crowding", "crowded", "constraint"},
    "拥挤": {"crowding", "crowded", "constraint"},
    "local": {"local", "localized"},
    "局部": {"local", "localized"},
    "energy": {"energy", "local_energy"},
    "能量": {"energy", "local_energy"},
    "scale": {"scale", "multiscale"},
    "尺度": {"scale", "multiscale"},
    "time_frequency": {"time_frequency", "multiscale"},
    "时频": {"time_frequency", "multiscale"},
    "withdrawal": {"withdrawal", "liquidity_provision", "constraint"},
    "撤退": {"withdrawal", "liquidity_provision", "constraint"},
    "pressure": {"pressure", "forced_flow", "inventory_pressure"},
    "压力": {"pressure", "forced_flow", "inventory_pressure"},
}
MECHANISM_BRIDGE_TRIGGERS = {
    "liquidity",
    "流动性",
    "crowding",
    "拥挤",
    "withdrawal",
    "撤退",
    "pressure",
    "压力",
}

GREEK_TOKEN_ALIASES = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "epsilon",
    "θ": "theta",
    "λ": "lambda",
    "μ": "mu",
    "π": "pi",
    "ρ": "rho",
    "σ": "sigma",
    "τ": "tau",
    "φ": "phi",
    "ω": "omega",
    "ψ": "psi",
}
MATH_SYMBOL_TOKEN_ALIASES = {
    "∂": "partial",
    "∇": "nabla",
    "∑": "sum",
    "∏": "product",
    "∫": "integral",
    "√": "sqrt",
    "∞": "infinity",
    "×": "multiply",
    "⊗": "tensor_product",
    "±": "plus_minus",
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


def resolve_graph_node_path(
    raw_path: str | Path, *, repo_root: Path | None = None,
    graph_root: Path | None = None,
) -> Path:
    path = Path(raw_path).expanduser()
    parts = path.parts
    if graph_root is not None:
        # An explicitly selected export must never read an identically named
        # node from the installed checkout. Portable indexes can carry either
        # nodes/foo.json or historical .../graph/nodes/foo.json paths.
        root = Path(graph_root).expanduser().resolve()
        if ".." in parts:
            raise KnowledgeRetrievalError("graph node path escapes selected graph")
        graph_positions = [
            i for i in range(len(parts) - 1)
            if parts[i:i + 2] == ("graph", "nodes")
        ]
        if graph_positions:
            candidate = root.joinpath(*parts[graph_positions[-1] + 1:])
        elif not path.is_absolute():
            candidate = root / path
        else:
            candidate = path
        if not candidate.resolve().is_relative_to(root):
            raise KnowledgeRetrievalError("graph node path escapes selected graph")
        return candidate
    checkout_root = Path(repo_root) if repo_root is not None else REPO_ROOT
    for marker in (("knowledge", "因子工厂"), ("knowledge", "factor_factory")):
        for index in range(len(parts) - len(marker) + 1):
            if tuple(parts[index : index + len(marker)]) != marker:
                continue
            remapped = checkout_root.joinpath(*parts[index:])
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
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    raw = set(
        re.findall(
            r"[a-z_][a-z0-9_]{2,}|[\u0370-\u03ff]+|[\u3400-\u9fff]+|"
            r"[\u2202\u2207\u220f\u2211\u221a\u221e\u222b\u00d7\u00b1\u2297]",
            normalized,
        )
    )
    expanded = set(raw)
    for token in raw:
        if "_" in token:
            expanded.update(part for part in token.split("_") if len(part) >= 3)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            # Chinese prose is normally unsegmented.  Whole-span matching made a
            # natural-language query miss a node unless the complete sentence was
            # repeated verbatim.  Short character n-grams provide a deterministic,
            # dependency-free lexical floor; typed taxonomy and graph filters still
            # carry the semantic precision.
            for width in range(2, min(4, len(token)) + 1):
                expanded.update(
                    token[start : start + width]
                    for start in range(0, len(token) - width + 1)
                )
        if re.fullmatch(r"[\u0370-\u03ff]+", token):
            for symbol in token:
                expanded.add(symbol)
                alias = GREEK_TOKEN_ALIASES.get(symbol)
                if alias:
                    expanded.add(alias)
        alias = MATH_SYMBOL_TOKEN_ALIASES.get(token)
        if alias:
            expanded.add(alias)
    return expanded


def _semantic_expansion_terms(text: str, mapping: Mapping[str, set[str]]) -> set[str]:
    terms: set[str] = set()
    lowered = unicodedata.normalize("NFKC", str(text or "")).casefold()
    lexical = tokenize(lowered)
    for name, additions in mapping.items():
        normalized_name = unicodedata.normalize("NFKC", name).casefold()
        if normalized_name in lexical or re.search(
            rf"(?<![\w]){re.escape(normalized_name)}(?![\w])", lowered
        ):
            terms.update(additions)
    return terms


def _query_has_trigger(text: str, trigger: str) -> bool:
    lowered = unicodedata.normalize("NFKC", str(text or "")).casefold()
    normalized_trigger = unicodedata.normalize("NFKC", trigger).casefold()
    lexical = tokenize(lowered)
    return normalized_trigger in lexical or re.search(
        rf"(?<![\w]){re.escape(normalized_trigger)}(?![\w])", lowered
    ) is not None


def _triggered_named_math_profiles(text: str) -> list[tuple[str, Mapping[str, set[str]]]]:
    return [
        (profile_id, profile)
        for profile_id, profile in NAMED_MATH_QUERY_PROFILES.items()
        if any(_query_has_trigger(text, trigger) for trigger in profile["triggers"])
    ]


def _triggered_exact_mechanism_profiles(
    text: str,
) -> list[tuple[str, Mapping[str, set[str]]]]:
    return [
        (profile_id, profile)
        for profile_id, profile in EXACT_MECHANISM_QUERY_PROFILES.items()
        if any(_query_has_trigger(text, trigger) for trigger in profile["triggers"])
    ]


def _anchor_terms(row: Mapping[str, Any]) -> set[str]:
    """Return only exact title/id/tag atoms, without underscore suffix splitting."""

    terms = tokenize(f"{row.get('id') or ''} {row.get('title') or ''}")
    for raw_tag in row.get("tags") or []:
        normalized = unicodedata.normalize("NFKC", str(raw_tag)).casefold()
        terms.add(normalized)
        if ":" in normalized:
            terms.add(normalized.rsplit(":", 1)[-1])
    return terms


def _triggered_bridge_concepts(
    text: str,
) -> list[tuple[tuple[str, ...], set[str], str]]:
    grouped: dict[tuple[frozenset[str], str], list[str]] = {}
    for trigger, additions in SEMANTIC_BRIDGE_QUERY_EXPANSIONS.items():
        if _query_has_trigger(text, trigger):
            category = (
                "MECHANISM"
                if trigger in MECHANISM_BRIDGE_TRIGGERS
                else "GENERIC_MATH"
            )
            grouped.setdefault((frozenset(additions), category), []).append(trigger)
    return [
        (tuple(triggers), set(additions), category)
        for (additions, category), triggers in grouped.items()
    ]


def semantic_query_specific_terms(text: str) -> set[str]:
    terms = _semantic_expansion_terms(text, FORMULA_QUERY_EXPANSIONS)
    for _profile_id, profile in _triggered_named_math_profiles(text):
        terms.update(profile["anchors"])
    for _profile_id, profile in _triggered_exact_mechanism_profiles(text):
        terms.update(profile["anchors"])
    return terms


def semantic_query_bridge_terms(text: str) -> set[str]:
    terms = _semantic_expansion_terms(text, SEMANTIC_BRIDGE_QUERY_EXPANSIONS)
    for _profile_id, profile in _triggered_named_math_profiles(text):
        terms.update(profile["bridges"])
    return terms


def semantic_query_terms(text: str) -> set[str]:
    return semantic_query_specific_terms(text) | semantic_query_bridge_terms(text)


def score_text(query: str, row: dict[str, Any]) -> tuple[float, list[str]]:
    lexical_query = tokenize(query)
    legacy_specific_query = _semantic_expansion_terms(query, FORMULA_QUERY_EXPANSIONS)
    named_profiles = _triggered_named_math_profiles(query)
    exact_mechanism_profiles = _triggered_exact_mechanism_profiles(query)
    named_anchor_query = {
        term
        for _profile_id, profile in named_profiles
        for term in profile["anchors"]
    }
    exact_mechanism_anchor_query = {
        term
        for _profile_id, profile in exact_mechanism_profiles
        for term in profile["anchors"]
    }
    bridge_concepts = _triggered_bridge_concepts(query)
    named_bridge_query = {
        term
        for _profile_id, profile in named_profiles
        for term in profile["bridges"]
    }
    generic_bridge_query = {
        term
        for _triggers, additions, _category in bridge_concepts
        for term in additions
    }
    specific_query = (
        legacy_specific_query
        | named_anchor_query
        | exact_mechanism_anchor_query
    )
    bridge_query = named_bridge_query | generic_bridge_query
    q = lexical_query | specific_query | bridge_query
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
    anchor_haystack_terms = _anchor_terms(row)

    suppressed_lexical: set[str] = set()
    for triggers, _additions, _category in bridge_concepts:
        for trigger in triggers:
            suppressed_lexical.update(tokenize(trigger))
    for _profile_id, profile in named_profiles:
        for trigger in profile["triggers"]:
            if _query_has_trigger(query, trigger):
                suppressed_lexical.update(tokenize(trigger))
    if named_profiles:
        for companion in NAMED_MATH_GENERIC_COMPANIONS:
            if _query_has_trigger(query, companion):
                suppressed_lexical.update(tokenize(companion))
    for _profile_id, profile in exact_mechanism_profiles:
        for trigger in profile["triggers"]:
            if _query_has_trigger(query, trigger):
                suppressed_lexical.update(tokenize(trigger))
    lexical_overlap = (lexical_query - suppressed_lexical) & haystack_terms
    legacy_specific_overlap = legacy_specific_query & haystack_terms
    named_anchor_overlap = named_anchor_query & anchor_haystack_terms
    exact_mechanism_anchor_overlap = (
        exact_mechanism_anchor_query & anchor_haystack_terms
    )
    bridge_overlap = bridge_query & haystack_terms

    matched_named_profiles = 0
    for _profile_id, profile in named_profiles:
        if profile["anchors"] & anchor_haystack_terms:
            matched_named_profiles += 1
    matched_bridge_concepts = 0
    matched_mechanism_bridge_concepts = 0
    used_bridge_terms: set[str] = set()
    for _triggers, additions, category in bridge_concepts:
        available = sorted((additions & haystack_terms) - used_bridge_terms)
        if available:
            matched_bridge_concepts += 1
            if category == "MECHANISM":
                matched_mechanism_bridge_concepts += 1
            used_bridge_terms.add(available[0])

    # A named method is a claim about corpus coverage.  If its anchor is absent,
    # the row may still be returned as an explicitly broader analogy when the
    # economic/mechanism query independently matches either direct lexical
    # evidence or at least two distinct generic bridge concepts.  The named
    # method's own nearby terms can never establish that fallback by themselves.
    if (
        named_profiles
        and matched_named_profiles == 0
        and not lexical_overlap
        and not legacy_specific_overlap
        and matched_mechanism_bridge_concepts < 2
    ):
        return 0.0, []

    if (
        not lexical_overlap
        and not legacy_specific_overlap
        and not named_anchor_overlap
        and not exact_mechanism_anchor_overlap
        and matched_bridge_concepts < 2
    ):
        return 0.0, []
    overlap = sorted(
        lexical_overlap
        | legacy_specific_overlap
        | named_anchor_overlap
        | exact_mechanism_anchor_overlap
        | bridge_overlap
    )
    score = (
        3.0 * len(lexical_overlap)
        + 2.0 * len(legacy_specific_overlap)
        + 6.0 * len(named_anchor_overlap)
        + 5.0 * len(exact_mechanism_anchor_overlap)
        + 0.5 * matched_bridge_concepts
        + 0.25 * len(bridge_overlap)
    )
    return score, overlap


def ensure_graph_index(node_index_path: Path, edge_index_path: Path) -> None:
    for role, path in (("node", node_index_path), ("edge", edge_index_path)):
        if not path.is_file() or path.is_symlink():
            raise KnowledgeRetrievalError(
                f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: "
                f"{role} index missing or unsafe: {path}"
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
    repo_root: Path | None = None,
    graph_root: Path | None = None,
) -> dict[str, Any]:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")
    node_index_path = Path(node_index).expanduser()
    edge_index_path = Path(edge_index).expanduser()
    ensure_graph_index(node_index_path, edge_index_path)
    required_tags, alias_resolution = resolve_tags(tags or [], taxonomy)
    required_status = set(status or [])
    required_node_types = set(node_type or [])
    scored_rows: list[tuple[float, list[str], dict[str, Any]]] = []

    indexed_nodes = load_jsonl(node_index_path)
    for row in indexed_nodes:
        source_node_path = row.get("source_node_path")
        if not source_node_path:
            continue
        resolved_node_path = resolve_graph_node_path(
            source_node_path, repo_root=repo_root, graph_root=graph_root
        )
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
            resolved_node_path = resolve_graph_node_path(
                source_node_path, repo_root=repo_root, graph_root=graph_root
            )
            full_node = load_json(resolved_node_path)
        else:
            full_node = row
        compact = compact_node(full_node, row, overlap)
        if graph_root is not None and source_node_path:
            compact["source_node_path"] = str(resolved_node_path.resolve())
        full_nodes.append(compact)

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


_EVO_V2_FINGERPRINT_FIELDS = {
    "economic_claim",
    "estimand_id",
    "payer_or_constraint",
    "mathematical_object",
    "broken_invariant_or_boundary",
    "observation_mapping",
    "failure_signature",
}
_EVO_V2_RETRIEVAL_LANES = (
    "structural_isomorph",
    "cross_math_analogy",
    "near_miss_failure",
    "direct_counterexample",
    "historical_episode_context",
)
_EVO_V2_IDENTITY_FIELDS = {
    "factor_id",
    "report_id",
    "research_id",
    "branch_id",
    "run_id",
}
_EVO_V2_COLD_START_INDEX_IDS = {"role_memory", "factor_knowledge"}


def _evo_v2_fingerprint_reasons(value: Any) -> list[str]:
    if not isinstance(value, Mapping) or set(value) != _EVO_V2_FINGERPRINT_FIELDS:
        return ["mechanism_fingerprint_fields"]
    reasons: list[str] = []
    for field in _EVO_V2_FINGERPRINT_FIELDS:
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            reasons.append(f"mechanism_fingerprint_{field}")
    if not SAFE_ID_RE.fullmatch(str(value.get("estimand_id") or "")):
        reasons.append("mechanism_fingerprint_estimand_id")
    return reasons


def _evo_v2_cold_start_query_hash(
    mechanism_fingerprint: Mapping[str, Any],
) -> str:
    return stable_json_hash(
        {
            "query_mode": "MECHANISM_FIRST_AFTER_BLIND_DERIVATION",
            "mechanism_fingerprint": dict(mechanism_fingerprint),
        }
    )


def validate_evo_v2_cold_start_search_receipt(
    receipt: Any,
    *,
    artifact_identity: Mapping[str, Any],
    mechanism_fingerprint: Mapping[str, Any],
    trust_store: Any,
) -> list[str]:
    """Validate zero-hit proof from a completed isolated retrieval session."""

    from factor_factory.researcher_memory_review import (
        _evo_v2_adapter_completion_reasons,
    )

    reasons: list[str] = []
    if not isinstance(receipt, Mapping):
        return ["cold_start_search_receipt_object"]
    expected_fields = {
        "contract_version",
        "authority",
        "artifact_identity",
        "query",
        "inventory",
        "retrieval_runtime",
        "authority_guard",
        "receipt_sha256",
    }
    if set(receipt) != expected_fields:
        reasons.append("cold_start_search_receipt_fields")
    if (
        receipt.get("contract_version") != EVO_V2_COLD_START_SEARCH_RECEIPT_TYPE
        or receipt.get("authority")
        != "runtime_attested_zero_hit_search_host_admission_required"
    ):
        reasons.append("cold_start_search_receipt_type")
    if (
        not isinstance(artifact_identity, Mapping)
        or set(artifact_identity) != _EVO_V2_IDENTITY_FIELDS
        or receipt.get("artifact_identity") != artifact_identity
        or any(
            not SAFE_ID_RE.fullmatch(str(artifact_identity.get(field) or ""))
            for field in _EVO_V2_IDENTITY_FIELDS
        )
    ):
        reasons.append("cold_start_search_identity")
    reasons.extend(_evo_v2_fingerprint_reasons(mechanism_fingerprint))
    expected_query = {
        "query_mode": "MECHANISM_FIRST_AFTER_BLIND_DERIVATION",
        "mechanism_fingerprint_sha256": stable_json_hash(
            dict(mechanism_fingerprint)
        ),
        "query_sha256": _evo_v2_cold_start_query_hash(mechanism_fingerprint),
    }
    if receipt.get("query") != expected_query:
        reasons.append("cold_start_search_query_binding")
    runtime = receipt.get("retrieval_runtime")
    if not isinstance(runtime, Mapping) or set(runtime) != {
        "adapter_completion_receipt",
        "search_request",
        "search_output",
        "search_output_bytes_b64",
        "search_output_sha256",
        "model_execution",
    }:
        reasons.append("cold_start_search_runtime_fields")
        runtime = {}
    request = runtime.get("search_request")
    output = runtime.get("search_output")
    request_reasons = _evo_v2_cold_search_request_reasons(
        request,
        artifact_identity=artifact_identity,
        mechanism_fingerprint=mechanism_fingerprint,
    )
    reasons.extend(request_reasons)
    try:
        raw_output = base64.b64decode(
            str(runtime.get("search_output_bytes_b64") or ""),
            validate=True,
        )
        parsed_output = json.loads(raw_output.decode("utf-8"))
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        raw_output = b""
        parsed_output = None
        reasons.append("cold_start_search_output_bytes")
    if (
        parsed_output != output
        or hashlib.sha256(raw_output).hexdigest()
        != runtime.get("search_output_sha256")
    ):
        reasons.append("cold_start_search_output_readback")
    output_reasons, output_inventory = _evo_v2_cold_search_output_reasons(
        output,
        request=request if isinstance(request, Mapping) else {},
    )
    reasons.extend(output_reasons)
    if receipt.get("inventory") != output_inventory:
        reasons.append("cold_start_search_inventory_binding")
    adapter = runtime.get("adapter_completion_receipt")
    adapter_identity = (
        adapter.get("identity") if isinstance(adapter, Mapping) else {}
    )
    adapter_session = (
        adapter.get("session") if isinstance(adapter, Mapping) else {}
    )
    reviewer_runtime_instance_id = str(
        (request or {}).get("runtime_instance_id") or ""
    )
    reasons.extend(
        _evo_v2_adapter_completion_reasons(
            adapter,
            artifact_identity=artifact_identity,
            trust_store=trust_store,
            expected_role_id=EVO_V2_COLD_START_SEARCH_ROLE_ID,
            expected_task_sha256=(request or {}).get("request_sha256"),
            expected_session_id=(request or {}).get("retrieval_session_id"),
            expected_runtime_instance_id=reviewer_runtime_instance_id,
            expected_output_sha256=runtime.get("search_output_sha256"),
            expected_output_size_bytes=len(raw_output),
        )
    )
    if (
        adapter_identity.get("task_id") != (request or {}).get("task_id")
        or adapter_session.get("session_uid")
        != (request or {}).get("retrieval_session_id")
    ):
        reasons.append("cold_start_search_runtime_identity")
    model_execution = runtime.get("model_execution")
    if (
        not isinstance(model_execution, Mapping)
        or set(model_execution)
        != {
            "provider",
            "model",
            "transport",
            "isolation_class",
            "owned_termination_supported",
        }
        or any(
            not isinstance(model_execution.get(field), str)
            or not model_execution.get(field)
            for field in ("provider", "model", "transport", "isolation_class")
        )
        or model_execution.get("owned_termination_supported") is not True
    ):
        reasons.append("cold_start_search_model_execution")
    if receipt.get("authority_guard") != {
        "blind_derivation_completed": True,
        "regime_shortcut_allowed": False,
        "current_factor_proof_authority": False,
        "host_admission_required": True,
    }:
        reasons.append("cold_start_search_authority_guard")
    from factor_factory.research_org.contracts import validate_content_hash

    reasons.extend(
        validate_content_hash(
            receipt,
            hash_field="receipt_sha256",
            label="evo_v2_cold_start_search_receipt",
        )
    )
    return list(dict.fromkeys(reasons))


def _evo_v2_cold_search_request_reasons(
    request: Any,
    *,
    artifact_identity: Mapping[str, Any],
    mechanism_fingerprint: Mapping[str, Any],
) -> list[str]:
    from factor_factory.research_org.contracts import validate_content_hash

    if not isinstance(request, Mapping):
        return ["cold_start_search_request_object"]
    reasons: list[str] = []
    if set(request) != {
        "contract_version",
        "artifact_identity",
        "executor_role_id",
        "task_id",
        "retrieval_session_id",
        "runtime_instance_id",
        "query",
        "mechanism_fingerprint",
        "checked_indexes",
        "blind_derivation_completed",
        "policy",
        "request_sha256",
    }:
        reasons.append("cold_start_search_request_fields")
    if (
        request.get("contract_version")
        != EVO_V2_COLD_START_SEARCH_REQUEST_VERSION
        or request.get("artifact_identity") != artifact_identity
        or request.get("executor_role_id") != EVO_V2_COLD_START_SEARCH_ROLE_ID
        or request.get("mechanism_fingerprint") != mechanism_fingerprint
        or request.get("query")
        != {
            "query_mode": "MECHANISM_FIRST_AFTER_BLIND_DERIVATION",
            "mechanism_fingerprint_sha256": stable_json_hash(
                dict(mechanism_fingerprint)
            ),
            "query_sha256": _evo_v2_cold_start_query_hash(
                mechanism_fingerprint
            ),
        }
        or request.get("blind_derivation_completed") is not True
        or request.get("policy")
        != {
            "must_inspect_every_bound_index_snapshot": True,
            "regime_shortcut_allowed": False,
            "historical_performance_ranking_allowed": False,
            "current_factor_proof_authority": False,
        }
        or not SAFE_ID_RE.fullmatch(str(request.get("task_id") or ""))
        or not SAFE_ID_RE.fullmatch(
            str(request.get("retrieval_session_id") or "")
        )
        or not SAFE_ID_RE.fullmatch(
            str(request.get("runtime_instance_id") or "")
        )
    ):
        reasons.append("cold_start_search_request_binding")
    indexes = request.get("checked_indexes")
    observed_ids: set[str] = set()
    if not isinstance(indexes, list) or len(indexes) != 2:
        reasons.append("cold_start_search_request_indexes")
    else:
        for item in indexes:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"index_id", "path", "sha256"}
                or not SAFE_ID_RE.fullmatch(str(item.get("index_id") or ""))
                or not isinstance(item.get("path"), str)
                or Path(str(item.get("path"))).is_absolute()
                or ".." in Path(str(item.get("path"))).parts
                or not SHA256_RE.fullmatch(str(item.get("sha256") or ""))
            ):
                reasons.append("cold_start_search_request_index_entry")
                continue
            observed_ids.add(str(item["index_id"]))
    if observed_ids != _EVO_V2_COLD_START_INDEX_IDS:
        reasons.append("cold_start_search_request_index_scope")
    reasons.extend(
        validate_content_hash(
            request,
            hash_field="request_sha256",
            label="evo_v2_cold_start_search_request",
        )
    )
    return list(dict.fromkeys(reasons))


def _assert_evo_v2_cold_search_index_readback(
    *,
    context_root: Path,
    request: Mapping[str, Any],
) -> None:
    indexes = request.get("checked_indexes")
    if not isinstance(indexes, list) or len(indexes) != 2:
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: "
            "cold_start_search_index_readback"
        )
    try:
        observed_ids: set[str] = set()
        for item in indexes:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"index_id", "path", "sha256"}
            ):
                raise ValueError("invalid index binding")
            index_id = item.get("index_id")
            relative = item.get("path")
            expected_sha256 = item.get("sha256")
            if (
                not isinstance(index_id, str)
                or not SAFE_ID_RE.fullmatch(index_id)
                or not isinstance(relative, str)
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or not isinstance(expected_sha256, str)
                or not SHA256_RE.fullmatch(expected_sha256)
            ):
                raise ValueError("invalid index binding")
            observed_ids.add(index_id)
            observed = read_workspace_bytes(context_root, relative)
            if hashlib.sha256(observed).hexdigest() != expected_sha256:
                raise ValueError("index hash mismatch")
        if observed_ids != _EVO_V2_COLD_START_INDEX_IDS:
            raise ValueError("invalid index scope")
    except (OSError, ResearchOrganizationError, ValueError) as exc:
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: "
            "cold_start_search_index_readback"
        ) from exc


def _evo_v2_cold_search_invocation_reasons(
    *,
    request: Any,
    invocation: Any,
) -> list[str]:
    if not isinstance(request, Mapping):
        return ["cold_start_search_invocation_binding"]
    reasons: list[str] = []
    if request.get("task_id") != invocation.task_id:
        reasons.append("cold_start_search_task_binding")
    if request.get("retrieval_session_id") != invocation.session_id:
        reasons.append("cold_start_search_session_binding")
    if request.get("runtime_instance_id") != invocation.runtime_instance_id:
        reasons.append("cold_start_search_runtime_binding")
    if (
        request.get("request_sha256") != invocation.task_sha256
        or request.get("request_sha256")
        != invocation.context_manifest_sha256
    ):
        reasons.append("cold_start_search_task_hash_binding")
    return reasons


def _evo_v2_cold_search_output_reasons(
    output: Any,
    *,
    request: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    from factor_factory.research_org.runtime import (
        PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
    )

    reasons: list[str] = []
    empty_inventory = {"checked_indexes": [], "admissible_hit_count": -1}
    if not isinstance(output, Mapping) or set(output) != {
        "contract_version",
        "status",
        "public_research_record",
    }:
        return ["cold_start_search_output_fields"], empty_inventory
    record = output.get("public_research_record")
    if (
        output.get("contract_version") != PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION
        or output.get("status") != "PASS"
        or not isinstance(record, Mapping)
        or set(record)
        != {
            "contract_version",
            "artifact_identity",
            "executor_role_id",
            "query_sha256",
            "checked_indexes",
            "admissible_hits",
            "admissible_hit_count",
            "memory_state",
        }
        or record.get("contract_version")
        != EVO_V2_COLD_START_SEARCH_AGENT_RECORD_VERSION
        or record.get("artifact_identity") != request.get("artifact_identity")
        or record.get("executor_role_id") != EVO_V2_COLD_START_SEARCH_ROLE_ID
        or record.get("query_sha256")
        != (request.get("query") or {}).get("query_sha256")
        or record.get("checked_indexes") != request.get("checked_indexes")
        or record.get("admissible_hits") != []
        or record.get("admissible_hit_count") != 0
        or record.get("memory_state") != "COLD_START_NO_ADMISSIBLE_MEMORY"
    ):
        reasons.append("cold_start_search_output_binding")
    inventory = {
        "checked_indexes": [
            {
                "index_id": item.get("index_id"),
                "snapshot_sha256": item.get("sha256"),
            }
            for item in (request.get("checked_indexes") or [])
            if isinstance(item, Mapping)
        ],
        "admissible_hit_count": 0,
    }
    return reasons, inventory


def prepare_evo_v2_cold_start_search_session(
    *,
    workspace: Path,
    worktree: Path,
    state_root: Path,
    installation_id: str,
    host_job_id: str,
    artifact_identity: Mapping[str, Any],
    mechanism_fingerprint: Mapping[str, Any],
    checked_indexes: Sequence[Mapping[str, Any]],
    timeout_seconds: int = 1800,
) -> tuple[Any, dict[str, Any], Path]:
    """Stage exact index snapshots for an isolated Knowledge Librarian search."""

    from factor_factory.research_org.contracts import (
        normalize_workspace_relative_path,
        read_workspace_bytes,
    )
    from factor_factory.research_org.runtime import ResearchOrgSessionInvocation
    from factor_factory.researcher_memory import (
        _assert_private_root,
        _ensure_private_directory,
    )
    from factor_factory.researcher_memory_review import (
        _json_bytes,
        _private_write_bytes,
    )

    workspace = Path(workspace).expanduser().resolve(strict=True)
    worktree = Path(worktree).expanduser().resolve(strict=True)
    state_root = Path(state_root).expanduser().resolve(strict=True)
    reasons = _evo_v2_fingerprint_reasons(mechanism_fingerprint)
    if (
        not isinstance(artifact_identity, Mapping)
        or set(artifact_identity) != _EVO_V2_IDENTITY_FIELDS
        or any(
            not SAFE_ID_RE.fullmatch(str(artifact_identity.get(field) or ""))
            for field in _EVO_V2_IDENTITY_FIELDS
        )
    ):
        reasons.append("cold_start_search_identity")
    if re.fullmatch(r"job_[a-f0-9]{10}", host_job_id) is None:
        reasons.append("cold_start_search_host_job_id")
    resolved_index_snapshots: list[tuple[dict[str, Any], bytes]] = []
    observed_ids: set[str] = set()
    for item in checked_indexes:
        if not isinstance(item, Mapping) or set(item) != {
            "index_id",
            "path",
            "sha256",
        }:
            reasons.append("cold_start_search_index_fields")
            continue
        relative = normalize_workspace_relative_path(
            item.get("path"),
            workspace=workspace,
            label="cold_start_search_index",
        )
        raw = read_workspace_bytes(workspace, relative)
        if hashlib.sha256(raw).hexdigest() != item.get("sha256"):
            reasons.append("cold_start_search_index_readback")
        resolved = {
            "index_id": str(item.get("index_id") or ""),
            "path": relative,
            "sha256": str(item.get("sha256") or ""),
        }
        resolved_index_snapshots.append((resolved, raw))
        observed_ids.add(resolved["index_id"])
    resolved_indexes = [
        resolved for resolved, _raw in resolved_index_snapshots
    ]
    if observed_ids != _EVO_V2_COLD_START_INDEX_IDS or len(resolved_indexes) != 2:
        reasons.append("cold_start_search_index_scope")
    if reasons:
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: {'|'.join(reasons)}"
        )
    session_root_parent = _assert_private_root(
        state_root / EVO_V2_COLD_START_SEARCH_SESSIONS_ROOT,
        repo_root=worktree,
        workspace=workspace,
        create=True,
    )
    token = uuid.uuid4().hex
    session_id = f"session_{token}"
    runtime_instance_id = f"fforg-evo-v2-search-{token[:16]}"
    task_id = f"evo_v2_memory_search_{token[:24]}"
    session_root = _ensure_private_directory(session_root_parent, session_id)
    context_root = _ensure_private_directory(session_root, "context")
    _ensure_private_directory(session_root, "output")
    for item, raw in resolved_index_snapshots:
        _private_write_bytes(context_root, item["path"], raw)
    request = with_content_hash(
        {
            "contract_version": EVO_V2_COLD_START_SEARCH_REQUEST_VERSION,
            "artifact_identity": dict(artifact_identity),
            "executor_role_id": EVO_V2_COLD_START_SEARCH_ROLE_ID,
            "task_id": task_id,
            "retrieval_session_id": session_id,
            "runtime_instance_id": runtime_instance_id,
            "query": {
                "query_mode": "MECHANISM_FIRST_AFTER_BLIND_DERIVATION",
                "mechanism_fingerprint_sha256": stable_json_hash(
                    dict(mechanism_fingerprint)
                ),
                "query_sha256": _evo_v2_cold_start_query_hash(
                    mechanism_fingerprint
                ),
            },
            "mechanism_fingerprint": dict(mechanism_fingerprint),
            "checked_indexes": resolved_indexes,
            "blind_derivation_completed": True,
            "policy": {
                "must_inspect_every_bound_index_snapshot": True,
                "regime_shortcut_allowed": False,
                "historical_performance_ranking_allowed": False,
                "current_factor_proof_authority": False,
            },
        },
        hash_field="request_sha256",
    )
    request_reasons = _evo_v2_cold_search_request_reasons(
        request,
        artifact_identity=artifact_identity,
        mechanism_fingerprint=mechanism_fingerprint,
    )
    if request_reasons:
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: "
            f"{'|'.join(request_reasons)}"
        )
    _private_write_bytes(
        context_root,
        "identity/evo_v2_cold_start_search_request.json",
        _json_bytes(request),
    )
    invocation = ResearchOrgSessionInvocation(
        identity=dict(artifact_identity),
        role_id=EVO_V2_COLD_START_SEARCH_ROLE_ID,
        task_id=task_id,
        task_sha256=request["request_sha256"],
        attempt_id=f"attempt_evo_v2_search_{token[:20]}",
        attempt_number=1,
        session_id=session_id,
        runtime_instance_id=runtime_instance_id,
        worktree=worktree,
        workspace=workspace,
        private_attempt_root=session_root,
        context_root=context_root,
        private_output_path=session_root / "output" / "agent_result.json",
        cancel_request_path=session_root / "cancel_request.json",
        context_manifest_sha256=request["request_sha256"],
        required_skills=("factor-forge-researcher-memory",),
        timeout_seconds=timeout_seconds,
        runtime_id=f"runtime_evo_v2_search_{token[:20]}",
        plan_sha256=stable_json_hash(
            {
                "query_sha256": request["query"]["query_sha256"],
                "checked_indexes": resolved_indexes,
            }
        ),
        scheduler_epoch=1,
        dispatch_event_seq=1,
        idempotency_key=stable_json_hash(
            {"session_id": session_id, "request_sha256": request["request_sha256"]}
        ),
        adapter_challenge=uuid.uuid4().hex,
        dependency_admissions=(),
        parent_session_uid=None,
        host_job_id=host_job_id,
    )
    return invocation, request, session_root_parent


def build_evo_v2_cold_start_search_prompt(
    invocation: Any,
    *,
    container_context_root: Path,
    container_private_output_path: Path,
) -> str:
    """Return the closed-output prompt for the isolated zero-hit verifier.

    The generic research-organization prompt expects a normal task packet.  An
    EVO V2 retrieval session instead receives the purpose-built request staged
    by :func:`prepare_evo_v2_cold_start_search_session`, so it needs a distinct
    prompt.  The session is deliberately allowed to attest only a true zero
    hit.  If it finds an admissible source it must BLOCK and leave transfer
    authoring to a later, separately reviewed stage.
    """

    from factor_factory.research_org.runtime import (
        PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
        RESEARCH_ORG_CONTAINER_CONTEXT_ROOT,
        RESEARCH_ORG_CONTAINER_PRIVATE_OUTPUT_PATH,
    )
    if (
        container_context_root != RESEARCH_ORG_CONTAINER_CONTEXT_ROOT
        or container_private_output_path
        != RESEARCH_ORG_CONTAINER_PRIVATE_OUTPUT_PATH
    ):
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: "
            "cold_start_search_container_paths"
        )

    try:
        request = strict_json_loads(
            read_workspace_bytes(
                invocation.context_root,
                "identity/evo_v2_cold_start_search_request.json",
                max_bytes=MAX_CONTRACT_JSON_BYTES,
            ),
            label="evo_v2_cold_start_search_request",
        )
    except (OSError, ResearchOrganizationError, ValueError, UnicodeError) as exc:
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: "
            "cold_start_search_request_readback"
        ) from exc
    mechanism_fingerprint = (
        request.get("mechanism_fingerprint")
        if isinstance(request, Mapping)
        and isinstance(request.get("mechanism_fingerprint"), Mapping)
        else {}
    )
    request_reasons = _evo_v2_cold_search_request_reasons(
        request,
        artifact_identity=invocation.identity,
        mechanism_fingerprint=mechanism_fingerprint,
    )
    request_reasons.extend(
        _evo_v2_cold_search_invocation_reasons(
            request=request,
            invocation=invocation,
        )
    )
    if request_reasons:
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: "
            f"{'|'.join(dict.fromkeys(request_reasons))}"
        )
    _assert_evo_v2_cold_search_index_readback(
        context_root=invocation.context_root,
        request=request,
    )
    zero_hit_output = {
        "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
        "status": "PASS",
        "public_research_record": {
            "contract_version": EVO_V2_COLD_START_SEARCH_AGENT_RECORD_VERSION,
            "artifact_identity": request["artifact_identity"],
            "executor_role_id": EVO_V2_COLD_START_SEARCH_ROLE_ID,
            "query_sha256": request["query"]["query_sha256"],
            "checked_indexes": request["checked_indexes"],
            "admissible_hits": [],
            "admissible_hit_count": 0,
            "memory_state": "COLD_START_NO_ADMISSIBLE_MEMORY",
        },
    }
    zero_hit_output_json = json.dumps(
        zero_hit_output,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    container_request_path = (
        container_context_root
        / "identity/evo_v2_cold_start_search_request.json"
    )
    return f"""# Factor Forge EVO V2 mechanism-first memory search

You are a disposable Knowledge Librarian session. Read the frozen request at
`{container_request_path}` and every hash-bound index snapshot named by
`checked_indexes` under `{container_context_root}`.
Search by the mechanism fingerprint, not by historical performance or a market
regime label. Historical episodes are context only and cannot authorize the
current factor.

Write exactly one private-output JSON object to
`{container_private_output_path}`. For a true zero hit, the complete output must
match this exact JSON object (JSON whitespace and key order may differ; no field
may be added, removed, or renamed):

```json
{zero_hit_output_json}
```

The outer object must contain exactly `contract_version`, `status`, and
`public_research_record`. The record key is literally `public_research_record`;
`public_record` is a forbidden alias and will be rejected.

You may return PASS only when `admissible_hits=[]`, `admissible_hit_count=0`,
and `memory_state=COLD_START_NO_ADMISSIBLE_MEMORY`. Copy identity, query hash,
and checked indexes exactly from the request. If any admissible experience or
knowledge source exists, return status BLOCK instead of declaring a cold start;
do not create a transfer mapping, lesson, factor verdict, or canonical write.
Do not include private chain-of-thought or absolute Host paths.
"""


def complete_evo_v2_cold_start_search_session(
    *,
    invocation: Any,
    outcome: Any,
    state_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    """Admit a zero-hit result only after a real adapter-completed session."""

    from factor_factory.research_org.runtime_trust import load_runtime_trust_store
    from factor_factory.researcher_memory_review import (
        _evo_v2_adapter_completion_reasons,
        _read_private_review_output,
    )

    trust_store = load_runtime_trust_store(
        Path(state_root) / "research-org-trust",
        installation_id=installation_id,
    )
    if (
        outcome.returncode != 0
        or outcome.cancelled
        or not outcome.owned_termination_supported
        or outcome.session_id != invocation.session_id
        or outcome.runtime_instance_id != invocation.runtime_instance_id
    ):
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: search_runtime_outcome"
        )
    try:
        request = strict_json_loads(
            read_workspace_bytes(
                invocation.context_root,
                "identity/evo_v2_cold_start_search_request.json",
                max_bytes=MAX_CONTRACT_JSON_BYTES,
            ),
            label="evo_v2_cold_start_search_request",
        )
    except (OSError, ResearchOrganizationError, ValueError, UnicodeError) as exc:
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: "
            "cold_start_search_request_readback"
        ) from exc
    mechanism_fingerprint = (
        request.get("mechanism_fingerprint")
        if isinstance(request, Mapping)
        and isinstance(request.get("mechanism_fingerprint"), Mapping)
        else {}
    )
    request_reasons = _evo_v2_cold_search_request_reasons(
        request,
        artifact_identity=invocation.identity,
        mechanism_fingerprint=mechanism_fingerprint,
    )
    request_reasons.extend(
        _evo_v2_cold_search_invocation_reasons(
            request=request,
            invocation=invocation,
        )
    )
    if request_reasons:
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: "
            f"{'|'.join(request_reasons)}"
        )
    _assert_evo_v2_cold_search_index_readback(
        context_root=invocation.context_root,
        request=request,
    )
    output, output_bytes = _read_private_review_output(
        invocation.private_output_path
    )
    output_reasons, inventory = _evo_v2_cold_search_output_reasons(
        output,
        request=request,
    )
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    adapter_reasons = _evo_v2_adapter_completion_reasons(
        outcome.adapter_receipt,
        artifact_identity=invocation.identity,
        trust_store=trust_store,
        expected_role_id=EVO_V2_COLD_START_SEARCH_ROLE_ID,
        expected_task_sha256=invocation.task_sha256,
        expected_session_id=invocation.session_id,
        expected_runtime_instance_id=invocation.runtime_instance_id,
        expected_output_sha256=output_sha256,
        expected_output_size_bytes=len(output_bytes),
    )
    reasons = [*request_reasons, *output_reasons, *adapter_reasons]
    if reasons:
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: {'|'.join(reasons)}"
        )
    receipt = with_content_hash(
        {
            "contract_version": EVO_V2_COLD_START_SEARCH_RECEIPT_TYPE,
            "authority": "runtime_attested_zero_hit_search_host_admission_required",
            "artifact_identity": dict(invocation.identity),
            "query": dict(request["query"]),
            "inventory": inventory,
            "retrieval_runtime": {
                "adapter_completion_receipt": dict(outcome.adapter_receipt),
                "search_request": dict(request),
                "search_output": dict(output),
                "search_output_bytes_b64": base64.b64encode(
                    output_bytes
                ).decode("ascii"),
                "search_output_sha256": output_sha256,
                "model_execution": {
                    "provider": outcome.provider,
                    "model": outcome.model,
                    "transport": outcome.transport,
                    "isolation_class": outcome.isolation_class,
                    "owned_termination_supported": (
                        outcome.owned_termination_supported
                    ),
                },
            },
            "authority_guard": {
                "blind_derivation_completed": True,
                "regime_shortcut_allowed": False,
                "current_factor_proof_authority": False,
                "host_admission_required": True,
            },
        },
        hash_field="receipt_sha256",
    )
    reasons = validate_evo_v2_cold_start_search_receipt(
        receipt,
        artifact_identity=invocation.identity,
        mechanism_fingerprint=request["mechanism_fingerprint"],
        trust_store=trust_store,
    )
    if reasons:
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: {'|'.join(reasons)}"
        )
    return receipt


def _evo_v2_query_terms(value: Any) -> set[str]:
    if isinstance(value, str):
        return tokenize(value) | semantic_query_terms(value)
    if isinstance(value, Mapping):
        output: set[str] = set()
        for item in value.values():
            output.update(_evo_v2_query_terms(item))
        return output
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        output = set()
        for item in value:
            output.update(_evo_v2_query_terms(item))
        return output
    return set()


def _evo_v2_mechanism_score(
    source: Mapping[str, Any],
    target: Mapping[str, Any],
) -> tuple[int, list[str], bool]:
    score = 0
    dimensions: list[str] = []
    mechanism_anchor = False
    for field, weight in (
        ("payer_or_constraint", 5),
        ("estimand_id", 5),
        ("economic_claim", 4),
        ("broken_invariant_or_boundary", 3),
        ("observation_mapping", 2),
    ):
        source_text = " ".join(str(source.get(field) or "").casefold().split())
        target_text = " ".join(str(target.get(field) or "").casefold().split())
        overlap = _evo_v2_query_terms(source_text) & _evo_v2_query_terms(target_text)
        if source_text and source_text == target_text:
            score += weight
            dimensions.append(f"exact_{field}")
            if field in {"payer_or_constraint", "estimand_id"}:
                mechanism_anchor = True
        elif overlap:
            score += min(weight - 1, len(overlap))
            dimensions.append(f"overlap_{field}")
            if field in {"payer_or_constraint", "estimand_id"}:
                mechanism_anchor = True
    source_math = _evo_v2_query_terms(source.get("mathematical_object"))
    target_math = _evo_v2_query_terms(target.get("mathematical_object"))
    same_math = bool(source_math & target_math)
    if same_math:
        score += 3
        dimensions.append("mathematical_object")
    if not mechanism_anchor:
        return 0, [], same_math
    return score, sorted(set(dimensions)), same_math


def _evo_v2_overlap_score(left: Any, right: Any) -> tuple[int, list[str]]:
    overlap = sorted(_evo_v2_query_terms(left) & _evo_v2_query_terms(right))
    return min(6, len(overlap)), overlap


def retrieve_evo_v2_memory_projection(
    *,
    admissions: Sequence[Mapping[str, Any]],
    historical_episode_candidates: Sequence[Mapping[str, Any]] = (),
    target_mechanism_fingerprint: Mapping[str, Any],
    blind_derivation_completed: bool,
    trust_store: Any,
    source_workspace: Path | None = None,
    top_k_per_lane: int = 3,
) -> dict[str, Any]:
    """Project core EVO experiences into mechanism-first retrieval lanes.

    This is a non-canonical routing projection.  It cannot promote memory or
    validate a transfer; the selected experiences still have to enter the
    authoritative ``factorforge_evo_experience_transfer_bundle_v2`` contract.
    Market-state and event text is intentionally absent from every score.
    """

    from factor_factory.evo_v2 import EXPERIENCE_TRANSFER_BUNDLE_VERSION
    from factor_factory.evo_memory_runtime import (
        validate_terminal_historical_episode_candidate,
    )
    from factor_factory.researcher_memory import validate_evo_v2_memory_admission

    if (
        not isinstance(target_mechanism_fingerprint, Mapping)
        or set(target_mechanism_fingerprint) != _EVO_V2_FINGERPRINT_FIELDS
        or any(
            not isinstance(target_mechanism_fingerprint.get(field), str)
            or not str(target_mechanism_fingerprint.get(field)).strip()
            for field in _EVO_V2_FINGERPRINT_FIELDS
        )
    ):
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: target_fingerprint"
        )
    if blind_derivation_completed is not True:
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: blind_derivation_required"
        )
    if (
        type(top_k_per_lane) is not int
        or top_k_per_lane < 1
        or top_k_per_lane > 20
    ):
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: top_k_per_lane"
        )
    if not isinstance(admissions, Sequence) or isinstance(admissions, (str, bytes)):
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: admissions"
        )
    if not isinstance(historical_episode_candidates, Sequence) or isinstance(
        historical_episode_candidates,
        (str, bytes),
    ):
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: historical_episode_candidates"
        )
    resolved_source_workspace = (
        Path(source_workspace).expanduser().resolve(strict=True)
        if source_workspace is not None
        else None
    )
    lanes: dict[str, list[dict[str, Any]]] = {
        lane: [] for lane in _EVO_V2_RETRIEVAL_LANES
    }
    observed_admissions: set[str] = set()
    for admission_index, admission in enumerate(admissions):
        reasons = validate_evo_v2_memory_admission(
            admission,
            trust_store=trust_store,
            workspace=resolved_source_workspace,
            verify_refs=resolved_source_workspace is not None,
        )
        if reasons:
            raise KnowledgeRetrievalError(
                f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: "
                f"admission_{admission_index}:{'|'.join(reasons)}"
            )
        admission_id = str(admission["admission_id"])
        if admission_id in observed_admissions:
            raise KnowledgeRetrievalError(
                f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: duplicate_admission"
            )
        observed_admissions.add(admission_id)
        transfer_bundle = admission["core_payloads"]["experience_transfer_bundle"]
        if transfer_bundle.get("contract_version") != EXPERIENCE_TRANSFER_BUNDLE_VERSION:
            raise KnowledgeRetrievalError(
                f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: core_contract_drift"
            )
        source_fingerprint = transfer_bundle["mechanism_fingerprint"]
        mechanism_score, mechanism_dimensions, same_math = _evo_v2_mechanism_score(
            source_fingerprint,
            target_mechanism_fingerprint,
        )
        if mechanism_score <= 0:
            continue
        target_failure = target_mechanism_fingerprint["failure_signature"]
        for experience in transfer_bundle.get("experiences") or []:
            layer = str(experience["layer"])
            lesson = experience["lesson"]
            base = {
                "admission_id": admission_id,
                "experience_id": experience["experience_id"],
                "layer": layer,
                "source_factor_id": experience["source_factor_id"],
                "source_report_id": experience["source_report_id"],
                "source_outcome": experience["source_outcome"],
                "source_ref": dict(experience["source_ref"]),
                "host_admission_ref": dict(experience["host_admission_ref"]),
                "review_authority": dict(experience["review_authority"]),
                "core_experience": dict(experience),
                "mechanism_score": mechanism_score,
                "mechanism_match_dimensions": mechanism_dimensions,
                "performance_score_used_for_ranking": False,
                "regime_match_required": False,
                "current_factor_proof_authority": False,
                "authoritative_next_contract": EXPERIENCE_TRANSFER_BUNDLE_VERSION,
            }

            def append_hit(
                lane: str,
                *,
                diagnostic_score: int = 0,
                diagnostic_terms: Sequence[str] = (),
            ) -> None:
                lanes[lane].append(
                    {
                        **base,
                        "lane": lane,
                        "diagnostic_score": diagnostic_score,
                        "diagnostic_match_terms": list(diagnostic_terms),
                    }
                )

            if layer == "structural_lesson":
                append_hit(
                    "structural_isomorph" if same_math else "cross_math_analogy"
                )
                counter_score, counter_terms = _evo_v2_overlap_score(
                    [lesson.get("falsifier"), lesson.get("counterexample")],
                    [
                        target_mechanism_fingerprint["economic_claim"],
                        target_failure,
                    ],
                )
                if counter_score:
                    append_hit(
                        "direct_counterexample",
                        diagnostic_score=counter_score,
                        diagnostic_terms=counter_terms,
                    )
            elif layer == "conditional_realization":
                miss_score, miss_terms = _evo_v2_overlap_score(
                    [
                        lesson.get("causal_condition"),
                        lesson.get("expected_interaction_signature"),
                        lesson.get("condition_falsifier"),
                    ],
                    target_failure,
                )
                if miss_score:
                    append_hit(
                        "near_miss_failure",
                        diagnostic_score=miss_score,
                        diagnostic_terms=miss_terms,
                    )
                else:
                    append_hit("near_miss_failure")
            else:
                # event_timeline/state_variables/causal_role are retained in
                # core_experience but never read by the scoring functions.
                append_hit("historical_episode_context")

    observed_episode_candidates: set[str] = set()
    for episode_index, candidate in enumerate(historical_episode_candidates):
        reasons = validate_terminal_historical_episode_candidate(
            candidate,
            trust_store=trust_store,
        )
        if reasons:
            raise KnowledgeRetrievalError(
                f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: "
                f"historical_episode_{episode_index}:{'|'.join(reasons)}"
            )
        candidate_id = str(candidate["candidate_id"])
        if candidate_id in observed_episode_candidates:
            raise KnowledgeRetrievalError(
                f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: "
                "duplicate_historical_episode_candidate"
            )
        observed_episode_candidates.add(candidate_id)
        source_fingerprint = candidate["facts"]["mechanism_fingerprint"]
        mechanism_score, mechanism_dimensions, _same_math = (
            _evo_v2_mechanism_score(
                source_fingerprint,
                target_mechanism_fingerprint,
            )
        )
        if mechanism_score <= 0:
            continue
        terminal = candidate["facts"]["terminal_outcome"]
        lanes["historical_episode_context"].append(
            {
                "admission_id": f"episode_candidate:{candidate_id}",
                "experience_id": candidate_id,
                "layer": "historical_episode",
                "source_factor_id": candidate["identity"]["factor_id"],
                "source_report_id": candidate["identity"]["report_id"],
                "source_outcome": terminal["factor_verdict"],
                "source_ref": {
                    "path": candidate["source_refs"]["outcome_event"]["path"],
                    "sha256": candidate["source_refs"]["outcome_event"][
                        "event_sha256"
                    ],
                },
                "host_admission_ref": dict(
                    candidate["source_refs"]["host_attestation"]
                ),
                "review_authority": {
                    "required": False,
                    "status": "HOST_SIGNED_EPISODE_NO_STRUCTURAL_AUTHORITY",
                    "independent_session": False,
                    "reviewer_receipt_ref": None,
                },
                "core_experience": None,
                "historical_episode_candidate": dict(candidate),
                "candidate_only": True,
                "mechanism_score": mechanism_score,
                "mechanism_match_dimensions": mechanism_dimensions,
                "performance_score_used_for_ranking": False,
                "regime_match_required": False,
                "current_factor_proof_authority": False,
                "authoritative_next_contract": EXPERIENCE_TRANSFER_BUNDLE_VERSION,
                "lane": "historical_episode_context",
                "diagnostic_score": 0,
                "diagnostic_match_terms": [],
            }
        )

    for lane in _EVO_V2_RETRIEVAL_LANES:
        lanes[lane].sort(
            key=lambda hit: (
                -int(hit["mechanism_score"]),
                -int(hit["diagnostic_score"]),
                str(hit["experience_id"]),
                str(hit["admission_id"]),
            )
        )
        lanes[lane] = lanes[lane][:top_k_per_lane]
    projection = with_content_hash(
        {
            "contract_version": EVO_V2_MEMORY_RETRIEVAL_PROJECTION_VERSION,
            "authority": "noncanonical_retrieval_projection_only",
            "semantic_authority": "factor_factory.evo_v2",
            "target_mechanism_fingerprint": dict(target_mechanism_fingerprint),
            "routing_policy": {
                "query_mode": "MECHANISM_FIRST_AFTER_BLIND_DERIVATION",
                "primary_retrieval_key": "mechanism_fingerprint",
                "retrieval_lanes": list(_EVO_V2_RETRIEVAL_LANES),
                "market_regime_role": (
                    "historical_context_or_preregistered_boundary_only"
                ),
                "regime_shortcut_allowed": False,
                "historical_score_used_for_ranking": False,
                "current_factor_proof_authority": False,
            },
            "lanes": lanes,
            "retrieved_experience_count": len(
                {
                    (hit["admission_id"], hit["experience_id"])
                    for lane_hits in lanes.values()
                    for hit in lane_hits
                }
            ),
        },
        hash_field="projection_sha256",
    )
    expected_projection_sha = stable_json_hash(
        {
            key: value
            for key, value in projection.items()
            if key != "projection_sha256"
        }
    )
    if projection["projection_sha256"] != expected_projection_sha:
        raise KnowledgeRetrievalError(
            f"{BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID}: projection_hash"
        )
    return projection
