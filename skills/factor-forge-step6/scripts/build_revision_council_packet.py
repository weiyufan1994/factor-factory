#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
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
TOKEN_BRANCH_COMPARISON_MISSING = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_MISSING"
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


def collect_key_metrics(evaluation: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if isinstance(evaluation.get("key_metrics"), dict):
        metrics.update(evaluation["key_metrics"])
    for item in evaluation.get("backend_summary") or []:
        if isinstance(item, dict) and isinstance(item.get("key_metrics"), dict):
            metrics.update(item["key_metrics"])
    return metrics


def numeric_metric(metrics: dict[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


METRIC_ALIASES: dict[str, list[str]] = {
    "turnover": ["turnover", "turnover_mean", "long_side_turnover_mean_daily", "daily_turnover", "turnover_mean_daily"],
    "turnover_mean": ["turnover_mean", "turnover", "long_side_turnover_mean_daily", "daily_turnover", "turnover_mean_daily"],
    "long_side_turnover_mean_daily": ["long_side_turnover_mean_daily", "turnover_mean", "turnover", "daily_turnover", "turnover_mean_daily"],
    "trading_cogs_annual": ["trading_cogs_annual", "annual_cogs", "cogs_annual", "cost_annual", "annual_trading_cogs"],
    "long_side_max_drawdown": ["long_side_max_drawdown", "max_drawdown", "long_side_mdd", "mdd"],
    "long_side_recovery_days": ["long_side_recovery_days", "recovery_days", "long_side_recovery_time_days"],
}


def numeric_metric_any(metrics: dict[str, Any], key: str) -> float | None:
    for candidate in METRIC_ALIASES.get(key, [key]):
        value = numeric_metric(metrics, candidate)
        if value is not None:
            return value
    return None


def metric_delta(parent_metrics: dict[str, Any], child_metrics: dict[str, Any], key: str) -> dict[str, Any]:
    parent_value = numeric_metric_any(parent_metrics, key)
    child_value = numeric_metric_any(child_metrics, key)
    delta = None if parent_value is None or child_value is None else child_value - parent_value
    return {"parent": parent_value, "child": child_value, "delta": delta}


def load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return load_json(path)
    except Exception:
        return {}


def prior_revision_memory(report_id: str, spec: dict[str, Any], current_metrics: dict[str, Any]) -> dict[str, Any]:
    revision_identity = spec.get("revision_identity") if isinstance(spec.get("revision_identity"), dict) else {}
    revision_spec_ref = spec.get("executable_revision_spec_ref") or revision_identity.get("revision_spec_path")
    revision_spec_path = Path(str(revision_spec_ref)) if revision_spec_ref else Path("")
    if revision_spec_ref and not revision_spec_path.is_absolute():
        revision_spec_path = FF / revision_spec_path
    revision_spec = load_optional_json(revision_spec_path) if revision_spec_ref else {}
    parent_report_id = (
        revision_spec.get("parent_report_id")
        or revision_identity.get("parent_report_id")
        or spec.get("parent_report_id")
    )
    if not parent_report_id:
        return {
            "contract_version": "factorforge_prior_revision_memory_v1",
            "is_child_revision": False,
            "required_for_next_council": False,
        }

    parent_eval = load_optional_json(OBJ / "validation" / f"factor_evaluation__{parent_report_id}.json")
    parent_metrics = collect_key_metrics(parent_eval)
    deltas = {
        key: metric_delta(parent_metrics, current_metrics, key)
        for key in [
            "rank_ic_mean",
            "rank_ic_ir",
            "pearson_ic_mean",
            "long_side_annual_return",
            "cost_adjusted_annual_return",
            "long_side_sharpe",
            "turnover",
            "turnover_mean",
            "long_side_turnover_mean_daily",
            "trading_cogs_annual",
            "long_side_max_drawdown",
            "long_side_recovery_days",
        ]
    }
    rank_ic_delta = deltas["rank_ic_mean"].get("delta")
    cost_delta = deltas["cost_adjusted_annual_return"].get("delta")
    long_delta = deltas["long_side_annual_return"].get("delta")
    worsened = any(
        value is not None and value < 0
        for value in [rank_ic_delta, cost_delta, long_delta]
    )
    improved = any(
        value is not None and value > 0
        for value in [rank_ic_delta, cost_delta, long_delta]
    ) and not worsened
    outcome = "falsified" if worsened else ("improved" if improved else "inconclusive")
    derivation_rule = revision_spec.get("derivation_rule")
    parent_formula_hash = revision_spec.get("parent_formula_hash") or revision_identity.get("parent_formula_hash")
    child_formula_hash = revision_spec.get("child_formula_hash") or revision_identity.get("child_formula_hash")
    return {
        "contract_version": "factorforge_prior_revision_memory_v1",
        "is_child_revision": True,
        "required_for_next_council": True,
        "parent_report_id": parent_report_id,
        "child_report_id": report_id,
        "source_executable_revision_spec_path": str(revision_spec_path) if revision_spec_ref else None,
        "derivation_rule": derivation_rule,
        "parent_formula": revision_spec.get("parent_formula"),
        "child_formula": revision_spec.get("child_formula"),
        "parent_formula_hash": parent_formula_hash,
        "child_formula_hash": child_formula_hash,
        "metric_delta": deltas,
        "prior_revision_outcome": outcome,
        "falsified_revision": outcome == "falsified",
        "forbidden_repeat_revision_rules": [derivation_rule] if derivation_rule and outcome == "falsified" else [],
        "forbidden_repeat_formula_hashes": [
            item for item in [parent_formula_hash, child_formula_hash] if isinstance(item, str) and item
        ],
        "council_requirements": [
            "Explicitly state whether the previous executable revision was falsified, improved, or inconclusive.",
            "Do not repeat a falsified derivation rule or re-create an ancestor formula hash.",
            "Use parent-vs-child metric deltas as negative evidence before proposing the next executable law.",
        ],
    }


def executable_revision_spec_for_packet(spec: dict[str, Any]) -> tuple[Path | None, dict[str, Any]]:
    revision_identity = spec.get("revision_identity") if isinstance(spec.get("revision_identity"), dict) else {}
    revision_spec_ref = spec.get("executable_revision_spec_ref") or revision_identity.get("revision_spec_path")
    if not revision_spec_ref:
        return None, {}
    revision_spec_path = Path(str(revision_spec_ref)).expanduser()
    if not revision_spec_path.is_absolute():
        revision_spec_path = FF / revision_spec_path
    return revision_spec_path, load_optional_json(revision_spec_path)


def import_branch_comparison_validator():
    validator_path = REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "validate_branch_comparison.py"
    spec = importlib.util.spec_from_file_location("validate_branch_comparison", validator_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"{TOKEN_BRANCH_COMPARISON_MISSING}: cannot load branch comparison validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sibling_branch_memory(report_id: str, executable_spec: dict[str, Any]) -> dict[str, Any]:
    branch_group_id = str(executable_spec.get("branch_group_id") or nested(executable_spec, "branch_context").get("branch_group_id") or "")
    if not branch_group_id:
        return {
            "contract_version": "factorforge_sibling_branch_memory_v1",
            "required": False,
            "reason": "not_multibranch_child",
        }
    try:
        sibling_count = int(executable_spec.get("sibling_branch_count") or nested(executable_spec, "branch_context").get("sibling_branch_count") or 0)
    except (TypeError, ValueError):
        sibling_count = 0
    if sibling_count <= 1:
        return {
            "contract_version": "factorforge_sibling_branch_memory_v1",
            "required": False,
            "reason": "single_child_branch_group",
            "branch_group_id": branch_group_id,
        }
    parent_report_id = str(executable_spec.get("parent_report_id") or nested(executable_spec, "branch_context").get("parent_report_id") or "")
    if not parent_report_id:
        raise ValueError(f"{TOKEN_BRANCH_COMPARISON_MISSING}: parent_report_id missing for {report_id}")

    validator = import_branch_comparison_validator()
    comparison_dir = OBJ / "research_iteration_master"
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(comparison_dir.glob(f"branch_comparison__{parent_report_id}__loop*.json")):
        payload = load_optional_json(path)
        if payload.get("branch_group_id") != branch_group_id:
            continue
        failures = validator.validate_payload(payload)
        if failures:
            raise ValueError(f"{TOKEN_BRANCH_COMPARISON_MISSING}: invalid comparison {path}: {failures}")
        matches.append((path, payload))
    if not matches:
        raise ValueError(f"{TOKEN_BRANCH_COMPARISON_MISSING}: branch_group_id={branch_group_id}")
    comparison_path, comparison = matches[-1]
    selected = comparison.get("main_agent_selection") if isinstance(comparison.get("main_agent_selection"), dict) else {}
    children = comparison.get("children") if isinstance(comparison.get("children"), list) else []
    siblings: list[dict[str, Any]] = []
    current_branch: dict[str, Any] = {}
    forbidden_hashes: list[str] = []
    forbidden_rules: list[str] = []
    for raw in children:
        child = raw if isinstance(raw, dict) else {}
        child_id = str(child.get("child_report_id") or "")
        formula_hash = str(child.get("formula_hash") or "")
        law_id = str(child.get("law_id") or "")
        if child_id == report_id:
            current_branch = child
        else:
            siblings.append(
                {
                    "child_report_id": child_id,
                    "branch_role": child.get("branch_role"),
                    "law_id": law_id,
                    "formula_hash": formula_hash,
                    "branch_outcome": child.get("branch_outcome"),
                    "metric_delta_vs_parent": child.get("metric_delta_vs_parent") or {},
                }
            )
        if child.get("branch_outcome") == "falsified":
            if formula_hash:
                forbidden_hashes.append(formula_hash)
            if law_id:
                forbidden_rules.append(law_id)
    return {
        "contract_version": "factorforge_sibling_branch_memory_v1",
        "required": True,
        "branch_group_id": branch_group_id,
        "source_branch_comparison_path": str(comparison_path),
        "selected_current_child_report_id": report_id,
        "selected_next_parent_child_report_id": selected.get("selected_next_parent_child_report_id"),
        "current_branch": {
            "child_report_id": current_branch.get("child_report_id"),
            "branch_role": current_branch.get("branch_role"),
            "law_id": current_branch.get("law_id"),
            "formula_hash": current_branch.get("formula_hash"),
            "branch_outcome": current_branch.get("branch_outcome"),
            "metric_delta_vs_parent": current_branch.get("metric_delta_vs_parent") or {},
        },
        "siblings": siblings,
        "forbidden_repeat_sibling_formula_hashes": sorted(set(forbidden_hashes)),
        "forbidden_repeat_sibling_revision_rules": sorted(set(forbidden_rules)),
        "council_requirements": [
            "Compare the current selected branch against sibling branch outcomes before proposing another revision.",
            "Do not re-create a sibling formula hash or rejected sibling derivation law unless explicitly justified by new evidence.",
            "Preserve exploration learnings even when the next parent follows the exploit branch.",
        ],
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
    metrics = collect_key_metrics(evaluation)
    revision_memory = prior_revision_memory(rid, spec, metrics)
    _revision_spec_path, executable_spec = executable_revision_spec_for_packet(spec)
    try:
        sibling_memory = sibling_branch_memory(rid, executable_spec)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

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
        "prior_revision_memory": revision_memory,
        "sibling_branch_memory": sibling_memory,
        "main_agent_mechanism_memo_ref": relpath(paths["main_agent_mechanism_memo"]),
        "main_agent_formula_component_map": main_agent_memo.get("formula_component_map") or [],
        "main_agent_math_hypothesis": main_agent_memo.get("math_hypothesis") or {},
        "main_agent_evidence_comparison": main_agent_memo.get("evidence_comparison") or {},
        "council_required_critiques": [
            "critique formula component mapping",
            "critique selected mathematical model",
            "critique payer derivation",
            "critique evidence contradictions",
            "critique prior executable revision outcome and do not repeat falsified revision laws",
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
