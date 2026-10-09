from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


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


def _hosted_memory():
    """Load the optional hosted component only for an explicit hosted request."""
    try:
        from factor_factory import evo_memory_retrieval
    except ImportError as exc:
        if getattr(exc, "name", None) in {"factor_factory.evo_memory_retrieval", "factor_factory"}:
            raise ImportError("Hosted memory retrieval requires the optional hosted source distribution") from exc
        raise
    return evo_memory_retrieval


def validate_evo_v2_cold_start_search_receipt(
    receipt: Any,
    *,
    artifact_identity: Mapping[str, Any],
    mechanism_fingerprint: Mapping[str, Any],
    trust_store: Any,
) -> list[str]:
    return _hosted_memory().validate_evo_v2_cold_start_search_receipt(
        receipt, artifact_identity=artifact_identity,
        mechanism_fingerprint=mechanism_fingerprint, trust_store=trust_store,
    )


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
    return _hosted_memory().prepare_evo_v2_cold_start_search_session(
        workspace=workspace, worktree=worktree, state_root=state_root,
        installation_id=installation_id, host_job_id=host_job_id,
        artifact_identity=artifact_identity, mechanism_fingerprint=mechanism_fingerprint,
        checked_indexes=checked_indexes, timeout_seconds=timeout_seconds,
    )


def build_evo_v2_cold_start_search_prompt(
    invocation: Any,
    *,
    container_context_root: Path,
    container_private_output_path: Path,
) -> str:
    return _hosted_memory().build_evo_v2_cold_start_search_prompt(
        invocation, container_context_root=container_context_root,
        container_private_output_path=container_private_output_path,
    )


def complete_evo_v2_cold_start_search_session(
    *,
    invocation: Any,
    outcome: Any,
    state_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    return _hosted_memory().complete_evo_v2_cold_start_search_session(
        invocation=invocation, outcome=outcome, state_root=state_root,
        installation_id=installation_id,
    )


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
    return _hosted_memory().retrieve_evo_v2_memory_projection(
        admissions=admissions, historical_episode_candidates=historical_episode_candidates,
        target_mechanism_fingerprint=target_mechanism_fingerprint,
        blind_derivation_completed=blind_derivation_completed, trust_store=trust_store,
        source_workspace=source_workspace, top_k_per_lane=top_k_per_lane,
    )
