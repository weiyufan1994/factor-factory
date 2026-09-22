from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


KNOWLEDGE_REFERENCE_CONTRACT_VERSION = "factorforge_knowledge_reference_contract_v1"

BLOCK_KNOWLEDGE_RETRIEVAL_PROVENANCE_MISSING = "BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_PROVENANCE_MISSING"
BLOCK_KNOWLEDGE_RETRIEVAL_INDEX_MISSING = "BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_INDEX_MISSING"
BLOCK_KNOWLEDGE_RETRIEVAL_REQUIRED = "BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_REQUIRED"
BLOCK_REVISION_KNOWLEDGE_CONTEXT_MISSING = "BLOCK_FACTORFORGE_REVISION_KNOWLEDGE_CONTEXT_MISSING"
BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE = "BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_UNAVAILABLE"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def optional_semantic_retrieval(query: str, index_path: Path, encoder: Any, *, top_k: int = 10, allowed_ids: set[str] | None = None) -> dict[str, Any]:
    """Opt-in dense candidate lane; unavailable/stale indexes remain visible."""
    from factor_factory.semantic_knowledge_retrieval import retrieve_semantic
    return retrieve_semantic(query, index_path, encoder, top_k=top_k, allowed_ids=allowed_ids)


def tokens(text: str) -> set[str]:
    return {
        item.lower()
        for item in re.split(r"[^A-Za-z0-9_\u4e00-\u9fff]+", str(text or ""))
        if item
    }


def stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def default_retrieval_index_paths(repo_root: Path, knowledge_root: Path | None = None) -> list[Path]:
    # An explicit root is an isolation boundary.  In particular, do not make a
    # temporary/research root accidentally consume another checkout's index.
    if knowledge_root is not None:
        paths = [Path(knowledge_root).expanduser() / "retrieval" / "factorforge_retrieval_index.jsonl"]
    else:
        paths = [
            Path(repo_root).expanduser() / "knowledge" / "retrieval" / "factorforge_retrieval_index.jsonl",
            Path(repo_root).expanduser() / "factorforge" / "knowledge" / "retrieval" / "factorforge_retrieval_index.jsonl",
        ]
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            deduped.append(path)
            seen.add(key)
    return deduped


def resolve_runtime_retrieval_index(
    repo_root: Path, *, environ: Mapping[str, str] | None = None
) -> Path:
    """Choose an existing local/exported experience index, never build one.

    Ultimate already passes workspace and shared roots to its Step consumers.
    Public graph lookup is separate, so a workspace index does not hide the
    curated graph. An explicit override (even missing/broken) never falls back.
    This resolver is not used by the source-only/A0 graph adapter.
    """
    env = os.environ if environ is None else environ
    override = env.get("FACTORFORGE_RETRIEVAL_INDEX")
    if override:
        return Path(override).expanduser()
    roots = [
        env.get("FACTORFORGE_FACTOR_WORKSPACE") or env.get("FACTORFORGE_ROOT"),
        env.get("FACTORFORGE_SHARED_FACTORFORGE_ROOT"),
        str(repo_root),
    ]
    paths = list(dict.fromkeys(
        Path(root).expanduser() / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
        for root in roots if root
    ))
    # A malformed index or dangling link must be reported by the reader; do not
    # silently substitute a different corpus because the chosen one is broken.
    return next((path for path in paths if path.exists() or path.is_symlink()), paths[0])


def _graph_paths(repo_root: Path, knowledge_root: Path | None) -> tuple[Path, Path, Path]:
    """Resolve graph files without crossing an explicit knowledge-root boundary."""
    if knowledge_root is None:
        graph_root = Path(repo_root).expanduser() / "knowledge" / "因子工厂" / "graph"
        taxonomy = Path(repo_root).expanduser() / "knowledge" / "因子工厂" / "taxonomy" / "factor_taxonomy_v1.json"
    else:
        root = Path(knowledge_root).expanduser()
        vault = root / "因子工厂" if (root / "因子工厂").is_dir() else root
        graph_root = vault / "graph" if (vault / "graph").is_dir() else vault
        taxonomy = vault / "taxonomy" / "factor_taxonomy_v1.json"
    return (
        graph_root / "factor_knowledge_nodes.jsonl",
        graph_root / "factor_knowledge_edges.jsonl",
        taxonomy,
    )


