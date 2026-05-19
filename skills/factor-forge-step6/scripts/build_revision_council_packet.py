#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path("/home/ubuntu/.openclaw/workspace")
FF = Path(os.getenv("FACTORFORGE_ROOT") or (LEGACY_WORKSPACE / "factorforge" if (LEGACY_WORKSPACE / "factorforge").exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.mechanism_math.classifier import build_mechanism_math_contract
from factor_factory.mechanism_math.formula_specific import (
    build_formula_specific_derivation,
    validate_mechanism_formula_consistency,
)
from factor_factory.mechanism_math.main_agent_memo import validate_main_agent_mechanism_memo
from factor_factory.mechanism_math.validator import validate_mechanism_math_contract

OBJ = FF / "objects"
TOKEN_MISSING = "BLOCK_REVISION_COUNCIL_PACKET_MISSING_INPUT"
BASELINE_VERSION = "factorforge_revision_council_forbidden_writeback_baseline_v1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(FF))
    except ValueError:
        return str(path)


def should_skip_digest_path(path: Path) -> bool:
    name = path.name
    return (
        name == "__pycache__"
        or name == ".DS_Store"
        or name.endswith(".lock")
        or name.endswith(".tmp")
        or name.endswith(".swp")
        or name.endswith(".swx")
        or name.startswith(".#")
        or name.startswith("~$")
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_digest(path: Path) -> str:
    entries: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*"), key=lambda p: p.relative_to(path).as_posix()):
        if any(should_skip_digest_path(part) for part in item.relative_to(path).parents):
            continue
        if should_skip_digest_path(item):
            continue
        if not item.is_file():
            continue
        stat = item.stat()
        entries.append(
            {
                "relative_path": item.relative_to(path).as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(item),
            }
        )
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def snapshot_path(path: Path, kind: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "path": relpath(path),
        "exists": path.exists(),
        "kind": kind,
        "mtime_ns": None,
    }
    if not path.exists():
        if kind == "file":
            snapshot["sha256"] = None
        else:
            snapshot["digest"] = None
        return snapshot
    stat = path.stat()
    snapshot["mtime_ns"] = stat.st_mtime_ns
    if kind == "file":
        snapshot["sha256"] = sha256_file(path) if path.is_file() else None
    else:
        snapshot["digest"] = directory_digest(path) if path.is_dir() else None
    return snapshot


def forbidden_writeback_baseline(report_id: str) -> dict[str, Any]:
    paths = {
        "handoff_to_step3b": snapshot_path(OBJ / "handoff" / f"handoff_to_step3b__{report_id}.json", "file"),
        "generated_code": snapshot_path(FF / "generated_code" / report_id, "directory"),
        "official_library": snapshot_path(OBJ / "factor_library_official" / f"factor_record__{report_id}.json", "file"),
        "data_clean": snapshot_path(FF / "data" / "clean", "directory"),
    }
    return {
        "contract_version": BASELINE_VERSION,
        "captured_at": utc_now(),
        "paths": paths,
    }


def nested(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(key)
    return cur if isinstance(cur, dict) else {}


def mechanism_math_for_packet(spec: dict[str, Any], case: dict[str, Any], handoff: dict[str, Any], memo: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    canonical = spec.get("canonical_spec") if isinstance(spec.get("canonical_spec"), dict) else {}
    for candidate in [
        nested(memo, "mechanism_analysis").get("mechanism_math_contract"),
        spec.get("mechanism_math_contract"),
        canonical.get("mechanism_math_contract"),
        case.get("mechanism_math_contract"),
        handoff.get("mechanism_math_contract"),
    ]:
        if isinstance(candidate, dict) and candidate:
            current_failures = validate_mechanism_math_contract(candidate)
            if not current_failures:
                return candidate
            failures.extend(current_failures)
    rebuilt = build_mechanism_math_contract(spec or canonical or {})
    if failures:
        evidence = rebuilt.get("classification_evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        evidence["rebuilt_from_stale_or_invalid_upstream_contract"] = True
        evidence["upstream_contract_failure_codes"] = sorted({str(item.get("code")) for item in failures if item.get("code")})
        rebuilt["classification_evidence"] = evidence
    return rebuilt


def factor_tokens(report_id: str, spec: dict[str, Any], iteration: dict[str, Any]) -> list[str]:
    raw = [
        report_id,
        str(spec.get("factor_id") or ""),
        str(iteration.get("factor_id") or ""),
        str((spec.get("canonical_spec") or {}).get("factor_id") or "") if isinstance(spec.get("canonical_spec"), dict) else "",
    ]
    tokens: list[str] = []
    for item in raw:
        item = item.strip()
        if not item:
            continue
        tokens.append(item)
        prefix = item.split("_")[0]
        if prefix and prefix != item:
            tokens.append(prefix)
    return list(dict.fromkeys(tokens))


def read_text_limited(path: Path, limit: int = 50000) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[TRUNCATED_BY_FACTOR_FORGE_SUPPLEMENTAL_CONTEXT_LIMIT]\n"


def supplemental_research_context(report_id: str, spec: dict[str, Any], iteration: dict[str, Any]) -> dict[str, Any]:
    tokens = factor_tokens(report_id, spec, iteration)
    items: list[dict[str, Any]] = []
    seen: set[Path] = set()

    def add_file(path: Path, source: str) -> None:
        if not path.exists() or not path.is_file() or path in seen:
            return
        seen.add(path)
        items.append(
            {
                "source": source,
                "path": str(path),
                "relative_path": relpath(path),
                "sha256": sha256_file(path),
                "content": read_text_limited(path),
            }
        )

    supplemental_dir = OBJ / "research_iteration_master" / "revision_council" / report_id / "supplemental_context"
    if supplemental_dir.exists():
        for path in sorted(supplemental_dir.glob("*.md")):
            add_file(path, "revision_council_supplemental_context")

    kb_dir = FF / "knowledge" / "因子工厂" / "知识库"
    if kb_dir.exists():
        for path in sorted(kb_dir.glob("*.md")):
            name = path.name.lower()
            token_hit = any(token and token.lower() in name for token in tokens)
            mechanism_hit = any(marker in name for marker in ["mechanism", "机制", "math", "数学"])
            if token_hit and mechanism_hit:
                add_file(path, "factorforge_knowledge_mechanism_context")

    return {
        "contract_version": "factorforge_revision_council_supplemental_context_v1",
        "lookup_tokens": tokens,
        "item_count": len(items),
        "items": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    rid = args.report_id

    paths = {
        "research_iteration_master": OBJ / "research_iteration_master" / f"research_iteration_master__{rid}.json",
        "factor_case_master": OBJ / "factor_case_master" / f"factor_case_master__{rid}.json",
        "factor_evaluation": OBJ / "validation" / f"factor_evaluation__{rid}.json",
        "factor_run_master": OBJ / "factor_run_master" / f"factor_run_master__{rid}.json",
        "handoff_to_step6": OBJ / "handoff" / f"handoff_to_step6__{rid}.json",
        "factor_spec_master": OBJ / "factor_spec_master" / f"factor_spec_master__{rid}.json",
        "main_agent_mechanism_memo": OBJ / "research_iteration_master" / f"main_agent_mechanism_memo__{rid}.json",
    }
    required = ["research_iteration_master", "factor_case_master", "factor_evaluation", "factor_run_master"]
    missing = [str(paths[name]) for name in required if not paths[name].exists()]
    if missing:
        print(TOKEN_MISSING + ": " + json.dumps({"missing": missing}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)

    iteration = load_json(paths["research_iteration_master"])
    case = load_json(paths["factor_case_master"])
    evaluation = load_json(paths["factor_evaluation"])
    run = load_json(paths["factor_run_master"])
    handoff = load_json(paths["handoff_to_step6"]) if paths["handoff_to_step6"].exists() else {}
    spec = load_json(paths["factor_spec_master"]) if paths["factor_spec_master"].exists() else {}
    if not paths["main_agent_mechanism_memo"].exists():
        print("BLOCK_MAIN_AGENT_MECHANISM_MEMO_MISSING: " + str(paths["main_agent_mechanism_memo"]), file=sys.stderr)
        raise SystemExit(1)
    main_agent_memo = load_json(paths["main_agent_mechanism_memo"])
    memo_failures = validate_main_agent_mechanism_memo(main_agent_memo, spec)
    if memo_failures:
        print("BLOCK_MAIN_AGENT_MECHANISM_MEMO_INVALID: " + json.dumps({"failures": memo_failures}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)

    memo = nested(iteration, "research_judgment", "research_memo")
    canonical = spec.get("canonical_spec") if isinstance(spec.get("canonical_spec"), dict) else {}
    metrics: dict[str, Any] = {}
    for item in evaluation.get("backend_summary") or []:
        if isinstance(item, dict) and isinstance(item.get("key_metrics"), dict):
            metrics.update(item["key_metrics"])

    brief_ref = iteration.get("loop_research_brief") or {}
    brief_json = {}
    if isinstance(brief_ref, dict) and brief_ref.get("json_path") and Path(brief_ref["json_path"]).exists():
        brief_json = load_json(Path(brief_ref["json_path"]))
    mechanism_analysis = nested(memo, "mechanism_analysis")
    formula_specific_derivation = mechanism_analysis.get("formula_specific_derivation") if isinstance(mechanism_analysis, dict) else None
    if not isinstance(formula_specific_derivation, dict) or not formula_specific_derivation:
        formula_specific_derivation = brief_json.get("formula_specific_derivation") if isinstance(brief_json.get("formula_specific_derivation"), dict) else {}
    if not formula_specific_derivation:
        formula_specific_derivation = build_formula_specific_derivation(spec or canonical or {}, mechanism_analysis if isinstance(mechanism_analysis, dict) else {}, metrics)
    mechanism_formula_consistency = mechanism_analysis.get("mechanism_formula_consistency") if isinstance(mechanism_analysis, dict) else None
    if not isinstance(mechanism_formula_consistency, dict) or not mechanism_formula_consistency:
        mechanism_formula_consistency = validate_mechanism_formula_consistency(spec or canonical or {}, mechanism_analysis if isinstance(mechanism_analysis, dict) else {}, formula_specific_derivation)

    packet = {
        "contract_version": "factorforge_revision_council_packet_v1",
        "report_id": rid,
        "artifact_identity": iteration.get("artifact_identity") or case.get("artifact_identity") or run.get("artifact_identity") or {},
        "factor_formula": canonical.get("formula_text") or spec.get("formula_text") or nested(brief_json, "economic_interpretation").get("formula"),
        "implementation_mode": (iteration.get("artifact_identity") or {}).get("implementation_mode") or (run.get("artifact_identity") or {}).get("implementation_mode"),
        "mechanism_math_contract": (
            mechanism_math_for_packet(spec, case, handoff, memo)
        ),
        "formula_specific_derivation": formula_specific_derivation,
        "mechanism_formula_consistency": mechanism_formula_consistency,
        "main_agent_mechanism_memo_ref": relpath(paths["main_agent_mechanism_memo"]),
        "main_agent_formula_component_map": main_agent_memo.get("formula_component_map") or [],
        "main_agent_math_hypothesis": main_agent_memo.get("math_hypothesis") or {},
        "main_agent_evidence_comparison": main_agent_memo.get("evidence_comparison") or {},
        "council_required_critiques": [
            "critique formula component mapping",
            "critique selected mathematical model",
            "critique payer derivation",
            "critique evidence contradictions",
            "propose revision or kill recommendation",
        ],
        "research_memo": {
            "evidence_audit": memo.get("evidence_audit") or {},
            "mechanism_analysis": memo.get("mechanism_analysis") or {},
            "case_comparison": memo.get("case_comparison") or {},
            "revision_strategy": memo.get("revision_strategy") or {},
            "search_policy_decision": memo.get("search_policy_decision") or {},
        },
        "loop_research_brief": {
            "reference": brief_ref,
            "decision_snapshot": nested(brief_json, "decision_snapshot"),
            "mechanism_math_summary": brief_json.get("mechanism_math_summary") or {},
        },
        "metrics": metrics,
        "chart_evidence": brief_json.get("chart_evidence") or {},
        "program_search_policy": memo.get("search_policy_decision") or memo.get("program_search_policy") or {},
        "supplemental_research_context": supplemental_research_context(rid, spec, iteration),
        "source_paths": {key: str(value) for key, value in paths.items() if value.exists()},
        "forbidden_writeback_baseline": forbidden_writeback_baseline(rid),
    }

    out = OBJ / "research_iteration_master" / "revision_council" / rid / f"revision_council_packet__{rid}.json"
    write_json(out, packet)
    print(json.dumps({"status": "written", "path": str(out), "report_id": rid}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
