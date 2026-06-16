from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


KNOWLEDGE_REFERENCE_CONTRACT_VERSION = "factorforge_knowledge_reference_contract_v1"

BLOCK_KNOWLEDGE_RETRIEVAL_PROVENANCE_MISSING = "BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_PROVENANCE_MISSING"
BLOCK_KNOWLEDGE_RETRIEVAL_INDEX_MISSING = "BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_INDEX_MISSING"
BLOCK_KNOWLEDGE_RETRIEVAL_REQUIRED = "BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_REQUIRED"
BLOCK_REVISION_KNOWLEDGE_CONTEXT_MISSING = "BLOCK_FACTORFORGE_REVISION_KNOWLEDGE_CONTEXT_MISSING"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


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
    paths = []
    if knowledge_root:
        paths.append(Path(knowledge_root).expanduser() / "retrieval" / "factorforge_retrieval_index.jsonl")
    paths.extend(
        [
            Path(repo_root).expanduser() / "knowledge" / "retrieval" / "factorforge_retrieval_index.jsonl",
            Path(repo_root).expanduser() / "factorforge" / "knowledge" / "retrieval" / "factorforge_retrieval_index.jsonl",
        ]
    )
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            deduped.append(path)
            seen.add(key)
    return deduped


def build_knowledge_reference_contract(
    *,
    repo_root: Path,
    query_text: str,
    producer: str,
    knowledge_root: Path | None = None,
    top_k: int = 3,
    retrieval_required: bool = False,
) -> dict[str, Any]:
    q_tokens = tokens(query_text)
    index_paths = default_retrieval_index_paths(repo_root, knowledge_root)
    candidates: list[tuple[float, dict[str, Any], str]] = []
    indexes_available = []
    for path in index_paths:
        if not path.exists():
            continue
        indexes_available.append(str(path))
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except Exception:
                continue
            text = stringify(doc.get("text") or doc)
            overlap = q_tokens & tokens(text)
            if not overlap:
                continue
            label = " / ".join(str(x) for x in [doc.get("factor_id"), doc.get("decision")] if x)
            lesson = (label + ": " + text[:300]).strip(": ")
            candidates.append((float(len(overlap)), doc, lesson))
    candidates.sort(key=lambda item: item[0], reverse=True)
    lessons: list[str] = []
    case_ids: list[str] = []
    seen_lessons: set[str] = set()
    for _score, doc, lesson in candidates:
        if lesson and lesson not in seen_lessons:
            lessons.append(lesson)
            seen_lessons.add(lesson)
            case_ids.append(str(doc.get("id") or doc.get("report_id") or doc.get("factor_id") or "unknown"))
        if len(lessons) >= top_k:
            break
    fallback_reason = None
    if not lessons:
        fallback_reason = "knowledge_retrieval_cold_start_no_similar_case"
        lessons.append("No similar prior case was retrieved; treat this as a cold-start prior and write back lessons after Step6.")
    return {
        "contract_version": KNOWLEDGE_REFERENCE_CONTRACT_VERSION,
        "producer": producer,
        "created_at_utc": utc_now(),
        "retrieval_required": bool(retrieval_required),
        "retrieval_status": "retrieved" if case_ids else "cold_start",
        "query_hash": stable_hash(query_text),
        "query_terms": sorted(q_tokens)[:40],
        "index_paths_checked": [str(path) for path in index_paths],
        "indexes_available": indexes_available,
        "hit_count": len(case_ids),
        "retrieved_case_ids": case_ids,
        "similar_case_lessons_imported": lessons,
        "fallback_reason": fallback_reason,
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
    if required and not contract.get("indexes_available"):
        failures.append(f"{BLOCK_KNOWLEDGE_RETRIEVAL_INDEX_MISSING}: indexes_available")
    if required and int(contract.get("hit_count") or 0) <= 0:
        failures.append(f"{BLOCK_KNOWLEDGE_RETRIEVAL_REQUIRED}: hit_count")
    if not contract.get("query_hash"):
        failures.append(f"{BLOCK_KNOWLEDGE_RETRIEVAL_PROVENANCE_MISSING}: query_hash")
    if "hit_count" not in contract:
        failures.append(f"{BLOCK_KNOWLEDGE_RETRIEVAL_PROVENANCE_MISSING}: hit_count")
    return failures