def _graph_reference_context(
    *, repo_root: Path, knowledge_root: Path | None, query_text: str, top_k: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Path], str | None]:
    """Read the existing public graph and project it into advisory references."""
    node_path, edge_path, taxonomy_path = _graph_paths(repo_root, knowledge_root)
    paths = [node_path, edge_path, taxonomy_path]
    present = [path.is_file() for path in paths]
    if not any(present):
        return [], [], paths, None
    if not all(present):
        return [], [], paths, f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: partial_graph_index"
    if not str(query_text or "").strip():
        return [], [], paths, None
    try:
        from factor_factory.knowledge_context import retrieve_factor_knowledge_context

        # The graph retriever owns semantic scoring; feed it taxonomy aliases so
        # Chinese mechanism queries (e.g. 占用测度/价量) use the same path as
        # their canonical English/tag forms.
        graph_query = str(query_text or "")
        taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
        aliases = taxonomy.get("aliases") or {}
        for alias, mapped in aliases.items():
            if str(alias).casefold() in graph_query.casefold():
                graph_query += " " + " ".join(str(item) for item in mapped)

        context = retrieve_factor_knowledge_context(
            text=graph_query,
            top_k=max(1, int(top_k)),
            node_index=node_path,
            edge_index=edge_path,
            taxonomy=taxonomy_path,
            repo_root=repo_root,
            graph_root=node_path.parent,
        )
        nodes = context.get("nodes") or []
        relations = context.get("related_edges") or []
        # This reader is post-source only. The A0 graph adapter never calls it.
        from factor_factory.semantic_knowledge_retrieval import graph_documents, retrieve_configured
        config = (Path(knowledge_root) if knowledge_root is not None
                  else Path(repo_root) / "knowledge") / "retrieval/semantic_config.json"
        if config.is_file() and os.environ.get("FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL") != "1":
            docs = graph_documents(node_path, repo_root)
            dense = retrieve_configured(query_text, docs, config, top_k=max(top_k, 10))
            by_id = {doc["id"]: doc["node"] for doc in docs}
            ranked = {node["id"]: 1 / (60 + rank) for rank, node in enumerate(nodes, 1)}
            for rank, hit in enumerate(dense.get("hits", []), 1):
                ranked[hit["id"]] = ranked.get(hit["id"], 0) + 1 / (60 + rank)
            if dense["semantic_used"]:
                selected = sorted(ranked, key=lambda key: (-ranked[key], key))[:top_k]
                nodes = [dict(by_id[key], retrieval_similarity_is_evidence=False) for key in selected]
                from factor_factory.knowledge_context import load_jsonl
                relations = [edge for edge in load_jsonl(edge_path)
                             if edge.get("source") in selected or edge.get("target") in selected]
        return nodes, relations, paths, None
    except Exception as exc:
        return [], [], paths, f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: {type(exc).__name__}"


def project_knowledge_case(doc: dict[str, Any]) -> dict[str, Any]:
    """Keep explicit experience fields, never a raw memo or inferred diagnosis."""
    projection = doc.get("advisory_projection")
    metadata = doc.get("metadata")
    projection = {} if projection is None else projection
    metadata = {} if metadata is None else metadata
    if not isinstance(projection, dict) or not isinstance(metadata, dict):
        raise ValueError("invalid experience projection")
    identity = {
        field: doc.get(field) or (projection.get("identity") or {}).get(field) or {}
        for field in ("artifact_identity", "source_identity", "source_case_identity", "evidence_identity")
    }
    mechanism = {
        field: doc.get(field) or projection.get(field)
        for field in ("factor_family", "monetization_model", "bias_type", "return_source_hypothesis", "objective_constraint_dependency", "constraint_sources")
    }
    return {
        "id": doc.get("id") or doc.get("report_id") or doc.get("factor_id"),
        "factor_id": doc.get("factor_id"), "report_id": doc.get("report_id"),
        "decision": doc.get("decision"), "doc_type": doc.get("doc_type"),
        "research_variant": doc.get("research_variant") or projection.get("research_variant"),
        "paper_replication_status": doc.get("paper_replication_status") or projection.get("paper_replication_status"),
        "source_path": doc.get("source_path"), "identity": identity,
        "workspace_export_source": projection.get("workspace_export_source") or {
            "record_relative_ref": doc.get("source_record_relative_ref"),
            "record_sha256": doc.get("source_record_sha256"),
        },
        "mechanism": mechanism,
        "success_patterns": metadata.get("success_patterns") or [],
        "failure_patterns": metadata.get("failure_patterns") or [],
        "failure_conditions": doc.get("expected_failure_regimes") or projection.get("expected_failure_regimes") or [],
        "reuse_constraints": doc.get("reuse_constraints") or projection.get("reuse_constraints") or [],
        # Preserve explicit Step6 structural lessons.  These are copied only;
        # retrieval never infers a mathematical object or an operator.
        "mathematical_object": doc.get("mathematical_object") or projection.get("mathematical_object"),
        "reusable_operator": doc.get("reusable_operator") or projection.get("reusable_operator"),
        "implementation_references": doc.get("implementation_references") or projection.get("implementation_references") or [],
        **{field: doc.get(field, projection.get(field)) for field in (
            "applicability_conditions", "regime_detection", "treatment_effect",
            "evidence_class", "validity_status", "invalidation_reason",
            "learning_and_innovation", "research_compatibility_profile",
            "next_research_tests_absence_reason",
            "lessons_status", "source_refs", "formal_step6_completed", "reported_research_recommendation")},
        "modification_hypotheses": [
            {"text": item, "status": "candidate_not_verified"}
            for item in metadata.get("modification_hypotheses") or []
        ],
        "search_text": doc.get("search_text") or doc.get("text"),
        "advisory_only": True, "not_same_factor_unless_identity_matches": True,
    }


def build_knowledge_reference_contract(
    *,
    repo_root: Path,
    query_text: str,
    producer: str,
    knowledge_root: Path | None = None,
    retrieval_index: Path | None = None,
    top_k: int = 3,
    retrieval_required: bool = False,
) -> dict[str, Any]:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("top_k must be a positive integer")
    q_tokens = tokens(query_text)
    effective_top_k = top_k
    index_paths = ([Path(retrieval_index).expanduser()] if retrieval_index is not None
                   else default_retrieval_index_paths(repo_root, knowledge_root))
    candidates: list[tuple[float, dict[str, Any], str]] = []
    semantic_state = {"semantic_available": False, "semantic_used": False, "fallback": "disabled_or_unconfigured"}
    visible_by_index: dict[Path, list[dict[str, Any]]] = {}
    indexes_available = []
    legacy_error: str | None = None
    legacy_case_ids: set[str] = set()
    graph_nodes, graph_relations, graph_paths, graph_error = _graph_reference_context(
        repo_root=repo_root,
        knowledge_root=knowledge_root,
        query_text=query_text,
        top_k=effective_top_k or 1,
    )
    graph_available = not graph_error and all(path.is_file() for path in graph_paths)
    if graph_available:
        indexes_available.extend(str(path) for path in graph_paths[:2])
    for path in index_paths:
        if not path.exists() and not path.is_symlink():
            continue
        if not path.is_file() or path.is_symlink():
            legacy_error = f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: unsafe_legacy_index:{path}"
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            legacy_error = f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: {type(exc).__name__}"
            continue
        indexes_available.append(str(path))
        for line_number, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except Exception:
                legacy_error = f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: malformed_legacy_json:{path}:{line_number}"
                continue
            if not isinstance(doc, dict):
                legacy_error = f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: legacy_record_not_object:{path}:{line_number}"
                continue
            if not (doc.get("id") or doc.get("report_id") or doc.get("factor_id")):
                legacy_error = f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: missing_legacy_id:{path}:{line_number}"
                continue
            identity = str(doc.get("id") or doc.get("report_id") or doc.get("factor_id") or "")
            if identity and identity in legacy_case_ids:
                legacy_error = f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: duplicate_legacy_id:{identity}"
                continue
            if identity:
                legacy_case_ids.add(identity)
            text = stringify(doc.get("search_text") or doc.get("text") or doc)
            # A new semantic projection must not gain weight from outcome/ID
            # tags. Older documents retain their historical text compatibility.
            searchable = {"text": text} if "search_text" in doc else dict(doc, text=text)
            try:
                from factor_factory.knowledge_context import score_text

                score, overlap_list = score_text(query_text, searchable)
                overlap = set(overlap_list)
                project_knowledge_case(doc)
            except (TypeError, ValueError, AttributeError) as exc:
                legacy_error = f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: invalid_legacy_projection:{type(exc).__name__}"
                continue
            visible_by_index.setdefault(path, []).append(doc)
            label = " / ".join(str(x) for x in [doc.get("factor_id"), doc.get("research_variant"), doc.get("paper_replication_status"), doc.get("decision")] if x)
            lesson = (label + ": " + text[:300]).strip(": ")
            candidates.append((float(score) if overlap else 0.0, doc, lesson))
    from factor_factory.semantic_knowledge_retrieval import retrieve_configured

    semantic_hits: list[dict[str, Any]] = []
    semantic_lanes = []
    for path, visible in visible_by_index.items():
        visible = [doc for doc in visible if doc.get("doc_type") != "research_episode"]
        state = retrieve_configured(query_text, visible, path.parent / "semantic_config.json",
                                    top_k=max(top_k, 10))
        semantic_lanes.append({"index_path": str(path), **state})
        semantic_hits.extend(state.get("hits", []))
    if semantic_lanes:
        semantic_state = {
            "semantic_available": any(lane["semantic_available"] for lane in semantic_lanes),
            "semantic_used": any(lane["semantic_used"] for lane in semantic_lanes),
            "fallback": next((lane["fallback"] for lane in semantic_lanes if lane["fallback"]), None),
            "lanes": [{k: v for k, v in lane.items() if k != "hits"} for lane in semantic_lanes],
        }
    # Reciprocal rank fusion keeps incomparable lexical/dense scales separate.
    # With semantic disabled the original lexical order remains unchanged.
    dense_rank = {str(hit["id"]): rank for rank, hit in enumerate(semantic_hits, 1)}
    lexical = sorted((item for item in candidates if item[0] > 0),
                     key=lambda item: (-item[0], str(item[1].get("id") or "")))
    lexical_rank = {str(item[1]["id"]): rank for rank, item in enumerate(lexical, 1)}
    if semantic_state["semantic_used"]:
        candidates = [
            ((1 / (60 + lexical_rank[doc["id"]]) if doc["id"] in lexical_rank else 0)
             + (1 / (60 + dense_rank[doc["id"]]) if doc["id"] in dense_rank else 0), doc, lesson)
            for score, doc, lesson in candidates
            if score > 0 or doc["id"] in dense_rank
        ]
    else:
        candidates = lexical
    candidates.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
    lessons: list[str] = []
    case_ids: list[str] = []
    seen_lessons: set[str] = set()
    selected_docs: list[dict[str, Any]] = []
    for _score, doc, lesson in candidates:
        if lesson and lesson not in seen_lessons:
            lessons.append(lesson)
            seen_lessons.add(lesson)
            case_ids.append(str(doc.get("id") or doc.get("report_id") or doc.get("factor_id") or "unknown"))
            selected_docs.append(doc)
        if len(lessons) >= effective_top_k:
            break
    retrieved_nodes = []
    for node in graph_nodes[:effective_top_k]:
        retrieved_nodes.append(
            {
                "id": node.get("id"),
                "title": node.get("title"),
                "node_type": node.get("node_type"),
                "summary": node.get("summary"),
                "research_status": node.get("research_status") or [],
                "evidence_classification": (node.get("evidence") or {}).get("classification"),
                "evidence_boundary": (node.get("evidence") or {}).get("boundary"),
                "mechanism": node.get("mechanism") or {},
                "reuse_guidance": node.get("reuse_guidance") or [],
                "source_paths": node.get("source_paths") or [],
                "source_node_path": node.get("source_node_path"),
                "advisory_only": True,
            }
        )
    # The public graph and workspace experience index are distinct advisory
    # lanes.  A weak lexical experience hit must not make graph relevance
    # disappear merely because the legacy lane is non-empty.  Keep each lane's
    # own ordering, make the graph's semantic ranking visible first, and bound
    # each lane by the caller's top_k.  IDs are the cross-lane deduplication
    # key; graph nodes win a collision because their source/provenance is
    # explicit in this public contract.
    merged_case_ids: set[str] = set()
    merged_cases: list[dict[str, Any]] = []
    merged_lessons: list[str] = []
    for node in retrieved_nodes:
        identity = str(node.get("id") or "unknown")
        if identity in merged_case_ids:
            continue
        merged_case_ids.add(identity)
        merged_cases.append(node)
        label = str(node.get("title") or identity)
        summary = str(node.get("summary") or "").strip()
        merged_lessons.append(f"{label}: {summary}" if summary else label)
    for doc, lesson in zip(selected_docs, lessons):
        identity = str(doc.get("id") or doc.get("report_id") or doc.get("factor_id") or "unknown")
        if identity in merged_case_ids:
            continue
        merged_case_ids.add(identity)
        merged_cases.append(project_knowledge_case(doc))
        if lesson:
            merged_lessons.append(lesson)
    case_ids = [str(case.get("id") or "unknown") for case in merged_cases]
    lessons = merged_lessons
    fallback_reason = legacy_error or graph_error
    if not merged_cases and graph_error:
        fallback_reason = graph_error
    elif not merged_cases and not legacy_error:
        fallback_reason = "knowledge_retrieval_cold_start_no_similar_case"
        lessons.append("No similar prior case was retrieved; treat this as a cold-start prior and write back lessons after Step6.")
    return {
        "contract_version": KNOWLEDGE_REFERENCE_CONTRACT_VERSION,
        "producer": producer,
        "created_at_utc": utc_now(),
        "retrieval_required": bool(retrieval_required),
        "retrieval_status": "unavailable" if (graph_error or legacy_error) else ("retrieved" if case_ids else "cold_start"),
        "query_hash": stable_hash(query_text),
        "query_terms": sorted(q_tokens)[:40],
        "index_paths_checked": [str(path) for path in index_paths],
        "indexes_available": indexes_available,
        "hit_count": len(case_ids),
        "retrieval_limits": {"top_k_per_lane": top_k, "maximum_merged_cases": 2 * top_k},
        "retrieved_case_ids": case_ids,
        "retrieved_cases": merged_cases,
        "similar_case_lessons_imported": lessons,
        "fallback_reason": fallback_reason,
        "graph_index_paths_checked": [str(path) for path in graph_paths],
        "graph_indexes_available": [str(path) for path in graph_paths if path.is_file()],
        "retrieved_knowledge_nodes": retrieved_nodes,
        "retrieved_knowledge_relations": graph_relations,
        "knowledge_advisory": {
            "advisory_only": True,
            "selection_authority": "current_model_identification_and_falsification",
            "applicability_boundaries": [
                str(guidance)
                for node in retrieved_nodes
                for guidance in (node.get("reuse_guidance") or [])
            ],
        },
        "semantic_retrieval": semantic_state,
    }


def build_legacy_knowledge_reference_contract(
    *,
    similar_case_lessons: list[Any],
    producer: str,
) -> dict[str, Any]:
    lessons = [str(item) for item in (similar_case_lessons or []) if str(item).strip()]
    return {
        "contract_version": KNOWLEDGE_REFERENCE_CONTRACT_VERSION,
        "producer": producer,
        "created_at_utc": utc_now(),
        "retrieval_required": False,
        "retrieval_status": "legacy_artifact_without_retrieval_provenance",
        "query_hash": "legacy_artifact_no_query_hash",
        "query_terms": [],
        "index_paths_checked": [],
        "indexes_available": [],
        "hit_count": 0,
        "retrieved_case_ids": [],
        "similar_case_lessons_imported": lessons,
        "fallback_reason": "legacy_artifact_missing_knowledge_reference_contract",
    }


def validate_knowledge_reference_contract(contract: dict[str, Any], *, retrieval_required: bool | None = None) -> list[str]:
    if not isinstance(contract, dict) or not contract:
        return [f"{BLOCK_KNOWLEDGE_RETRIEVAL_PROVENANCE_MISSING}: knowledge_reference_contract"]
    failures: list[str] = []
    if contract.get("contract_version") != KNOWLEDGE_REFERENCE_CONTRACT_VERSION:
        failures.append(f"{BLOCK_KNOWLEDGE_RETRIEVAL_PROVENANCE_MISSING}: contract_version")
    required = contract.get("retrieval_required") is True if retrieval_required is None else bool(retrieval_required)
    if required and contract.get("retrieval_status") == "unavailable":
        failures.append(f"{BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE}: retrieval_status")
    if required and not contract.get("indexes_available"):
        failures.append(f"{BLOCK_KNOWLEDGE_RETRIEVAL_INDEX_MISSING}: indexes_available")
    if required and int(contract.get("hit_count") or 0) <= 0:
        failures.append(f"{BLOCK_KNOWLEDGE_RETRIEVAL_REQUIRED}: hit_count")
    if not contract.get("query_hash"):
        failures.append(f"{BLOCK_KNOWLEDGE_RETRIEVAL_PROVENANCE_MISSING}: query_hash")
    if "hit_count" not in contract:
        failures.append(f"{BLOCK_KNOWLEDGE_RETRIEVAL_PROVENANCE_MISSING}: hit_count")
    return failures


def measurement_program_available_knowledge_node_ids_from_step2_summary(
    summary: Mapping[str, Any] | None,
) -> set[str]:
    """Project the already-frozen Step2 knowledge summary for program checks.

    This is deliberately a projection, not a retrieval/admission validator.
    A component cannot certify its own ``knowledge_node_ids`` and a bare
    top-level ``cited_node_ids`` list is not evidence.  The source is instead
    the author-carried knowledge context in a research-discipline container,
    plus explicitly carried retrieved-case records in that same container.
    Method references and retrieved case references are separate lanes.
    """
    root = summary if isinstance(summary, Mapping) else {}
    parents = [root]
    canonical = root.get("canonical_spec")
    if isinstance(canonical, Mapping):
        parents.append(canonical)
    frozen_containers = [
        parent.get(key)
        for parent in parents
        for key in ("research_discipline", "learning_and_innovation", "research_contract")
        if isinstance(parent.get(key), Mapping)
    ]

    available: set[str] = set()
    for container in frozen_containers:
        context = container.get("factor_knowledge_context")
        if isinstance(context, Mapping):
            for node in context.get("nodes") or []:
                if isinstance(node, Mapping) and str(node.get("id") or "").strip():
                    available.add(str(node["id"]).strip())

        # A frozen retrieval record is self-describing through its materialized
        # case entries.  Do not accept a cited list by itself here: the Step6
        # retrieval-proof validator remains responsible for stronger checks.
        contract = container.get("knowledge_reference_contract")
        if not isinstance(contract, Mapping):
            continue
        retrieved_ids = contract.get("retrieved_case_ids")
        retrieved_cases = contract.get("retrieved_cases")
        if not isinstance(retrieved_ids, list) or not isinstance(retrieved_cases, list):
            continue
        ids = [str(item).strip() for item in retrieved_ids if str(item).strip()]
        case_ids = [
            str(case.get("id") or "").strip()
            for case in retrieved_cases
            if isinstance(case, Mapping) and str(case.get("id") or "").strip()
        ]
        if (
            ids
            and len(ids) == len(retrieved_ids) == len(set(ids))
            and len(case_ids) == len(retrieved_cases) == len(set(case_ids))
            and set(ids) == set(case_ids)
        ):
            available.update(ids)
    return available
